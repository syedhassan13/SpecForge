"""
Unit tests for the SpecLoop pipeline.

Tests cover:
- Schema data contracts
- Mock provider behavior
- Agent factory and mode selection
- Spec integrity guards
- Evaluator aggregation
- Pipeline end-to-end with mock provider
"""

import os
import sys
import json
import tempfile
import unittest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.schemas import (
    AgentMode,
    EvaluationMetrics,
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
from src.providers.llm_provider import MockProvider
from src.agents.coding_agent import (
    SingleShotAgent,
    TestingOnlyAgent,
    VerifierFeedbackAgent,
    CombinedAgent,
    create_agent,
    _extract_code,
)
from src.backends.dafny_backend import DafnyBackend
from src.backends.python_contract_backend import PythonContractBackend
from src.evaluation.evaluator import Evaluator
from src.pipeline import SpecLoopPipeline


class TestSchemas(unittest.TestCase):
    """Test data schema contracts."""

    def test_verification_result_success_rate(self):
        vr = VerificationResult(
            status=VerificationStatus.VERIFIED,
            verified_conditions=8,
            total_conditions=10,
        )
        self.assertAlmostEqual(vr.success_rate, 0.8)

    def test_verification_result_zero_conditions(self):
        vr = VerificationResult(status=VerificationStatus.ERROR)
        self.assertAlmostEqual(vr.success_rate, 0.0)

    def test_test_result_pass_rate(self):
        tr = TestResult(status=TestStatus.PASSED, passed=7, total=10)
        self.assertAlmostEqual(tr.pass_rate, 0.7)

    def test_pipeline_result_properties(self):
        pr = PipelineResult(
            task_id="t1",
            model="test",
            agent_mode=AgentMode.SINGLE_SHOT,
            language=Language.DAFNY,
            final_code="",
            verification_result=VerificationResult(status=VerificationStatus.VERIFIED),
            test_result=TestResult(status=TestStatus.PASSED),
        )
        self.assertTrue(pr.formally_verified)
        self.assertTrue(pr.tests_passed)

    def test_evaluation_metrics_rates(self):
        em = EvaluationMetrics(
            model="test",
            agent_mode=AgentMode.TESTING_ONLY,
            language=Language.DAFNY,
            total_tasks=10,
            verified_count=7,
            test_pass_count=8,
            correct_count=6,
        )
        self.assertAlmostEqual(em.verification_rate, 0.7)
        self.assertAlmostEqual(em.test_pass_rate, 0.8)
        self.assertAlmostEqual(em.correctness_rate, 0.6)

    def test_language_enum(self):
        self.assertEqual(Language.DAFNY.value, "dafny")
        self.assertEqual(Language.PYTHON_ICONTRACT.value, "python_icontract")

    def test_agent_mode_enum(self):
        self.assertEqual(AgentMode.COMBINED.value, "combined")
        modes = list(AgentMode)
        self.assertEqual(len(modes), 4)


class TestMockProvider(unittest.TestCase):
    """Test the mock LLM provider."""

    def test_default_response(self):
        provider = MockProvider(default_response="hello")
        text, pt, ct = provider.generate("test prompt")
        self.assertEqual(text, "hello")
        self.assertEqual(provider.call_count, 1)

    def test_keyword_matching(self):
        provider = MockProvider(
            responses={"dafny": "method Foo() {}"}
        )
        text, _, _ = provider.generate("Write Dafny code")
        self.assertEqual(text, "method Foo() {}")

    def test_model_name(self):
        provider = MockProvider(model="test-model-v1")
        self.assertEqual(provider.model_name(), "test-model-v1")


class TestCodeExtraction(unittest.TestCase):
    """Test code extraction from LLM responses."""

    def test_extract_from_fenced_block(self):
        response = "Here is the code:\n```dafny\nmethod Abs(x: int) {}\n```\n"
        code = _extract_code(response, "dafny")
        self.assertEqual(code, "method Abs(x: int) {}")

    def test_extract_plain_response(self):
        response = "method Abs(x: int) {}"
        code = _extract_code(response, "dafny")
        self.assertEqual(code, "method Abs(x: int) {}")

    def test_extract_python(self):
        response = "```python\ndef foo():\n    return 1\n```"
        code = _extract_code(response, "python")
        self.assertEqual(code, "def foo():\n    return 1")


class TestAgentFactory(unittest.TestCase):
    """Test agent creation factory."""

    def test_create_all_modes(self):
        provider = MockProvider()
        for mode in AgentMode:
            agent = create_agent(mode, provider)
            self.assertIsNotNone(agent)

    def test_single_shot_type(self):
        agent = create_agent(AgentMode.SINGLE_SHOT, MockProvider())
        self.assertIsInstance(agent, SingleShotAgent)

    def test_testing_only_type(self):
        agent = create_agent(AgentMode.TESTING_ONLY, MockProvider())
        self.assertIsInstance(agent, TestingOnlyAgent)

    def test_verifier_feedback_type(self):
        agent = create_agent(AgentMode.VERIFIER_FEEDBACK, MockProvider())
        self.assertIsInstance(agent, VerifierFeedbackAgent)

    def test_combined_type(self):
        agent = create_agent(AgentMode.COMBINED, MockProvider())
        self.assertIsInstance(agent, CombinedAgent)


class TestSpecIntegrity(unittest.TestCase):
    """Test specification integrity guards."""

    def test_dafny_spec_intact(self):
        backend = DafnyBackend()
        spec = "requires x > 0\n  ensures result >= 0\n"
        code = "method Foo(x: int) returns (result: int)\n  requires x > 0\n  ensures result >= 0\n{}\n"
        ok, violations = backend.guard_spec_integrity(spec, code)
        self.assertTrue(ok)

    def test_dafny_spec_missing_ensures(self):
        backend = DafnyBackend()
        spec = "requires x > 0\n  ensures result >= 0\n"
        code = "method Foo(x: int) returns (result: int)\n  requires x > 0\n{}\n"
        ok, violations = backend.guard_spec_integrity(spec, code)
        self.assertFalse(ok)
        self.assertTrue(len(violations) > 0)

    def test_python_spec_intact(self):
        backend = PythonContractBackend()
        spec = "@icontract.require(lambda x: x > 0)\n@icontract.ensure(lambda result: result >= 0)\n"
        code = "import icontract\n@icontract.require(lambda x: x > 0)\n@icontract.ensure(lambda result: result >= 0)\ndef foo(x): return x\n"
        ok, violations = backend.guard_spec_integrity(spec, code)
        self.assertTrue(ok)


class TestEvaluator(unittest.TestCase):
    """Test the evaluation aggregator."""

    def setUp(self):
        self.evaluator = Evaluator()
        # Add some mock results
        for i in range(5):
            self.evaluator.add_result(PipelineResult(
                task_id=f"task_{i}",
                model="gpt-4o",
                agent_mode=AgentMode.TESTING_ONLY,
                language=Language.DAFNY,
                final_code="",
                verification_result=VerificationResult(
                    status=VerificationStatus.VERIFIED if i < 3 else VerificationStatus.FAILED
                ),
                test_result=TestResult(
                    status=TestStatus.PASSED if i < 4 else TestStatus.FAILED
                ),
                correct=(i < 3),
                attempts=i + 1,
                total_time_seconds=2.0 * (i + 1),
            ))

    def test_compute_metrics(self):
        metrics = self.evaluator.compute_metrics(
            model="gpt-4o",
            agent_mode=AgentMode.TESTING_ONLY,
        )
        self.assertEqual(metrics.total_tasks, 5)
        self.assertEqual(metrics.verified_count, 3)
        self.assertEqual(metrics.test_pass_count, 4)
        self.assertEqual(metrics.correct_count, 3)

    def test_comparison_table(self):
        table = self.evaluator.comparison_table()
        self.assertEqual(len(table), 1)
        self.assertEqual(table[0]["Model"], "gpt-4o")

    def test_save_results(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.evaluator.save_results(tmpdir)
            files = os.listdir(tmpdir)
            self.assertTrue(any("results_" in f for f in files))
            self.assertTrue(any("comparison_" in f for f in files))


class TestPipelineEndToEnd(unittest.TestCase):
    """Test the full pipeline with mock provider."""

    def test_load_tasks(self):
        pipeline = SpecLoopPipeline(provider=MockProvider())
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        tasks_dir = os.path.join(base_dir, "benchmarks", "dafny_tasks")
        n = pipeline.load_tasks(tasks_dir)
        self.assertGreater(n, 0)

    def test_mock_evaluation(self):
        """Run a quick evaluation with mock provider — verifies the full pipeline works."""
        provider = MockProvider(
            default_response="method Abs(x: int) returns (result: int)\n"
                           "  ensures result >= 0\n"
                           "{\n  result := 0;\n}\n"
        )
        pipeline = SpecLoopPipeline(
            provider=provider,
            max_attempts=2,
        )
        
        # Create a minimal task inline
        from src.schemas import TaskSpec
        pipeline.tasks = [
            TaskSpec(
                task_id="test_task",
                description="Test task",
                language=Language.DAFNY,
                specification="ensures result >= 0",
                reference_solution="result := 0;",
            )
        ]

        results = pipeline.run_evaluation(
            modes=[AgentMode.SINGLE_SHOT],
            task_limit=1,
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].task_id, "test_task")


if __name__ == "__main__":
    unittest.main()
