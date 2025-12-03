#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Market Pattern Analysis Pipeline

This script implements a pipeline for analyzing temporal market patterns in stock data.
It loads cleaned and normalized stock data, performs pattern detection, and generates
visualizations and reports.

Usage:
    python market_pattern_analysis.py --input path/to/cleaned_data.csv --output path/to/output_dir

Author: [Your Name]
Date: March 2025
"""

import os
import sys
import json
import time
import logging
import argparse
import pandas as pd
import numpy as np
import random
import functools
import numba  # Added for JIT compilation
import traceback

import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend
import matplotlib.pyplot as plt

from typing import Type
from concurrent.futures import ProcessPoolExecutor, as_completed
from sklearn.neighbors import BallTree, KDTree  # Added for spatial indexing
from typing import Callable, Any, Dict, List, Optional, Tuple
from datetime import datetime
from json_encoder_fix import EnhancedJSONEncoder, safe_json_dump

# Pydantic imports
from pydantic import field_validator, model_validator, BaseModel, Field
# Local modules
from Pattern_Detection_Module import PatternDetector

# -------------------------
# Logging Configuration
# -------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("pattern_analysis.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("PatternAnalysisPipeline")


# -------------------------
# Pydantic Models
# -------------------------
class SessionTime(BaseModel):
    start: str
    end: str

    # Cache for time string to minutes conversion
    _time_cache: Dict[str, int] = {}

    @classmethod
    @field_validator('start', 'end')
    def validate_time_format(cls, time_value: str) -> str:
        """Validate time format (HH:MM)."""
        try:
            datetime.strptime(time_value, '%H:%M')
            return time_value
        except ValueError as val_err:
            raise ValueError(f"Time must be in HH:MM format, got {time_value}: {val_err}")

    @staticmethod
    def minutes_since_midnight(time_str: str) -> int:
        """Convert HH:MM time to minutes since midnight."""
        # Check the cache first for performance
        if time_str in SessionTime._time_cache:
            return SessionTime._time_cache[time_str]

        # If not in cache, compute and store
        time_obj = datetime.strptime(time_str, '%H:%M')
        minutes = time_obj.hour * 60 + time_obj.minute
        SessionTime._time_cache[time_str] = minutes
        return minutes

    def is_overnight(self) -> bool:
        """Check if the session crosses midnight."""
        start_mins = self.minutes_since_midnight(self.start)
        end_mins = self.minutes_since_midnight(self.end)
        return end_mins < start_mins


class SessionTimes(BaseModel):
    pre_market: SessionTime
    main_session: SessionTime
    post_market: SessionTime

    @classmethod
    @field_validator('main_session')
    def validate_session_sequence_main(cls, main_val: SessionTime, values: dict) -> SessionTime:
        """Ensure pre-market ends before main session starts."""
        if 'pre_market' in values:
            pre_market_val: SessionTime = values['pre_market']
            if not pre_market_val.is_overnight():
                pre_end = pre_market_val.minutes_since_midnight(pre_market_val.end)
                main_start = main_val.minutes_since_midnight(main_val.start)
                if pre_end > main_start:
                    raise ValueError(
                        f"Pre-market end ({pre_market_val.end}) must be before or at main session start ({main_val.start})"
                    )
        return main_val

    @classmethod
    @field_validator('post_market')
    def validate_session_sequence_post(cls, post_val: SessionTime, values: dict) -> SessionTime:
        """Ensure main session ends before post-market starts."""
        if 'main_session' in values:
            main_session_val: SessionTime = values['main_session']
            if not main_session_val.is_overnight():
                main_end = main_session_val.minutes_since_midnight(main_session_val.end)
                post_start = post_val.minutes_since_midnight(post_val.start)
                if main_end > post_start:
                    raise ValueError(
                        f"Main session end ({main_session_val.end}) must be before or at post-market start ({post_val.start})"
                    )
        return post_val

    @classmethod
    @model_validator(mode='after')
    def check_sessions_overnight(cls, self) -> "SessionTimes":
        """Warn if all sessions cross midnight."""
        if (self.pre_market.is_overnight() and
                self.main_session.is_overnight() and
                self.post_market.is_overnight()):
            logger.warning("All trading sessions cross midnight. This is unusual but allowed.")
        return self


class PatternConfig(BaseModel):
    time_window: int = Field(default=5, ge=1, le=60, description="Time window in minutes")
    min_pattern_occurrences: int = Field(default=3, ge=2, description="Minimum occurrences to qualify as a pattern")
    significance_threshold: float = Field(default=0.05, gt=0, lt=1, description="Statistical significance threshold")
    price_impact_threshold: float = Field(default=0.2, gt=0, description="Minimum price impact percentage")
    volume_impact_threshold: float = Field(default=1.5, gt=0, description="Minimum volume impact multiplier")
    time_shift_tolerance: int = Field(default=15, ge=1, le=60, description="Tolerance for time shifts in minutes")
    timezone: str = "Asia/Jerusalem"
    session_times: Optional[SessionTimes] = None
    parallel_processing: bool = True
    max_workers: Optional[int] = None
    cache_results: bool = True
    # Added new parameters for spatial indexing
    spatial_index_type: str = Field(default="ball_tree",
                                    description="Type of spatial index to use (ball_tree or kd_tree)")
    leaf_size: int = Field(default=30, ge=1, description="Leaf size for spatial index")

    model_config = {
        "validate_assignment": True,
        "extra": "ignore",
    }

    def export_dict(self) -> dict:
        """Non-shadowing method to dump the model as a dict."""
        return {
            "min_pattern_occurrences": self.min_pattern_occurrences,
            "price_impact_threshold": self.price_impact_threshold,
            "significance_threshold": self.significance_threshold,
            "volume_impact_threshold": self.volume_impact_threshold,
            "time_window": self.time_window,
            "time_shift_tolerance": self.time_shift_tolerance,
            "timezone": self.timezone,
            "session_times": self.session_times.model_dump() if self.session_times else None,
            "parallel_processing": self.parallel_processing,
            "max_workers": self.max_workers,
            "cache_results": self.cache_results,
            "spatial_index_type": self.spatial_index_type,
            "leaf_size": self.leaf_size
        }


class PatternResult(BaseModel):
    time: str
    session: str
    count: int = Field(..., ge=1)
    mean_price_change: float
    direction_consistency: float
    consistent_direction: str


class PatternSummary(BaseModel):
    total_patterns: int = 0
    pattern_count_by_ticker: Dict[str, int] = {}
    pattern_count_by_session: Dict[str, int] = {}
    most_consistent_patterns: List[Dict[str, Any]] = []


class ResultsSchema(BaseModel):
    recurring_patterns: Dict[str, Dict[str, Any]] = {}
    temporal_clusters: Dict[str, Any] = {}
    trend_reversals: Dict[str, List[Any]] = {}
    time_correlations: Dict[str, List[Any]] = {}
    time_shifts: Dict[str, List[Any]] = {}
    pattern_summary: Optional[PatternSummary] = None


class CircuitBreaker:
    """
    Implements the Circuit Breaker pattern to prevent cascading failures.

    Attributes:
        failure_threshold (int): Number of failures before opening the circuit
        recovery_timeout (int): Seconds to wait before attempting recovery
        timeout_factor (float): Multiplication factor for increasing timeout on consecutive failures
        failure_count (int): Current number of consecutive failures
        last_failure_time (float): Timestamp of the last failure
        state (str): Current circuit state ('closed', 'open', or 'half-open')
    """

    def __init__(self, failure_threshold: int = 3, recovery_timeout: int = 60, timeout_factor: float = 2.0):
        """Initialize the circuit breaker with configurable parameters."""
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.timeout_factor = timeout_factor
        self.failure_count = 0
        self.last_failure_time = 0
        self.state = 'closed'  # closed = normal operation, open = preventing calls, half-open = testing recovery
        self.error_history: List[Dict[str, Any]] = []
        self._max_history_size = 10

    def record_success(self) -> None:
        """Record a successful operation, resetting the failure count."""
        self.failure_count = 0
        if self.state != 'closed':
            logger.info("Circuit breaker: Resetting to closed state after success")
        self.state = 'closed'

    def record_failure(self, error: Exception, context: Optional[Dict[str, Any]] = None) -> None:
        """
        Record a failure, potentially opening the circuit.

        Args:
            error: The exception that caused the failure
            context: Optional dictionary with additional context about the failure
        """
        error_info = {
            'timestamp': datetime.now().isoformat(),
            'error_type': type(error).__name__,
            'error_message': str(error),
            'context': context or {}
        }

        # Add to history with size limit
        self.error_history.append(error_info)
        if len(self.error_history) > self._max_history_size:
            self.error_history = self.error_history[-self._max_history_size:]

        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.failure_count >= self.failure_threshold:
            if self.state != 'open':
                logger.warning(f"Circuit breaker: Opening circuit after {self.failure_count} failures")
            self.state = 'open'

    def can_execute(self) -> bool:
        """
        Check if the operation should be allowed to execute.

        Returns:
            bool: True if execution is allowed, False otherwise
        """
        if self.state == 'closed':
            return True

        # Check if recovery timeout has elapsed
        if self.state == 'open' and time.time() - self.last_failure_time > self.recovery_timeout:
            logger.info(f"Circuit breaker: Moving to half-open state after {self.recovery_timeout}s timeout")
            self.state = 'half-open'
            return True

        if self.state == 'half-open':
            logger.info("Circuit breaker: Testing in half-open state")
            return True

        return False

    def get_current_timeout(self) -> float:
        """
        Calculate the current timeout value using exponential backoff.

        Returns:
            float: Current timeout in seconds
        """
        if self.failure_count == 0:
            return 0
        return self.recovery_timeout * (self.timeout_factor ** (self.failure_count - 1))

    def get_status_report(self) -> Dict[str, Any]:
        """
        Generate a status report with the current state and history.

        Returns:
            dict: Status information about the circuit breaker
        """
        return {
            'state': self.state,
            'failure_count': self.failure_count,
            'last_failure_time': datetime.fromtimestamp(
                self.last_failure_time).isoformat() if self.last_failure_time else None,
            'current_timeout': self.get_current_timeout(),
            'error_history': self.error_history
        }


class ErrorTracker:
    """
    Tracks errors across multiple operations, providing aggregated error reporting.
    """

    def __init__(self):
        """Initialize the error tracker."""
        self.errors: Dict[str, List[Dict[str, Any]]] = {}
        self.error_counts: Dict[str, int] = {}
        self.total_operations = 0
        self.failed_operations = 0
        self.partial_failures: Dict[str, Dict[str, Any]] = {}

    def record_error(self, operation: str, error: Exception, context: Optional[Dict[str, Any]] = None) -> None:
        """
        Record an error for a specific operation.

        Args:
            operation: Name of the operation that failed
            error: The exception that was raised
            context: Optional context information about the failure
        """
        if operation not in self.errors:
            self.errors[operation] = []

        error_info = {
            'timestamp': datetime.now().isoformat(),
            'error_type': type(error).__name__,
            'error_message': str(error),
            'traceback': traceback.format_exc(),
            'context': context or {}
        }

        self.errors[operation].append(error_info)
        self.error_counts[operation] = self.error_counts.get(operation, 0) + 1
        self.failed_operations += 1

    def record_partial_failure(self, operation: str, total_parts: int, failed_parts: int,
                               details: Optional[Dict[str, Any]] = None) -> None:
        """
        Record a partial failure where some components succeeded and others failed.

        Args:
            operation: Name of the operation
            total_parts: Total number of components in the operation
            failed_parts: Number of components that failed
            details: Detailed information about the partial failure
        """
        self.partial_failures[operation] = {
            'timestamp': datetime.now().isoformat(),
            'total_parts': total_parts,
            'failed_parts': failed_parts,
            'success_rate': ((total_parts - failed_parts) / total_parts) * 100 if total_parts > 0 else 0,
            'details': details or {}
        }

    def record_operation(self, success: bool = True) -> None:
        """
        Record the execution of an operation.

        Args:
            success: Whether the operation was successful
        """
        self.total_operations += 1
        if not success:
            self.failed_operations += 1

    def get_error_summary(self) -> Dict[str, Any]:
        """
        Generate a summary of all errors recorded.

        Returns:
            dict: Error summary statistics
        """
        return {
            'total_operations': self.total_operations,
            'failed_operations': self.failed_operations,
            'success_rate': ((self.total_operations - self.failed_operations) / self.total_operations) * 100
            if self.total_operations > 0 else 0,
            'error_counts_by_operation': self.error_counts,
            'partial_failures': self.partial_failures,
            'most_common_errors': self._get_most_common_errors()
        }

    def _get_most_common_errors(self, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Identify the most common error types across all operations.

        Args:
            limit: Maximum number of error types to return

        Returns:
            list: Most common error types and their counts
        """
        error_types: Dict[str, int] = {}

        for operation, errors in self.errors.items():
            for error in errors:
                error_type = error['error_type']
                error_types[error_type] = error_types.get(error_type, 0) + 1

        sorted_errors = sorted(error_types.items(), key=lambda x: x[1], reverse=True)

        return [
            {'error_type': error_type, 'count': count}
            for error_type, count in sorted_errors[:limit]
        ]

    def generate_error_report(self) -> str:
        """
        Generate a detailed text report of all errors.

        Returns:
            str: Formatted error report
        """
        summary = self.get_error_summary()
        report = [
            "=== ERROR REPORT ===",
            f"Total operations: {summary['total_operations']}",
            f"Failed operations: {summary['failed_operations']}",
            f"Success rate: {summary['success_rate']:.2f}%",
            "\n--- MOST COMMON ERRORS ---"
        ]

        for error in summary['most_common_errors']:
            report.append(f"{error['error_type']}: {error['count']} occurrences")

        report.append("\n--- ERRORS BY OPERATION ---")
        for operation, count in summary['error_counts_by_operation'].items():
            report.append(f"{operation}: {count} errors")
            for i, error in enumerate(self.errors[operation][:3], 1):  # Show first 3 errors for each operation
                report.append(f"  {i}. {error['error_type']}: {error['error_message']}")

        report.append("\n--- PARTIAL FAILURES ---")
        for operation, details in summary['partial_failures'].items():
            report.append(f"{operation}: {details['failed_parts']}/{details['total_parts']} parts failed "
                          f"({details['success_rate']:.2f}% success)")

        return "\n".join(report)

    def write_error_report(self, output_dir: str) -> Optional[str]:
        """
        Write the error report to a file.

        Args:
            output_dir: Directory to write the report to

        Returns:
            Optional[str]: Path to the error report file, or None if there was an error
        """
        os.makedirs(output_dir, exist_ok=True)
        report_path = os.path.join(output_dir, f"error_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")

        try:
            with open(report_path, 'w') as f:
                f.write(self.generate_error_report())
            return report_path
        except Exception as e:
            logger.error(f"Failed to write error report: {e}")
            return None

