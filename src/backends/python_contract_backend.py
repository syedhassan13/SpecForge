"""
Python + iContract backend.

verify()    -> CrossHair symbolic execution over the iContract contracts.
               CrossHair is a bounded checker: "verified" here means no
               counterexample was found within the time budget, which is a
               weaker guarantee than a Dafny proof (discussed in the paper).
run_tests() -> executes the generated test runner with iContract enabled, so
               a contract violation shows up as a failing case.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

from src.backends import tool_cache
from src.schemas import (TestResult, TestStatus, VerificationResult,
                         VerificationStatus)
from src.backends.dafny_backend import _collect
from src.backends.proc import run_tree
from src.tasks.harness import python_harness

_CH_LINE = re.compile(r"^(?P<file>.+?\.py):(?P<line>\d+): (?P<sev>error|warning|info): (?P<msg>.*)$")


def _hash(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()


class PythonContractBackend:
    name = "python"

    def __init__(self, crosshair_timeout: int = 6, test_timeout: int = 30,
                 python: str = sys.executable):
        self.crosshair_timeout = crosshair_timeout      # per condition
        self.test_timeout = test_timeout
        self.python = python
        self._cache: dict[str, object] = {}
        self._lock = threading.Lock()

    def _disk_key(self, key: str) -> str:
        return f"crosshair|{self.crosshair_timeout}|{self.test_timeout}|{key}"

    def _write(self, code: str) -> tuple[str, str]:
        work = tempfile.mkdtemp(prefix="specloop_py_")
        path = os.path.join(work, "candidate.py")
        with open(path, "w", encoding="utf-8") as f:
            f.write(code)
        return work, path

    @staticmethod
    def syntax_error(code: str) -> str:
        try:
            compile(code, "candidate.py", "exec")
        except SyntaxError as e:
            return f"line {e.lineno}: SyntaxError: {e.msg}"
        return ""

    # ------------------------------------------------------------------
    def verify(self, code: str) -> VerificationResult:
        key = _hash("verify", code)
        with self._lock:
            if key in self._cache:
                return self._cache[key]  # type: ignore[return-value]
        disk = tool_cache.get(self._disk_key(key))
        if disk is not None:
            with self._lock:
                self._cache[key] = disk
            return disk
        start = time.time()
        syn = self.syntax_error(code)
        if syn:
            res = VerificationResult(VerificationStatus.FAILED, errors=[syn],
                                     time_seconds=time.time() - start, raw_output=syn)
            with self._lock:
                self._cache[key] = res
            return res
        work, path = self._write(code)
        overall = max(60, self.crosshair_timeout * 12)
        try:
            rc, out = run_tree(
                [self.python, "-m", "crosshair", "check", "--analysis_kind", "icontract",
                 "--per_condition_timeout", str(self.crosshair_timeout), path],
                cwd=work, timeout=overall)
        except subprocess.TimeoutExpired:
            res = VerificationResult(VerificationStatus.TIMEOUT,
                                     errors=[f"CrossHair timed out after {overall}s"],
                                     time_seconds=time.time() - start, raw_output="TIMEOUT")
            with self._lock:
                self._cache[key] = res
            return res
        finally:
            shutil.rmtree(work, ignore_errors=True)

        errors = []
        for line in out.splitlines():
            m = _CH_LINE.match(line.strip())
            if m and m.group("sev") == "error":
                errors.append(f"line {m.group('line')}: {m.group('msg')}")
        if rc == 0 and not errors:
            status = VerificationStatus.VERIFIED
        else:
            status = VerificationStatus.FAILED
            if not errors:
                # import error or crash inside crosshair, keep the useful tail
                tail = [l for l in out.splitlines() if l.strip()][-4:]
                errors = ["could not analyse module: " + " | ".join(tail)]
        n_cond = code.count("@icontract.ensure") + code.count("@icontract.require")
        res = VerificationResult(status=status, errors=errors,
                                 time_seconds=time.time() - start,
                                 verified_conditions=0 if errors else n_cond,
                                 total_conditions=n_cond, raw_output=out)
        with self._lock:
            self._cache[key] = res
        return res

    # ------------------------------------------------------------------
    def run_tests(self, code: str, entry: str, params: list[dict], returns: str,
                  cases: list[dict]) -> TestResult:
        if not cases:
            return TestResult(TestStatus.PASSED)
        program = code + "\n" + python_harness(entry, params, returns, cases)
        key = _hash("tests", program)
        with self._lock:
            if key in self._cache:
                return self._cache[key]  # type: ignore[return-value]
        disk = tool_cache.get(self._disk_key(key))
        if disk is not None:
            with self._lock:
                self._cache[key] = disk
            return disk
        start = time.time()
        work, path = self._write(program)
        try:
            rc, out = _run([self.python, path], cwd=work, timeout=self.test_timeout)
            res = _collect(cases, out, rc, time.time() - start)
        except subprocess.TimeoutExpired:
            res = TestResult(TestStatus.TIMEOUT, total=len(cases),
                             failures=["test run timed out (possible infinite loop)"],
                             time_seconds=time.time() - start, raw_output="TIMEOUT")
        finally:
            shutil.rmtree(work, ignore_errors=True)
        with self._lock:
            self._cache[key] = res
        return res
