"""
SpecLoop command line interface.

  python specloop.py solve vb_051 --language dafny --model gpt-4o-mini
  python specloop.py solve vb_051 --language python --mode testing_only --no-router
  python specloop.py run experiments/configs/E3_proposed.json --workers 12
  python specloop.py analyze
  python specloop.py validate --ids vb_051
  python specloop.py tasks --split dev

`solve` runs the agent on one task and prints the trajectory (states, tool
calls, routed feedback, decisions) followed by the oracle's verdict.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.agents.controller import AgentConfig, SpecLoopAgent  # noqa: E402
from src.providers import LLMCache, create_provider  # noqa: E402
from src.schemas import AgentMode, Language  # noqa: E402
from src.tasks.loader import TASK_DIR, load_split, load_task_file  # noqa: E402


def cmd_solve(a):
    path = TASK_DIR / f"{a.task}.json"
    lang = Language.DAFNY if a.language == "dafny" else Language.PYTHON_ICONTRACT
    task = next(t for t in load_task_file(path) if t.language is lang)
    cfg = AgentConfig(mode=AgentMode(a.mode), max_attempts=a.max_attempts, normalizer=not a.no_normalizer,
                      router=not a.no_router, guard=not a.no_guard, stagnation=not a.no_stagnation,
                      name=f"cli_{a.mode}")
    provider = create_provider(a.model, cache=LLMCache(ROOT / "cache" / "llm_cache.sqlite"))
    print(f"task {task.task_id} ({task.entry_point}), model {a.model}, mode {a.mode}\n")
    res, traj = SpecLoopAgent(provider, cfg, seed=a.seed).run(task)
    for e in traj.events:
        t = f"[{e['t']:6.1f}s]"
        if e["type"] == "state":
            print(f"{t} == {e['to']}" + (f" (attempt {e['attempt']})" if "attempt" in e else ""))
        elif e["type"] == "llm":
            print(f"{t}    llm {e['purpose']}: {e['prompt_tokens']}+{e['completion_tokens']} tokens"
                  f"{' (cached)' if e['cached'] else ''}")
            if e.get("analysis"):
                print(f"           model says: {e['analysis'][:200]}")
        elif e["type"] == "tool":
            extra = {k: e[k] for k in ("status", "ok", "passed", "total", "kinds") if k in e}
            print(f"{t}    tool {e['tool']}: {extra}")
        elif e["type"] == "feedback":
            print(f"{t}    router -> {e['failure_class']}")
            if a.verbose:
                print("           " + e["text"].replace("\n", "\n           "))
        elif e["type"] == "decision":
            print(f"{t}    decision: {e['what']} ({e['reason']})")
        elif e["type"] == "oracle":
            print(f"{t}    oracle: intact={e['spec_intact']} verified={e['verified']} "
                  f"tests={e['tests_passed']}/{e['tests_total']} -> {'CORRECT' if e['correct'] else 'not correct'}")
    print(f"\nresult: {'CORRECT' if res.correct else 'NOT CORRECT'} after {res.attempts} attempt(s), "
          f"stop={res.stop_reason}, cost ${res.cost_usd:.4f}")
    if a.show_code:
        print("\nfinal program:\n" + res.final_code)
    if a.trace:
        Path(a.trace).write_text(json.dumps(traj.to_dict(), indent=1), encoding="utf-8")
        print(f"trajectory written to {a.trace}")


def cmd_tasks(a):
    ids = load_split(a.split) if a.split else sorted(p.stem for p in TASK_DIR.glob("*.json"))
    for pid in ids:
        d = json.loads((TASK_DIR / f"{pid}.json").read_text(encoding="utf-8"))
        print(f"{pid}  {d['entry_point']:<32} {d['verina_id']:<18} {len(d['tests'])} tests")
    print(f"{len(ids)} tasks")


def main():
    ap = argparse.ArgumentParser(description="SpecLoop: verification-feedback agent for LLM code generation")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("solve", help="run the agent on one task and print its trajectory")
    s.add_argument("task", help="task id, e.g. vb_051")
    s.add_argument("--language", choices=["dafny", "python"], default="dafny")
    s.add_argument("--model", default="gpt-4o-mini")
    s.add_argument("--mode", default="combined", choices=[m.value for m in AgentMode])
    s.add_argument("--max-attempts", type=int, default=5)
    s.add_argument("--seed", type=int, default=0)
    for flag in ("no-normalizer", "no-router", "no-guard", "no-stagnation"):
        s.add_argument(f"--{flag}", action="store_true")
    s.add_argument("--verbose", action="store_true", help="print the full feedback messages")
    s.add_argument("--show-code", action="store_true")
    s.add_argument("--trace", help="write the trajectory JSON to this file")
    r = sub.add_parser("run", help="run an experiment config (see experiments/configs)")
    r.add_argument("rest", nargs=argparse.REMAINDER)
    sub.add_parser("analyze", help="rebuild tables, figures and results/summary.json")
    v = sub.add_parser("validate", help="validate benchmark tasks")
    v.add_argument("rest", nargs=argparse.REMAINDER)
    t = sub.add_parser("tasks", help="list tasks")
    t.add_argument("--split", choices=["dev", "test"])
    a = ap.parse_args()
    if a.cmd == "solve":
        cmd_solve(a)
    elif a.cmd == "run":
        sys.exit(subprocess.call([sys.executable, "-m", "experiments.run", *a.rest], cwd=ROOT))
    elif a.cmd == "analyze":
        sys.exit(subprocess.call([sys.executable, "-m", "experiments.analyze"], cwd=ROOT))
    elif a.cmd == "validate":
        sys.exit(subprocess.call([sys.executable, "data/scripts/validate_tasks.py", *a.rest], cwd=ROOT))
    elif a.cmd == "tasks":
        cmd_tasks(a)


if __name__ == "__main__":
    main()
