"""FluentPath speech interpreter: Gemini-backed clip interpretation and the
confidence-driven confirmation policy (docs/architecture.md section 4)."""
from swasthya.interpreter.confidence_policy import PolicyDecision, decide
from swasthya.interpreter.speech_interpreter import InterpretationFailed, interpret_clip

__all__ = [
    "InterpretationFailed",
    "PolicyDecision",
    "decide",
    "interpret_clip",
]
