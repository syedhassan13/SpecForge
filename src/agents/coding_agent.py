"""
Coding agent implementations for the verification feedback loop.

Provides four agent modes:
1. SingleShotAgent: One-shot generation, no feedback (ablation control).
2. TestingOnlyAgent: Feedback from runtime tests only (baseline).
3. VerifierFeedbackAgent: Feedback from formal verifier only.
4. CombinedAgent: Feedback from both verifier and tests (proposed system).

Each agent follows the same interface: given a task specification and an LLM
provider, it generates code and optionally iterates through a feedback loop.
"""

import re
import time
from typing import Optional

from src.schemas import (
    AgentMode,
    FeedbackMessage,
    GeneratedCode,
    Language,
    PipelineResult,
    TaskSpec,
    TestResult,
    TestStatus,
    VerificationResult,
    VerificationStatus,
)
from src.backends.dafny_backend import DafnyBackend
from src.backends.python_contract_backend import PythonContractBackend
from src.providers.llm_provider import LLMProvider
from src.agents.prompts import (
    SYSTEM_PROMPT_DAFNY,
    SYSTEM_PROMPT_PYTHON,
    INITIAL_PROMPT_TEMPLATE,
    FEEDBACK_PROMPT_TEMPLATE,
    COMBINED_FEEDBACK_TEMPLATE,
)


