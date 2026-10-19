"""
Dafny verification backend.

verify()    -> runs `dafny verify` on the candidate program
run_tests() -> compiles the candidate with a generated Main (Python target,
               --no-verify) and reads per-case PASS/FAIL markers

Results are memoised by a hash of the program text, so the final oracle
does not pay twice for a candidate the agent already checked.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Optional

from src.backends import tool_cache
from src.backends.proc import run_tree
from src.schemas import (TestCaseOutcome, TestResult, TestStatus,
                         VerificationResult, VerificationStatus)
from src.tasks.harness import FAIL, PASS, case_repr, dafny_harness, parse_markers

DEFAULT_DAFNY = os.environ.get("DAFNY_PATH", "dafny")

_LOC = re.compile(r"^(?P<file>.+?)\((?P<line>\d+),(?P<col>\d+)\): "
                  r"(?P<sev>Error|Warning|Related location): (?P<msg>.*)$")
_SUMMARY = re.compile(r"finished with (\d+) verified, (\d+) errors?")
_MAIN = re.compile(r"\bmethod\s+Main\s*\(")


def _hash(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()


class DafnyBackend:
    name = "dafny"

    def __init__(self, dafny_path: str = DEFAULT_DAFNY, timeout: int = 90,
                 z3_timeout: int = 20):
        self.dafny_path = dafny_path
        self.timeout = timeout
        self.z3_timeout = z3_timeout
        self._cache: dict[str, object] = {}
        self._lock = threading.Lock()

    def _disk_key(self, key: str) -> str:
        return f"dafny4.11|{self.timeout}|{self.z3_timeout}|{key}"

    # ------------------------------------------------------------------
    def _run(self, args: list[str], code: str, cwd_files: Optional[str] = None):
        work = tempfile.mkdtemp(prefix="specloop_dfy_")
        path = os.path.join(work, "candidate.dfy")
        with open(path, "w", encoding="utf-8") as f:
            f.write(code)
        try:
            # run_tree kills the compiled program too if a candidate loops forever
            return run_tree([self.dafny_path, *args, path], cwd=work, timeout=self.timeout)
        finally:
            shutil.rmtree(work, ignore_errors=True)

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
        try:
            rc, out = self._run(["verify", "--allow-warnings", "--cores", "1",
                                 "--verification-time-limit", str(self.z3_timeout)], code)
        except subprocess.TimeoutExpired:
            res = VerificationResult(VerificationStatus.TIMEOUT,
                                     errors=[f"verification timed out after {self.timeout}s"],
                                     time_seconds=time.time() - start,
                                     raw_output="TIMEOUT")
            with self._lock:
                self._cache[key] = res
            return res
        except FileNotFoundError:
            return VerificationResult(VerificationStatus.ERROR,
                                      errors=[f"Dafny not found at {self.dafny_path!r}"])
        errors, warnings = [], []
        for line in out.splitlines():
            m = _LOC.match(line.strip())
            if not m:
                if "parse errors detected" in line or "resolution/type errors" in line:
                    errors.append(line.strip())
                continue
            text = f"line {m.group('line')}: {m.group('sev')}: {m.group('msg')}"
            (warnings if m.group("sev") == "Warning" else errors).append(text)
        verified, failed = 0, 0
        sm = _SUMMARY.search(out)
        if sm:
            verified, failed = int(sm.group(1)), int(sm.group(2))
        if rc == 0 and sm and failed == 0:
            status = VerificationStatus.VERIFIED
        elif "timed out" in out.lower() or "out of resource" in out.lower():
            status = VerificationStatus.TIMEOUT
        else:
            status = VerificationStatus.FAILED
            if not errors:
                errors = [out.strip()[-600:] or "verification failed"]
        res = VerificationResult(status=status, errors=errors, warnings=warnings,
                                 time_seconds=time.time() - start,
                                 verified_conditions=verified,
                                 total_conditions=verified + failed, raw_output=out)
        with self._lock:
            self._cache[key] = res
        return res

    # ------------------------------------------------------------------
    def run_tests(self, code: str, entry: str, params: list[dict], returns: str,
                  cases: list[dict]) -> TestResult:
        if not cases:
            return TestResult(TestStatus.PASSED)
        # a Main written by the model would clash with the harness
        program = _MAIN.sub("method Main_unused(", code) + "\n\n" + \
            dafny_harness(entry, params, returns, cases)
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
        try:
            rc, out = self._run(["run", "--no-verify", "--allow-warnings",
                                 "--target", "py"], program)
        except subprocess.TimeoutExpired:
            res = TestResult(TestStatus.TIMEOUT, total=len(cases),
                             failures=["test run timed out (possible infinite loop)"],
                             time_seconds=time.time() - start, raw_output="TIMEOUT")
            with self._lock:
                self._cache[key] = res
            return res
        except FileNotFoundError:
            return TestResult(TestStatus.ERROR, total=len(cases), failures=["Dafny not found"])
        res = _collect(cases, out, rc, time.time() - start)
        with self._lock:
            self._cache[key] = res
        return res


def _collect(cases: list[dict], out: str, rc: int, elapsed: float) -> TestResult:
    marks = parse_markers(out)
    outcomes, failures = [], []
    for i, case in enumerate(cases):
        marker, detail = marks.get(i, ("", ""))
        ok = marker == PASS
        got = detail[4:] if detail.startswith("got=") else ""
        err = "" if ok or marker == FAIL else (detail or "did not run (earlier crash or compile error)")
        outcomes.append(TestCaseOutcome(index=i, passed=ok, input_repr=case_repr(case),
                                        expected_repr=repr(case["expected"]),
                                        got_repr=got, error=err))
        if not ok:
            msg = f"test {i}: input ({case_repr(case)}) expected {case['expected']!r}"
            msg += f" got {got}" if marker == FAIL else f" error: {err}"
            failures.append(msg)
    passed = sum(o.passed for o in outcomes)
    if not marks:
        # nothing ran: compile/resolution error or crash before the first case
        tail = "\n".join(l for l in out.splitlines() if l.strip())[-800:]
        return TestResult(TestStatus.ERROR, passed=0, total=len(cases),
                          failures=[f"program did not run: {tail}"], time_seconds=elapsed,
                          cases=outcomes, raw_output=out)
    status = TestStatus.PASSED if passed == len(cases) else TestStatus.FAILED
    return TestResult(status, passed=passed, total=len(cases), failures=failures,
                      time_seconds=elapsed, cases=outcomes, raw_output=out)
