"""
Create the fixed dev/test split (data/splits.json).

The split is drawn once, over the VERINA ids we extracted, with a fixed seed,
before any experiment touched the tasks. 20 tasks go to dev (used for prompt
and component decisions, the 2-shot examples of E2 and the devlog
iterations); everything else is test. Tasks that fail validation are removed
from whichever side they were on; they are never moved between sides.
"""

import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SEED = 2026
N_DEV = 20


def main():
    raw = sorted(ROOT.glob("data/raw/verina_basic/verina_basic_*.json"))
    ids = sorted(f"vb_{int(p.stem.split('_')[-1]):03d}" for p in raw)
    rng = random.Random(SEED)
    dev = sorted(rng.sample(ids, N_DEV))
    test = sorted(set(ids) - set(dev))
    admitted = {p.stem for p in (ROOT / "data" / "tasks").glob("vb_*.json")}
    report = ROOT / "data" / "validation_report.json"
    if report.exists():
        ok = {r["task_id"] for r in json.loads(report.read_text()) if r.get("ok")}
        admitted &= ok
    out = {"seed": SEED, "dev": [i for i in dev if i in admitted] if report.exists() else dev,
           "test": [i for i in test if i in admitted] if report.exists() else test,
           "dev_planned": dev, "test_planned": test}
    (ROOT / "data" / "splits.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"dev {len(out['dev'])}/{len(dev)}  test {len(out['test'])}/{len(test)}")


if __name__ == "__main__":
    main()
