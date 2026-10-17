"""
Pipeline orchestrator — the main entry point for running the
specification-verification feedback loop.

Ties together: benchmark loading → agent selection → code generation →
verification → testing → feedback → evaluation.
"""

import json
import os
import time
from typing import Optional

from src.schemas import AgentMode, Language, PipelineResult, TaskSpec
from src.agents.coding_agent import create_agent
from src.providers.llm_provider import LLMProvider, MockProvider
from src.evaluation.evaluator import Evaluator


class SpecLoopPipeline:
    """Main pipeline orchestrator for the SpecLoop system.

    Usage:
        pipeline = SpecLoopPipeline(provider=OpenAIProvider())
        pipeline.load_tasks("benchmarks/dafny_tasks/")
        results = pipeline.run_evaluation(
            modes=[AgentMode.TESTING_ONLY, AgentMode.VERIFIER_FEEDBACK],
        )
        pipeline.save_results()
    """

    def __init__(
        self,
        provider: Optional[LLMProvider] = None,
        max_attempts: int = 5,
        output_dir: str = "results",
    ):
        self.provider = provider or MockProvider()
        self.max_attempts = max_attempts
        self.output_dir = output_dir
        self.tasks: list[TaskSpec] = []
        self.evaluator = Evaluator()

    def load_tasks(self, tasks_dir: str) -> int:
        """Load benchmark tasks from a directory of JSON files.

        Each JSON file should contain a TaskSpec-compatible dict.

        Args:
            tasks_dir: Path to directory containing task JSON files.

        Returns:
            Number of tasks loaded.
        """
        self.tasks = []

        if not os.path.exists(tasks_dir):
            print(f"Warning: {tasks_dir} not found")
            return 0

        for filename in sorted(os.listdir(tasks_dir)):
            if not filename.endswith(".json"):
                continue

            filepath = os.path.join(tasks_dir, filename)
            try:
                with open(filepath, "r") as f:
                    data = json.load(f)

                task = TaskSpec(
                    task_id=data["task_id"],
                    description=data["description"],
                    language=Language(data["language"]),
                    specification=data["specification"],
                    reference_solution=data.get("reference_solution", ""),
                    test_cases=data.get("test_cases", []),
                    difficulty=data.get("difficulty", "medium"),
                    source_benchmark=data.get("source_benchmark", "custom"),
                )
                self.tasks.append(task)
            except (json.JSONDecodeError, KeyError) as e:
                print(f"Warning: Could not load {filename}: {e}")

        print(f"Loaded {len(self.tasks)} tasks from {tasks_dir}")
        return len(self.tasks)

    def run_single_task(
        self,
        task: TaskSpec,
        mode: AgentMode,
    ) -> PipelineResult:
        """Run a single task with the specified agent mode.

        Args:
            task: The benchmark task.
            mode: Agent operating mode.

        Returns:
            PipelineResult for this task.
        """
        agent = create_agent(mode, self.provider, self.max_attempts)
        result = agent.run(task)
        self.evaluator.add_result(result)
        return result

    def run_evaluation(
        self,
        modes: Optional[list[AgentMode]] = None,
        languages: Optional[list[Language]] = None,
        task_limit: Optional[int] = None,
    ) -> list[PipelineResult]:
        """Run full evaluation across modes and tasks.

        Args:
            modes: Agent modes to evaluate. Defaults to all four.
            languages: Filter tasks by language. Defaults to all.
            task_limit: Maximum tasks to evaluate (for quick testing).

        Returns:
            List of all PipelineResults.
        """
        if modes is None:
            modes = list(AgentMode)

        tasks = self.tasks
        if languages:
            tasks = [t for t in tasks if t.language in languages]
        if task_limit:
            tasks = tasks[:task_limit]

        print(f"\n{'='*60}")
        print(f"SpecLoop Evaluation")
        print(f"  Model: {self.provider.model_name()}")
        print(f"  Tasks: {len(tasks)}")
        print(f"  Modes: {[m.value for m in modes]}")
        print(f"  Max Attempts: {self.max_attempts}")
        print(f"{'='*60}\n")

        all_results = []
        total = len(tasks) * len(modes)
        done = 0

        for mode in modes:
            print(f"\n--- Agent Mode: {mode.value} ---")
            for task in tasks:
                done += 1
                print(f"  [{done}/{total}] Task {task.task_id}...", end=" ")

                result = self.run_single_task(task, mode)
                all_results.append(result)

                status = "PASS" if result.correct else "FAIL"
                print(f"{status} (attempts={result.attempts}, "
                      f"time={result.total_time_seconds:.1f}s)")

        return all_results

    def print_summary(self):
        """Print a formatted summary of evaluation results."""
        table = self.evaluator.comparison_table()

        if not table:
            print("No results to summarize.")
            return

        print(f"\n{'='*80}")
        print("EVALUATION SUMMARY")
        print(f"{'='*80}")

        try:
            from tabulate import tabulate
            print(tabulate(table, headers="keys", tablefmt="grid"))
        except ImportError:
            # Fallback: simple print
            for row in table:
                print(row)

    def save_results(self) -> tuple[str, str]:
        """Save all results to the output directory."""
        return self.evaluator.save_results(self.output_dir)
