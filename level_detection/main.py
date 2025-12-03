#!/usr/bin/env python3
"""
Main script for BSU Level Detection.

Phase 1: Gerchik False Breakout Strategy
- Loads and aggregates 5-min data to daily
- Detects BSU levels using fractal analysis
- Applies scoring system
- Generates output CSV and visualizations
"""

import argparse
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from level_detection.config import Config
from level_detection.data_aggregator import DataAggregator
from level_detection.bsu_detector import BSUDetector
from level_detection.visualizer import LevelVisualizer


def main(
    data_path: Path | None = None,
    output_path: Path | None = None,
    ticker: str | None = None,
    visualize: bool = True,
    save_chart: bool = True,
) -> None:
    """
    Run the BSU level detection pipeline.

    Args:
        data_path: Path to input CSV file
        output_path: Path to output CSV file
        ticker: Optional ticker to filter (default: all tickers)
        visualize: Whether to generate visualizations
        save_chart: Whether to save chart to file
    """
    print("=" * 60)
    print("BSU Level Detection - Phase 1")
    print("Gerchik False Breakout Strategy")
    print("=" * 60)

    # Initialize components
    config = Config()
    aggregator = DataAggregator(config)
    detector = BSUDetector(config)
    visualizer = LevelVisualizer(config)

    # Set paths
    base_path = Path(__file__).parent.parent
    data_path = data_path or base_path / config.DATA_PATH
    output_path = output_path or base_path / config.OUTPUT_PATH

    print(f"\n[1/4] Loading data from: {data_path}")

    # Load and process data
    try:
        df_daily = aggregator.process_data(data_path)
        print(f"      Loaded {len(df_daily)} daily bars")
        print(f"      Tickers: {', '.join(df_daily['Ticker'].unique())}")
        print(f"      Date range: {df_daily['Date'].min()} to {df_daily['Date'].max()}")
    except FileNotFoundError:
        print(f"ERROR: Data file not found: {data_path}")
        sys.exit(1)

    # Filter by ticker if specified
    if ticker:
        df_daily = df_daily[df_daily["Ticker"] == ticker].reset_index(drop=True)
        if df_daily.empty:
            print(f"ERROR: No data found for ticker: {ticker}")
            sys.exit(1)
        print(f"      Filtered to ticker: {ticker} ({len(df_daily)} bars)")

    print(f"\n[2/4] Detecting BSU levels...")

    # Detect levels
    levels, levels_df = detector.detect_all_tickers(df_daily)

    print(f"      Detected {len(levels)} levels")

    if levels:
        # Show breakdown by type
        type_counts = levels_df["Type"].value_counts()
        for level_type, count in type_counts.items():
            type_name = {"R": "Resistance", "S": "Support", "M": "Mirror"}[level_type]
            print(f"      - {type_name}: {count}")

        # Show score statistics
        print(f"      Score range: {levels_df['Score'].min()} - {levels_df['Score'].max()}")
        print(f"      Average score: {levels_df['Score'].mean():.1f}")

    print(f"\n[3/4] Saving results to: {output_path}")

    # Save results
    output_path.parent.mkdir(parents=True, exist_ok=True)
    detector.save_levels(levels_df, output_path)
    print(f"      Saved {len(levels_df)} levels")

    # Generate visualizations
    if visualize and levels:
        print(f"\n[4/4] Generating visualizations...")

        chart_dir = output_path.parent / "charts"
        chart_dir.mkdir(parents=True, exist_ok=True)

        # If single ticker, generate chart
        tickers_to_plot = [ticker] if ticker else df_daily["Ticker"].unique()

        for t in tickers_to_plot:
            ticker_df = df_daily[df_daily["Ticker"] == t].reset_index(drop=True)
            ticker_levels = [l for l in levels if l.ticker == t]

            if not ticker_levels:
                print(f"      No levels for {t}, skipping chart")
                continue

            chart_path = chart_dir / f"{t}_levels.png" if save_chart else None

            try:
                fig = visualizer.plot_candlestick(
                    ticker_df,
                    ticker_levels,
                    ticker=t,
                    save_path=chart_path,
                )

                if save_chart:
                    print(f"      Saved chart: {chart_path}")
                else:
                    import matplotlib.pyplot as plt
                    plt.show()

            except Exception as e:
                print(f"      Error generating chart for {t}: {e}")

        # Generate statistics chart
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

    # Print summary
    if levels:
        print("\nTop 10 Levels by Score:")
        print("-" * 60)
        top_levels = levels_df.nlargest(10, "Score")
        for _, row in top_levels.iterrows():
            type_name = {"R": "Resistance", "S": "Support", "M": "Mirror"}[row["Type"]]
            print(f"  {row['Ticker']:5} | {row['Date'].strftime('%Y-%m-%d')} | "
                  f"${row['Price']:8.2f} | {type_name:10} | Score: {row['Score']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="BSU Level Detection for Gerchik False Breakout Strategy"
    )
    parser.add_argument(
        "--data", "-d",
        type=Path,
        help="Path to input CSV file",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        help="Path to output CSV file",
    )
    parser.add_argument(
        "--ticker", "-t",
        type=str,
        help="Filter by ticker symbol (e.g., AAPL)",
    )
    parser.add_argument(
        "--no-visualize",
        action="store_true",
        help="Skip visualization generation",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Show charts instead of saving",
    )

    args = parser.parse_args()

    main(
        data_path=args.data,
        output_path=args.output,
        ticker=args.ticker,
        visualize=not args.no_visualize,
        save_chart=not args.show,
    )
