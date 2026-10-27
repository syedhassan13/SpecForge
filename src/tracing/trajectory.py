"""
Agent trajectory logging.

Each run produces one trajectory: a header (task, model, configuration,
seed) followed by timestamped events. Event types:

  state     state machine transition (GENERATE -> CHECK -> ROUTE -> REPAIR ...)
  llm       one model call: purpose, tokens, the model's own "analysis" and
            "strategy" fields, and the code it returned
  tool      one tool call: spec_guard / verify / run_tests, input hash, a
            summary of the output and its duration
  feedback  the routed feedback text and failure class sent to the model
  decision  stop / continue / switch-to-rewrite, with the reason
  oracle    independent final judgement of a candidate

Trajectories are written as gzipped JSONL under logs/trajectories/.
"""

from __future__ import annotations

import gzip
import json
import threading
import time
from pathlib import Path
from typing import Any


class Trajectory:
    def __init__(self, run_id: str, header: dict[str, Any]):
        self.run_id = run_id
        self.header = header
        self.events: list[dict[str, Any]] = []
        self._t0 = time.time()
        self.state = "START"

    def log(self, kind: str, **data):
        self.events.append({"t": round(time.time() - self._t0, 3), "type": kind, **data})

    def transition(self, new_state: str, **data):
        self.log("state", frm=self.state, to=new_state, **data)
        self.state = new_state

    def to_dict(self) -> dict:
        return {"run_id": self.run_id, **self.header, "events": self.events}


class TrajectoryWriter:
    """Thread-safe appender for one experiment/config file."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def write(self, traj: Trajectory):
        line = json.dumps(traj.to_dict(), ensure_ascii=False) + "\n"
        with self._lock:
            with gzip.open(self.path, "at", encoding="utf-8") as f:
                f.write(line)


def read_trajectories(path: str | Path) -> list[dict]:
    out = []
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                out.append(json.loads(line))
    return out
