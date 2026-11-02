"""
Diagnostic normaliser (Gap 1 component).

Dafny and CrossHair report problems in very different shapes. Dafny gives a
file position and a message ("a postcondition could not be proved on this
return path") plus a "Related location" that points at the clause; CrossHair
gives a contract line and a concrete call that breaks it. Both refer to line
numbers the model never sees.

The normaliser maps both into one taxonomy (`Diagnostic.kind`) and attaches
the offending source line and the related specification clause, so the same
agent loop can be run on either language with comparable feedback. With the
component switched off the agent receives the raw tool output instead
(ablation E5).
"""

from __future__ import annotations

import re

from src.schemas import Diagnostic, Language, VerificationResult, VerificationStatus

_DFY = re.compile(r"^(?P<file>.+?)\((?P<line>\d+),(?P<col>\d+)\): "
                  r"(?P<sev>Error|Warning|Related location): (?P<msg>.*)$")
_CH = re.compile(r"^line (?P<line>\d+): (?P<msg>.*)$")

# message fragment -> kind (checked in order)
_DAFNY_KINDS = [
    ("postcondition", "postcondition"),
    ("invariant could not be proved on entry", "invariant_entry"),
    ("invariant could not be proved to be maintained", "invariant_maintained"),
    ("might not be maintained", "invariant_maintained"),
    ("decreases", "termination"),
    ("termination", "termination"),
    ("index out of range", "index_bounds"),
    ("precondition", "call_precondition"),
    ("assertion", "assertion"),
    ("subset constraint", "subset_type"),
    ("out of resource", "timeout"),
    ("timed out", "timeout"),
]

KIND_HINTS = {
    "postcondition": "the result may not satisfy this ensures clause",
    "invariant_entry": "this loop invariant does not hold before the loop starts",
    "invariant_maintained": "this loop invariant is not preserved by the loop body",
    "termination": "the verifier cannot show that the loop or recursion terminates",
    "index_bounds": "an index may be out of range here",
    "call_precondition": "a call here may violate the callee's requires clause",
    "assertion": "this assertion may not hold",
    "subset_type": "a value may violate its subset type (for example nat must be >= 0)",
    "counterexample": "CrossHair found inputs for which the contract fails",
    "exception": "CrossHair found inputs that make the function raise",
    "syntax": "the program does not parse",
    "resolution": "a name or type error stops the program from compiling",
    "timeout": "the verifier ran out of time",
    "invariant_comment": "write each one as `invariant <expr>` between the `while` line and `{`",
    "missing_invariant": ("add `invariant` clauses that bound the loop index and relate the partial "
                          "result to the ensures clauses"),
}


# Added in dev iteration 4 (docs/devlog.md): most persistent dev failures were
# compile errors caused by habits from other languages. The messages Dafny
# prints name the problem but not the fix, so we attach a generic fix hint.
# The table is keyed on the error message only, never on a task.
FIX_HINTS = [
    (r"size operator expects a collection argument \(instead got array",
     "for an array use a.Length; or keep the result as a seq and append with r := r + [x]"),
    (r"new can be applied only to class types",
     "Dafny has no StringBuilder or new string(...); build strings/sequences by concatenation, e.g. r := r + [c]"),
    (r"lbrace expected",
     "in statements write `if cond { ... } else { ... }`; `then` is only used in if-expressions"),
    (r"Duplicate local-variable name: (result|r)\b",
     "the out-parameter is already declared in `returns (...)`; assign to it instead of declaring `var` again"),
    (r"LHS of array assignment must denote an array element \(found seq",
     "sequences are immutable: use s := s[i := v] or build a new sequence"),
    (r"unresolved identifier",
     "this name does not exist; Dafny has almost no library functions for strings/lists, define a helper yourself"),
    (r"(member|function) .* does not exist in type",
     "this member does not exist in Dafny; check the type (seq, string, array) and write a helper if needed"),
    (r"ghost",
     "ghost functions/variables can only be used in specifications; compute the value with executable code in the body"),
    (r"type mismatch|incorrect type|expected type",
     "check int vs nat vs char vs string; convert explicitly (e.g. compare chars with chars, use 'a' not \"a\")"),
    (r"cannot prove termination|decreases",
     "add a decreases clause to the loop or recursive call, e.g. `decreases |s| - i`"),
    (r"loop invariant could not be proved on entry",
     "the invariant must already hold before the first iteration with the initial values of the variables"),
    (r"invariant could not be proved to be maintained",
     "the loop body breaks this invariant; strengthen other invariants or change the update order"),
    (r"index out of range",
     "add `invariant 0 <= i <= |a|` (or a guard) so every index is provably in bounds"),
]
_FIX_RE = [(re.compile(p, re.IGNORECASE), h) for p, h in FIX_HINTS]


_WHILE = re.compile(r"\bwhile\b")
_INV_CLAUSE = re.compile(r"^\s*invariant\b", re.M)
_INV_COMMENT = re.compile(r"(//|/\*).*\binvariant", re.I)


def loop_annotation_diagnostics(code: str) -> list[Diagnostic]:
    """Dev iteration 5: catch loops whose invariants are missing or only in comments.

    Dafny reports both cases as an unprovable postcondition, which does not
    tell the model that the loop itself carries no proof annotations.
    """
    if not _WHILE.search(code) or _INV_CLAUSE.search(code):
        return []
    lines = code.splitlines()
    ln = next((i + 1 for i, l in enumerate(lines) if _WHILE.search(l)), None)
    if _INV_COMMENT.search(code):
        return [Diagnostic("invariant_comment", "loop invariants are written as comments, which Dafny ignores",
                           line=ln, source_line=lines[ln - 1].strip() if ln else "")]
    return [Diagnostic("missing_invariant", "the loop has no invariant clauses",
                       line=ln, source_line=lines[ln - 1].strip() if ln else "")]


