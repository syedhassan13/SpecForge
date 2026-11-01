"""
SpecLoop agent controller.

The agent is a small state machine around an LLM:

    GENERATE -> CHECK -> (success?) -> STOP
                  |
                  v
                ROUTE -> REPAIR (patch | rewrite) -> CHECK -> ...

CHECK calls tools, and which tools depends on the mode:
    spec guard       (all modes, unless the guard is ablated)
    verifier         (verifier_feedback, combined)
    visible tests    (testing_only, combined)

ROUTE turns tool output into feedback (normaliser + router), REPAIR asks the
model for a new program, and the stagnation monitor can force a "rewrite"
when the loop is stuck. Every step is written to the trajectory.

All runs end with the independent oracle (src/evaluation/oracle.py); with
`oracle_every_attempt` the oracle also judges each intermediate candidate,
which gives correctness@k curves without extra LLM calls.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field, asdict
from typing import Optional

from src.agents import prompts as P
from src.backends import get_backend
from src.components import (DiagnosticNormalizer, FeedbackRouter, Observation,
                            SpecGuard, StagnationMonitor, classify)
from src.components.router import SOLVED
from src.components.stagnation import code_hash, failure_signature
from src.evaluation.oracle import judge
from src.providers.llm_provider import LLMProvider
from src.schemas import (AgentMode, GuardResult, Language, PipelineResult, TaskSpec,
                         TestStatus, VerificationStatus)
from src.tracing.trajectory import Trajectory


@dataclass
class AgentConfig:
    mode: AgentMode = AgentMode.COMBINED
    max_attempts: int = 5            # candidate programs checked (1 initial + 4 repairs)
    normalizer: bool = True          # Gap 1 component
    fix_hints: bool = True           # dev iteration 4: fix hints inside the normaliser
    compile_from_tests: bool = True  # dev iteration 4: show compile errors seen only in the test run
    loop_check: bool = True          # dev iteration 5: flag loops with no / commented-out invariants
    router: bool = True              # Gap 2 component
    guard: bool = True               # spec integrity guard inside the loop
    stagnation: bool = True          # rewrite on repeated failure
    temperature: float = 0.2
    rewrite_temperature: float = 0.6
    max_tokens: int = 4096
    oracle_every_attempt: bool = True
    name: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["mode"] = self.mode.value
        return d


@dataclass
class Candidate:
    code: str
    analysis: str = ""
    strategy: str = ""
    parse_ok: bool = True


_FENCE = re.compile(r"```(?:dafny|python|py)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)


def parse_reply(text: str) -> Candidate:
    """Read the JSON answer; fall back to a fenced code block if needed."""
    try:
        obj = json.loads(text)
        return Candidate(code=str(obj.get("code", "")).strip(), analysis=str(obj.get("analysis", "")),
                         strategy=str(obj.get("strategy", "")))
    except (json.JSONDecodeError, AttributeError):
        pass
    m = _FENCE.search(text)
    if m:
        return Candidate(code=m.group(1).strip(), parse_ok=False)
    return Candidate(code=text.strip(), parse_ok=False)


def _short(s: str, n: int = 300) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[:n] + "..."


class SpecLoopAgent:
    def __init__(self, provider: LLMProvider, config: AgentConfig, seed: int = 0):
        self.provider = provider
        self.cfg = config
        self.seed = seed
        self.normalizer = DiagnosticNormalizer(enabled=config.normalizer, hints=config.fix_hints,
                                               loop_check=config.loop_check)
        self.router = FeedbackRouter(enabled=config.router, compile_from_tests=config.compile_from_tests)
        self.guard = SpecGuard(enabled=config.guard)

    # ------------------------------------------------------------------
    def _llm(self, traj: Trajectory, res: PipelineResult, messages: list[dict], purpose: str,
             attempt: int, temperature: float, schema: dict) -> Candidate:
        reply = None
        for retry in range(2):
            try:
                reply = self.provider.chat(messages, temperature=temperature,
                                           max_tokens=self.cfg.max_tokens, seed=self.seed,
                                           json_schema=schema, sample=retry)
                break
            except Exception as e:  # noqa: BLE001
                traj.log("error", where="llm", attempt=attempt, error=_short(str(e), 200))
                if retry == 1:
                    raise
        res.llm_calls += 1
        res.prompt_tokens += reply.prompt_tokens
        res.completion_tokens += reply.completion_tokens
        res.cost_usd += reply.cost_usd
        res.llm_seconds += reply.seconds
        cand = parse_reply(reply.text)
        traj.log("llm", purpose=purpose, attempt=attempt, temperature=temperature,
                 prompt_tokens=reply.prompt_tokens, completion_tokens=reply.completion_tokens,
                 cached=reply.cached, analysis=_short(cand.analysis, 600), strategy=cand.strategy,
                 json_ok=cand.parse_ok, code_hash=code_hash(cand.code), code=cand.code)
        return cand

    def _system(self, task: TaskSpec) -> str:
        return P.SYSTEM_PROMPT_DAFNY if task.language is Language.DAFNY else P.SYSTEM_PROMPT_PYTHON

    @staticmethod
    def _fence(task: TaskSpec) -> tuple[str, str]:
        return ("Dafny", "dafny") if task.language is Language.DAFNY else ("Python + iContract", "python")

    # ------------------------------------------------------------------
    def _check(self, task: TaskSpec, code: str, traj: Trajectory, res: PipelineResult) -> Observation:
        mode = self.cfg.mode
        be = get_backend(task.language)
        obs = Observation()
        if self.cfg.guard:
            t0 = time.time()
            try:
                g = self.guard.check(task.language, task.specification, code, task.entry_point)
            except Exception as e:  # noqa: BLE001
                g = GuardResult(ok=False, checked=False, violations=[f"guard error: {e}"])
            res.tool_seconds += time.time() - t0
            traj.log("tool", tool="spec_guard", input=code_hash(code), ok=g.ok, checked=g.checked,
                     violations=g.violations[:4], seconds=round(time.time() - t0, 3))
            obs.guard = g
            if not g.ok and g.checked:
                res.guard_blocks += 1
                return obs                      # no point verifying a tampered program
        if mode.uses_verifier:
            vr = be.verify(code)
            res.verifier_calls += 1
            res.tool_seconds += vr.time_seconds
            if self.cfg.guard and task.language is Language.DAFNY and vr.warnings:
                g2 = self.guard.check(task.language, task.specification, code, task.entry_point, vr.warnings)
                if not g2.ok:
                    obs.guard = g2
                    res.guard_blocks += 1
            obs.vr = vr
            obs.diagnostics = self.normalizer.diagnostics(task.language, vr, code)
            obs.verifier_text = self.normalizer.render(task.language, vr, code) \
                if vr.status is not VerificationStatus.VERIFIED else ""
            traj.log("tool", tool="verify", input=code_hash(code), status=vr.status.value,
                     n_errors=len(vr.errors), kinds=[d.kind for d in obs.diagnostics],
                     errors=[_short(e, 160) for e in vr.errors[:4]], seconds=round(vr.time_seconds, 2))
        if mode.uses_tests:
            tr = be.run_tests(code, task.entry_point, task.params, task.returns, task.visible_tests)
            res.test_calls += 1
            res.tool_seconds += tr.time_seconds
            obs.tr = tr
            obs.test_text = self.router.test_text(tr)
            traj.log("tool", tool="run_tests", input=code_hash(code), status=tr.status.value,
                     passed=tr.passed, total=tr.total,
                     failures=[_short(f, 200) for f in tr.failures[:3]], seconds=round(tr.time_seconds, 2))
        return obs

    def _mode_success(self, obs: Observation) -> bool:
        if obs.guard is not None and not obs.guard.ok and obs.guard.checked:
            return False
        mode = self.cfg.mode
        ver_ok = obs.vr is not None and obs.vr.status is VerificationStatus.VERIFIED
        test_ok = obs.tr is not None and obs.tr.status is TestStatus.PASSED
        if mode is AgentMode.TESTING_ONLY:
            return test_ok
        if mode is AgentMode.VERIFIER_FEEDBACK:
            return ver_ok
        if mode is AgentMode.COMBINED:
            return ver_ok and test_ok
        return False

    # ------------------------------------------------------------------
    def run(self, task: TaskSpec, run_id: str = "") -> tuple[PipelineResult, Trajectory]:
        cfg = self.cfg
        start = time.time()
        res = PipelineResult(task_id=task.task_id, model=self.provider.model_name(), agent_mode=cfg.mode,
                             language=task.language, final_code="", config_name=cfg.name,
                             seed=self.seed, pair_id=task.pair_id)
        traj = Trajectory(run_id or f"{cfg.name}:{task.task_id}:{self.seed}",
                          {"task_id": task.task_id, "pair_id": task.pair_id, "language": task.language.value,
                           "model": self.provider.model_name(), "seed": self.seed, "config": cfg.to_dict()})
        lang, fence = self._fence(task)
        system = self._system(task)
        monitor = StagnationMonitor(enabled=cfg.stagnation)
        history: list[str] = []
        budget = 1 if cfg.mode is AgentMode.SINGLE_SHOT else cfg.max_attempts

        traj.transition("GENERATE")
        first = P.INITIAL_PROMPT_TEMPLATE.format(description=task.description, language=lang, fence=fence,
                                                 specification=task.specification)
        cand = self._llm(traj, res, [{"role": "system", "content": system}, {"role": "user", "content": first}],
                         "generate", 1, cfg.temperature, P.INITIAL_SCHEMA)
        res.stop_reason = "budget"
        verdicts = []
        for attempt in range(1, budget + 1):
            traj.transition("CHECK", attempt=attempt)
            obs = self._check(task, cand.code, traj, res) if cfg.mode is not AgentMode.SINGLE_SHOT else Observation()
            cls = classify(obs) if cfg.mode is not AgentMode.SINGLE_SHOT else ""
            if cls:
                res.failure_classes.append(cls)
            if cfg.oracle_every_attempt or attempt == budget:
                v = judge(task, cand.code)
                verdicts.append(v)
                traj.log("oracle", attempt=attempt, **v.to_dict())
                if v.correct and res.solved_at_attempt is None:
                    res.solved_at_attempt = attempt
            res.attempts = attempt
            res.final_code = cand.code
            if self._mode_success(obs):
                res.stop_reason = "mode_success"
                traj.log("decision", what="stop", reason="all feedback checks of this mode passed",
                         attempt=attempt)
                break
            if attempt == budget:
                traj.log("decision", what="stop", reason="attempt budget used", attempt=attempt)
                break

            traj.transition("ROUTE", attempt=attempt)
            fb = self.router.route(obs, cfg.mode.uses_verifier, cfg.mode.uses_tests)
            traj.log("feedback", attempt=attempt, failure_class=fb.failure_class, source=fb.source,
                     text=fb.message[:3000])
            history.append(f"- attempt {attempt}: {fb.failure_class or 'failed'}"
                           + (f" ({obs.diagnostics[0].kind} at line {obs.diagnostics[0].line})"
                              if obs.diagnostics and obs.diagnostics[0].line else ""))
            sig = failure_signature(fb.failure_class, obs.diagnostics, obs.tr)
            rewrite = monitor.observe(cand.code, sig)
            if rewrite:
                res.strategy_switches += 1
                traj.log("decision", what="switch_strategy", reason="same failure repeated or program resubmitted",
                         attempt=attempt)
            traj.transition("REPAIR", attempt=attempt, strategy="rewrite" if rewrite else "patch")
            hist_text = ""
            if len(history) > 1:
                hist_text = "\n## Earlier attempts\n" + "\n".join(history[:-1]) + "\n"
            prompt = P.REPAIR_PROMPT_TEMPLATE.format(
                description=task.description, language=lang, fence=fence, specification=task.specification,
                attempt=attempt, previous_code=cand.code, feedback=fb.message or "(no details)",
                history=hist_text)
            if rewrite:
                prompt += P.REWRITE_NOTE
            temp = cfg.rewrite_temperature if rewrite else cfg.temperature
            cand = self._llm(traj, res, [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                             "rewrite" if rewrite else "repair", attempt + 1, temp, P.REPAIR_SCHEMA)

        final = verdicts[-1]
        res.spec_intact = final.spec_intact
        res.correct = final.correct
        res.extra["tests_ok"] = final.tests_ok
        res.extra["verified"] = final.verified
        res.extra["tests_passed"] = final.tests_passed
        res.extra["tests_total"] = final.tests_total
        res.extra["per_attempt_correct"] = [v.correct for v in verdicts]
        res.extra["per_attempt_tests_ok"] = [v.tests_ok for v in verdicts]
        res.extra["per_attempt_verified"] = [v.verified for v in verdicts]
        res.extra["false_success"] = res.stop_reason == "mode_success" and not final.correct
        res.first_attempt_tests_passed = verdicts[0].tests_ok
        res.first_attempt_verified = verdicts[0].verified
        res.final_failure_class = "" if final.correct else _final_class(final)
        res.total_time_seconds = time.time() - start
        res.trajectory_id = traj.run_id
        traj.transition("STOP", reason=res.stop_reason, correct=res.correct)
        return res, traj


def _final_class(v) -> str:
    if not v.spec_intact:
        return "spec_violation"
    if not v.tests_ok and not v.verified:
        return "wrong_and_unverified"
    if not v.tests_ok:
        return "verified_but_fails_tests"
    return "passes_tests_but_unverified"
