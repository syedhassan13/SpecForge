"""
Differential test of the Dafny and Python reference solutions.

For every admitted task we generate random inputs from the neutral types,
keep those that satisfy the Python precondition (iContract raises on a
violated precondition), run BOTH references on the same inputs and compare
the outputs. Together with the shared tests and the spec probes in
validate_tasks.py this is our evidence that the two versions of a task are
the same problem.

Inputs are generated with a fixed seed; a few structured generators (sorted
lists, lists with duplicates, small ranges) raise the share of inputs that
pass typical preconditions such as "sorted" or "non-empty".

usage: python data/scripts/check_equivalence.py [--n 40] [--ids vb_001 ...]
"""

from __future__ import annotations

import argparse
import ast
import copy
import json
import os
import random
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.backends import DafnyBackend  # noqa: E402
from src.tasks.types import NType, parse_type, python_literal  # noqa: E402

TASKS = ROOT / "data" / "tasks"
OUT = ROOT / "data" / "equivalence_report.json"
CHARS = "abcxyzABZ019 ,.!:-"


def gen(t: NType, rng: random.Random, style: int):
    if t.kind == "int":
        return rng.randint(-6, 6) if style % 2 else rng.randint(-50, 50)
    if t.kind == "nat":
        return rng.randint(0, 6) if style % 2 else rng.randint(0, 40)
    if t.kind == "bool":
        return rng.random() < 0.5
    if t.kind == "char":
        return rng.choice(CHARS)
    if t.kind == "string":
        return "".join(rng.choice(CHARS) for _ in range(rng.randint(0, 8)))
    if t.kind == "list":
        n = rng.randint(0, 7) if style != 3 else rng.randint(1, 7)
        xs = [gen(t.args[0], rng, style) for _ in range(n)]
        if style == 2 and all(isinstance(x, int) for x in xs):
            xs.sort()
        if style == 4 and xs:
            xs = [xs[0]] * len(xs)
        return xs
    if t.kind == "tuple":
        return [gen(a, rng, style) for a in t.args]
    raise ValueError(t)


def _pre_only_source(task: dict) -> str:
    """Copy of the target function that keeps only the @icontract.require decorators."""
    tree = ast.parse(task["python"]["reference"])
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == task["entry_point"])
    pre = copy.deepcopy(fn)
    pre.name = "__pre_only"
    pre.decorator_list = [d for d in pre.decorator_list
                          if not (isinstance(d, ast.Call) and getattr(d.func, "attr", "") == "ensure")]
    pre.body = [ast.Return(value=ast.Constant(None))]
    return ast.unparse(ast.fix_missing_locations(ast.Module(body=[pre], type_ignores=[])))


def python_outputs(task: dict, inputs: list[dict]) -> list:
    """Run the Python reference; None marks a precondition violation."""
    ptypes = [(p["name"], parse_type(p["type"])) for p in task["params"]]
    entry = task["entry_point"]
    lines = ["def __main():", "    out = []"]
    for inp in inputs:
        kw = ", ".join(f"{n}={python_literal(inp[n], t)}" for n, t in ptypes)
        lines += [
            "    try:",
            f"        __pre_only({kw})",
            "    except icontract.ViolationError:",
            "        out.append(['pre', None])",
            "    else:",
            "        try:",
            f"            out.append(['ok', {entry}({kw})])",
            "        except Exception as e:",
            "            out.append(['crash', type(e).__name__])",
        ]
    lines += ["    print('EQUIV ' + __j.dumps(out, default=list))", "", "__main()", ""]
    src = "\n\n".join([task["python"]["reference"], _pre_only_source(task), "import json as __j",
                       "\n".join(lines)])
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "ref.py")
        Path(p).write_text(src, encoding="utf-8")
        proc = subprocess.run([sys.executable, p], capture_output=True, text=True, timeout=120)
    line = next((l for l in proc.stdout.splitlines() if l.startswith("EQUIV ")), None)
    if line is None:
        raise RuntimeError(proc.stderr[-300:])
    norm = []
    for kind, val in json.loads(line[6:]):
        norm.append(_jsonable(val) if kind == "ok" else (None if kind == "pre" else f"<{kind}>"))
    return norm


def _jsonable(v):
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    return v


def precondition_filter(task: dict, inputs: list[dict]) -> list[dict]:
    """Keep inputs that satisfy the precondition (decided by iContract)."""
    outs = python_outputs(task, inputs)
    return [i for i, o in zip(inputs, outs) if o is not None]


def check_task(path: Path, n: int, seed: int) -> dict:
    task = json.loads(path.read_text(encoding="utf-8"))
    rng = random.Random(f"{seed}:{task['task_id']}")
    ptypes = [(p["name"], parse_type(p["type"])) for p in task["params"]]
    pool = []
    for k in range(n * 6):
        style = k % 5
        pool.append({name: gen(t, rng, style) for name, t in ptypes})
    # dedupe, then keep inputs that pass the precondition
    seen, uniq = set(), []
    for x in pool:
        key = json.dumps(x, sort_keys=True)
        if key not in seen:
            seen.add(key)
            uniq.append(x)
    try:
        valid = precondition_filter(task, uniq)[:n]
    except Exception as e:  # noqa: BLE001
        return {"task_id": task["task_id"], "error": f"python reference failed: {e}"}
    if not valid:
        return {"task_id": task["task_id"], "inputs": 0, "agree": 0, "note": "no random input met the precondition"}
    py = python_outputs(task, valid)
    cases = [{"input": i, "expected": None} for i in valid]
    # run the Dafny reference; we compare printed values against the Python outputs
    dfy = DafnyBackend()
    cases = [{"input": i, "expected": o if not isinstance(o, str) or not o.startswith("<") else None}
             for i, o in zip(valid, py)]
    usable = [c for c in cases if c["expected"] is not None]
    tr = dfy.run_tests(task["dafny"]["reference"], task["entry_point"], task["params"], task["returns"], usable)
    disagreements = [f for f in tr.failures][:3]
    return {"task_id": task["task_id"], "inputs": len(usable), "agree": tr.passed,
            "python_crashes": len(cases) - len(usable), "disagreements": disagreements}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--ids", nargs="*")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    files = sorted(TASKS.glob("*.json"))
    if args.ids:
        files = [f for f in files if f.stem in set(args.ids)]
    with ThreadPoolExecutor(args.workers) as ex:
        rows = list(ex.map(lambda f: check_task(f, args.n, args.seed), files))
    total_in = sum(r.get("inputs", 0) for r in rows)
    total_ok = sum(r.get("agree", 0) for r in rows)
    for r in rows:
        if r.get("error") or r.get("disagreements") or r.get("python_crashes"):
            print(r)
    print(f"{len(rows)} tasks, {total_in} random inputs, {total_ok} agreements "
          f"({100 * total_ok / max(total_in, 1):.1f}%)")
    if not args.ids:
        OUT.write_text(json.dumps({"seed": args.seed, "n_per_task": args.n, "tasks": rows,
                                   "total_inputs": total_in, "total_agree": total_ok}, indent=1),
                       encoding="utf-8")


if __name__ == "__main__":
    main()
