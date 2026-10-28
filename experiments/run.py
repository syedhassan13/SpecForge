"""
Run one experiment configuration.

    python -m experiments.run experiments/configs/E3_proposed.json
    python -m experiments.run experiments/configs/E1_baseline.json --models gpt-4o-mini --workers 8
    python -m experiments.run experiments/configs/E3_proposed.json --offline   # replay from the LLM cache

Results go to results/raw/<experiment>/ and trajectories to
logs/trajectories/<experiment>/. Runs are resumable. After running, build
tables and figures with `python -m experiments.analyze`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.agents.controller import AgentConfig  # noqa: E402
from src.evaluation.verina_protocol import run_verina_protocol  # noqa: E402
from src.pipeline import Runner, RunSpec  # noqa: E402
from src.providers import LLMCache, create_provider  # noqa: E402
from src.schemas import AgentMode, Language  # noqa: E402
from src.tasks.loader import load_split, load_tasks  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    ap.add_argument("--models", nargs="*", help="override the model list")
    ap.add_argument("--seeds", nargs="*", type=int)
    ap.add_argument("--only", nargs="*", help="run only these config names")
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--budget", type=float, default=2.0, help="global USD cap, includes earlier spend")
    ap.add_argument("--limit", type=int, help="first N pairs only (smoke runs)")
    ap.add_argument("--offline", action="store_true", help="cache replay only, no API calls")
    ap.add_argument("--reuse-first-attempt", metavar="RESULTS_JSONL",
                    help="skip (task, seed) units that this full-system run solved with its first "
                         "candidate; every combined-mode ablation would stop at the same candidate "
                         "with the same verdict, so the analysis reuses that row")
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    langs = [Language(l) for l in cfg["languages"]]
    pair_ids = load_split(cfg["split"])
    if args.limit:
        pair_ids = pair_ids[: args.limit]
    tasks = load_tasks(languages=langs, pair_ids=pair_ids)
    models = args.models or cfg["models"]
    print(f"{cfg['experiment']}: {len(tasks)} task instances ({len(pair_ids)} pairs), models {models}")

    if cfg["experiment"].startswith("E2"):
        cache = LLMCache(ROOT / "cache" / "llm_cache.sqlite")
        dev = load_tasks(split="dev")
        shots = {lang: [t for t in dev if t.language is lang][:2] for lang in langs}
        for m in models:
            prov = create_provider(m, cache=cache, offline=args.offline)
            out = ROOT / "results" / "raw" / cfg["experiment"] / f"verina_protocol__{m.replace(':', '_').replace('/', '_')}.jsonl"
            rows = run_verina_protocol(prov, tasks, shots, out, samples=cfg["samples"],
                                       temperature=cfg["temperature"], workers=args.workers,
                                       budget=args.budget, cache=cache)
            print(f"  {m}: {len(rows)} new samples -> {out.relative_to(ROOT)}")
        return

    runner = Runner(workers=args.workers, budget_usd=args.budget, offline=args.offline)
    if args.reuse_first_attempt:
        base = [json.loads(l) for l in open(args.reuse_first_attempt, encoding="utf-8") if l.strip()]
        runner.skip_units = {(r["task_id"], r["seed"]) for r in base
                             if r["attempts"] == 1 and r["stop_reason"] == "mode_success"}
        print(f"reusing {len(runner.skip_units)} first-attempt units from {args.reuse_first_attempt}")
    seeds = args.seeds if args.seeds is not None else cfg["seeds"]
    for c in cfg["configs"]:
        if args.only and c["name"] not in args.only:
            continue
        ac = AgentConfig(mode=AgentMode(c["mode"]), name=c["name"],
                         **{k: v for k, v in c.items() if k not in ("name", "mode")})
        for m in models:
            runner.run(RunSpec(cfg["experiment"], ac, m, seeds), tasks)
    print(f"total spent this invocation: ${runner.spent:.2f}")


if __name__ == "__main__":
    main()
