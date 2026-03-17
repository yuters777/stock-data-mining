#!/usr/bin/env python3
"""
Targeted script to fetch Mar 1-9 2026 crypto data for BTC and ETH.
Tries Binance API, then Binance Vision daily, then CryptoCompare.
Merges with existing CSVs, deduplicates, validates.
"""

import os
import sys
import io
import time
import zipfile
import logging
from datetime import datetime, timedelta, timezone

import requests
import pandas as pd
import pytz

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

EASTERN = pytz.timezone("America/New_York")
CSV_COLUMNS = ["Datetime", "Open", "High", "Low", "Close", "Volume", "Ticker"]
BINANCE_SYMBOL_MAP = {"ETH": "ETHUSDT", "BTC": "BTCUSDT"}

# Date range: Mar 1 00:00 UTC to Mar 10 00:00 UTC
START_DT = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)
END_DT = datetime(2026, 3, 10, 0, 0, 0, tzinfo=timezone.utc)

# Cap at current time
NOW_UTC = datetime.now(timezone.utc)
if END_DT > NOW_UTC:
    END_DT = NOW_UTC
    logger.info(f"Capped END_DT to {END_DT}")


def utc_to_eastern(dt):
    if dt.tzinfo is None:
        dt = pytz.utc.localize(dt)
    return dt.astimezone(EASTERN).replace(tzinfo=None)


# =========================================================================
# Source 1: Binance API
# =========================================================================
def fetch_binance(ticker):
    """Fetch 5m klines from Binance public API."""
    symbol = BINANCE_SYMBOL_MAP[ticker]
    url = "https://api.binance.com/api/v3/klines"
    start_ms = int(START_DT.timestamp() * 1000)
    end_ms = int(END_DT.timestamp() * 1000)

    all_records = []
    current_start = start_ms

    while current_start < end_ms:
        chunk_end = min(current_start + 1000 * 5 * 60 * 1000, end_ms)
        params = {"symbol": symbol, "interval": "5m",
                  "startTime": current_start, "endTime": chunk_end, "limit": 1000}

        klines = None
        for attempt in range(3):
            try:
                resp = requests.get(url, params=params, timeout=30)
                if resp.status_code == 429:
                    logger.warning(f"Binance rate limit for {ticker}, waiting 10s")
                    time.sleep(10)
                    continue
                if resp.status_code == 451:
                    logger.warning(f"Binance geo-blocked for {ticker}")
                    return pd.DataFrame()
                resp.raise_for_status()
                klines = resp.json()
                break
            except Exception as e:
                logger.error(f"Binance {ticker} attempt {attempt+1}: {e}")
                time.sleep(2 * (attempt + 1))

        if not klines:
            current_start = chunk_end + 1
            continue

        for k in klines:
            open_time_utc = datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc)
            et_time = utc_to_eastern(open_time_utc)
            all_records.append({
                "Datetime": et_time.strftime("%Y-%m-%d %H:%M:%S"),
                "Open": float(k[1]),
                "High": float(k[2]),
                "Low": float(k[3]),
                "Close": float(k[4]),
                "Volume": int(float(k[5])),
                "Ticker": ticker,
            })

        last_ms = klines[-1][0]
        current_start = last_ms + 5 * 60 * 1000

    if not all_records:
        return pd.DataFrame()

    df = pd.DataFrame(all_records)
    df["Datetime"] = pd.to_datetime(df["Datetime"])
    df = df.sort_values("Datetime").reset_index(drop=True)
    logger.info(f"Binance {ticker}: {len(df)} bars, {df['Datetime'].min()} to {df['Datetime'].max()}")
    return df


