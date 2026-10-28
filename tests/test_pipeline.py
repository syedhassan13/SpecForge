"""
Unit tests for the deterministic parts of SpecLoop.

These run without network access. Tests that need Dafny or CrossHair are
skipped automatically when the tool is not installed.

    python -m pytest tests -q
"""

import os
import shutil
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.agents.controller import AgentConfig, SpecLoopAgent, parse_reply  # noqa: E402
from src.components.diagnostics import DiagnosticNormalizer, normalise_dafny, normalise_python  # noqa: E402
from src.components.router import (LOGIC_BUG, PROOF_GAP, SPEC_TAMPER, SYNTAX, SOLVED, VERIFY_FAIL,  # noqa: E402
                                   FeedbackRouter, Observation, classify)
from src.components.spec_guard import (guard_dafny, guard_python, split_dafny_toplevel,  # noqa: E402
                                       strip_dafny_comments)
from src.components.stagnation import StagnationMonitor, failure_signature  # noqa: E402
from src.providers.llm_provider import MockProvider, price  # noqa: E402
from src.schemas import (AgentMode, Diagnostic, GuardResult, Language, TaskSpec, TestCaseOutcome,  # noqa: E402
                         TestResult, TestStatus, VerificationResult, VerificationStatus)
from src.tasks.harness import dafny_harness, parse_markers, python_harness  # noqa: E402
from src.tasks.types import check_value, dafny_literal, dafny_type, parse_type, python_literal, python_type  # noqa: E402

DAFNY = os.environ.get("DAFNY_PATH", "dafny")
HAVE_DAFNY = shutil.which(DAFNY) is not None or os.path.exists(DAFNY)

DFY_SPEC = """predicate Sorted(a: seq<int>)
{
  forall i, j :: 0 <= i < j < |a| ==> a[i] <= a[j]
}

method Find(a: seq<int>, key: int) returns (result: int)
  requires Sorted(a)
  ensures -1 <= result < |a|
  ensures result >= 0 ==> a[result] == key
{
  // IMPLEMENT HERE
}
"""

DFY_GOOD = """predicate Sorted(a: seq<int>)
{
  forall i, j :: 0 <= i < j < |a| ==> a[i] <= a[j]
}

// a comment the model added
method Find(a: seq<int>, key: int) returns (result: int)
    requires Sorted(a)
    ensures -1 <= result < |a|
    ensures result >= 0 ==> a[result] == key
{
  result := -1;
  var i := 0;
  while i < |a|
    invariant 0 <= i <= |a|
    invariant -1 <= result < |a|
    invariant result >= 0 ==> a[result] == key
  {
    if a[i] == key { result := i; }
    i := i + 1;
  }
}
"""

PY_SPEC = """import icontract
from typing import List


@icontract.require(lambda a: len(a) > 0)
@icontract.ensure(lambda a, result: result in a)
@icontract.ensure(lambda a, result: all(result >= x for x in a))
def max_of(a: List[int]) -> int:
    # IMPLEMENT HERE
    pass
"""

PY_GOOD = """import icontract
from typing import List


@icontract.require(lambda a: len(a) > 0)
@icontract.ensure(lambda a, result: result in a)
@icontract.ensure(lambda a, result: all(result >= x for x in a))
def max_of(a: List[int]) -> int:
    best = a[0]
    for x in a:
        if x > best:
            best = x
    return best
"""


class TestTypes(unittest.TestCase):
    def test_parse_and_render(self):
        t = parse_type("tuple<list<int>, bool>")
        self.assertEqual(dafny_type(t), "(seq<int>, bool)")
        self.assertEqual(python_type(t), "Tuple[List[int], bool]")
        self.assertEqual(dafny_literal([[1, -2], True], t), "([1, -2], true)")
        self.assertEqual(python_literal([[1, -2], True], t), "([1, -2], True)")

    def test_string_and_char_escapes(self):
        self.assertEqual(dafny_literal('a"b\\', parse_type("string")), '"a\\"b\\\\"')
        self.assertEqual(dafny_literal("'", parse_type("char")), "'\\''")

    def test_check_value(self):
        self.assertTrue(check_value(3, parse_type("nat")))
        self.assertFalse(check_value(-1, parse_type("nat")))
        self.assertFalse(check_value(True, parse_type("int")))
        self.assertTrue(check_value([["a"], False], parse_type("tuple<list<char>, bool>")))

    def test_bad_type(self):
        with self.assertRaises(ValueError):
            parse_type("float")


