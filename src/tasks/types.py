"""
Language-neutral type system used by the benchmark.

Every task signature is written with a small set of neutral types so that the
same task (and the same test cases) can be rendered into Dafny and into
Python/iContract. This is what makes the Gap 1 comparison controlled: both
languages see identical inputs and expected outputs.

Supported types:
    int, nat, bool, char, string, list<T>, tuple<T1, T2, ...>
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class NType:
    """A parsed neutral type. `args` holds element types for list/tuple."""
    kind: str
    args: tuple["NType", ...] = field(default_factory=tuple)

    def __str__(self) -> str:
        if self.kind == "list":
            return f"list<{self.args[0]}>"
        if self.kind == "tuple":
            return "tuple<" + ", ".join(str(a) for a in self.args) + ">"
        return self.kind


SCALARS = {"int", "nat", "bool", "char", "string"}


def _split_top(s: str) -> list[str]:
    """Split a comma separated list but ignore commas nested inside <>."""
    parts, depth, cur = [], 0, ""
    for ch in s:
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        parts.append(cur.strip())
    return parts


def parse_type(text: str) -> NType:
    text = text.strip()
    if text in SCALARS:
        return NType(text)
    if text.startswith("list<") and text.endswith(">"):
        return NType("list", (parse_type(text[5:-1]),))
    if text.startswith("tuple<") and text.endswith(">"):
        return NType("tuple", tuple(parse_type(p) for p in _split_top(text[6:-1])))
    raise ValueError(f"unsupported neutral type: {text!r}")


# ---------------------------------------------------------------------------
# Rendering type names
# ---------------------------------------------------------------------------

def dafny_type(t: NType) -> str:
    if t.kind in ("int", "nat", "bool", "char", "string"):
        return t.kind
    if t.kind == "list":
        return f"seq<{dafny_type(t.args[0])}>"
    if t.kind == "tuple":
        return "(" + ", ".join(dafny_type(a) for a in t.args) + ")"
    raise ValueError(t)


def python_type(t: NType) -> str:
    base = {"int": "int", "nat": "int", "bool": "bool", "char": "str", "string": "str"}
    if t.kind in base:
        return base[t.kind]
    if t.kind == "list":
        return f"List[{python_type(t.args[0])}]"
    if t.kind == "tuple":
        return "Tuple[" + ", ".join(python_type(a) for a in t.args) + "]"
    raise ValueError(t)


# ---------------------------------------------------------------------------
# Rendering literal values (values come from the JSON test files)
# ---------------------------------------------------------------------------

def _dafny_char_body(c: str, quote: str) -> str:
    if c == "\\":
        return "\\\\"
    if c == quote:
        return "\\" + quote
    if c == "\n":
        return "\\n"
    if c == "\t":
        return "\\t"
    if c == "\r":
        return "\\r"
    if 32 <= ord(c) < 127:
        return c
    # Dafny 4 uses unicode chars by default, escaped as \U{hex}
    return "\\U{" + format(ord(c), "x") + "}"


def dafny_literal(value, t: NType) -> str:
    if t.kind in ("int", "nat"):
        return str(int(value))
    if t.kind == "bool":
        return "true" if value else "false"
    if t.kind == "char":
        return "'" + _dafny_char_body(value, "'") + "'"
    if t.kind == "string":
        return '"' + "".join(_dafny_char_body(c, '"') for c in value) + '"'
    if t.kind == "list":
        return "[" + ", ".join(dafny_literal(v, t.args[0]) for v in value) + "]"
    if t.kind == "tuple":
        return "(" + ", ".join(dafny_literal(v, a) for v, a in zip(value, t.args)) + ")"
    raise ValueError(t)


def python_literal(value, t: NType) -> str:
    if t.kind in ("int", "nat"):
        return str(int(value))
    if t.kind == "bool":
        return "True" if value else "False"
    if t.kind in ("char", "string"):
        return repr(value)
    if t.kind == "list":
        return "[" + ", ".join(python_literal(v, t.args[0]) for v in value) + "]"
    if t.kind == "tuple":
        inner = ", ".join(python_literal(v, a) for v, a in zip(value, t.args))
        return "(" + inner + ("," if len(t.args) == 1 else "") + ")"
    raise ValueError(t)


def check_value(value, t: NType) -> bool:
    """Light runtime check that a JSON value matches the neutral type."""
    if t.kind == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if t.kind == "nat":
        return isinstance(value, int) and not isinstance(value, bool) and value >= 0
    if t.kind == "bool":
        return isinstance(value, bool)
    if t.kind == "char":
        return isinstance(value, str) and len(value) == 1
    if t.kind == "string":
        return isinstance(value, str)
    if t.kind == "list":
        return isinstance(value, list) and all(check_value(v, t.args[0]) for v in value)
    if t.kind == "tuple":
        return (isinstance(value, list) and len(value) == len(t.args)
                and all(check_value(v, a) for v, a in zip(value, t.args)))
    return False
