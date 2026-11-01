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

---

### 2026-10-26 · Rebuilding the benchmark from VERINA-BASIC
**Missing.** 7 tasks were too few for any significance test (supervisor
feedback) and the language comparison was not controlled.

**Changed.** Extracted VERINA-BASIC (108 tasks), kept 97 whose types exist in
both languages, wrote paired Dafny and Python/iContract specs plus verified
references, and added `validate_tasks.py` with five admission checks
including spec probes (`docs/benchmark.md`).

**Effect.** 97/97 tasks admitted (`data/validation_report.json`). Building
the probes exposed a real problem: Dafny cannot decide existential
postconditions on concrete inputs, so several Dafny specs were rewritten into
equivalent decidable forms (32 tasks carry a `notes` field explaining a
reformulation or a deviation from VERINA), and 3 tasks
keep a documented `probe_exempt` for accept-probes Dafny cannot decide.

---

### 2026-10-27 · Model choice under the API budget
**Constraint.** The project budget for API calls was capped at 2 USD in
total. The Phase 1 plan (GPT-4o and Claude Sonnet) and our later plan
(GPT-4.1 + GPT-4o-mini) do not fit.

**Changed.** All experiments use gpt-4o-mini-2024-07-18, which VERINA also
evaluates (44.0% CodeGen pass@1 on VERINA-BASIC). A global spend cap read
from the response cache stops any run that would cross the budget
(`src/pipeline.py`). E2 uses 3 samples per task instead of VERINA's 5.

---

### 2026-10-28 · Iteration 1: diagnostic normaliser (Gap 1)
**Observed (it0).** Phase 1 style combined agent (raw tool output, verifier
and test output pasted together): Dafny 12/20 correct, Python 20/20.
Raw Dafny output refers to `candidate.dfy(18,2)` positions the model never
sees.

**Changed.** Normaliser: one taxonomy for Dafny and CrossHair, offending
line and spec clause quoted, one-line meaning per error kind.

**Effect.** Dafny 12/20 (no change), all-tests-pass 16 -> 17/20, Python
20/20. No measurable gain in correctness on dev with this model.

---

### 2026-10-29 · Iteration 2: feedback router (Gap 2)
**Changed.** Router classifies every failed check (SPEC_TAMPER, SYNTAX,
LOGIC_BUG, PROOF_GAP) and gives a class-specific instruction.

**Effect.** Dafny 12/20, Python 20/20. Same tasks solved; vb_062 now solved
(after 4 attempts) but vb_069 lost. Kept because the classification is also
what the failure analysis needs, and because the effect is within noise.

---

### 2026-10-30 · Iteration 3: stagnation monitor
**Observed.** In it2, 8 Dafny runs used all 5 attempts and 4 of them
resubmitted an identical program at least once.

**Changed.** Fingerprint each failure; on a repeat (or an identical program)
the next call is a "rewrite" with temperature 0.6.

**Effect.** Dafny 12/20 (no change), 10 strategy switches fired, none of
them turned a failing task into a solved one on dev.

---

### 2026-11-01 · Iteration 4: fix hints and compile-error routing
**Observed.** In it0-it3, three Dafny tasks (vb_017, vb_082, vb_105) failed
with compile errors in **all five attempts of all four iterations**. The
errors came from habits of other languages: `|arr|` on an array,
`new string(...)`, `StringBuilder`, `if ... then {` in a statement, a second
`var result` next to the out-parameter. The normalised message names the
problem but not the fix. We also found a routing bug: when a program
verifies but does not compile (ghost function in executable code), the
router showed the verifier report instead of the compile error.

**Changed.** A table of generic fix hints keyed on Dafny error messages
(never on a task), and SYNTAX routing that shows the compile error from the
test run when the verifier did not see it.

**Effect.** Dafny 13/20 (+1). All three persistent compile-error tasks are
now solved (vb_017 in 2 attempts, vb_082 and vb_105 in 3), but vb_032 and
vb_062 are lost. Mean model calls per Dafny run 3.00 -> 2.75, cost 0.0194
-> 0.0182 USD.
