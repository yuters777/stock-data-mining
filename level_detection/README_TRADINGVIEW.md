# TradingView Integration Guide

This guide explains how to use the BSU Level Detection system with TradingView.

## Quick Start

### 1. Set Up Environment

```bash
# Set GitHub token (one time) - required for auto-fetch
export GITHUB_TOKEN="ghp_your_token_here"

# Install dependencies
pip install -r level_detection/requirements.txt
```

### 2. Generate Levels (Daily Routine)

```bash
# Generate levels for a single ticker with auto-fetch
python level_detection/main.py --ticker TSLA --auto-fetch

# Process all 9 tickers in batch
python level_detection/main.py --batch

# Use local cache (faster, no GitHub fetch)
python level_detection/main.py --ticker AAPL --auto-fetch --use-cache

# TradingView format only (no charts)
python level_detection/main.py --ticker NVDA --auto-fetch --format tradingview --no-visualize
```

### 3. Copy to TradingView

1. Open the output file: `level_detection/output/levels_TSLA_tradingview.txt`
2. Copy the entire string
3. Open TradingView → TSLA chart (5-min or desired timeframe)
4. Add indicator: "Gerchik False Breakout v3.4" (Pine Script - Phase 2)
5. Settings → Paste Level Data → Paste the string
6. Click OK

### 4. View Levels on Chart

The indicator will display:
- 🔵 **Blue dashed lines**: Normal levels
- 🟣 **Purple solid lines**: Mirror levels (highest priority)
- 🟠 **Orange dashed lines**: Paranormal bars (Model #4 candidates)

Only levels within ±5% of current price are displayed (Active Zone rendering).

---

## TradingView String Format

The serialized output follows this format:

```
Price:Type:Meta,Price:Type:Meta,...
```

**Example:**
```
540.62:R:P,488.85:R:N,525.00:S:M,510.50:R:N
```

### Type Encoding
| Code | Meaning |
|------|---------|
| `R` | Resistance |
| `S` | Support |

### Meta Encoding
| Code | Meaning | Priority |
|------|---------|----------|
| `M` | Mirror level (acts as both S/R) | Highest |
| `P` | Paranormal bar / Model #4 candidate | High |
| `N` | Normal level | Standard |

---

## Data Source

### MarketPatterns-AI Repository

Data is automatically fetched from the private `yuters777/MarketPatterns-AI` repository.

**Update Schedule:**
- 5:00 AM IST
- 4:00 PM IST
- 11:30 PM IST

**Available Tickers (9):**
- AAPL, MSFT, NVDA, TSLA, META
- COIN, BABA, GOOGL, AMZN

**Data Format:**
- 5-minute OHLCV bars
- Timezone: IST (Israel Standard Time)

### Caching

To avoid repeated API calls:
```bash
python level_detection/main.py --ticker TSLA --auto-fetch --use-cache
```

Cached files are stored in `level_detection/cache/`.

---

## Earnings Filter

The system automatically checks the earnings calendar per v3.4 specification.

**Behavior:**
- **Earnings TODAY**: Trading BLOCKED (exit code 1)
- **Earnings TOMORROW**: Warning issued, trading allowed
- **Earnings 2+ days**: Normal operation

**Override:**
```bash
python level_detection/main.py --ticker TSLA --auto-fetch --no-earnings
```

---

## CLI Reference

```
usage: main.py [-h] [--batch | --ticker TICKER] [--auto-fetch] [--no-fetch]
               [--use-cache] [--data DATA] [--output OUTPUT]
               [--format {csv,tradingview,all}] [--no-earnings]
               [--no-visualize] [--show]

BSU Level Detection for Gerchik False Breakout Strategy

optional arguments:
  -h, --help            show this help message and exit
  --batch, -b           Process all available tickers in batch
  --ticker, -t TICKER   Process single ticker (e.g., AAPL, TSLA)
  --auto-fetch, -a      Fetch data from MarketPatterns-AI repository
  --no-fetch            Use local data only (no GitHub fetch)
  --use-cache           Use cached data if available
  --data, -d DATA       Path to local input CSV file
  --output, -o OUTPUT   Output directory (default: level_detection/output)
  --format, -f          Output format: csv, tradingview, or all (default: all)
  --no-earnings         Skip earnings calendar check
  --no-visualize        Skip chart visualization
  --show                Show charts instead of saving

Environment Variables:
  GITHUB_TOKEN  - Required for --auto-fetch and --batch modes
```

---

## Output Files

After running, you'll find these files:

```
level_detection/output/
├── levels_detected.csv           # All levels in CSV format
├── levels_TSLA_tradingview.txt   # TradingView string for TSLA
├── levels_AAPL_tradingview.txt   # TradingView string for AAPL
├── ...
└── charts/
    ├── TSLA_levels.png           # Candlestick chart with levels
    └── level_statistics.png      # Summary statistics
```

---

## Workflow Example

### Daily Morning Routine

```bash
#!/bin/bash
# daily_levels.sh

export GITHUB_TOKEN="ghp_your_token"

echo "=== Generating BSU Levels ==="
cd /path/to/stock-data-mining

# Process all tickers
python level_detection/main.py --batch --format tradingview

echo "=== Done! Check output/ for TradingView files ==="
```

### Single Ticker Quick Check

```bash
# Quick check for TSLA before market open
python level_detection/main.py -t TSLA -a --no-visualize

# Output:
# ============================================================
# BSU Level Detection - Phase 1
# ============================================================
# [1/5] Checking earnings calendar...
#       [OK] Next earnings in 45 days
# [2/5] Loading data...
#       Fetched 36,828 rows from MarketPatterns-AI
# ...
# TradingView Level String (copy this):
# ------------------------------------------------------------
# 540.62:R:P,488.85:S:M,525.00:R:N,...
# ------------------------------------------------------------
```

---

## Troubleshooting

### "GitHub token required" Error
```bash
export GITHUB_TOKEN="ghp_your_personal_access_token"
```

### "No earnings data available" Warning
This is normal for some tickers. The system will proceed with trading allowed.

### Slow Fetching
Use `--use-cache` after the first fetch:
```bash
python level_detection/main.py -t TSLA -a --use-cache
```

### yfinance ImportError
```bash
pip install yfinance
```

---

## Phase 2 Preview

Coming in Phase 2:
- Pine Script indicator for TradingView
- False breakout pattern detection
- Entry/exit signal generation
- Risk management integration

---

## Support

For issues or questions:
- GitHub Issues: https://github.com/yuters777/stock-data-mining/issues
- Specification: `docs/specs/Gerchik_FalseBreakout_TZ_v3.4_YOUTUBE.docx`
