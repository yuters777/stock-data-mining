"""Unit tests for scripts/add_entry_timestamps.py (BT-0).

All 10 tests use synthetic fixtures — no real CSVs are opened.
"""
from __future__ import annotations

import sys
from io import StringIO
from pathlib import Path

import pandas as pd
import pytest

_REPO = Path(__file__).resolve().parents[1]
for _p in (str(_REPO), str(_REPO / 'scripts')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import add_entry_timestamps as ats  # noqa: E402


# ── helpers ──────────────────────────────────────────────────────────────────

def _write_csv(tmp_path: Path, rows: list[dict], filename: str = 'trades.csv') -> Path:
    df = pd.DataFrame(rows)
    p = tmp_path / filename
    df.to_csv(p, index=False, encoding='utf-8')
    return p


# ── 1. slot_to_zone boundaries ────────────────────────────────────────────────

def test_slot_to_zone_boundaries():
    assert ats.slot_to_zone(0) == 'Z1'
    assert ats.slot_to_zone(11) == 'Z1'
    assert ats.slot_to_zone(12) == 'Z2'
    assert ats.slot_to_zone(29) == 'Z2'
    assert ats.slot_to_zone(30) == 'Z3'
    assert ats.slot_to_zone(47) == 'Z3'
    assert ats.slot_to_zone(48) == 'Z4'
    assert ats.slot_to_zone(59) == 'Z4'
    assert ats.slot_to_zone(60) == 'Z5'
    assert ats.slot_to_zone(77) == 'Z5'
    assert ats.slot_to_zone(-1) is None
    assert ats.slot_to_zone(78) is None


# ── 2. et_time_to_slot boundaries ─────────────────────────────────────────────

def test_et_time_to_slot_boundaries():
    assert ats.et_time_to_slot(9, 30) == 0
    assert ats.et_time_to_slot(9, 35) == 1
    assert ats.et_time_to_slot(13, 25) == 47
    assert ats.et_time_to_slot(13, 30) == 48
    assert ats.et_time_to_slot(15, 55) == 77
    assert ats.et_time_to_slot(16, 0) is None
    assert ats.et_time_to_slot(9, 29) is None
    assert ats.et_time_to_slot(4, 0) is None


# ── 3. compute_entry_close_time: RTH bar 1 ────────────────────────────────────

def test_compute_entry_close_time_rth_bar_1():
    # Bar 1: start 09:30 + 4h - 5min = 13:25
    assert ats.compute_entry_close_time('1') == (13, 25)


# ── 4. compute_entry_close_time: RTH bar 2 ────────────────────────────────────

def test_compute_entry_close_time_rth_bar_2():
    # Bar 2 ends at market close: override to 15:55
    assert ats.compute_entry_close_time('2') == (15, 55)


# ── 5. compute_entry_close_time: extended bar C ───────────────────────────────

def test_compute_entry_close_time_ext_c():
    # Bar C: start 12:00 + 4h - 5min = 15:55
    assert ats.compute_entry_close_time('C') == (15, 55)


# ── 6. compute_entry_close_time: extended bar A (pre-market) ─────────────────

def test_compute_entry_close_time_ext_a():
    # Bar A: start 04:00 + 4h - 5min = 07:55
    assert ats.compute_entry_close_time('A') == (7, 55)


# ── 7. enrich_csv: RTH trades (bars 1, 2, 1) ─────────────────────────────────

def test_enrich_csv_rth_trades(tmp_path):
    rows = [
        {'entry_date': '2024-01-15', 'entry_bar': '1', 'entry_price': 100.0},
        {'entry_date': '2024-01-16', 'entry_bar': '2', 'entry_price': 101.0},
        {'entry_date': '2024-01-17', 'entry_bar': '1', 'entry_price': 102.0},
    ]
    in_path = _write_csv(tmp_path, rows)
    out_path = tmp_path / 'out.csv'

    ats.enrich_csv(in_path, out_path, has_entry_bar=True)

    df = pd.read_csv(out_path)
    assert list(df['entry_ts_ny']) == [
        '2024-01-15T13:25:00',
        '2024-01-16T15:55:00',
        '2024-01-17T13:25:00',
    ]
    assert list(df['entry_slot_id']) == [47, 77, 47]
    assert list(df['entry_zone']) == ['Z3', 'Z5', 'Z3']


# ── 8. enrich_csv: extended bars A and D → OUT_OF_RTH ────────────────────────

def test_enrich_csv_extended_a_d_marked_out_of_rth(tmp_path):
    rows = [
        {'entry_date': '2024-03-01', 'entry_bar': 'A', 'entry_price': 50.0},
        {'entry_date': '2024-03-01', 'entry_bar': 'D', 'entry_price': 55.0},
    ]
    in_path = _write_csv(tmp_path, rows)
    out_path = tmp_path / 'out.csv'

    result = ats.enrich_csv(in_path, out_path, has_entry_bar=True)

    df = pd.read_csv(out_path)
    assert list(df['entry_zone']) == ['OUT_OF_RTH', 'OUT_OF_RTH']
    assert list(df['entry_slot_id']) == [-1, -1]
    assert result['out_of_rth_count'] == 2


# ── 9. enrich_csv: M7 default label '2' → all Z5 ─────────────────────────────

def test_enrich_csv_m7_default_label(tmp_path):
    rows = [
        {'entry_date': '2024-02-01', 'entry_price': 200.0, 'return_pct': 0.01},
        {'entry_date': '2024-02-05', 'entry_price': 205.0, 'return_pct': -0.02},
        {'entry_date': '2024-02-10', 'entry_price': 198.0, 'return_pct': 0.03},
    ]
    in_path = _write_csv(tmp_path, rows)
    out_path = tmp_path / 'out.csv'

    ats.enrich_csv(in_path, out_path, has_entry_bar=False, default_bar_label_for_missing='2')

    df = pd.read_csv(out_path)
    assert list(df['entry_zone']) == ['Z5', 'Z5', 'Z5']
    assert list(df['entry_slot_id']) == [77, 77, 77]


# ── 10. enrich_csv: row count preserved ──────────────────────────────────────

def test_enrich_csv_row_count_preserved(tmp_path):
    rows = [
        {'entry_date': f'2024-01-{d:02d}', 'entry_bar': bar, 'entry_price': 100.0 + d}
        for d, bar in enumerate(['B', 'C', '1', '2', 'B', 'C'], start=1)
    ]
    in_path = _write_csv(tmp_path, rows)
    out_path = tmp_path / 'out.csv'

    result = ats.enrich_csv(in_path, out_path, has_entry_bar=True)

    assert result['rows_read'] == 6
    assert result['rows_written'] == 6
    df = pd.read_csv(out_path)
    assert len(df) == 6
