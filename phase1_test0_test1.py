"""Phase 1: Test 0 (Data Inventory) + Test 1 (Stress Event Identification)"""
import pandas as pd
import numpy as np
import os, json

DATA_DIR = "Fetched_Data"
OUT_DIR = "backtest_output"
os.makedirs(OUT_DIR, exist_ok=True)

TICKERS_31 = [
    "AAPL", "AMD", "AMZN", "ARM", "AVGO", "BA", "BABA", "BIDU", "BTC",
    "C", "COIN", "COST", "ETH", "GOOGL", "GS", "INTC", "JPM", "MARA",
    "META", "MSFT", "MSTR", "MU", "NVDA", "PLTR", "SMCI", "SPY", "TSLA",
    "TSM", "V", "VIXY",
]
TRADE_UNIVERSE = [t for t in TICKERS_31 if t not in ("SPY", "VIXY")]

# ── Test 0: Load & filter ──────────────────────────────────────────────
print("=" * 60)
print("TEST 0: DATA INVENTORY & QUALITY CHECK")
print("=" * 60)

raw_data = {}
for tk in TICKERS_31:
    fp = os.path.join(DATA_DIR, f"{tk}_data.csv")
    df = pd.read_csv(fp, parse_dates=["Datetime"])
    raw_data[tk] = df

# Report raw row counts and date ranges
print(f"\n{'Ticker':<8} {'Rows':>8} {'Start':<12} {'End':<12}")
print("-" * 44)
for tk in TICKERS_31:
    df = raw_data[tk]
    print(f"{tk:<8} {len(df):>8} {str(df['Datetime'].min().date()):<12} {str(df['Datetime'].max().date()):<12}")

# Filter to regular session: 09:30-15:55 ET.
# RAW DATA STRUCTURE: Alpha Vantage CSVs contain TWO overlapping blocks:
#   ET block  (04:00-10:55): original US/Eastern timestamps
#   IST block (11:00-23:55): same bars shifted +7h by fetch_SP500_Data.py
# The IST regular session (16:30-22:55 IST = 09:30-15:55 ET) has the
# CORRECT high-volume bars. We select those and convert back to ET.
#
# BUG FIXED 2026-03-24: Previous filter used 09:30-15:55 directly on raw
# timestamps, which captured ET bars for 09:30-10:55 (correct) but IST
# pre-market bars for 11:00-15:55 (wrong). See I8/I9 audit for details.
filtered = {}
for tk in TICKERS_31:
    df = raw_data[tk].copy()
    hm = df["Datetime"].dt.hour * 60 + df["Datetime"].dt.minute
    # Select IST regular session block: 16:30-22:55 IST = 09:30-15:55 ET
    mask = (hm >= 16 * 60 + 30) & (hm <= 22 * 60 + 55)
    filt = df[mask].copy()
    # Convert IST timestamps to ET (subtract 7 hours)
    filt["Datetime"] = filt["Datetime"] - pd.Timedelta(hours=7)
    filtered[tk] = filt

print(f"\n{'Ticker':<8} {'RegSess':>8} {'TradingDays':>12}")
print("-" * 32)
for tk in TICKERS_31:
    df = filtered[tk]
    ndays = df["Datetime"].dt.date.nunique()
    print(f"{tk:<8} {len(df):>8} {ndays:>12}")

# Load VIX daily
vix = pd.read_csv(os.path.join(DATA_DIR, "VIXCLS_FRED_real.csv"))
vix.columns = ["Date", "VIX_Close"]
vix["Date"] = pd.to_datetime(vix["Date"])
vix["VIX_Close"] = pd.to_numeric(vix["VIX_Close"], errors="coerce")
vix = vix.dropna(subset=["VIX_Close"]).sort_values("Date").reset_index(drop=True)
print(f"\nVIX daily: {len(vix)} rows, {vix['Date'].min().date()} to {vix['Date'].max().date()}")

# Compute daily returns (close-to-close using first and last regular session bar)
daily_prices = {}
for tk in TICKERS_31:
    df = filtered[tk].copy()
    df["date"] = df["Datetime"].dt.date
    # Open = first bar close, Close = last bar close (per spec)
    day_ohlc = df.groupby("date").agg(
        Open=("Close", "first"),
        Close=("Close", "last"),
        High=("High", "max"),
        Low=("Low", "min"),
        Volume=("Volume", "sum")
    ).reset_index()
    day_ohlc["date"] = pd.to_datetime(day_ohlc["date"])
    daily_prices[tk] = day_ohlc

# Build daily returns matrix
all_dates = sorted(set().union(*(set(daily_prices[tk]["date"]) for tk in TICKERS_31)))
ret_tickers = TRADE_UNIVERSE + ["SPY"]
returns_dict = {}
for tk in ret_tickers:
    dp = daily_prices[tk].set_index("date")["Close"]
    returns_dict[tk] = dp.pct_change()

daily_returns = pd.DataFrame(returns_dict, index=pd.DatetimeIndex(all_dates)).sort_index()
daily_returns = daily_returns.dropna(how="all")
print(f"\nDaily returns matrix: {daily_returns.shape[0]} days × {daily_returns.shape[1]} tickers")
print(f"Date range: {daily_returns.index[0].date()} to {daily_returns.index[-1].date()}")

# Save intermediate data
daily_returns.to_csv(os.path.join(OUT_DIR, "daily_returns.csv"))

# Save daily prices for later phases
for tk in TICKERS_31:
    daily_prices[tk].to_csv(os.path.join(OUT_DIR, f"{tk}_daily.csv"), index=False)

