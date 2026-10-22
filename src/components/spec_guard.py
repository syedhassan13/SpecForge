"""
Specification integrity guard.

A verifier only says "this code satisfies the spec that is in the file". If
the model edits the spec (drops an ensures clause, changes a predicate) or
uses an escape hatch (assume, {:axiom}, a bodyless lemma, a CrossHair
directive) then "verified" no longer means correct. The guard compares the
candidate against the original specification and rejects any change.

Dafny rules
  * the target method header (signature + requires/ensures/decreases) must
    appear unchanged (comments and whitespace ignored)
  * every other declaration in the spec file (predicates, functions, ...)
    must appear unchanged
  * no assume, {:axiom}, {:verify false}, {:only}, {:extern}, decreases *
  * no Dafny warning about bodyless declarations or assume statements

Python rules (checked on the AST, so formatting does not matter)
  * the target function keeps exactly the same decorators, arguments and
    return annotation
  * helper definitions and imports given in the spec are kept unchanged
  * no CrossHair directives, no rebinding or patching of icontract,
    no exec/eval/sys.modules tricks
"""

from __future__ import annotations

import ast
import re
from typing import Iterable, Optional

from src.schemas import GuardResult, Language

# ---------------------------------------------------------------------------
# Dafny
# ---------------------------------------------------------------------------

_DAFNY_CHEATS = [
    (re.compile(r"\bassume\b"), "uses an `assume` statement"),
    (re.compile(r"\{:\s*axiom"), "uses the {:axiom} attribute"),
    (re.compile(r"\{:\s*verify\s+false"), "disables verification with {:verify false}"),
    (re.compile(r"\{:\s*only"), "restricts verification with {:only}"),
    (re.compile(r"\{:\s*extern"), "declares an {:extern} member"),
    (re.compile(r"decreases\s*\*"), "uses `decreases *` (skips the termination proof)"),
]
_DAFNY_WARN_CHEATS = ("bodyless", "assume statement", "has no body")