class TestHarness(unittest.TestCase):
    params = [{"name": "a", "type": "list<int>"}, {"name": "key", "type": "int"}]
    cases = [{"input": {"a": [1, 2], "key": 2}, "expected": 1},
             {"input": {"a": [], "key": 0}, "expected": -1}]

    def test_dafny_uses_runtime_checks_not_assert(self):
        h = dafny_harness("Find", self.params, "int", self.cases)
        self.assertIn("method Main()", h)
        self.assertIn("var r0 := Find([1, 2], 2);", h)
        self.assertNotIn("assert", h)   # Phase 1 bug: ghost asserts are erased at run time

    def test_python_harness_compiles(self):
        h = python_harness("find", self.params, "int", self.cases)
        compile("def find(a, key):\n    return -1\n" + h, "x", "exec")

    def test_parse_markers(self):
        out = "SPECLOOP_PASS 0\nnoise\nSPECLOOP_FAIL 1 got=[3]\nSPECLOOP_ERROR 2 IndexError: x"
        m = parse_markers(out)
        self.assertEqual(m[0][0], "SPECLOOP_PASS")
        self.assertEqual(m[1], ("SPECLOOP_FAIL", "got=[3]"))
        self.assertEqual(m[2][0], "SPECLOOP_ERROR")


class TestDafnyGuard(unittest.TestCase):
    def test_comment_stripping_keeps_strings(self):
        s = strip_dafny_comments('var s := "a // not a comment"; // real\n/* block */x')
        self.assertIn('"a // not a comment"', s)
        self.assertNotIn("real", s)
        self.assertNotIn("block", s)

    def test_split_toplevel(self):
        chunks = split_dafny_toplevel(strip_dafny_comments(DFY_SPEC))
        self.assertEqual(len(chunks), 2)
        self.assertTrue(chunks[0].startswith("predicate Sorted"))

    def test_reference_passes(self):
        self.assertTrue(guard_dafny(DFY_SPEC, DFY_GOOD, "Find").ok)

    def test_dropped_ensures_rejected(self):
        bad = DFY_GOOD.replace("    ensures result >= 0 ==> a[result] == key\n", "", 1)
        self.assertFalse(guard_dafny(DFY_SPEC, bad, "Find").ok)

    def test_weakened_predicate_rejected(self):
        bad = DFY_GOOD.replace("a[i] <= a[j]", "true", 1)
        self.assertFalse(guard_dafny(DFY_SPEC, bad, "Find").ok)

    def test_assume_and_attributes_rejected(self):
        for inject in ("assume false;", "assert {:axiom} false;"):
            bad = DFY_GOOD.replace("result := -1;", "result := -1; " + inject, 1)
            self.assertFalse(guard_dafny(DFY_SPEC, bad, "Find").ok, inject)
        bad = DFY_GOOD.replace("method Find", "method {:verify false} Find", 1)
        self.assertFalse(guard_dafny(DFY_SPEC, bad, "Find").ok)

    def test_bodyless_lemma_warning_rejected(self):
        g = guard_dafny(DFY_SPEC, DFY_GOOD, "Find",
                        ["line 3: Warning: This ensures clause is part of a bodyless method"])
        self.assertFalse(g.ok)


class TestPythonGuard(unittest.TestCase):
    def test_reference_passes(self):
        self.assertTrue(guard_python(PY_SPEC, PY_GOOD, "max_of").ok)

    def test_reformatting_is_fine(self):
        reformatted = PY_GOOD.replace("lambda a, result: result in a", "lambda a, result:   result in a")
        self.assertTrue(guard_python(PY_SPEC, reformatted, "max_of").ok)

    def test_removed_decorator_rejected(self):
        bad = PY_GOOD.replace("@icontract.ensure(lambda a, result: result in a)\n", "")
        self.assertFalse(guard_python(PY_SPEC, bad, "max_of").ok)

    def test_weakened_contract_rejected(self):
        bad = PY_GOOD.replace("all(result >= x for x in a)", "True")
        self.assertFalse(guard_python(PY_SPEC, bad, "max_of").ok)

    def test_escape_hatches_rejected(self):
        for bad in (PY_GOOD + "\n# crosshair: off\n",
                    PY_GOOD.replace("import icontract\n", "import icontract\nicontract.ensure = None\n"),
                    PY_GOOD.replace("best = a[0]", "best = eval('a[0]')")):
            self.assertFalse(guard_python(PY_SPEC, bad, "max_of").ok)

    def test_unparseable(self):
        g = guard_python(PY_SPEC, "def max_of(:\n", "max_of")
        self.assertFalse(g.ok)
        self.assertFalse(g.checked)


