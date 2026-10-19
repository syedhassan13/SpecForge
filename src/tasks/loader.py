"""
Benchmark loading and fixed data splits.

Each file in data/tasks/ describes one VERINA-BASIC problem in both
specification languages. `load_tasks` expands it into two TaskSpec objects.
The dev/test split is fixed in data/splits.json and must not be changed
after the test set has been touched.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Iterable, Optional

from src.schemas import Language, TaskSpec

ROOT = Path(__file__).resolve().parents[2]
TASK_DIR = ROOT / "data" / "tasks"
SPLIT_FILE = ROOT / "data" / "splits.json"


def _to_spec(data: dict, language: Language, digest: str = "") -> TaskSpec:
    block = data["dafny"] if language is Language.DAFNY else data["python"]
    return TaskSpec(
        task_id=f"{data['task_id']}_{language.short}",
        description=data["description"],
        language=language,
        specification=block["spec"],
        reference_solution=block["reference"],
        entry_point=data["entry_point"],
        params=data["params"],
        returns=data["returns"],
        tests=data["tests"],
        pair_id=data["task_id"],
        verina_id=data.get("verina_id", ""),
        difficulty=data.get("difficulty", "basic"),
        source_benchmark=data.get("upstream", "verina-basic"),
        content_hash=digest,
    )


def load_task_file(path: str | os.PathLike) -> list[TaskSpec]:
    raw = Path(path).read_bytes()
    data = json.loads(raw.decode("utf-8"))
    digest = hashlib.sha1(raw).hexdigest()[:12]
    return [_to_spec(data, lang, digest) for lang in (Language.DAFNY, Language.PYTHON_ICONTRACT)]


def load_split(name: str) -> list[str]:
    with open(SPLIT_FILE, encoding="utf-8") as f:
        return json.load(f)[name]


def load_tasks(
    split: Optional[str] = None,
    languages: Optional[Iterable[Language]] = None,
    task_dir: str | os.PathLike = TASK_DIR,
    pair_ids: Optional[Iterable[str]] = None,
) -> list[TaskSpec]:
    """Load tasks, optionally restricted to a split, languages or pair ids."""
    wanted = set(load_split(split)) if split else None
    if pair_ids is not None:
        wanted = set(pair_ids) if wanted is None else wanted & set(pair_ids)
    langs = set(languages) if languages else None
    out: list[TaskSpec] = []
    for fn in sorted(os.listdir(task_dir)):
        if not fn.endswith(".json"):
            continue
        for t in load_task_file(Path(task_dir) / fn):
            if wanted is not None and t.pair_id not in wanted:
                continue
            if langs is not None and t.language not in langs:
                continue
            out.append(t)
    return out
