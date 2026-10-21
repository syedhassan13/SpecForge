"""
Validate benchmark tasks (data/tasks/*.json).

A task is only admitted to the benchmark if, in BOTH languages:
  1. the reference solution passes the integrity guard against the spec,
  2. the reference verifies (Dafny proof / CrossHair finds no counterexample),
  3. the reference passes every test case,
  4. the unimplemented stub is rejected (so the spec is not vacuous),
  5. spec probes: for every test input the spec ACCEPTS the expected output
     and REJECTS VERINA's known-wrong outputs ("unexpected" values).

Check 5 is how we argue that the Dafny and Python specs say the same thing:
both are probed with the same concrete input/output pairs.

usage: python data/scripts/validate_tasks.py [--ids vb_001 vb_002 ...] [--workers 8]
"""

from __future__ import annotations

import argparse
import ast
import copy
import json
import re
import subprocess
import sys
import tempfile
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.backends import DafnyBackend, PythonContractBackend  # noqa: E402
from src.components.spec_guard import (SpecGuard, dafny_spec_parts,  # noqa: E402
                                       strip_dafny_comments)
from src.schemas import Language, TestStatus, VerificationStatus  # noqa: E402
from src.tasks.loader import load_task_file  # noqa: E402
from src.tasks.types import check_value, dafny_literal, parse_type, python_literal  # noqa: E402

TASKS = ROOT / "data" / "tasks"
REPORT = ROOT / "data" / "validation_report.json"
REQUIRED = ["task_id", "verina_id", "entry_point", "description", "params", "returns",
            "tests", "dafny", "python"]

dafny = DafnyBackend()
python = PythonContractBackend()
guard = SpecGuard()


# ---------------------------------------------------------------------------
# spec probes
# ---------------------------------------------------------------------------

def _probe_pairs(task: dict) -> list[tuple[int, object, bool]]:
    """(test index, output value, should_be_accepted)"""
    pairs = []
    for i, t in enumerate(task["tests"]):
        pairs.append((i, t["expected"], True))
        for u in t.get("unexpected", [])[:4]:
            pairs.append((i, u, False))
    return pairs


def dafny_probes(task: dict) -> dict:
    spec = strip_dafny_comments(task["dafny"]["spec"])
    entry = task["entry_point"]
    header, others = dafny_spec_parts(spec, entry)
    m = re.search(r"\breturns\s*\(\s*(\w+)\s*:", header)
    if not m:
        return {"error": "could not find returns clause"}
    out_name = m.group(1)
    # position right after the closing paren of `returns (...)`
    i, depth = header.find("(", m.start()), 0
    for j in range(i, len(header)):
        depth += header[j] == "("
        depth -= header[j] == ")"
        if depth == 0:
            cut = j + 1
            break
    sig, clauses = header[:cut], header[cut:]
    sig = re.sub(r"\bmethod\s+" + re.escape(entry) + r"\b", "method {NAME}", sig, count=1)
    ptypes = [(p["name"], parse_type(p["type"])) for p in task["params"]]
    rt = parse_type(task["returns"])
    text = "\n\n".join(others) + "\n\n"
    owner = {}
    pairs = _probe_pairs(task)
    for k, (ti, val, _) in enumerate(pairs):
        pins = " ".join(f"requires {n} == {dafny_literal(task['tests'][ti]['input'][n], t)}"
                        for n, t in ptypes)
        start = text.count("\n") + 1
        text += (sig.replace("{NAME}", f"Probe_{k}") + f" {pins} {clauses}\n"
                 f"{{\n  {out_name} := {dafny_literal(val, rt)};\n}}\n\n")
        for ln in range(start, text.count("\n") + 1):
            owner[ln] = k
    program = text
    vr = dafny.verify(program)
    if vr.status is VerificationStatus.TIMEOUT:
        return {"error": "probe verification timed out"}
    if "parse errors" in vr.raw_output or "resolution/type errors" in vr.raw_output:
        return {"error": "probe program did not resolve: " + "; ".join(vr.errors[:3])}
    failed = set()
    for e in vr.errors:
        mm = re.match(r"line (\d+): Error", e)
        if mm and int(mm.group(1)) in owner:
            failed.add(owner[int(mm.group(1))])
    acc_ok = sum(1 for k, (_, _, good) in enumerate(pairs) if good and k not in failed)
    acc_n = sum(1 for _, _, good in pairs if good)
    rej_ok = sum(1 for k, (_, _, good) in enumerate(pairs) if not good and k in failed)
    rej_n = sum(1 for _, _, good in pairs if not good)
    return {"accept": [acc_ok, acc_n], "reject": [rej_ok, rej_n]}