DFY_OUT = """C:\\tmp\\x\\candidate.dfy(12,4): Error: index out of range
C:\\tmp\\x\\candidate.dfy(18,2): Error: a postcondition could not be proved on this return path
C:\\tmp\\x\\candidate.dfy(3,10): Related location: this is the postcondition that could not be proved

Dafny program verifier finished with 1 verified, 2 errors"""


class TestNormalizer(unittest.TestCase):
    def test_dafny(self):
        code = "\n".join(f"line{i}" for i in range(1, 25))
        vr = VerificationResult(VerificationStatus.FAILED, raw_output=DFY_OUT)
        d = normalise_dafny(vr, code)
        self.assertEqual([x.kind for x in d], ["index_bounds", "postcondition"])
        self.assertEqual(d[0].source_line, "line12")
        self.assertIn("line 3: line3", d[1].related)

    def test_dafny_parse_error(self):
        vr = VerificationResult(VerificationStatus.FAILED,
                                raw_output="c.dfy(3,10): Error: invalid UnaryExpression\n1 parse errors detected in c.dfy")
        self.assertEqual(normalise_dafny(vr, "a\nb\nc")[0].kind, "syntax")

    def test_python_counterexample(self):
        code = "a\nb\n@icontract.ensure(lambda x, result: result > 0)\n"
        vr = VerificationResult(VerificationStatus.FAILED,
                                errors=["line 3: false when calling f(-1) (which returns 0)"])
        d = normalise_python(vr, code)[0]
        self.assertEqual(d.kind, "counterexample")
        self.assertEqual(d.counterexample, "f(-1) returned 0")

    def test_raw_mode_strips_paths(self):
        n = DiagnosticNormalizer(enabled=False)
        vr = VerificationResult(VerificationStatus.FAILED, raw_output=DFY_OUT)
        txt = n.render(Language.DAFNY, vr, "")
        self.assertNotIn("C:\\tmp", txt)
        self.assertIn("candidate.dfy(12,4)", txt)


class TestRouter(unittest.TestCase):
    def _tr(self, ok):
        return TestResult(TestStatus.PASSED if ok else TestStatus.FAILED, passed=1 if ok else 0, total=1,
                          failures=[] if ok else ["test 0: input (x=1) expected 2 got 3"],
                          cases=[TestCaseOutcome(0, ok)])

    def test_classes(self):
        fail = VerificationResult(VerificationStatus.FAILED)
        post = [Diagnostic("postcondition", "x", 3)]
        self.assertEqual(classify(Observation(guard=GuardResult(False, violations=["x"]))), SPEC_TAMPER)
        self.assertEqual(classify(Observation(vr=fail, diagnostics=[Diagnostic("syntax", "x")])), SYNTAX)
        self.assertEqual(classify(Observation(vr=fail, diagnostics=post, tr=self._tr(False))), LOGIC_BUG)
        self.assertEqual(classify(Observation(vr=fail, diagnostics=post, tr=self._tr(True))), PROOF_GAP)
        self.assertEqual(classify(Observation(vr=fail, diagnostics=post)), VERIFY_FAIL)
        self.assertEqual(classify(Observation(vr=fail, diagnostics=[Diagnostic("counterexample", "x")])), LOGIC_BUG)
        ok = VerificationResult(VerificationStatus.VERIFIED)
        self.assertEqual(classify(Observation(vr=ok, tr=self._tr(True))), SOLVED)

    def test_proof_gap_message(self):
        obs = Observation(vr=VerificationResult(VerificationStatus.FAILED),
                          diagnostics=[Diagnostic("postcondition", "x", 3)], tr=self._tr(True),
                          verifier_text="[postcondition] line 3")
        fb = FeedbackRouter().route(obs, True, True)
        self.assertEqual(fb.failure_class, PROOF_GAP)
        self.assertIn("Keep the algorithm", fb.message)

    def test_router_off_is_plain_concatenation(self):
        obs = Observation(vr=VerificationResult(VerificationStatus.FAILED), tr=self._tr(False),
                          verifier_text="V", test_text="T")
        fb = FeedbackRouter(enabled=False).route(obs, True, True)
        self.assertIn("## Formal verification result", fb.message)
        self.assertNotIn("Fix the algorithm first", fb.message)


