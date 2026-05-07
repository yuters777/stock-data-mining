"""Shared constants for M4 baseline probe audit scripts.

DR-frozen M4 parameters (spec: RP-002, module4.py:29-39 @ SHA 9a6f7e1).
Do NOT modify these — they are the values being audited, not inputs.
"""
from __future__ import annotations

import os
from pathlib import Path

# Project root
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent

# Snapshot and output paths
SNAPSHOTS_DIR = PROJECT_ROOT / "data" / "snapshots"
AUDITS_OUTPUT_DIR = PROJECT_ROOT / "audits" / "output"
FETCHED_DATA_DIR = PROJECT_ROOT / "Fetched_Data"

# M4 frozen constants (claimed values from spec DD-002 / RP-002)
CLAIMED_STREAK_LENGTH = 3
CLAIMED_VIX_GATE = 25.0
CLAIMED_RSI_THRESHOLD = 35
CLAIMED_D6_VIX_ROC_THRESHOLD = 30.0
CLAIMED_MAX_BARS_HOLD = 10

# Canonical 27-ticker M4 universe (DD-005)
CANONICAL_UNIVERSE = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA",
    "TSLA", "AMD", "SMCI", "PLTR", "AVGO", "ARM", "TSM",
    "MU", "INTC", "COST",
    "COIN", "MSTR", "MARA",
    "C", "GS", "V", "BA", "JPM",
    "BABA", "JD", "BIDU",
]

# Canonical baseline values (DD-002 / RP-001)
CANONICAL_BASELINE_N = 47
CANONICAL_BASELINE_PF = 21.38
CANONICAL_BASELINE_WR = 0.94
CANONICAL_BASELINE_MEAN_RETURN = 7.52
CANONICAL_BASELINE_SHARPE = 1.38
CANONICAL_BASELINE_LOCKED_DATE = "2026-04-16"

# Snapshot file patterns
MODULE4_SNAPSHOT_NAME = "module4_py_9a6f7e1.txt"
TICKERS_SNAPSHOT_NAME = "tickers_py_9a6f7e1.txt"

# Local canonical trade ledger (best available — HARN-1.1 applies: N!=47)
LOCAL_TRADES_CSV = PROJECT_ROOT / "backtest_results" / "m4_5yr_trades.csv"
LOCAL_TRADES_ENRICHED_CSV = PROJECT_ROOT / "scripts" / "m4_5yr_trades_enriched.csv"

# S44 streak sensitivity results (source of N=57)
S44_STREAK_RESULTS_MD = PROJECT_ROOT / "results" / "S44_Module4_Streak_Sensitivity.md"
S44_BASELINE_RESULTS_MD = PROJECT_ROOT / "results" / "S44_Module4_Baseline_Results.md"

# VIX sweep results (source of N=4-8)
VIX_SWEEP_RESULTS_JSON = PROJECT_ROOT / "scripts" / "m4_vix_threshold_sweep_results.json"

# Max bars sweep results (counterfactual N=264 context)
MAX_BARS_SWEEP_RESULTS_JSON = PROJECT_ROOT / "scripts" / "m4_max_bars_sweep_results.json"

# GO/NO-GO thresholds
LOYO_MIN_PF = 5.0
LOTO_MIN_PF = 5.0
LOVO_MIN_PF = 5.0
COST_STRESS_MIN_PF_AT_15BPS = 10.0
SURVIVORSHIP_MAX_POSTHOC_TICKERS = 3
