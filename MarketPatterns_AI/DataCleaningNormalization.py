#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Stock Data Cleaning and Normalization

This script processes stock data retrieved by fetch_SP500_Data.py, performing:
- Automatic column detection and analysis
- Data cleaning (removing invalid values, handling outliers)
- Intelligent normalization of price data (OHLC columns)
- Output of cleaned and normalized data to CSV
- Generation of summary statistics

Note: Volume data is read but excluded from normalization processing.
"""
import os
import sys
import logging
import argparse
from typing import Dict, Optional

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.preprocessing import StandardScaler, MinMaxScaler, RobustScaler

# Around line 27-38, update your path handling:
# Dynamically add project root and Processed_Data to Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)  # Parent directory
Processed_Data_dir = os.path.join(project_root, 'Processed_Data')

if not os.path.exists(Processed_Data_dir):
    raise FileNotFoundError(f"Directory '{Processed_Data_dir}' not found!")

# Add both paths to sys.path
if project_root not in sys.path:
    sys.path.append(project_root)
if Processed_Data_dir not in sys.path:
    sys.path.append(Processed_Data_dir)

# Import custom modules
try:
    from json_encoder_fix import EnhancedJSONEncoder
    from Pattern_Detection_Module import PatternDetector, safe_calculation
except ImportError as e:
    print(f"Import error: {e}")
    print(f"sys.path: {sys.path}")
    raise

class StockDataProcessor:
    """Handles cleaning and normalization of stock market data."""

    def __init__(self, config: Dict = None):
        """
        Initialize the StockDataProcessor.

        Args:
            config (Dict, optional): Configuration dictionary. Defaults to None.
        """
        # Default configuration
        self.default_config = {
            "input_dir": "Fetched_Data",
            "input_file": "combined_sp500_all_data_5min.csv",
            "output_dir": "Processed_Data",
            "output_file": "cleaned_normalized_data.csv",
            "log_file": "data_cleaning_normalization.log",
            "price_columns": ["Open", "High", "Low", "Close"],
            "default_normalization": "robust",  # Options: 'standard', 'minmax', 'robust'
            "outlier_detection": {
                "enabled": True,
                "method": "iqr",  # Options: 'zscore', 'iqr', 'percentile'
                "zscore_threshold": 3.0,
                "iqr_multiplier": 1.5,
                "percentile_range": [0.001, 0.999]
            },
            "handle_missing": {
                "method": "interpolate",  # Options: 'drop', 'interpolate', 'ffill'
                "max_consecutive_missing": 3  # Max consecutive missing values allowed for interpolation
            },
            # Add default parallel processing configuration
            "parallel_processing": {
                "enabled": False,  # Default to sequential processing
                "max_workers": None,  # Auto-determine based on CPU count
                "use_processes": False,  # Default to threads for better shared memory access
                "min_rows_per_worker": 10000,  # Minimum dataset size to consider parallelization
                "cleanup_temp_files": True  # Whether to clean up temporary log files
            }
        }

        # Merge provided config with defaults
        self.config = self.default_config.copy()
        if config:
            self.config.update(config)

        # Setup logging
        self._setup_logging()

        # Initialize data structures
        self.data = None
        self.cleaned_data = None
        self.normalized_data = None
        self.normalization_params = {}
        self.stats_summary = {}

    def setup_logging(self):
        """Public method to set up logging configuration."""
        self._setup_logging()

    def _setup_logging(self):
        """Set up logging configuration."""
        log_dir = os.path.dirname(self.config["log_file"])
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)

        self.logger = logging.getLogger("StockDataProcessor")
        self.logger.setLevel(logging.INFO)

        # Create handlers
        file_handler = logging.FileHandler(self.config["log_file"])
        console_handler = logging.StreamHandler()

        # Create formatter
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)

        # Add handlers
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)

        self.logger.info("StockDataProcessor initialized")

    def _cleanup_temp_logs(self):
        """Clean up temporary log files created during parallel processing."""
        import glob
        import os

        # Get the base log file path without extension
        base_log_path = os.path.splitext(self.config["log_file"])[0]

        # Find all temporary log files created during parallel processing
        temp_log_pattern = f"{base_log_path}_*_norm.log"
        ticker_log_pattern = f"{base_log_path}_*.log"

        # Clean up normalization logs
        for log_file in glob.glob(temp_log_pattern):
            try:
                os.remove(log_file)
                self.logger.debug(f"Removed temporary log file: {log_file}")
            except Exception as e:
                self.logger.warning(f"Failed to remove temporary log file {log_file}: {e}")

        # Clean up ticker-specific logs
        for log_file in glob.glob(ticker_log_pattern):
            if "_norm.log" not in log_file:  # Avoid double-processing norm logs
                try:
                    os.remove(log_file)
                    self.logger.debug(f"Removed temporary log file: {log_file}")
                except Exception as e:
                    self.logger.warning(f"Failed to remove temporary log file {log_file}: {e}")

    def load_data(self, file_path: Optional[str] = None) -> pd.DataFrame:
        """
        Load stock data from CSV file.

        Args:
            file_path (str, optional): Path to the input CSV file. If None, use config path.

        Returns:
            pd.DataFrame: Loaded stock data
        """
        if file_path is None:
            file_path = os.path.join(self.config["input_dir"], self.config["input_file"])

        self.logger.info(f"Loading data from {file_path}")

        try:
            # Read first few rows to analyze
            sample_data = pd.read_csv(file_path, nrows=5)
            dtypes = {}

            # Check for Datetime column and set appropriate dtype
            if "Datetime" in sample_data.columns:
                dtypes["Datetime"] = str  # Load as string first, convert later

            # Load the full dataset with appropriate dtypes
            data = pd.read_csv(file_path, dtype=dtypes)

            # Validate required columns
            self._validate_required_columns(data)

            # Convert Datetime to proper datetime objects
            if "Datetime" in data.columns:
                data["Datetime"] = pd.to_datetime(data["Datetime"])

            # Basic data inspection
            total_rows = len(data)
            columns = list(data.columns)
            dtypes = {col: str(data[col].dtype) for col in columns}
            missing_values = data.isna().sum().to_dict()

            self.logger.info(f"Data loaded successfully: {total_rows} rows, {len(columns)} columns")
            self.logger.info(f"Columns: {columns}")
            self.logger.info(f"Data types: {dtypes}")

            missing_values_str = ", ".join([f"{col}: {count}" for col, count in missing_values.items() if count > 0])
            if missing_values_str:
                self.logger.info(f"Missing values: {missing_values_str}")
            else:
                self.logger.info("No missing values detected")

            # Detect price columns if not specified
            self._detect_price_columns(data)

            self.data = data
            return data

        except Exception as e:
            self.logger.error(f"Error loading data: {e}")
            raise

    def _validate_required_columns(self, data):
        """
        Validate that the data contains all required columns.

        Args:
            data (pandas.DataFrame): The data to validate

        Raises:
            ValueError: If required columns are missing
        """
        # Define required columns
        required_columns = ["Ticker", "Datetime"]

        # Check for missing required columns
        missing_columns = [col for col in required_columns if col not in data.columns]

        if missing_columns:
            error_msg = f"Required column(s) missing from data: {', '.join(missing_columns)}"
            self.logger.error(error_msg)

            # Provide helpful guidance for common column name variations
            suggestions = []
            for missing_col in missing_columns:
                if missing_col == "Ticker":
                    possible_alternatives = [col for col in data.columns if col.lower() in
                                             ["symbol", "stock", "ticker_symbol", "instrument", "security"]]
                    if possible_alternatives:
                        suggestions.append(f"'{missing_col}' might be one of: {', '.join(possible_alternatives)}")

                elif missing_col == "Datetime":
                    possible_alternatives = [col for col in data.columns if col.lower() in
                                             ["date", "time", "timestamp", "time_stamp", "date_time"]]
                    if possible_alternatives:
                        suggestions.append(f"'{missing_col}' might be one of: {', '.join(possible_alternatives)}")

            if suggestions:
                error_msg += f"\nPossible alternatives found:\n" + "\n".join(suggestions)
                error_msg += "\n\nYou can rename columns in your CSV file or modify the script to use your column names."

            raise ValueError(error_msg)

        # Also validate that there are sufficient price columns
        price_columns = [col for col in self.config["price_columns"] if col in data.columns]
        if not price_columns:
            # Try to find any potential price-related columns
            numeric_cols = data.select_dtypes(include=['number']).columns.tolist()
            if "Volume" in numeric_cols:
                numeric_cols.remove("Volume")

            # Look for columns that might be price-related
            possible_price_cols = [col for col in numeric_cols if
                                   any(term in col.lower() for term in ['price', 'open', 'high', 'low', 'close'])]

            error_msg = "No price columns found in data. Expected at least one of: 'Open', 'High', 'Low', 'Close'"

            if possible_price_cols:
                error_msg += f"\nPossible price columns found: {', '.join(possible_price_cols)}"
                error_msg += "\nYou can specify these in your configuration or rename them to the expected column names."

            self.logger.error(error_msg)
            raise ValueError(error_msg)

        # Verify we have sufficient data for each ticker
        for ticker in data["Ticker"].unique():
            ticker_data = data[data["Ticker"] == ticker]
            if len(ticker_data) < 5:  # Arbitrary minimum, but normalization with too few points is problematic
                self.logger.warning(
                    f"Ticker {ticker} has only {len(ticker_data)} data points, which may be insufficient for reliable normalization")

        # Log the columns that will be normalized
        self.logger.info(f"Will normalize the following columns: {price_columns}")

    def _detect_price_columns(self, data):
        """
        Detect price columns in the dataset.

        Args:
            data (pandas.DataFrame): Input stock data
        """
        # First standardize column names to handle case sensitivity
        column_map = {}
        standard_columns = []

        # Build mapping of case-insensitive to standard column names
        for col in data.columns:
            col_lower = col.lower()
            if col_lower == "open":
                column_map[col] = "Open"
                standard_columns.append("Open")
            elif col_lower == "high":
                column_map[col] = "High"
                standard_columns.append("High")
            elif col_lower == "low":
                column_map[col] = "Low"
                standard_columns.append("Low")
            elif col_lower == "close":
                column_map[col] = "Close"
                standard_columns.append("Close")
            elif col_lower == "volume":
                column_map[col] = "Volume"

        # Log detected mappings if any found
        if column_map:
            self.logger.info(f"Standardizing column names: {column_map}")
            # Apply the mapping to standardize column names
            data.rename(columns=column_map, inplace=True)

        # Use default price columns as a starting point (now case-insensitive)
        price_columns = [col for col in self.config["price_columns"] if col in standard_columns]

        # If none of the default price columns are found, try to detect them
        if not price_columns:
            self.logger.warning(f"None of the default price columns {self.config['price_columns']} found in data")

            # Get all numeric columns as candidates
            numeric_cols = data.select_dtypes(include=['number']).columns.tolist()

            # Remove likely non-price columns (case-insensitive)
            excluded_patterns = ["volume", "vol", "qty", "quantity"]
            numeric_cols = [col for col in numeric_cols if col.lower() not in excluded_patterns]

            # Check for common naming patterns in remaining columns
            detected = []
            for col in numeric_cols:
                col_lower = col.lower()
                if any(price_term in col_lower for price_term in ['open', 'high', 'low', 'close', 'price']):
                    detected.append(col)

            if detected:
                price_columns = detected
                self.logger.info(f"Auto-detected potential price columns: {price_columns}")
            else:
                # If we still can't find price columns, use the first few numeric columns as a fallback
                # but exclude likely non-price columns like index, date, or ID columns
                exclude_patterns = ['id', 'date', 'time', 'index', 'ticker', 'symbol', 'volume', 'vol']
                fallback_cols = [
                                    col for col in numeric_cols
                                    if not any(pattern in col.lower() for pattern in exclude_patterns)
                                ][:4]  # Take up to 4 columns

                if fallback_cols:
                    price_columns = fallback_cols
                    self.logger.warning(
                        f"Could not detect specific price columns. Using numeric columns as fallback: {price_columns}"
                    )
                else:
                    self.logger.error("Could not detect any usable price columns in the data")

        if price_columns:
            self.config["price_columns"] = price_columns
            self.logger.info(f"Detected price columns: {price_columns}")
        else:
            self.logger.warning("Could not detect price columns. Please specify price columns manually.")

    def analyze_distributions(self, data=None) -> Dict:
        """
        Analyze distributions of price columns to determine best normalization.

        Args:
            data (pandas.DataFrame, optional): Input data. If None, use self.data.

        Returns:
            Dict: Distribution analysis results
        """
        if data is None:
            data = self.data

        if data is None:
            self.logger.error("No data available for distribution analysis")
            return {}

        self.logger.info("Analyzing price column distributions")
        distribution_results = {}

        for ticker in data["Ticker"].unique():
            ticker_data = data[data["Ticker"] == ticker]
            ticker_results = {}

            for col in self.config["price_columns"]:
                if col in ticker_data.columns:
                    values = ticker_data[col].dropna()

                    # Skip empty columns
                    if len(values) == 0:
                        continue

                    # Basic statistics
                    stats_dict = {
                        "mean": values.mean(),
                        "median": values.median(),
                        "std": values.std(),
                        "min": values.min(),
                        "max": values.max(),
                        "skew": stats.skew(values),
                        "kurtosis": stats.kurtosis(values)
                    }

                    # Normality test
                    shapiro_test = stats.shapiro(values.sample(min(1000, len(values)), random_state=42))
                    statistic, p_value = shapiro_test  # Unpack the tuple properly
                    stats_dict["normality_pvalue"] = float(p_value)
                    stats_dict["is_normal"] = float(p_value) > 0.05

                    ticker_results[col] = stats_dict

            distribution_results[ticker] = ticker_results

        # Determine optimal normalization method based on distribution properties
        # This is a simplified heuristic and can be refined based on specific needs
        overall_normal_count = 0
        overall_skew_count = 0
        total_distributions = 0

        for ticker, ticker_results in distribution_results.items():
            for col, stats_dict in ticker_results.items():
                total_distributions += 1
                if stats_dict.get("is_normal", False):
                    overall_normal_count += 1
                if abs(stats_dict.get("skew", 0)) > 1.0:
                    overall_skew_count += 1

        # Normalization selection logic
        if total_distributions > 0:
            normal_ratio = overall_normal_count / total_distributions
            skew_ratio = overall_skew_count / total_distributions

            if normal_ratio > 0.7:
                # Mostly normal distributions
                recommended_method = "standard"
            elif skew_ratio > 0.3:
                # Significant skew present
                recommended_method = "robust"
            else:
                # Default to MinMax for more predictable ranges
                recommended_method = "minmax"

            self.logger.info(f"Distribution analysis complete. Recommended normalization: {recommended_method}")
            self.logger.info(f"Normal distributions: {normal_ratio:.2%}, Skewed distributions: {skew_ratio:.2%}")

            # Update config with recommended method
            self.config["default_normalization"] = recommended_method
        else:
            self.logger.warning("Could not determine optimal normalization method from distributions")

        return distribution_results

    def clean_data(self, data=None) -> pd.DataFrame:
        """
        Clean the stock data by handling missing values, outliers, and invalid data.

        Args:
            data (pandas.DataFrame, optional): Input data. If None, use self.data.

        Returns:
            pandas.DataFrame: Cleaned data
        """
        if data is None:
            data = self.data

        if data is None:
            self.logger.error("No data available for cleaning")
            return pd.DataFrame()

        self.logger.info("Starting data cleaning process")

        # Make a copy to avoid modifying the original
        cleaned = data.copy()
        original_rows = len(cleaned)

        # 1. Handle invalid values (NaN, inf)
        self.logger.info("Handling invalid values")
        cleaned.replace([np.inf, -np.inf], np.nan, inplace=True)

        # Count NaN values before cleaning
        nan_count_before = cleaned.isna().sum().sum()
        self.logger.info(f"Found {nan_count_before} NaN values before cleaning")

        # Group data by ticker once to avoid repeated grouping operations
        ticker_groups = cleaned.groupby("Ticker")

        # 2. Handle missing values based on config
        missing_method = self.config["handle_missing"]["method"]
        max_consecutive = self.config["handle_missing"]["max_consecutive_missing"]

        # Process each ticker group only once
        if missing_method in ["interpolate", "ffill"]:
            self.logger.info(
                f"Handling missing values using {missing_method} method (max consecutive: {max_consecutive})")
            processed_groups = []

            for ticker, group in ticker_groups:
                # Sort by datetime (once per ticker)
                group_sorted = group.sort_values("Datetime")

                if missing_method == "interpolate":
                    # Process all price columns at once for this ticker
                    for col in self.config["price_columns"]:
                        if col in group_sorted.columns:
                            # Find large gaps (more than max_consecutive consecutive NaNs)
                            mask = group_sorted[col].isna()
                            if mask.any():
                                # Count consecutive NaNs
                                # Fix for boolean Series astype issue
                                mask_diff = (mask != mask.shift())
                                group_sorted['nan_group'] = pd.Series(mask_diff, index=group_sorted.index).astype(
                                    int).cumsum()
                                consec_counts = group_sorted.groupby('nan_group')['Datetime'].count()

                                # For large gaps, keep them as NaN
                                large_gap_groups = consec_counts[consec_counts > max_consecutive].index
                                large_gap_mask = group_sorted['nan_group'].isin(large_gap_groups) & mask

                                # Interpolate the rest
                                temp_col = group_sorted[col].copy()
                                temp_col.interpolate(method='linear', limit=max_consecutive, inplace=True)

                                # Keep large gaps as NaN
                                temp_col[large_gap_mask] = np.nan
                                group_sorted[col] = temp_col

                                # Log large gaps
                                if large_gap_mask.any():
                                    self.logger.info(
                                        f"Found {large_gap_mask.sum()} values in large gaps for {ticker}, {col}")

                            # Clean up
                            if 'nan_group' in group_sorted.columns:
                                group_sorted.drop('nan_group', axis=1, inplace=True)

                elif missing_method == "ffill":
                    # Forward fill all price columns at once
                    price_cols = [col for col in self.config["price_columns"] if col in group_sorted.columns]
                    group_sorted[price_cols] = group_sorted[price_cols].fillna(method='ffill')

                processed_groups.append(group_sorted)

            if processed_groups:
                cleaned = pd.concat(processed_groups)

        elif missing_method == "drop":
            # Drop rows with NaN in price columns
            self.logger.info("Dropping rows with missing values in price columns")
            price_cols = [col for col in self.config["price_columns"] if col in cleaned.columns]
            before_drop = len(cleaned)
            cleaned = cleaned.dropna(subset=price_cols)
            self.logger.info(f"Dropped {before_drop - len(cleaned)} rows with missing price values")

        # Count remaining NaN values after filling methods
        nan_count_after = cleaned.isna().sum().sum()
        self.logger.info(f"Remaining NaN values after handling: {nan_count_after}")

        # Drop any remaining rows with NaN in price columns as a last resort
        price_cols = [col for col in self.config["price_columns"] if col in cleaned.columns]
        if price_cols:
            before_final_drop = len(cleaned)
            cleaned = cleaned.dropna(subset=price_cols)
            final_dropped = before_final_drop - len(cleaned)
            if final_dropped > 0:
                self.logger.info(f"Final drop of {final_dropped} rows with NaN values that couldn't be filled")

        # 3. Handle outliers if enabled - use the already grouped data
        if self.config["outlier_detection"]["enabled"]:
            self.logger.info("Detecting and handling outliers")

            # Re-group the data if it's changed (otherwise reuse existing groups)
            if missing_method != "drop":
                ticker_groups = cleaned.groupby("Ticker")

            # Apply outlier detection method efficiently using the grouped data
            outlier_method = self.config["outlier_detection"]["method"]
            cleaned = self._handle_outliers_efficiently(cleaned, ticker_groups, outlier_method)

        # Log results
        rows_removed = original_rows - len(cleaned)
        self.logger.info(f"Cleaning complete. Removed {rows_removed} rows ({rows_removed / original_rows:.2%})")

        self.cleaned_data = cleaned
        return cleaned

    def _handle_outliers_efficiently(self, data, ticker_groups, method):
        """
        Optimized version of outlier detection that works directly with grouped data.

        Args:
            data (pandas.DataFrame): Input data
            ticker_groups (pandas.core.groupby.DataFrameGroupBy): Already grouped data by ticker
            method (str): Outlier detection method ('zscore', 'iqr', 'percentile')

        Returns:
            pandas.DataFrame: Data with outliers handled
        """
        # Create a copy to avoid modifying the input
        result = data.copy()

        # Track outliers for logging
        total_outliers = 0
        outlier_counts = {}

        # Process each ticker group
        for ticker, ticker_data in ticker_groups:
            ticker_outliers = 0
            ticker_outlier_counts = {}

            # Check each price column for outliers
            for col in self.config["price_columns"]:
                if col not in ticker_data.columns:
                    continue

                values = ticker_data[col].dropna()
                if len(values) == 0:
                    continue

                # Initialize outlier mask (all False by default)
                outlier_mask = pd.Series(False, index=ticker_data.index)

                if method == "zscore":
                    # Z-score method
                    threshold = self.config["outlier_detection"]["zscore_threshold"]
                    z_scores = safe_calculation(lambda: np.abs((values - values.mean()) / values.std()),
                                                default_value=0.0)
                    z_outlier_indices = values.index[z_scores > threshold]
                    outlier_mask.loc[z_outlier_indices] = True

                elif method == "iqr":
                    # IQR method
                    multiplier = self.config["outlier_detection"]["iqr_multiplier"]
                    q1 = values.quantile(0.25)
                    q3 = values.quantile(0.75)
                    iqr = q3 - q1
                    lower_bound = q1 - (multiplier * iqr)
                    upper_bound = q3 + (multiplier * iqr)

                    iqr_outlier_indices = values.index[(values < lower_bound) | (values > upper_bound)]
                    outlier_mask.loc[iqr_outlier_indices] = True

                elif method == "percentile":
                    # Percentile method
                    percentile_range = self.config["outlier_detection"]["percentile_range"]
                    lower_bound = values.quantile(percentile_range[0])
                    upper_bound = values.quantile(percentile_range[1])

                    percentile_outlier_indices = values.index[(values < lower_bound) | (values > upper_bound)]
                    outlier_mask.loc[percentile_outlier_indices] = True

                # Count outliers
                col_outliers = outlier_mask.sum()
                ticker_outliers += col_outliers

                if col_outliers > 0:
                    ticker_outlier_counts[col] = col_outliers
                    # FIX: Get the actual indices where outliers are detected
                    outlier_indices = outlier_mask[outlier_mask].index
                    if len(outlier_indices) > 0:
                        # Replace outliers with NaN for later interpolation
                        result.loc[outlier_indices, col] = np.nan

            # Store outlier counts for logging
            if ticker_outliers > 0:
                outlier_counts[ticker] = ticker_outlier_counts

            total_outliers += ticker_outliers

        # Log outlier information
        if total_outliers > 0:
            self.logger.info(f"Detected {total_outliers} outliers using {method} method")
            for ticker, cols in outlier_counts.items():
                outlier_str = ", ".join([f"{col}: {count}" for col, count in cols.items() if count > 0])
                if outlier_str:
                    self.logger.info(f"Outliers for {ticker}: {outlier_str}")

            # Now interpolate the outliers we replaced with NaN - reuse the ticker grouping
            # This avoids regrouping again which could be expensive
            processed_groups = []

            for ticker, group in result.groupby("Ticker"):
                # Sort by datetime
                group_sorted = group.sort_values("Datetime")

                # Interpolate outliers in price columns - do all columns at once
                price_cols = [col for col in self.config["price_columns"] if col in group_sorted.columns]
                if price_cols:
                    # Check if any of these columns have NaNs
                    if group_sorted[price_cols].isna().any().any():
                        # Interpolate all columns at once
                        group_sorted[price_cols] = group_sorted[price_cols].interpolate(method='linear')

                processed_groups.append(group_sorted)

            if processed_groups:
                result = pd.concat(processed_groups)

            # Final cleanup of any remaining NaNs with forward/backward fill
            # Apply to all columns at once to reduce operations
            price_cols = [col for col in self.config["price_columns"] if col in result.columns]
            if price_cols:
                has_nas = result[price_cols].isna().any().any()
                if has_nas:
                    # First forward fill
                    result[price_cols] = result[price_cols].fillna(method='ffill')
                    # Then backward fill for any remaining NaNs
                    result[price_cols] = result[price_cols].fillna(method='bfill')

        return result

    def normalize_data(self, data=None) -> pd.DataFrame:
        """
        Normalize price columns using the selected normalization method.

        Args:
            data (pandas.DataFrame, optional): Input data. If None, use self.cleaned_data.

        Returns:
            pandas.DataFrame: Normalized data
        """
        if data is None:
            data = self.cleaned_data

        if data is None:
            self.logger.error("No cleaned data available for normalization")
            return pd.DataFrame()

        # Validate that required columns exist before proceeding
        self._validate_normalization_requirements(data)

        # Get normalization method from config
        method = self.config["default_normalization"]
        self.logger.info(f"Normalizing price columns using {method} method")

        # Make a copy of the data to avoid modifying the original
        normalized = data.copy()

        # Initialize normalization parameter storage
        self.normalization_params = {}

        # Track columns that were skipped due to all-NaN values
        all_nan_columns = {}

        # Process each ticker separately to maintain relative price relationships within each ticker
        for ticker in normalized["Ticker"].unique():
            ticker_mask = normalized["Ticker"] == ticker
            ticker_data = normalized.loc[ticker_mask]

            ticker_params = {}
            ticker_all_nan = []

            # Normalize each price column
            for col in self.config["price_columns"]:
                if col not in ticker_data.columns:
                    continue

                # Extract column values and check for all-NaN or constant value
                values = ticker_data[col].values

                # Skip if all values are NaN
                if np.isnan(values).all():
                    self.logger.warning(f"Column {col} for {ticker} contains all NaN values, skipping normalization")
                    ticker_all_nan.append(col)
                    # Don't attempt to normalize this column for this ticker
                    continue

                # Check if all values are the same (after removing NaNs)
                non_nan_values = values[~np.isnan(values)]
                if len(non_nan_values) == 0:
                    self.logger.warning(f"Column {col} for {ticker} contains no valid values, skipping normalization")
                    ticker_all_nan.append(col)
                    continue

                if len(non_nan_values) > 0 and np.all(non_nan_values == non_nan_values[0]):
                    self.logger.warning(
                        f"Column {col} for {ticker} contains only a single value ({non_nan_values[0]}), skipping normalization")
                    # For constant values, set all to a constant normalized value (e.g., 0.5 for MinMax)
                    if method == "minmax":
                        normalized.loc[ticker_mask, col] = 0.5
                    elif method == "standard" or method == "robust":
                        normalized.loc[ticker_mask, col] = 0.0  # Z-score of constant value is 0
                    ticker_params[col] = {"constant_value": float(non_nan_values[0])}
                    continue

                # Reshape for scikit-learn (requires 2D array)
                values_2d = values.reshape(-1, 1)

                # Choose scaler based on method
                if method == "standard":
                    scaler = StandardScaler()
                elif method == "minmax":
                    scaler = MinMaxScaler()
                elif method == "robust":
                    scaler = RobustScaler()
                else:
                    self.logger.warning(f"Unknown normalization method: {method}, using RobustScaler as fallback")
                    scaler = RobustScaler()

                try:
                    # Fit and transform
                    normalized_values = scaler.fit_transform(values_2d)

                    # Store normalization parameters (fixing the deprecation warnings)
                    if method == "standard":
                        ticker_params[col] = {
                            "mean": float(scaler.mean_[0]) if hasattr(scaler.mean_, "__len__") else float(scaler.mean_),
                            "scale": float(scaler.scale_[0]) if hasattr(scaler.scale_, "__len__") else float(
                                scaler.scale_)
                        }
                    elif method == "minmax":
                        ticker_params[col] = {
                            "min": float(scaler.min_[0]) if hasattr(scaler.min_, "__len__") else float(scaler.min_),
                            "scale": float(scaler.scale_[0]) if hasattr(scaler.scale_, "__len__") else float(
                                scaler.scale_)
                        }
                    elif method == "robust":
                        ticker_params[col] = {
                            "center": float(scaler.center_[0]) if hasattr(scaler.center_, "__len__") else float(
                                scaler.center_),
                            "scale": float(scaler.scale_[0]) if hasattr(scaler.scale_, "__len__") else float(
                                scaler.scale_)
                        }

                    # Update the dataframe with normalized values
                    normalized.loc[ticker_mask, col] = normalized_values

                except Exception as e:
                    self.logger.error(f"Error normalizing {col} for {ticker}: {e}")
                    # If normalization fails, add to the all-NaN list and continue with other columns
                    ticker_all_nan.append(col)

            # Store the parameters
            self.normalization_params[ticker] = ticker_params

            # Track columns that were all NaN for this ticker
            if ticker_all_nan:
                all_nan_columns[ticker] = ticker_all_nan

        # Log columns that were skipped due to all-NaN values
        if all_nan_columns:
            self.logger.warning(
                "The following columns were skipped during normalization due to all-NaN values or constant values:")
            for ticker, cols in all_nan_columns.items():
                self.logger.warning(f"  {ticker}: {', '.join(cols)}")

        self.normalized_data = normalized
        self.logger.info("Normalization complete")
        return normalized

    def _normalize_data_parallel(self, data):
        """
        Normalize data using parallel processing for improved performance on large datasets.

        Args:
            data (pandas.DataFrame): Data to normalize

        Returns:
            pandas.DataFrame: Normalized data
        """
        import concurrent.futures
        from functools import partial

        # Determine whether to use processes or threads
        use_processes = self.config["parallel_processing"]["use_processes"]
        max_workers = self.config["parallel_processing"]["max_workers"]

        # Split data by ticker to allow parallel processing
        tickers = data["Ticker"].unique()
        ticker_data_dict = {ticker: data[data["Ticker"] == ticker] for ticker in tickers}

        # Function to normalize a single ticker's data
        def normalize_ticker_data(ticker, ticker_data, norm_method):
            # Create a configuration for this specific job
            job_config = self.config.copy()
            # Ensure we use the same normalization method for all tickers
            job_config["default_normalization"] = norm_method
            # Use the ticker name in the log file to avoid conflicts
            job_config["log_file"] = os.path.splitext(self.config["log_file"])[0] + f"_{ticker}_norm.log"

            # Create a processor just for this ticker
            processor = StockDataProcessor(job_config)

            # The normalization needs to know this is already cleaned
            processor.cleaned_data = ticker_data

            # Process this ticker's data
            normalized = processor.normalize_data()

            # Store the normalization parameters for this ticker
            return (ticker, normalized, processor.normalization_params.get(ticker, {}))

        # Use the selected normalization method from main processor
        norm_method = self.config["default_normalization"]

        # Create partial function with fixed parameters
        normalize_func = partial(normalize_ticker_data, norm_method=norm_method)

        # Storage for results
        normalized_pieces = []
        combined_params = {}

        # Choose the appropriate executor
        executor_class = concurrent.futures.ProcessPoolExecutor if use_processes else concurrent.futures.ThreadPoolExecutor

        # Log the parallelization approach
        self.logger.info(
            f"Normalizing data in parallel using {max_workers or 'auto'} {'processes' if use_processes else 'threads'}")

        # Run in parallel
        with executor_class(max_workers=max_workers) as executor:
            # Submit all normalization jobs
            future_to_ticker = {executor.submit(normalize_func, ticker, data): ticker
                                for ticker, data in ticker_data_dict.items()}

            # Process as they complete
            for future in concurrent.futures.as_completed(future_to_ticker):
                ticker = future_to_ticker[future]
                try:
                    # Get results: (ticker, normalized_data, params)
                    ticker, normalized_data, params = future.result()
                    if normalized_data is not None and not normalized_data.empty:
                        normalized_pieces.append(normalized_data)
                        combined_params[ticker] = params
                        self.logger.info(f"Successfully normalized data for {ticker} in parallel")
                    else:
                        self.logger.warning(f"Parallel normalization returned empty result for {ticker}")
                except Exception as e:
                    self.logger.error(f"Error normalizing {ticker} in parallel: {e}")

        # Store the combined normalization parameters
        self.normalization_params.update(combined_params)

        # Combine results
        if normalized_pieces:
            return pd.concat(normalized_pieces)
        else:
            self.logger.error("No data was successfully normalized in parallel")
            return pd.DataFrame()

    def _clean_data_parallel(self, data):
        """
        Clean data using parallel processing for improved performance on large datasets.

        Args:
            data (pandas.DataFrame): Data to clean

        Returns:
            pandas.DataFrame: Cleaned data
        """
        import concurrent.futures
        from functools import partial

        # Determine whether to use processes or threads
        use_processes = self.config["parallel_processing"]["use_processes"]
        max_workers = self.config["parallel_processing"]["max_workers"]

        # Split data by ticker to allow parallel processing
        tickers = data["Ticker"].unique()
        ticker_data_dict = {ticker: data[data["Ticker"] == ticker] for ticker in tickers}

        # Define a function to clean a single ticker's data
        def clean_ticker_data(ticker, ticker_data):
            # Create a configuration for this specific job
            job_config = self.config.copy()
            # Use the ticker name in the log file to avoid conflicts
            job_config["log_file"] = os.path.splitext(self.config["log_file"])[0] + f"_{ticker}.log"

            # Create a processor just for this ticker
            processor = StockDataProcessor(job_config)
            # Clean this ticker's data
            return processor.clean_data(ticker_data)

        # Create partial function with fixed first argument
        clean_func = partial(clean_ticker_data)

        # Storage for results
        cleaned_pieces = []

        # Choose the appropriate executor
        executor_class = concurrent.futures.ProcessPoolExecutor if use_processes else concurrent.futures.ThreadPoolExecutor

        # Log the parallelization approach
        self.logger.info(
            f"Cleaning data in parallel using {max_workers or 'auto'} {'processes' if use_processes else 'threads'}")

        # Run in parallel
        with executor_class(max_workers=max_workers) as executor:
            # Submit all cleaning jobs
            future_to_ticker = {executor.submit(clean_func, ticker, data): ticker
                                for ticker, data in ticker_data_dict.items()}

            # Process as they complete
            for future in concurrent.futures.as_completed(future_to_ticker):
                ticker = future_to_ticker[future]
                try:
                    # Get result
                    result = future.result()
                    if result is not None and not result.empty:
                        cleaned_pieces.append(result)
                        self.logger.info(f"Successfully cleaned data for {ticker} in parallel")
                    else:
                        self.logger.warning(f"Parallel cleaning returned empty result for {ticker}")
                except Exception as e:
                    self.logger.error(f"Error cleaning {ticker} in parallel: {e}")

        # Combine results
        if cleaned_pieces:
            return pd.concat(cleaned_pieces)
        else:
            self.logger.error("No data was successfully cleaned in parallel")
            return pd.DataFrame()

    def _validate_normalization_requirements(self, data):
        """
        Validate that the data contains the required columns for normalization.

        Args:
            data (pandas.DataFrame): The data to validate

        Raises:
            ValueError: If required columns for normalization are missing
        """
        # Check if Ticker column exists
        if "Ticker" not in data.columns:
            error_msg = "Cannot perform normalization: 'Ticker' column is required but missing"
            self.logger.error(error_msg)
            raise ValueError(error_msg)

        # Check if any price columns exist
        price_columns = [col for col in self.config["price_columns"] if col in data.columns]
        if not price_columns:
            error_msg = f"Cannot perform normalization: No price columns found in data. Expected at least one of: {self.config['price_columns']}"
            self.logger.error(error_msg)
            raise ValueError(error_msg)

        # Verify we have sufficient data for each ticker
        for ticker in data["Ticker"].unique():
            ticker_data = data[data["Ticker"] == ticker]
            if len(ticker_data) < 5:  # Arbitrary minimum, but normalization with too few points is problematic
                self.logger.warning(
                    f"Ticker {ticker} has only {len(ticker_data)} data points, which may be insufficient for reliable normalization")

        # Log the columns that will be normalized
        self.logger.info(f"Will normalize the following columns: {price_columns}")

    def generate_statistics(self, data=None) -> Dict:
        """
        Generate summary statistics for the processed data.

        Args:
            data (pd.DataFrame, optional): Input data. If None, use self.normalized_data.

        Returns:
            Dict: Summary statistics
        """
        if data is None:
            data = self.normalized_data

        if data is None:
            self.logger.error("No normalized data available for statistics generation")
            return {}

        self.logger.info("Generating summary statistics")

        # Overall statistics
        statistics  = {
            "total_rows": len(data),
            "tickers": list(data["Ticker"].unique()),
            "columns": list(data.columns),
            "date_range": {
                "start": data["Datetime"].min(),
                "end": data["Datetime"].max()
            },
            "ticker_stats": {},
            "normalization_params": self.normalization_params
        }

        # Per-ticker statistics
        for ticker in data["Ticker"].unique():
            ticker_data = data[data["Ticker"] == ticker]

            ticker_stats = {
                "row_count": len(ticker_data),
                "price_stats": {}
            }

            # Statistics for each price column
            for col in self.config["price_columns"]:
                if col in ticker_data.columns:
                    # Original data statistics (if available)
                    orig_stats = {}
                    if self.cleaned_data is not None:
                        orig_col_data = self.cleaned_data.loc[self.cleaned_data["Ticker"] == ticker, col]
                        orig_stats = {
                            "mean": float(orig_col_data.mean()),
                            "median": float(orig_col_data.median()),
                            "std": float(orig_col_data.std()),
                            "min": float(orig_col_data.min()),
                            "max": float(orig_col_data.max())
                        }

                    # Normalized data statistics
                    norm_col_data = ticker_data[col]
                    norm_stats = {
                        "mean": float(norm_col_data.mean()),
                        "median": float(norm_col_data.median()),
                        "std": float(norm_col_data.std()),
                        "min": float(norm_col_data.min()),
                        "max": float(norm_col_data.max())
                    }

                    ticker_stats["price_stats"][col] = {
                        "original": orig_stats,
                        "normalized": norm_stats
                    }

            statistics["ticker_stats"][ticker] = ticker_stats

        self.stats_summary = statistics
        self.logger.info("Statistics generation complete")

        # Log some key statistics
        self.logger.info(f"Total rows in final dataset: {statistics['total_rows']}")
        self.logger.info(f"Date range: {statistics['date_range']['start']} to {statistics['date_range']['end']}")
        for ticker in statistics["ticker_stats"]:
            self.logger.info(f"{ticker}: {statistics['ticker_stats'][ticker]['row_count']} rows")

        return statistics

    def save_output(self, data=None, file_path=None) -> str:
        """
        Save processed data to CSV.

        Args:
            data (pd.DataFrame, optional): Input data. If None, use self.normalized_data.
            file_path (str, optional): Output file path. If None, use config path.

        Returns:
            str: Path to the saved file
        """
        if data is None:
            data = self.normalized_data

        if data is None:
            self.logger.error("No normalized data available to save")
            return ""

        if file_path is None:
            # Ensure output directory exists
            os.makedirs(self.config["output_dir"], exist_ok=True)
            file_path = os.path.join(self.config["output_dir"], self.config["output_file"])

        try:
            self.logger.info(f"Saving normalized data to {file_path}")
            data.to_csv(file_path, index=False)
            self.logger.info(f"Successfully saved {len(data)} rows to {file_path}")

            # Also save statistics if available
            if self.stats_summary:
                stats_path = os.path.splitext(file_path)[0] + "_stats.json"
                import json

                # Custom JSON encoder that handles various non-serializable types
                class StockDataEncoder(json.JSONEncoder):
                    def default(self, obj):
                        # Handle Numpy types
                        if isinstance(obj, (np.integer, np.int64, np.int32)):
                            return int(obj)
                        if isinstance(obj, (np.floating, np.float64, np.float32)):
                            return float(obj)
                        if isinstance(obj, np.ndarray):
                            return obj.tolist()
                        if isinstance(obj, np.bool_):
                            return bool(obj)

                        # Handle timestamps and datetime objects
                        if hasattr(obj, 'isoformat'):  # datetime, date, etc.
                            return obj.isoformat()

                        # Let the base class handle other types or raise TypeError
                        return super(StockDataEncoder, self).default(obj)

                # Write using the custom encoder
                with open(stats_path, 'w', encoding='utf-8') as f:
                    json.dump(self.stats_summary, f, indent=2, cls=EnhancedJSONEncoder)  # type: ignore
                self.logger.info(f"Saved statistics to {stats_path}")

            return file_path
        except Exception as e:
            self.logger.error(f"Error saving data: {e}")
            return ""

    def process_pipeline(self, input_file=None, output_file=None) -> pd.DataFrame:
        """
        Run the complete processing pipeline.

        Args:
            input_file (str, optional): Input file path. If None, use config path.
            output_file (str, optional): Output file path. If None, use config path.

        Returns:
            pd.DataFrame: Processed and normalized data
        """
        try:
            # Check if parallel processing is enabled in config
            enable_parallel = self.config["parallel_processing"]["enabled"]

            # 1. Load data
            self.logger.info("Step 1: Loading data")
            self.load_data(input_file)

            # Get number of rows and tickers to decide if parallel processing is worthwhile
            if self.data is not None:
                num_rows = len(self.data)
                num_tickers = len(self.data["Ticker"].unique())
                self.logger.info(f"Dataset contains {num_rows} rows and {num_tickers} unique tickers")

                # Auto-enable parallel processing for large datasets if not explicitly disabled
                if num_rows > 100000 or num_tickers > 20:
                    self.logger.info("Large dataset detected, enabling parallel processing automatically")
                    # Update parallel processing settings for large datasets
                    self.config["parallel_processing"]["enabled"] = True
                    self.config["parallel_processing"][
                        "use_processes"] = num_rows > 500000  # Use processes for very large datasets
                    enable_parallel = True  # Update the local variable

            # 2. Analyze distributions to pick best normalization
            self.logger.info("Step 2: Analyzing distributions")
            self.analyze_distributions()

            # 3. Clean data - can benefit from parallel if many tickers
            self.logger.info("Step 3: Cleaning data")
            if enable_parallel and self.data is not None and len(self.data) > self.config["parallel_processing"][
                "min_rows_per_worker"]:
                self.logger.info("Using parallel processing for data cleaning")
                self.cleaned_data = self._clean_data_parallel(self.data)
            else:
                self.cleaned_data = self.clean_data()

            # 4. Normalize data - can also benefit from parallel if many tickers
            self.logger.info("Step 4: Normalizing data")
            if enable_parallel and self.cleaned_data is not None and len(self.cleaned_data) > \
                    self.config["parallel_processing"]["min_rows_per_worker"]:
                self.logger.info("Using parallel processing for normalization")
                self.normalized_data = self._normalize_data_parallel(self.cleaned_data)
            else:
                self.normalized_data = self.normalize_data()

            # 5. Generate statistics
            self.logger.info("Step 5: Generating statistics")
            self.generate_statistics()

            # 6. Save output
            self.logger.info("Step 6: Saving results")
            output_path = self.save_output(file_path=output_file)

            # 7. Clean up temporary resources if parallel processing was used
            if enable_parallel and self.config["parallel_processing"]["cleanup_temp_files"]:
                self.logger.info("Step 7: Cleaning up temporary resources")
                self._cleanup_temp_logs()

            self.logger.info(f"Processing pipeline completed successfully. Results saved to {output_path}")

            return self.normalized_data

        except Exception as e:
            self.logger.error(f"Error in processing pipeline: {e}")
            import traceback
            self.logger.error(traceback.format_exc())

            # Provide some helpful context on what might have gone wrong
            if "required column" in str(e).lower() or "missing" in str(e).lower():
                self.logger.error(
                    "The error appears to be related to missing columns. Please ensure your input data "
                    "contains the required columns 'Ticker', 'Datetime', and at least one price column "
                    "('Open', 'High', 'Low', 'Close')."
                )

            return pd.DataFrame()


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Clean and normalize stock market data.")
    parser.add_argument("--input", type=str, help="Path to input CSV file")
    parser.add_argument("--output", type=str, help="Path to output CSV file")
    parser.add_argument("--config", type=str, help="Path to optional config JSON file")
    parser.add_argument("--log", type=str, help="Path to log file")
    parser.add_argument("--method", type=str, choices=["standard", "minmax", "robust"],
                        help="Normalization method (standard, minmax, robust)")
    parser.add_argument("--skip-outliers", action="store_true",
                        help="Skip outlier detection and handling")
    parser.add_argument("--debug", action="store_true",
                        help="Enable debug logging")
    parser.add_argument("--parallel", action="store_true",
                        help="Enable parallel processing")
    return parser.parse_args()


def main():
    """Main function to run the data cleaning and normalization pipeline."""
    # Parse command line arguments
    args = parse_args()

    # Load config from file if specified
    config = None
    if args.config:
        try:
            import json
            with open(args.config, 'r') as f:
                config = json.load(f)
                print(f"Loaded configuration from {args.config}")
        except Exception as e:
            print(f"Error loading config file: {e}")
            return 1

    # Create processor with default or loaded config
    processor = StockDataProcessor(config)

    # Apply command line overrides to config
    if args.log:
        processor.config["log_file"] = args.log
        # Re-setup logging with new log file
        processor.setup_logging()

    if args.method:
        processor.config["default_normalization"] = args.method
        processor.logger.info(f"Overriding normalization method to {args.method}")

    if args.skip_outliers:
        processor.config["outlier_detection"]["enabled"] = False
        processor.logger.info("Outlier detection disabled via command line")

    if args.parallel:
        processor.config["parallel_processing"]["enabled"] = True
        processor.logger.info("Parallel processing enabled via command line")

    if args.debug:
        processor.logger.setLevel(logging.DEBUG)
        for handler in processor.logger.handlers:
            handler.setLevel(logging.DEBUG)
        processor.logger.debug("Debug logging enabled")

    # Run the processing pipeline
    processor.process_pipeline(args.input, args.output)

    return 0


if __name__ == "__main__":
    sys.exit(main())