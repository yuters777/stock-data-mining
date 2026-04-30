"""ONE-OFF GENERATOR — runs once to produce static NYSE calendar CSV.
NOT a runtime dependency. After CSV is checked in, this file may be deleted
or kept for regeneration. The runtime nyse_calendar.py reads CSV only.
"""
import pandas as pd
import pandas_market_calendars as mcal

nyse = mcal.get_calendar("XNYS")
schedule = nyse.schedule(start_date="2021-01-01", end_date="2026-12-31")
schedule = schedule.reset_index()
schedule.columns = ["trading_date_et", "market_open_utc", "market_close_utc"]
schedule["trading_date_et"] = pd.to_datetime(schedule["trading_date_et"]).dt.strftime("%Y-%m-%d")

schedule["close_et"] = pd.to_datetime(schedule["market_close_utc"]).dt.tz_convert("America/New_York").dt.strftime("%H:%M")
schedule["is_early_close"] = (schedule["close_et"] != "16:00").astype(int)
schedule["session_mode"] = schedule["is_early_close"].map({0: "standard", 1: "early_close"})
schedule["early_close_et"] = schedule["close_et"].where(schedule["is_early_close"] == 1, None)

out = schedule[["trading_date_et", "session_mode", "early_close_et"]]
out.to_csv("Fetched_Data/nyse_calendar_2021_2026.csv", index=False)
print(f"Wrote {len(out)} rows to Fetched_Data/nyse_calendar_2021_2026.csv")
