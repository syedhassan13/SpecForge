"""
Experiment runner.

A run unit is (task, agent configuration, model, seed). Units are executed in
a thread pool (LLM calls and verifier subprocesses release the GIL). Results
are appended to results/raw/<experiment>/<config>__<model>.jsonl and
trajectories to logs/trajectories/<experiment>/<config>__<model>.jsonl.gz.

The runner is resumable: units whose run_id is already in the results file
are skipped, so an interrupted experiment can simply be started again.
A dollar budget stops new units from being launched once it is reached.
"""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.agents.controller import AgentConfig, SpecLoopAgent
from src.providers.cache import LLMCache, total_spend
from src.providers.llm_provider import create_provider
from src.schemas import PipelineResult, TaskSpec
from src.tracing.trajectory import TrajectoryWriter

ROOT = Path(__file__).resolve().parents[1]
CACHE_PATH = ROOT / "cache" / "llm_cache.sqlite"


def result_to_dict(r: PipelineResult) -> dict:
    return {
        "run_id": r.trajectory_id, "task_id": r.task_id, "pair_id": r.pair_id, "model": r.model,
        "config": r.config_name, "mode": r.agent_mode.value, "language": r.language.value, "seed": r.seed,
        "correct": r.correct, "spec_intact": r.spec_intact, "attempts": r.attempts,
        "solved_at_attempt": r.solved_at_attempt, "stop_reason": r.stop_reason,
        "first_attempt_tests_ok": r.first_attempt_tests_passed,
        "first_attempt_verified": r.first_attempt_verified,
        "llm_calls": r.llm_calls, "prompt_tokens": r.prompt_tokens, "completion_tokens": r.completion_tokens,
        "cost_usd": round(r.cost_usd, 6), "verifier_calls": r.verifier_calls, "test_calls": r.test_calls,
        "guard_blocks": r.guard_blocks, "strategy_switches": r.strategy_switches,
        "llm_seconds": round(r.llm_seconds, 2), "tool_seconds": round(r.tool_seconds, 2),
        "wall_seconds": round(r.total_time_seconds, 2), "failure_classes": r.failure_classes,
        "final_failure_class": r.final_failure_class, **r.extra,
    }


@dataclass
class RunSpec:
    experiment: str
    config: AgentConfig
    model: str
    seeds: list[int]


class Runner:
    def __init__(self, workers: int = 12, budget_usd: float = 2.0, offline: bool = False,
                 results_dir: Path = ROOT / "results" / "raw", logs_dir: Path = ROOT / "logs" / "trajectories"):
        self.workers = workers
        self.budget = budget_usd
        self.offline = offline
        self.results_dir = Path(results_dir)
        self.logs_dir = Path(logs_dir)
        self.cache = LLMCache(CACHE_PATH)
        self.skip_units: set = set()
        self.spent = 0.0
        # global cap: money spent by earlier runs counts against it
        self.already_spent = total_spend(self.cache)
        print(f"budget: ${self.already_spent:.3f} already spent, cap ${self.budget:.2f}")
        self._lock = threading.Lock()

    def _done_ids(self, path: Path) -> set[str]:
        if not path.exists():
            return set()
        with open(path, encoding="utf-8") as f:
            return {json.loads(l)["run_id"] for l in f if l.strip()}

    def run(self, spec: RunSpec, tasks: list[TaskSpec], verbose: bool = True) -> list[dict]:
        provider = create_provider(spec.model, cache=self.cache, offline=self.offline)
        tag = f"{spec.config.name}__{spec.model.replace('/', '_').replace(':', '_')}"
        out_path = self.results_dir / spec.experiment / f"{tag}.jsonl"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        writer = TrajectoryWriter(self.logs_dir / spec.experiment / f"{tag}.jsonl.gz")
        done = self._done_ids(out_path)
        units = [(t, s) for s in spec.seeds for t in tasks
                 if f"{spec.experiment}:{tag}:{t.task_id}:s{s}" not in done
                 and (t.task_id, s) not in self.skip_units]
        if verbose:
            print(f"[{spec.experiment}] {tag}: {len(units)} units to run ({len(done)} already done)")
        results: list[dict] = []
        write_lock = threading.Lock()

        def work(task: TaskSpec, seed: int):
            with self._lock:
                if self.already_spent + self.spent >= self.budget:
                    return None
            agent = SpecLoopAgent(provider, spec.config, seed=seed)
            run_id = f"{spec.experiment}:{tag}:{task.task_id}:s{seed}"
            res, traj = agent.run(task, run_id=run_id)
            row = result_to_dict(res)
            row["experiment"] = spec.experiment
            row["task_hash"] = task.content_hash
            with self._lock:
                self.spent += res.cost_usd
            with write_lock:
                with open(out_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(row) + "\n")
                writer.write(traj)
            return row

        t0 = time.time()
        with ThreadPoolExecutor(self.workers) as ex:
            futs = {ex.submit(work, t, s): (t.task_id, s) for t, s in units}
            for i, fut in enumerate(as_completed(futs), 1):
                try:
                    row = fut.result()
                except Exception as e:  # noqa: BLE001 - keep going, report at the end
                    tid, s = futs[fut]
                    print(f"  ! {tid} s{s} crashed: {type(e).__name__}: {str(e)[:200]}")
                    continue
                if row is None:
                    continue
                results.append(row)
                if verbose and (i % 20 == 0 or i == len(units)):
                    acc = sum(r["correct"] for r in results) / max(len(results), 1)
                    print(f"  {i}/{len(units)} done, correct so far {acc:.1%}, "
                          f"spent ${self.spent:.2f}, {time.time() - t0:.0f}s")
        return results
