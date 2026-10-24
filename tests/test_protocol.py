"""Tests for the Kerala protocol rule engine (architecture.md section 5, T1-T5)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from swasthya.contracts import PROTOCOL_VERSION, SpeechOnset, Tier
from swasthya.protocol.kerala_protocol_mcp import (
    apply_acuity_floor,
    query_triage_protocol,
)

REPO_ROOT = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# T5 — determinism
# ---------------------------------------------------------------------------


def test_determinism_same_input_gives_identical_result():
    first = query_triage_protocol(["chest_pain"], ["radiating_arm_pain"])
    second = query_triage_protocol(["chest_pain"], ["radiating_arm_pain"])
    assert first == second


def test_determinism_across_acuity_floor():
    base = query_triage_protocol(["fever"], [])
    first = apply_acuity_floor(base, ["slurred"], SpeechOnset.NEW, 0.9, 0.5)
    second = apply_acuity_floor(base, ["slurred"], SpeechOnset.NEW, 0.9, 0.5)
    assert first == second


def test_every_result_stamps_protocol_version():
    result = query_triage_protocol(["chest_pain"], [])
    assert result.protocol_version == PROTOCOL_VERSION


# ---------------------------------------------------------------------------
# T1 — suspected stroke resolves to C1
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("sign", ["facial_droop", "arm_weakness", "speech_difficulty"])
def test_any_single_fast_sign_resolves_to_c1(sign):
    result = query_triage_protocol([sign], [])
    assert result.matched is True
    assert result.tier == Tier.C1
    assert result.condition == "suspected_stroke"


def test_stroke_with_warning_sign_still_c1():
    result = query_triage_protocol(["facial_droop", "arm_weakness"], ["speech_difficulty"])
    assert result.matched is True
    assert result.tier == Tier.C1


# ---------------------------------------------------------------------------
# T3 — no silent default to tier B
# ---------------------------------------------------------------------------


def test_no_match_returns_unmatched_with_reason_not_tier_b():
    result = query_triage_protocol(["unrecognised_gibberish_symptom"], [])
    assert result.matched is False
    assert result.tier is None
    assert result.no_match_reason is not None
    assert "human review" in result.no_match_reason.lower()


def test_empty_input_is_no_match():
    result = query_triage_protocol([], [])
    assert result.matched is False
    assert result.no_match_reason is not None


# ---------------------------------------------------------------------------
# T2 — acuity floor: chronic onset exempt, new/unknown onset forces C1
# ---------------------------------------------------------------------------


def test_chronic_onset_does_not_raise_floor():
    base = query_triage_protocol(["fever"], [])
    assert base.tier == Tier.B

    floored = apply_acuity_floor(
        base,
        speech_impairment_signals=["slurred"],
        speech_onset=SpeechOnset.CHRONIC,
        interpretation_confidence=0.95,
        confidence_low_threshold=0.5,
    )
    assert floored.tier == Tier.B
    assert floored.floor_applied is False


@pytest.mark.parametrize("onset", [SpeechOnset.NEW, SpeechOnset.UNKNOWN])
def test_new_or_unknown_onset_raises_floor_to_c1(onset):
    base = query_triage_protocol(["fever"], [])
    assert base.tier == Tier.B

    floored = apply_acuity_floor(
        base,
        speech_impairment_signals=["slurred", "word_finding_pause"],
        speech_onset=onset,
        interpretation_confidence=0.95,
        confidence_low_threshold=0.5,
    )
    assert floored.tier == Tier.C1
    assert floored.floor_applied is True
    assert floored.floor_reason is not None


def test_no_speech_signals_means_no_stroke_floor():
    base = query_triage_protocol(["fever"], [])
    floored = apply_acuity_floor(
        base,
        speech_impairment_signals=[],
        speech_onset=SpeechOnset.NEW,
        interpretation_confidence=0.95,
        confidence_low_threshold=0.5,
    )
    assert floored.tier == Tier.B
    assert floored.floor_applied is False


def test_stroke_floor_can_rescue_an_otherwise_unmatched_case():
    base = query_triage_protocol(["unrecognised_gibberish_symptom"], [])
    assert base.matched is False

    floored = apply_acuity_floor(
        base,
        speech_impairment_signals=["slurred"],
        speech_onset=SpeechOnset.UNKNOWN,
        interpretation_confidence=0.9,
        confidence_low_threshold=0.5,
    )
    assert floored.matched is True
    assert floored.tier == Tier.C1


# ---------------------------------------------------------------------------
# T2 — low confidence raises floor by exactly one step
# ---------------------------------------------------------------------------


def test_low_confidence_raises_tier_by_exactly_one_step():
    base = query_triage_protocol(["fever"], [])
    assert base.tier == Tier.B

    floored = apply_acuity_floor(
        base,
        speech_impairment_signals=[],
        speech_onset=SpeechOnset.UNKNOWN,
        interpretation_confidence=0.1,
        confidence_low_threshold=0.5,
    )
    assert floored.tier == Tier.C2
    assert floored.floor_applied is True


def test_low_confidence_never_skips_past_c1():
    base = query_triage_protocol(["facial_droop"], [])
    assert base.tier == Tier.C1

    floored = apply_acuity_floor(
        base,
        speech_impairment_signals=[],
        speech_onset=SpeechOnset.UNKNOWN,
        interpretation_confidence=0.1,
        confidence_low_threshold=0.5,
    )
    assert floored.tier == Tier.C1


def test_low_confidence_on_unmatched_case_flags_review_without_inventing_tier():
    base = query_triage_protocol(["unrecognised_gibberish_symptom"], [])
    assert base.matched is False

    floored = apply_acuity_floor(
        base,
        speech_impairment_signals=[],
        speech_onset=SpeechOnset.UNKNOWN,
        interpretation_confidence=0.1,
        confidence_low_threshold=0.5,
    )
    assert floored.matched is False
    assert floored.tier is None
    assert "confidence" in floored.no_match_reason.lower()


def test_high_confidence_does_not_raise_floor():
    base = query_triage_protocol(["fever"], [])
    floored = apply_acuity_floor(
        base,
        speech_impairment_signals=[],
        speech_onset=SpeechOnset.UNKNOWN,
        interpretation_confidence=0.95,
        confidence_low_threshold=0.5,
    )
    assert floored.tier == Tier.B
    assert floored.floor_applied is False


# ---------------------------------------------------------------------------
# Other conditions, sanity coverage
# ---------------------------------------------------------------------------


def test_chest_pain_without_warning_sign_is_c2():
    result = query_triage_protocol(["chest_pain"], [])
    assert result.tier == Tier.C2


def test_chest_pain_with_warning_sign_escalates_to_c1():
    result = query_triage_protocol(["chest_pain"], ["crushing_pressure"])
    assert result.tier == Tier.C1


def test_breathing_difficulty_with_cyanosis_is_c1():
    result = query_triage_protocol(["breathing_difficulty"], ["blue_lips_or_face"])
    assert result.tier == Tier.C1


def test_trauma_with_uncontrolled_bleeding_is_c1():
    result = query_triage_protocol(["trauma"], ["uncontrolled_bleeding"])
    assert result.tier == Tier.C1


def test_highest_acuity_condition_wins_when_multiple_match():
    result = query_triage_protocol(["fever", "facial_droop"], [])
    assert result.tier == Tier.C1
    assert result.condition == "suspected_stroke"


# ---------------------------------------------------------------------------
# ingest_protocol.py --check (L10)
# ---------------------------------------------------------------------------


def test_ingest_protocol_check_passes_against_committed_graph():
    completed = subprocess.run(
        [sys.executable, "-m", "swasthya.protocol.ingest_protocol", "--check"],
        cwd=REPO_ROOT,
        env={**__import__("os").environ, "PYTHONPATH": str(REPO_ROOT / "src")},
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "OK" in completed.stdout
