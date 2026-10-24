"""Pure confidence-policy decision table (docs/architecture.md section 4).

This module makes exactly one decision: given an already schema-validated
InterpreterOutput and the two configured thresholds, which confirmation
strategy should the voice agent use next? It never touches audio, never calls
a model, and never decides a triage tier — the rule engine (T2,
``apply_acuity_floor`` in the triage core) owns clinical acuity decisions.
"""
from __future__ import annotations

from enum import Enum

from swasthya.contracts import InterpreterOutput


class PolicyDecision(str, Enum):
    """One decision per call to :func:`decide`.

    ACUITY_FLOOR_STROKE is exposed here only as a shared vocabulary value for
    callers to reference; this module's pure confidence-only logic never
    returns it (see note in ``decide``'s docstring).
    """

    ONE_SHOT_SUMMARY = "ONE_SHOT_SUMMARY"
    PER_FACT_READBACK = "PER_FACT_READBACK"
    REASK = "REASK"
    ACUITY_FLOOR_STROKE = "ACUITY_FLOOR_STROKE"
    EMERGENCY_SKIP = "EMERGENCY_SKIP"


def decide(
    output: InterpreterOutput,
    confidence_high: float,
    confidence_low: float,
) -> PolicyDecision:
    """Implements architecture.md section 4's confidence-policy table exactly,
    for the rows that are this module's to decide:

    1. ``emergency_terms_heard`` non-empty -> EMERGENCY_SKIP. Checked first;
       overrides every other row, including low confidence.
    2. No impairment signals AND confidence >= confidence_high ->
       ONE_SHOT_SUMMARY.
    3. Any impairment signal, OR confidence_low <= confidence < confidence_high
       -> PER_FACT_READBACK.
    4. confidence < confidence_low -> REASK (a failed attempt upstream).

    Note on the stroke-floor row: the doc's "speech difficulty with new/unknown
    onset -> acuity floor" row is a *clinical* decision that depends on
    symptom/condition state this module does not have (and must not guess at
    from speech alone) — it belongs to ``apply_acuity_floor`` in the rule
    engine (T2), which this module does not duplicate. ACUITY_FLOOR_STROKE
    stays in the enum only so callers share one vocabulary across modules;
    ``decide`` itself never returns it.
    """
    if output.emergency_terms_heard:
        return PolicyDecision.EMERGENCY_SKIP

    if not output.impairment_signals and output.confidence >= confidence_high:
        return PolicyDecision.ONE_SHOT_SUMMARY

    if output.confidence < confidence_low:
        return PolicyDecision.REASK

    # Remaining cases: any impairment signal present, or confidence sits in
    # [confidence_low, confidence_high) with no signals.
    return PolicyDecision.PER_FACT_READBACK
