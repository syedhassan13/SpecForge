# SpecLoop: Specification-Driven Verification Feedback Pipeline

A formal specification-driven development pipeline that improves the correctness and reliability of LLM coding agents through a verification feedback loop.

## Project Overview

SpecLoop builds a feedback loop in which an LLM coding agent generates code, a formal verification tool checks it against the specification, and any failures are sent back to the agent for repair. The system compares:

1. **Specification Languages**: Dafny (purpose-built) vs. Python with iContract + CrossHair (mainstream)
2. **Verification + Testing**: Combined formal verification with runtime testing
3. **Cross-Model Evaluation**: Multiple LLMs (GPT-4o, Claude, etc.) against testing-only baseline

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    SpecLoop Pipeline                     │
│                                                          │
│  ┌──────────┐    ┌──────────────┐    ┌───────────────┐  │
│  │ Benchmark │───>│  LLM Agent   │───>│   Verifier    │  │
│  │  Loader   │    │  (4 modes)   │<───│   Backend     │  │
│  └──────────┘    └──────────────┘    └───────────────┘  │
│                         │                     │          │
│                         v                     v          │
│                  ┌──────────────┐    ┌───────────────┐  │
│                  │  Generated   │    │  Test Runner   │  │
│                  │    Code      │    │   Backend      │  │
│                  └──────────────┘    └───────────────┘  │
│                         │                     │          │
│                         v                     v          │
│                  ┌──────────────────────────────────┐   │
│                  │         Evaluator                 │   │
│                  │  (Metrics, Comparison Tables)     │   │
│                  └──────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

## Agent Modes

| Mode | Feedback Source | Description |
|------|----------------|-------------|
| `single_shot` | None | One-shot generation (ablation control) |
| `testing_only` | Runtime tests | Baseline — tests-only feedback |
| `verifier_feedback` | Formal verifier | Verifier errors guide repair |
| `combined` | Both | Full system — verifier + tests |

## Setup

### Prerequisites
- Python 3.10+
- Dafny 4.x (for Dafny verification tasks)

### Installation

```bash
# Clone the repository
git clone https://github.com/syedhassan13/SpecForge.git
cd SpecForge

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# OR
venv\Scripts\activate     # Windows

# Install dependencies
pip install -r requirements.txt

# (Optional) Install Dafny
# Download from https://github.com/dafny-lang/dafny/releases
```

### Configuration

```bash
# Copy .env.example and add your API keys
cp .env.example .env
# Edit .env with your API keys
```

## Running the Baseline

### Quick Test (Mock Provider — No API Key Needed)

```bash
# Run with mock LLM (validates pipeline works end-to-end)
python run_baseline.py --mode single_shot --model mock --tasks benchmarks/dafny_tasks/

# Run all modes
python run_baseline.py --mode all --model mock --tasks benchmarks/dafny_tasks/
```

### With Real LLM (Requires API Key)

```bash
# OpenAI GPT-4o
python run_baseline.py --mode combined --model gpt-4o --tasks benchmarks/dafny_tasks/ \
    --api-key YOUR_KEY

# Anthropic Claude  
python run_baseline.py --mode combined --model claude-sonnet-4-20250514 --tasks benchmarks/dafny_tasks/ \
    --api-key YOUR_KEY

# Full cross-model evaluation
python run_baseline.py --mode all --model gpt-4o --tasks benchmarks/dafny_tasks/
python run_baseline.py --mode all --model claude-sonnet-4-20250514 --tasks benchmarks/dafny_tasks/
```

### Python Contract Tasks

```bash
python run_baseline.py --mode combined --model mock --tasks benchmarks/python_tasks/
```

## Running Tests

```bash
python -m pytest tests/ -v
# OR
python -m unittest tests.test_pipeline -v
```

## Project Structure

```
specloop/
├── src/
│   ├── __init__.py
│   ├── schemas.py              # Core data contracts
│   ├── pipeline.py             # Main orchestrator
│   ├── backends/
│   │   ├── dafny_backend.py    # Dafny verifier + test runner
│   │   └── python_contract_backend.py  # iContract + CrossHair
│   ├── agents/
│   │   ├── coding_agent.py     # 4 agent implementations
│   │   └── prompts.py          # Prompt templates
│   ├── providers/
│   │   └── llm_provider.py     # OpenAI, Anthropic, Mock providers
│   └── evaluation/
│       └── evaluator.py        # Metrics aggregation
├── benchmarks/
│   ├── dafny_tasks/            # Dafny benchmark tasks (JSON)
│   └── python_tasks/           # Python iContract tasks (JSON)
├── tests/
│   └── test_pipeline.py        # Unit tests
├── results/                    # Evaluation output
├── docs/                       # Documentation & diagrams
├── run_baseline.py             # CLI entry point
├── requirements.txt
├── .env.example
└── README.md
```

## Evaluation Metrics

- **Verification Rate**: Fraction of tasks passing formal verification
- **Test Pass Rate**: Fraction of tasks passing all runtime tests
- **Correctness Rate**: Fraction of tasks correct on both verification and tests
- **Average Attempts**: Mean feedback loop iterations to convergence
- **Average Time**: Mean wall-clock time per task

## Research Gaps Addressed

1. **Gap 1**: No controlled comparison of contract languages (Dafny vs. iContract) under one agent loop
2. **Gap 2**: Existing repair loops use verifier errors only; tests used just for scoring
3. **Gap 3**: Models compared in single snapshot with no testing-only baseline

## License

MIT License

## Team

- **Syed Muhammad Hassan** — 23i-0519 (Group Head)
- **Abdul Majeed** — 23p-3038


## Acknowledgments

Base paper: VERINA — Benchmarking LLMs on Verifiable Code Generation (ICLR 2026)
