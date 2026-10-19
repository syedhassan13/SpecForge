"""
Core data schemas for the SpecLoop pipeline.

These dataclasses are the contracts passed between the loader, the backends,
the agent controller and the evaluator. Phase 1 had a single binary test
result per task; Phase 2 keeps per-test-case outcomes and structured
diagnostics so that feedback can be routed and failures can be analysed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class VerificationStatus(Enum):
    VERIFIED = "verified"
    FAILED = "failed"
    TIMEOUT = "timeout"
    ERROR = "error"          # tool missing / crashed, not the candidate's fault


class TestStatus(Enum):
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"          # program did not compile or crashed before tests
    TIMEOUT = "timeout"


class Language(Enum):
    DAFNY = "dafny"
    PYTHON_ICONTRACT = "python_icontract"

    @property
    def short(self) -> str:
        return "dafny" if self is Language.DAFNY else "python"


class AgentMode(Enum):
    """Feedback configuration of the agent (Phase 1 naming kept)."""
    SINGLE_SHOT = "single_shot"              # no feedback loop
    TESTING_ONLY = "testing_only"            # Phase 1 baseline: test feedback only
    VERIFIER_FEEDBACK = "verifier_feedback"  # formal verifier feedback only
    COMBINED = "combined"                    # proposed: verifier + tests

    @property
    def uses_verifier(self) -> bool:
        return self in (AgentMode.VERIFIER_FEEDBACK, AgentMode.COMBINED)

    @property
    def uses_tests(self) -> bool:
        return self in (AgentMode.TESTING_ONLY, AgentMode.COMBINED)


@dataclass
class TaskSpec:
    """One benchmark task rendered in one specification language.

    The same `pair_id` is shared by the Dafny and the Python version of a
    task, which is what the paired Gap 1 analysis keys on.
    """
    task_id: str
    description: str
    language: Language
    specification: str
    reference_solution: str
    entry_point: str = ""
    params: list[dict] = field(default_factory=list)     # [{"name", "type"}]
    returns: str = ""
    tests: list[dict] = field(default_factory=list)      # [{"input": {...}, "expected": ...}]
    pair_id: str = ""
    verina_id: str = ""
    difficulty: str = "basic"
    source_benchmark: str = "verina-basic"
    content_hash: str = ""                               # sha1 of the task file
    test_cases: list[str] = field(default_factory=list)  # legacy Phase 1 field

    @property
    def n_visible(self) -> int:
        # first half (rounded up) of the tests is shown to the agent,
        # the rest is held out and only used by the final oracle
        return math.ceil(len(self.tests) / 2)

    @property
    def visible_tests(self) -> list[dict]:
        return self.tests[: self.n_visible]

    @property
    def hidden_tests(self) -> list[dict]:
        return self.tests[self.n_visible:]


@dataclass
class Diagnostic:
    """A normalised, language independent error report (Gap 1 component)."""
    kind: str                       # syntax, resolution, postcondition, invariant, ...
    message: str
    line: Optional[int] = None
    source_line: str = ""           # text of the offending line in the candidate
    related: str = ""               # spec clause involved, if the tool reports one
    counterexample: str = ""        # concrete inputs (CrossHair) if any

    def to_dict(self) -> dict:
        return dict(kind=self.kind, message=self.message, line=self.line,
                    source_line=self.source_line, related=self.related,
                    counterexample=self.counterexample)


@dataclass
class VerificationResult:
    status: VerificationStatus
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    time_seconds: float = 0.0
    verified_conditions: int = 0
    total_conditions: int = 0
    raw_output: str = ""
    diagnostics: list[Diagnostic] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        if self.total_conditions == 0:
            return 0.0
        return self.verified_conditions / self.total_conditions


@dataclass
class TestCaseOutcome:
    index: int
    passed: bool
    input_repr: str = ""
    expected_repr: str = ""
    got_repr: str = ""
    error: str = ""


@dataclass
class TestResult:
    status: TestStatus
    passed: int = 0
    total: int = 0
    failures: list[str] = field(default_factory=list)
    time_seconds: float = 0.0
    cases: list[TestCaseOutcome] = field(default_factory=list)
    raw_output: str = ""

    @property
    def pass_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return self.passed / self.total


@dataclass
class GuardResult:
    """Outcome of the specification integrity guard."""
    ok: bool
    checked: bool = True            # False when the code could not be parsed
    violations: list[str] = field(default_factory=list)


@dataclass
class GeneratedCode:
    task_id: str
    code: str
    language: Language
    model: str
    attempt: int = 1
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass
class FeedbackMessage:
    """Feedback produced by the router and sent to the LLM for repair."""
    source: str                     # "verifier", "test", "combined", "guard"
    success: bool
    message: str
    failure_class: str = ""         # SPEC_TAMPER, SYNTAX, LOGIC_BUG, PROOF_GAP, ...
    errors: list[str] = field(default_factory=list)
    suggestion: Optional[str] = None


@dataclass
class PipelineResult:
    """Everything recorded for one (task, configuration, seed) run."""
    task_id: str
    model: str
    agent_mode: AgentMode
    language: Language
    final_code: str
    verification_result: Optional[VerificationResult] = None
    test_result: Optional[TestResult] = None
    attempts: int = 1
    total_time_seconds: float = 0.0
    correct: bool = False
    # Phase 2 additions
    config_name: str = ""
    seed: int = 0
    pair_id: str = ""
    spec_intact: bool = True
    first_attempt_tests_passed: bool = False
    first_attempt_verified: bool = False
    solved_at_attempt: Optional[int] = None
    stop_reason: str = ""
    llm_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    verifier_calls: int = 0
    test_calls: int = 0
    guard_blocks: int = 0
    strategy_switches: int = 0
    llm_seconds: float = 0.0
    tool_seconds: float = 0.0
    failure_classes: list[str] = field(default_factory=list)
    final_failure_class: str = ""
    trajectory_id: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def formally_verified(self) -> bool:
        return (self.verification_result is not None
                and self.verification_result.status == VerificationStatus.VERIFIED)

    @property
    def tests_passed(self) -> bool:
        return (self.test_result is not None
                and self.test_result.status == TestStatus.PASSED)


@dataclass
class EvaluationMetrics:
    model: str
    agent_mode: AgentMode
    language: Language
    total_tasks: int = 0
    verified_count: int = 0
    test_pass_count: int = 0
    correct_count: int = 0
    avg_attempts: float = 0.0
    avg_time: float = 0.0

    @property
    def verification_rate(self) -> float:
        return self.verified_count / max(self.total_tasks, 1)

    @property
    def test_pass_rate(self) -> float:
        return self.test_pass_count / max(self.total_tasks, 1)

    @property
    def correctness_rate(self) -> float:
        return self.correct_count / max(self.total_tasks, 1)
