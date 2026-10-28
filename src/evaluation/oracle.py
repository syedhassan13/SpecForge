"""
Independent correctness oracle.

The agent's own stopping rule depends on its mode (a testing-only agent stops
when the visible tests pass). The oracle ignores the mode and judges every
candidate the same way:

    correct  <=>  spec intact (guard, always on)
                  AND verified (Dafny proof / no CrossHair counterexample)
                  AND all tests pass (visible + held-out)

`tests_ok` alone is VERINA's CodeGen metric (pass@1 on unit tests), which is
what we compare against the base paper's reported numbers.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from src.backends import get_backend
from src.components.spec_guard import SpecGuard
from src.schemas import Language, TaskSpec, TestStatus, VerificationStatus


@dataclass
class OracleVerdict:
    spec_intact: bool
    verified: bool
    tests_ok: bool
    tests_passed: int
    tests_total: int
    correct: bool
    verify_status: str
    compiles: bool
    guard_violations: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


_guard = SpecGuard(enabled=True)


def judge(task: TaskSpec, code: str) -> OracleVerdict:
    be = get_backend(task.language)
    vr = be.verify(code)
    try:
        g = _guard.check(task.language, task.specification, code, task.entry_point,
                         vr.warnings if task.language is Language.DAFNY else None)
    except Exception as e:  # noqa: BLE001 - malformed code must not crash the run
        from src.schemas import GuardResult
        g = GuardResult(ok=False, checked=False, violations=[f"guard error: {e}"])
    tr = be.run_tests(code, task.entry_point, task.params, task.returns, task.tests)
    verified = vr.status is VerificationStatus.VERIFIED
    tests_ok = tr.status is TestStatus.PASSED
    return OracleVerdict(spec_intact=g.ok, verified=verified, tests_ok=tests_ok,
                         tests_passed=tr.passed, tests_total=tr.total,
                         correct=g.ok and verified and tests_ok,
                         verify_status=vr.status.value,
                         compiles=tr.status is not TestStatus.ERROR,
                         guard_violations=g.violations[:5])
