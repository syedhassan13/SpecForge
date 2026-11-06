"""
Statistics helpers used by experiments/analyze.py.

Unit of analysis: a task instance (task x language). With 3 seeds per
configuration we first average correctness over seeds per task, then
compare configurations on the same tasks (paired design):

  * Wilcoxon signed-rank test on the per-task mean correctness
  * exact McNemar test on per-(task, seed) outcomes, as a second check
  * bootstrap 95% confidence interval for the difference in rates
  * mean and standard deviation over seeds for every reported rate
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from typing import Iterable

import numpy as np
from scipy import stats as sps


def rate_by_seed(rows: list[dict], key: str = "correct") -> dict[int, float]:
    by = defaultdict(list)
    for r in rows:
        by[r["seed"]].append(1.0 if r[key] else 0.0)
    return {s: sum(v) / len(v) for s, v in by.items() if v}


def mean_std(rows: list[dict], key: str = "correct") -> tuple[float, float, int]:
    per = list(rate_by_seed(rows, key).values())
    if not per:
        return float("nan"), float("nan"), 0
    sd = float(np.std(per, ddof=1)) if len(per) > 1 else 0.0
    return float(np.mean(per)), sd, len(per)


def per_task_mean(rows: list[dict], key: str = "correct") -> dict[str, float]:
    by = defaultdict(list)
    for r in rows:
        by[r["task_id"]].append(1.0 if r[key] else 0.0)
    return {t: sum(v) / len(v) for t, v in by.items()}


def paired(a_rows: list[dict], b_rows: list[dict], key: str = "correct", n_boot: int = 5000,
           seed: int = 7) -> dict:
    """Compare configuration A against B on the tasks both have results for."""
    a, b = per_task_mean(a_rows, key), per_task_mean(b_rows, key)
    common = sorted(set(a) & set(b))
    if not common:
        return {"n_tasks": 0}
    da = np.array([a[t] for t in common])
    db = np.array([b[t] for t in common])
    diff = da - db
    if np.allclose(diff, 0):
        p_w = 1.0
    else:
        p_w = float(sps.wilcoxon(da, db, zero_method="wilcox").pvalue)
    rng = random.Random(seed)
    idx = list(range(len(common)))
    boots = []
    for _ in range(n_boot):
        s = [rng.choice(idx) for _ in idx]
        boots.append(float(np.mean(diff[s])))
    lo, hi = np.percentile(boots, [2.5, 97.5])
    # McNemar on matched (task, seed) outcomes
    am = {(r["task_id"], r["seed"]): bool(r[key]) for r in a_rows}
    bm = {(r["task_id"], r["seed"]): bool(r[key]) for r in b_rows}
    keys = set(am) & set(bm)
    n01 = sum(1 for k in keys if not am[k] and bm[k])
    n10 = sum(1 for k in keys if am[k] and not bm[k])
    p_m = mcnemar_exact(n10, n01)
    return {"n_tasks": len(common), "a": float(da.mean()), "b": float(db.mean()),
            "diff": float(diff.mean()), "ci95": [float(lo), float(hi)], "p_wilcoxon": p_w,
            "mcnemar_a_only": n10, "mcnemar_b_only": n01, "p_mcnemar": p_m}


def mcnemar_exact(b: int, c: int) -> float:
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    p = sum(math.comb(n, i) for i in range(0, k + 1)) / 2 ** n
    return min(1.0, 2 * p)


def fmt_pct(m: float, s: float | None = None) -> str:
    if m != m:  # NaN
        return "n/a"
    return f"{100 * m:.1f}" + (f" ± {100 * s:.1f}" if s is not None else "")


def correctness_at_k(rows: list[dict], k: int) -> float:
    """Share of runs whose candidate after k attempts (or earlier stop) is correct."""
    vals = []
    for r in rows:
        seq = r.get("per_attempt_correct") or [r["correct"]]
        vals.append(1.0 if seq[min(k, len(seq)) - 1] else 0.0)
    return float(np.mean(vals)) if vals else float("nan")


def flatten(xs: Iterable[Iterable]) -> list:
    return [y for x in xs for y in x]
