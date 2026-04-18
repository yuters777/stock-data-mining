#!/usr/bin/env python3
"""BT-0: Post-process existing trade CSVs to add entry_ts_ny, entry_slot_id, entry_zone.

Pure read-existing-CSVs → compute-derived-columns → write-enriched-CSVs.
Does NOT modify backtest scripts or re-run any backtest.

Usage:
    python scripts/add_entry_timestamps.py [--output-dir results/bt0_enriched] [--verbose]
"""
from __future__ import annotations  # Py 3.9 compat on Windows

import json
import os
import sys
from pathlib import Path
from typing import Optional

import pandas as pd

# Single source of truth: import bar start times from shared utility
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backtest_utils_extended import _BAR_TIME_ET  # noqa: E402

_BAR_DURATION_HOURS = 4  # all 4H extended bars are exactly 4h

# RTH bar 2 (13:30–15:55) ends at market close, not at bar_start + 4h.
# bar_start + 4h - 5min = 17:25 is wrong; override to actual close.
_BAR_CLOSE_OVERRIDE_ET: dict[str, tuple[int, int]] = {
    '2': (15, 55),
}

# Zone boundaries from Zone_Guide §2.5: M5 slot → zone label
_ZONE_SLOT_RANGES = {
    'Z1': (0, 11),
    'Z2': (12, 29),
    'Z3': (30, 47),
    'Z4': (48, 59),
    'Z5': (60, 77),
}


def slot_to_zone(slot_id: int) -> Optional[str]:
    """Return 'Z1'..'Z5' or None for slot outside RTH (0-77)."""
    for zone, (lo, hi) in _ZONE_SLOT_RANGES.items():
        if lo <= slot_id <= hi:
            return zone
    return None


def et_time_to_slot(hour: int, minute: int) -> Optional[int]:
    """Return M5 slot 0-77 for RTH ET hour:minute, else None."""
    total_min = hour * 60 + minute
    rth_start_min = 9 * 60 + 30   # 09:30
    rth_end_min = 16 * 60          # 16:00 exclusive
    if total_min < rth_start_min or total_min >= rth_end_min:
        return None
    return (total_min - rth_start_min) // 5


def compute_entry_close_time(bar_label: str) -> tuple[int, int]:
    """Return (hour, minute) of bar close in ET.

    Uses _BAR_TIME_ET (start times) plus 4h duration for extended bars.
    RTH bar '2' is overridden to 15:55 because it ends at market close,
    not at bar_start + 4h.
    """
    if bar_label in _BAR_CLOSE_OVERRIDE_ET:
        return _BAR_CLOSE_OVERRIDE_ET[bar_label]
    start_h, start_m = _BAR_TIME_ET[bar_label]
    total_min = start_h * 60 + start_m + _BAR_DURATION_HOURS * 60 - 5  # last M5 bar
    return total_min // 60, total_min % 60


def enrich_csv(
    input_path: Path,
    output_path: Path,
    has_entry_bar: bool,
    default_bar_label_for_missing: Optional[str] = None,
) -> dict:
    """Read CSV, add entry_ts_ny / entry_slot_id / entry_zone columns, write output.

    Args:
        has_entry_bar: True if CSV has 'entry_bar' column.
        default_bar_label_for_missing: Used when has_entry_bar is False
            (e.g. '2' for M7 daily close → 15:55 ET).

    Returns:
        dict with row counts, skipped counts, zone distribution.
    """
    df = pd.read_csv(input_path, encoding='utf-8')
    initial_rows = len(df)

    if has_entry_bar:
        labels = df['entry_bar'].astype(str)
    else:
        if default_bar_label_for_missing is None:
            raise ValueError(f'{input_path}: no entry_bar column and no default label provided')
        labels = pd.Series([default_bar_label_for_missing] * len(df), dtype=str)

    entry_ts_list: list[str] = []
    slot_list: list[int] = []
    zone_list: list[str] = []
    out_of_rth_count = 0

    for idx, (date_str, label) in enumerate(zip(df['entry_date'], labels)):
        if label not in _BAR_TIME_ET and label not in _BAR_CLOSE_OVERRIDE_ET:
            raise ValueError(f'Row {idx}: unknown bar_label {label!r}')

        hour, minute = compute_entry_close_time(label)
        ts_naive_et = pd.Timestamp(str(date_str)) + pd.Timedelta(hours=hour, minutes=minute)
        entry_ts_list.append(ts_naive_et.isoformat())

        slot = et_time_to_slot(hour, minute)
        slot_list.append(slot if slot is not None else -1)
        zone = slot_to_zone(slot) if slot is not None else 'OUT_OF_RTH'
        zone_list.append(zone)

        if zone == 'OUT_OF_RTH':
            out_of_rth_count += 1

    df['entry_ts_ny'] = entry_ts_list
    df['entry_slot_id'] = slot_list
    df['entry_zone'] = zone_list

    df.to_csv(output_path, index=False, encoding='utf-8')

    return {
        'input': str(input_path),
        'output': str(output_path),
        'rows_read': initial_rows,
        'rows_written': len(df),
        'out_of_rth_count': out_of_rth_count,
        'zone_distribution': df['entry_zone'].value_counts().to_dict(),
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description='Add entry timestamps to trade CSVs (BT-0)')
    parser.add_argument('--output-dir', default='results/bt0_enriched',
                        help='Directory for *_with_ts.csv outputs')
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    TARGETS = [
        # (input_path, has_entry_bar, default_label)
        ('results/extended_validation/m4_extended_trades.csv', True, None),
        ('results/extended_validation/m4_rth_trades.csv', True, None),
        ('results/extended_validation/m6_extended_trades.csv', True, None),
        ('results/extended_validation/m6_rth_trades.csv', True, None),
        # M7 daily-close trades have no entry_bar; use bar '2' (15:55 ET) by §2.2 convention
        ('results/m7_rs_falsification/trade_sim_results.csv', False, '2'),
    ]

    summary: dict = {'processed': [], 'total_rows': 0}
    for input_rel, has_bar, default_label in TARGETS:
        in_path = Path(input_rel)
        if not in_path.exists():
            print(f'[SKIP] {input_rel} not found')
            continue
        out_path = output_dir / (in_path.stem + '_with_ts.csv')
        result = enrich_csv(in_path, out_path, has_bar, default_label)
        summary['processed'].append(result)
        summary['total_rows'] += result['rows_written']
        if args.verbose:
            print(f"[OK] {input_rel} → {out_path}: {result['rows_written']} rows, "
                  f"zones {result['zone_distribution']}")

    with open(output_dir / 'bt0_summary.json', 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2, default=str)

    print(f"\n✓ Processed {len(summary['processed'])} files, {summary['total_rows']} total rows")
    print(f"Summary written to {output_dir / 'bt0_summary.json'}")


if __name__ == '__main__':
    main()
