#!/usr/bin/env python3
"""
Main script for BSU Level Detection.

Phase 1: Gerchik False Breakout Strategy
- Loads and aggregates 5-min data to daily
- Detects BSU levels using fractal analysis
- Applies scoring system
- Generates output CSV, TradingView format, and visualizations

Supports:
- Auto-fetch from MarketPatterns-AI repository
- Earnings calendar filtering
- Batch processing multiple tickers
- TradingView serialization output
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from level_detection.config import Config
from level_detection.data_aggregator import DataAggregator
from level_detection.bsu_detector import BSUDetector
from level_detection.visualizer import LevelVisualizer
from level_detection.tradingview_serializer import TradingViewSerializer
from level_detection.earnings_filter import EarningsFilter

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def run_single_ticker(
    ticker: str,
    data_path: Optional[Path] = None,
    output_dir: Path = Path("level_detection/output"),
    auto_fetch: bool = False,
    use_cache: bool = False,
    format_output: str = "all",
    check_earnings: bool = True,
    visualize: bool = True,
    save_chart: bool = True,
) -> int:
    """
    Run BSU detection for a single ticker.

    Args:
        ticker: Stock symbol.
        data_path: Path to local CSV file (optional if auto_fetch).
        output_dir: Output directory.
        auto_fetch: Whether to fetch from MarketPatterns-AI.
        use_cache: Use cached data if available.
        format_output: Output format ('csv', 'tradingview', 'all').
        check_earnings: Check earnings calendar.
        visualize: Generate chart visualizations.
        save_chart: Save charts to file.

    Returns:
        Exit code (0 for success, 1 for error).
    """
    print("=" * 60)
    print("BSU Level Detection - Phase 1")
    print("Gerchik False Breakout Strategy")
    print("=" * 60)
    print(f"Ticker: {ticker}")
    print(f"Mode: {'Auto-Fetch' if auto_fetch else 'Local File'}")
    print("=" * 60)

    config = Config()
    aggregator = DataAggregator(config)
    detector = BSUDetector(config)
    visualizer = LevelVisualizer(config)

    # Check earnings if enabled
    if check_earnings:
        print("\n[1/5] Checking earnings calendar...")
        try:
            earnings_filter = EarningsFilter()
            result = earnings_filter.check_earnings_conflict(ticker)

            if result.blocked:
                print(f"      BLOCKED: {result.reason}")
                print("      Trading not recommended. Use --no-earnings to override.")
                return 1
            else:
                status = "WARNING" if result.days_until and result.days_until <= 1 else "OK"
                print(f"      [{status}] {result.reason}")
        except ImportError:
            print("      [SKIP] yfinance not installed")
        except Exception as e:
            print(f"      [SKIP] Error checking earnings: {e}")
    else:
        print("\n[1/5] Earnings check: DISABLED")

    # Load data
    print("\n[2/5] Loading data...")
    df_5min = None

    if auto_fetch:
        try:
            from level_detection.market_data_fetcher import MarketDataFetcher

            fetcher = MarketDataFetcher()
            df_5min = fetcher.fetch_ticker(ticker, use_cache=use_cache)
            print(f"      Fetched {len(df_5min):,} rows from MarketPatterns-AI")
        except ValueError as e:
            print(f"      ERROR: {e}")
            print("      Set GITHUB_TOKEN environment variable or use --no-fetch")
            return 1
        except Exception as e:
            print(f"      ERROR fetching data: {e}")
            return 1
    else:
        # Load from local file
        base_path = Path(__file__).parent.parent
        data_path = data_path or base_path / config.DATA_PATH

        try:
            df_5min = aggregator.load_data(data_path)
            df_5min = df_5min[df_5min["Ticker"] == ticker]
            if df_5min.empty:
                print(f"      ERROR: No data for ticker {ticker} in {data_path}")
                return 1
            print(f"      Loaded {len(df_5min):,} rows from {data_path}")
        except FileNotFoundError:
            print(f"      ERROR: File not found: {data_path}")
            print("      Use --auto-fetch to download from MarketPatterns-AI")
            return 1

    # Aggregate to daily
    print("\n[3/5] Aggregating to daily timeframe...")
    df_daily = aggregator.aggregate_to_daily(df_5min)
    df_daily = aggregator.calculate_modified_atr(df_daily)
    print(f"      Created {len(df_daily)} daily bars")
    print(f"      Date range: {df_daily['Date'].min().date()} to {df_daily['Date'].max().date()}")

    # Detect levels
    print("\n[4/5] Detecting BSU levels...")
    levels = detector.detect_levels(df_daily, ticker)
    levels_df = detector.levels_to_dataframe(levels)

    print(f"      Detected {len(levels)} levels")
    if levels:
        type_counts = levels_df["Type"].value_counts()
        for level_type, count in type_counts.items():
            type_name = {"R": "Resistance", "S": "Support", "M": "Mirror"}[level_type]
            print(f"      - {type_name}: {count}")
        print(f"      Score range: {levels_df['Score'].min()} - {levels_df['Score'].max()}")

    # Save outputs
    print("\n[5/5] Saving outputs...")
    output_dir.mkdir(parents=True, exist_ok=True)

    # CSV output
    if format_output in ("csv", "all"):
        csv_path = output_dir / "levels_detected.csv"
        detector.save_levels(levels_df, csv_path)
        print(f"      CSV: {csv_path}")

    # TradingView output
    if format_output in ("tradingview", "all") and levels:
        tv_string = TradingViewSerializer.serialize_levels(levels_df, ticker)
        tv_path = TradingViewSerializer.save_to_file(tv_string, ticker, output_dir)
        print(f"      TradingView: {tv_path}")

        # Print TradingView string for easy copy
        print("\n" + "-" * 60)
        print("TradingView Level String (copy this):")
        print("-" * 60)
        print(tv_string[:500] + ("..." if len(tv_string) > 500 else ""))
        print("-" * 60)

    # Visualizations
    if visualize and levels:
        chart_dir = output_dir / "charts"
        chart_dir.mkdir(parents=True, exist_ok=True)

        chart_path = chart_dir / f"{ticker}_levels.png" if save_chart else None

        try:
            fig = visualizer.plot_candlestick(
                df_daily,
                levels,
                ticker=ticker,
                save_path=chart_path,
            )

            if save_chart:
                print(f"      Chart: {chart_path}")
            else:
                import matplotlib.pyplot as plt
                plt.show()
        except Exception as e:
            print(f"      Chart error: {e}")

    # Summary
    print("\n" + "=" * 60)
    print("BSU Level Detection Complete!")
    print("=" * 60)

    if levels:
        print("\nTop 5 Levels by Score:")
        print("-" * 60)
        top_levels = levels_df.nlargest(5, "Score")
        for _, row in top_levels.iterrows():
            type_name = {"R": "Resistance", "S": "Support", "M": "Mirror"}[row["Type"]]
            print(f"  ${row['Price']:8.2f} | {type_name:10} | Score: {row['Score']}")

    return 0


def run_batch(
    output_dir: Path = Path("level_detection/output"),
    check_earnings: bool = True,
    use_cache: bool = False,
) -> int:
    """
    Run batch processing for all available tickers.

    Args:
        output_dir: Output directory.
        check_earnings: Check earnings calendar.
        use_cache: Use cached data.

    Returns:
        Exit code.
    """
    try:
        from level_detection.batch_processor import BatchProcessor

        processor = BatchProcessor(
            use_cache=use_cache,
            check_earnings=check_earnings,
        )

        results = processor.process_all_tickers(output_dir=output_dir)

        # Count successes
        successes = sum(1 for r in results.values() if r.success)
        return 0 if successes > 0 else 1

    except ValueError as e:
        print(f"ERROR: {e}")
        print("Set GITHUB_TOKEN environment variable for batch processing")
        return 1
    except Exception as e:
        print(f"ERROR: {e}")
        return 1


def run_legacy(
    data_path: Optional[Path] = None,
    output_path: Optional[Path] = None,
    ticker: Optional[str] = None,
    visualize: bool = True,
    save_chart: bool = True,
) -> int:
    """
    Legacy mode: Run from local file without new features.

    Maintains backward compatibility with original behavior.
    """
    print("=" * 60)
    print("BSU Level Detection - Phase 1 (Legacy Mode)")
    print("Gerchik False Breakout Strategy")
    print("=" * 60)

    config = Config()
    aggregator = DataAggregator(config)
    detector = BSUDetector(config)
    visualizer = LevelVisualizer(config)

    base_path = Path(__file__).parent.parent
    data_path = data_path or base_path / config.DATA_PATH
    output_path = output_path or base_path / config.OUTPUT_PATH

    print(f"\n[1/4] Loading data from: {data_path}")

    try:
        df_daily = aggregator.process_data(data_path)
        print(f"      Loaded {len(df_daily)} daily bars")
        print(f"      Tickers: {', '.join(df_daily['Ticker'].unique())}")
        print(f"      Date range: {df_daily['Date'].min()} to {df_daily['Date'].max()}")
    except FileNotFoundError:
        print(f"ERROR: Data file not found: {data_path}")
        return 1

    if ticker:
        df_daily = df_daily[df_daily["Ticker"] == ticker].reset_index(drop=True)
        if df_daily.empty:
            print(f"ERROR: No data found for ticker: {ticker}")
            return 1
        print(f"      Filtered to ticker: {ticker} ({len(df_daily)} bars)")

    print(f"\n[2/4] Detecting BSU levels...")
    levels, levels_df = detector.detect_all_tickers(df_daily)
    print(f"      Detected {len(levels)} levels")

    if levels:
        type_counts = levels_df["Type"].value_counts()
        for level_type, count in type_counts.items():
            type_name = {"R": "Resistance", "S": "Support", "M": "Mirror"}[level_type]
            print(f"      - {type_name}: {count}")
        print(f"      Score range: {levels_df['Score'].min()} - {levels_df['Score'].max()}")
        print(f"      Average score: {levels_df['Score'].mean():.1f}")

    print(f"\n[3/4] Saving results to: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    detector.save_levels(levels_df, output_path)
    print(f"      Saved {len(levels_df)} levels")

    if visualize and levels:
        print(f"\n[4/4] Generating visualizations...")
        chart_dir = output_path.parent / "charts"
        chart_dir.mkdir(parents=True, exist_ok=True)

        tickers_to_plot = [ticker] if ticker else df_daily["Ticker"].unique()

        for t in tickers_to_plot:
            ticker_df = df_daily[df_daily["Ticker"] == t].reset_index(drop=True)
            ticker_levels = [l for l in levels if l.ticker == t]

            if not ticker_levels:
                continue

            chart_path = chart_dir / f"{t}_levels.png" if save_chart else None

            try:
                visualizer.plot_candlestick(
                    ticker_df,
                    ticker_levels,
                    ticker=t,
                    save_path=chart_path,
                )
                if save_chart:
                    print(f"      Saved chart: {chart_path}")
            except Exception as e:
                print(f"      Error generating chart for {t}: {e}")

        if len(tickers_to_plot) > 1 or not ticker:
            try:
                stats_path = chart_dir / "level_statistics.png" if save_chart else None
                visualizer.plot_level_statistics(levels, save_path=stats_path)
                if save_chart:
                    print(f"      Saved statistics: {stats_path}")
            except Exception as e:
                print(f"      Error generating statistics: {e}")
    else:
        print(f"\n[4/4] Skipping visualizations")

    print("\n" + "=" * 60)
    print("BSU Level Detection Complete!")
    print("=" * 60)

    if levels:
        print("\nTop 10 Levels by Score:")
        print("-" * 60)
        top_levels = levels_df.nlargest(10, "Score")
        for _, row in top_levels.iterrows():
            type_name = {"R": "Resistance", "S": "Support", "M": "Mirror"}[row["Type"]]
            print(f"  {row['Ticker']:5} | {row['Date'].strftime('%Y-%m-%d')} | "
                  f"${row['Price']:8.2f} | {type_name:10} | Score: {row['Score']}")

    return 0


def main():
    """Main entry point with CLI argument parsing."""
    parser = argparse.ArgumentParser(
        description="BSU Level Detection for Gerchik False Breakout Strategy",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single ticker with auto-fetch from MarketPatterns-AI
  python main.py --ticker TSLA --auto-fetch

  # Batch processing all tickers
  python main.py --batch

  # Use local cache (no GitHub fetch)
  python main.py --ticker AAPL --auto-fetch --use-cache

  # Custom output format for TradingView only
  python main.py --ticker NVDA --auto-fetch --format tradingview

  # Legacy mode with local file
  python main.py --data path/to/data.csv --ticker AAPL

Environment Variables:
  GITHUB_TOKEN  - Required for --auto-fetch and --batch modes
        """
    )

    # Mode selection
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--batch", "-b",
        action="store_true",
        help="Process all available tickers in batch",
    )
    mode_group.add_argument(
        "--ticker", "-t",
        type=str,
        help="Process single ticker (e.g., AAPL, TSLA)",
    )

    # Data source options
    parser.add_argument(
        "--auto-fetch", "-a",
        action="store_true",
        help="Fetch data from MarketPatterns-AI repository",
    )
    parser.add_argument(
        "--no-fetch",
        action="store_true",
        help="Use local data only (no GitHub fetch)",
    )
    parser.add_argument(
        "--use-cache",
        action="store_true",
        help="Use cached data if available",
    )
    parser.add_argument(
        "--data", "-d",
        type=Path,
        help="Path to local input CSV file",
    )

    # Output options
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=Path("level_detection/output"),
        help="Output directory (default: level_detection/output)",
    )
    parser.add_argument(
        "--format", "-f",
        choices=["csv", "tradingview", "all"],
        default="all",
        help="Output format (default: all)",
    )

    # Feature toggles
    parser.add_argument(
        "--no-earnings",
        action="store_true",
        help="Skip earnings calendar check",
    )
    parser.add_argument(
        "--no-visualize",
        action="store_true",
        help="Skip chart visualization",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Show charts instead of saving",
    )

    args = parser.parse_args()

    # Batch mode
    if args.batch:
        return run_batch(
            output_dir=args.output,
            check_earnings=not args.no_earnings,
            use_cache=args.use_cache,
        )

    # Single ticker mode
    if args.ticker:
        return run_single_ticker(
            ticker=args.ticker.upper(),
            data_path=args.data,
            output_dir=args.output,
            auto_fetch=args.auto_fetch and not args.no_fetch,
            use_cache=args.use_cache,
            format_output=args.format,
            check_earnings=not args.no_earnings,
            visualize=not args.no_visualize,
            save_chart=not args.show,
        )

    # Legacy mode (no ticker specified, no batch)
    return run_legacy(
        data_path=args.data,
        output_path=args.output / "levels_detected.csv" if args.output else None,
        ticker=None,
        visualize=not args.no_visualize,
        save_chart=not args.show,
    )


if __name__ == "__main__":
    sys.exit(main())