def python_probes(task: dict) -> dict:
    spec = task["python"]["spec"]
    entry = task["entry_point"]
    tree = ast.parse(spec)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == entry)
    rt = parse_type(task["returns"])
    ptypes = [(p["name"], parse_type(p["type"])) for p in task["params"]]
    pairs = _probe_pairs(task)
    body = [n for n in tree.body if n is not fn]
    calls = []
    for k, (ti, val, _) in enumerate(pairs):
        f = copy.deepcopy(fn)
        f.name = f"__probe_{k}"
        f.body = [ast.parse(f"return {python_literal(val, rt)}").body[0]]
        body.append(f)
        kw = ", ".join(f"{n}={python_literal(task['tests'][ti]['input'][n], t)}" for n, t in ptypes)
        calls.append(f"    try:\n        __probe_{k}({kw})\n        print('PROBE', {k}, 'accept')\n"
                     f"    except icontract.ViolationError:\n        print('PROBE', {k}, 'reject')\n"
                     f"    except Exception as e:\n        print('PROBE', {k}, 'crash')")
    mod = ast.Module(body=body, type_ignores=[])
    src = ast.unparse(ast.fix_missing_locations(mod))
    src = "import icontract\n" + src + "\n\ndef __main():\n" + "\n".join(calls) + "\n\n__main()\n"
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "probe.py")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(src)
        proc = subprocess.run([sys.executable, p], capture_output=True, text=True, timeout=60)
    res = {}
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0] == "PROBE":
            res[int(parts[1])] = parts[2]
    if not res:
        return {"error": "probe script failed: " + proc.stderr[-300:]}
    acc_ok = sum(1 for k, (_, _, g) in enumerate(pairs) if g and res.get(k) == "accept")
    acc_n = sum(1 for _, _, g in pairs if g)
    # a postcondition that crashes on a wrong value (e.g. index error) also rejects it
    rej_ok = sum(1 for k, (_, _, g) in enumerate(pairs) if not g and res.get(k) in ("reject", "crash"))
    rej_n = sum(1 for _, _, g in pairs if not g)
    return {"accept": [acc_ok, acc_n], "reject": [rej_ok, rej_n]}


# ---------------------------------------------------------------------------

def validate_language(task_json: dict, ts) -> dict:
    lang = ts.language
    be = dafny if lang is Language.DAFNY else python
    r: dict = {}
    try:
        g = guard.check(lang, ts.specification, ts.reference_solution, ts.entry_point)
        r["guard_ok"] = g.ok
        if not g.ok:
            r["guard_violations"] = g.violations
    except Exception as e:  # noqa: BLE001
        r["guard_ok"] = False
        r["guard_violations"] = [f"guard crashed: {e}"]
    vr = be.verify(ts.reference_solution)
    if lang is Language.DAFNY:
        g2 = guard.check(lang, ts.specification, ts.reference_solution, ts.entry_point, vr.warnings)
        r["guard_ok"] = r["guard_ok"] and g2.ok
    r["verified"] = vr.status is VerificationStatus.VERIFIED
    if not r["verified"]:
        r["verify_errors"] = vr.errors[:5]
    tr = be.run_tests(ts.reference_solution, ts.entry_point, ts.params, ts.returns, ts.tests)
    r["tests"] = [tr.passed, tr.total]
    if tr.status is not TestStatus.PASSED:
        r["test_failures"] = tr.failures[:5]
    svr = be.verify(ts.specification)
    str_ = be.run_tests(ts.specification, ts.entry_point, ts.params, ts.returns, ts.tests)
    r["stub_rejected"] = not (svr.status is VerificationStatus.VERIFIED and str_.status is TestStatus.PASSED)
    try:
        r["probes"] = dafny_probes(task_json) if lang is Language.DAFNY else python_probes(task_json)
    except Exception as e:  # noqa: BLE001
        r["probes"] = {"error": f"probe crashed: {e}"}
    p = r["probes"]
    # "probe_exempt" lets a task document a probe the verifier cannot decide
    # (e.g. a recursive spec function on a long literal); it is reported, not hidden
    exempt = task_json.get("probe_exempt", {}).get(lang.short, {})
    probes_ok = "error" not in p and \
        (p["accept"][0] == p["accept"][1] or "accept" in exempt) and \
        (p["reject"][0] == p["reject"][1] or "reject" in exempt)
    if exempt:
        r["probe_exempt"] = exempt
    r["ok"] = bool(r["guard_ok"] and r["verified"] and tr.status is TestStatus.PASSED
                   and r["stub_rejected"] and probes_ok)
    return r