# -------------------------
# Time Conversion Utilities
# -------------------------
# Global time cache for faster lookups
_TIME_STRING_CACHE: Dict[str, int] = {}


def time_string_to_minutes(time_str: str) -> int:
    """
    Convert time string to minutes since midnight with caching.

    Args:
        time_str: Time string in 'HH:MM' format

    Returns:
        int: Minutes since midnight
    """
    if time_str in _TIME_STRING_CACHE:
        return _TIME_STRING_CACHE[time_str]

    time_obj = datetime.strptime(time_str, '%H:%M')
    minutes = time_obj.hour * 60 + time_obj.minute
    _TIME_STRING_CACHE[time_str] = minutes
    return minutes


def extract_time_minutes(datetime_obj) -> int:
    """
    Extract time in minutes since midnight from a datetime object.

    Args:
        datetime_obj: Datetime object

    Returns:
        int: Minutes since midnight
    """
    return datetime_obj.hour * 60 + datetime_obj.minute


# Apply numba JIT compilation for speed
@numba.jit(nopython=True)
def calculate_time_difference(time1_minutes: int, time2_minutes: int, wrap_around: bool = True) -> int:
    """
    Calculate difference between two times in minutes, optionally handling overnight wrapping.

    Args:
        time1_minutes: First time in minutes since midnight
        time2_minutes: Second time in minutes since midnight
        wrap_around: Whether to handle overnight wrapping (default: True)

    Returns:
        int: Time difference in minutes
    """
    diff = abs(time1_minutes - time2_minutes)
    if wrap_around:
        # Handle overnight wrapping
        return min(diff, 1440 - diff)  # 1440 = 24*60 minutes in a day
    return diff


# -------------------------
# JSON & Serialization
# -------------------------
def create_json_encoder() -> Type[json.JSONEncoder]:
    """
    Create a custom JSON encoder that can handle NumPy and Pandas types.
    """
    class CustomEncoder(json.JSONEncoder):
        def default(self, obj: Any) -> Any:
            if isinstance(obj, (np.integer, np.floating, np.bool_)):
                return obj.item()
            if isinstance(obj, np.ndarray):
                return obj.tolist()
            if isinstance(obj, (pd.Timestamp, datetime)):
                return obj.isoformat()
            if isinstance(obj, pd.Series):
                return obj.tolist()
            if isinstance(obj, pd.DataFrame):
                return obj.to_dict('records')
            # Add handling for date objects
            if isinstance(obj, datetime.date):
                return obj.isoformat()
            return super().default(obj)

    return CustomEncoder


def safe_write_json(data: Any, file_path: str, indent: int = 2) -> bool:
    """
    Safely write JSON data to a file, with enhanced Python 3.13 compatibility.
    """
    return safe_json_dump(data, file_path, indent)


# -------------------------
# CLI Argument Parsing
# -------------------------
def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Analyze temporal market patterns in stock data.")
    parser.add_argument("--input", type=str, required=True, help="Path to input CSV file with cleaned data")
    parser.add_argument("--output", type=str, default="pattern_analysis_results", help="Directory for output files")
    parser.add_argument("--config", type=str, help="Path to configuration JSON file")
    parser.add_argument("--tickers", type=str, help="Comma-separated list of tickers to analyze (default: all)")
    parser.add_argument("--visualize", action="store_true", help="Generate visualizations")
    parser.add_argument("--report_template", type=str, help="Path to custom HTML report template")
    parser.add_argument("--incremental", action="store_true", help="Enable incremental analysis")
    parser.add_argument("--cache_dir", type=str, default=".cache", help="Directory for caching intermediate results")
    return parser.parse_args()


def load_config(config_path: Optional[str] = None) -> PatternConfig:
    """
    Load and validate configuration from JSON file using Pydantic.
    """
    if config_path is None:
        logger.info("Using default configuration")
        return PatternConfig()
    try:
        with open(config_path, 'r') as f:
            config_data = json.load(f)
            logger.info(f"Loaded configuration from {config_path}")
            if "pattern_detector" in config_data:
                config_data = config_data["pattern_detector"]
            return PatternConfig.model_validate(config_data)
    except json.JSONDecodeError as json_exc:
        logger.error(f"Error parsing config file: {json_exc}")
        logger.info("Using default configuration")
        return PatternConfig()
    except Exception as external:
        logger.error(f"Error loading config file: {external}")
        logger.error(traceback.format_exc())
        logger.info("Using default configuration")
        return PatternConfig()


