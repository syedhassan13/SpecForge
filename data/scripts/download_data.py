"""
Download the raw data used to build the benchmark.

  * VERINA (Ye et al., 2026) from Hugging Face: sunblaze-ucb/verina
  * upstream Dafny sources that VERINA-BASIC was translated from:
      - CloverBench  (github.com/ChuyueSun/Clover)
      - MBPP-DFY     (github.com/Mondego/dafny-synthesis)

The upstream files are only read by humans while writing the Dafny specs;
nothing from them is executed. Everything lands in data/raw/ (git ignored).
"""

import subprocess
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
VERINA_URL = ("https://huggingface.co/datasets/sunblaze-ucb/verina/resolve/main/"
              "data/train-00000-of-00001.parquet")
REPOS = {
    "Clover": "https://github.com/ChuyueSun/Clover.git",
    "dafny-synthesis": "https://github.com/Mondego/dafny-synthesis.git",
}


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    target = RAW / "verina.parquet"
    if not target.exists():
        print("downloading VERINA ...")
        urllib.request.urlretrieve(VERINA_URL, target)
    up = RAW / "upstream"
    up.mkdir(exist_ok=True)
    for name, url in REPOS.items():
        if not (up / name).exists():
            print(f"cloning {name} ...")
            subprocess.run(["git", "clone", "--depth", "1", "-q", url, str(up / name)], check=True)
    print("done")


if __name__ == "__main__":
    main()
