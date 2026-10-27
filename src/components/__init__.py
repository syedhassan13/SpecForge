"""Gap-specific and robustness components (each can be switched off for ablation).

Gap 1 -> diagnostics.DiagnosticNormalizer
Gap 2 -> router.FeedbackRouter (plus the test feedback channel in COMBINED mode)
Gap 3 -> the verifier feedback channel itself (AgentMode.uses_verifier)
Robustness -> spec_guard.SpecGuard, stagnation.StagnationMonitor
"""

from src.components.diagnostics import DiagnosticNormalizer
from src.components.router import FeedbackRouter, Observation, classify
from src.components.spec_guard import SpecGuard
from src.components.stagnation import StagnationMonitor

__all__ = ["DiagnosticNormalizer", "FeedbackRouter", "Observation", "classify",
           "SpecGuard", "StagnationMonitor"]
