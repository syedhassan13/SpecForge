"""
Disk cache for LLM responses (SQLite, thread safe).

The key is a SHA-256 of the full request (model, messages, temperature, seed,
sample index, response schema). Because the experiments are run with fixed
seeds and sample indices, a warm cache replays every run exactly.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from pathlib import Path


class LLMCache:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("CREATE TABLE IF NOT EXISTS llm (k TEXT PRIMARY KEY, v TEXT NOT NULL)")
        self._conn.commit()

    @staticmethod
    def key(request: dict) -> str:
        blob = json.dumps(request, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def get(self, request: dict):
        k = self.key(request)
        with self._lock:
            row = self._conn.execute("SELECT v FROM llm WHERE k=?", (k,)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, request: dict, value: dict):
        k = self.key(request)
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO llm (k, v) VALUES (?, ?)",
                               (k, json.dumps(value, ensure_ascii=False)))
            self._conn.commit()

    def __len__(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM llm").fetchone()[0]


def total_spend(cache: "LLMCache") -> float:
    """Dollar cost of every response stored in the cache (= everything ever paid for)."""
    from src.providers.llm_provider import price
    with cache._lock:
        rows = cache._conn.execute("SELECT v FROM llm").fetchall()
    total = 0.0
    for (v,) in rows:
        d = json.loads(v)
        total += price(d.get("model_version", ""), d.get("pt", 0), d.get("ct", 0))
    return total