# =========================================================================
# Source 2: Binance Vision daily klines
# =========================================================================
def fetch_vision(ticker):
    """Download daily kline ZIPs from data.binance.vision."""
    symbol = BINANCE_SYMBOL_MAP[ticker]
    base = "https://data.binance.vision/data/spot/daily/klines"
    all_records = []

    current = START_DT
    while current < END_DT:
        date_str = current.strftime("%Y-%m-%d")
        url = f"{base}/{symbol}/5m/{symbol}-5m-{date_str}.zip"

        for attempt in range(2):
            try:
                resp = requests.get(url, timeout=60)
                if resp.status_code == 404:
                    logger.warning(f"Vision {ticker} {date_str}: not found")
                    break
                resp.raise_for_status()

                with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                    csv_name = zf.namelist()[0]
                    with zf.open(csv_name) as f:
                        df = pd.read_csv(f, header=None, names=[
                            "open_time", "Open", "High", "Low", "Close", "Volume",
                            "close_time", "quote_volume", "count",
                            "taker_buy_volume", "taker_buy_quote_volume", "ignore"
                        ])

                # Auto-detect timestamp unit
                sample_ts = df["open_time"].iloc[0]
                if sample_ts > 1e15:
                    ts_unit = "us"
                elif sample_ts > 1e12:
                    ts_unit = "ms"
                else:
                    ts_unit = "s"

                df["Datetime_utc"] = pd.to_datetime(df["open_time"], unit=ts_unit, utc=True)
                df["Datetime_et"] = df["Datetime_utc"].dt.tz_convert("America/New_York")

                for _, row in df.iterrows():
                    all_records.append({
                        "Datetime": row["Datetime_et"].strftime("%Y-%m-%d %H:%M:%S"),
                        "Open": float(row["Open"]),
                        "High": float(row["High"]),
                        "Low": float(row["Low"]),
                        "Close": float(row["Close"]),
                        "Volume": int(float(row["Volume"])),
                        "Ticker": ticker,
                    })
                logger.info(f"Vision {ticker} {date_str}: {len(df)} bars")
                break
            except Exception as e:
                logger.error(f"Vision {ticker} {date_str} attempt {attempt+1}: {e}")
                time.sleep(2)

        current += timedelta(days=1)

    if not all_records:
        return pd.DataFrame()

    result = pd.DataFrame(all_records)
    result["Datetime"] = pd.to_datetime(result["Datetime"])
    result = result.sort_values("Datetime").reset_index(drop=True)
    logger.info(f"Vision {ticker}: {len(result)} total bars")
    return result


# =========================================================================
# Source 3: CryptoCompare
# =========================================================================
def fetch_cryptocompare(ticker):
    """Fetch 1-min data from CryptoCompare, resample to 5-min."""
    base = "https://min-api.cryptocompare.com/data/v2/histominute"
    start_ts = int(START_DT.timestamp())
    end_ts = int(END_DT.timestamp())
    current_to = end_ts
    all_records = []

    while current_to > start_ts:
        params = {"fsym": ticker, "tsym": "USDT", "limit": 2000, "toTs": current_to}
        bars = []
        for attempt in range(3):
            try:
                resp = requests.get(base, params=params, timeout=30)
                resp.raise_for_status()
                data = resp.json()
                bars = data.get("Data", {}).get("Data", [])
                break
            except Exception as e:
                logger.error(f"CryptoCompare {ticker} attempt {attempt+1}: {e}")
                time.sleep(2 * (attempt + 1))

        if not bars:
            break

        for bar in bars:
            ts = bar.get("time", 0)
            if ts < start_ts or ts > end_ts:
                continue
            if bar.get("close", 0) == 0:
                continue
            open_time_utc = datetime.fromtimestamp(ts, tz=timezone.utc)
            et_time = utc_to_eastern(open_time_utc)
            all_records.append({
                "Datetime": et_time,
                "Open": float(bar["open"]),
                "High": float(bar["high"]),
                "Low": float(bar["low"]),
                "Close": float(bar["close"]),
                "Volume": int(float(bar.get("volumeto", 0))),
                "Ticker": ticker,
            })

        earliest_ts = min(b.get("time", current_to) for b in bars)
        if earliest_ts >= current_to:
            break
        current_to = earliest_ts - 1

    if not all_records:
        return pd.DataFrame()

    df_1m = pd.DataFrame(all_records)
    df_1m["Datetime"] = pd.to_datetime(df_1m["Datetime"])
    df_1m = df_1m.set_index("Datetime").sort_index()

    df_5m = df_1m.resample("5min").agg({
        "Open": "first", "High": "max", "Low": "min",
        "Close": "last", "Volume": "sum", "Ticker": "first",
    }).dropna(subset=["Open"]).reset_index()

    logger.info(f"CryptoCompare {ticker}: {len(df_5m)} 5m bars")
    return df_5m