def strip_dafny_comments(code: str) -> str:
    out, i, n = [], 0, len(code)
    in_str = False
    while i < n:
        c = code[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(code[i + 1])
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            out.append(c)
            i += 1
        elif code.startswith("//", i):
            j = code.find("\n", i)
            i = n if j < 0 else j
        elif code.startswith("/*", i):
            j = code.find("*/", i + 2)
            i = n if j < 0 else j + 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _norm(s: str) -> str:
    return " ".join(s.split())


def split_dafny_toplevel(code: str) -> list[str]:
    """Split a (comment free) Dafny file into top-level declarations.

    A declaration ends when the brace depth returns to zero. String and char
    literals are skipped so braces inside them do not count.
    """
    chunks, cur, depth, i, n = [], [], 0, 0, len(code)
    while i < n:
        c = code[i]
        cur.append(c)
        if c == '"':
            i += 1
            while i < n:
                cur.append(code[i])
                if code[i] == "\\" and i + 1 < n:
                    cur.append(code[i + 1])
                    i += 2
                    continue
                if code[i] == '"':
                    break
                i += 1
        elif c == "'" and i + 2 < n and (code[i + 2] == "'" or code[i + 1] == "\\"):
            # char literal such as 'a' or '\n'
            j = code.find("'", i + 2 if code[i + 1] != "\\" else i + 3)
            if j > 0:
                cur.extend(code[i + 1:j + 1])
                i = j
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                chunk = "".join(cur).strip()
                if chunk:
                    chunks.append(chunk)
                cur = []
        i += 1
    rest = "".join(cur).strip()
    if rest:
        chunks.append(rest)
    return chunks


def _target_re(entry: str) -> re.Pattern:
    return re.compile(r"\bmethod\s+" + re.escape(entry) + r"\s*[(<]")


def dafny_spec_parts(spec: str, entry: str) -> tuple[str, list[str]]:
    """Return (normalised target header, normalised other declarations)."""
    clean = strip_dafny_comments(spec)
    header, others = "", []
    for ch in split_dafny_toplevel(clean):
        if _target_re(entry).search(ch):
            header = _norm(ch[: ch.rfind("{")])
        else:
            others.append(_norm(ch))
    if not header:
        raise ValueError(f"target method {entry!r} not found in spec")
    return header, others


def guard_dafny(spec: str, code: str, entry: str,
                verifier_warnings: Optional[Iterable[str]] = None) -> GuardResult:
    header, others = dafny_spec_parts(spec, entry)
    clean = strip_dafny_comments(code)
    flat = _norm(clean)
    violations = []
    if (header + " {") not in flat:
        violations.append(
            f"the signature or requires/ensures clauses of method {entry} were changed; "
            f"they must stay exactly as: {header}")
    for decl in others:
        if decl not in flat:
            first = decl.split("{")[0].strip()[:120]
            violations.append(f"a declaration from the specification was changed or removed: {first}")
    for pat, why in _DAFNY_CHEATS:
        if pat.search(clean):
            violations.append(f"forbidden construct: {why}")
    for w in verifier_warnings or []:
        if any(k in w.lower() for k in _DAFNY_WARN_CHEATS):
            violations.append(f"forbidden construct reported by Dafny: {w}")
    return GuardResult(ok=not violations, violations=violations)


# ---------------------------------------------------------------------------
# Python / iContract
# ---------------------------------------------------------------------------

_PY_BANNED_CALLS = {"exec", "eval", "compile", "__import__", "setattr"}


def _find_func(tree: ast.Module, entry: str) -> Optional[ast.FunctionDef]:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == entry:
            return node
    return None


def guard_python(spec: str, code: str, entry: str) -> GuardResult:
    spec_tree = ast.parse(spec)
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return GuardResult(ok=False, checked=False,
                           violations=["the code could not be parsed, so the contracts could not be checked"])
    violations: list[str] = []
    sf, cf = _find_func(spec_tree, entry), _find_func(tree, entry)
    if sf is None:
        raise ValueError(f"function {entry!r} not found in spec")
    if cf is None:
        violations.append(f"function {entry} is missing")
    else:
        if [ast.dump(d) for d in sf.decorator_list] != [ast.dump(d) for d in cf.decorator_list]:
            violations.append(f"the @icontract decorators of {entry} were changed, removed or reordered; "
                              "they must be kept exactly as given")
        if ast.dump(sf.args) != ast.dump(cf.args) or ast.dump(sf.returns or ast.Constant(None)) != \
                ast.dump(cf.returns or ast.Constant(None)):
            violations.append(f"the signature of {entry} was changed")
        n_defs = sum(1 for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == entry)
        if n_defs > 1:
            violations.append(f"{entry} is defined more than once")
    have = {ast.dump(n) for n in tree.body}
    for node in spec_tree.body:
        if node is sf:
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.ClassDef, ast.Assign)):
            if ast.dump(node) not in have:
                violations.append("a definition or import from the specification was changed or removed: "
                                  + ast.unparse(node).splitlines()[0][:120])
    # escape hatches
    if re.search(r"#\s*crosshair\s*:", code, re.IGNORECASE):
        violations.append("forbidden construct: CrossHair directive comment")
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                base = t
                while isinstance(base, ast.Attribute):
                    base = base.value
                if isinstance(base, ast.Name) and base.id == "icontract":
                    violations.append("forbidden construct: modifies the icontract module")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _PY_BANNED_CALLS:
            violations.append(f"forbidden construct: call to {node.func.id}()")
        if isinstance(node, ast.Attribute) and node.attr == "modules" and \
                isinstance(node.value, ast.Name) and node.value.id == "sys":
            violations.append("forbidden construct: touches sys.modules")
        if isinstance(node, (ast.Import, ast.ImportFrom)) and node not in spec_tree.body:
            for alias in node.names:
                if alias.name.split(".")[0] == "crosshair" or alias.asname == "icontract":
                    violations.append("forbidden construct: imports crosshair or rebinds icontract")
    return GuardResult(ok=not violations, violations=sorted(set(violations), key=violations.index))


# ---------------------------------------------------------------------------

class SpecGuard:
    """Thin wrapper used by the agent and by the final oracle."""

    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    def check(self, language: Language, spec: str, code: str, entry: str,
              verifier_warnings: Optional[Iterable[str]] = None) -> GuardResult:
        if language is Language.DAFNY:
            return guard_dafny(spec, code, entry, verifier_warnings)
        return guard_python(spec, code, entry)
