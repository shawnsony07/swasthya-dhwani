"""Tests verifying that the L12 evaluation harness passes all release gates."""
from __future__ import annotations

from scripts.run_evaluation import run_evaluation


def test_evaluation_harness_passes_all_release_gates():
    assert run_evaluation() is True
