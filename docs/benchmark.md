# SpecLoop-VB benchmark: how the tasks were built

The Phase 1 benchmark had 7 hand-written tasks (5 Dafny, 2 Python) that were
not paired, so the language comparison was not controlled. For Phase 2 we
rebuilt the benchmark from the base paper's own data.

## Source

VERINA-BASIC (Ye et al., ICLR 2026) has 108 tasks. Each one was translated by
the VERINA authors into Lean 4 from a Dafny original in CloverBench (59 tasks)
or MBPP-DFY (49 tasks). We go back the other way: every task is written once
more as a Dafny program and once as a Python function with iContract
contracts, using VERINA's Lean pre/postcondition as the ground truth for the
meaning of the task and VERINA's positive tests as our tests.

11 tasks were left out because their types have no clean equivalent in both
languages (Float, Option, Map, UInt8, higher-order arguments, nested arrays)
or because the VERINA record is malformed (`verina_basic_39`). See
`data/raw/verina_basic/skipped.json` after running the extraction.

## Task file format (`data/tasks/vb_XXX.json`)

| field | meaning |
|---|---|
| `task_id` | `vb_` + VERINA number, zero padded (`verina_basic_51` -> `vb_051`) |
| `verina_id`, `upstream` | provenance |
| `entry_point` | method / function name (same in both languages) |
| `description` | language-neutral problem statement (no Lean wording) |
| `params`, `returns` | neutral types: `int nat bool char string list<T> tuple<A,B>` |
| `tests` | VERINA positive tests: `input`, `expected`, plus `unexpected` wrong outputs |
| `dafny.spec` / `python.spec` | the specification with an empty body marked `IMPLEMENT HERE` |
| `dafny.reference` / `python.reference` | a verified solution |
| `notes` (optional) | any deviation from VERINA and why |
| `probe_exempt` (optional) | probe categories the verifier cannot decide, with a reason |

Conventions:

* Dafny: `method Entry(<params>) returns (result: T)`, lists are `seq<T>`,
  strings are `string`, tuples are `(A, B)`, `nat` where VERINA uses `Nat`.
  Helper predicates/functions may be part of the spec. The spec body is
  exactly `{\n  // IMPLEMENT HERE\n}`.
* Python: `import icontract`, `from typing import List, Tuple`, the same
  parameter names, `@icontract.require` / `@icontract.ensure` decorators,
  body `# IMPLEMENT HERE` + `pass`. `Nat` parameters get a `>= 0`
  precondition, `Nat` results a `result >= 0` postcondition.

## Admission checks (`data/scripts/validate_tasks.py`)

A task is admitted only if all of the following hold in **both** languages:

1. the reference passes the specification integrity guard,
2. the reference verifies (Dafny) / CrossHair finds no counterexample (Python),
3. the reference passes every test,
4. the empty stub is rejected (the spec is not vacuous),
5. **spec probes**: for every test input, the spec accepts VERINA's expected
   output and rejects every wrong output VERINA lists for that input.

Probe 5 is our equivalence argument: the Dafny and the Python spec are asked
the same concrete questions and must give the same answers. In Dafny a probe
is a copy of the method with the inputs pinned by extra `requires` clauses
and the body returning the candidate output; in Python it is a copy of the
decorated function that returns the candidate output.

A second, independent check (`data/scripts/check_equivalence.py`) runs both
reference solutions on randomly generated inputs that satisfy the
precondition and compares the outputs (differential testing).
