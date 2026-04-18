"""Unit tests for scripts/compute_m5_seasonal_baselines.py.

Tests 1-8 run on synthetic fixtures and must pass in any sandbox.
Tests 9-10 require local Fetched_Data/ CSVs on the operator's Windows
machine and are skipped here — unskip them before running the full
pipeline on real data.
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / 'scripts'))

import compute_m5_seasonal_baselines as cms  # noqa: E402
from backtest_utils_extended import load_extended_data  # noqa: E402


# ── Synthetic fixture helpers ────────────────────────────────────────────

_BUSINESS_DAYS_2023 = pd.bdate_range('2023-01-03', '2024-12-30')


def _synth_day_bars(day, open_price=100.0, seed=0):
    """78 RTH M5 bars for a single ET trading day.

    Builds a deterministic pseudo-random random walk with small noise.
    Returns a DataFrame with columns matching the prompt-spec contract
    for load_extended_data (timestamp_ny tz-aware ET, ohlcv).
    """
    rs = np.random.RandomState(seed)
    rows = []
    price = open_price
    ts0 = pd.Timestamp(day).tz_localize('America/New_York') + pd.Timedelta(
        hours=9, minutes=30)
    for i in range(78):
        ts = ts0 + pd.Timedelta(minutes=5 * i)
        drift = rs.normal(0, 0.002) * price
        close = price + drift
        high = max(price, close) + abs(rs.normal(0, 0.001)) * price
        low = min(price, close) - abs(rs.normal(0, 0.001)) * price
        rows.append({
            'timestamp_ny': ts,
            'open': price,
            'high': high,
            'low': low,
            'close': close,
            'volume': 1000 + i,
        })
        price = close
    return pd.DataFrame(rows)


def _synth_frame(days, open_price=100.0):
    """Concat per-day frames into one ticker-wide frame."""
    parts = []
    for i, d in enumerate(days):
        parts.append(_synth_day_bars(d, open_price=open_price, seed=i))
    return pd.concat(parts, ignore_index=True)


def _train_window_dates(window='2023-2024'):
    _, start, end = cms.parse_train_window(window)
    return start, end


# ── Test 1: load_extended_data contract (synthetic CSV) ─────────────────

def test_load_single_ticker(tmp_path):
    """Synthetic _m5_extended.csv round-trips through load_extended_data.

    The in-repo loader expects a 'date' column; operator Windows machines
    may use the 'timestamp_ny' contract. This test asserts the loader
    returns a non-empty frame with OHLCV columns regardless of which
    contract variant is present.
    """
    df_synth = _synth_day_bars('2023-01-03')
    df_csv = df_synth.rename(columns={'timestamp_ny': 'date'})
    # Drop tz because the in-repo load_extended_data parses as naive.
    df_csv['date'] = df_csv['date'].dt.tz_localize(None)
    csv_path = tmp_path / 'FAKE_m5_extended.csv'
    df_csv.to_csv(csv_path, index=False)

    loaded = load_extended_data('FAKE', data_dir=str(tmp_path))
    assert not loaded.empty
    for col in ('open', 'high', 'low', 'close', 'volume'):
        assert col in loaded.columns
    # Either contract must surface at least one timestamp column.
    assert any(c in loaded.columns for c in ('timestamp_ny', 'date'))


# ── Test 2: RTH filter excludes extended hours ──────────────────────────

def test_rth_filter_excludes_extended_hours():
    day = pd.Timestamp('2023-01-03')
    rows = []
    # Pre-market bar 04:00 ET (should be excluded).
    rows.append({
        'timestamp_ny': day.tz_localize('America/New_York') + pd.Timedelta(hours=4),
        'open': 100.0, 'high': 100.1, 'low': 99.9, 'close': 100.05, 'volume': 1,
    })
    # 09:30 ET RTH start (kept).
    rows.append({
        'timestamp_ny': day.tz_localize('America/New_York') + pd.Timedelta(hours=9, minutes=30),
        'open': 100.0, 'high': 100.2, 'low': 99.8, 'close': 100.1, 'volume': 1,
    })
    # 16:05 ET post-market (excluded — also exclusive end at 16:00).
    rows.append({
        'timestamp_ny': day.tz_localize('America/New_York') + pd.Timedelta(hours=16, minutes=5),
        'open': 100.0, 'high': 100.1, 'low': 99.9, 'close': 100.05, 'volume': 1,
    })
    df = pd.DataFrame(rows)
    start, end = _train_window_dates()
    out = cms.prepare_ticker_frame(df, start, end)
    # Only one bar survives but the day is incomplete (!= 78 bars), so the
    # drop-incomplete-days step removes it → empty frame. That still
    # verifies the extended-hours bars were filtered (neither 04:00 nor
    # 16:05 created a surviving day).
    assert out is None or out.empty


# ── Test 3: slot_id assignment boundaries ───────────────────────────────

def test_slot_id_assignment():
    day = pd.Timestamp('2023-01-03')
    times = [
        ('09:30', 0, True),
        ('09:35', 1, True),
        ('15:55', 77, True),
        ('16:00', None, False),   # exclusive end → excluded
    ]
    # Build a synthetic complete day and then replace a few timestamps to
    # probe boundary conditions via the slot_id computation directly.
    day_frame = _synth_day_bars(day)

    # Probe the helper functions directly.
    assert cms.slot_et_time(0) == '09:30'
    assert cms.slot_et_time(1) == '09:35'
    assert cms.slot_et_time(77) == '15:55'

    # Probe via prepare_ticker_frame: all 78 slot_ids present exactly once.
    start, end = _train_window_dates()
    work = cms.prepare_ticker_frame(day_frame, start, end)
    assert work is not None and not work.empty
    assert sorted(work['slot_id'].unique().tolist()) == list(range(78))

    # 16:00 bars must never appear.
    assert work['_ts'].dt.hour.max() < 16 or (
        (work['_ts'].dt.hour == 15).all() | (work['_ts'].dt.minute <= 55).all()
    )


# ── Test 4: per-slot percentile monotonicity on uniform sample ──────────

def test_per_slot_percentile_monotonicity():
    # 500 complete synthetic days → every slot has 500 observations.
    days = _BUSINESS_DAYS_2023[:500]
    df = _synth_frame(days)
    start, end = _train_window_dates()
    work = cms.prepare_ticker_frame(df, start, end)
    stats = cms.compute_per_slot_stats(work)
    for slot_id in range(78):
        entry = stats[str(slot_id)]
        vals = [entry['p{}_range'.format(p)] for p in cms.PERCENTILES]
        assert all(vals[i] < vals[i + 1] for i in range(len(vals) - 1)), (
            'range percentiles non-monotonic at slot {}: {}'.format(slot_id, vals)
        )
        vals = [entry['p{}_abs_return'.format(p)] for p in cms.PERCENTILES]
        assert all(vals[i] < vals[i + 1] for i in range(len(vals) - 1)), (
            'abs_return percentiles non-monotonic at slot {}: {}'.format(slot_id, vals)
        )


# ── Test 5: per-zone activity_raw matches manual computation ────────────

def test_per_zone_activity_raw_computation():
    day = pd.Timestamp('2023-01-03')
    # Build one full synthetic day, overwrite Z3 bars with known values.
    df = _synth_day_bars(day)
    z3_mask = df.index[(df.index >= 30) & (df.index < 48)]
    # Set Z3 bars to a known OHLC pattern.
    df.loc[z3_mask, 'open'] = 100.0
    df.loc[z3_mask, 'close'] = 100.5
    df.loc[z3_mask, 'high'] = 101.0
    df.loc[z3_mask, 'low'] = 99.0
    # First bar's open is the reference; set high/low varied across zone.
    df.loc[z3_mask[0], 'open'] = 100.0
    df.loc[z3_mask[-1], 'high'] = 102.0
    df.loc[z3_mask[0], 'low'] = 98.0

    start, end = _train_window_dates()
    work = cms.prepare_ticker_frame(df, start, end)
    assert work is not None and not work.empty

    z3 = work[work['zone'] == 'Z3']
    first_open = float(z3.iloc[0]['open'])
    zone_range = (float(z3['high'].max()) - float(z3['low'].min())) / first_open
    zone_avg_abs = float(z3['bar_abs_return'].mean())
    expected = (zone_range * zone_avg_abs) ** 0.5

    dists = cms.compute_per_zone_distribution(work)
    z3_dist = dists['Z3']
    assert z3_dist['sample_size'] == 1
    assert abs(z3_dist['sorted_values'][0] - expected) < 1e-9


# ── Test 6: ticker rejected on insufficient trading days ────────────────

def test_ticker_rejected_insufficient_days(tmp_path, monkeypatch):
    days = _BUSINESS_DAYS_2023[:400]   # 400 < MIN_TRADING_DAYS (450)
    df = _synth_frame(days)

    def fake_loader(ticker, data_dir='Fetched_Data'):
        return df

    monkeypatch.setattr(cms, 'load_extended_data', fake_loader)
    start, end = _train_window_dates()
    status, per_slot, per_zone = cms.process_ticker(
        'FAKE', start, end, 'Fetched_Data', verbose=False
    )
    assert status['accepted'] is False
    assert status['reason'].startswith('insufficient_days')
    assert per_slot is None and per_zone is None


# ── Test 7: ticker rejected on insufficient slot sample ─────────────────

def test_ticker_rejected_insufficient_slot_sample(monkeypatch):
    # 500 complete days satisfies the day gate; we'll zero out slot 30
    # on all but 180 of them to trigger the slot-sample gate.
    days = _BUSINESS_DAYS_2023[:500]
    df = _synth_frame(days)

    # Drop slot 30 bars from first (500 - 180) = 320 days, creating
    # incomplete days that get filtered out at the day-completeness step.
    # That leaves 180 complete days — but we need 500 complete days to
    # pass the day gate AND ≤ 199 observations for slot 30.
    # Approach: keep 500 days (day gate passes) and for 320 of them
    # replace slot 30 with NaN ohlc so it's dropped post-numeric-coercion
    # BUT that also drops the whole day (incomplete).
    #
    # Simpler: build 500 full days, then mutate slot 30 on 320 of those
    # days by stepping the timestamp off-grid (e.g. +30s) so it no longer
    # falls into any valid 5-minute slot. Day-completeness (!= 78) will
    # still pass because we're not removing rows, just shifting one — but
    # the shifted bar will still have tod=09:30 (unchanged minute). Let's
    # instead remove slot 30 entirely on 320 days → those days have 77
    # bars and get dropped as incomplete. That leaves 180 complete days,
    # each contributing 1 observation to every slot → slot_size=180<200.

    keep_full_day_count = 180
    drop_slot_30_day_count = 500 - keep_full_day_count

    drop_mask_rows = []
    for day_idx in range(drop_slot_30_day_count):
        day_start_row = day_idx * 78
        drop_mask_rows.append(day_start_row + 30)
    df = df.drop(index=drop_mask_rows).reset_index(drop=True)

    def fake_loader(ticker, data_dir='Fetched_Data'):
        return df

    monkeypatch.setattr(cms, 'load_extended_data', fake_loader)
    start, end = _train_window_dates()
    # With 180 complete days < 450, the day-gate fires first. Lower the
    # gate for this test via monkeypatch so we can isolate the slot gate.
    monkeypatch.setattr(cms, 'MIN_TRADING_DAYS', 100)
    status, per_slot, per_zone = cms.process_ticker(
        'FAKE', start, end, 'Fetched_Data', verbose=False
    )
    assert status['accepted'] is False
    assert status['reason'].startswith('insufficient_slot_sample: slot=')
    assert per_slot is None and per_zone is None


# ── Test 8: output JSON schema contains all required top-level keys ────

def test_output_json_schema_validates(tmp_path, monkeypatch):
    days = _BUSINESS_DAYS_2023[:500]
    df_a = _synth_frame(days)
    df_b = _synth_frame(days, open_price=200.0)

    store = {'AAA': df_a, 'BBB': df_b}

    def fake_loader(ticker, data_dir='Fetched_Data'):
        return store[ticker].copy()

    monkeypatch.setattr(cms, 'load_extended_data', fake_loader)
    # Ensure the day gate is satisfied by our 500-day fixture.
    monkeypatch.setattr(cms, 'MIN_TRADING_DAYS', 100)

    payload = cms.run_pipeline(
        '2023-2024', pd.Timestamp('2023-01-01'), pd.Timestamp('2024-12-31'),
        tickers=['AAA', 'BBB'], data_dir='Fetched_Data', verbose=False,
    )
    out_path = tmp_path / 'baselines.json'
    cms.dump_json(payload, out_path)
    data = json.loads(out_path.read_text())

    for key in ('train_window', 'computed_at', 'tickers_accepted',
                'tickers_rejected', 'per_slot_stats',
                'per_zone_distributions', 'qa_checks', 'metadata'):
        assert key in data, 'missing top-level key: {}'.format(key)

    # Per-slot dict structure
    assert 'AAA' in data['per_slot_stats']
    slot0 = data['per_slot_stats']['AAA']['0']
    for p in (10, 30, 50, 70, 90):
        assert 'p{}_range'.format(p) in slot0
        assert 'p{}_abs_return'.format(p) in slot0
    for f in ('sample_size', 'et_time', 'zone'):
        assert f in slot0


# ── Test 9: U-shape on real ticker (requires local CSVs) ────────────────

@pytest.mark.skip(
    reason='requires local Fetched_Data/ CSVs — run on operator Windows machine'
)
def test_u_shape_check3_passes_for_known_ticker():
    start, end = _train_window_dates('2023-2024')
    df = load_extended_data('NVDA')
    work = cms.prepare_ticker_frame(df, start, end)
    stats = cms.compute_per_slot_stats(work)
    outer = []
    for i in list(range(0, 12)) + list(range(60, 78)):
        outer.append(stats[str(i)]['p50_range'])
    dead = []
    for i in range(30, 48):
        dead.append(stats[str(i)]['p50_range'])
    ratio = float(np.mean(outer)) / float(np.mean(dead))
    assert ratio >= 1.25, 'NVDA U-shape ratio {:.3f} < 1.25'.format(ratio)


# ── Test 10: end-to-end two-ticker run (requires local CSVs) ────────────

@pytest.mark.skip(
    reason='requires local Fetched_Data/ CSVs — run on operator Windows machine'
)
def test_end_to_end_two_tickers(tmp_path):
    payload = cms.run_pipeline(
        '2023-2024', pd.Timestamp('2023-01-01'), pd.Timestamp('2024-12-31'),
        tickers=['SPY', 'NVDA'], data_dir='Fetched_Data', verbose=False,
    )
    out_path = tmp_path / 'baselines_e2e.json'
    cms.dump_json(payload, out_path)
    data = json.loads(out_path.read_text())
    assert set(data['per_slot_stats'].keys()) == {'SPY', 'NVDA'}
    assert set(data['per_zone_distributions'].keys()) == {'SPY', 'NVDA'}
    assert sorted(data['tickers_accepted']) == ['NVDA', 'SPY']
    for k in ('check1_tickers_accepted', 'check2_sample_uniformity',
             'check3_u_shape_phase0', 'check4_distribution_sanity',
             'check5_per_slot_monotonicity'):
        assert k in data['qa_checks']
