# Development log (Phase 2)

Each entry: date, what failed or was missing, what we changed, and the
measured effect. Dev-split numbers come from `results/raw/dev/` (20 dev
tasks, one seed, gpt-4o-mini-2024-07-18) and can be re-read with
`python -m experiments.analyze` or the per-task table at the end. The test
split was not used for any of these decisions.

---

### 2026-10-18 · Iteration 0: auditing the Phase 1 prototype
**Observed.** Supervisor feedback asked for real-model baselines and more
tasks. While re-running the Phase 1 baseline we found that its Dafny tests
were written as `assert` statements inside `Main`. In Dafny `assert` is a
ghost statement: it is checked by the verifier and erased from compiled
code, and the Phase 1 backend compiled tests with `--no-verify`. We ran the
5 Phase 1 Dafny tasks with the **empty stub** as the "solution": all
**5/5 stubs passed the tests**. The testing-only baseline in Phase 1 was
therefore not testing anything on Dafny. Test results were also a single
pass/fail bit, and the 7 tasks (5 Dafny, 2 Python) were not paired.

**Changed.** New harness (`src/tasks/harness.py`) that stores each test once
in neutral JSON and renders it into Dafny/Python with ordinary `if`/`print`
checks, one marker line per case; per-case results in `TestResult`;
visible/held-out test split.

**Effect.** With the new harness the empty stub of every benchmark task is
rejected (admission check 4 in `validate_tasks.py`, 97/97 tasks, both
languages), and the generated Dafny tests contain no `assert`
(`tests/test_pipeline.py::TestHarness`).

---

### 2026-10-22 · Rewriting the integrity guard
**Observed.** The Phase 1 guard matched `requires/ensures/invariant` lines
with a regex and compared them as strings. It did not look at helper
predicates (a model could change `Sorted` to `true`), and it did not know
about `assume`, `{:verify false}`, `{:axiom}` or bodyless lemmas. In Python
it matched decorators with a regex that broke on multi-line lambdas.

**Changed.** Header-and-declaration comparison for Dafny, AST comparison for
Python, explicit escape-hatch rules, and Dafny's own bodyless/assume warnings
(`src/components/spec_guard.py`).

**Effect.** On the stress test (`experiments/guard_stress.py`, all tasks) the
guard rejects every tampering mutant and accepts every benign one; see
`results/guard_stress_summary.json` (numbers in the paper, Table on reliability).