# -------------------------
# Data Validation & Filters
# -------------------------
def validate_input_data(data: pd.DataFrame) -> bool:
    """
    Validate the input data structure and format.
    """
    required_cols = ['Ticker', 'Datetime', 'Open', 'High', 'Low', 'Close', 'Volume']
    missing_cols = [col for col in required_cols if col not in data.columns]
    if missing_cols:
        logger.error(f"Missing required columns: {missing_cols}")
        return False

    try:
        # Enhanced datetime conversion with error handling
        if 'Datetime' in data.columns:
            # Check if it's already a datetime type
            if not pd.api.types.is_datetime64_any_dtype(data['Datetime']):
                # Try to convert to datetime
                try:
                    data['Datetime'] = pd.to_datetime(data['Datetime'])
                    logger.info("Successfully converted Datetime column to datetime type")
                except Exception as e:
                    logger.error(f"Failed to convert Datetime column: {e}")
                    return False

            # Extract date and time components for later use
            # This ensures .dt accessor will work later
            data['Date'] = data['Datetime'].dt.date
            data['Time'] = data['Datetime'].dt.time
            logger.info("Added Date and Time columns from Datetime")
    except Exception as conv_err:
        logger.error(f"Error processing Datetime column: {conv_err}")
        return False

    # Check for missing values in critical columns
    critical_cols = ['Ticker', 'Datetime', 'Close', 'Volume']
    for col in critical_cols:
        if data[col].isna().any():
            logger.warning(f"Column '{col}' contains missing values.")

    if len(data) < 100:
        logger.warning("Dataset may be too small for meaningful pattern detection.")

    return True


def filter_data_by_tickers(data: pd.DataFrame, tickers: Optional[List[str]] = None) -> pd.DataFrame:
    """
    Filter data to include only specified tickers.
    """
    if not tickers:
        return data
    available_tickers = set(data['Ticker'].unique())
    requested_tickers = set(tickers)
    missing_tickers = requested_tickers - available_tickers
    if missing_tickers:
        logger.warning(f"Requested tickers not found in data: {missing_tickers}")
    return data[data['Ticker'].isin(tickers)]


# -------------------------
# Optimized Time-Shifted Pattern Detection
# -------------------------
def build_spatial_index(data: pd.DataFrame, config: Dict[str, Any]) -> Tuple[Any, np.ndarray, np.ndarray]:
    """
    Build a spatial index (KDTree or BallTree) from time and price features.

    Args:
        data: DataFrame containing data for pattern detection
        config: Configuration dictionary

    Returns:
        Tuple containing:
        - Spatial index (KDTree or BallTree)
        - Feature array used for indexing
        - Array of indices mapping back to original data
    """
    # Extract time as minutes since midnight
    data['time_minutes'] = data['Datetime'].apply(
        lambda dt: dt.hour * 60 + dt.minute
    ).values

    # Create feature array with time and normalized price/volume
    features = np.column_stack([
        data['time_minutes'],
        (data['Close'] - data['Close'].mean()) / data['Close'].std()
    ])

    # Build the appropriate spatial index
    if config.get('spatial_index_type', 'ball_tree').lower() == 'kd_tree':
        tree = KDTree(features, leaf_size=config.get('leaf_size', 30))
    else:
        tree = BallTree(features, leaf_size=config.get('leaf_size', 30))

    return tree, features, np.arange(len(data))