# Save filtered M5 data for later phases
for tk in TICKERS_31:
    filtered[tk].to_csv(os.path.join(OUT_DIR, f"{tk}_m5_regsess.csv"), index=False)

# ── Test 1: Stress Event Identification ─────────────────────────────────
print("\n" + "=" * 60)
print("TEST 1: STRESS EVENT IDENTIFICATION")
print("=" * 60)

# VIX levels
vix["VIX_Chg_Pct"] = vix["VIX_Close"].pct_change() * 100

# Median ticker return per day (trade universe only)
trade_returns = daily_returns[TRADE_UNIVERSE].copy()
median_ret = trade_returns.median(axis=1)
median_ret.name = "MedianTickerReturn"

# Build event calendar
event_cal = vix[["Date", "VIX_Close", "VIX_Chg_Pct"]].copy()
event_cal = event_cal.merge(
    median_ret.reset_index().rename(columns={"index": "Date", "MedianTickerReturn": "MedianTickerReturn"}),
    on="Date", how="outer"
).sort_values("Date").reset_index(drop=True)

# Stress levels
event_cal["LevelA"] = event_cal["VIX_Close"] > 25
event_cal["LevelB"] = event_cal["VIX_Chg_Pct"] > 10
event_cal["LevelC"] = event_cal["VIX_Chg_Pct"] > 15
event_cal["LevelD"] = event_cal["MedianTickerReturn"] < -0.01
event_cal["LevelE"] = event_cal["MedianTickerReturn"] < -0.015
event_cal["LevelF"] = event_cal["MedianTickerReturn"] < -0.02

# Crush within 3 days: VIX drops >5%
event_cal["CrushNext3D"] = False
for i in range(len(event_cal) - 3):
    if pd.notna(event_cal.loc[i, "VIX_Close"]):
        future = event_cal.loc[i+1:i+3, "VIX_Close"].dropna()
        if len(future) > 0:
            min_future = future.min()
            if (event_cal.loc[i, "VIX_Close"] - min_future) / event_cal.loc[i, "VIX_Close"] > 0.05:
                event_cal.loc[i, "CrushNext3D"] = True

# Summary
print("\nStress event counts:")
for lvl, label in [("LevelA","VIX>25"), ("LevelB","VIX chg>10%"), ("LevelC","VIX chg>15%"),
                    ("LevelD","Median ret<-1%"), ("LevelE","Median ret<-1.5%"), ("LevelF","Median ret<-2%")]:
    n = event_cal[lvl].sum()
    print(f"  {label:.<30} {n:>4} days")

# Primary threshold
stress_days_D = event_cal[event_cal["LevelD"]]["Date"].dropna().tolist()
n_stress = len(stress_days_D)
print(f"\nPrimary threshold (Level D): {n_stress} stress days")
if n_stress < 15:
    print("WARNING: N < 15, relaxing to -0.75%")
    event_cal["LevelD_relaxed"] = event_cal["MedianTickerReturn"] < -0.0075
    stress_days_D = event_cal[event_cal["LevelD_relaxed"]]["Date"].dropna().tolist()
    n_stress = len(stress_days_D)
    print(f"  Relaxed threshold: {n_stress} stress days")

crush_on_stress = event_cal[event_cal["LevelD"] & event_cal["CrushNext3D"]]
print(f"  Spike→crush pairs (Level D + crush within 3d): {len(crush_on_stress)}")

# Save event calendar
event_cal.to_csv(os.path.join(OUT_DIR, "event_calendar.csv"), index=False)

# Save stress days list for subsequent phases
stress_dates = [d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d) for d in stress_days_D]
with open(os.path.join(OUT_DIR, "stress_days.json"), "w") as f:
    json.dump(stress_dates, f)

print(f"\nStress day dates:")
for d in stress_days_D:
    row = event_cal[event_cal["Date"] == d]
    if len(row):
        r = row.iloc[0]
        vx = f"{r['VIX_Close']:.1f}" if pd.notna(r['VIX_Close']) else "N/A"
        mr = f"{r['MedianTickerReturn']*100:.2f}%" if pd.notna(r['MedianTickerReturn']) else "N/A"
        print(f"  {str(d)[:10]}  VIX={vx:>6}  MedianRet={mr:>8}")

# Phase 1 summary JSON for report
summary = {
    "n_tickers": 27, "trade_universe": 25,
    "date_range": f"{daily_returns.index[0].date()} to {daily_returns.index[-1].date()}",
    "n_trading_days": int(daily_returns.shape[0]),
    "n_stress_days_D": n_stress,
    "stress_counts": {
        "LevelA_VIX_gt25": int(event_cal["LevelA"].sum()),
        "LevelB_VIX_chg_gt10": int(event_cal["LevelB"].sum()),
        "LevelC_VIX_chg_gt15": int(event_cal["LevelC"].sum()),
        "LevelD_median_lt_neg1": int(event_cal["LevelD"].sum()),
        "LevelE_median_lt_neg1p5": int(event_cal["LevelE"].sum()),
        "LevelF_median_lt_neg2": int(event_cal["LevelF"].sum()),
    },
    "crush_pairs": int(len(crush_on_stress)),
    "vix_range": f"{vix['Date'].min().date()} to {vix['Date'].max().date()}",
}
with open(os.path.join(OUT_DIR, "phase1_summary.json"), "w") as f:
    json.dump(summary, f, indent=2)

print("\n✓ Phase 1 complete. Outputs in backtest_output/")
