#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Enhanced Alpha Vantage Stock Data Fetcher

This script fetches historical stock price data from Alpha Vantage for multiple tickers,
processes the data, and generates a combined dataset. This enhanced version includes:
- Incremental data fetching to reduce API calls
- API response caching for restart resilience
- Exponential backoff for rate limit handling
- Data quality validation with automated fixing
- Command-line interface for flexible usage
- Range-based fetch strategy to minimize API usage
- Advanced parallel processing with dynamic resource optimization
- Real-time progress tracking and ETA estimation
- Adaptive rate limiting based on API response patterns
"""

import os
import json
import logging
import pandas as pd
import numpy as np
import requests
import pytz
import time
import uuid
import argparse
import multiprocessing
import sys
from datetime import datetime
import threading
import concurrent.futures
from collections import defaultdict, deque

# Try to import optional dependencies with proper fallback
try:
    import psutil

    PSUTIL_AVAILABLE = True
except ImportError:
    # Create a minimal psutil substitute for when it's not available
    class PsutilSubstitute:
        class VirtualMemory:
            def __init__(self):
                self.total = 0
                self.available = 0
                self.percent = 0

        @staticmethod
        def virtual_memory():
            return PsutilSubstitute.VirtualMemory()


    psutil = PsutilSubstitute()
    PSUTIL_AVAILABLE = False


class EnhancedAlphaVantageStockFetcher:
    """Enhanced fetcher for stock data from Alpha Vantage API with advanced features."""

    def __init__(self, config_path="config.json"):
        """Initialize the StockDataFetcher with configuration."""
        # Load configuration
        self.config_path = config_path
        self.config = self._load_config()

        # Setup logging
        self._setup_logging()

        # Create data directory if it doesn't exist
        os.makedirs(self.config["data_dir"], exist_ok=True)
        os.makedirs(os.path.join(self.config["data_dir"], "cache"), exist_ok=True)

        # Initialize storage for processed dataframes
        self.dataframes = {}

        # Verify API key exists
        if "alpha_vantage_api_key" not in self.config or not self.config["alpha_vantage_api_key"]:
            self.logger.error("Alpha Vantage API key is missing in config.json")
            raise ValueError("Alpha Vantage API key is required. Add 'alpha_vantage_api_key' to your config.json")

        # Setup proxy if configured
        if "proxy" in self.config:
            self.proxies = {
                "http": self.config["proxy"],
                "https": self.config["proxy"]
            }
        else:
            self.proxies = None

        # Track API calls for rate limiting
        self.last_api_call_time = 0
        self.min_call_interval = self.config.get("min_api_call_interval", 12)  # seconds

        # Manage API call counts
        self.api_calls_today = 0
        self.max_daily_calls = self.config.get("max_daily_calls", 500)
        self.api_calls_last_reset = datetime.now().date()

        # Initialize dynamic rate limiting metrics
        self.api_response_times = deque(maxlen=20)  # Store last 20 response times
        self.api_success_rate = 1.0  # Initialize with 100% success rate
        self.api_error_counts = defaultdict(int)  # Count different types of errors

        # Data structures for parallel processing status tracking
        self.ticker_status = {}  # Track status of each ticker's processing
        self.ticker_processing_times = {}  # Track processing time for each ticker
        self.progress_start_time = None  # Starting time for overall progress tracking

        # Lock for thread-safe operations
        self.lock = threading.RLock()

        # Load API call counter from persistent storage if available
        self._load_api_call_counter()

        self.logger.info(f"EnhancedAlphaVantageStockFetcher initialized with config: {self.config_path}")

    def _load_config(self):
        """Load configuration from JSON file."""
        try:
            with open(self.config_path, 'r') as f:
                config = json.load(f)

            # Ensure required fields exist
            if "last_fetched_times" not in config:
                config["last_fetched_times"] = {}

            if "data_dir" not in config:
                config["data_dir"] = "data"

            if "alpha_vantage_params" not in config:
                config["alpha_vantage_params"] = {
                    "data_type": "intraday",
                    "interval": "5min"
                }

            # Add configuration for parallel processing if not present
            if "parallel_processing" not in config:
                config["parallel_processing"] = {
                    "cpu_multiplier": 2,  # Default to 2x CPU cores for I/O bound tasks
                    "max_memory_percent": 80,  # Don't use more than 80% of system memory
                    "dynamic_throttling": True,  # Enable dynamic throttling based on API responses
                    "min_semaphore_limit": 1,  # Minimum number of concurrent API calls
                    "max_semaphore_limit": 5,  # Maximum number of concurrent API calls
                }

            return config
        except Exception as e:
            print(f"Error loading configuration: {e}")
            raise

    def _save_config(self):
        """Save configuration back to JSON file."""
        try:
            with open(self.config_path, 'w') as f:
                json.dump(self.config, f, indent=2, sort_keys=True, default=str)
        except Exception as e:
            self.logger.error(f"Error saving configuration: {e}")
            raise

    def _setup_logging(self):
        """Set up logging configuration."""
        self.logger = logging.getLogger("EnhancedAlphaVantageStockFetcher")
        self.logger.setLevel(logging.INFO)

        # Check if handlers already exist to avoid duplicates
        if not self.logger.handlers:
            # Create a file handler
            log_file = self.config.get("log_file", "stock_fetcher.log")
            handler = logging.FileHandler(log_file)
            handler.setLevel(logging.INFO)

            # Create a logging format
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)

            # Add the handler to the logger
            self.logger.addHandler(handler)

            # Also add a console handler
            console = logging.StreamHandler()
            console.setLevel(logging.INFO)
            console.setFormatter(formatter)
            self.logger.addHandler(console)

    def _load_api_call_counter(self):
        """Load the API call counter from persistent storage."""
        counter_file = os.path.join(self.config["data_dir"], "api_call_counter.json")
        if os.path.exists(counter_file):
            try:
                with open(counter_file, 'r') as f:
                    counter_data = json.load(f)

                # Parse the stored date
                date_str = counter_data.get("date")
                if date_str:
                    stored_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                    # If the stored date is today, restore the counter
                    if stored_date == datetime.now().date():
                        self.api_calls_today = counter_data.get("count", 0)
                        self.logger.info(f"Restored API call counter: {self.api_calls_today} calls today")
            except Exception as e:
                self.logger.warning(f"Failed to load API call counter: {e}")

    def _save_api_call_counter(self):
        """Save the API call counter to persistent storage."""
        counter_file = os.path.join(self.config["data_dir"], "api_call_counter.json")
        try:
            counter_data = {
                "date": datetime.now().date().strftime("%Y-%m-%d"),
                "count": self.api_calls_today,
                "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            with open(counter_file, 'w') as f:
                json.dump(counter_data, f, indent=2)
        except Exception as e:
            self.logger.warning(f"Failed to save API call counter: {e}")

    def _get_dynamic_call_interval(self):
        """
        Dynamically adjust API call interval based on recent API response patterns.

        Returns:
            float: Recommended interval in seconds between API calls
        """
        base_interval = self.min_call_interval

        # If we don't have enough data yet, use the configured base interval
        if not self.api_response_times:
            return base_interval

        # Calculate average response time
        avg_response_time = sum(self.api_response_times) / len(self.api_response_times)

        # Factor in success rate
        if self.api_success_rate < 0.9:  # Less than 90% success
            # Increase interval for poor success rates
            interval_factor = 2.0 - self.api_success_rate  # Ranges from 1.1 to 2.0
        else:
            interval_factor = 1.0

        # Rate limit errors should significantly increase the interval
        if self.api_error_counts.get(429, 0) > 0:
            interval_factor += min(self.api_error_counts[429] * 0.5, 2.0)  # Up to +2.0 for rate limit errors

        # Calculate final interval
        dynamic_interval = max(
            base_interval,
            avg_response_time * 0.5,  # Half the average response time as minimum
            base_interval * interval_factor
        )

        return dynamic_interval

    def _track_api_call(self):
        """Track API call and manage rate limiting."""
        # Use lock for thread safety
        with self.lock:
            # Check if we're on a new day
            today = datetime.now().date()
            if today != self.api_calls_last_reset:
                self.api_calls_today = 0
                self.api_calls_last_reset = today

            # Increment counter
            self.api_calls_today += 1

            # Save the updated counter
            self._save_api_call_counter()

            # Check if we're approaching the daily limit
            if self.api_calls_today >= self.max_daily_calls * 0.9:  # 90% of limit
                self.logger.warning(f"Approaching daily API call limit: {self.api_calls_today}/{self.max_daily_calls}")

            # Use dynamic interval for smarter rate limiting
            dynamic_interval = self._get_dynamic_call_interval()

            # Enforce minimum delay between API calls
            current_time = time.time()
            elapsed = current_time - self.last_api_call_time

            if elapsed < dynamic_interval and self.last_api_call_time > 0:
                sleep_time = dynamic_interval - elapsed
                self.logger.debug(
                    f"Rate limiting: Waiting {sleep_time:.2f}s between API calls (dynamic interval: {dynamic_interval:.2f}s)")
                time.sleep(sleep_time)

            # Update last call time
            self.last_api_call_time = time.time()

    def _track_api_response(self, success, response_time, error_code=None):
        """
        Track API response metrics to optimize rate limiting.

        Args:
            success (bool): Whether the API call was successful
            response_time (float): Time taken for the API call in seconds
            error_code (int, optional): HTTP error code if applicable
        """
        with self.lock:
            # Track response time
            self.api_response_times.append(response_time)

            # Update success rate with weighted average (most recent calls count more)
            # New success rate = 0.8 * old rate + 0.2 * new result (1 for success, 0 for failure)
            self.api_success_rate = 0.8 * self.api_success_rate + 0.2 * (1.0 if success else 0.0)

            # Track error code if present
            if error_code is not None:
                self.api_error_counts[error_code] += 1

            # Reset error counts periodically
            if len(self.api_response_times) == self.api_response_times.maxlen:
                # Keep rate limit (429) errors longer, but reset other counts
                rate_limit_count = self.api_error_counts.get(429, 0)
                self.api_error_counts.clear()
                if rate_limit_count > 0:
                    self.api_error_counts[429] = max(1, rate_limit_count - 1)  # Gradually reduce, but keep at least 1

    def _get_cache_path(self, ticker, function, interval=None):
        """Get the path to the cache file for a specific API request."""
        # Create a filename that uniquely identifies this request
        if interval:
            filename = f"{ticker}_{function}_{interval}_cache.json"
        else:
            filename = f"{ticker}_{function}_cache.json"

        return os.path.join(self.config["data_dir"], "cache", filename)

    def _get_cached_response(self, ticker, function, interval=None, max_age_hours=24):
        """Get cached response if available and not too old."""
        cache_path = self._get_cache_path(ticker, function, interval)

        if os.path.exists(cache_path):
            # Check file age
            file_time = os.path.getmtime(cache_path)
            age_hours = (time.time() - file_time) / 3600

            if age_hours <= max_age_hours:
                try:
                    with open(cache_path, 'r') as f:
                        self.logger.info(f"Using cached data for {ticker} (age: {age_hours:.1f} hours)")
                        return json.load(f)
                except Exception as e:
                    self.logger.warning(f"Failed to load cached data: {e}")

        return None

    def _save_cached_response(self, ticker, function, data, interval=None):
        """Save API response to cache."""
        cache_path = self._get_cache_path(ticker, function, interval)

        try:
            with open(cache_path, 'w') as f:
                json.dump(data, f)
                self.logger.debug(f"Saved API response to cache: {cache_path}")
        except Exception as e:
            self.logger.warning(f"Failed to save API response to cache: {e}")

    def _fetch_with_backoff(self, base_url, params, max_retries=5, request_id=None):
        """Make API request with exponential backoff for failures and rate limits."""
        if request_id is None:
            request_id = str(uuid.uuid4())[:8]

        retry_count = 0
        # Initialize start_time to avoid potential reference before assignment
        start_time = time.time()

        while retry_count < max_retries:
            try:
                # Track API call for rate limiting
                self._track_api_call()

                # Make the request
                self.logger.debug(f"[{request_id}] Making API request: {base_url} {params}")
                start_time = time.time()  # Reset start_time before each request
                response = requests.get(base_url, params=params, proxies=self.proxies)
                response_time = time.time() - start_time

                # Check for HTTP errors
                response.raise_for_status()

                # Parse the response
                data = response.json()

                # Check for Alpha Vantage specific errors
                if "Error Message" in data:
                    self._track_api_response(False, response_time)
                    raise Exception(data["Error Message"])

                # Check for rate limit messages
                if "Note" in data and "call frequency" in data["Note"]:
                    self._track_api_response(False, response_time, error_code=429)
                    retry_count += 1
                    wait_time = min(60 * (2 ** retry_count), 600)  # Max 10 minutes
                    self.logger.warning(f"[{request_id}] Rate limit reached. Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                    continue

                # If we got here, the request was successful
                self._track_api_response(True, response_time)
                return data

            except requests.exceptions.HTTPError as e:
                response_time = time.time() - start_time
                retry_count += 1

                # Handle rate limiting specifically
                if e.response.status_code == 429:
                    self._track_api_response(False, response_time, error_code=429)
                    wait_time = min(60 * (2 ** retry_count), 600)
                    self.logger.warning(f"[{request_id}] Rate limit (429) reached. Retrying in {wait_time}s...")
                else:
                    self._track_api_response(False, response_time, error_code=e.response.status_code)
                    wait_time = min(30 * (2 ** retry_count), 600)
                    self.logger.error(f"[{request_id}] HTTP error on attempt {retry_count}: {e}")

                if retry_count >= max_retries:
                    self.logger.error(f"[{request_id}] Max retries reached. Giving up.")
                    raise

                self.logger.info(f"[{request_id}] Retrying in {wait_time}s...")
                time.sleep(wait_time)

            except Exception as e:
                # Make sure we always have a valid response_time even if an error occurred before
                # setting start_time or during the request itself
                response_time = time.time() - start_time
                retry_count += 1
                self._track_api_response(False, response_time)
                wait_time = min(30 * (2 ** retry_count), 600)
                self.logger.error(f"[{request_id}] Error on attempt {retry_count}: {e}")

                if retry_count >= max_retries:
                    self.logger.error(f"[{request_id}] Max retries reached. Giving up.")
                    raise

                self.logger.info(f"[{request_id}] Retrying in {wait_time}s...")
                time.sleep(wait_time)

        # Should not reach here, but just in case
        raise Exception(f"Failed to get response after {max_retries} attempts")

    def _fetch_intraday_data(self, ticker, force=False):
        """
        Fetch intraday data from Alpha Vantage API with caching and range-based optimization.

        Args:
            ticker (str): The stock ticker symbol.
            force (bool): Force refresh even if cache is valid, but still optimize for date range.

        Returns:
            pd.DataFrame: DataFrame containing the fetched stock data.
        """
        request_id = str(uuid.uuid4())[:8]
        self.logger.info(f"[{request_id}] Fetching intraday data for {ticker}")

        # Update ticker status for progress tracking
        with self.lock:
            self.ticker_status[ticker] = "started"
            self.ticker_processing_times[ticker] = {"start": time.time()}

        # Alpha Vantage API supports different intervals
        av_interval = self.config.get("alpha_vantage_params", {}).get("interval", "5min")
        function = "TIME_SERIES_INTRADAY"

        # Load existing data to determine what range we need to fetch
        existing_data = None
        file_path = os.path.join(self.config["data_dir"], f"{ticker}_data.csv")
        last_timestamp = None

        if os.path.exists(file_path):
            try:
                existing_data = pd.read_csv(file_path)
                if 'Datetime' in existing_data.columns and not existing_data.empty:
                    # Find the most recent timestamp in our data
                    existing_data['Datetime'] = pd.to_datetime(existing_data['Datetime'])
                    last_timestamp = existing_data['Datetime'].max()
                    self.logger.info(f"[{request_id}] Found existing data for {ticker} up to {last_timestamp}")

                    # Update status
                    with self.lock:
                        self.ticker_status[ticker] = "found_existing"
            except Exception as e:
                self.logger.warning(f"[{request_id}] Error loading existing data: {e}")

        # Determine if we should fetch new data based on market hours
        should_fetch_new_data = force  # Always fetch if force=True

        if not should_fetch_new_data and last_timestamp is not None:
            # Check if we're during market hours (US Eastern Time)
            now = datetime.now()
            eastern = pytz.timezone('America/New_York')
            et_now = eastern.localize(now.replace(tzinfo=None))

            # Check if it's a weekday
            is_weekday = et_now.weekday() < 5  # 0-4 are weekdays (Monday-Friday)

            # Check if it's during extended market hours (4:00 AM - 8:00 PM ET)
            et_hour = et_now.hour
            is_market_hours = 4 <= et_hour < 20

            # Calculate time difference in minutes
            time_diff_minutes = (now - last_timestamp).total_seconds() / 60

            # During market hours on weekdays, use shorter intervals
            if is_weekday and is_market_hours:
                # During market hours, fetch if last data is more than 15 minutes old
                should_fetch_new_data = time_diff_minutes > 15
                self.logger.info(
                    f"Market hours: Last data for {ticker} is {time_diff_minutes:.1f} minutes old - {'fetching new data' if should_fetch_new_data else 'using existing data'}")
            else:
                # Outside market hours, fetch if last data is more than 120 minutes old
                should_fetch_new_data = time_diff_minutes > 120
                self.logger.info(
                    f"Outside market hours: Last data for {ticker} is {time_diff_minutes:.1f} minutes old - {'fetching new data' if should_fetch_new_data else 'using existing data'}")

        # Try to get from cache if not forcing refresh and we're not during market hours
        if not should_fetch_new_data:
            # Calculate an appropriate max cache age based on market hours
            now = datetime.now()
            eastern = pytz.timezone('America/New_York')

            try:
                et_now = eastern.localize(now.replace(tzinfo=None))
                is_weekday = et_now.weekday() < 5
                et_hour = et_now.hour
                is_market_hours = 4 <= et_hour < 20

                if is_weekday and is_market_hours:
                    max_age_hours = 0.25  # 15 minutes during market hours
                else:
                    max_age_hours = 2.0  # 2 hours outside market hours
            except Exception:
                # If timezone handling fails, use a conservative value
                max_age_hours = 0.5  # 30 minutes

            cached_data = self._get_cached_response(ticker, function, av_interval, max_age_hours=max_age_hours)
            if cached_data:
                # Update status
                with self.lock:
                    self.ticker_status[ticker] = "using_cache"

                # Convert cached data to DataFrame
                df = self._convert_intraday_to_dataframe(cached_data, ticker)

                # Update completion status
                with self.lock:
                    self.ticker_status[ticker] = "completed"
                    self.ticker_processing_times[ticker]["end"] = time.time()
                    self.ticker_processing_times[ticker]["duration"] = (
                            self.ticker_processing_times[ticker]["end"] -
                            self.ticker_processing_times[ticker]["start"]
                    )

                return df

        # Determine optimal fetch strategy based on existing data
        output_size = "compact"  # Default to compact (latest ~100 data points)

        # If we have recent data and we're within the API's compact window (100 data points)
        # we can use compact mode efficiently
        fetch_strategy = "recent_only"

        # If we have no data or very old data, we need a full fetch
        if last_timestamp is None or (datetime.now() - last_timestamp).days > 5:
            output_size = "full"
            fetch_strategy = "full_history"
            self.logger.info(f"[{request_id}] No recent data found - fetching full history for {ticker}")

            # Update status
            with self.lock:
                self.ticker_status[ticker] = "fetching_full"
        else:
            # We have recent data - calculate how many intervals we're missing
            interval_mins = int(av_interval.replace('min', ''))
            time_diff = datetime.now() - last_timestamp
            missing_intervals = time_diff.total_seconds() / 60 / interval_mins

            # If we're missing more intervals than compact provides (~100)
            # we may need multiple fetches to get all missing data
            if missing_intervals > 100:
                # If reasonable number (e.g., 200-300), we could do multiple compact fetches
                # For simplicity in this implementation, we'll just do a full fetch
                output_size = "full"
                fetch_strategy = "gap_fill"
                self.logger.info(
                    f"[{request_id}] Large data gap ({missing_intervals:.0f} intervals) - filling gap for {ticker}")

                # Update status
                with self.lock:
                    self.ticker_status[ticker] = "filling_gap"
            else:
                self.logger.info(f"[{request_id}] Fetching ~{missing_intervals:.0f} missing intervals for {ticker}")

                # Update status
                with self.lock:
                    self.ticker_status[ticker] = "fetching_recent"

        # Build API URL
        base_url = "https://www.alphavantage.co/query"
        params = {
            "function": function,
            "symbol": ticker,
            "interval": av_interval,
            "outputsize": output_size,
            "apikey": self.config["alpha_vantage_api_key"]
        }

        try:
            # Make API request with backoff
            with self.lock:
                self.ticker_status[ticker] = "api_request"

            self.logger.info(f"[{request_id}] Making fresh API request for {ticker}")
            data = self._fetch_with_backoff(base_url, params, request_id=request_id)

            # Save to cache
            self._save_cached_response(ticker, function, data, av_interval)

            # Convert to DataFrame
            with self.lock:
                self.ticker_status[ticker] = "processing"

            df = self._convert_intraday_to_dataframe(data, ticker)

            # If we're using the efficient "recent_only" strategy, we need to merge with existing data
            if fetch_strategy == "recent_only" and existing_data is not None and not existing_data.empty:
                # Ensure we have datetime in the right format
                if df is not None and not df.empty:
                    # Convert index to DataFrame column if it's a DatetimeIndex
                    if isinstance(df.index, pd.DatetimeIndex):
                        df = df.reset_index()

                    # Ensure datetime column exists and is datetime type
                    if 'Datetime' in df.columns:
                        df['Datetime'] = pd.to_datetime(df['Datetime'])

                        # Filter out data we already have (keep only newer data)
                        if last_timestamp is not None:
                            new_data = df[df['Datetime'] > last_timestamp]
                            skipped_count = len(df) - len(new_data)

                            if len(new_data) > 0:
                                self.logger.info(
                                    f"[{request_id}] Found {len(new_data)} new data points for {ticker} (skipped {skipped_count} existing records)")
                            else:
                                self.logger.info(
                                    f"[{request_id}] No new data found for {ticker} since {last_timestamp}")

                            # Merge with existing data
                            df = pd.concat([existing_data, new_data]).drop_duplicates(subset=['Datetime'])

                            # Sort by datetime
                            df = df.sort_values('Datetime')

            if df is not None:
                self.logger.info(
                    f"[{request_id}] Successfully processed {len(df)} rows for {ticker} using {fetch_strategy} strategy")

            # Update completion status
            with self.lock:
                self.ticker_status[ticker] = "completed"
                self.ticker_processing_times[ticker]["end"] = time.time()
                self.ticker_processing_times[ticker]["duration"] = (
                        self.ticker_processing_times[ticker]["end"] -
                        self.ticker_processing_times[ticker]["start"]
                )

            return df

        except Exception as e:
            self.logger.error(f"[{request_id}] Error fetching data for {ticker} from Alpha Vantage: {e}")

            # Update status
            with self.lock:
                self.ticker_status[ticker] = "error"

            # Try to use cache as fallback, even if it's older than we'd like
            self.logger.info(f"[{request_id}] Attempting to use cache as fallback for {ticker}")
            cached_data = self._get_cached_response(ticker, function, av_interval,
                                                    max_age_hours=168)  # Up to 1 week old
            if cached_data:
                with self.lock:
                    self.ticker_status[ticker] = "using_fallback_cache"
                df = self._convert_intraday_to_dataframe(cached_data, ticker)

                # Update completion status
                with self.lock:
                    self.ticker_status[ticker] = "completed_with_fallback"
                    self.ticker_processing_times[ticker]["end"] = time.time()
                    self.ticker_processing_times[ticker]["duration"] = (
                            self.ticker_processing_times[ticker]["end"] -
                            self.ticker_processing_times[ticker]["start"]
                    )
                return df

            # If no cache, return existing data as a last resort
            if existing_data is not None and not existing_data.empty:
                self.logger.info(f"[{request_id}] Using existing data as fallback for {ticker}")

                with self.lock:
                    self.ticker_status[ticker] = "using_existing_data"
                    self.ticker_processing_times[ticker]["end"] = time.time()
                    self.ticker_processing_times[ticker]["duration"] = (
                            self.ticker_processing_times[ticker]["end"] -
                            self.ticker_processing_times[ticker]["start"]
                    )
                return existing_data

            # Update final status if all fallbacks failed
            with self.lock:
                self.ticker_status[ticker] = "failed"
                self.ticker_processing_times[ticker]["end"] = time.time()
                self.ticker_processing_times[ticker]["duration"] = (
                        self.ticker_processing_times[ticker]["end"] -
                        self.ticker_processing_times[ticker]["start"]
                )
            return None

        def _get_cached_response(self, ticker, function, interval=None, max_age_hours=24):
            """Get cached response if available and not too old."""
            cache_path = self._get_cache_path(ticker, function, interval)

            if os.path.exists(cache_path):
                # Check file age
                file_time = os.path.getmtime(cache_path)
                age_hours = (time.time() - file_time) / 3600

                if age_hours <= max_age_hours:
                    try:
                        with open(cache_path, 'r') as f:
                            self.logger.info(
                                f"Using cached data for {ticker} (age: {age_hours:.1f} hours, max: {max_age_hours:.1f} hours)")
                            return json.load(f)
                    except Exception as e:
                        self.logger.warning(f"Failed to load cached data: {e}")
                else:
                    self.logger.info(
                        f"Cache for {ticker} is too old ({age_hours:.1f} hours > {max_age_hours:.1f} hours), fetching fresh data")

            return None

        def _should_fetch_new_data(self, ticker, last_timestamp):
            """
            Determine if we should fetch new data based on market hours and last timestamp.

            Args:
                ticker (str): The stock ticker symbol.
                last_timestamp (datetime): The timestamp of the most recent data point.

            Returns:
                bool: True if new data should be fetched, False otherwise.
            """
            if last_timestamp is None:
                return True

            # Get current time in Eastern Time (ET)
            now = datetime.now()
            eastern = pytz.timezone('America/New_York')
            et_now = now.astimezone(eastern) if now.tzinfo else eastern.localize(now)

            # Convert last_timestamp to ET for comparison if it's not timezone-aware
            if last_timestamp.tzinfo is None:
                # Create a datetime object in ET timezone
                et_last = eastern.localize(last_timestamp)
            else:
                # Convert existing timezone to ET
                et_last = last_timestamp.astimezone(eastern)

            # Check if it's a weekday
            is_weekday = et_now.weekday() < 5  # 0-4 are weekdays (Monday-Friday)

            # Calculate time difference in minutes
            time_diff_minutes = (et_now - et_last).total_seconds() / 60

            # If it's a weekday and current time is between 4:00 AM and 8:00 PM ET (extended market hours)
            if is_weekday and 4 <= et_now.hour < 20:
                # During market hours, fetch if last data is more than 10 minutes old
                if time_diff_minutes > 10:
                    self.logger.info(
                        f"Market hours: Last data for {ticker} is {time_diff_minutes:.1f} minutes old - fetching new data")
                    return True
                else:
                    self.logger.info(
                        f"Market hours: Last data for {ticker} is only {time_diff_minutes:.1f} minutes old - using existing data")
                    return False
            else:
                # Outside market hours, fetch if last data is more than 60 minutes old
                if time_diff_minutes > 60:
                    self.logger.info(
                        f"Outside market hours: Last data for {ticker} is {time_diff_minutes:.1f} minutes old - fetching new data")
                    return True
                else:
                    self.logger.info(
                        f"Outside market hours: Last data for {ticker} is only {time_diff_minutes:.1f} minutes old - using existing data")
                    return False

    def _convert_intraday_to_dataframe(self, data, ticker):
        """Convert Alpha Vantage intraday JSON response to DataFrame."""
        if not data:
            return None

        # Extract time series data
        time_series_keys = [k for k in data.keys() if k.startswith('Time Series')]
        if not time_series_keys:
            self.logger.error(f"Unexpected response format from Alpha Vantage for {ticker}")
            return None

        time_series_key = time_series_keys[0]
        time_series = data[time_series_key]

        # Convert to DataFrame
        df = pd.DataFrame.from_dict(time_series, orient="index")

        # Rename columns (Alpha Vantage uses prefixes)
        if not df.empty:
            df.columns = [col.split(". ")[1] for col in df.columns]
            df.index.name = "Datetime"

            # Convert values to numeric
            for col in df.columns:
                df[col] = pd.to_numeric(df[col])

            # Add ticker column
            df["Ticker"] = ticker

            # Sort by datetime index (descending by default from Alpha Vantage)
            # but we want to ensure consistent sorting
            df = df.sort_index()

            # Reset index to make Datetime a column
            df = df.reset_index()

        return df

    def _fetch_daily_data(self, ticker, force=False):
        """
        Fetch daily data from Alpha Vantage API with caching and range-based optimization.

        Args:
            ticker (str): The stock ticker symbol.
            force (bool): Force refresh even if cache is valid, but still optimize for date range.

        Returns:
            pd.DataFrame: DataFrame containing the fetched stock data.
        """
        request_id = str(uuid.uuid4())[:8]
        self.logger.info(f"[{request_id}] Fetching daily data for {ticker}")

        # Update ticker status for progress tracking
        with self.lock:
            self.ticker_status[ticker] = "started"
            self.ticker_processing_times[ticker] = {"start": time.time()}

        function = "TIME_SERIES_DAILY"

        # Load existing data to determine what range we need to fetch
        existing_data = None
        file_path = os.path.join(self.config["data_dir"], f"{ticker}_data.csv")
        last_timestamp = None

        if os.path.exists(file_path):
            try:
                existing_data = pd.read_csv(file_path)
                if 'Datetime' in existing_data.columns and not existing_data.empty:
                    # Find the most recent timestamp in our data
                    existing_data['Datetime'] = pd.to_datetime(existing_data['Datetime'])
                    last_timestamp = existing_data['Datetime'].max()
                    self.logger.info(f"[{request_id}] Found existing data for {ticker} up to {last_timestamp}")

                    # Update status
                    with self.lock:
                        self.ticker_status[ticker] = "found_existing"
            except Exception as e:
                self.logger.warning(f"[{request_id}] Error loading existing data: {e}")

        # Try to get from cache if not forcing refresh
        if not force:
            cached_data = self._get_cached_response(ticker, function)
            if cached_data:
                # Update status
                with self.lock:
                    self.ticker_status[ticker] = "using_cache"

                # Convert cached data to DataFrame
                df = self._convert_daily_to_dataframe(cached_data, ticker)

                # Update completion status
                with self.lock:
                    self.ticker_status[ticker] = "completed"
                    self.ticker_processing_times[ticker]["end"] = time.time()
                    self.ticker_processing_times[ticker]["duration"] = (
                            self.ticker_processing_times[ticker]["end"] -
                            self.ticker_processing_times[ticker]["start"]
                    )

                return df

        # Determine optimal fetch strategy based on existing data
        output_size = "compact"  # Default to compact (latest 100 data points)

        # If we have recent data and we're within the API's compact window (100 data points)
        # we can use compact mode efficiently
        fetch_strategy = "recent_only"

        # If we have no data or very old data, we need a full fetch
        if last_timestamp is None or (datetime.now() - last_timestamp).days > 100:
            output_size = "full"
            fetch_strategy = "full_history"
            self.logger.info(f"[{request_id}] No recent data found - fetching full history for {ticker}")

            # Update status
            with self.lock:
                self.ticker_status[ticker] = "fetching_full"
        else:
            # We have recent data - calculate how many days we're missing
            time_diff = datetime.now() - last_timestamp
            missing_days = time_diff.days

            # If we're missing more days than compact provides (~100)
            if missing_days > 100:
                output_size = "full"
                fetch_strategy = "gap_fill"
                self.logger.info(f"[{request_id}] Large data gap ({missing_days} days) - filling gap for {ticker}")

                # Update status
                with self.lock:
                    self.ticker_status[ticker] = "filling_gap"
            else:
                self.logger.info(f"[{request_id}] Fetching ~{missing_days} missing days for {ticker}")

                # Update status
                with self.lock:
                    self.ticker_status[ticker] = "fetching_recent"

        # Build API URL
        base_url = "https://www.alphavantage.co/query"
        params = {
            "function": function,
            "symbol": ticker,
            "outputsize": output_size,
            "apikey": self.config["alpha_vantage_api_key"]
        }

        try:
            # Make API request with backoff
            with self.lock:
                self.ticker_status[ticker] = "api_request"

            data = self._fetch_with_backoff(base_url, params, request_id=request_id)

            # Save to cache
            self._save_cached_response(ticker, function, data)

            # Convert to DataFrame
            with self.lock:
                self.ticker_status[ticker] = "processing"

            df = self._convert_daily_to_dataframe(data, ticker)

            # If we're using the efficient "recent_only" strategy, we need to merge with existing data
            if fetch_strategy == "recent_only" and existing_data is not None and not existing_data.empty:
                # Ensure we have datetime in the right format
                if df is not None and not df.empty:
                    # Convert index to DataFrame column if it's a DatetimeIndex
                    if isinstance(df.index, pd.DatetimeIndex):
                        df = df.reset_index()

                    # Ensure datetime column exists and is datetime type
                    if 'Datetime' in df.columns:
                        df['Datetime'] = pd.to_datetime(df['Datetime'])

                        # Filter out data we already have (keep only newer data)
                        if last_timestamp is not None:
                            new_data = df[df['Datetime'] > last_timestamp]
                            skipped_count = len(df) - len(new_data)

                            if skipped_count > 0:
                                self.logger.info(
                                    f"[{request_id}] Skipped {skipped_count} already existing records for {ticker}")

                            # Merge with existing data
                            df = pd.concat([existing_data, new_data]).drop_duplicates(subset=['Datetime'])

                            # Sort by datetime
                            df = df.sort_values('Datetime')

            if df is not None:
                self.logger.info(
                    f"[{request_id}] Successfully processed {len(df)} rows for {ticker} using {fetch_strategy} strategy")

            # Update completion status
            with self.lock:
                self.ticker_status[ticker] = "completed"
                self.ticker_processing_times[ticker]["end"] = time.time()
                self.ticker_processing_times[ticker]["duration"] = (
                        self.ticker_processing_times[ticker]["end"] -
                        self.ticker_processing_times[ticker]["start"]
                )

            return df

        except Exception as e:
            self.logger.error(f"[{request_id}] Error fetching data for {ticker} from Alpha Vantage: {e}")

            # Update status
            with self.lock:
                self.ticker_status[ticker] = "error"

            # Try to use cache as fallback, even if it's older than we'd like
            self.logger.info(f"[{request_id}] Attempting to use cache as fallback for {ticker}")
            cached_data = self._get_cached_response(ticker, function, max_age_hours=168)  # Up to 1 week old
            if cached_data:
                with self.lock:
                    self.ticker_status[ticker] = "using_fallback_cache"
                df = self._convert_daily_to_dataframe(cached_data, ticker)

                # Update completion status
                with self.lock:
                    self.ticker_status[ticker] = "completed_with_fallback"
                    self.ticker_processing_times[ticker]["end"] = time.time()
                    self.ticker_processing_times[ticker]["duration"] = (
                            self.ticker_processing_times[ticker]["end"] -
                            self.ticker_processing_times[ticker]["start"]
                    )
                return df

            # If no cache, return existing data as a last resort
            if existing_data is not None and not existing_data.empty:
                self.logger.info(f"[{request_id}] Using existing data as fallback for {ticker}")

                with self.lock:
                    self.ticker_status[ticker] = "using_existing_data"
                    self.ticker_processing_times[ticker]["end"] = time.time()
                    self.ticker_processing_times[ticker]["duration"] = (
                            self.ticker_processing_times[ticker]["end"] -
                            self.ticker_processing_times[ticker]["start"]
                    )
                return existing_data

            # Update final status if all fallbacks failed
            with self.lock:
                self.ticker_status[ticker] = "failed"
                self.ticker_processing_times[ticker]["end"] = time.time()
                self.ticker_processing_times[ticker]["duration"] = (
                        self.ticker_processing_times[ticker]["end"] -
                        self.ticker_processing_times[ticker]["start"]
                )
            return None

    def _convert_daily_to_dataframe(self, data, ticker):
        """Convert Alpha Vantage daily JSON response to DataFrame."""
        if not data:
            return None

        # Extract time series data
        if "Time Series (Daily)" not in data:
            self.logger.error(f"Unexpected response format from Alpha Vantage for {ticker}")
            return None

        # Convert to DataFrame
        time_series = data["Time Series (Daily)"]
        df = pd.DataFrame.from_dict(time_series, orient="index")

        # Rename columns (Alpha Vantage uses prefixes)
        if not df.empty:
            df.columns = [col.split(". ")[1] for col in df.columns]
            df.index.name = "Datetime"

            # Convert values to numeric
            for col in df.columns:
                df[col] = pd.to_numeric(df[col])

            # Add ticker column
            df["Ticker"] = ticker

            # Sort by datetime index (descending by default from Alpha Vantage)
            # but we want to ensure consistent sorting
            df = df.sort_index()

            # Reset index to make Datetime a column
            df = df.reset_index()

        return df

    def _validate_data(self, df, ticker):
        """
        Perform quality checks on fetched data and automatically fix common issues.

        Args:
            df (pd.DataFrame): The data to validate and clean.
            ticker (str): The ticker symbol.

        Returns:
            tuple: (cleaned_df, actions) - The cleaned dataframe and list of cleaning actions performed.
        """
        if df is None or df.empty:
            return df, ["Empty dataframe - no cleaning possible"]

        issues = []
        actions = []

        # Make a copy to avoid modifying the original
        df_copy = df.copy()

        # Ensure index is datetime for time-based validations
        datetime_in_index = df_copy.index.name == "Datetime"
        datetime_in_columns = "Datetime" in df_copy.columns

        if datetime_in_index:
            df_copy.index = pd.to_datetime(df_copy.index)
        elif datetime_in_columns:
            df_copy["Datetime"] = pd.to_datetime(df_copy["Datetime"])

        # Check for data freshness
        if datetime_in_index:
            most_recent = df_copy.index.max()
            days_old = (pd.Timestamp.now() - most_recent).days
            if days_old > 5:  # More than 5 days old
                issues.append(f"Data may be stale - most recent is {days_old} days old")
        elif datetime_in_columns:
            most_recent = pd.to_datetime(df_copy["Datetime"]).max()
            days_old = (pd.Timestamp.now() - most_recent).days
            if days_old > 5:  # More than 5 days old
                issues.append(f"Data may be stale - most recent is {days_old} days old")

        # Check for price jumps
        price_col = None
        if "close" in df_copy.columns:
            price_col = "close"
        elif "Close" in df_copy.columns:
            price_col = "Close"

        if price_col:
            if datetime_in_index:
                df_sorted = df_copy.sort_index()
            else:
                df_sorted = df_copy.sort_values("Datetime") if datetime_in_columns else df_copy

            df_sorted["pct_change"] = df_sorted[price_col].pct_change()
            big_jumps = df_sorted[abs(df_sorted["pct_change"]) > 0.1]
            if not big_jumps.empty:
                issues.append(f"Found {len(big_jumps)} price jumps > 10%")

                # Log the specific jumps for investigation
                for idx, row in big_jumps.iterrows():
                    dt = idx if datetime_in_index else row.get("Datetime", "Unknown")
                    self.logger.warning(f"Large price jump for {ticker} at {dt}: {row['pct_change'] * 100:.2f}% change")

        # Fix duplicate timestamps - automatically remove duplicates, keeping the latest
        if datetime_in_index:
            duplicates = df_copy.index.duplicated().sum()
            if duplicates > 0:
                issues.append(f"Found {duplicates} duplicate timestamps")
                # Fix: Keep the latest record for each timestamp
                df_copy = df_copy[~df_copy.index.duplicated(keep='last')]
                actions.append(f"Removed {duplicates} duplicate timestamps")
        elif datetime_in_columns:
            duplicates = df_copy["Datetime"].duplicated().sum()
            if duplicates > 0:
                issues.append(f"Found {duplicates} duplicate timestamps")
                # Fix: Keep the latest record for each timestamp
                df_copy = df_copy.drop_duplicates(subset=["Datetime"], keep='last')
                actions.append(f"Removed {duplicates} duplicate timestamps")

        # Check for and fix missing values
        missing_values = df_copy.isnull().sum()
        total_missing = missing_values.sum()

        if total_missing > 0:
            issues.append(f"Found {total_missing} missing values")

            # Log the specific columns with missing values
            for col, count in missing_values.items():
                if count > 0:
                    self.logger.warning(f"Missing values in {ticker} column '{col}': {count}")

            # Fix missing values intelligently
            # 1. Volume: Use linear interpolation
            if "volume" in df_copy.columns and missing_values.get("volume", 0) > 0:
                before_count = df_copy["volume"].isna().sum()
                df_copy["volume"].interpolate(method="linear", inplace=True)
                df_copy["volume"].fillna(method="bfill", inplace=True)  # For edge cases
                df_copy["volume"].fillna(method="ffill", inplace=True)  # For edge cases
                after_count = df_copy["volume"].isna().sum()
                actions.append(f"Interpolated {before_count - after_count} missing volume values")

            if "Volume" in df_copy.columns and missing_values.get("Volume", 0) > 0:
                before_count = df_copy["Volume"].isna().sum()
                df_copy["Volume"].interpolate(method="linear", inplace=True)
                df_copy["Volume"].fillna(method="bfill", inplace=True)  # For edge cases
                df_copy["Volume"].fillna(method="ffill", inplace=True)  # For edge cases
                after_count = df_copy["Volume"].isna().sum()
                actions.append(f"Interpolated {before_count - after_count} missing Volume values")

            # 2. Close: Use forward fill (last observation carried forward)
            if "close" in df_copy.columns and missing_values.get("close", 0) > 0:
                before_count = df_copy["close"].isna().sum()
                df_copy["close"].fillna(method="ffill", inplace=True)
                df_copy["close"].fillna(method="bfill", inplace=True)  # For edge cases
                after_count = df_copy["close"].isna().sum()
                actions.append(f"Filled {before_count - after_count} missing close values")

            if "Close" in df_copy.columns and missing_values.get("Close", 0) > 0:
                before_count = df_copy["Close"].isna().sum()
                df_copy["Close"].fillna(method="ffill", inplace=True)
                df_copy["Close"].fillna(method="bfill", inplace=True)  # For edge cases
                after_count = df_copy["Close"].isna().sum()
                actions.append(f"Filled {before_count - after_count} missing Close values")

            # 3. Other OHLC values: Linear interpolation with ffill/bfill for edge cases
            for col in ["open", "high", "low", "Open", "High", "Low"]:
                if col in df_copy.columns and missing_values.get(col, 0) > 0:
                    before_count = df_copy[col].isna().sum()
                    df_copy[col].interpolate(method="linear", inplace=True)
                    df_copy[col].fillna(method="ffill", inplace=True)  # For edge cases
                    df_copy[col].fillna(method="bfill", inplace=True)  # For edge cases
                    after_count = df_copy[col].isna().sum()
                    actions.append(f"Filled {before_count - after_count} missing {col} values")

        # Log any issues and actions
        if issues:
            self.logger.warning(f"Data quality issues for {ticker}: {'; '.join(issues)}")
        if actions:
            self.logger.info(f"Data cleaning for {ticker}: {'; '.join(actions)}")

        return df_copy, actions

    def _process_dataframe(self, df, ticker):
        """
        Process the raw dataframe from Alpha Vantage.

        Args:
            df (pd.DataFrame): Raw dataframe from Alpha Vantage.
            ticker (str): The ticker symbol.

        Returns:
            pd.DataFrame: Processed dataframe.
        """
        if df is None or df.empty:
            self.logger.warning(f"Empty dataframe for {ticker}, skipping processing")
            return None

        # Make a copy to avoid modifying the original
        processed_df = df.copy()

        # Rename columns to match our standard schema
        column_mapping = {
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume"
        }

        # Only rename columns that exist
        cols_to_rename = {k: v for k, v in column_mapping.items() if k in processed_df.columns}
        processed_df = processed_df.rename(columns=cols_to_rename)

        # Convert index to datetime if it's not already
        if processed_df.index.name == "Datetime":
            processed_df.index = pd.to_datetime(processed_df.index)
            processed_df = processed_df.reset_index()  # Make Datetime a column

        # Ensure Datetime is a column, not an index
        if 'Datetime' not in processed_df.columns and processed_df.index.name != 'Datetime':
            processed_df = processed_df.reset_index()  # Try to reset any existing index
            if 'index' in processed_df.columns:
                processed_df = processed_df.rename(columns={'index': 'Datetime'})

        # Convert Datetime column to datetime objects
        if 'Datetime' in processed_df.columns:
            processed_df['Datetime'] = pd.to_datetime(processed_df['Datetime'])

            # Store a sample of original timestamps for debugging
            try:
                sample_original = processed_df['Datetime'].iloc[0:3].tolist()

                # Apply timezone shift (add 7 hours)
                processed_df['Datetime'] = processed_df['Datetime'] + pd.Timedelta(hours=7)

                # Log sample conversion without special characters (to avoid encoding errors)
                sample_converted = processed_df['Datetime'].iloc[0:3].tolist()
                self.logger.info(f"Sample ET to IST conversion: {sample_original[0]} to {sample_converted[0]}")
                self.logger.info(f"Successfully converted {ticker} timestamps from ET to IST")
            except Exception as e:
                self.logger.error(f"Error in timezone conversion: {e}")

        # Clean the data
        # Remove rows with invalid values (NaN in critical columns)
        cols_to_check = [col for col in ['Open', 'Close', 'High', 'Low'] if col in processed_df.columns]
        if cols_to_check:
            processed_df = processed_df.dropna(subset=cols_to_check)

        # Remove rows with zero volume if Volume column exists
        if 'Volume' in processed_df.columns:
            processed_df = processed_df[processed_df['Volume'] > 0]

        # Remove rows with infinite values
        processed_df = processed_df.replace([np.inf, -np.inf], np.nan)
        processed_df = processed_df.dropna()

        # Interpolate missing values in Volume if the column exists
        if 'Volume' in processed_df.columns:
            processed_df['Volume'] = processed_df['Volume'].interpolate(method='linear')

        # Round numerical columns to 2 decimal places
        for col in [c for c in ['Open', 'High', 'Low', 'Close'] if c in processed_df.columns]:
            processed_df[col] = processed_df[col].round(2)

        # Validate and automatically clean the processed data
        processed_df, actions = self._validate_data(processed_df, ticker)
        if actions:
            self.logger.info(f"Data cleaning during processing for {ticker}: {', '.join(actions)}")

        # IMPORTANT FIX: Handle duplicate timestamps that could be created by timezone conversion
        if 'Datetime' in processed_df.columns:
            # Check if there are duplicates
            dup_count = processed_df.duplicated(subset=['Datetime']).sum()
            if dup_count > 0:
                self.logger.warning(f"Found {dup_count} duplicate timestamps for {ticker}, keeping latest values")
                processed_df = processed_df.drop_duplicates(subset=['Datetime'], keep='last')

            # Always sort consistently in ascending order (oldest to newest)
            processed_df = processed_df.sort_values('Datetime', ascending=True)
            self.logger.debug(f"Processed dataframe sorted chronologically for {ticker} with {len(processed_df)} rows")

        # Generate data schema documentation
        schema_path = os.path.join(self.config["data_dir"], f"{ticker}_schema.json")
        self._document_data_schema(processed_df, schema_path)

        return processed_df

    def _document_data_schema(self, df, output_path):
        """
        Generate documentation for the data schema.

        Args:
            df (pd.DataFrame): The data to document.
            output_path (str): Where to save the schema documentation.
        """
        if df is None or df.empty:
            return

        # Get column descriptions
        descriptions = {
            "Datetime": "Date and time of the price data in 'YYYY-MM-DD HH:MM' format (Israel Standard Time)",
            "Open": "Opening price for the time period",
            "High": "Highest price during the time period",
            "Low": "Lowest price during the time period",
            "Close": "Closing price for the time period",
            "Volume": "Number of shares traded during the time period",
            "Ticker": "Stock ticker symbol"
        }

        # Create the schema
        schema = {
            "columns": {col: {
                "dtype": str(df[col].dtype),
                "sample": str(df[col].iloc[0]) if not df.empty else None,
                "description": descriptions.get(col, "No description available")
            } for col in df.columns},
            "rows": len(df),
            "date_range": f"{df['Datetime'].min()} to {df['Datetime'].max()}" if 'Datetime' in df.columns else None,
            "tickers": df['Ticker'].unique().tolist() if 'Ticker' in df.columns else None
        }

        # Add basic statistics
        stats = {}
        for col in [c for c in ['Open', 'High', 'Low', 'Close'] if c in df.columns]:
            stats[col] = {
                "min": float(df[col].min()),
                "max": float(df[col].max()),
                "mean": float(df[col].mean()),
                "median": float(df[col].median())
            }

        if stats:
            schema["statistics"] = stats

        # Save to file
        try:
            with open(output_path, 'w') as f:
                json.dump(schema, f, indent=2, default=str)
        except Exception as e:
            self.logger.warning(f"Error saving schema documentation: {e}")

    def _save_ticker_data(self, df, ticker):
        """
        Save processed dataframe to CSV using a consistent sorting approach.

        Args:
            df (pd.DataFrame): Processed dataframe with new data to save.
            ticker (str): The ticker symbol.

        Returns:
            str: Path to the saved CSV file.
        """
        if df is None or df.empty:
            self.logger.warning(f"No data to save for {ticker}")
            return None

        # Construct file path
        file_path = os.path.join(self.config["data_dir"], f"{ticker}_data.csv")

        # Check if file exists
        file_exists = os.path.isfile(file_path)

        # In both cases, ensure we have datetime in the right format
        if 'Datetime' in df.columns:
            df['Datetime'] = pd.to_datetime(df['Datetime'])

        # Always sort the incoming data by datetime in ascending order for consistency
        if 'Datetime' in df.columns:
            df = df.sort_values('Datetime', ascending=True)

        if file_exists:
            # Load and merge approach - we'll optimize for memory usage but ensure consistent sorting
            try:
                # Read the entire file - this is more reliable but potentially memory-intensive for large files
                # For production systems with very large files, consider using a database instead of CSV
                existing_data = pd.read_csv(file_path)

                if 'Datetime' in existing_data.columns:
                    existing_data['Datetime'] = pd.to_datetime(existing_data['Datetime'])

                    # Combine with new data
                    combined_data = pd.concat([existing_data, df])

                    # Remove duplicates, keeping the most recent version
                    combined_data = combined_data.drop_duplicates(subset=['Datetime'], keep='last')

                    # Sort by datetime in ASCENDING order (oldest first, newest last)
                    # This ensures consistent ordering regardless of how data is appended
                    combined_data = combined_data.sort_values('Datetime', ascending=True)

                    # Save to CSV (complete rewrite)
                    combined_data.to_csv(file_path, index=False)

                    # Store in memory
                    self.dataframes[ticker] = combined_data

                    self.logger.info(f"Updated data for {ticker}, total rows: {len(combined_data)}")
                else:
                    # Fallback if Datetime column not found
                    self.logger.warning(f"No Datetime column found in {file_path}, using fallback approach")
                    self._save_ticker_data_fallback(df, ticker, file_path)
            except Exception as e:
                self.logger.warning(f"Error merging data for {ticker}, using fallback: {e}")
                self._save_ticker_data_fallback(df, ticker, file_path)
        else:
            # For new files, simply write the sorted dataframe
            df.to_csv(file_path, index=False)
            self.logger.info(f"Created new data file for {ticker}, rows: {len(df)}")

            # Store in memory
            self.dataframes[ticker] = df

        return file_path

    def _save_ticker_data_fallback(self, df, ticker, file_path):
        """
        Fallback method for saving ticker data when the primary approach fails.

        Args:
            df (pd.DataFrame): The data to save
            ticker (str): The ticker symbol
            file_path (str): Path to the output file
        """
        try:
            # Ensure datetime is in the right format and sort the incoming data
            if 'Datetime' in df.columns:
                df['Datetime'] = pd.to_datetime(df['Datetime'])
                df = df.sort_values('Datetime', ascending=True)

            if os.path.exists(file_path):
                # Load existing data - full file read (memory intensive but reliable)
                existing_data = pd.read_csv(file_path)

                if 'Datetime' in existing_data.columns:
                    existing_data['Datetime'] = pd.to_datetime(existing_data['Datetime'])

                # Combine with new data
                combined_data = pd.concat([existing_data, df])

                # Remove duplicates
                if 'Datetime' in combined_data.columns:
                    combined_data = combined_data.drop_duplicates(subset=['Datetime'], keep='last')

                    # Always sort consistently in ASCENDING order (oldest first)
                    combined_data = combined_data.sort_values('Datetime', ascending=True)

                # Save to CSV (full rewrite)
                combined_data.to_csv(file_path, index=False)

                # Store in memory
                self.dataframes[ticker] = combined_data

                self.logger.info(f"Fallback: Updated data for {ticker}, total rows: {len(combined_data)}")
            else:
                # File doesn't exist, just write the data directly
                df.to_csv(file_path, index=False)
                self.dataframes[ticker] = df
                self.logger.info(f"Fallback: Created new data file for {ticker}, rows: {len(df)}")
        except Exception as e:
            self.logger.error(f"Fallback also failed for {ticker}: {e}")
            # Last resort: just save the new data, potentially losing old data
            try:
                # Final attempt - sort and save just the new data
                if 'Datetime' in df.columns:
                    df = df.sort_values('Datetime', ascending=True)
                df.to_csv(file_path, index=False)
                self.dataframes[ticker] = df
                self.logger.warning(f"Last resort: Saved only new data for {ticker}, old data may be lost")
            except Exception as e2:
                self.logger.critical(f"Critical failure saving data for {ticker}: {e2}")
                # Nothing we can do at this point

    def _update_last_fetched_time(self, df, ticker):
        """
        Update the last fetched time for a ticker.

        Args:
            df (pd.DataFrame): Processed dataframe.
            ticker (str): The ticker symbol.
        """
        if df is None or df.empty:
            return

        # Get the latest datetime
        if 'Datetime' in df.columns:
            latest_time = df['Datetime'].max()

            # Update in config
            self.config["last_fetched_times"][ticker] = latest_time

            # Save config
            self._save_config()

            self.logger.info(f"Updated last fetched time for {ticker} to {latest_time}")

    def fetch_single_ticker(self, ticker, force=False):
        """
        Fetch data for a single ticker with optimized API usage.

        Args:
            ticker (str): The ticker symbol to fetch.
            force (bool): Whether to force refresh even if cache is valid.

        Returns:
            pd.DataFrame: The processed ticker data.
        """
        # Even with force=True, we now use a smarter approach that only fetches missing data
        # from the last successful timestamp rather than fetching everything again
        try:
            # Get the data type (intraday or daily)
            data_type = self.config.get("alpha_vantage_params", {}).get("data_type", "intraday")

            # Fetch data based on type
            if data_type == "intraday":
                df = self._fetch_intraday_data(ticker, force=force)
            else:
                df = self._fetch_daily_data(ticker, force=force)

            if df is not None:
                # Process data
                processed_df = self._process_dataframe(df, ticker)

                # Save to CSV
                self._save_ticker_data(processed_df, ticker)

                # Update last fetched time
                self._update_last_fetched_time(processed_df, ticker)

                return processed_df
            else:
                self.logger.warning(f"No data returned for {ticker}")
                return None

        except Exception as e:
            self.logger.error(f"Error processing {ticker}: {e}")
            return None

    def fetch_all_tickers(self, force=False, parallel=False, max_workers=None):
        """
        Fetch data for all tickers in the configuration with optimized parallel processing.

        Args:
            force (bool): Whether to force refresh even if cache is valid.
            parallel (bool): Whether to fetch tickers in parallel.
            max_workers (int, optional): Maximum number of parallel workers. If None, will be auto-determined.
        """
        if parallel:
            # If max_workers is not specified, we'll use the optimized value in _fetch_all_tickers_parallel
            self._fetch_all_tickers_parallel(force=force, max_workers=max_workers)
        else:
            self._fetch_all_tickers_sequential(force=force)

    def _fetch_all_tickers_sequential(self, force=False):
        """
        Fetch all tickers sequentially with proper rate limiting.

        Args:
            force (bool): Whether to force refresh even if cache is valid.
        """
        # Reset progress tracking
        self.ticker_status = {}
        self.ticker_processing_times = {}
        self.progress_start_time = time.time()

        total_tickers = len(self.config["tickers"])

        for i, ticker in enumerate(self.config["tickers"]):
            # Display progress
            print(f"Processing {ticker} ({i + 1}/{total_tickers}, {(i + 1) / total_tickers * 100:.1f}%)")

            # Process the ticker
            self.fetch_single_ticker(ticker, force=force)

            # Calculate and display ETA after a few tickers
            if i >= 2 and i < total_tickers - 1:
                elapsed = time.time() - self.progress_start_time
                avg_time_per_ticker = elapsed / (i + 1)
                remaining_tickers = total_tickers - (i + 1)
                eta_seconds = avg_time_per_ticker * remaining_tickers

                # Format ETA
                if eta_seconds < 60:
                    eta_str = f"{eta_seconds:.1f} seconds"
                elif eta_seconds < 3600:
                    eta_str = f"{eta_seconds / 60:.1f} minutes"
                else:
                    eta_str = f"{eta_seconds / 3600:.1f} hours"

                print(f"Estimated time remaining: {eta_str}")

    def _get_current_memory_usage(self):
        """
        Get current memory usage percentage if psutil is available.

        Returns:
            float: Memory usage as percentage or None if psutil not available
        """
        if PSUTIL_AVAILABLE:
            try:
                return psutil.virtual_memory().percent
            except Exception:
                return None
        return None

    def _get_dynamic_semaphore_limit(self):
        """
        Calculate an optimal dynamic semaphore limit based on current conditions.

        Returns:
            int: The optimal number of concurrent API calls
        """
        # Get base configuration values
        base_limit = 2  # Default concurrent API calls
        min_limit = self.config.get("parallel_processing", {}).get("min_semaphore_limit", 1)
        max_limit = self.config.get("parallel_processing", {}).get("max_semaphore_limit", 5)

        # Start with base limit
        dynamic_limit = base_limit

        # Factor in API success rate
        if self.api_success_rate < 0.95:  # Below 95% success
            # Reduce limit based on failure rate
            dynamic_limit = max(min_limit, int(dynamic_limit * self.api_success_rate))
        elif self.api_success_rate > 0.98 and len(self.api_response_times) >= 5:
            # Increase limit if we're doing well
            dynamic_limit += 1

        # Factor in rate limit errors
        if self.api_error_counts.get(429, 0) > 0:
            # Reduce limit if we've hit rate limits
            dynamic_limit = max(min_limit, dynamic_limit - self.api_error_counts[429])

        # Factor in memory usage if available
        memory_usage = self._get_current_memory_usage()
        if memory_usage is not None:
            max_memory = self.config.get("parallel_processing", {}).get("max_memory_percent", 80)
            if memory_usage > max_memory:
                # Reduce if memory usage is high
                dynamic_limit = max(min_limit, dynamic_limit - 1)

        # Ensure we stay within configured limits
        return max(min_limit, min(max_limit, dynamic_limit))

    def _fetch_all_tickers_parallel(self, force=False, max_workers=None):
        """
        Fetch all tickers in parallel with dynamically optimized thread count.

        Args:
            force (bool): Whether to force refresh even if cache is valid.
            max_workers (int, optional): Maximum number of parallel workers. If None, will be auto-determined.
        """
        # Reset progress tracking
        self.ticker_status = {}
        self.ticker_processing_times = {}
        self.progress_start_time = time.time()

        # Calculate optimal number of workers based on system capabilities
        cpu_count = multiprocessing.cpu_count()
        cpu_multiplier = self.config.get("parallel_processing", {}).get("cpu_multiplier", 2)
        optimal_workers = cpu_count * cpu_multiplier  # I/O bound tasks benefit from multiple CPU count

        # If max_workers is not specified, use the optimal number
        if max_workers is None:
            max_workers = optimal_workers

        # Limit max_workers to the number of tickers and optimal value
        ticker_count = len(self.config["tickers"])
        max_workers = min(max_workers, ticker_count, optimal_workers)

        # Check memory if available and reduce workers if needed
        if PSUTIL_AVAILABLE:
            try:
                memory_usage = psutil.virtual_memory().percent
                max_memory = self.config.get("parallel_processing", {}).get("max_memory_percent", 80)

                # If memory usage is already high, reduce workers
                if memory_usage > max_memory * 0.8:  # Over 80% of our limit
                    memory_factor = 0.8  # Reduce by 20%
                    max_workers = max(1, int(max_workers * memory_factor))
                    self.logger.warning(
                        f"High memory usage detected ({memory_usage:.1f}%), reducing workers to {max_workers}")
            except Exception as e:
                self.logger.warning(f"Error checking memory usage: {e}")

        # Log the chosen worker count and the basis for the decision
        self.logger.info(
            f"System has {cpu_count} CPU cores, CPU multiplier: {cpu_multiplier}, optimal worker count: {optimal_workers}")
        self.logger.info(f"Fetching {ticker_count} tickers in parallel with {max_workers} workers")

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Initial semaphore limit based on configuration or dynamic calculation
            if self.config.get("parallel_processing", {}).get("dynamic_throttling", True):
                initial_semaphore_limit = self._get_dynamic_semaphore_limit()
            else:
                initial_semaphore_limit = min(2, max_workers)  # Static: Allow at most 2 concurrent API calls

            # Create the semaphore at function scope
            current_semaphore = threading.Semaphore(initial_semaphore_limit)
            current_semaphore_limit = initial_semaphore_limit

            # Check if we're allowing multiple concurrent API calls
            if current_semaphore_limit > 1:
                self.logger.info(f"Using {current_semaphore_limit} concurrent API calls with rate limiting")
            else:
                self.logger.info("Using strictly sequential API calls for maximum rate limit compliance")

            def fetch_with_rate_limit(ticker):
                # Use the current outer scope semaphore
                nonlocal current_semaphore, current_semaphore_limit

                with current_semaphore:
                    result = self.fetch_single_ticker(ticker, force=force)

                    # Dynamically adjust semaphore limit if enabled
                    if self.config.get("parallel_processing", {}).get("dynamic_throttling", True):
                        # This runs inside the semaphore-protected block to avoid race conditions
                        new_limit = self._get_dynamic_semaphore_limit()

                        # If the limit has changed, create a new semaphore
                        if new_limit != current_semaphore_limit:
                            with self.lock:  # Use lock to avoid race conditions when updating semaphore
                                self.logger.info(
                                    f"Dynamically adjusting concurrent API calls from {current_semaphore_limit} to {new_limit}")
                                current_semaphore_limit = new_limit
                                current_semaphore = threading.Semaphore(new_limit)

                    return ticker, result

            futures = {executor.submit(fetch_with_rate_limit, ticker): ticker
                       for ticker in self.config["tickers"]}

            # Track progress
            completed = 0
            total = len(futures)
            start_time = time.time()

            # For more granular progress reporting
            progress_interval = max(1, min(total // 10, 5))  # Report every 10% or at most every 5 tickers

            # Dictionary to track ticker status for detailed progress reporting
            status_counts = defaultdict(int)

            for future in concurrent.futures.as_completed(futures):
                ticker = futures[future]
                try:
                    ticker, data = future.result()
                    completed += 1

                    # Update status counts for reporting
                    with self.lock:
                        # Import Counter from collections for Counter usage
                        from collections import Counter
                        for status, count in Counter(self.ticker_status.values()).items():
                            status_counts[status] = count

                    # Calculate ETA
                    elapsed = time.time() - start_time
                    ticker_per_second = completed / elapsed if elapsed > 0 else 0
                    remaining = total - completed
                    eta_seconds = remaining / ticker_per_second if ticker_per_second > 0 else 0

                    # Format ETA string
                    if eta_seconds < 60:
                        eta_str = f"{eta_seconds:.1f} seconds"
                    elif eta_seconds < 3600:
                        eta_str = f"{eta_seconds / 60:.1f} minutes"
                    else:
                        eta_str = f"{eta_seconds / 3600:.2f} hours"

                    # Print progress at intervals or for completion
                    if completed == total or completed % progress_interval == 0:
                        # Enhanced progress report with statuses
                        status_report = ", ".join([f"{status}: {count}" for status, count in status_counts.items()])

                        # Get memory usage if available
                        memory_str = ""
                        if PSUTIL_AVAILABLE:
                            try:
                                memory_usage = psutil.virtual_memory().percent
                                memory_str = f", Memory: {memory_usage:.1f}%"
                            except Exception:
                                pass

                        self.logger.info(
                            f"Progress: {completed}/{total} tickers processed ({completed / total * 100:.1f}%), "
                            f"ETA: {eta_str}, Rate: {ticker_per_second:.2f} tickers/sec{memory_str}"
                        )

                        # More detailed log at completion
                        if completed == total:
                            successful = sum(1 for status in self.ticker_status.values()
                                             if status in ["completed", "completed_with_fallback"])
                            self.logger.info(
                                f"Fetch complete. {successful}/{total} tickers processed successfully. "
                                f"Total time: {elapsed:.1f} seconds"
                            )
                except Exception as e:
                    self.logger.error(f"Error in parallel processing for {ticker}: {e}")
                    completed += 1  # Still count it for progress reporting

    def create_combined_dataset(self):
        """Merge all individual CSV files into a single combined dataset with consistent ordering."""
        if not self.dataframes:
            # Try to load data from existing CSV files if available
            for ticker in self.config["tickers"]:
                file_path = os.path.join(self.config["data_dir"], f"{ticker}_data.csv")
                if os.path.isfile(file_path):
                    try:
                        ticker_df = pd.read_csv(file_path)
                        # Ensure datetime is properly formatted
                        if 'Datetime' in ticker_df.columns:
                            ticker_df['Datetime'] = pd.to_datetime(ticker_df['Datetime'])
                            # Ensure consistent sorting within each ticker's data
                            ticker_df = ticker_df.sort_values('Datetime', ascending=True)
                        self.dataframes[ticker] = ticker_df
                        self.logger.info(f"Loaded existing data for {ticker} from {file_path}")
                    except Exception as e:
                        self.logger.warning(f"Error loading data for {ticker}: {e}")

        if not self.dataframes:
            self.logger.warning("No dataframes to combine")
            return None

        # Combine all dataframes
        combined_df = pd.concat(self.dataframes.values())

        # Ensure datetime is properly formatted for the combined dataset
        if 'Datetime' in combined_df.columns:
            combined_df['Datetime'] = pd.to_datetime(combined_df['Datetime'])

        # Sort consistently by ticker (alphabetically) and datetime (chronologically)
        if 'Datetime' in combined_df.columns and 'Ticker' in combined_df.columns:
            combined_df = combined_df.sort_values(['Ticker', 'Datetime'], ascending=[True, True])

        # Save combined dataset
        combined_path = os.path.join(self.config["data_dir"],
                                     self.config.get("combined_file_name", "combined_data.csv"))
        combined_df.to_csv(combined_path, index=False)

        self.logger.info(f"Created combined dataset at {combined_path} with {len(combined_df)} rows")

        return combined_df

    def generate_summary_report(self):
        """
        Generate a summary report of the processed data.

        Returns:
            dict: Summary report.
        """
        if not self.dataframes:
            self.logger.warning("No data to generate summary report")
            return None

        # Combine all dataframes
        all_data = pd.concat(self.dataframes.values())

        # Calculate summary statistics
        summary = {
            "processed_tickers": list(self.dataframes.keys()),
            "total_tickers": len(self.dataframes),
            "total_rows": len(all_data),
            "rows_per_ticker": {ticker: len(df) for ticker, df in self.dataframes.items()},
            "missing_values": all_data.isna().sum().to_dict(),
            "api_calls_today": self.api_calls_today,
            "processing_times": {ticker: f"{data.get('duration', 0):.1f}s"
                                 for ticker, data in self.ticker_processing_times.items()
                                 if 'duration' in data},
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        # Add date range if Datetime column exists
        if 'Datetime' in all_data.columns:
            summary["start_date"] = all_data['Datetime'].min()
            summary["end_date"] = all_data['Datetime'].max()

            # Calculate average time between data points
            all_data['Datetime'] = pd.to_datetime(all_data['Datetime'])
            grouped = all_data.groupby('Ticker')

            avg_intervals = {}
            for ticker, group in grouped:
                sorted_group = group.sort_values('Datetime')
                if len(sorted_group) > 1:
                    # Calculate average interval in minutes
                    intervals = sorted_group['Datetime'].diff().dropna()
                    avg_interval = intervals.mean().total_seconds() / 60
                    avg_intervals[ticker] = round(avg_interval, 1)

            summary["avg_interval_minutes"] = avg_intervals

        # Save summary to json
        summary_path = os.path.join(self.config["data_dir"], "summary_report.json")
        with open(summary_path, 'w') as f:
            json.dump(summary, f, indent=2, default=str)

        self.logger.info(f"Generated summary report at {summary_path}")

        return summary

    @staticmethod
    def explain_sorting_consistency():
        """
        Explain the data sorting approach used to ensure consistent chronological order.

        Returns:
            str: Explanation of the sorting approach
        """
        explanation = """
        DATA SORTING CONSISTENCY APPROACH
        --------------------------------

        The Enhanced Alpha Vantage Stock Data Fetcher now enforces consistent timestamp 
        ordering throughout the entire data processing pipeline:

        1. When data is received from Alpha Vantage:
           - Alpha Vantage sometimes returns data in descending order (newest first)
           - We now immediately sort by datetime in ascending order (oldest first)

        2. When processing dataframes:
           - All dataframes are sorted chronologically before any operations
           - This ensures consistent time ordering regardless of data source

        3. When saving data:
           - The delta-based append approach has been replaced with a more reliable merge-and-sort approach
           - All data is sorted chronologically before saving
           - This prevents timestamp ordering issues when appending new data

        4. When combining datasets:
           - Data is sorted first by ticker (alphabetically) then by datetime (chronologically)
           - This ensures the combined dataset has a consistent and predictable ordering

        These changes ensure that all data follows a consistent chronological order (oldest to newest)
        throughout the entire processing pipeline, eliminating issues with mixed timestamp ordering.
        """
        return explanation


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Enhanced Alpha Vantage Stock Data Fetcher")
    parser.add_argument("--config", default="config.json", help="Path to config file")
    parser.add_argument("--ticker", help="Fetch a specific ticker only")
    parser.add_argument("--force", action="store_true", help="Force refresh even if data is recent")
    parser.add_argument("--parallel", action="store_true", help="Fetch tickers in parallel")
    parser.add_argument("--workers", type=int, default=None,
                        help="Number of parallel workers (default: auto-determined based on CPU count)")
    parser.add_argument("--cpu-multiplier", type=float, default=None,
                        help="Multiplier for CPU cores to determine worker count (default: 2.0 for I/O bound tasks)")
    parser.add_argument("--combine-only", action="store_true", help="Only combine existing data, don't fetch")
    parser.add_argument("--cache-clear", action="store_true", help="Clear the cache before fetching")
    parser.add_argument("--validate", action="store_true", help="Validate existing data and automatically fix issues")
    parser.add_argument("--system-info", action="store_true", help="Display system information and optimal settings")
    parser.add_argument("--disable-dynamic-throttling", action="store_true",
                        help="Disable dynamic throttling based on API responses")
    return parser.parse_args()


def main():
    """Main function to run the EnhancedAlphaVantageStockFetcher."""
    args = parse_args()

    # Display system information if requested
    if args.system_info:
        import multiprocessing
        cpu_count = multiprocessing.cpu_count()
        optimal_workers = cpu_count * 2

        print(f"System Information:")
        print(f"CPU Cores: {cpu_count}")
        print(f"Optimal worker threads: {optimal_workers}")
        print(f"Memory usage monitoring: {'Available' if PSUTIL_AVAILABLE else 'Not available'}")

        if PSUTIL_AVAILABLE:
            memory = psutil.virtual_memory()
            print(f"Total Memory: {memory.total / (1024 ** 3):.1f} GB")
            print(f"Available Memory: {memory.available / (1024 ** 3):.1f} GB")
            print(f"Memory Usage: {memory.percent}%")

        return 0

    # Load config first
    fetcher = EnhancedAlphaVantageStockFetcher(args.config)

    # Update config with command line parameters if specified
    if args.cpu_multiplier is not None:
        fetcher.config["parallel_processing"]["cpu_multiplier"] = args.cpu_multiplier
        fetcher.logger.info(f"Setting CPU multiplier to {args.cpu_multiplier} from command line")

    if args.disable_dynamic_throttling:
        fetcher.config["parallel_processing"]["dynamic_throttling"] = False
        fetcher.logger.info("Disabled dynamic throttling from command line")

    # Save updated config
    fetcher._save_config()

    # Clear cache if requested
    if args.cache_clear:
        cache_dir = os.path.join(fetcher.config["data_dir"], "cache")
        if os.path.exists(cache_dir):
            for file in os.listdir(cache_dir):
                if file.endswith('_cache.json'):
                    os.remove(os.path.join(cache_dir, file))
            print(f"Cleared cache in {cache_dir}")

    # Validation and automated cleaning mode
    if args.validate:
        print("Validating and cleaning existing data...")
        cleaned_count = 0
        for ticker in fetcher.config["tickers"]:
            file_path = os.path.join(fetcher.config["data_dir"], f"{ticker}_data.csv")
            if os.path.isfile(file_path):
                print(f"Processing {ticker}...")
                df = pd.read_csv(file_path)
                cleaned_df, actions = fetcher._validate_data(df, ticker)

                if actions:
                    print(f"  {ticker}: {', '.join(actions)}")
                    # Save the cleaned data back to the file
                    cleaned_df.to_csv(file_path, index=False)
                    print(f"  Saved cleaned data back to {file_path}")
                    cleaned_count += 1
                else:
                    print(f"  {ticker}: No cleaning actions needed, data looks good")

        print(f"\nCleaning complete. Fixed issues in {cleaned_count}/{len(fetcher.config['tickers'])} ticker datasets.")
        return 0

    # Combine-only mode
    if args.combine_only:
        print("Skipping fetch, only combining existing data...")
        fetcher.create_combined_dataset()
        summary = fetcher.generate_summary_report()
    else:
        # Fetch mode
        if args.ticker:
            # Process single ticker
            print(f"Fetching data for {args.ticker}...")
            fetcher.fetch_single_ticker(args.ticker, force=args.force)
        else:
            # Process all tickers
            print("Fetching data for all tickers...")
            fetcher.fetch_all_tickers(force=args.force, parallel=args.parallel, max_workers=args.workers)

        # Create combined dataset and report
        fetcher.create_combined_dataset()
        summary = fetcher.generate_summary_report()

    if summary:
        print("\nSummary Report:")
        print(f"Processed {summary.get('total_tickers', 0)} tickers: {', '.join(summary.get('processed_tickers', []))}")
        if 'start_date' in summary and 'end_date' in summary:
            print(f"Data range: {summary['start_date']} to {summary['end_date']}")
        print(f"Total rows: {summary.get('total_rows', 0)}")
        print(f"API calls today: {summary.get('api_calls_today', 0)}")

        # Show processing times if available
        if 'processing_times' in summary:
            print("\nProcessing times:")
            processing_times = summary['processing_times']
            if processing_times:
                max_time = max([float(time[:-1]) for time in processing_times.values()], default=0)
                min_time = min([float(time[:-1]) for time in processing_times.values()], default=0)
                avg_time = sum([float(time[:-1]) for time in processing_times.values()]) / len(
                    processing_times) if processing_times else 0

                print(f"  Min: {min_time:.1f}s, Max: {max_time:.1f}s, Avg: {avg_time:.1f}s")

                # Show slowest tickers
                if processing_times:
                    sorted_times = sorted(processing_times.items(), key=lambda x: float(x[1][:-1]), reverse=True)
                    print("\n  Slowest tickers:")
                    for ticker, time in sorted_times[:3]:
                        print(f"    {ticker}: {time}")

        print("\nRows per ticker:")
        for ticker, count in summary.get('rows_per_ticker', {}).items():
            print(f"  {ticker}: {count}")

        # Show average interval if available
        if 'avg_interval_minutes' in summary:
            print("\nAverage interval between data points (minutes):")
            for ticker, avg in summary['avg_interval_minutes'].items():
                print(f"  {ticker}: {avg}")

        print("\nMissing values:")
        for col, count in summary.get('missing_values', {}).items():
            if count > 0:
                print(f"  {col}: {count}")
    else:
        print("\nNo data was processed. Check the log for details.")
        return 1

    return 0


if __name__ == "__main__":
    # Import Counter from collections for detailed progress reporting
    try:
        from collections import Counter
    except ImportError:
        # Fallback implementation if Counter is not available
        class Counter(dict):
            def __init__(self, iterable=None):
                super().__init__()
                if iterable:
                    for item in iterable:
                        self[item] = self.get(item, 0) + 1

    sys.exit(main())