def _extract_code(response: str, language: str) -> str:
    """Extract code from LLM response, handling markdown fences."""
    # Try to extract from code block
    pattern = rf"```(?:{language})?\s*\n(.*?)```"
    match = re.search(pattern, response, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    # If no code block, return the whole response
    return response.strip()


def _get_backend(language: Language):
    """Get the appropriate verification backend for the language."""
    if language == Language.DAFNY:
        return DafnyBackend()
    elif language == Language.PYTHON_ICONTRACT:
        return PythonContractBackend()
    else:
        raise ValueError(f"Unsupported language: {language}")


def _get_system_prompt(language: Language) -> str:
    """Get the system prompt for the given language."""
    if language == Language.DAFNY:
        return SYSTEM_PROMPT_DAFNY
    return SYSTEM_PROMPT_PYTHON


class SingleShotAgent:
    """One-shot code generation with no feedback loop.

    This agent generates code once and evaluates it.
    Used as the minimal ablation control.
    """

    MODE = AgentMode.SINGLE_SHOT

    def __init__(self, provider: LLMProvider):
        self.provider = provider

    def run(self, task: TaskSpec) -> PipelineResult:
        """Generate code for the task with no feedback."""
        start = time.time()
        backend = _get_backend(task.language)
        lang_str = "dafny" if task.language == Language.DAFNY else "python"
        system_prompt = _get_system_prompt(task.language)

        prompt = INITIAL_PROMPT_TEMPLATE.format(
            description=task.description,
            language=lang_str,
            specification=task.specification,
        )

        response, pt, ct = self.provider.generate(prompt, system_prompt)
        code = _extract_code(response, lang_str)

        # Verify
        vr = backend.verify(code)

        # Test
        test_code = "\n".join(task.test_cases) if task.test_cases else ""
        tr = backend.run_tests(code, test_code) if test_code else None

        correct = (
            vr.status == VerificationStatus.VERIFIED
            and (tr is None or tr.status == TestStatus.PASSED)
        )

        return PipelineResult(
            task_id=task.task_id,
            model=self.provider.model_name(),
            agent_mode=self.MODE,
            language=task.language,
            final_code=code,
            verification_result=vr,
            test_result=tr,
            attempts=1,
            total_time_seconds=time.time() - start,
            correct=correct,
        )


class TestingOnlyAgent:
    """Agent with feedback loop driven by test results only.

    This is the primary BASELINE — represents agents that rely on
    testing alone without formal verification feedback.
    """

    MODE = AgentMode.TESTING_ONLY

    def __init__(self, provider: LLMProvider, max_attempts: int = 5):
        self.provider = provider
        self.max_attempts = max_attempts

    def run(self, task: TaskSpec) -> PipelineResult:
        """Generate code with test-driven feedback loop."""
        start = time.time()
        backend = _get_backend(task.language)
        lang_str = "dafny" if task.language == Language.DAFNY else "python"
        system_prompt = _get_system_prompt(task.language)

        # Initial generation
        prompt = INITIAL_PROMPT_TEMPLATE.format(
            description=task.description,
            language=lang_str,
            specification=task.specification,
        )

        response, _, _ = self.provider.generate(prompt, system_prompt)
        code = _extract_code(response, lang_str)
        test_code = "\n".join(task.test_cases) if task.test_cases else ""

        best_code = code
        best_tr = None

        for attempt in range(1, self.max_attempts + 1):
            tr = backend.run_tests(code, test_code) if test_code else TestResult(status=TestStatus.PASSED)
            best_tr = tr

            if tr.status == TestStatus.PASSED:
                best_code = code
                break

            # Send test failures back
            error_msgs = "\n".join(tr.failures) if tr.failures else "Tests failed"
            feedback_prompt = FEEDBACK_PROMPT_TEMPLATE.format(
                language=lang_str,
                previous_code=code,
                feedback_type="Test Execution",
                feedback_status="FAILED",
                error_messages=error_msgs,
            )

            response, _, _ = self.provider.generate(feedback_prompt, system_prompt)
            code = _extract_code(response, lang_str)
            best_code = code

        # Final verification (for measurement, not used for feedback)
        vr = backend.verify(best_code)

        correct = (
            vr.status == VerificationStatus.VERIFIED
            and (best_tr is None or best_tr.status == TestStatus.PASSED)
        )

        return PipelineResult(
            task_id=task.task_id,
            model=self.provider.model_name(),
            agent_mode=self.MODE,
            language=task.language,
            final_code=best_code,
            verification_result=vr,
            test_result=best_tr,
            attempts=attempt if 'attempt' in dir() else 1,
            total_time_seconds=time.time() - start,
            correct=correct,
        )


class VerifierFeedbackAgent:
    """Agent with feedback loop driven by formal verifier errors.

    Uses Dafny/CrossHair verification errors as feedback to guide
    the LLM in repairing its code. Core of our proposed system.
    """

    MODE = AgentMode.VERIFIER_FEEDBACK

    def __init__(self, provider: LLMProvider, max_attempts: int = 5):
        self.provider = provider
        self.max_attempts = max_attempts

    def run(self, task: TaskSpec) -> PipelineResult:
        """Generate code with verifier-feedback loop."""
        start = time.time()
        backend = _get_backend(task.language)
        lang_str = "dafny" if task.language == Language.DAFNY else "python"
        system_prompt = _get_system_prompt(task.language)

        prompt = INITIAL_PROMPT_TEMPLATE.format(
            description=task.description,
            language=lang_str,
            specification=task.specification,
        )

        response, _, _ = self.provider.generate(prompt, system_prompt)
        code = _extract_code(response, lang_str)

        best_code = code
        best_vr = None
        attempt = 1

        for attempt in range(1, self.max_attempts + 1):
            # Guard against spec tampering
            spec_ok, violations = backend.guard_spec_integrity(
                task.specification, code
            )
            if not spec_ok:
                error_msgs = "SPECIFICATION TAMPERING DETECTED:\n" + "\n".join(violations)
                error_msgs += "\n\nYou MUST preserve all specification clauses exactly as given."
            else:
                # Verify
                vr = backend.verify(code)
                best_vr = vr

                if vr.status == VerificationStatus.VERIFIED:
                    best_code = code
                    break

                error_msgs = "\n".join(vr.errors) if vr.errors else "Verification failed"

            # Send verifier errors back
            feedback_prompt = FEEDBACK_PROMPT_TEMPLATE.format(
                language=lang_str,
                previous_code=code,
                feedback_type="Formal Verification",
                feedback_status="FAILED",
                error_messages=error_msgs,
            )

            response, _, _ = self.provider.generate(feedback_prompt, system_prompt)
            code = _extract_code(response, lang_str)
            best_code = code

        # Final test (for measurement)
        test_code = "\n".join(task.test_cases) if task.test_cases else ""
        tr = backend.run_tests(best_code, test_code) if test_code else None

        correct = (
            (best_vr is not None and best_vr.status == VerificationStatus.VERIFIED)
            and (tr is None or tr.status == TestStatus.PASSED)
        )

        return PipelineResult(
            task_id=task.task_id,
            model=self.provider.model_name(),
            agent_mode=self.MODE,
            language=task.language,
            final_code=best_code,
            verification_result=best_vr,
            test_result=tr,
            attempts=attempt,
            total_time_seconds=time.time() - start,
            correct=correct,
        )


class CombinedAgent:
    """Agent with feedback from BOTH formal verifier AND tests.

    This is the full proposed system — addresses Gap 2 by combining
    formal verification with testing for comprehensive feedback.
    """

    MODE = AgentMode.COMBINED

    def __init__(self, provider: LLMProvider, max_attempts: int = 5):
        self.provider = provider
        self.max_attempts = max_attempts

    def run(self, task: TaskSpec) -> PipelineResult:
        """Generate code with combined verifier + test feedback."""
        start = time.time()
        backend = _get_backend(task.language)
        lang_str = "dafny" if task.language == Language.DAFNY else "python"
        system_prompt = _get_system_prompt(task.language)

        prompt = INITIAL_PROMPT_TEMPLATE.format(
            description=task.description,
            language=lang_str,
            specification=task.specification,
        )

        response, _, _ = self.provider.generate(prompt, system_prompt)
        code = _extract_code(response, lang_str)

        best_code = code
        best_vr = None
        best_tr = None
        attempt = 1

        test_code = "\n".join(task.test_cases) if task.test_cases else ""

        for attempt in range(1, self.max_attempts + 1):
            # Guard spec integrity
            spec_ok, violations = backend.guard_spec_integrity(
                task.specification, code
            )

            if not spec_ok:
                ver_errors = "SPEC TAMPERING:\n" + "\n".join(violations)
                vr = VerificationResult(
                    status=VerificationStatus.FAILED,
                    errors=violations,
                )
            else:
                vr = backend.verify(code)

            best_vr = vr

            # Run tests
            tr = backend.run_tests(code, test_code) if test_code else TestResult(status=TestStatus.PASSED)
            best_tr = tr

            if (vr.status == VerificationStatus.VERIFIED and
                    tr.status == TestStatus.PASSED):
                best_code = code
                break

            # Build combined feedback
            ver_errors = "\n".join(vr.errors) if vr.errors else "No verification errors"
            test_errors = "\n".join(tr.failures) if tr.failures else "No test failures"

            feedback_prompt = COMBINED_FEEDBACK_TEMPLATE.format(
                language=lang_str,
                previous_code=code,
                verification_status=vr.status.value,
                verification_errors=ver_errors,
                test_status=tr.status.value,
                test_errors=test_errors,
            )

            response, _, _ = self.provider.generate(feedback_prompt, system_prompt)
            code = _extract_code(response, lang_str)
            best_code = code

        correct = (
            (best_vr is not None and best_vr.status == VerificationStatus.VERIFIED)
            and (best_tr is None or best_tr.status == TestStatus.PASSED)
        )

        return PipelineResult(
            task_id=task.task_id,
            model=self.provider.model_name(),
            agent_mode=self.MODE,
            language=task.language,
            final_code=best_code,
            verification_result=best_vr,
            test_result=best_tr,
            attempts=attempt,
            total_time_seconds=time.time() - start,
            correct=correct,
        )


def create_agent(
    mode: AgentMode,
    provider: LLMProvider,
    max_attempts: int = 5,
):
    """Factory function to create the appropriate agent.

    Args:
        mode: The agent mode to use.
        provider: The LLM provider instance.
        max_attempts: Maximum feedback loop iterations.

    Returns:
        An agent instance of the appropriate type.
    """
    agents = {
        AgentMode.SINGLE_SHOT: lambda: SingleShotAgent(provider),
        AgentMode.TESTING_ONLY: lambda: TestingOnlyAgent(provider, max_attempts),
        AgentMode.VERIFIER_FEEDBACK: lambda: VerifierFeedbackAgent(provider, max_attempts),
        AgentMode.COMBINED: lambda: CombinedAgent(provider, max_attempts),
    }
    return agents[mode]()
