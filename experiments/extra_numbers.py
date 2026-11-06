"""
A few numbers that are not part of results/summary.json:
how many E5 units were executed (vs. reused) and the total API spend
recorded in the response cache. Writes results/extra_numbers.json, which
experiments/paper_numbers.py merges into paper/numbers.tex.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.providers.cache import LLMCache, total_spend  # noqa: E402

out = {}
e5 = ROOT / "results" / "raw" / "E5_ablation"
counts = []
for f in sorted(e5.glob("*.jsonl")):
    if f.name.startswith("no_normalizer"):
        continue          # this arm was partly run before the reuse option existed
    counts.append(sum(1 for _ in open(f, encoding="utf-8")))
if counts:
    out["e5.executed"] = max(counts)
out["e5.total"] = 231
cache = ROOT / "cache" / "llm_cache.sqlite"
if cache.exists():
    out["total.allspend"] = f"{total_spend(LLMCache(cache)):.2f}"
(ROOT / "results" / "extra_numbers.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
print(out)
