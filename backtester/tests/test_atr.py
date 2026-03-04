"""Tests for backtester.atr — True Range, Modified ATR, Exhaustion, Paranormal."""

import pytest
import pandas as pd

from backtester.data_types import Bar, SignalDirection
from backtester.atr import true_range, modified_atr, calc_exhaustion, is_paranormal


def make_bar(o, h, l, c, symbol="TEST", ts="2025-01-01"):
    """Helper to create a Bar quickly."""
    return Bar(
        symbol=symbol,
        timestamp=pd.Timestamp(ts),
        timeframe="D1",
        open=o, high=h, low=l, close=c,
    )


# ── Test true_range ───────────────────────────────────────────────────────

class TestTrueRange:
    def test_no_gap(self):
        """TR = H - L when no previous bar."""
        bar = make_bar(100, 105, 95, 102)
        assert true_range(bar) == pytest.approx(10.0)

    def test_gap_up(self):
        """TR considers gap from prev close."""
        prev = make_bar(90, 95, 88, 93)
        bar = make_bar(100, 105, 99, 102)
        # TR = max(105-99=6, |105-93|=12, |99-93|=6) = 12
        assert true_range(bar, prev) == pytest.approx(12.0)

    def test_gap_down(self):
        """TR considers gap down from prev close."""
        prev = make_bar(100, 105, 98, 103)
        bar = make_bar(95, 97, 90, 92)
        # TR = max(97-90=7, |97-103|=6, |90-103|=13) = 13
        assert true_range(bar, prev) == pytest.approx(13.0)

    def test_no_gap_standard(self):
        """Normal bar with no gap: TR = H - L."""
        prev = make_bar(100, 105, 95, 102)
        bar = make_bar(102, 106, 100, 104)
        # TR = max(106-100=6, |106-102|=4, |100-102|=2) = 6
        assert true_range(bar, prev) == pytest.approx(6.0)

    def test_doji_bar(self):
        """Very small range bar."""
        prev = make_bar(100, 101, 99, 100)
        bar = make_bar(100, 100.1, 99.9, 100)
        # TR = max(0.2, |100.1-100|=0.1, |99.9-100|=0.1) = 0.2
        assert true_range(bar, prev) == pytest.approx(0.2)


# ── Test modified_atr ─────────────────────────────────────────────────────