def validate_file(path: Path) -> dict:
    out = {"file": path.name}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        missing = [k for k in REQUIRED if k not in data]
        if missing:
            return {**out, "ok": False, "error": f"missing fields {missing}"}
        for p in data["params"]:
            parse_type(p["type"])
        rt = parse_type(data["returns"])
        for t in data["tests"]:
            for p in data["params"]:
                if not check_value(t["input"][p["name"]], parse_type(p["type"])):
                    return {**out, "ok": False, "error": f"bad test input for {p['name']}"}
            if not check_value(t["expected"], rt):
                return {**out, "ok": False, "error": "bad expected value"}
        if "// IMPLEMENT HERE" not in data["dafny"]["spec"]:
            return {**out, "ok": False, "error": "dafny spec must contain // IMPLEMENT HERE"}
        if "# IMPLEMENT HERE" not in data["python"]["spec"]:
            return {**out, "ok": False, "error": "python spec must contain # IMPLEMENT HERE"}
        ts_d, ts_p = load_task_file(path)
    except Exception as e:  # noqa: BLE001
        return {**out, "ok": False, "error": f"could not load: {e}"}
    out["task_id"] = data["task_id"]
    out["dafny"] = validate_language(data, ts_d)
    out["python"] = validate_language(data, ts_p)
    out["ok"] = out["dafny"]["ok"] and out["python"]["ok"]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", nargs="*", help="task ids (file stems) to validate")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--no-report", action="store_true", help="do not update the report file")
    args = ap.parse_args()
    files = sorted(TASKS.glob("*.json"))
    if args.ids:
        files = [f for f in files if f.stem in set(args.ids)]
    with ThreadPoolExecutor(args.workers) as ex:
        results = list(ex.map(validate_file, files))
    for r in results:
        flag = "OK  " if r["ok"] else "FAIL"
        if "error" in r:
            print(f"{flag} {r['file']}: {r['error']}")
            continue
        def brief(x):
            p = x["probes"]
            ps = p["error"] if "error" in p else \
                f"acc {p['accept'][0]}/{p['accept'][1]} rej {p['reject'][0]}/{p['reject'][1]}"
            return (f"guard={x['guard_ok']} ver={x['verified']} tests={x['tests'][0]}/{x['tests'][1]} "
                    f"stub_rej={x['stub_rejected']} probes[{ps}]")
        print(f"{flag} {r['file']}\n   dafny : {brief(r['dafny'])}\n   python: {brief(r['python'])}")
        for lang in ("dafny", "python"):
            for k in ("guard_violations", "verify_errors", "test_failures"):
                if k in r[lang]:
                    print(f"   {lang}.{k}: {r[lang][k]}")
    if not args.no_report:
        old = {}
        if REPORT.exists():
            old = {x["file"]: x for x in json.load(open(REPORT, encoding="utf-8"))}
        for r in results:
            old[r["file"]] = r
        with open(REPORT, "w", encoding="utf-8") as f:
            json.dump([old[k] for k in sorted(old)], f, indent=1)
    n_ok = sum(r["ok"] for r in results)
    print(f"\n{n_ok}/{len(results)} tasks valid")


if __name__ == "__main__":
    main()
