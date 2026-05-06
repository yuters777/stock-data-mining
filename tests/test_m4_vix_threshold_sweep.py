"""Tests for m4_vix_threshold_sweep.py - sweep correctness."""
from scripts.m4_vix_threshold_sweep import (
    VIX_THRESHOLDS,
    VIX_BUCKETS,
    analyze_per_bucket,
)


def test_vix_thresholds_includes_25():
    """Canonical M4 gate=25 must be in tested thresholds (regression check)."""
    assert 25.0 in VIX_THRESHOLDS


def test_vix_buckets_cover_continuous_range_above_20():
    """Buckets must tile the VIX range without gaps from 20.0 onward."""
    sorted_buckets = sorted(VIX_BUCKETS, key=lambda b: b[0])
    for i in range(len(sorted_buckets) - 1):
        assert sorted_buckets[i][1] == sorted_buckets[i + 1][0], (
            f"Gap between {sorted_buckets[i]} and {sorted_buckets[i + 1]}"
        )


def test_analyze_per_bucket_handles_empty_trades():
    """Empty trades list -> all buckets N=0, PF None."""
    result = analyze_per_bucket([])
    for label in [b[2] for b in VIX_BUCKETS]:
        assert result[label]["N"] == 0
        assert result[label]["PF"] is None


def test_analyze_per_bucket_assigns_to_correct_range():
    """Trades are assigned to buckets via half-open [low, high) intervals."""
    fake_trades = [
        {"vix_at_entry": 23.5, "return_pct": 0.05},
        {"vix_at_entry": 27.0, "return_pct": -0.02},
        {"vix_at_entry": 23.5, "return_pct": 0.03},
    ]
    result = analyze_per_bucket(fake_trades)
    assert result["22-25"]["N"] == 2  # both 23.5 trades
    assert result["25-30"]["N"] == 1  # 27.0 trade
    for label in ["20-22", "30-35", "35+"]:
        assert result[label]["N"] == 0


def test_analyze_per_bucket_boundary_value_falls_in_upper_bucket():
    """VIX=22.0 falls in '22-25' (half-open), not '20-22'."""
    fake_trades = [
        {"vix_at_entry": 22.0, "return_pct": 0.01},
        {"vix_at_entry": 25.0, "return_pct": 0.01},
    ]
    result = analyze_per_bucket(fake_trades)
    assert result["20-22"]["N"] == 0
    assert result["22-25"]["N"] == 1
    assert result["25-30"]["N"] == 1
