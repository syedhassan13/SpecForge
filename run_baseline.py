"""
SpecLoop CLI — command-line interface for the verification-feedback pipeline.

Usage:
    python run_baseline.py --mode testing_only --tasks benchmarks/dafny_tasks/
    python run_baseline.py --mode verifier_feedback --tasks benchmarks/python_tasks/
    python run_baseline.py --mode combined --model gpt-4o --tasks benchmarks/dafny_tasks/
"""

import argparse
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.schemas import AgentMode, Language
from src.pipeline import SpecLoopPipeline
from src.providers.llm_provider import MockProvider, OpenAIProvider, AnthropicProvider


def create_provider(model: str, api_key: str = ""):
    """Create the appropriate LLM provider based on model name."""
    if model.startswith("gpt") or model.startswith("o1") or model.startswith("o3"):
        return OpenAIProvider(model=model, api_key=api_key)
    elif model.startswith("claude"):
        return AnthropicProvider(model=model, api_key=api_key)
    elif model == "mock":
        return MockProvider()
    else:
        # Default to OpenAI-compatible
        return OpenAIProvider(model=model, api_key=api_key)


def main():
    parser = argparse.ArgumentParser(
        description="SpecLoop: Specification-Driven Verification Feedback Pipeline"
    )
    parser.add_argument(
        "--mode",
        type=str,
        default="testing_only",
        choices=["single_shot", "testing_only", "verifier_feedback", "combined", "all"],
        help="Agent mode (default: testing_only)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="mock",
        help="LLM model name (default: mock for testing)",
    )
    parser.add_argument(
        "--tasks",
        type=str,
        default="benchmarks/dafny_tasks",
        help="Path to benchmark tasks directory",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=5,
        help="Maximum feedback loop iterations (default: 5)",
    )
    parser.add_argument(
        "--task-limit",
        type=int,
        default=None,
        help="Limit number of tasks (for quick testing)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="results",
        help="Output directory for results (default: results)",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default="",
        help="API key for the LLM provider (or set env variable)",
    )

    args = parser.parse_args()

    # Create provider
    provider = create_provider(args.model, args.api_key)

    # Determine modes
    if args.mode == "all":
        modes = list(AgentMode)
    else:
        modes = [AgentMode(args.mode)]

    # Create and run pipeline
    pipeline = SpecLoopPipeline(
        provider=provider,
        max_attempts=args.max_attempts,
        output_dir=args.output,
    )

    # Load tasks
    n_tasks = pipeline.load_tasks(args.tasks)
    if n_tasks == 0:
        print("Error: No tasks found. Check the --tasks path.")
        sys.exit(1)

    # Run evaluation
    results = pipeline.run_evaluation(
        modes=modes,
        task_limit=args.task_limit,
    )

    # Print summary
    pipeline.print_summary()

    # Save results
    raw_path, table_path = pipeline.save_results()
    print(f"\nResults saved to:")
    print(f"  Raw: {raw_path}")
    print(f"  Table: {table_path}")


if __name__ == "__main__":
    main()