def fix_hint(message: str) -> str:
    for pat, hint in _FIX_RE:
        if pat.search(message):
            return hint
    return ""


def _line(code_lines: list[str], n: int | None) -> str:
    if n is None or n < 1 or n > len(code_lines):
        return ""
    return code_lines[n - 1].strip()


def normalise_dafny(vr: VerificationResult, code: str) -> list[Diagnostic]:
    lines = code.splitlines()
    out = vr.raw_output or ""
    is_parse = "parse errors detected" in out
    is_resolve = "resolution/type errors detected" in out
    diags: list[Diagnostic] = []
    for raw in out.splitlines():
        m = _DFY.match(raw.strip())
        if not m:
            continue
        ln, sev, msg = int(m.group("line")), m.group("sev"), m.group("msg").strip()
        if sev == "Warning":
            continue
        if sev == "Related location":
            if diags:
                clause = _line(lines, ln)
                diags[-1].related = (diags[-1].related + " | " if diags[-1].related else "") + \
                    f"line {ln}: {clause}"
            continue
        if is_parse:
            kind = "syntax"
        elif is_resolve:
            kind = "resolution"
        else:
            kind = next((k for frag, k in _DAFNY_KINDS if frag in msg.lower()), "other")
        diags.append(Diagnostic(kind=kind, message=msg, line=ln, source_line=_line(lines, ln)))
    if not diags and vr.status is VerificationStatus.TIMEOUT:
        diags.append(Diagnostic(kind="timeout", message="verification timed out"))
    if not diags and vr.status is not VerificationStatus.VERIFIED:
        diags.append(Diagnostic(kind="other", message=(vr.errors or ["verification failed"])[0][:400]))
    return diags


_CALL = re.compile(r"when calling (?P<call>.*?)(?: \(which returns (?P<ret>.*)\))?$")


def normalise_python(vr: VerificationResult, code: str) -> list[Diagnostic]:
    lines = code.splitlines()
    diags: list[Diagnostic] = []
    for err in vr.errors:
        m = _CH.match(err)
        if not m:
            kind = "timeout" if vr.status is VerificationStatus.TIMEOUT else "resolution"
            diags.append(Diagnostic(kind=kind, message=err[:400]))
            continue
        ln, msg = int(m.group("line")), m.group("msg")
        if msg.startswith("SyntaxError"):
            diags.append(Diagnostic(kind="syntax", message=msg, line=ln, source_line=_line(lines, ln)))
            continue
        call = _CALL.search(msg)
        cex = ""
        if call:
            cex = call.group("call")
            if call.group("ret"):
                cex += f" returned {call.group('ret')}"
        src = _line(lines, ln)
        if msg.startswith("false when calling"):
            kind = "counterexample"
            message = "postcondition is false for a concrete input"
            related = f"line {ln}: {src}"
        else:
            kind = "exception"
            message = msg.split(" when calling")[0].strip()
            related = ""
        diags.append(Diagnostic(kind=kind, message=message, line=ln, source_line=src,
                                related=related, counterexample=cex))
    if not diags and vr.status is not VerificationStatus.VERIFIED:
        diags.append(Diagnostic(kind="other", message="verification failed"))
    return diags


class DiagnosticNormalizer:
    """Turns raw verifier output into feedback text (or passes it through)."""

    def __init__(self, enabled: bool = True, max_items: int = 4, raw_chars: int = 1500,
                 hints: bool = True, loop_check: bool = True):
        self.enabled = enabled
        self.hints = hints
        self.loop_check = loop_check
        self.max_items = max_items
        self.raw_chars = raw_chars

    def diagnostics(self, language: Language, vr: VerificationResult, code: str) -> list[Diagnostic]:
        if language is Language.DAFNY:
            return normalise_dafny(vr, code)
        return normalise_python(vr, code)

    def render(self, language: Language, vr: VerificationResult, code: str) -> str:
        if not self.enabled:
            return self.render_raw(vr)
        diags = self.diagnostics(language, vr, code)
        if self.loop_check and language is Language.DAFNY and \
                not any(d.kind in ("syntax", "resolution") for d in diags):
            diags = loop_annotation_diagnostics(code) + diags
        vr.diagnostics = diags
        parts = []
        for d in diags[: self.max_items]:
            head = f"[{d.kind}]" + (f" line {d.line}" if d.line else "") + f": {d.message}"
            sub = []
            if d.source_line:
                sub.append(f"    at:      {d.source_line}")
            if d.related:
                sub.append(f"    clause:  {d.related}")
            if d.counterexample:
                sub.append(f"    failing call: {d.counterexample}")
            hint = KIND_HINTS.get(d.kind)
            if hint:
                sub.append(f"    meaning: {hint}")
            fix = fix_hint(d.message) if self.hints and language is Language.DAFNY else ""
            if fix:
                sub.append(f"    fix:     {fix}")
            parts.append("\n".join([head] + sub))
        if len(diags) > self.max_items:
            parts.append(f"(+{len(diags) - self.max_items} more of the same kind)")
        return "\n".join(parts)

    def render_raw(self, vr: VerificationResult) -> str:
        """Phase 1 style feedback: the tool output, lightly trimmed."""
        text = vr.raw_output or "\n".join(vr.errors)
        text = re.sub(r"[A-Za-z]:\\[^\s:()]*?(candidate\.(dfy|py))", r"\1", text)
        text = re.sub(r"/[^\s:()]*?(candidate\.(dfy|py))", r"\1", text)
        keep = [l for l in text.splitlines() if l.strip()]
        return "\n".join(keep)[-self.raw_chars:]
