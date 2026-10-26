"""
Feedback router (Gap 2 component).

The key observation behind this component: a Dafny error such as
"a postcondition could not be proved" is ambiguous. It is produced both when
the program is wrong and when the program is right but the proof annotations
(loop invariants, decreases clauses) are missing. Test outcomes resolve that
ambiguity cheaply:

  tests fail                -> LOGIC_BUG  : fix the algorithm first
  tests pass, proof fails   -> PROOF_GAP  : keep the algorithm, add annotations
  does not compile          -> SYNTAX     : only compile errors matter
  spec edited / escape hatch-> SPEC_TAMPER: restore the spec

The router classifies each failed attempt, orders the evidence accordingly
and tells the model which kind of repair is needed. With the router switched
off, the combined agent gets the Phase 1 behaviour: verifier output and test
output pasted one after the other with no interpretation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from src.schemas import (Diagnostic, FeedbackMessage, GuardResult, TestResult,
                         TestStatus, VerificationResult, VerificationStatus)

SPEC_TAMPER = "SPEC_TAMPER"
SYNTAX = "SYNTAX"
LOGIC_BUG = "LOGIC_BUG"
PROOF_GAP = "PROOF_GAP"
VERIFY_FAIL = "VERIFY_FAIL"      # verifier failed, no test evidence to tell why
TIMEOUT = "TIMEOUT"
SOLVED = "SOLVED"

_COMPILE_KINDS = {"syntax", "resolution"}
_CONCRETE_KINDS = {"counterexample", "exception"}   # CrossHair found a real input


@dataclass
class Observation:
    """Everything the tools reported about one candidate."""
    guard: Optional[GuardResult] = None
    vr: Optional[VerificationResult] = None
    tr: Optional[TestResult] = None
    diagnostics: list[Diagnostic] = field(default_factory=list)
    verifier_text: str = ""          # rendered by the normaliser (or raw)
    test_text: str = ""


def classify(obs: Observation) -> str:
    if obs.guard is not None and not obs.guard.ok and obs.guard.checked:
        return SPEC_TAMPER
    kinds = {d.kind for d in obs.diagnostics}
    if kinds & _COMPILE_KINDS or (obs.tr is not None and obs.tr.status is TestStatus.ERROR):
        return SYNTAX
    tests_fail = obs.tr is not None and obs.tr.status in (TestStatus.FAILED, TestStatus.TIMEOUT)
    ver_fail = obs.vr is not None and obs.vr.status is not VerificationStatus.VERIFIED
    if tests_fail:
        return LOGIC_BUG
    if ver_fail:
        if kinds & _CONCRETE_KINDS:
            return LOGIC_BUG
        if obs.vr.status is VerificationStatus.TIMEOUT or kinds == {"timeout"}:
            return TIMEOUT
        return PROOF_GAP if obs.tr is not None else VERIFY_FAIL
    return SOLVED


_DIRECTIVES = {
    SPEC_TAMPER: ("Your code changed the specification or used a forbidden shortcut. "
                  "Restore every given declaration and contract exactly as provided, then "
                  "implement the body. Shortcuts are rejected no matter what the verifier says."),
    SYNTAX: ("The program does not compile. Only the compile errors below matter right now; "
             "fix them without changing the specification."),
    LOGIC_BUG: ("The implementation computes wrong results: there is concrete evidence below "
                "(failing tests or a counterexample). Fix the algorithm first. Adding proof "
                "annotations will not help until the behaviour is right."),
    PROOF_GAP: ("The implementation passes every test we ran, so the algorithm is probably right. "
                "The verifier still cannot prove it. Keep the algorithm and strengthen the proof: "
                "add or fix loop invariants (bounds on the loop index and a clause that relates "
                "the partial result to the specification), decreases clauses, or small "
                "assertions/lemmas."),
    VERIFY_FAIL: "The verifier rejected the program. Fix the problems reported below.",
    TIMEOUT: ("The verifier timed out. Simplify the proof: use a simpler loop structure, "
              "smaller quantifiers, or helper lemmas."),
}


class FeedbackRouter:
    def __init__(self, enabled: bool = True, max_tests: int = 3):
        self.enabled = enabled
        self.compile_from_tests = compile_from_tests
        self.max_tests = max_tests

    @staticmethod
    def test_text(tr: TestResult, limit: int = 3) -> str:
        if tr is None or tr.status is TestStatus.PASSED:
            return ""
        lines = tr.failures[:limit]
        if len(tr.failures) > limit:
            lines.append(f"(+{len(tr.failures) - limit} more failing tests)")
        return "\n".join(lines)

    def route(self, obs: Observation, mode_uses_verifier: bool, mode_uses_tests: bool) -> FeedbackMessage:
        cls = classify(obs)
        if cls == SPEC_TAMPER and obs.guard is not None:
            body = "\n".join(f"- {v}" for v in obs.guard.violations)
            return FeedbackMessage("guard", False, _DIRECTIVES[SPEC_TAMPER] + "\n\n" + body,
                                   failure_class=cls, errors=obs.guard.violations)

        if mode_uses_verifier and mode_uses_tests and not self.enabled:
            # ablation: naive concatenation, as in the Phase 1 combined agent
            msg = ("## Formal verification result\n"
                   f"Status: {obs.vr.status.value if obs.vr else 'n/a'}\n{obs.verifier_text or 'no errors'}\n\n"
                   "## Test execution result\n"
                   f"Status: {obs.tr.status.value if obs.tr else 'n/a'}\n{obs.test_text or 'no failures'}")
            return FeedbackMessage("combined", False, msg, failure_class=cls)

        sections = [_DIRECTIVES.get(cls, "")] if (mode_uses_verifier and mode_uses_tests) else []
        tests_block = obs.test_text
        ver_block = obs.verifier_text
        if cls == SYNTAX:
            # compile errors only. If the verifier saw them, its (normalised) report is
            # the clearest; if only the compiled test run failed (e.g. a ghost function
            # used in executable code passes `dafny verify` but not compilation) the
            # test output is the only place the real error appears (dev iteration 4).
            verifier_saw_it = any(d.kind in _COMPILE_KINDS for d in obs.diagnostics)
            if self.compile_from_tests:
                block = (ver_block if verifier_saw_it else tests_block) or ver_block or tests_block
            else:  # behaviour before dev iteration 4
                block = ver_block or tests_block
            sections.append("Compile errors:\n" + block)
        elif cls == LOGIC_BUG:
            if tests_block:
                sections.append("Failing tests (input, expected, actual):\n" + tests_block)
            if ver_block:
                sections.append("Verifier report:\n" + ver_block)
        else:
            if ver_block:
                sections.append("Verifier report:\n" + ver_block)
            if tests_block:
                sections.append("Failing tests:\n" + tests_block)
        source = "combined" if (mode_uses_verifier and mode_uses_tests) else \
            ("verifier" if mode_uses_verifier else "test")
        return FeedbackMessage(source, False, "\n\n".join(s for s in sections if s).strip(),
                               failure_class=cls)
