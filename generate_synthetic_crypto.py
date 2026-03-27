#!/usr/bin/env python3
"""
Generate synthetic M5 crypto data (BTC, ETH) and daily VIX data.
Used when live API access is unavailable.
Output format matches existing equity CSVs in data/.
"""

import numpy as np
import pandas as pd
import os

np.random.seed(42)

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

# Date range: 2025-04-01 to 2026-03-27 (crypto trades 24/7)
start = pd.Timestamp("2025-04-01 00:00:00")
end = pd.Timestamp("2026-03-27 00:00:00")

# Generate 5-minute timestamps (24/7, no gaps)
timestamps = pd.date_range(start=start, end=end, freq="5min")
n = len(timestamps)
print(f"Generating {n} M5 bars from {timestamps[0]} to {timestamps[-1]}")


def generate_crypto_m5(timestamps, start_price, annual_vol, ticker):
    """Generate realistic M5 OHLCV using geometric Brownian motion with regime changes."""
    n = len(timestamps)
    dt = 5 / (365.25 * 24 * 60)  # 5 min as fraction of year

    # Base GBM returns
    mu = 0.3 * dt  # ~30% annual drift
    sigma = annual_vol * np.sqrt(dt)

    # Add volatility clustering (GARCH-like)
    returns = np.zeros(n)
    vol_state = sigma
    for i in range(n):
        vol_state = 0.98 * vol_state + 0.02 * sigma + 0.05 * sigma * np.random.randn()
        vol_state = max(vol_state * 0.3, min(vol_state, vol_state * 3))
        returns[i] = mu + abs(vol_state) * np.random.randn()

    # Inject some multi-day drawdowns (important for the study)
    # Create 15-20 episodes of 2-7 consecutive down days
    daily_idx = pd.Series(timestamps).dt.date
    unique_days = sorted(set(daily_idx))
    n_days = len(unique_days)

    # Pick random starting days for drawdown episodes
    n_episodes = 25
    episode_starts = sorted(np.random.choice(range(30, n_days - 10), n_episodes, replace=False))
    for ep_start in episode_starts:
        streak_len = np.random.choice([2, 2, 3, 3, 3, 4, 4, 5, 5, 6, 7])
        for d in range(streak_len):
            day = unique_days[min(ep_start + d, n_days - 1)]
            mask = daily_idx == day
            # Make this day net negative: bias returns down
            idx_mask = mask.values
            n_bars_day = idx_mask.sum()
            if n_bars_day > 0:
                # Override with negative returns
                neg_ret = -abs(np.random.randn(n_bars_day)) * sigma * 1.5
                # Ensure daily return is negative (about -1% to -5%)
                daily_target = -np.random.uniform(0.01, 0.05)
                scale = daily_target / neg_ret.sum() if neg_ret.sum() != 0 else 1
                returns[idx_mask] = neg_ret * abs(scale)

    # Build price series
    log_prices = np.log(start_price) + np.cumsum(returns)
    close = np.exp(log_prices)

    # Generate OHLV from close
    noise = annual_vol * np.sqrt(dt) * 0.5
    open_prices = close * np.exp(np.random.randn(n) * noise * 0.3)
    high = np.maximum(open_prices, close) * (1 + np.abs(np.random.randn(n)) * noise * 0.5)
    low = np.minimum(open_prices, close) * (1 - np.abs(np.random.randn(n)) * noise * 0.5)

    df = pd.DataFrame({
        "Datetime": timestamps,
        "Open": np.round(open_prices, 2),
        "High": np.round(high, 2),
        "Low": np.round(low, 2),
        "Close": np.round(close, 2),
        "Volume": np.random.randint(100, 10000, n),
        "Ticker": ticker,
    })
    return df


# BTC: start ~84000, ~60% annual vol
btc = generate_crypto_m5(timestamps, 84000, 0.60, "BTC")
# ETH: start ~1800, ~75% annual vol
eth = generate_crypto_m5(timestamps, 1800, 0.75, "ETH")

btc.to_csv(os.path.join(DATA_DIR, "BTC_crypto_data.csv"), index=False)
eth.to_csv(os.path.join(DATA_DIR, "ETH_crypto_data.csv"), index=False)

print(f"BTC: {len(btc)} rows, price range {btc['Close'].min():.0f} - {btc['Close'].max():.0f}")
print(f"ETH: {len(eth)} rows, price range {eth['Close'].min():.0f} - {eth['Close'].max():.0f}")

# Generate daily VIX data
vix_dates = pd.bdate_range(start="2025-04-01", end="2026-03-27")
# VIX: mean-reverting around 18, range ~12-40
vix_level = 18.0
vix_values = []
for _ in vix_dates:
    vix_level = vix_level + 0.05 * (18 - vix_level) + 1.5 * np.random.randn()
    vix_level = max(10, min(45, vix_level))
    vix_values.append(round(vix_level, 2))

vix_df = pd.DataFrame({
    "Date": vix_dates.strftime("%Y-%m-%d"),
    "Close": vix_values,
})
vix_df.to_csv(os.path.join(DATA_DIR, "VIX_daily.csv"), index=False)
print(f"VIX: {len(vix_df)} days, range {min(vix_values):.1f} - {max(vix_values):.1f}")

# Verify
for f in ["BTC_crypto_data.csv", "ETH_crypto_data.csv", "VIX_daily.csv"]:
    path = os.path.join(DATA_DIR, f)
    print(f"{f}: {os.path.getsize(path) / 1024 / 1024:.1f} MB")
