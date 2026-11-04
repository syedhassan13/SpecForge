"""
Shared on-disk cache for verifier and test results.

Different experiments check the same programs many times: for a given task
and seed every configuration starts from the same (cached) first candidate,
and ablations that never trigger their component replay the full system's
trajectory exactly. Caching tool results by (tool, settings, program text)
removes that repeated work across processes. Results keep the run time that
was measured when they were first computed, so the latency numbers in E6
reflect real tool cost, not cache hits.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

from src.schemas import (TestCaseOutcome, TestResult, TestStatus, VerificationResult,
                         VerificationStatus)

ROOT = Path(__file__).resolve().parents[2]
_PATH = ROOT / "cache" / "tool_cache.sqlite"
_lock = threading.Lock()
_conn = None


def _db():
    global _conn
    if _conn is None:
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(_PATH), check_same_thread=False, timeout=60)
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("CREATE TABLE IF NOT EXISTS tool (k TEXT PRIMARY KEY, v TEXT NOT NULL)")
        _conn.commit()
    return _conn


def get(key: str):
    with _lock:
        row = _db().execute("SELECT v FROM tool WHERE k=?", (key,)).fetchone()
    if not row:
        return None
    d = json.loads(row[0])
    if d["kind"] == "verify":
        return VerificationResult(status=VerificationStatus(d["status"]), errors=d["errors"],
                                  warnings=d["warnings"], time_seconds=d["time_seconds"],
                                  verified_conditions=d["verified_conditions"],
                                  total_conditions=d["total_conditions"], raw_output=d["raw_output"])
    return TestResult(status=TestStatus(d["status"]), passed=d["passed"], total=d["total"],
                      failures=d["failures"], time_seconds=d["time_seconds"],
                      cases=[TestCaseOutcome(**c) for c in d["cases"]], raw_output=d["raw_output"])


def put(key: str, res):
    if isinstance(res, VerificationResult):
        d = {"kind": "verify", "status": res.status.value, "errors": res.errors, "warnings": res.warnings,
             "time_seconds": res.time_seconds, "verified_conditions": res.verified_conditions,
             "total_conditions": res.total_conditions, "raw_output": res.raw_output[-20000:]}
    else:
        d = {"kind": "tests", "status": res.status.value, "passed": res.passed, "total": res.total,
             "failures": res.failures, "time_seconds": res.time_seconds,
             "cases": [c.__dict__ for c in res.cases], "raw_output": res.raw_output[-20000:]}
    with _lock:
        _db().execute("INSERT OR REPLACE INTO tool (k, v) VALUES (?, ?)", (key, json.dumps(d)))
        _db().commit()
