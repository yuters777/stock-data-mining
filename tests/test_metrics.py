"""Tests for scripts/_metrics.py — synthetic data only."""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts._metrics import bootstrap_pf_ci, compute_metrics, holm_bonferroni


def test_compute_metrics_empty():
    m = compute_metrics([])
    assert m["N"] == 0
    assert math.isnan(m["PF"])
    assert math.isnan(m["WR"])


def test_compute_metrics_basic():
    m = compute_metrics([0.05, -0.02, 0.03])
    assert m["N"] == 3
    assert m["PF"] == pytest.approx(0.08 / 0.02)  # (0.05+0.03)/0.02 = 4.0
    assert m["WR"] == pytest.approx(2 / 3)
    assert m["mean"] == pytest.approx(0.02)


def test_bootstrap_pf_ci_reproducible():
    returns = [0.1, -0.05, 0.08, -0.02, 0.06]
    ci1 = bootstrap_pf_ci(returns, iterations=100, seed=42)
    ci2 = bootstrap_pf_ci(returns, iterations=100, seed=42)
    assert ci1 == ci2
    assert ci1[0] < ci1[1]


def test_holm_bonferroni_all_significant():
    p = {"a": 0.001, "b": 0.005, "c": 0.01}
    result = holm_bonferroni(p, alpha=0.05)
    assert result == {"a": True, "b": True, "c": True}


def test_holm_bonferroni_partial():
    # a: 0.01 <= 0.05/3=0.0167 → True
    # b: 0.04 > 0.05/2=0.025 → False (step-down halts)
    # c: 0.10 → False
    p = {"a": 0.01, "b": 0.04, "c": 0.10}
    result = holm_bonferroni(p, alpha=0.05)
    assert result["a"] is True
    assert result["b"] is False
    assert result["c"] is False
