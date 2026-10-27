"""
Agent modes (Phase 1 API kept for compatibility).

In Phase 1 there were four separate agent classes with copy-pasted loops,
which made it hard to switch single components off. Phase 2 has a single
controller (`controller.SpecLoopAgent`); the classes below are just presets.
"""

from __future__ import annotations

import re

from src.agents.controller import AgentConfig, SpecLoopAgent, parse_reply
from src.providers.llm_provider import LLMProvider
from src.schemas import AgentMode, TaskSpec, PipelineResult


def _extract_code(response: str, language: str) -> str:
    """Phase 1 helper: pull code out of a markdown fence (used by E2 and tests)."""
    pattern = rf"```(?:{language})?\s*\n(.*?)```"
    match = re.search(pattern, response, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return response.strip()


class _Preset:
    MODE = AgentMode.COMBINED

    def __init__(self, provider: LLMProvider, max_attempts: int = 5, seed: int = 0, **overrides):
        cfg = AgentConfig(mode=self.MODE, max_attempts=max_attempts, name=self.MODE.value, **overrides)
        self.agent = SpecLoopAgent(provider, cfg, seed=seed)

    def run(self, task: TaskSpec) -> PipelineResult:
        result, _ = self.agent.run(task)
        return result


class SingleShotAgent(_Preset):
    MODE = AgentMode.SINGLE_SHOT

    def __init__(self, provider: LLMProvider, max_attempts: int = 1, **kw):
        super().__init__(provider, 1, **kw)


class TestingOnlyAgent(_Preset):
    MODE = AgentMode.TESTING_ONLY


class VerifierFeedbackAgent(_Preset):
    MODE = AgentMode.VERIFIER_FEEDBACK


class CombinedAgent(_Preset):
    MODE = AgentMode.COMBINED


def create_agent(mode: AgentMode, provider: LLMProvider, max_attempts: int = 5, **kw):
    cls = {AgentMode.SINGLE_SHOT: SingleShotAgent, AgentMode.TESTING_ONLY: TestingOnlyAgent,
           AgentMode.VERIFIER_FEEDBACK: VerifierFeedbackAgent, AgentMode.COMBINED: CombinedAgent}[mode]
    return cls(provider, max_attempts, **kw)


__all__ = ["SingleShotAgent", "TestingOnlyAgent", "VerifierFeedbackAgent", "CombinedAgent",
           "create_agent", "_extract_code", "parse_reply"]
