"""
Batch Processor Module.

Processes multiple tickers in batch with earnings filtering
and TradingView serialization.
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Union

import pandas as pd

from .bsu_detector import BSUDetector
from .config import Config, DEFAULT_CONFIG
from .data_aggregator import DataAggregator
from .earnings_filter import EarningsCheckResult, EarningsFilter
from .market_data_fetcher import MarketDataFetcher
from .tradingview_serializer import TradingViewSerializer

logger = logging.getLogger(__name__)


@dataclass
class TickerResult:
    """Result of processing a single ticker."""

    ticker: str
    success: bool
    levels_df: Optional[pd.DataFrame] = None
    tradingview_string: Optional[str] = None
    tradingview_file: Optional[Path] = None
    earnings_check: Optional[EarningsCheckResult] = None
    error: Optional[str] = None
    stats: Optional[dict] = None

    @property
    def level_count(self) -> int:
        """Number of detected levels."""
        if self.levels_df is not None:
            return len(self.levels_df)
        return 0


class BatchProcessor:
    """
    Process multiple tickers in batch.

    Combines data fetching, BSU detection, earnings filtering,
    and TradingView serialization into a single workflow.
    """

    def __init__(
        self,
        config: Config = DEFAULT_CONFIG,
        github_token: Optional[str] = None,
        use_cache: bool = False,
        check_earnings: bool = True,
    ):
        """
        Initialize BatchProcessor.

        Args:
            config: Configuration parameters.
            github_token: GitHub token for data fetching.
            use_cache: Whether to use cached data.
            check_earnings: Whether to check earnings calendar.
        """
        self.config = config
        self.use_cache = use_cache
        self.check_earnings = check_earnings

        # Initialize components
        try:
            self.fetcher = MarketDataFetcher(github_token=github_token)
        except ValueError:
            logger.warning("No GitHub token provided, auto-fetch disabled")
            self.fetcher = None

        self.aggregator = DataAggregator(config)
        self.detector = BSUDetector(config)
        self.earnings_filter = EarningsFilter() if check_earnings else None

    def process_ticker(
        self,
        ticker: str,
        df_5min: Optional[pd.DataFrame] = None,
        output_dir: Union[str, Path] = "output",
        save_tradingview: bool = True,
    ) -> TickerResult:
        """
        Process a single ticker.

        Args:
            ticker: Stock symbol.
            df_5min: Optional pre-loaded 5-minute data.
            output_dir: Output directory for files.
            save_tradingview: Whether to save TradingView file.

        Returns:
            TickerResult with processing outcome.
        """
        ticker = ticker.upper()
        output_dir = Path(output_dir)

        logger.info(f"Processing {ticker}...")

        # Check earnings if enabled
        earnings_check = None
        if self.earnings_filter:
            earnings_check = self.earnings_filter.check_earnings_conflict(ticker)
            if earnings_check.blocked:
                logger.warning(f"{ticker}: {earnings_check.reason}")
                return TickerResult(
                    ticker=ticker,
                    success=False,
                    earnings_check=earnings_check,
                    error=f"Blocked due to earnings: {earnings_check.reason}",
                )

        # Fetch data if not provided
        if df_5min is None:
            if self.fetcher is None:
                return TickerResult(
                    ticker=ticker,
                    success=False,
                    error="No data provided and auto-fetch unavailable (no GitHub token)",
                )

            try:
                df_5min = self.fetcher.fetch_ticker(ticker, use_cache=self.use_cache)
            except Exception as e:
                logger.error(f"Error fetching {ticker}: {e}")
                return TickerResult(
                    ticker=ticker,
                    success=False,
                    error=f"Fetch error: {str(e)}",
                )

        # Aggregate to daily
        try:
            df_daily = self.aggregator.aggregate_to_daily(df_5min)
            df_daily = self.aggregator.calculate_modified_atr(df_daily)
        except Exception as e:
            logger.error(f"Error aggregating {ticker}: {e}")
            return TickerResult(
                ticker=ticker,
                success=False,
                error=f"Aggregation error: {str(e)}",
            )

        # Detect levels
        try:
            levels = self.detector.detect_levels(df_daily, ticker)
            levels_df = self.detector.levels_to_dataframe(levels)
        except Exception as e:
            logger.error(f"Error detecting levels for {ticker}: {e}")
            return TickerResult(
                ticker=ticker,
                success=False,
                error=f"Detection error: {str(e)}",
            )

        # Serialize for TradingView
        tv_string = TradingViewSerializer.serialize_levels(levels_df, ticker)
        tv_file = None

        if save_tradingview and tv_string:
            tv_file = TradingViewSerializer.save_to_file(
                tv_string, ticker, output_dir
            )

        # Calculate statistics
        stats = {
            "total_levels": len(levels_df),
            "resistance": len(levels_df[levels_df["Type"] == "R"]),
            "support": len(levels_df[levels_df["Type"] == "S"]),
            "mirror": len(levels_df[levels_df["Type"] == "M"]),
            "avg_score": levels_df["Score"].mean() if not levels_df.empty else 0,
            "max_score": levels_df["Score"].max() if not levels_df.empty else 0,
        }

        logger.info(
            f"{ticker}: {stats['total_levels']} levels detected "
            f"(R:{stats['resistance']}, S:{stats['support']}, M:{stats['mirror']})"
        )

        return TickerResult(
            ticker=ticker,
            success=True,
            levels_df=levels_df,
            tradingview_string=tv_string,
            tradingview_file=tv_file,
            earnings_check=earnings_check,
            stats=stats,
        )

    def process_all_tickers(
        self,
        tickers: Optional[List[str]] = None,
        output_dir: Union[str, Path] = "output",
        save_csv: bool = True,
        save_tradingview: bool = True,
    ) -> Dict[str, TickerResult]:
        """
        Process all available tickers.

        Args:
            tickers: Optional list of tickers. Uses all available if not specified.
            output_dir: Output directory for files.
            save_csv: Whether to save combined CSV.
            save_tradingview: Whether to save TradingView files.

        Returns:
            Dictionary mapping ticker to TickerResult.
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Get tickers
        if tickers is None:
            if self.fetcher:
                tickers = self.fetcher.get_available_tickers()
            else:
                logger.error("No tickers provided and fetcher unavailable")
                return {}

        results: Dict[str, TickerResult] = {}
        all_levels = []

        print("\n" + "=" * 60)
        print("BATCH PROCESSING")
        print("=" * 60)
        print(f"Tickers: {', '.join(tickers)}")
        print(f"Output: {output_dir}")
        print("=" * 60)

        # Print earnings report if checking
        if self.earnings_filter:
            report = self.earnings_filter.format_earnings_report(tickers)
            print("\n" + report + "\n")

        # Process each ticker
        for ticker in tickers:
            print(f"\n{'─' * 60}")
            print(f"Processing {ticker}...")
            print("─" * 60)

            result = self.process_ticker(
                ticker,
                output_dir=output_dir,
                save_tradingview=save_tradingview,
            )
            results[ticker] = result

            if result.success:
                print(f"  Levels: {result.level_count}")
                if result.stats:
                    print(f"  R: {result.stats['resistance']} | "
                          f"S: {result.stats['support']} | "
                          f"M: {result.stats['mirror']}")
                    print(f"  Avg Score: {result.stats['avg_score']:.1f}")

                if result.tradingview_file:
                    print(f"  TradingView: {result.tradingview_file}")

                if result.levels_df is not None:
                    all_levels.append(result.levels_df)
            else:
                print(f"  FAILED: {result.error}")

        # Save combined CSV
        if save_csv and all_levels:
            combined_df = pd.concat(all_levels, ignore_index=True)
            csv_path = output_dir / "levels_all_tickers.csv"
            combined_df.to_csv(csv_path, index=False)
            print(f"\nCombined CSV: {csv_path}")

        # Print summary
        self._print_summary(results)

        return results

    def _print_summary(self, results: Dict[str, TickerResult]) -> None:
        """Print processing summary."""
        print("\n" + "=" * 60)
        print("PROCESSING SUMMARY")
        print("=" * 60)

        successful = [t for t, r in results.items() if r.success]
        failed = [t for t, r in results.items() if not r.success]
        blocked = [t for t, r in results.items()
                   if r.earnings_check and r.earnings_check.blocked]

        print(f"Successful: {len(successful)} - {', '.join(successful) if successful else 'None'}")
        print(f"Failed: {len(failed)} - {', '.join(failed) if failed else 'None'}")
        print(f"Blocked (Earnings): {len(blocked)} - {', '.join(blocked) if blocked else 'None'}")

        total_levels = sum(r.level_count for r in results.values())
        print(f"\nTotal Levels Detected: {total_levels}")

        print("=" * 60)

    def get_combined_levels(
        self,
        results: Dict[str, TickerResult],
    ) -> pd.DataFrame:
        """
        Combine all levels from results into single DataFrame.

        Args:
            results: Dictionary of processing results.

        Returns:
            Combined DataFrame with all levels.
        """
        dfs = []
        for result in results.values():
            if result.success and result.levels_df is not None:
                dfs.append(result.levels_df)

        if not dfs:
            return pd.DataFrame()

        return pd.concat(dfs, ignore_index=True)


def run_batch_processing(
    tickers: Optional[List[str]] = None,
    output_dir: str = "output",
    check_earnings: bool = True,
) -> Dict[str, TickerResult]:
    """
    Convenience function to run batch processing.

    Args:
        tickers: Optional list of tickers.
        output_dir: Output directory.
        check_earnings: Whether to check earnings.

    Returns:
        Dictionary of results.
    """
    processor = BatchProcessor(check_earnings=check_earnings)
    return processor.process_all_tickers(tickers, output_dir)