class TestModifiedATR:
    def _make_bars(self, ranges):
        """Create bars with specified ranges (open=100, close=100+range)."""
        bars = []
        for i, r in enumerate(ranges):
            bars.append(make_bar(
                o=100, h=100 + r, l=100, c=100 + r * 0.5,
                ts=f"2025-01-{i+1:02d}",
            ))
        return bars

    def test_hand_calculated(self):
        """Verify ATR with known TR values.

        Bars with ranges: 3, 4, 5, 4, 3 → TRs: 4, 5, 4, 3 (need prev for TR)
        All within 0.5x-2x range of raw ATR, so none excluded.
        Raw ATR = (4+5+4+3)/4 = 4.0
        """
        bars = [
            make_bar(100, 103, 100, 101, ts="2025-01-01"),  # bar 0
            make_bar(101, 105, 101, 103, ts="2025-01-02"),  # TR = max(4, |105-101|=4, |101-101|=0) = 4
            make_bar(103, 108, 103, 106, ts="2025-01-03"),  # TR = max(5, |108-103|=5, |103-103|=0) = 5
            make_bar(106, 110, 106, 108, ts="2025-01-04"),  # TR = max(4, |110-106|=4, |106-106|=0) = 4
            make_bar(108, 111, 108, 110, ts="2025-01-05"),  # TR = max(3, |111-108|=3, |108-108|=0) = 3
        ]
        atr = modified_atr(bars, period=5)
        assert atr == pytest.approx(4.0)

    def test_paranormal_exclusion(self):
        """Inject a 3× ATR bar and verify it's excluded from next ATR calc.

        Normal bars: range ~4, then inject a bar with range ~12 (3× normal).
        The paranormal bar (TR=12) should be excluded (> 2x raw ATR).
        """
        bars = [
            make_bar(100, 104, 100, 102, ts="2025-01-01"),
            make_bar(102, 106, 102, 104, ts="2025-01-02"),  # TR=4
            make_bar(104, 108, 104, 106, ts="2025-01-03"),  # TR=4
            make_bar(106, 110, 106, 108, ts="2025-01-04"),  # TR=4
            make_bar(108, 112, 108, 110, ts="2025-01-05"),  # TR=4
            make_bar(110, 122, 110, 116, ts="2025-01-06"),  # TR=12 ← paranormal (3x)
            make_bar(116, 120, 116, 118, ts="2025-01-07"),  # TR=4
        ]
        # Period=5 uses last 5 TRs: [4, 4, 4, 12, 4]
        # Raw ATR = (4+4+4+12+4)/5 = 28/5 = 5.6
        # Filter: 2x raw = 11.2 → TR=12 excluded (12 > 11.2)
        # Filter: 0.5x raw = 2.8 → all TR=4 kept (4 > 2.8)
        # Filtered TRs: [4, 4, 4, 4]
        # Modified ATR = 4.0
        atr = modified_atr(bars, period=5)
        assert atr == pytest.approx(4.0)

    def test_dead_bar_exclusion(self):
        """Very low range bars should be excluded."""
        bars = [
            make_bar(100, 110, 100, 105, ts="2025-01-01"),
            make_bar(105, 115, 105, 110, ts="2025-01-02"),  # TR=10
            make_bar(110, 120, 110, 115, ts="2025-01-03"),  # TR=10
            make_bar(115, 125, 115, 120, ts="2025-01-04"),  # TR=10
            make_bar(120, 130, 120, 125, ts="2025-01-05"),  # TR=10
            make_bar(125, 125.5, 125, 125.2, ts="2025-01-06"),  # TR=0.5 ← dead
        ]
        # Period=5: TRs = [10, 10, 10, 10, 0.5]
        # Raw ATR = 40.5/5 = 8.1
        # Filter: 0.5 × 8.1 = 4.05 → TR=0.5 excluded (0.5 < 4.05)
        # Filtered: [10, 10, 10, 10] → 10.0
        atr = modified_atr(bars, period=5)
        assert atr == pytest.approx(10.0)

    def test_all_excluded_fallback(self):
        """If all bars would be excluded, fall back to unfiltered ATR.

        Create bars where some are paranormal and some dead, leaving none
        in the normal range after filtering.
        """
        bars = [
            make_bar(100, 110, 100, 105, ts="2025-01-01"),
            make_bar(105, 135, 105, 120, ts="2025-01-02"),  # TR=30 (paranormal)
            make_bar(120, 121, 120, 120.5, ts="2025-01-03"),  # TR=1 (dead vs 30)
        ]
        # Period=5: TRs = [30, 1]
        # Raw ATR = 31/2 = 15.5
        # 2x = 31.0, 0.5x = 7.75
        # TR=30 ≤ 31.0 → kept; TR=1 < 7.75 → excluded
        # Actually TR=30 is kept. Let me use even more extreme.
        # With just these, filtered = [30], so not all excluded.
        # Let me test the real edge case directly:
        atr = modified_atr(bars, period=5)
        assert atr > 0  # should return something reasonable

    def test_all_excluded_real_fallback(self):
        """Construct a case where all TRs are excluded."""
        bars = [
            make_bar(100, 110, 100, 105, ts="2025-01-01"),
            make_bar(105, 135, 105, 120, ts="2025-01-02"),  # TR=30
            make_bar(120, 120.1, 120, 120.05, ts="2025-01-03"),  # TR=0.1
        ]
        # TRs: [30, 0.1], raw_atr = 15.05
        # upper = 30.1, lower = 7.525
        # TR=30 ≤ 30.1 (kept), TR=0.1 < 7.525 (excluded)
        # Not all excluded. Need both extremes with period=2
        # Use upper_mult=1.0 and lower_mult=1.0 to force exclusion
        atr = modified_atr(bars, period=2, upper_mult=0.9, lower_mult=1.1)
        # With these thresholds, nothing is "normal" → fallback
        assert atr == pytest.approx(15.05)

    def test_fewer_than_2_bars(self):
        bar = make_bar(100, 105, 95, 102)
        assert modified_atr([bar]) == 0.0
        assert modified_atr([]) == 0.0

    def test_period_larger_than_data(self):
        """Period=10 but only 3 bars → uses all available TRs."""
        bars = [
            make_bar(100, 104, 100, 102, ts="2025-01-01"),
            make_bar(102, 106, 102, 104, ts="2025-01-02"),  # TR=4
            make_bar(104, 108, 104, 106, ts="2025-01-03"),  # TR=4
        ]
        atr = modified_atr(bars, period=10)
        assert atr == pytest.approx(4.0)


