"""
Prompt templates.

All agent modes share the same system prompt and the same first prompt, so
for a given task, model and seed the first candidate is identical across
modes (the request is cached). Modes only differ in the feedback they get.
"""

SYSTEM_PROMPT_DAFNY = """You are an expert Dafny programmer working with the Dafny 4 verifier.
You implement methods so that they satisfy a given formal specification.

Rules:
1. Keep the given specification exactly as it is: the method signature, every requires/ensures clause and every given predicate, function or lemma. Do not weaken, strengthen, reorder or reformat them.
2. Write the method body. You may add loop invariants, decreases clauses, assert statements, and new helper functions, predicates, lemmas (with proofs) or methods.
3. Forbidden: assume statements, {:axiom}, {:verify false}, {:only}, {:extern}, `decreases *`, and lemmas or methods without a body. Programs that use them are rejected.
4. Do not write a Main method.
5. The program must pass `dafny verify` with no errors and must compute the right results.

Answer with a JSON object: "analysis" (a few sentences about the approach or the fix) and "code" (the complete Dafny program, including all given declarations)."""

SYSTEM_PROMPT_PYTHON = """You are an expert Python programmer who writes code against iContract specifications.
You implement functions so that they satisfy the given contracts.

Rules:
1. Keep the given specification exactly as it is: the imports, every @icontract.require and @icontract.ensure decorator, the function signature and any given helper functions.
2. Write the function body. You may add new helper functions.
3. Forbidden: CrossHair directive comments, changing or patching icontract, exec/eval, touching sys.modules.
4. The code is checked with CrossHair (symbolic execution looking for inputs that break a contract) and by running tests with the contracts enabled.

Answer with a JSON object: "analysis" (a few sentences about the approach or the fix) and "code" (the complete Python module, including the imports and decorators)."""


INITIAL_PROMPT_TEMPLATE = """## Task
{description}

## Specification ({language})
```{fence}
{specification}
```

Implement the body marked IMPLEMENT HERE so that the program satisfies the specification. Return the complete program."""


REPAIR_PROMPT_TEMPLATE = """## Task
{description}

## Specification ({language}, must stay unchanged)
```{fence}
{specification}
```

## Your previous program (attempt {attempt})
```{fence}
{previous_code}
```

## Feedback on that program
{feedback}
{history}
Fix the program. Return the complete corrected program. In "strategy" say "patch" if you kept the previous approach and fixed it, or "rewrite" if you started over."""


REWRITE_NOTE = """
## Note
The last attempts kept failing in the same way. Do not keep patching the same idea: start from the specification again and write a new implementation with a different approach (different loop structure, different invariants)."""


# Phase 1 template, used only by the "router off" ablation of the combined agent
COMBINED_FEEDBACK_TEMPLATE = """## Formal Verification Result
Status: {verification_status}
{verification_errors}

## Test Execution Result
Status: {test_status}
{test_errors}"""


INITIAL_SCHEMA = {
    "name": "candidate_program",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {"analysis": {"type": "string"}, "code": {"type": "string"}},
        "required": ["analysis", "code"],
        "additionalProperties": False,
    },
}

REPAIR_SCHEMA = {
    "name": "repaired_program",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "analysis": {"type": "string"},
            "strategy": {"type": "string", "enum": ["patch", "rewrite"]},
            "code": {"type": "string"},
        },
        "required": ["analysis", "strategy", "code"],
        "additionalProperties": False,
    },
}


# ---------------------------------------------------------------------------
# VERINA-style CodeGen prompt (experiment E2). Mirrors VERINA's Prompt 1:
# expert instruction + task description + template with the reference spec,
# 2-shot examples taken from the dev split, plain-text answer.
# ---------------------------------------------------------------------------

VERINA_STYLE_INSTRUCTIONS = {
    "dafny": ("You are an expert in Dafny programming and verification. Please generate a Dafny program "
              "that finishes the task described in `task_description` using the template provided in "
              "`task_template`. The `task_template` is a Dafny code snippet with the reference "
              "specification; the body marked IMPLEMENT HERE is the code to be generated. The program "
              "should be well documented with comments if necessary and follow Dafny 4 best practices. "
              "Return the complete program in a single ```dafny code block."),
    "python": ("You are an expert in Python programming with iContract contracts. Please generate a Python "
               "program that finishes the task described in `task_description` using the template provided "
               "in `task_template`. The `task_template` is a Python code snippet with the reference "
               "specification as iContract decorators; the body marked IMPLEMENT HERE is the code to be "
               "generated. The program should be well documented with comments if necessary and follow "
               "Python best practices. Return the complete program in a single ```python code block."),
}

VERINA_STYLE_EXAMPLE = """task_description:
{description}

task_template:
```{fence}
{specification}
```
"""
