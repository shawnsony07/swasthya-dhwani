"""The Kerala protocol rule engine: pure functions, zero network/IO.

This module is the only place a clinical tier is assigned (architecture.md
section 1, idea 1: "The LLM interprets speech; it never chooses the tier.").
Every public function here is a pure function of its arguments plus the
static `disease_triage_matrix.json` content loaded at import time — no
network calls, no file writes, no randomness, no wall-clock reads, no
mutable module-level state that changes between calls (T5). The matrix file
itself is pinned by `protocol_version`, so re-running with the same inputs
and the same matrix always produces an identical `TriageResult`.

Two safety fixes live here:

* T3 — `query_triage_protocol` never silently defaults an unmatched case to
  tier B. It returns `matched=False` with a `no_match_reason`, which the
  workflow routes to `HUMAN_HANDOFF` (architecture.md section 6).
* T2 — `apply_acuity_floor` raises the tier floor to the stroke tier (C1)
  when speech-impairment signals have a new-or-unknown onset, and raises
  the floor by one step on low interpreter confidence. It never lowers a
  tier, and a chronic baseline is exempt (see its docstring).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from swasthya.contracts import PROTOCOL_VERSION, SpeechOnset, Tier, TriageResult

MATRIX_PATH = Path(__file__).parent / "disease_triage_matrix.json"

# Acuity order, lowest to highest. Matches `tier_order_low_to_high_acuity`
# in the matrix file; duplicated here as a tuple of the shared `Tier` enum
# so callers get a type-checked, import-time-frozen ordering.
TIER_ORDER: tuple[Tier, ...] = (Tier.A, Tier.B, Tier.C2, Tier.C1)

STROKE_CONDITION_ID = "suspected_stroke"
STROKE_FLOOR_TIER = Tier.C1


def _load_matrix() -> dict[str, Any]:
    return json.loads(MATRIX_PATH.read_text(encoding="utf-8"))


# Loaded once at import time. The file is static protocol data (versioned by
# `protocol_version`), not runtime state: reloading it never changes the
# answer for a fixed `protocol_version`, so this does not violate purity.
_MATRIX: dict[str, Any] = _load_matrix()


def _normalize(value: str) -> str:
    return value.strip().lower().replace(" ", "_").replace("-", "_")


def _condition_matches(condition: dict[str, Any], symptoms: frozenset[str]) -> bool:
    required = frozenset(condition["required_symptoms"])
    if condition.get("match_rule", "all") == "any":
        return bool(required & symptoms)
    return required.issubset(symptoms)


def _tier_for_condition(condition: dict[str, Any], warning_signs: frozenset[str]) -> tuple[Tier, bool]:
    warning_set = frozenset(condition.get("warning_signs", []))
    escalated = bool(warning_set & warning_signs)
    escalated_tier = condition.get("escalated_tier")
    if escalated and escalated_tier:
        return Tier(escalated_tier), True
    return Tier(condition["tier"]), False


def query_triage_protocol(symptoms: list[str], warning_signs: list[str]) -> TriageResult:
    """Match confirmed symptoms and warning signs against the protocol matrix.

    Returns the highest-acuity matching condition's tier. If nothing in the
    matrix matches, returns `matched=False` with `no_match_reason` set — T3:
    an unrecognised case is never quietly rated tier B, it is routed to
    `HUMAN_HANDOFF` by the workflow instead.
    """
    normalized_symptoms = frozenset(_normalize(s) for s in symptoms)
    normalized_warnings = frozenset(_normalize(w) for w in warning_signs)

    candidates: list[tuple[Tier, dict[str, Any], bool]] = []
    for condition in _MATRIX["conditions"]:
        if not _condition_matches(condition, normalized_symptoms):
            continue
        tier, escalated = _tier_for_condition(condition, normalized_warnings)
        candidates.append((tier, condition, escalated))

    if not candidates:
        return TriageResult(
            matched=False,
            no_match_reason=(
                "No condition in disease_triage_matrix.json matched "
                f"symptoms={sorted(normalized_symptoms)} "
                f"warning_signs={sorted(normalized_warnings)}; routed to human "
                "review (T3 — never silently defaulted to tier B)."
            ),
            protocol_version=PROTOCOL_VERSION,
        )

    tier, condition, escalated = max(candidates, key=lambda c: TIER_ORDER.index(c[0]))
    return TriageResult(
        matched=True,
        tier=tier,
        condition=condition["id"],
        hospital_tier_required=condition.get("hospital_tier_required"),
        floor_applied=False,
        floor_reason=None,
        protocol_version=PROTOCOL_VERSION,
    )


def _raise_tier_by_one_step(tier: Tier) -> Tier:
    index = TIER_ORDER.index(tier)
    return TIER_ORDER[min(index + 1, len(TIER_ORDER) - 1)]


def apply_acuity_floor(
    result: TriageResult,
    speech_impairment_signals: list[str],
    speech_onset: SpeechOnset,
    interpretation_confidence: float,
    confidence_low_threshold: float,
) -> TriageResult:
    """Raise (never lower) the tier floor from speech signals and confidence.

    Two independent floors, both one-directional:

    1. Stroke floor: any speech-impairment signal (`contracts.IMPAIRMENT_SIGNALS`,
       e.g. "slurred", "word_finding_pause") with onset `NEW` or `UNKNOWN`
       forces the tier to C1, the stroke tier, regardless of how confident
       the interpreter was. A chronic baseline (`SpeechOnset.CHRONIC`) is
       exempt by design: a caregiver who confirms "this is their normal
       speech, they have had ALS/Parkinson's for years" is giving exactly
       the ground truth that distinguishes a known, stable condition from a
       new neurological event — forcing C1 on every chronic-dysarthria call
       would make the floor noise instead of signal, and would not change
       which tier is clinically correct for that patient.
    2. Confidence floor: `interpretation_confidence` below
       `confidence_low_threshold` raises whatever tier is already assigned
       by exactly one step (A->B->C2->C1, capped at C1 — never skipped
       past it). If the case was unmatched (T3), low confidence does not
       invent a tier; it only strengthens the existing human-review
       routing by annotating `no_match_reason`.

    Both floors only ever raise acuity; neither ever lowers a tier that
    `query_triage_protocol` or an earlier floor step already assigned.
    """
    tier = result.tier
    floor_reasons: list[str] = [result.floor_reason] if result.floor_reason else []
    floor_applied = result.floor_applied
    no_match_reason = result.no_match_reason

    stroke_floor_triggered = (
        bool(speech_impairment_signals)
        and speech_onset in (SpeechOnset.NEW, SpeechOnset.UNKNOWN)
    )
    if stroke_floor_triggered:
        floor_applied = True
        floor_reasons.append(
            f"speech_impairment_signals={sorted(speech_impairment_signals)} with "
            f"speech_onset={speech_onset.value!r} (not chronic) forces the stroke "
            f"tier floor ({STROKE_FLOOR_TIER.value}) regardless of confidence (T2)."
        )
        if tier is None or TIER_ORDER.index(tier) < TIER_ORDER.index(STROKE_FLOOR_TIER):
            tier = STROKE_FLOOR_TIER
        matched = True
        condition: str | None = result.condition or STROKE_CONDITION_ID
        hospital_tier_required: str | None = (
            result.hospital_tier_required or "stroke_unit_or_tertiary"
        )
    else:
        matched = result.matched
        condition = result.condition
        hospital_tier_required = result.hospital_tier_required

    low_confidence = interpretation_confidence < confidence_low_threshold
    if low_confidence:
        if tier is not None:
            raised = _raise_tier_by_one_step(tier)
            if raised != tier:
                floor_applied = True
                floor_reasons.append(
                    f"interpretation_confidence={interpretation_confidence} is below "
                    f"confidence_low_threshold={confidence_low_threshold}; tier raised "
                    f"one step from {tier.value} to {raised.value} (T2)."
                )
            tier = raised
        elif no_match_reason is not None:
            no_match_reason = (
                f"{no_match_reason} Additionally, interpretation_confidence="
                f"{interpretation_confidence} is below confidence_low_threshold="
                f"{confidence_low_threshold}: flagged for human review, not "
                "defaulted to a tier."
            )

    return TriageResult(
        matched=matched,
        tier=tier,
        condition=condition,
        hospital_tier_required=hospital_tier_required,
        floor_applied=floor_applied,
        floor_reason=" | ".join(floor_reasons) if floor_reasons else None,
        protocol_version=PROTOCOL_VERSION,
        no_match_reason=no_match_reason,
    )
