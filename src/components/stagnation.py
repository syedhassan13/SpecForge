"""
Stagnation monitor (robustness component).

In early dev runs the repair loop often got stuck: the model resubmitted the
same program, or kept producing different programs that failed in exactly
the same place. The monitor keeps a fingerprint of each failure and, when it
sees a repeat, asks the controller to switch from "patch" to "rewrite" mode
for the next call (new approach, higher temperature).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from src.schemas import Diagnostic, TestResult


def code_hash(code: str) -> str:
    return hashlib.sha1(" ".join(code.split()).encode("utf-8")).hexdigest()[:12]


def failure_signature(cls: str, diags: list[Diagnostic], tr: TestResult | None) -> str:
    d = sorted(f"{x.kind}@{x.line}" for x in diags)
    t = sorted(o.index for o in tr.cases if not o.passed) if tr is not None else []
    return f"{cls}|{','.join(d)}|{t}"


@dataclass
class StagnationMonitor:
    enabled: bool = True
    patience: int = 2                      # identical signatures in a row before switching
    seen_code: set[str] = field(default_factory=set)
    last_sig: str = ""
    repeat: int = 0

    def observe(self, code: str, signature: str) -> bool:
        """Record an attempt. Returns True if the next call should be a rewrite."""
        h = code_hash(code)
        dup_code = h in self.seen_code
        self.seen_code.add(h)
        if signature == self.last_sig:
            self.repeat += 1
        else:
            self.repeat = 1
            self.last_sig = signature
        if not self.enabled:
            return False
        if dup_code or self.repeat >= self.patience:
            self.repeat = 0
            return True
        return False
