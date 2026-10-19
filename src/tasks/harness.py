"""
Test harness generation.

Test cases are stored once, in neutral JSON, and turned into a Dafny `Main`
method or a Python runner here. Each case prints one marker line so that the
backends can report per-case outcomes instead of a single pass/fail bit.

Phase 1 note: the old Dafny tests used `assert`, which is a ghost statement
and is erased at run time, so they never checked anything when compiled.
The harness below uses ordinary `if` + `print`, which does run.
"""

from __future__ import annotations

import json
import re

from src.tasks.types import NType, dafny_literal, parse_type, python_literal

PASS = "SPECLOOP_PASS"
FAIL = "SPECLOOP_FAIL"
ERROR = "SPECLOOP_ERROR"

_MARK = re.compile(r"^(SPECLOOP_PASS|SPECLOOP_FAIL|SPECLOOP_ERROR)\s+(\d+)\s*(.*)$")


def _typed_params(params: list[dict]) -> list[tuple[str, NType]]:
    return [(p["name"], parse_type(p["type"])) for p in params]


def case_repr(case: dict) -> str:
    """Short human readable form of a test input, used in feedback."""
    return ", ".join(f"{k}={json.dumps(v)}" for k, v in case["input"].items())


def dafny_harness(entry: str, params: list[dict], returns: str, cases: list[dict]) -> str:
    rt = parse_type(returns)
    typed = _typed_params(params)
    lines = ["method Main() {"]
    for i, case in enumerate(cases):
        args = ", ".join(dafny_literal(case["input"][name], t) for name, t in typed)
        exp = dafny_literal(case["expected"], rt)
        lines.append(f"  var r{i} := {entry}({args});")
        lines.append(f"  if r{i} == {exp} {{ print \"{PASS} {i}\\n\"; }}")
        lines.append(f"  else {{ print \"{FAIL} {i} got=\", r{i}, \"\\n\"; }}")
    lines.append("}")
    return "\n".join(lines)


def python_harness(entry: str, params: list[dict], returns: str, cases: list[dict]) -> str:
    rt = parse_type(returns)
    typed = _typed_params(params)
    rows = []
    for case in cases:
        kw = "{" + ", ".join(f"{name!r}: {python_literal(case['input'][name], t)}"
                             for name, t in typed) + "}"
        rows.append(f"    ({kw}, {python_literal(case['expected'], rt)}),")
    body = "\n".join(rows)
    return f'''

def __specloop_run_tests():
    __cases = [
{body}
    ]
    for __i, (__kw, __exp) in enumerate(__cases):
        try:
            __got = {entry}(**__kw)
        except Exception as __e:
            print("{ERROR}", __i, (type(__e).__name__ + ": " + str(__e)).replace("\\n", " ")[:300])
            continue
        if __got == __exp:
            print("{PASS}", __i)
        else:
            print("{FAIL}", __i, "got=" + repr(__got)[:200])


if __name__ == "__main__":
    __specloop_run_tests()
'''


def parse_markers(output: str) -> dict[int, tuple[str, str]]:
    """Map case index -> (marker, detail) from harness output."""
    found: dict[int, tuple[str, str]] = {}
    for line in output.splitlines():
        m = _MARK.match(line.strip())
        if m:
            found[int(m.group(2))] = (m.group(1), m.group(3).strip())
    return found