def detect_time_shifted_patterns_optimized(
        data: pd.DataFrame,
        config: Dict[str, Any]
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Detect time-shifted patterns using spatial indexing for O(n log n) complexity.

    Args:
        data: DataFrame containing data for pattern detection
        config: Configuration dictionary

    Returns:
        Dictionary mapping ticker symbols to lists of detected time-shifted patterns
    """

    # Helper function for safe division
    def safe_divide(numerator, denominator, default=0.0):
        """Safely divide numbers handling zero denominators."""
        if not (isinstance(numerator, (int, float, np.number)) and
                isinstance(denominator, (int, float, np.number))):
            return default
        return numerator / denominator if denominator != 0 else default

    results = {}
    tickers = data['Ticker'].unique()

    for ticker in tickers:
        ticker_data = data[data['Ticker'] == ticker].sort_values('Datetime').reset_index(drop=True)

        # Skip if insufficient data
        if len(ticker_data) < config.get('min_pattern_occurrences', 3):
            results[ticker] = []
            continue

        # Build spatial index from time and price features
        tree, features, indices = build_spatial_index(ticker_data, config)

        # Parameters for pattern detection
        time_tolerance = config.get('time_shift_tolerance', 15)
        min_occurrences = config.get('min_pattern_occurrences', 3)
        price_threshold = config.get('price_impact_threshold', 0.2)

        # Query the tree for each point to find nearby points within time tolerance
        ticker_patterns = []

        # Convert time tolerance to feature space distance
        # We'll use minutes directly for the time dimension
        time_radius = time_tolerance

        # For each data point, find points that occur at similar times
        for i, (_, row) in enumerate(ticker_data.iterrows()):
            # Get the time in minutes
            time_minutes = row['time_minutes']

            # Query the tree for points within time_radius
            # We're using the time_radius as a distance threshold in the feature space
            indices_within_radius = tree.query_radius(
                features[i:i + 1],
                r=time_radius
            )[0]

            # Filter out points that are the same or too close in actual date
            # This prevents matching the same pattern occurrence
            valid_indices = []
            base_date = row['Datetime'].date()

            for idx in indices_within_radius:
                comp_date = ticker_data.loc[idx, 'Datetime'].date()
                # Only include if dates are different
                if comp_date != base_date:
                    valid_indices.append(idx)

            # If we have enough occurrences to form a pattern
            if len(valid_indices) >= min_occurrences - 1:  # -1 because we're already counting the current point
                # Calculate price changes after the pattern
                future_window = 5  # Look ahead window

                # Calculate price impact for the current point safely
                current_idx = i
                current_change = 0.0  # Default value
                if current_idx + future_window < len(ticker_data):
                    current_price = ticker_data.loc[current_idx, 'Close']
                    future_price = ticker_data.loc[current_idx + future_window, 'Close']

                    # Skip calculation if any price is NaN or zero
                    if pd.notna(current_price) and pd.notna(future_price) and current_price != 0:
                        current_change = (future_price - current_price) / current_price * 100

                # Calculate price impacts for matched points
                changes = [current_change]
                valid_indices_with_future = []

                for idx in valid_indices:
                    if idx + future_window < len(ticker_data):
                        current_price = ticker_data.loc[idx, 'Close']
                        future_price = ticker_data.loc[idx + future_window, 'Close']

                        # Skip calculation if any price is NaN or zero
                        if pd.notna(current_price) and pd.notna(future_price) and current_price != 0:
                            change = (future_price - current_price) / current_price * 100
                            changes.append(change)
                            valid_indices_with_future.append(idx)

                # Filter out NaN values before calculations
                changes = [c for c in changes if pd.notna(c)]

                # Only create pattern if we have enough valid points with future data
                if len(changes) >= min_occurrences:
                    # Check for direction consistency
                    positive_count = sum(1 for c in changes if c > 0)
                    negative_count = sum(1 for c in changes if c < 0)
                    total_count = len(changes)

                    # Use safe division to avoid divide by zero
                    direction_consistency = safe_divide(max(positive_count, negative_count), total_count)
                    consistent_direction = "up" if positive_count >= negative_count else "down"

                    # Magnitude check - use numpy's nanmean to safely handle any NaN values
                    mean_change = np.nanmean(changes) if changes else 0

                    if (abs(mean_change) >= price_threshold and
                            direction_consistency >= 0.7):  # At least 70% consistent

                        # Format the pattern time (HH:MM)
                        pattern_time = f"{time_minutes // 60:02d}:{time_minutes % 60:02d}"

                        pattern = {
                            "time": pattern_time,
                            "occurrences": len(changes),
                            "mean_price_change": float(mean_change),
                            "direction_consistency": float(direction_consistency),
                            "consistent_direction": consistent_direction,
                            "sample_dates": [
                                ticker_data.loc[idx, 'Datetime'].date().isoformat()
                                for idx in valid_indices_with_future[:5]  # Limit to 5 examples
                            ]
                        }
                        ticker_patterns.append(pattern)

        # Sort patterns by consistency and occurrences
        ticker_patterns.sort(
            key=lambda p: (p["direction_consistency"], p["occurrences"]),
            reverse=True
        )

        # Remove duplicates (patterns at very similar times)
        unique_patterns = []
        used_times = set()

        for pattern in ticker_patterns:
            pattern_time = pattern["time"]
            pattern_minutes = time_string_to_minutes(pattern_time)

            # Check if we already have a similar pattern time
            similar_exists = False
            for used_time in used_times:
                used_minutes = time_string_to_minutes(used_time)
                if abs(pattern_minutes - used_minutes) <= 10:  # 10 minutes tolerance for duplicate removal
                    similar_exists = True
                    break

            if not similar_exists:
                unique_patterns.append(pattern)
                used_times.add(pattern_time)

        results[ticker] = unique_patterns

    return results


# -------------------------
# Core Analysis Functions
# -------------------------
def process_ticker(ticker_symbol: str,
                   ticker_data: pd.DataFrame,
                   detector: PatternDetector) -> Dict[str, Any]:
    """
    Process analysis for a single ticker.

    Args:
        ticker_symbol: Stock ticker symbol
        ticker_data: DataFrame containing ticker data
        detector: PatternDetector instance

    Returns:
        Dictionary with analysis results
    """
    logger.info(f"Processing ticker: {ticker_symbol} with {len(ticker_data)} data points")
    try:
        # Convert time strings to integers for faster comparison during processing
        if 'Datetime' in ticker_data.columns and not 'time_minutes' in ticker_data.columns:
            ticker_data['time_minutes'] = ticker_data['Datetime'].apply(
                lambda dt: dt.hour * 60 + dt.minute
            )

        preprocessed_data = detector.preprocess_for_pattern_detection(ticker_data)
        recurring_patterns = detector.detect_recurring_patterns(preprocessed_data)
        temporal_clusters = detector.detect_temporal_clusters(preprocessed_data)
        trend_reversals = detector.identify_trend_reversals(preprocessed_data)
        time_correlations = detector.analyze_time_correlations(preprocessed_data)

        # Use the optimized time-shifted pattern detection
        config_dict = detector.config if hasattr(detector, 'config') else {}
        time_shifts = detect_time_shifted_patterns_optimized(preprocessed_data, config_dict)

        ticker_results = {
            "recurring_patterns": recurring_patterns.get(ticker_symbol, {}),
            "temporal_clusters": temporal_clusters.get(ticker_symbol, {}),
            "trend_reversals": trend_reversals.get(ticker_symbol, []),
            "time_correlations": time_correlations.get(ticker_symbol, []),
            "time_shifts": time_shifts.get(ticker_symbol, [])
        }
        return ticker_results
    except Exception as error:
        logger.error(f"Error processing ticker {ticker_symbol}: {error}")
        logger.error(traceback.format_exc())
        return {
            "error": str(error),
            "recurring_patterns": {},
            "temporal_clusters": {},
            "trend_reversals": [],
            "time_correlations": [],
            "time_shifts": []
        }


def incorporate_ticker_results(results_dict: Dict[str, Any],
                               ticker_symbol: str,
                               ticker_results: Dict[str, Any]) -> None:
    """
    Incorporate ticker results into the main results dictionary.
    """
    for key_type in results_dict:
        if key_type in ticker_results:
            if key_type in ["recurring_patterns", "temporal_clusters"]:
                results_dict[key_type][ticker_symbol] = ticker_results[key_type]
            elif key_type in ["trend_reversals", "time_correlations", "time_shifts"]:
                results_dict[key_type][ticker_symbol] = ticker_results[key_type]


def validate_results_schema(results: Dict[str, Any]) -> bool:
    """
    Validate the results dictionary against the Pydantic schema.
    """
    try:
        ResultsSchema.model_validate(results)
        logger.info("Results schema validation passed.")
        return True
    except Exception as external:
        logger.error(f"Results schema validation failed: {external}")
        return False


def save_results(results: Dict[str, Any], output_dir: str) -> None:
    """
    Save analysis results to JSON files, with schema validation.
    """
    os.makedirs(output_dir, exist_ok=True)
    if not validate_results_schema(results):
        logger.warning("Results did not pass schema validation. Saving anyway...")
    for result_type, result_data in results.items():
        file_path = os.path.join(output_dir, f"{result_type}.json")
        if safe_write_json(result_data, file_path):
            logger.info(f"Saved {result_type} to {file_path}")
        else:
            logger.error(f"Failed to save {result_type} to {file_path}")


# -------------------------
# Optimized Data Processing
# -------------------------
def preprocess_data_vectorized(data: pd.DataFrame) -> pd.DataFrame:
    """
    Vectorized preprocessing of data for pattern detection.
    """
    # Make a copy to avoid modifying the original
    result = data.copy()

    # Ensure Datetime is properly converted
    if 'Datetime' in result.columns:
        if not pd.api.types.is_datetime64_any_dtype(result['Datetime']):
            result['Datetime'] = pd.to_datetime(result['Datetime'])

        # Add Date and Time columns if they don't exist
        if 'Date' not in result.columns:
            result['Date'] = result['Datetime'].dt.date
        if 'Time' not in result.columns:
            result['Time'] = result['Datetime'].dt.time

        # Convert time strings to minutes for faster comparison
        if 'time_minutes' not in result.columns:
            # Use a safer approach to extract hour and minute
            result['time_minutes'] = result['Datetime'].dt.hour * 60 + result['Datetime'].dt.minute
            logger.info(
                f"Added time_minutes column with range: {result['time_minutes'].min()}-{result['time_minutes'].max()}")

    # Vectorized calculation of returns
    result['returns'] = result.groupby('Ticker')['Close'].pct_change() * 100

    # Rest of the existing code...
    # [keep the remaining function implementation unchanged]

    return result


# -------------------------
# Caching Logic
# -------------------------
def load_or_create_cache_key(data: pd.DataFrame,
                             config_obj: PatternConfig,
                             cache_dir: str,
                             ticker_symbol: Optional[str] = None) -> str:
    """
    Generate a secure cache key based on data characteristics and configuration.

    Args:
        data (pandas.DataFrame): Input data
        config_obj (PatternConfig): Configuration
        cache_dir (str): Directory for caching
        ticker_symbol (Optional[str]): Specific ticker (default None)

    Returns:
        str: Secure SHA-256 cache key
    """
    os.makedirs(cache_dir, exist_ok=True)
    try:
        data_stats = {
            "rows": len(data),
            "tickers": len(data['Ticker'].unique()),
            "columns": list(data.columns),
            "start_date": data['Datetime'].min().isoformat(),
            "end_date": data['Datetime'].max().isoformat()
        }
        sample_data = data.head(100).to_json(orient='records')
    except AttributeError as attr_err:
        logger.error(f"Error creating data stats: {attr_err}")
        data_stats = {
            "rows": len(data),
            "columns": list(data.columns)
        }
        sample_data = str(data.shape)
    import hashlib
    config_json = json.dumps(config_obj.export_dict(), sort_keys=True)
    data_json = json.dumps(data_stats, sort_keys=True)
    base_source = f"{data_json}_{config_json}"
    if ticker_symbol:
        base_source += f"_{ticker_symbol}"
    content_to_hash = base_source + sample_data
    cache_key = hashlib.sha256(content_to_hash.encode()).hexdigest()
    key_file = os.path.join(cache_dir, "cache_keys.json")
    key_mapping = {}
    if os.path.exists(key_file):
        try:
            with open(key_file, 'r') as fh:
                key_mapping = json.load(fh)
        except json.JSONDecodeError as json_exc:
            logger.warning(f"Could not parse cache keys file: {json_exc}")
        except IOError as io_exc:
            logger.warning(f"Could not read cache keys file: {io_exc}")
    key_mapping[cache_key] = {
        "created": datetime.now().isoformat(),
        "data_stats": data_stats,
        "config": config_obj.export_dict(),
        "ticker": ticker_symbol if ticker_symbol else "all"
    }
    safe_write_json(key_mapping, key_file)
    return cache_key


def check_cache(cache_key: str, ticker_symbol: str, cache_dir: str) -> Optional[Dict[str, Any]]:
    """
    Check if results for a ticker are in the cache.
    """
    cache_file = os.path.join(cache_dir, f"{cache_key}_{ticker_symbol}.json")
    if os.path.exists(cache_file):
        try:
            with open(cache_file, 'r') as fh:
                cached_data = json.load(fh)
                logger.info(f"Using cached results for {ticker_symbol}")
                return cached_data
        except json.JSONDecodeError as json_exc:
            logger.warning(f"Error parsing cache for {ticker_symbol}: {json_exc}")
        except IOError as io_exc:
            logger.warning(f"Error reading cache for {ticker_symbol}: {io_exc}")
    return None


def save_to_cache(cache_key: str, ticker_symbol: str,
                  results_data: Dict[str, Any],
                  cache_dir: str) -> None:
    """
    Save ticker results to cache.
    """
    cache_file = os.path.join(cache_dir, f"{cache_key}_{ticker_symbol}.json")
    if safe_write_json(results_data, cache_file):
        logger.debug(f"Cached results for {ticker_symbol}")
    else:
        logger.warning(f"Error caching results for {ticker_symbol}")


# -------------------------
# Reporting
# -------------------------
def generate_html_report(
        results: Dict[str, Any],
        visualizations: Dict[str, str],
        output_dir: str,
        template_path: Optional[str] = None
) -> Optional[str]:
    """
    Generate an HTML report from analysis results using Jinja2 if available.

    Args:
        results: Dictionary containing analysis results
        visualizations: Dictionary mapping visualization names to file paths
        output_dir: Directory to save the report
        template_path: Optional path to a custom Jinja2 template

    Returns:
        Optional path to the generated report
    """
    report_path = os.path.join(output_dir, "pattern_analysis_report.html")
    pattern_summary = results.get("pattern_summary", {})
    recurring_patterns = results.get("recurring_patterns", {})

    try:
        # First, check if Jinja2 is available at all
        import jinja2
    except ImportError:
        logger.warning("Jinja2 not available. Falling back to legacy HTML method.")
        return generate_html_report_legacy(results, visualizations, output_dir)

    # If we get here, Jinja2 is available
    try:
        from jinja2 import Environment, FileSystemLoader, select_autoescape

        # Define basename filter function
        def basename_filter(path_str: str) -> str:
            """Extract basename from path."""
            return os.path.basename(path_str) if path_str else ""

        # Set up the Jinja2 environment based on template path
        if template_path and os.path.exists(template_path):
            logger.info(f"Using custom Jinja2 template from {template_path}")
            template_dir = os.path.dirname(template_path)
            template_file = os.path.basename(template_path)
            env = Environment(
                loader=FileSystemLoader(template_dir),
                autoescape=select_autoescape(['html', 'xml'])
            )
            template = env.get_template(template_file)
        else:
            # Default template text (abbreviated here)
            default_template = """<!DOCTYPE html>
                <html>
                <head>
                    <title>Market Pattern Analysis Report</title>
                    <style>
                        /* CSS styles would go here */
                    </style>
                </head>
                <body>
                    <div class="container">
                        <h1>Market Pattern Analysis Report</h1>
                        <p>Generated on: {{ generated_date }}</p>

                        <!-- ... rest of template content ... -->
                    </div>
                </body>
                </html>"""

            # Create environment without a loader
            env = Environment(autoescape=select_autoescape(['html', 'xml']))
            template = env.from_string(default_template)

        # Register filters
        env.filters['basename'] = basename_filter

        # Prepare context data for template
        context = {
            'generated_date': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'pattern_summary': pattern_summary,
            'recurring_patterns': recurring_patterns,
            'visualizations': visualizations,
            'most_consistent_patterns': pattern_summary.get('most_consistent_patterns', [])[:10]
        }

        # Render the template
        html_content = template.render(**context)

        # Write to file
        with open(report_path, 'w') as f:
            f.write(html_content)

        logger.info(f"Generated HTML report at {report_path}")
        return report_path

    except Exception as error:
        logger.error(f"Error generating HTML report: {error}")
        logger.error(traceback.format_exc())
        return None


def generate_html_report_legacy(results: Dict[str, Any],
                                visualizations: Dict[str, str],
                                output_dir: str) -> Optional[str]:
    """
    Legacy HTML report generation without Jinja2.

    Args:
        results: Dictionary containing analysis results
        visualizations: Dictionary mapping visualization names to file paths
        output_dir: Directory to save the report

    Returns:
        Optional path to the generated report
    """
    report_path = os.path.join(output_dir, "pattern_analysis_report.html")
    try:
        # Simple HTML generation without Jinja2
        with open(report_path, 'w') as f:
            f.write("<!DOCTYPE html>\n<html>\n<head>\n")
            f.write("  <title>Market Pattern Analysis Report (Legacy)</title>\n")
            f.write("</head>\n<body>\n")
            f.write("  <h1>Market Pattern Analysis Report</h1>\n")
            f.write(f"  <p>Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>\n")

            # Add basic result summary
            pattern_summary = results.get("pattern_summary", {})
            total_patterns = pattern_summary.get("total_patterns", 0)
            f.write(f"  <p>Total patterns detected: {total_patterns}</p>\n")

            # List visualizations if any
            if visualizations:
                f.write("  <h2>Visualizations</h2>\n  <ul>\n")
                for viz_name, viz_path in visualizations.items():
                    viz_file = os.path.basename(viz_path)
                    f.write(f"    <li><a href='{viz_file}'>{viz_name}</a></li>\n")
                f.write("  </ul>\n")

            f.write("</body>\n</html>")

        logger.info(f"Generated legacy HTML report at {report_path}")
        return report_path
    except Exception as error:
        logger.error(f"Error generating legacy HTML report: {error}")
        logger.error(traceback.format_exc())
        return None


# -------------------------
# Progress Display
# -------------------------
def show_progress(completed: int, total: int, start_time: float) -> None:
    """
    Display progress information.
    """
    if total == 0:
        return
    percent = (completed / total) * 100
    elapsed = time.time() - start_time
    if completed > 0:
        estimated_total = (elapsed / completed) * total
        remaining = estimated_total - elapsed
        eta_minutes = remaining / 60
        logger.info(f"Progress: {completed}/{total} ({percent:.1f}%) - ETA: {eta_minutes:.1f} minutes")
    else:
        logger.info(f"Progress: {completed}/{total} ({percent:.1f}%)")


def retry_with_backoff(max_retries: int = 3,
                       initial_backoff: float = 1.0,
                       backoff_factor: float = 2.0,
                       max_backoff: float = 60.0,
                       jitter: bool = True) -> Callable:
    """
    Decorator for retrying functions with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts
        initial_backoff: Initial backoff time in seconds
        backoff_factor: Multiplier for backoff time on consecutive failures
        max_backoff: Maximum backoff time in seconds
        jitter: Whether to add randomness to the backoff time

    Returns:
        Callable: Decorator function
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            backoff = initial_backoff

            for attempt in range(max_retries + 1):  # +1 to include the first attempt
                try:
                    if attempt > 0:
                        logger.info(f"Retry attempt {attempt}/{max_retries} for {func.__name__} after {backoff:.2f}s")
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt == max_retries:
                        # Log the final failure before re-raising
                        logger.error(f"All {max_retries} retries failed for {func.__name__}: {e}")
                        raise

                    # Log the failure but prepare to retry
                    logger.warning(f"Error in {func.__name__} (attempt {attempt + 1}/{max_retries}): {e}")

                    # Calculate next backoff time
                    backoff = min(backoff * backoff_factor, max_backoff)

                    # Add jitter if enabled (±15%)
                    if jitter:
                        backoff = backoff * random.uniform(0.85, 1.15)

                    # Wait before retrying
                    time.sleep(backoff)

            # This should not be reached due to the final raise, but just in case
            raise last_exception

        return wrapper

    return decorator


def safe_data_handler(default_return: Any = None,
                      partial_results: bool = True,
                      error_logger: Optional[ErrorTracker] = None) -> Callable:
    """
    Decorator for functions that process data, allowing graceful degradation.

    Args:
        default_return: Default value to return if the function fails completely
        partial_results: Whether to return partial results if possible
        error_logger: Optional ErrorTracker to record errors

    Returns:
        Callable: Decorator function
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            function_name = func.__name__
            try:
                return func(*args, **kwargs)
            except Exception as e:
                # Log the error
                logger.error(f"Error in {function_name}: {e}")
                logger.error(traceback.format_exc())

                # Record in error tracker if provided
                if error_logger is not None:
                    context = {
                        'args': str(args),
                        'kwargs': str(kwargs),
                        'function': function_name
                    }
                    error_logger.record_error(function_name, e, context)

                # Try to extract partial results if enabled
                if partial_results:
                    try:
                        # This requires knowledge of the function's structure
                        # For example, if the first argument is the main data
                        if args and hasattr(args[0], 'copy'):
                            partial_data = args[0].copy()
                            logger.info(f"Returning partial data from {function_name} ({len(partial_data)} rows)")

                            # Record partial failure if we have an error tracker
                            if error_logger is not None:
                                error_logger.record_partial_failure(
                                    function_name,
                                    total_parts=1,  # Simplified; actual implementation would count components
                                    failed_parts=1,
                                    details={'partial_data_size': len(partial_data)}
                                )

                            return partial_data
                    except Exception as partial_err:
                        logger.warning(f"Could not extract partial results: {partial_err}")

                # Return default if all else fails
                logger.warning(f"Returning default value from {function_name}")
                return default_return

        return wrapper

    return decorator


# -------------------------
# Data Recovery and Validation
# -------------------------

def recover_missing_data(data: pd.DataFrame,
                         column: str,
                         method: str = 'interpolate',
                         max_gap: int = 5,
                         fill_value: Optional[Any] = None) -> pd.DataFrame:
    """
    Recover missing values in a dataframe column.

    Args:
        data: Input DataFrame
        column: Column name to process
        method: Method for filling gaps ('interpolate', 'ffill', 'bfill', or 'value')
        max_gap: Maximum size of gap to fill (in number of rows)
        fill_value: Value to use when method is 'value'

    Returns:
        pandas.DataFrame: DataFrame with recovered data
    """
    if column not in data.columns:
        logger.warning(f"Column '{column}' not found in dataframe")
        return data

    result = data.copy()

    if not result[column].isna().any():
        return result  # No missing values to fill

    # Identify gaps (consecutive NaN values)
    is_null = result[column].isna()
    null_groups = is_null.ne(is_null.shift()).cumsum()
    null_counts = null_groups.map(null_groups.value_counts())

    # Create mask for gaps we want to fill (smaller than max_gap)
    fillable_mask = is_null & (null_counts <= max_gap)

    # Only try to fill values within the fillable mask
    if fillable_mask.any():
        temp_df = result.copy()

        if method == 'interpolate':
            # Only interpolate within the fillable gaps
            temp_series = temp_df.loc[fillable_mask, column]
            if isinstance(temp_series.index, pd.DatetimeIndex):
                filled_values = temp_df[column].interpolate(method='time')
            else:
                filled_values = temp_df[column].interpolate(method='linear')
            result.loc[fillable_mask, column] = filled_values.loc[fillable_mask]

        elif method == 'ffill':
            # Forward fill within max_gap
            for group_id in null_groups.loc[fillable_mask].unique():
                group_mask = null_groups == group_id
                if isinstance(group_mask, (pd.Series, pd.DataFrame)) and group_mask.any().any() and null_counts.loc[group_mask].iloc[0] <= max_gap:
                    result.loc[group_mask, column] = result.loc[group_mask, column].ffill()

        elif method == 'bfill':
            # Backward fill within max_gap
            for group_id in null_groups.loc[fillable_mask].unique():
                group_mask = null_groups == group_id
                if isinstance(group_mask, (pd.Series, pd.DataFrame)) and group_mask.any().any() and null_counts.loc[group_mask].iloc[0] <= max_gap:
                    result.loc[group_mask, column] = result.loc[group_mask, column].bfill()

        elif method == 'value':
            # Fill with specified value
            result.loc[fillable_mask, column] = fill_value

        # Log the recovery
        filled_count = fillable_mask.sum()
        total_null = is_null.sum()
        logger.info(f"Recovered {filled_count}/{total_null} missing values in column '{column}' using {method}")

    return result


def recover_ticker_data(ticker_data: pd.DataFrame,
                        config: Dict[str, Any],
                        error_tracker: Optional[ErrorTracker] = None) -> Tuple[pd.DataFrame, bool]:
    """
    Attempt to recover and validate ticker data with missing or problematic values.

    Args:
        ticker_data: DataFrame containing data for a specific ticker
        config: Configuration dictionary
        error_tracker: Optional error tracking object

    Returns:
        tuple: (Recovered DataFrame, boolean indicating if data is usable)
    """
    # Create a default empty DataFrame with required columns to handle None cases
    default_columns = ['Ticker', 'Datetime', 'Close', 'Volume', 'Open', 'High', 'Low']
    empty_df = pd.DataFrame(columns=default_columns)

    if ticker_data is None:
        logger.warning("None ticker data provided to recovery function")
        return empty_df, False

    if len(ticker_data) == 0:
        logger.warning("Empty ticker data provided to recovery function")
        return ticker_data.copy() if isinstance(ticker_data, pd.DataFrame) else empty_df, False

    # Make sure ticker_data is a DataFrame to avoid type issues
    if not isinstance(ticker_data, pd.DataFrame):
        logger.warning(f"Invalid ticker data type: {type(ticker_data)}. Expected DataFrame.")
        return empty_df, False

    ticker_symbol = ticker_data['Ticker'].iloc[0] if 'Ticker' in ticker_data.columns else "UNKNOWN"

    # Track missing values before recovery
    total_rows = len(ticker_data)
    missing_before = {}
    recovered_data = ticker_data.copy()

    try:
        # Identify critical and non-critical columns
        critical_cols = ['Ticker', 'Datetime', 'Close']
        numerical_cols = ['Open', 'High', 'Low', 'Close', 'Volume']

        # Check for missing values in critical columns
        for col in critical_cols:
            if col in recovered_data.columns:
                missing_count = recovered_data[col].isna().sum()
                missing_before[col] = missing_count
                missing_pct = (missing_count / total_rows) * 100

                if missing_count > 0:
                    logger.warning(
                        f"Ticker {ticker_symbol}: {missing_count} missing values ({missing_pct:.2f}%) in critical column '{col}'")

                    # We don't try to recover Ticker or Datetime columns
                    if col not in ['Ticker', 'Datetime'] and missing_count < total_rows * 0.25:  # Less than 25% missing
                        recovery_method = 'interpolate' if col != 'Volume' else 'ffill'
                        max_gap = 3 if col != 'Volume' else 5  # Different gap sizes based on column
                        recovered_data = recover_missing_data(
                            recovered_data, col, method=recovery_method, max_gap=max_gap
                        )

        # Handle numerical columns
        for col in numerical_cols:
            if col in recovered_data.columns and col not in critical_cols:
                missing_count = recovered_data[col].isna().sum()
                missing_before[col] = missing_count

                if missing_count > 0:
                    recovery_method = 'interpolate'
                    if col == 'Volume':
                        recovery_method = 'ffill'

                    recovered_data = recover_missing_data(
                        recovered_data, col, method=recovery_method, max_gap=5
                    )

        # Ensure Open/High/Low/Close consistency
        if all(col in recovered_data.columns for col in ['Open', 'High', 'Low', 'Close']):
            # Ensure High is the highest value
            recovered_data['High'] = recovered_data[['Open', 'High', 'Low', 'Close']].max(axis=1)

            # Ensure Low is the lowest value
            recovered_data['Low'] = recovered_data[['Open', 'High', 'Low', 'Close']].min(axis=1)

        # Final validation check
        critical_cols_missing = any(
            recovered_data[col].isna().any() for col in critical_cols if col in recovered_data.columns)
        data_usable = not critical_cols_missing and len(recovered_data) >= config.get('min_pattern_occurrences', 3)

        if error_tracker is not None:
            # Calculate recovery statistics
            missing_after = {col: recovered_data[col].isna().sum() for col in missing_before.keys()}
            recovered_values = {col: missing_before[col] - missing_after[col] for col in missing_before.keys()}

            recovery_details = {
                'ticker': ticker_symbol,
                'total_rows': total_rows,
                'missing_before': missing_before,
                'missing_after': missing_after,
                'recovered_values': recovered_values,
                'data_usable': data_usable
            }

            # Record as a partial failure if we couldn't recover everything
            if any(count > 0 for count in missing_after.values()):
                failed_parts = sum(1 for count in missing_after.values() if count > 0)
                total_parts = len(missing_after)

                error_tracker.record_partial_failure(
                    f"ticker_data_recovery_{ticker_symbol}",
                    total_parts=total_parts,
                    failed_parts=failed_parts,
                    details=recovery_details
                )

        return recovered_data, data_usable

    except Exception as e:
        logger.error(f"Error recovering data for ticker {ticker_symbol}: {e}")
        logger.error(traceback.format_exc())

        if error_tracker is not None:
            error_tracker.record_error(
                f"recover_ticker_data_{ticker_symbol}",
                e,
                {'ticker': ticker_symbol, 'data_rows': len(ticker_data)}
            )

        # Return a copy of the original data to ensure we don't return None
        return ticker_data.copy(), False  # Always return a DataFrame, never None


# Apply the improved error handling to the main process_ticker function
@retry_with_backoff(max_retries=2, initial_backoff=2.0)
def process_ticker_robust(ticker_symbol: str,
                          ticker_data: pd.DataFrame,
                          detector: PatternDetector,
                          circuit_breaker: CircuitBreaker,
                          error_tracker: ErrorTracker,
                          config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process analysis for a single ticker with robust error handling.

    Args:
        ticker_symbol: Stock ticker symbol
        ticker_data: DataFrame containing ticker data
        detector: PatternDetector instance
        circuit_breaker: Circuit breaker to prevent cascading failures
        error_tracker: Error tracking object
        config: Configuration parameters

    Returns:
        dict: Analysis results or error information
    """
    if not circuit_breaker.can_execute():
        logger.warning(f"Circuit breaker open, skipping processing for {ticker_symbol}")
        return {
            "error": "Circuit breaker open",
            "circuit_breaker_status": circuit_breaker.get_status_report(),
            "ticker": ticker_symbol
        }

    logger.info(f"Processing ticker: {ticker_symbol} with {len(ticker_data)} data points")
    error_tracker.record_operation(success=True)

    try:
        # First attempt to recover any missing data
        recovered_data, data_usable = recover_ticker_data(ticker_data, config, error_tracker)

        if not data_usable:
            logger.warning(f"Insufficient data quality for {ticker_symbol} after recovery attempts")
            error_tracker.record_operation(success=False)

            # This is a controlled failure, not a system error, so don't increment circuit breaker
            return {
                "error": "Insufficient data quality",
                "ticker": ticker_symbol,
                "data_rows": len(recovered_data)
            }

        # Convert time strings to integers for faster comparison during processing
        if 'Datetime' in recovered_data.columns and not 'time_minutes' in recovered_data.columns:
            recovered_data['time_minutes'] = recovered_data['Datetime'].apply(
                lambda dt: dt.hour * 60 + dt.minute
            )

        # Process each analysis step separately to allow partial results on failure
        results = {
            "ticker": ticker_symbol,
            "data_points": len(recovered_data),
            "recurring_patterns": {},
            "temporal_clusters": {},
            "trend_reversals": [],
            "time_correlations": [],
            "time_shifts": []
        }

        # Try each analysis component separately
        try:
            preprocessed_data = detector.preprocess_for_pattern_detection(recovered_data)
            results["preprocessed"] = True
        except Exception as e:
            logger.error(f"Error preprocessing data for {ticker_symbol}: {e}")
            error_tracker.record_error(f"preprocess_{ticker_symbol}", e)
            preprocessed_data = recovered_data  # Fall back to recovered data
            results["preprocessed"] = False

        # Track completed analysis components
        successful_components = 0
        total_components = 5  # Number of analysis components

        # Component 1: Recurring patterns
        try:
            patterns = detector.detect_recurring_patterns(preprocessed_data)
            results["recurring_patterns"] = patterns.get(ticker_symbol, {})
            successful_components += 1
        except Exception as e:
            logger.error(f"Error detecting recurring patterns for {ticker_symbol}: {e}")
            error_tracker.record_error(f"recurring_patterns_{ticker_symbol}", e)

        # Component 2: Temporal clusters
        try:
            clusters = detector.detect_temporal_clusters(preprocessed_data)
            results["temporal_clusters"] = clusters.get(ticker_symbol, {})
            successful_components += 1
        except Exception as e:
            logger.error(f"Error detecting temporal clusters for {ticker_symbol}: {e}")
            error_tracker.record_error(f"temporal_clusters_{ticker_symbol}", e)

        # Component 3: Trend reversals
        try:
            reversals = detector.identify_trend_reversals(preprocessed_data)
            results["trend_reversals"] = reversals.get(ticker_symbol, [])
            successful_components += 1
        except Exception as e:
            logger.error(f"Error identifying trend reversals for {ticker_symbol}: {e}")
            error_tracker.record_error(f"trend_reversals_{ticker_symbol}", e)

        # Component 4: Time correlations
        try:
            correlations = detector.analyze_time_correlations(preprocessed_data)
            results["time_correlations"] = correlations.get(ticker_symbol, [])
            successful_components += 1
        except Exception as e:
            logger.error(f"Error analyzing time correlations for {ticker_symbol}: {e}")
            error_tracker.record_error(f"time_correlations_{ticker_symbol}", e)

        # Component 5: Time shifts (using the optimized version)
        try:
            config_dict = detector.config if hasattr(detector, 'config') else {}
            time_shifts = detect_time_shifted_patterns_optimized(preprocessed_data, config_dict)
            results["time_shifts"] = time_shifts.get(ticker_symbol, [])
            successful_components += 1
        except Exception as e:
            logger.error(f"Error detecting time shifts for {ticker_symbol}: {e}")
            error_tracker.record_error(f"time_shifts_{ticker_symbol}", e)

        # Record the partial success rate if not all components succeeded
        if successful_components < total_components:
            error_tracker.record_partial_failure(
                f"process_ticker_{ticker_symbol}",
                total_parts=total_components,
                failed_parts=total_components - successful_components,
                details={
                    'ticker': ticker_symbol,
                    'successful_components': successful_components,
                    'total_components': total_components
                }
            )

        # Record success in the circuit breaker
        circuit_breaker.record_success()

        return results

    except Exception as error:
        logger.error(f"Error processing ticker {ticker_symbol}: {error}")
        logger.error(traceback.format_exc())

        # Record the failure in both the error tracker and circuit breaker
        error_tracker.record_error(
            f"process_ticker_{ticker_symbol}",
            error,
            {'ticker': ticker_symbol, 'data_rows': len(ticker_data)}
        )
        error_tracker.record_operation(success=False)

        circuit_breaker.record_failure(error, {'ticker': ticker_symbol})

        # Return a structured error response
        return {
            "error": str(error),
            "error_type": type(error).__name__,
            "ticker": ticker_symbol,
            "circuit_breaker_status": circuit_breaker.get_status_report()
        }

# -------------------------
# Enhanced Main Pipeline
# -------------------------
def main_with_robust_error_handling() -> int:
    """
    Main function to run the pattern analysis pipeline with enhanced error handling.
    """
    # Set numpy to ignore specific warnings
    np.seterr(invalid='ignore', divide='ignore')

    args = None
    try:
        args = parse_args()
        # Rest of your initialization code
    except FileNotFoundError as e:
        # Handle missing files
        logger.error(f"Required file not found: {e}")
        output_dir = args.output if args is not None else "."
        return 1
    except argparse.ArgumentError as e:
        # Handle command line argument errors
        logger.error(f"Invalid command line arguments: {e}")
        return 1
    except ImportError as e:
        # Handle missing module errors
        logger.error(f"Missing required module: {e}")
        return 1
    except Exception as e:
        # As a last resort, catch any other exceptions
        logger.error(f"Error during initialization: {e}")
        output_dir = args.output if args is not None else "."
        return 1

    start_time = time.time()
    # Initialize error tracking systems
    error_tracker = ErrorTracker()
    global_circuit_breaker = CircuitBreaker(
        failure_threshold=3,  # Open circuit after 3 consecutive failures
        recovery_timeout=120,  # Wait 2 minutes before testing recovery
        timeout_factor=1.5  # Increase timeout by 50% for each failure
    )

    try:
        args = parse_args()
        config_obj = load_config(args.config)
        logger.info(f"Using configuration: {config_obj.export_dict()}")

        os.makedirs(args.output, exist_ok=True)
        if config_obj.cache_results:
            os.makedirs(args.cache_dir, exist_ok=True)

        # Load data
        try:
            logger.info(f"Loading data from {args.input}")
            data = pd.read_csv(args.input)
            data['Datetime'] = pd.to_datetime(data['Datetime'])
            logger.info(f"Loaded {len(data)} rows, {len(data['Ticker'].unique())} tickers")

            # Vectorized preprocessing (add time_minutes column)
            logger.info("Preprocessing data with vectorized operations")
            data = preprocess_data_vectorized(data)

        except Exception as external:
            logger.error(f"Error loading data: {external}")
            logger.error(traceback.format_exc())
            # Record critical error
            error_tracker.record_error("data_loading", external, {'input_file': args.input})
            return 1

        if not validate_input_data(data):
            logger.error("Input data validation failed.")
            error_tracker.record_error("data_validation", ValueError("Input data validation failed"))
            return 1

        # Filter tickers if specified
        if args.tickers:
            ticker_list = [t.strip() for t in args.tickers.split(',')]
            logger.info(f"Filtering data to include only: {ticker_list}")
            data = filter_data_by_tickers(data, ticker_list)
            logger.info(f"Filtered data now has {len(data)} rows, {len(data['Ticker'].unique())} tickers")

        # Prepare results structure
        master_results = {
            "recurring_patterns": {},
            "temporal_clusters": {},
            "trend_reversals": {},
            "time_correlations": {},
            "time_shifts": {}
        }
        all_tickers = data['Ticker'].unique().tolist()
        logger.info(f"Processing {len(all_tickers)} tickers: {all_tickers}")

        # Create cache key if caching is enabled
        cache_key = None
        if config_obj.cache_results:
            cache_key = load_or_create_cache_key(data, config_obj, args.cache_dir)
            logger.info(f"Using cache key: {cache_key[:8]}...")

        # Parallel or sequential processing
        completed_tickers = 0
        successful_tickers = 0
        failed_tickers = 0
        partial_success_tickers = 0
        total_tickers = len(all_tickers)
        detector = PatternDetector(config=config_obj.export_dict())

        # Create a dictionary to track per-ticker circuit breakers
        ticker_circuit_breakers = {
            ticker: CircuitBreaker(
                failure_threshold=2,  # Open circuit after 2 consecutive failures
                recovery_timeout=60,  # Wait 1 minute before testing recovery
                timeout_factor=2.0  # Double timeout for each failure
            ) for ticker in all_tickers
        }

        if config_obj.parallel_processing and total_tickers > 1:
            max_workers = config_obj.max_workers or min(os.cpu_count() or 4, total_tickers)
            logger.info(f"Using parallel processing with {max_workers} workers")

            # Process tickers in batches to avoid overwhelming the system
            batch_size = min(max_workers * 2, total_tickers)
            all_ticker_batches = [all_tickers[i:i + batch_size] for i in range(0, total_tickers, batch_size)]

            for batch_idx, ticker_batch in enumerate(all_ticker_batches):
                if global_circuit_breaker.can_execute():
                    logger.info(
                        f"Processing batch {batch_idx + 1}/{len(all_ticker_batches)} ({len(ticker_batch)} tickers)")

                    with ProcessPoolExecutor(max_workers=max_workers) as executor:
                        future_map = {}
                        for ticker_symbol in ticker_batch:
                            # Check ticker-specific circuit breaker
                            if not ticker_circuit_breakers[ticker_symbol].can_execute():
                                logger.warning(f"Circuit breaker open for {ticker_symbol}, skipping")
                                failed_tickers += 1
                                completed_tickers += 1
                                show_progress(completed_tickers, total_tickers, start_time)
                                continue

                            # Check cache first
                            if cache_key:
                                cached_data = check_cache(cache_key, ticker_symbol, args.cache_dir)
                                if cached_data:
                                    incorporate_ticker_results(master_results, ticker_symbol, cached_data)
                                    successful_tickers += 1
                                    completed_tickers += 1
                                    show_progress(completed_tickers, total_tickers, start_time)
                                    continue

                            ticker_data = data[data['Ticker'] == ticker_symbol]

                            # Skip if insufficient data
                            if len(ticker_data) < config_obj.min_pattern_occurrences:
                                logger.warning(f"Insufficient data for {ticker_symbol}, skipping")
                                failed_tickers += 1
                                completed_tickers += 1
                                show_progress(completed_tickers, total_tickers, start_time)
                                continue

                            fut = executor.submit(
                                process_ticker_robust,
                                ticker_symbol,
                                ticker_data,
                                detector,
                                ticker_circuit_breakers[ticker_symbol],
                                error_tracker,
                                config_obj.export_dict()
                            )
                            future_map[fut] = ticker_symbol

                        # Process completed futures
                        for fut in as_completed(future_map):
                            symbol_done = future_map[fut]
                            try:
                                ticker_out = fut.result()

                                # Check if there was an error
                                if "error" in ticker_out:
                                    logger.warning(f"Error processing {symbol_done}: {ticker_out['error']}")

                                    # Update circuit breaker if this was a system error
                                    if "circuit_breaker_status" in ticker_out:
                                        # Error already recorded in the worker process
                                        failed_tickers += 1
                                    else:
                                        # This was a controlled error (e.g., insufficient data quality)
                                        # Do not count as a failure for the circuit breaker
                                        partial_success_tickers += 1
                                else:
                                    # Process successful or partial results
                                    has_partial_data = (
                                            any(len(ticker_out.get(k, {})) > 0 for k in
                                                ["recurring_patterns", "temporal_clusters"]) or
                                            any(len(ticker_out.get(k, [])) > 0 for k in
                                                ["trend_reversals", "time_correlations", "time_shifts"])
                                    )

                                    if has_partial_data:
                                        incorporate_ticker_results(master_results, symbol_done, ticker_out)

                                        if cache_key:
                                            save_to_cache(cache_key, symbol_done, ticker_out, args.cache_dir)

                                        # Count as full success if all keys have data
                                        all_components_present = all(
                                            k in ticker_out and ticker_out[k] for k in
                                            ["recurring_patterns", "temporal_clusters", "trend_reversals",
                                             "time_correlations", "time_shifts"]
                                        )

                                        if all_components_present:
                                            successful_tickers += 1
                                        else:
                                            partial_success_tickers += 1
                                    else:
                                        # No usable results
                                        failed_tickers += 1

                            except Exception as external:
                                logger.error(f"Error processing ticker {symbol_done}: {external}")
                                logger.error(traceback.format_exc())

                                # Record error and update circuit breaker
                                error_tracker.record_error(f"process_ticker_{symbol_done}", external)
                                ticker_circuit_breakers[symbol_done].record_failure(external)

                                # Update global circuit breaker if too many errors
                                if failed_tickers > total_tickers * 0.25:  # More than 25% failed
                                    global_circuit_breaker.record_failure(
                                        Exception(f"Too many ticker failures ({failed_tickers}/{total_tickers})"),
                                        {'batch': batch_idx}
                                    )

                                failed_tickers += 1

                            completed_tickers += 1
                            show_progress(completed_tickers, total_tickers, start_time)

                    # Check if global circuit breaker has tripped
                    if not global_circuit_breaker.can_execute():
                        logger.warning(
                            f"Global circuit breaker tripped after batch {batch_idx + 1}. Pausing processing.")
                        # Wait for recovery timeout
                        recovery_time = global_circuit_breaker.get_current_timeout()
                        logger.info(f"Waiting {recovery_time:.1f}s for circuit breaker recovery")
                        time.sleep(recovery_time)

                else:
                    logger.warning("Global circuit breaker open, waiting for recovery")
                    time.sleep(global_circuit_breaker.get_current_timeout())
                    # After waiting, check if circuit can be closed
                    if global_circuit_breaker.can_execute():
                        logger.info("Global circuit breaker reset, continuing processing")
                    else:
                        logger.error("Global circuit breaker remains open, aborting remaining processing")
                        break
        else:
            logger.info("Using sequential processing")
            for i, ticker_symbol in enumerate(all_tickers, start=1):
                if not global_circuit_breaker.can_execute():
                    logger.warning("Global circuit breaker open, skipping remaining tickers")
                    break

                # Check ticker-specific circuit breaker
                if not ticker_circuit_breakers[ticker_symbol].can_execute():
                    logger.warning(f"Circuit breaker open for {ticker_symbol}, skipping")
                    failed_tickers += 1
                    show_progress(i, total_tickers, start_time)
                    continue

                # Check cache first
                if cache_key:
                    cached_data = check_cache(cache_key, ticker_symbol, args.cache_dir)
                    if cached_data:
                        incorporate_ticker_results(master_results, ticker_symbol, cached_data)
                        successful_tickers += 1
                        show_progress(i, total_tickers, start_time)
                        continue

                ticker_data = data[data['Ticker'] == ticker_symbol]

                # Skip if insufficient data
                if len(ticker_data) < config_obj.min_pattern_occurrences:
                    logger.warning(f"Insufficient data for {ticker_symbol}, skipping")
                    failed_tickers += 1
                    show_progress(i, total_tickers, start_time)
                    continue

                try:
                    ticker_results = process_ticker_robust(
                        ticker_symbol,
                        ticker_data,
                        detector,
                        ticker_circuit_breakers[ticker_symbol],
                        error_tracker,
                        config_obj.export_dict()
                    )

                    # Check if there was an error
                    if "error" in ticker_results:
                        logger.warning(f"Error processing {ticker_symbol}: {ticker_results['error']}")
                        failed_tickers += 1
                    else:
                        # Process successful or partial results
                        has_partial_data = (
                                any(len(ticker_results.get(k, {})) > 0 for k in
                                    ["recurring_patterns", "temporal_clusters"]) or
                                any(len(ticker_results.get(k, [])) > 0 for k in
                                    ["trend_reversals", "time_correlations", "time_shifts"])
                        )

                        if has_partial_data:
                            incorporate_ticker_results(master_results, ticker_symbol, ticker_results)

                            if cache_key:
                                save_to_cache(cache_key, ticker_symbol, ticker_results, args.cache_dir)

                            # Count as full success if all keys have data
                            all_components_present = all(
                                k in ticker_results and ticker_results[k] for k in
                                ["recurring_patterns", "temporal_clusters", "trend_reversals", "time_correlations",
                                 "time_shifts"]
                            )

                            if all_components_present:
                                successful_tickers += 1
                            else:
                                partial_success_tickers += 1
                        else:
                            # No usable results
                            failed_tickers += 1

                except Exception as external:
                    logger.error(f"Error processing ticker {ticker_symbol}: {external}")
                    logger.error(traceback.format_exc())

                    # Record error and update circuit breakers
                    error_tracker.record_error(f"process_ticker_{ticker_symbol}", external)
                    ticker_circuit_breakers[ticker_symbol].record_failure(external)

                    # Update global circuit breaker if too many errors
                    if failed_tickers > total_tickers * 0.25:  # More than 25% failed
                        global_circuit_breaker.record_failure(
                            Exception(f"Too many ticker failures ({failed_tickers}/{total_tickers})")
                        )

                    failed_tickers += 1

                show_progress(i, total_tickers, start_time)

        # Generate pattern summary with whatever data we have
        logger.info("Generating pattern summary")
        try:
            master_results["pattern_summary"] = detector.generate_pattern_summary()
        except Exception as summary_err:
            logger.error(f"Error generating pattern summary: {summary_err}")
            error_tracker.record_error("pattern_summary", summary_err)
            master_results["pattern_summary"] = {
                "error": str(summary_err),
                "total_patterns": 0,
                "pattern_count_by_ticker": {},
                "pattern_count_by_session": {
                    "pre_market": 0,
                    "main_session": 0,
                    "post_market": 0,
                    "after_hours": 0
                },
                "most_consistent_patterns": []
            }

        # Include error statistics in results
        master_results["processing_stats"] = {
            "total_tickers": total_tickers,
            "successful_tickers": successful_tickers,
            "partial_success_tickers": partial_success_tickers,
            "failed_tickers": failed_tickers,
            "success_rate": (successful_tickers / total_tickers) * 100 if total_tickers > 0 else 0,
            "partial_success_rate": (partial_success_tickers / total_tickers) * 100 if total_tickers > 0 else 0,
            "failure_rate": (failed_tickers / total_tickers) * 100 if total_tickers > 0 else 0,
            "processing_time_minutes": (time.time() - start_time) / 60.0
        }

        # Save results to JSON
        logger.info(f"Saving results to {args.output}")
        save_results(master_results, args.output)

        # Generate error report
        error_report_path = error_tracker.write_error_report(args.output)
        if error_report_path:
            logger.info(f"Error report written to {error_report_path}")

        # Generate visualizations if requested
        visualizations = {}
        if args.visualize:
            logger.info("Generating visualizations...")
            try:
                if 'preprocessed' not in data.columns:
                    data_for_viz = detector.preprocess_for_pattern_detection(data)
                else:
                    data_for_viz = data
                # Generate visualizations for successful tickers
                generated_visualizations = detector.visualize_patterns(data_for_viz, args.output)
                visualizations.update(generated_visualizations)
            except Exception as viz_exc:
                logger.error(f"Visualization error: {viz_exc}")
                error_tracker.record_error("visualization", viz_exc)

        # Generate HTML report
        logger.info("Generating HTML report")
        report_path = generate_html_report(master_results, visualizations, args.output, args.report_template)

        # Generate additional error summary visualization
        try:
            error_summary = error_tracker.get_error_summary()
            plt.figure(figsize=(10, 6))
            plt.bar(['Success', 'Partial Success', 'Failure'],
                    [successful_tickers, partial_success_tickers, failed_tickers])
            plt.title('Processing Results by Ticker')
            plt.ylabel('Number of Tickers')
            plt.tight_layout()
            error_viz_path = os.path.join(args.output, "error_summary.png")
            plt.savefig(error_viz_path)
            plt.close()
            logger.info(f"Error summary visualization saved to {error_viz_path}")
        except Exception as plot_err:
            logger.warning(f"Could not generate error summary plot: {plot_err}")

        total_time = (time.time() - start_time) / 60.0
        logger.info(f"Pattern analysis pipeline completed in {total_time:.2f} minutes")
        logger.info(
            f"Results: {successful_tickers} successful, {partial_success_tickers} partial, {failed_tickers} failed out of {total_tickers} tickers")

        if report_path:
            logger.info(f"View the report at: {report_path}")

        return 0

    except KeyboardInterrupt:
        logger.info("Pattern analysis interrupted by user")
        return 130
    except Exception as external:
        logger.error(f"Unhandled exception in pattern analysis pipeline: {external}")
        logger.error(traceback.format_exc())
        if error_tracker:
            error_tracker.record_error("main_pipeline", external)
            error_tracker.write_error_report(args.output if 'args' in locals() else ".")
        return 1


# -------------------------
# Optional: Chunked Processing
# -------------------------
def process_data_in_chunks() -> int:  # Removed unused parameters
    """Example chunked processing function."""
    # Implementation placeholder
    return 0


if __name__ == "__main__":
    try:
        exit_code = main_with_robust_error_handling()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.info("Pattern analysis interrupted by user")
        sys.exit(130)
    except Exception as exc:
        logger.critical(f"Critical error in main: {exc}")
        logger.critical(traceback.format_exc())
        sys.exit(1)