class TestStagnation(unittest.TestCase):
    def test_duplicate_code_triggers_rewrite(self):
        m = StagnationMonitor()
        self.assertFalse(m.observe("x := 1;", "A"))
        self.assertTrue(m.observe("x  :=  1;", "B"))    # same program, whitespace differs

    def test_repeated_signature(self):
        m = StagnationMonitor(patience=2)
        self.assertFalse(m.observe("v1", "S"))
        self.assertTrue(m.observe("v2", "S"))

    def test_disabled(self):
        m = StagnationMonitor(enabled=False)
        m.observe("v", "S")
        self.assertFalse(m.observe("v", "S"))

    def test_signature(self):
        tr = TestResult(TestStatus.FAILED, cases=[TestCaseOutcome(0, True), TestCaseOutcome(1, False)])
        s = failure_signature("LOGIC_BUG", [Diagnostic("postcondition", "m", 7)], tr)
        self.assertEqual(s, "LOGIC_BUG|postcondition@7|[1]")


class TestParsingAndPricing(unittest.TestCase):
    def test_parse_reply_json(self):
        c = parse_reply('{"analysis": "a", "strategy": "patch", "code": "x"}')
        self.assertEqual((c.code, c.strategy, c.parse_ok), ("x", "patch", True))

    def test_parse_reply_fence_fallback(self):
        c = parse_reply("blah\n```dafny\nmethod M() {}\n```")
        self.assertEqual(c.code, "method M() {}")
        self.assertFalse(c.parse_ok)

    def test_price(self):
        self.assertAlmostEqual(price("gpt-4o-mini-2024-07-18", 1_000_000, 1_000_000), 0.75)
        self.assertAlmostEqual(price("gpt-4.1-2025-04-14", 1000, 0), 0.002)
        self.assertEqual(price("unknown", 10, 10), 0.0)


class TestTaskSplits(unittest.TestCase):
    def test_visible_hidden_split(self):
        t = TaskSpec("t", "d", Language.DAFNY, "", "", tests=[{"input": {}, "expected": i} for i in range(5)])
        self.assertEqual(len(t.visible_tests), 3)
        self.assertEqual(len(t.hidden_tests), 2)

    def test_split_file_disjoint(self):
        from src.tasks.loader import SPLIT_FILE
        if not SPLIT_FILE.exists():
            self.skipTest("splits not generated yet")
        import json
        s = json.loads(SPLIT_FILE.read_text())
        self.assertFalse(set(s["dev"]) & set(s["test"]))


@unittest.skipUnless(HAVE_DAFNY, "Dafny not installed")
class TestDafnyIntegration(unittest.TestCase):
    def test_reference_verifies_and_agent_stops(self):
        task = TaskSpec("find_dafny", "find key", Language.DAFNY, DFY_SPEC, DFY_GOOD, entry_point="Find",
                        params=[{"name": "a", "type": "list<int>"}, {"name": "key", "type": "int"}],
                        returns="int", tests=[{"input": {"a": [1, 2, 3], "key": 2}, "expected": 1},
                                              {"input": {"a": [1, 2, 3], "key": 5}, "expected": -1}])
        reply = '{"analysis": "linear scan", "code": %s}' % __import__("json").dumps(DFY_GOOD)
        agent = SpecLoopAgent(MockProvider(script=[reply]), AgentConfig(mode=AgentMode.COMBINED, name="t"))
        res, traj = agent.run(task)
        self.assertTrue(res.correct)
        self.assertEqual(res.attempts, 1)
        self.assertEqual(res.stop_reason, "mode_success")
        kinds = [e["type"] for e in traj.events]
        self.assertIn("tool", kinds)
        self.assertIn("oracle", kinds)


if __name__ == "__main__":
    unittest.main()
