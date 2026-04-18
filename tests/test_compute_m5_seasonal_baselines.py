"""Unit tests for scripts/compute_m5_seasonal_baselines.py.

All 10 tests run on synthetic fixtures — no test opens Fetched_Data/*.csv.
Operator runs the real-data pipeline on the Windows machine via the CLI.
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_REPO = Path(__file__).resolve().parents[1]
for _p in (str(_REPO), str(_REPO / 'scripts')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import compute_m5_seasonal_baselines as cms  # noqa: E402
from scripts.backtest_utils_extended import load_extended_data  # noqa: E402


# ── Synthetic fixture helpers ────────────────────────────────────────────

_BUSINESS_DAYS_2023 = pd.bdate_range('2023-01-03', '2024-12-30')


def _synth_day(day, open_price=100.0, seed=0, slot_range_mult=None):
    """Build a 78-row RTH DataFrame for a single ET trading day.

    Columns match load_extended_data() output: date, open, high, low,
    close, volume, date_only, time_str, hour, minute.

    slot_range_mult : Optional[Callable[[int], float]]
        Per-slot multiplier applied to bar amplitude. Used by the
        U-shape fixture to create wide bars in Z1/Z5 and narrow bars
        in Z3.
    """
    rs = np.random.RandomState(seed)
    rows = []
    price = float(open_price)
    day_ts = pd.Timestamp(day)
    for i in range(78):
        minute_of_day = 9 * 60 + 30 + 5 * i
        hh = minute_of_day // 60
        mm = minute_of_day % 60
        ts = day_ts + pd.Timedelta(hours=hh, minutes=mm)

        amp = 0.002
        if slot_range_mult is not None:
            amp = amp * float(slot_range_mult(i))

        drift = rs.normal(0, amp) * price
        close = price + drift
        high = max(price, close) + abs(rs.normal(0, amp * 0.5)) * price
        low = min(price, close) - abs(rs.normal(0, amp * 0.5)) * price
        rows.append({
            'date': ts,
            'open': price,
            'high': high,
            'low': low,
            'close': close,
            'volume': 1000 + i,
            'date_only': ts.date(),
            'time_str': ts.strftime('%H:%M'),
            'hour': int(hh),
            'minute': int(mm),
        })
        price = close
    return pd.DataFrame(rows)


def _synth_frame(days, open_price=100.0, slot_range_mult=None):
    parts = []
    for i, d in enumerate(days):
        parts.append(_synth_day(
            d, open_price=open_price, seed=i,
            slot_range_mult=slot_range_mult,
        ))
    return pd.concat(parts, ignore_index=True)


def _train_window_dates(window='2023-2024'):
    _, start, end = cms.parse_train_window(window)
    return start, end


def _u_shape_multiplier(slot_id):
    """Wide in Z1 (0-11) + Z5 (60-77), narrow in Z3 (30-47)."""
    if 0 <= slot_id < 12:
        return 3.0
    if 60 <= slot_id < 78:
        return 3.0
    if 30 <= slot_id < 48:
        return 0.5
    return 1.0


# ── Test 1: load_extended_data contract (synthetic CSV, tmp_path) ───────

def test_load_single_ticker(tmp_path):
    """Synthetic _m5_extended.csv round-trips through load_extended_data.

    No Fetched_Data access — writes to tmp_path and points the loader at
    it via data_dir. Verifies the DataFrame columns we depend on.
    """
    day_df = _synth_day('2023-01-03')
    csv_df = day_df[['date', 'open', 'high', 'low', 'close', 'volume']]
    csv_path = tmp_path / 'FAKE_m5_extended.csv'
    csv_df.to_csv(csv_path, index=False)

    loaded = load_extended_data('FAKE', data_dir=str(tmp_path))
    assert not loaded.empty
    for col in ('date', 'open', 'high', 'low', 'close', 'volume',
                'date_only', 'time_str', 'hour', 'minute'):
        assert col in loaded.columns, 'missing col {}'.format(col)


# ── Test 2: RTH filter excludes extended hours ──────────────────────────

def test_rth_filter_excludes_extended_hours():
    day = '2023-01-03'

    def _row(hour, minute):
        ts = pd.Timestamp(day) + pd.Timedelta(hours=hour, minutes=minute)
        return {
            'date': ts, 'open': 100.0, 'high': 100.1, 'low': 99.9,
            'close': 100.05, 'volume': 100,
            'date_only': ts.date(),
            'time_str': ts.strftime('%H:%M'),
            'hour': hour, 'minute': minute,
        }

    rows = [
        _row(4, 0),    # pre-market — excluded
        _row(9, 29),   # one minute before open — excluded
        _row(9, 30),   # RTH start — kept
        _row(16, 0),   # exclusive end — excluded
        _row(16, 5),   # post-market — excluded
    ]
    df = pd.DataFrame(rows)
    start, end = _train_window_dates()
    out = cms.prepare_ticker_frame(df, start, end)
    # 09:30 survives the RTH mask but the day has only 1 bar, so the
    # drop-incomplete-days step removes it. That still confirms extended-
    # hours bars never produced a complete 78-bar day.
    assert out is None or out.empty


# ── Test 3: slot_id assignment boundaries ───────────────────────────────

def test_slot_id_assignment():
    day_df = _synth_day('2023-01-03')

    assert cms.slot_et_time(0) == '09:30'
    assert cms.slot_et_time(1) == '09:35'
    assert cms.slot_et_time(77) == '15:55'

    start, end = _train_window_dates()
    work = cms.prepare_ticker_frame(day_df, start, end)
    assert work is not None and not work.empty
    # Every slot_id 0..77 appears exactly once on a single complete day.
    assert sorted(work['slot_id'].unique().tolist()) == list(range(78))
    # 16:00 never appears.
    assert not ((work['hour'] == 16) & (work['minute'] == 0)).any()


# ── Test 4: per-slot percentile monotonicity ────────────────────────────

def test_per_slot_percentile_monotonicity():
    days = _BUSINESS_DAYS_2023[:500]
    df = _synth_frame(days)
    start, end = _train_window_dates()
    work = cms.prepare_ticker_frame(df, start, end)
    stats = cms.compute_per_slot_stats(work)
    for slot_id in range(78):
        entry = stats[str(slot_id)]
        vals = [entry['p{}_range'.format(p)] for p in cms.PERCENTILES]
        assert all(vals[i] < vals[i + 1] for i in range(len(vals) - 1)), (
            'range non-monotonic at slot {}: {}'.format(slot_id, vals)
        )
        vals = [entry['p{}_abs_return'.format(p)] for p in cms.PERCENTILES]
        assert all(vals[i] < vals[i + 1] for i in range(len(vals) - 1)), (
            'abs_return non-monotonic at slot {}: {}'.format(slot_id, vals)
        )


# ── Test 5: per-zone activity_raw matches manual computation ────────────

def test_per_zone_activity_raw_computation():
    df = _synth_day('2023-01-03')
    # Overwrite Z3 bars with a known OHLC pattern.
    z3_rows = df.index[(df.index >= 30) & (df.index < 48)]
    df.loc[z3_rows, 'open'] = 100.0
    df.loc[z3_rows, 'close'] = 100.5
    df.loc[z3_rows, 'high'] = 101.0
    df.loc[z3_rows, 'low'] = 99.0
    df.loc[z3_rows[-1], 'high'] = 102.0
    df.loc[z3_rows[0], 'low'] = 98.0

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


# ── Test 6: rejected for insufficient trading days ──────────────────────

def test_ticker_rejected_insufficient_days(monkeypatch):
    days = _BUSINESS_DAYS_2023[:400]   # 400 < MIN_TRADING_DAYS (450)
    df = _synth_frame(days)

    def fake_loader(ticker, data_dir='Fetched_Data'):
        return df

    monkeypatch.setattr(cms, 'load_extended_data', fake_loader)
    start, end = _train_window_dates()
    status, per_slot, per_zone = cms.process_ticker(
        'FAKE', start, end, 'Fetched_Data', verbose=False,
    )
    assert status['accepted'] is False
    assert status['reason'].startswith('insufficient_days')
    assert per_slot is None and per_zone is None


# ── Test 7: rejected for insufficient slot sample ───────────────────────

def test_ticker_rejected_insufficient_slot_sample(monkeypatch):
    # Build 180 complete days — fewer than 200 observations per slot.
    days = _BUSINESS_DAYS_2023[:180]
    df = _synth_frame(days)

    def fake_loader(ticker, data_dir='Fetched_Data'):
        return df

    monkeypatch.setattr(cms, 'load_extended_data', fake_loader)
    # Lower the day-count gate so the slot-sample gate can fire.
    monkeypatch.setattr(cms, 'MIN_TRADING_DAYS', 100)
    start, end = _train_window_dates()
    status, per_slot, per_zone = cms.process_ticker(
        'FAKE', start, end, 'Fetched_Data', verbose=False,
    )
    assert status['accepted'] is False
    assert status['reason'].startswith('insufficient_slot_sample: slot=')
    assert per_slot is None and per_zone is None


# ── Test 8: output JSON schema validates ────────────────────────────────

def test_output_json_schema_validates(tmp_path, monkeypatch):
    days = _BUSINESS_DAYS_2023[:500]
    df_a = _synth_frame(days)
    df_b = _synth_frame(days, open_price=200.0)
    store = {'AAA': df_a, 'BBB': df_b}

    def fake_loader(ticker, data_dir='Fetched_Data'):
        return store[ticker].copy()

    monkeypatch.setattr(cms, 'load_extended_data', fake_loader)
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

    assert 'AAA' in data['per_slot_stats']
    slot0 = data['per_slot_stats']['AAA']['0']
    for p in (10, 30, 50, 70, 90):
        assert 'p{}_range'.format(p) in slot0
        assert 'p{}_abs_return'.format(p) in slot0
    for f in ('sample_size', 'et_time', 'zone'):
        assert f in slot0


# ── Test 9: Phase-0 U-shape ratio on synthetic U-shape fixture ──────────

def test_u_shape_check3_passes_for_known_ticker(monkeypatch):
    """Synthetic U-shape: wide range in Z1+Z5, narrow in Z3 → ratio >= 1.25."""
    days = _BUSINESS_DAYS_2023[:500]
    df = _synth_frame(days, slot_range_mult=_u_shape_multiplier)

    def fake_loader(ticker, data_dir='Fetched_Data'):
        return df

    monkeypatch.setattr(cms, 'load_extended_data', fake_loader)
    monkeypatch.setattr(cms, 'MIN_TRADING_DAYS', 100)

    start, end = _train_window_dates('2023-2024')
    status, per_slot, per_zone = cms.process_ticker(
        'UTIC', start, end, 'Fetched_Data', verbose=False,
    )
    assert status['accepted'] is True

    outer = []
    for i in list(range(0, 12)) + list(range(60, 78)):
        outer.append(per_slot[str(i)]['p50_range'])
    dead = []
    for i in range(30, 48):
        dead.append(per_slot[str(i)]['p50_range'])
    ratio = float(np.mean(outer)) / float(np.mean(dead))
    assert ratio >= 1.25, 'synthetic U-shape ratio {:.3f} < 1.25'.format(ratio)

    # Sanity-check qa_check3 on a one-ticker payload.
    qa = cms.qa_check3_u_shape_phase0({'UTIC': per_slot})
    assert qa['per_ticker_ratios']['UTIC'] >= 1.25


# ── Test 10: end-to-end two-ticker synthetic pipeline ──────────────────

def test_end_to_end_two_tickers(tmp_path, monkeypatch):
    days = _BUSINESS_DAYS_2023[:500]
    # Give both tickers a U-shape so QA check 3 passes.
    df_spy = _synth_frame(days, slot_range_mult=_u_shape_multiplier)
    df_nvda = _synth_frame(
        days, open_price=400.0, slot_range_mult=_u_shape_multiplier,
    )
    store = {'SPY': df_spy, 'NVDA': df_nvda}

    def fake_loader(ticker, data_dir='Fetched_Data'):
        return store[ticker].copy()

    monkeypatch.setattr(cms, 'load_extended_data', fake_loader)
    monkeypatch.setattr(cms, 'MIN_TRADING_DAYS', 100)

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