# =========================================================================
# Main
# =========================================================================
def main():
    tickers = ["BTC", "ETH"]
    data_dirs = ["Fetched_Data", "MarketPatterns_AI/Fetched_Data"]
    sources = [
        ("Binance API", fetch_binance),
        ("Binance Vision", fetch_vision),
        ("CryptoCompare", fetch_cryptocompare),
    ]

    for ticker in tickers:
        logger.info(f"\n{'='*60}\nFetching {ticker} for Mar 1-9, 2026\n{'='*60}")

        new_df = pd.DataFrame()
        for source_name, fetch_fn in sources:
            logger.info(f"Trying {source_name} for {ticker}...")
            try:
                new_df = fetch_fn(ticker)
            except Exception as e:
                logger.error(f"{source_name} failed for {ticker}: {e}")
                new_df = pd.DataFrame()

            if not new_df.empty:
                logger.info(f"SUCCESS: {source_name} returned {len(new_df)} bars for {ticker}")
                break
            else:
                logger.warning(f"{source_name} returned no data for {ticker}, trying next...")

        if new_df.empty:
            logger.error(f"FATAL: All sources failed for {ticker}")
            sys.exit(1)

        new_df["Datetime"] = pd.to_datetime(new_df["Datetime"])

        # Filter to only Mar 1-9 range (Eastern time)
        mar1_et = pd.Timestamp("2026-02-28 19:00:00")  # Mar 1 00:00 UTC in ET
        mar10_et = pd.Timestamp("2026-03-09 20:00:00")  # Mar 10 00:00 UTC in ET (after DST)
        # Actually, be generous - keep all March data up to Mar 10
        new_df = new_df[(new_df["Datetime"] >= "2026-03-01") & (new_df["Datetime"] < "2026-03-10")]
        logger.info(f"{ticker} filtered to Mar 1-9 ET: {len(new_df)} rows")

        if new_df.empty:
            logger.error(f"No Mar 1-9 data after filtering for {ticker}")
            sys.exit(1)

        for data_dir in data_dirs:
            csv_path = os.path.join(data_dir, f"{ticker}_crypto_data.csv")
            if not os.path.exists(csv_path):
                logger.warning(f"{csv_path} not found, skipping")
                continue

            existing = pd.read_csv(csv_path)
            existing["Datetime"] = pd.to_datetime(existing["Datetime"])
            rows_before = len(existing)
            logger.info(f"Existing {csv_path}: {rows_before} rows, "
                         f"{existing['Datetime'].min()} to {existing['Datetime'].max()}")

            combined = pd.concat([existing, new_df], ignore_index=True)
            combined = combined.drop_duplicates(subset=["Datetime"], keep="last")
            combined = combined.sort_values("Datetime").reset_index(drop=True)

            new_rows = len(combined) - rows_before
            logger.info(f"{ticker}: {rows_before} + {new_rows} new = {len(combined)} total")

            # Validate
            nulls = combined[CSV_COLUMNS].isnull().sum()
            null_cols = {k: v for k, v in nulls.items() if v > 0}
            dupes = combined["Datetime"].duplicated().sum()

            logger.info(f"  Nulls: {null_cols if null_cols else 'None'}")
            logger.info(f"  Duplicates: {dupes}")
            logger.info(f"  Range: {combined['Datetime'].min()} to {combined['Datetime'].max()}")

            if null_cols:
                logger.error(f"NULL values in {csv_path}!")
                sys.exit(1)
            if dupes > 0:
                logger.error(f"Duplicate timestamps in {csv_path}!")
                sys.exit(1)

            # Check Mar 1-9 coverage
            mar_data = combined[(combined["Datetime"] >= "2026-03-01") &
                               (combined["Datetime"] < "2026-03-10")]
            logger.info(f"  Mar 1-9 rows: {len(mar_data)}")
            if len(mar_data) < 100:
                logger.error(f"Too few Mar 1-9 rows for {ticker}: {len(mar_data)}")
                sys.exit(1)

            # Save
            df_out = combined[CSV_COLUMNS].copy()
            df_out["Datetime"] = df_out["Datetime"].dt.strftime("%Y-%m-%d %H:%M:%S")
            df_out["Volume"] = df_out["Volume"].astype(int)
            df_out.to_csv(csv_path, index=False)
            logger.info(f"Saved {csv_path}: {len(df_out)} rows")

    logger.info("\nAll done! Both BTC and ETH updated with Mar 1-9 data.")


if __name__ == "__main__":
    main()
