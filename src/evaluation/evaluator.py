"""
Evaluation and metrics computation module.

Aggregates results from pipeline runs across tasks, models, agent modes,
and specification languages to compute the metrics needed for cross-model
and cross-language comparison.
"""

import json
import os
from collections import defaultdict
from datetime import datetime
from typing import Optional

from src.schemas import (
    AgentMode,
    EvaluationMetrics,
    Language,
    PipelineResult,
    VerificationStatus,
    TestStatus,
)


class Evaluator:
    """Aggregates and computes metrics across pipeline runs.

    Collects PipelineResult objects and computes per-model, per-mode,
    and per-language metrics for the cross-comparison evaluation.
    """

    def __init__(self):
        self.results: list[PipelineResult] = []

    def add_result(self, result: PipelineResult):
        """Add a single pipeline result."""
        self.results.append(result)

    def add_results(self, results: list[PipelineResult]):
        """Add multiple pipeline results."""
        self.results.extend(results)

    def compute_metrics(
        self,
        model: Optional[str] = None,
        agent_mode: Optional[AgentMode] = None,
        language: Optional[Language] = None,
    ) -> EvaluationMetrics:
        """Compute aggregated metrics for the specified filters.

        Args:
            model: Filter by model name (None = all).
            agent_mode: Filter by agent mode (None = all).
            language: Filter by language (None = all).

        Returns:
            EvaluationMetrics with aggregated counts and rates.
        """
        filtered = self.results

        if model:
            filtered = [r for r in filtered if r.model == model]
        if agent_mode:
            filtered = [r for r in filtered if r.agent_mode == agent_mode]
        if language:
            filtered = [r for r in filtered if r.language == language]

        if not filtered:
            return EvaluationMetrics(
                model=model or "all",
                agent_mode=agent_mode or AgentMode.SINGLE_SHOT,
                language=language or Language.DAFNY,
            )

        verified = sum(1 for r in filtered if r.formally_verified)
        test_pass = sum(1 for r in filtered if r.tests_passed)
        correct = sum(1 for r in filtered if r.correct)
        avg_attempts = sum(r.attempts for r in filtered) / len(filtered)
        avg_time = sum(r.total_time_seconds for r in filtered) / len(filtered)

        return EvaluationMetrics(
            model=model or "all",
            agent_mode=agent_mode or filtered[0].agent_mode,
            language=language or filtered[0].language,
            total_tasks=len(filtered),
            verified_count=verified,
            test_pass_count=test_pass,
            correct_count=correct,
            avg_attempts=avg_attempts,
            avg_time=avg_time,
        )

    def comparison_table(self) -> list[dict]:
        """Generate a cross-model, cross-mode comparison table.

        Returns a list of dicts, one per (model, mode, language) combination,
        suitable for tabulate or pandas DataFrame.
        """
        groups = defaultdict(list)
        for r in self.results:
            key = (r.model, r.agent_mode.value, r.language.value)
            groups[key].append(r)

        table = []
        for (model, mode, lang), results in sorted(groups.items()):
            metrics = self.compute_metrics(
                model=model,
                agent_mode=AgentMode(mode),
                language=Language(lang),
            )
            table.append({
                "Model": model,
                "Agent Mode": mode,
                "Language": lang,
                "Tasks": metrics.total_tasks,
                "Verified": metrics.verified_count,
                "Tests Passed": metrics.test_pass_count,
                "Correct": metrics.correct_count,
                "Verification Rate": f"{metrics.verification_rate:.1%}",
                "Test Pass Rate": f"{metrics.test_pass_rate:.1%}",
                "Correctness Rate": f"{metrics.correctness_rate:.1%}",
                "Avg Attempts": f"{metrics.avg_attempts:.1f}",
                "Avg Time (s)": f"{metrics.avg_time:.1f}",
            })

        return table

    def save_results(self, output_dir: str = "results"):
        """Save all results and metrics to JSON files.

        Args:
            output_dir: Directory to save results in.
        """
        os.makedirs(output_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Save raw results
        raw_path = os.path.join(output_dir, f"results_{timestamp}.json")
        raw_data = []
        for r in self.results:
            raw_data.append({
                "task_id": r.task_id,
                "model": r.model,
                "agent_mode": r.agent_mode.value,
                "language": r.language.value,
                "correct": r.correct,
                "formally_verified": r.formally_verified,
                "tests_passed": r.tests_passed,
                "attempts": r.attempts,
                "time_seconds": r.total_time_seconds,
            })
        with open(raw_path, "w") as f:
            json.dump(raw_data, f, indent=2)

        # Save comparison table
        table_path = os.path.join(output_dir, f"comparison_{timestamp}.json")
        with open(table_path, "w") as f:
            json.dump(self.comparison_table(), f, indent=2)

        return raw_path, table_path