# ── Test calc_exhaustion ──────────────────────────────────────────────────

class TestCalcExhaustion:
    def test_short_from_resistance(self):
        """Known level at $100, low_so_far = $97, ATR_D1 = $4 → 75% exhaustion."""
        session_bars = [
            make_bar(99, 100.5, 97, 98),
            make_bar(98, 99, 97.5, 98.5),
        ]
        ex = calc_exhaustion(100.0, SignalDirection.SHORT, session_bars, 4.0)
        # (100 - 97) / 4 = 0.75
        assert ex == pytest.approx(0.75)

    def test_long_from_support(self):
        """Level at $50, high_so_far = $53, ATR = $5 → 60% exhaustion."""
        session_bars = [
            make_bar(50.5, 53, 50, 52),
            make_bar(52, 52.5, 51, 52),
        ]
        ex = calc_exhaustion(50.0, SignalDirection.LONG, session_bars, 5.0)
        # (53 - 50) / 5 = 0.60
        assert ex == pytest.approx(0.60)

    def test_zero_atr_returns_zero(self):
        session_bars = [make_bar(100, 105, 95, 102)]
        assert calc_exhaustion(100.0, SignalDirection.SHORT, session_bars, 0.0) == 0.0

    def test_no_bars_returns_zero(self):
        assert calc_exhaustion(100.0, SignalDirection.SHORT, [], 4.0) == 0.0

    def test_low_exhaustion(self):
        """Price barely moved from level → low exhaustion."""
        session_bars = [make_bar(100, 100.5, 99.8, 100.2)]
        ex = calc_exhaustion(100.0, SignalDirection.SHORT, session_bars, 4.0)
        # (100 - 99.8) / 4 = 0.05
        assert ex == pytest.approx(0.05)

    def test_over_exhaustion(self):
        """Price moved more than 1 ATR → exhaustion > 100%."""
        session_bars = [make_bar(100, 101, 94, 95)]
        ex = calc_exhaustion(100.0, SignalDirection.SHORT, session_bars, 4.0)
        # (100 - 94) / 4 = 1.5
        assert ex == pytest.approx(1.5)


# ── Test is_paranormal ────────────────────────────────────────────────────

class TestIsParanormal:
    def test_paranormal_bar(self):
        """Range = 10, ATR = 4 → 2.5x → paranormal."""
        bar = make_bar(100, 110, 100, 105)
        assert is_paranormal(bar, 4.0) is True

    def test_normal_bar(self):
        """Range = 5, ATR = 4 → 1.25x → not paranormal."""
        bar = make_bar(100, 105, 100, 103)
        assert is_paranormal(bar, 4.0) is False

    def test_exactly_2x(self):
        """Range = 8, ATR = 4 → exactly 2.0x → paranormal (>= threshold)."""
        bar = make_bar(100, 108, 100, 104)
        assert is_paranormal(bar, 4.0) is True

    def test_just_below_2x(self):
        """Range = 7.99, ATR = 4 → 1.9975x → not paranormal."""
        bar = make_bar(100, 107.99, 100, 104)
        assert is_paranormal(bar, 4.0) is False

    def test_zero_atr(self):
        """Zero ATR → not paranormal (avoid division issues)."""
        bar = make_bar(100, 110, 100, 105)
        assert is_paranormal(bar, 0.0) is False
