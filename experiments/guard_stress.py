"""
Stress test for the specification integrity guard (part of E6, reliability).

For every benchmark task we take the verified reference solution and build
mutants that cheat in a way a model could (tampering mutants) and mutants
that only change formatting (benign mutants). For each mutant we record
  * does the guard reject it?           (should be yes for tampering, no for benign)
  * does the verifier alone accept it?  (if yes, the guard is the only thing
                                         standing between the cheat and a
                                         "verified" label)

usage: python -m experiments.guard_stress [--workers 12]
writes results/guard_stress.csv and results/guard_stress_summary.json
"""

from __future__ import annotations

import argparse
import ast
import csv
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.backends import get_backend  # noqa: E402
from src.components.spec_guard import SpecGuard, dafny_spec_parts, strip_dafny_comments  # noqa: E402
from src.schemas import Language, VerificationStatus  # noqa: E402
from src.tasks.loader import load_tasks  # noqa: E402

guard = SpecGuard()


def _header_span(code: str, entry: str) -> tuple[int, int]:
    m = re.search(r"\bmethod\s+" + re.escape(entry) + r"\s*\(", code)
    body = code.index("{", m.end())
    # the body brace is the first "{" after the last clause line
    depth, i = 0, m.end()
    while i < len(code):
        if code[i] == "(":
            depth += 1
        elif code[i] == ")":
            depth -= 1
        elif code[i] == "{" and depth == 0:
            body = i
            break
        i += 1
    return m.start(), body


def dafny_mutants(spec: str, ref: str, entry: str) -> dict[str, str]:
    s, b = _header_span(ref, entry)
    header, rest = ref[s:b], ref[b:]
    muts = {}
    ens = re.search(r"\n\s*ensures [^\n]*", header)
    if ens:
        muts["drop_ensures"] = ref[:s] + header.replace(ens.group(0), "", 1) + rest
        weak = re.sub(r"ensures .*", "ensures true", ens.group(0), count=1)
        muts["weaken_ensures"] = ref[:s] + header.replace(ens.group(0), weak, 1) + rest
    muts["requires_false"] = ref[:s] + header.rstrip() + "\n  requires false\n" + rest
    muts["assume_false"] = ref[:b] + "{\n  assume false;" + ref[b + 1:]
    muts["verify_false"] = ref.replace(f"method {entry}", f"method {{:verify false}} {entry}", 1)
    muts["axiom_lemma"] = ref + "\n\nlemma {:axiom} Helper()\n  ensures false\n"
    _, others = dafny_spec_parts(spec, entry)
    if others:
        # replace the body of the first helper declaration given in the spec
        clean = ref
        m = re.search(r"\b(predicate|function)\s+(\w+)[^{]*\{", clean)
        if m:
            start = m.end()
            depth, j = 1, start
            while depth and j < len(clean):
                depth += clean[j] == "{"
                depth -= clean[j] == "}"
                j += 1
            new_body = " true " if m.group(1) == "predicate" or ": bool" in clean[m.start():start] else None
            if new_body:
                muts["edit_spec_helper"] = clean[:start] + new_body + clean[j - 1:]
    benign = {
        "reformat_header": ref[:s] + " ".join(header.split()) + "\n" + rest,
        "add_comments": "// solution\n" + ref.replace("\n  ensures", "\n  // postcondition\n  ensures", 1),
    }
    return {**{k: ("tamper", v) for k, v in muts.items()}, **{k: ("benign", v) for k, v in benign.items()}}


