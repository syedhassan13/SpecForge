"""
Phase 1 entry point, kept so old instructions still work.

It now runs experiment E1 (single-shot and testing-only baselines) through
the Phase 2 runner. Prefer `python specloop.py run experiments/configs/E1_baseline.json`.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

if __name__ == "__main__":
    args = sys.argv[1:]
    sys.exit(subprocess.call([sys.executable, "-m", "experiments.run",
                              str(ROOT / "experiments" / "configs" / "E1_baseline.json"), *args], cwd=ROOT))
