"""
VERINA CodeGen protocol (experiment E2).

Reproduces the base paper's evaluation setup on our benchmark: for each task
the model gets an expert instruction, the task description and a template
containing the reference specification, with two worked examples (2-shot,
taken from the dev split so they never overlap the test set). Sampling uses
temperature 1.0 and 5 samples per task; pass@1 is the mean over samples
(the unbiased estimator of Chen et al. reduces to c/n for k = 1).

VERINA scores code by unit tests only. We record that metric (`tests_ok`)
and also whether the same sample verifies and keeps the spec intact.
"""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from src.agents import prompts as P
from src.agents.coding_agent import _extract_code
from src.evaluation.oracle import judge
from src.providers.llm_provider import LLMProvider
from src.schemas import Language, TaskSpec


def build_messages(task: TaskSpec, shots: list[TaskSpec]) -> list[dict]:
    lang = "dafny" if task.language is Language.DAFNY else "python"
    msgs = [{"role": "system", "content": P.VERINA_STYLE_INSTRUCTIONS[lang]}]
    for ex in shots:
        msgs.append({"role": "user", "content": P.VERINA_STYLE_EXAMPLE.format(
            description=ex.description, fence=lang, specification=ex.specification)})
        msgs.append({"role": "assistant", "content": f"```{lang}\n{ex.reference_solution.strip()}\n```"})
    msgs.append({"role": "user", "content": P.VERINA_STYLE_EXAMPLE.format(
        description=task.description, fence=lang, specification=task.specification)})
    return msgs


def run_verina_protocol(provider: LLMProvider, tasks: list[TaskSpec], shots: dict[Language, list[TaskSpec]],
                        out_path: Path, samples: int = 5, temperature: float = 1.0,
                        workers: int = 12, budget: float = 2.0, cache=None) -> list[dict]:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if out_path.exists():
        done = {json.loads(l)["run_id"] for l in open(out_path, encoding="utf-8") if l.strip()}
    lock = threading.Lock()
    rows: list[dict] = []
    from src.providers.cache import total_spend
    spent = [total_spend(cache) if cache is not None else 0.0]

    def work(task: TaskSpec, k: int):
        run_id = f"E2:{provider.model_name()}:{task.task_id}:sample{k}"
        if run_id in done or spent[0] >= budget:
            return None
        msgs = build_messages(task, shots[task.language])
        reply = provider.chat(msgs, temperature=temperature, max_tokens=4096, seed=None, sample=k)
        lang = "dafny" if task.language is Language.DAFNY else "python"
        code = _extract_code(reply.text, lang)
        v = judge(task, code)
        row = {"run_id": run_id, "task_id": task.task_id, "pair_id": task.pair_id,
               "language": task.language.value, "model": provider.model_name(), "sample": k,
               "tests_ok": v.tests_ok, "verified": v.verified, "spec_intact": v.spec_intact,
               "correct": v.correct, "verify_status": v.verify_status,
               "compiles": v.compiles,
               "prompt_tokens": reply.prompt_tokens, "completion_tokens": reply.completion_tokens,
               "cost_usd": reply.cost_usd, "task_hash": task.content_hash, "code": code}
        with lock:
            spent[0] += 0.0 if reply.cached else reply.cost_usd
            with open(out_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
        return row

    with ThreadPoolExecutor(workers) as ex:
        futs = [ex.submit(work, t, k) for t in tasks for k in range(samples)]
        for fut in as_completed(futs):
            try:
                r = fut.result()
            except Exception as e:  # noqa: BLE001
                print("  ! sample failed:", type(e).__name__, str(e)[:160])
                continue
            if r:
                rows.append(r)
    return rows