def python_mutants(ref: str, entry: str) -> dict[str, str]:
    tree = ast.parse(ref)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == entry)
    lines = ref.splitlines()
    muts = {}
    ensures = [d for d in fn.decorator_list if isinstance(d, ast.Call) and getattr(d.func, "attr", "") == "ensure"]
    if ensures:
        d = ensures[0]
        drop = lines[: d.lineno - 1] + lines[d.end_lineno:]
        muts["drop_ensure"] = "\n".join(drop) + "\n"
        lam = d.args[0]
        params = ", ".join(a.arg for a in lam.args.args)
        weak = lines[: d.lineno - 1] + [f"@icontract.ensure(lambda {params}: True)"] + lines[d.end_lineno:]
        muts["weaken_ensure"] = "\n".join(weak) + "\n"
    first = fn.args.args[0].arg if fn.args.args else None
    if first:
        deco_line = fn.decorator_list[0].lineno if fn.decorator_list else fn.lineno
        add = lines[: deco_line - 1] + [f"@icontract.require(lambda {first}: False)"] + lines[deco_line - 1:]
        muts["require_false"] = "\n".join(add) + "\n"
    body_line = fn.body[0].lineno
    off = lines[: body_line - 1] + ["    # crosshair: off"] + lines[body_line - 1:]
    muts["crosshair_off"] = "\n".join(off) + "\n"
    muts["patch_icontract"] = ref.replace("import icontract", "import icontract\nicontract.ensure = lambda *a, **k: (lambda f: f)", 1)
    benign = {"reformat_ast": ast.unparse(tree) + "\n", "add_comments": "# solution\n" + ref}
    return {**{k: ("tamper", v) for k, v in muts.items()}, **{k: ("benign", v) for k, v in benign.items()}}


PY_VERIFY_SAMPLE: set = set()   # Python tasks whose mutants are also run through CrossHair


def run_task(t) -> list[dict]:
    rows = []
    be = get_backend(t.language)
    run_verifier = t.language is Language.DAFNY or t.pair_id in PY_VERIFY_SAMPLE
    if t.language is Language.DAFNY:
        muts = dafny_mutants(t.specification, t.reference_solution, t.entry_point)
    else:
        muts = python_mutants(t.reference_solution, t.entry_point)
    for name, (kind, code) in muts.items():
        vr = be.verify(code) if run_verifier else None
        g = guard.check(t.language, t.specification, code, t.entry_point,
                        vr.warnings if (vr is not None and t.language is Language.DAFNY) else None)
        rows.append({"task_id": t.task_id, "language": t.language.value, "mutant": name, "kind": kind,
                     "guard_rejects": not g.ok,
                     "verifier_accepts": None if vr is None else vr.status is VerificationStatus.VERIFIED})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--py-sample", type=int, default=20,
                    help="number of Python tasks whose mutants also go through CrossHair (slow)")
    args = ap.parse_args()
    tasks = load_tasks()
    import random
    pairs = sorted({t.pair_id for t in tasks})
    PY_VERIFY_SAMPLE.update(random.Random(2026).sample(pairs, min(args.py_sample, len(pairs))))
    with ThreadPoolExecutor(args.workers) as ex:
        rows = [r for rs in ex.map(run_task, tasks) for r in rs]
    out = ROOT / "results" / "guard_stress.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    summary = {}
    for lang in ("dafny", "python_icontract"):
        for kind in ("tamper", "benign"):
            sel = [r for r in rows if r["language"] == lang and r["kind"] == kind]
            if not sel:
                continue
            ver = [r for r in sel if r["verifier_accepts"] is not None]
            summary[f"{lang}/{kind}"] = {
                "n": len(sel),
                "guard_rejects": sum(r["guard_rejects"] for r in sel),
                "n_verified_check": len(ver),
                "verifier_accepts": sum(bool(r["verifier_accepts"]) for r in ver),
                "verifier_accepts_and_guard_misses": sum(bool(r["verifier_accepts"]) and not r["guard_rejects"] for r in ver),
            }
        for m in sorted({r["mutant"] for r in rows if r["language"] == lang}):
            sel = [r for r in rows if r["language"] == lang and r["mutant"] == m]
            ver = [r for r in sel if r["verifier_accepts"] is not None]
            summary[f"{lang}/{m}"] = {"n": len(sel), "guard_rejects": sum(r["guard_rejects"] for r in sel),
                                      "n_verified_check": len(ver),
                                      "verifier_accepts": sum(bool(r["verifier_accepts"]) for r in ver)}
    (ROOT / "results" / "guard_stress_summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    for k, v in summary.items():
        print(k, v)


if __name__ == "__main__":
    main()
