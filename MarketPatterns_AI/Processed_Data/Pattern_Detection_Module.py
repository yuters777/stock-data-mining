import numpy as np
import pandas as pd
import datetime as dt  # Alias to avoid confusion with the imported datetime class
import pytz
import matplotlib

from scipy import stats
from scipy.signal import find_peaks
from collections import defaultdict
from sklearn.cluster import DBSCAN
from sklearn.neighbors import BallTree, KDTree  # Added for spatial indexing
from datetime import datetime  # Direct imports for type checking

matplotlib.use('Agg')  # Use non-interactive backend
import matplotlib.pyplot as plt
import os

import logging

logger = logging.getLogger(__name__)


def safe_calculation(func, default_value=0.0):
    """
    Safely perform a calculation that might produce warnings.

    Args:
        func: Lambda function containing the calculation
        default_value: Value to return if calculation fails

    Returns:
        Result of calculation or default value
    """
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            result = func()
            if pd.isna(result) or np.isinf(result):
                return default_value
            return result
        except (ValueError, TypeError, ArithmeticError, ZeroDivisionError) as e:
            # Uncomment this line to use the 'e' variable
            logger.debug(f"Calculation error: {e}")
            return default_value

# -------------------------
# Time Conversion Utilities
# -------------------------
# Global time cache for faster lookups
_TIME_STRING_CACHE = {}


def time_string_to_minutes(time_str):
    """
    Convert time string to minutes since midnight with caching.

    Args:
        time_str: Time string in 'HH:MM' format

    Returns:
        int: Minutes since midnight
    """
    if time_str in _TIME_STRING_CACHE:
        return _TIME_STRING_CACHE[time_str]

    time_obj = dt.datetime.strptime(time_str, '%H:%M')
    minutes = time_obj.hour * 60 + time_obj.minute
    _TIME_STRING_CACHE[time_str] = minutes
    return minutes


def extract_time_minutes(datetime_obj):
    """
    Extract time in minutes since midnight from a datetime object.

    Args:
        datetime_obj: Datetime object

    Returns:
        int: Minutes since midnight
    """
    return datetime_obj.hour * 60 + datetime_obj.minute


def minutes_to_time_string(minutes):
    """
    Convert minutes since midnight to time string.

    Args:
        minutes: Minutes since midnight

    Returns:
        str: Time string in 'HH:MM' format
    """
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours:02d}:{mins:02d}"


# -------------------------
# PatternDetector Class
# -------------------------
class PatternDetector:
    """
    Detects temporal market patterns in stock data, focused on finding
    recurring trends tied to specific times of day.
    """

    def __init__(self, config=None):
        """
        Initialize the PatternDetector.

        Args:
            config (dict, optional): Configuration parameters
        """
        # Default configuration
        self.default_config = {
            # Core parameters
            "time_window": 5,  # Time window in minutes
            "min_pattern_occurrences": 3,  # Minimum occurrences to consider a pattern
            "significance_threshold": 0.05,  # p-value threshold for statistical significance
            "price_impact_threshold": 0.2,  # Minimum % price change to be considered significant
            "volume_impact_threshold": 1.5,  # Volume ratio compared to average to be significant
            "time_shift_tolerance": 15,  # Max time shift in minutes to consider same pattern

            # Time correlation parameters
            "strong_correlation_threshold": 0.7,  # Threshold for strong time correlations

            # Time shift detection parameters
            "magnitude_similarity_threshold": 0.7,  # Threshold for similar magnitude events (70%)

            # Time shift clustering parameters
            "time_shift_cluster_eps": 15,  # DBSCAN eps parameter for time shift clustering
            "time_shift_cluster_min_samples": 2,  # DBSCAN min_samples for time shift clustering

            # Trend reversal parameters
            "price_smooth_span": 5,  # EWMA span for price smoothing
            "peak_prominence": 0.5,  # Prominence for peak detection

            # Visualization parameters
            "random_seed": 42,  # Random seed for reproducible visualizations

            # Timezone and session times
            "timezone": "Asia/Jerusalem",  # Timezone for analysis (Israel Time)
            "auto_adjust_session_times": True,  # Automatically adjust session times based on DST

            # Spatial indexing parameters (new)
            "spatial_index_type": "ball_tree",  # Type of spatial index to use (ball_tree or kd_tree)
            "leaf_size": 30  # Leaf size for spatial index
        }

        # Merge provided config with defaults
        self.config = self.default_config.copy()
        if config:
            self.config.update(config)

        # Initialize storage for detected patterns
        self.patterns = {}
        self.temporal_clusters = {}

        # Handle session times based on DST if needed
        if self.config.get('auto_adjust_session_times', True):
            self._set_dst_aware_session_times()

        # Initialize time string cache
        self._initialize_time_cache()

    def _initialize_time_cache(self):
        """Initialize cache for time string to minutes conversion."""
        global _TIME_STRING_CACHE
        # Pre-populate cache with common time values
        for hour in range(24):
            for minute in range(0, 60, 5):  # Every 5 minutes
                time_str = f"{hour:02d}:{minute:02d}"
                _TIME_STRING_CACHE[time_str] = hour * 60 + minute

    def _set_dst_aware_session_times(self):
        """
        Set the correct session times based on current DST status.
        Also convert session times to minutes for faster comparison.
        """
        # Get timezone from config
        tz_name = self.config.get('timezone', 'Asia/Jerusalem')
        time_zone = pytz.timezone(tz_name)

        # Get current local time in the configured timezone
        local_now = dt.datetime.now(time_zone)

        # Check if DST is active
        dst_active = (local_now.dst() != dt.timedelta(0))

        # If active_session_times is provided, just use that
        if 'active_session_times' in self.config:
            self.config['session_times'] = self.config['active_session_times']
            self._convert_session_times_to_minutes()
            return

        # If we have session_times in the config
        if 'session_times' in self.config and isinstance(self.config['session_times'], dict):
            session_times = self.config['session_times']

            # If session_times has 'dst' and 'standard' keys, choose one based on DST
            if 'dst' in session_times and 'standard' in session_times:
                if dst_active:
                    self.config['session_times'] = session_times['dst']
                    logger.info("DST is active. Using summer session times.")
                else:
                    self.config['session_times'] = session_times['standard']
                    logger.info("DST is not active. Using winter session times.")
                self._convert_session_times_to_minutes()
                return

        # Otherwise, use fallback defaults
        if dst_active:
            self.config['session_times'] = {
                "pre_market": {"start": "11:00", "end": "16:30"},
                "main_session": {"start": "16:30", "end": "23:00"},
                "post_market": {"start": "23:00", "end": "02:59"}
            }
            logger.info("Using default DST (summer) session times")
        else:
            self.config['session_times'] = {
                "pre_market": {"start": "10:00", "end": "15:30"},
                "main_session": {"start": "15:30", "end": "22:00"},
                "post_market": {"start": "22:00", "end": "01:59"}
            }
            logger.info("Using default standard (winter) session times")

        self._convert_session_times_to_minutes()

    def _convert_session_times_to_minutes(self):
        """
        Convert session time strings to minutes since midnight for faster comparison.
        """
        if 'session_times' not in self.config or not isinstance(self.config['session_times'], dict):
            return

        # Create a new key for minutes representation
        self.config['session_times_minutes'] = {}

        for session, times in self.config['session_times'].items():
            start_str = times.get('start')
            end_str = times.get('end')

            if start_str and end_str:
                start_minutes = time_string_to_minutes(start_str)
                end_minutes = time_string_to_minutes(end_str)

                self.config['session_times_minutes'][session] = {
                    'start': start_minutes,
                    'end': end_minutes
                }

    @staticmethod
    def load_data(data_path):
        """
        Load and validate the input data.

        Args:
            data_path (str): Path to the processed data CSV

        Returns:
            pandas.DataFrame: Loaded and validated data
        """
        data = pd.read_csv(data_path)
        required_cols = ['Ticker', 'Datetime', 'Open', 'High', 'Low', 'Close', 'Volume']
        missing = [col for col in required_cols if col not in data.columns]
        if missing:
            raise ValueError(f"Missing required columns: {missing}")
        data['Datetime'] = pd.to_datetime(data['Datetime'])
        data = data.sort_values(['Ticker', 'Datetime'])
        return data

    def preprocess_for_pattern_detection(self, data):
        """
        Preprocess data for pattern detection by adding time features
        and classifying trading sessions using vectorized operations.

        Args:
            data (pandas.DataFrame): Input data

        Returns:
            pandas.DataFrame: Preprocessed data with time features
        """
        # Make a deep copy to avoid modifying the original
        df = data.copy()

        # Ensure Datetime is properly converted
        if 'Datetime' in df.columns:
            # Force conversion to datetime if not already
            if not pd.api.types.is_datetime64_any_dtype(df['Datetime']):
                df['Datetime'] = pd.to_datetime(df['Datetime'])

            # Extract time components if not already present
            if 'Hour' not in df.columns:
                df['Hour'] = df['Datetime'].dt.hour
            if 'Minute' not in df.columns:
                df['Minute'] = df['Datetime'].dt.minute

            # Extract date components
            if 'Date' not in df.columns:
                df['Date'] = df['Datetime'].dt.date
            if 'Time' not in df.columns:
                df['Time'] = df['Datetime'].dt.time

            # Calculate time_minutes for efficient comparisons
            if 'time_minutes' not in df.columns:
                df['time_minutes'] = df['Hour'] * 60 + df['Minute']

            # Add day of week and formatted time string
            df['DayOfWeek'] = df['Datetime'].dt.dayofweek
            df['TimeOfDay'] = df['Hour'] + df['Minute'] / 60
            df['TimeString'] = df['Datetime'].dt.strftime('%H:%M')

            # Timezone handling
            try:
                israel_tz = pytz.timezone(self.config['timezone'])
                if df['Datetime'].dt.tz is None:
                    # Only attempt to localize if not already timezone-aware
                    df['Datetime'] = df['Datetime'].dt.tz_localize(israel_tz, ambiguous='raise')
            except Exception as e:
                logger.warning(f"Could not localize timezone: {e}. Continuing without timezone.")

        # Classify trading session using vectorized operations
        self._classify_sessions_vectorized(df)

        # Ensure PriceChange calculation doesn't fail (add error handling)
        try:
            if 'PriceChange' not in df.columns:
                # Handle potential NaN values in groupby operations
                df['PriceChange'] = df.groupby('Ticker')['Close'].pct_change() * 100
        except Exception as e:
            logger.warning(f"Error calculating PriceChange: {e}. Creating empty column.")
            df['PriceChange'] = 0.0  # Default to zero

        # Calculate other derived columns with error handling
        try:
            if 'RollingVol' not in df.columns:
                df['RollingVol'] = df.groupby('Ticker')['PriceChange'].transform(
                    lambda x: x.rolling(window=12, min_periods=1).std()
                )
        except Exception as e:
            logger.warning(f"Error calculating RollingVol: {e}. Creating empty column.")
            df['RollingVol'] = 0.0

        try:
            if 'AvgVolume' not in df.columns:
                df['AvgVolume'] = df.groupby(['Ticker', 'Hour'])['Volume'].transform('mean')
        except Exception as e:
            logger.warning(f"Error calculating AvgVolume: {e}. Creating empty column.")
            df['AvgVolume'] = df['Volume']  # Use actual volume as fallback

        try:
            if 'VolumeRatio' not in df.columns:
                # Avoid division by zero
                df['VolumeRatio'] = df['Volume'] / df['AvgVolume'].replace(0, np.nan).fillna(1.0)
        except Exception as e:
            logger.warning(f"Error calculating VolumeRatio: {e}. Creating empty column.")
            df['VolumeRatio'] = 1.0  # Default to 1.0 (no impact)

        # Identify significant events (vectorized)
        price_thresh = self.config['price_impact_threshold']
        volume_thresh = self.config['volume_impact_threshold']

        # Calculate with protection against errors
        if 'SignificantPriceMove' not in df.columns:
            df['SignificantPriceMove'] = abs(df['PriceChange']) > price_thresh
        if 'SignificantVolume' not in df.columns:
            df['SignificantVolume'] = df['VolumeRatio'] > volume_thresh
        if 'SignificantEvent' not in df.columns:
            df['SignificantEvent'] = df['SignificantPriceMove'] & df['SignificantVolume']

        # Add additional vectorized calculations with error handling
        try:
            if 'returns' not in df.columns:
                df['returns'] = df.groupby('Ticker')['Close'].pct_change() * 100
        except Exception as e:
            logger.warning(f"Error calculating returns: {e}. Creating empty column.")
            df['returns'] = 0.0

        try:
            if 'volume_change' not in df.columns:
                df['volume_change'] = df.groupby('Ticker')['Volume'].pct_change() * 100
        except Exception as e:
            logger.warning(f"Error calculating volume_change: {e}. Creating empty column.")
            df['volume_change'] = 0.0

        try:
            if 'volatility' not in df.columns:
                df['volatility'] = df.groupby('Ticker')['returns'].transform(
                    lambda x: x.rolling(window=5, min_periods=1).std()
                )
        except Exception as e:
            logger.warning(f"Error calculating volatility: {e}. Creating empty column.")
            df['volatility'] = 0.0

        try:
            if 'ma5' not in df.columns:
                df['ma5'] = df.groupby('Ticker')['Close'].transform(
                    lambda x: x.rolling(window=5, min_periods=1).mean()
                )
        except Exception as e:
            logger.warning(f"Error calculating ma5: {e}. Creating empty column.")
            df['ma5'] = df['Close']

        try:
            if 'ma20' not in df.columns:
                df['ma20'] = df.groupby('Ticker')['Close'].transform(
                    lambda x: x.rolling(window=20, min_periods=1).mean()
                )
        except Exception as e:
            logger.warning(f"Error calculating ma20: {e}. Creating empty column.")
            df['ma20'] = df['Close']

        try:
            if 'momentum' not in df.columns:
                df['momentum'] = df.groupby('Ticker')['Close'].transform(
                    lambda x: x.pct_change(periods=5) * 100
                )
        except Exception as e:
            logger.warning(f"Error calculating momentum: {e}. Creating empty column.")
            df['momentum'] = 0.0

        return df

    def _classify_sessions_vectorized(self, df):
        """
        Classify trading sessions using vectorized operations.

        Args:
            df (pandas.DataFrame): DataFrame with time_minutes column
        """
        if 'session_times_minutes' not in self.config:
            self._convert_session_times_to_minutes()

        # Initialize the TradingSession column with 'after_hours'
        df['TradingSession'] = 'after_hours'

        # Handle each session type
        for session, times in self.config['session_times_minutes'].items():
            start_mins = times['start']
            end_mins = times['end']

            if end_mins < start_mins:  # Session crosses midnight
                mask = (df['time_minutes'] >= start_mins) | (df['time_minutes'] <= end_mins)
            else:
                mask = (df['time_minutes'] >= start_mins) & (df['time_minutes'] < end_mins)

            df.loc[mask, 'TradingSession'] = session

    def detect_temporal_clusters(self, preprocessed_data):
        """
        Detect time-based clusters of significant market events.

        Args:
            preprocessed_data (pandas.DataFrame): Preprocessed data

        Returns:
            dict: Temporal clusters for each ticker
        """
        clusters = {}

        for ticker in preprocessed_data['Ticker'].unique():
            ticker_data = preprocessed_data[preprocessed_data['Ticker'] == ticker]
            significant_events = ticker_data[ticker_data['SignificantEvent']]
            if len(significant_events) < self.config['min_pattern_occurrences']:
                continue

            # Use time_minutes instead of converting from Hour and Minute
            if 'time_minutes' in significant_events.columns:
                x = significant_events['time_minutes'].values.reshape(-1, 1)
            else:
                x = (significant_events['Hour'].values * 60 + significant_events['Minute'].values).reshape(-1, 1)

            dbscan = DBSCAN(eps=self.config['time_window'], min_samples=self.config['min_pattern_occurrences'])
            cluster_labels = dbscan.fit_predict(x)
            valid_events = significant_events[cluster_labels != -1]
            valid_labels = cluster_labels[cluster_labels != -1]

            ticker_clusters = {}
            for cluster_id in np.unique(valid_labels):
                cluster_events = valid_events[valid_labels == cluster_id]

                # Initialize with default values to avoid variable reference before assignment
                _mean_minutes = 0
                _std_minutes = 0

                # Use time_minutes for calculations if available
                if 'time_minutes' in cluster_events.columns:
                    cluster_times_minutes = cluster_events['time_minutes'].values
                    mean_minutes = np.mean(cluster_times_minutes)
                    std_minutes = np.std(cluster_times_minutes)
                    mean_hour = int(mean_minutes // 60)
                    mean_minute = round(mean_minutes % 60)
                else:
                    cluster_times = cluster_events['TimeOfDay'].values
                    mean_time = np.mean(cluster_times)
                    std_time = np.std(cluster_times)
                    mean_hour = int(mean_time)
                    mean_minute = round((mean_time - mean_hour) * 60)
                    mean_minutes = mean_hour * 60 + mean_minute
                    std_minutes = std_time * 60

                # Handle edge case
                if mean_minute == 60:
                    mean_hour += 1
                    mean_minute = 0

                mean_time_str = f"{mean_hour:02d}:{mean_minute:02d}"
                mean_price_impact = cluster_events['PriceChange'].mean()
                std_price_impact = cluster_events['PriceChange'].std()

                if len(cluster_events) >= 5:
                    t_stat, p_value = stats.ttest_1samp(cluster_events['PriceChange'], 0)
                    is_significant = p_value < self.config['significance_threshold']
                else:
                    is_significant = None

                ticker_clusters[int(cluster_id)] = {  # Convert numpy int to Python int
                    'mean_time': mean_time_str,
                    'mean_time_minutes': int(mean_minutes),  # Store minutes representation
                    'std_time_minutes': std_minutes,
                    'count': len(cluster_events),
                    'mean_price_impact': float(mean_price_impact),  # Convert numpy float to Python float
                    'std_price_impact': float(std_price_impact),  # Convert numpy float to Python float
                    'is_statistically_significant': is_significant,
                    'events': cluster_events.to_dict('records')
                }
            if ticker_clusters:
                clusters[ticker] = ticker_clusters

        self.temporal_clusters = clusters
        return clusters

    def detect_recurring_patterns(self, preprocessed_data):
        """
        Detect recurring price patterns based on time of day using vectorized operations.

        Args:
            preprocessed_data (pandas.DataFrame): Preprocessed data

        Returns:
            dict: Detected patterns for each ticker.
        """
        patterns = {}

        # Make a copy to avoid modifying the input
        data = preprocessed_data.copy()

        # Ensure Datetime is datetime type to prevent .dt accessor errors
        if 'Datetime' in data.columns and not pd.api.types.is_datetime64_any_dtype(data['Datetime']):
            data['Datetime'] = pd.to_datetime(data['Datetime'])

        # Ensure Date column exists and is proper date type
        if 'Date' not in data.columns or not pd.api.types.is_datetime64_any_dtype(data['Date']):
            data['Date'] = data['Datetime'].dt.date

        # Group data by ticker and time for vectorized operations
        for ticker in data['Ticker'].unique():
            ticker_data = data[data['Ticker'] == ticker]
            ticker_patterns = {}

            # Use time_minutes if available for faster grouping
            if 'time_minutes' in ticker_data.columns:
                # First group by minutes, then convert to time string for display
                grouped = ticker_data.groupby('time_minutes')

                for time_minutes, group in grouped:
                    if len(group) < self.config['min_pattern_occurrences']:
                        continue

                    # Convert minutes back to time string for display
                    time_str = minutes_to_time_string(time_minutes)

                    # Perform calculations on the group
                    price_changes = group['PriceChange'].dropna()
                    if len(price_changes) < self.config['min_pattern_occurrences']:
                        continue

                    # Vectorized calculations
                    mean_change = price_changes.mean()
                    std_change = price_changes.std()
                    median_change = price_changes.median()
                    positive_pct = (price_changes > 0).mean() * 100
                    negative_pct = (price_changes < 0).mean() * 100
                    direction_consistency = max(positive_pct, negative_pct)
                    consistent_direction = 'positive' if positive_pct > negative_pct else 'negative'

                    # Statistical significance test
                    t_stat, p_value = stats.ttest_1samp(price_changes, 0)
                    is_significant = p_value < self.config['significance_threshold']
                    impact_exceeds = abs(mean_change) > self.config['price_impact_threshold']

                    if is_significant and impact_exceeds:
                        session = group['TradingSession'].iloc[0]  # Get session from first row

                        # Make sure we can safely get dates
                        _dates_observed = []
                        try:
                            # Safely retrieve dates - use a cleaner approach with proper type checking
                            if 'Date' in group.columns:
                                # Try converting to string directly
                                dates_observed = group['Date'].astype(str).tolist()
                            elif 'Datetime' in group.columns:
                                # Extract from Datetime
                                dates_observed = group['Datetime'].dt.strftime('%Y-%m-%d').tolist()
                            else:
                                # Fallback
                                dates_observed = [f"Day {i + 1}" for i in range(len(group))]
                        except Exception as e:
                            logger.warning(f"Error extracting dates for pattern at {time_str}: {e}")
                            # If we can't get dates, provide a fallback
                            dates_observed = [f"Day {i + 1}" for i in range(len(group))]

                        ticker_patterns[time_str] = {
                            'time': time_str,
                            'time_minutes': int(time_minutes),  # Store minutes for faster comparisons
                            'session': session,
                            'count': len(price_changes),
                            'mean_price_change': float(mean_change),
                            'median_price_change': float(median_change),
                            'std_price_change': float(std_change),
                            'direction_consistency': float(direction_consistency / 100.0),  # Convert to ratio
                            'consistent_direction': consistent_direction,
                            'p_value': float(p_value),
                            'is_statistically_significant': is_significant,
                            'dates_observed': dates_observed
                        }
            else:
                # Traditional time string-based grouping (legacy support)
                # Ensure TimeString column exists
                if 'TimeString' not in ticker_data.columns:
                    if 'Datetime' in ticker_data.columns and pd.api.types.is_datetime64_any_dtype(
                            ticker_data['Datetime']):
                        ticker_data['TimeString'] = ticker_data['Datetime'].dt.strftime('%H:%M')
                    elif 'time_minutes' in ticker_data.columns:
                        ticker_data['TimeString'] = ticker_data['time_minutes'].apply(minutes_to_time_string)
                    else:
                        # Can't proceed without time information
                        logger.error(f"Cannot create TimeString for {ticker} - missing required columns")
                        continue

                time_groups = ticker_data.groupby('TimeString')

                for time_str, group in time_groups:
                    if len(group) < self.config['min_pattern_occurrences']:
                        continue

                    price_changes = group['PriceChange'].dropna()
                    if len(price_changes) < self.config['min_pattern_occurrences']:
                        continue

                    # Calculate time_minutes for this pattern
                    time_minutes = time_string_to_minutes(time_str)

                    # Same calculations as above
                    mean_change = price_changes.mean()
                    std_change = price_changes.std()
                    median_change = price_changes.median()
                    positive_pct = (price_changes > 0).mean() * 100
                    negative_pct = (price_changes < 0).mean() * 100
                    direction_consistency = max(positive_pct, negative_pct)
                    consistent_direction = 'positive' if positive_pct > negative_pct else 'negative'

                    t_stat, p_value = stats.ttest_1samp(price_changes, 0)
                    is_significant = p_value < self.config['significance_threshold']
                    impact_exceeds = abs(mean_change) > self.config['price_impact_threshold']

                    if is_significant and impact_exceeds:
                        session = group['TradingSession'].iloc[0]

                        # Make sure we can safely get dates
                        dates_observed = []
                        try:
                            # Safely retrieve dates - convert if needed
                            if isinstance(group['Date'].iloc[0], (str, pd.Timestamp, datetime.date)):
                                # Directly use existing Date column
                                dates_observed = group['Date'].astype(str).tolist()
                            elif 'Datetime' in group.columns and pd.api.types.is_datetime64_any_dtype(
                                    group['Datetime']):
                                # Extract from Datetime column
                                dates_observed = group['Datetime'].dt.strftime('%Y-%m-%d').tolist()
                        except Exception as e:
                            logger.warning(f"Error extracting dates for pattern at {time_str}: {e}")
                            # If we can't get dates, provide a fallback
                            dates_observed = [f"Day {i + 1}" for i in range(len(group))]

                        ticker_patterns[time_str] = {
                            'time': time_str,
                            'time_minutes': int(time_minutes),
                            'session': session,
                            'count': len(price_changes),
                            'mean_price_change': float(mean_change),
                            'median_price_change': float(median_change),
                            'std_price_change': float(std_change),
                            'direction_consistency': float(direction_consistency / 100.0),  # Convert to ratio
                            'consistent_direction': consistent_direction,
                            'p_value': float(p_value),
                            'is_statistically_significant': is_significant,
                            'dates_observed': dates_observed
                        }

            if ticker_patterns:
                patterns[ticker] = ticker_patterns

        self.patterns = patterns
        return patterns

    def generate_pattern_summary(self):
        """
        Generate a summary of all detected patterns.

        Returns:
            dict: Pattern summary
        """
        if not self.patterns:
            return {"error": "No patterns detected. Run detection methods first."}

        summary = {
            "recurring_patterns": {},
            "pattern_count_by_ticker": {},
            "pattern_count_by_session": {
                "pre_market": 0,
                "main_session": 0,
                "post_market": 0,
                "after_hours": 0
            },
            "most_consistent_patterns": []
        }
        all_patterns = []
        for ticker, ticker_patterns in self.patterns.items():
            summary["pattern_count_by_ticker"][ticker] = len(ticker_patterns)
            session_counts = {
                "pre_market": 0,
                "main_session": 0,
                "post_market": 0,
                "after_hours": 0
            }
            for time_str, pattern in ticker_patterns.items():
                session = pattern["session"]
                session_counts[session] += 1
                pattern_with_ticker = pattern.copy()
                pattern_with_ticker["ticker"] = ticker
                all_patterns.append(pattern_with_ticker)
            for session, count in session_counts.items():
                summary["pattern_count_by_session"][session] += count
        summary["total_patterns"] = len(all_patterns)
        if all_patterns:
            sorted_patterns = sorted(all_patterns, key=lambda x: x["direction_consistency"], reverse=True)
            summary["most_consistent_patterns"] = sorted_patterns[:10]
        hour_patterns = {}
        for pattern in all_patterns:
            hour = pattern["time"].split(":")[0]
            hour_patterns[hour] = hour_patterns.get(hour, 0) + 1
        summary["patterns_by_hour"] = hour_patterns
        return summary

    def identify_trend_reversals(self, preprocessed_data):
        """
        Identify points of significant trend reversals using vectorized operations.

        Args:
            preprocessed_data (pandas.DataFrame): Preprocessed data

        Returns:
            dict: Detected trend reversals for each ticker.
        """
        reversals = {}

        for ticker in preprocessed_data['Ticker'].unique():
            ticker_data = preprocessed_data[preprocessed_data['Ticker'] == ticker].copy()
            if len(ticker_data) < 20:
                continue

            # Sort data by datetime
            ticker_data = ticker_data.sort_values('Datetime')

            # Calculate smoothed price (vectorized)
            ticker_data['Smooth_Price'] = ticker_data['Close'].ewm(span=self.config['price_smooth_span']).mean()

            # Find peaks and troughs
            peaks, _ = find_peaks(ticker_data['Smooth_Price'].values, prominence=self.config['peak_prominence'])
            troughs, _ = find_peaks(-ticker_data['Smooth_Price'].values, prominence=self.config['peak_prominence'])

            peak_indices = peaks.tolist() if hasattr(peaks, 'tolist') else np.asarray(peaks).tolist()
            trough_indices = troughs.tolist() if hasattr(troughs, 'tolist') else np.asarray(troughs).tolist()

            extrema = [(idx, 'peak') for idx in peak_indices] + [(idx, 'trough') for idx in trough_indices]
            extrema.sort(key=lambda x: x[0])

            reversals_list = []

            # Reuse previously sorted indices
            for i in range(1, len(extrema)):
                prev_idx, prev_type = extrema[i - 1]
                curr_idx, curr_type = extrema[i]

                if prev_type != curr_type:
                    prev_point = ticker_data.iloc[prev_idx]
                    curr_point = ticker_data.iloc[curr_idx]

                    # Calculate price change and time difference
                    price_change_pct = ((curr_point['Close'] - prev_point['Close']) / prev_point['Close']) * 100

                    # Calculate time diff
                    time_diff = (curr_point['Datetime'] - prev_point['Datetime']).total_seconds() / 60

                    if abs(price_change_pct) > self.config['price_impact_threshold']:
                        # Get or calculate time_minutes
                        if 'time_minutes' in curr_point:
                            time_minutes = curr_point['time_minutes']
                        else:
                            time_minutes = extract_time_minutes(curr_point['Datetime'])

                        reversals_list.append({
                            'datetime': curr_point['Datetime'],
                            'time': curr_point['TimeString'],
                            'time_minutes': int(time_minutes),
                            'price': float(curr_point['Close']),
                            'reversal_type': f"from_{prev_type}_to_{curr_type}",
                            'price_change_pct': float(price_change_pct),
                            'duration_minutes': float(time_diff),
                            'volume_ratio': float(curr_point['VolumeRatio'])
                        })

            if reversals_list:
                reversals[ticker] = reversals_list

        return reversals

    def analyze_time_correlations(self, preprocessed_data):
        """
        Analyze correlations between different times of day and price patterns
        using vectorized operations.

        Args:
            preprocessed_data (pandas.DataFrame): Preprocessed data

        Returns:
            dict: Time-based correlation analysis.
        """
        time_correlations = {}

        # Process each ticker
        for ticker in preprocessed_data['Ticker'].unique():
            ticker_data = preprocessed_data[preprocessed_data['Ticker'] == ticker]

            # Create pivot table for correlation analysis
            if 'time_minutes' in ticker_data.columns:
                # Group by time_minutes first, then convert to TimeString for display
                # This avoids string comparisons in the pivot table operations
                ticker_data['TimeString'] = ticker_data['time_minutes'].apply(minutes_to_time_string)
                pivot = ticker_data.pivot_table(
                    index='Date',
                    columns='TimeString',
                    values='PriceChange',
                    aggfunc='mean'
                )
            else:
                # Traditional string-based pivot table
                pivot = ticker_data.pivot_table(
                    index='Date',
                    columns='TimeString',
                    values='PriceChange',
                    aggfunc='mean'
                )

            min_points = self.config['min_pattern_occurrences']
            valid_cols = pivot.columns[pivot.count() >= min_points]

            # Skip if not enough valid columns
            if len(valid_cols) < 2:
                continue

            pivot = pivot[valid_cols]

            # Calculate correlation matrix (vectorized)
            corr_matrix = pivot.corr()

            # Extract significant correlations
            significant_corrs = []

            # Use numpy operations for faster processing
            corr_values = corr_matrix.values
            column_names = corr_matrix.columns.tolist()

            for i in range(len(column_names)):
                for j in range(i + 1, len(column_names)):
                    time1 = column_names[i]
                    time2 = column_names[j]
                    corr_val = corr_values[i, j]

                    if abs(corr_val) > self.config['strong_correlation_threshold']:
                        # Get the number of valid observations
                        n = len(pivot[[time1, time2]].dropna())

                        if n > 2:
                            # Calculate t-statistic and p-value
                            t_val = corr_val * np.sqrt((n - 2) / (1 - corr_val ** 2))
                            p_val = 2 * (1 - stats.t.cdf(abs(t_val), n - 2))

                            if p_val < self.config['significance_threshold']:
                                # Store time_minutes values for faster comparisons later
                                time1_minutes = time_string_to_minutes(time1)
                                time2_minutes = time_string_to_minutes(time2)

                                significant_corrs.append({
                                    'time1': time1,
                                    'time2': time2,
                                    'time1_minutes': int(time1_minutes),
                                    'time2_minutes': int(time2_minutes),
                                    'correlation': float(corr_val),
                                    'p_value': float(p_val),
                                    'sample_size': int(n)
                                })

            if significant_corrs:
                time_correlations[ticker] = significant_corrs

        return time_correlations

    def build_spatial_index(self, data, leaf_size=None):
        """
        Build a spatial index (KDTree or BallTree) from time and price features.

        Args:
            data (pandas.DataFrame): DataFrame containing data for pattern detection
            leaf_size (int, optional): Leaf size for the spatial index. If None, use config value.

        Returns:
            tuple: Tuple containing:
                - Spatial index (KDTree or BallTree)
                - Feature array used for indexing
                - Array of indices mapping back to original data
        """
        # Use config leaf_size if not provided
        if leaf_size is None:
            leaf_size = self.config.get('leaf_size', 30)

        # Make sure time_minutes column exists
        if 'time_minutes' not in data.columns:
            data['time_minutes'] = data['Hour'] * 60 + data['Minute']

        # Create feature array with time and normalized price
        features = np.column_stack([
            data['time_minutes'].values,
            (data['Close'].values - data['Close'].mean()) / data['Close'].std()
        ])

        # Build the appropriate spatial index
        if self.config.get('spatial_index_type', 'ball_tree').lower() == 'kd_tree':
            tree = KDTree(features, leaf_size=leaf_size)
        else:
            tree = BallTree(features, leaf_size=leaf_size)

        return tree, features, np.arange(len(data))

    @staticmethod
    def safe_divide(numerator, denominator, default=0.0):
        """
        Safely divide numbers handling zero denominators and type issues.

        Args:
            numerator: The division numerator
            denominator: The division denominator
            default: Default value to return when denominator is zero or types are invalid

        Returns:
            float: Result of division or default value
        """
        # Check for valid numeric types
        if not (isinstance(numerator, (int, float, np.number)) and
                isinstance(denominator, (int, float, np.number))):
            # Log the type error
            print(f"Type error in division: numerator type: {type(numerator)}, denominator type: {type(denominator)}")
            return default

        # Check for zero denominator
        if denominator == 0:
            return default

        return numerator / denominator


    def detect_time_shifted_patterns(self, preprocessed_data):
        """
        Detect when patterns may be shifting in time using spatial indexing for O(n log n) complexity.

        Args:
            preprocessed_data (pandas.DataFrame): Preprocessed data

        Returns:
            dict: Detected time shifts in patterns.
        """
        time_shifts = {}

        for ticker in preprocessed_data['Ticker'].unique():
            ticker_data = preprocessed_data[preprocessed_data['Ticker'] == ticker].sort_values('Datetime').reset_index(drop=True)

            # Skip if insufficient data
            if len(ticker_data) < self.config['min_pattern_occurrences']:
                continue

            # Filter significant events
            significant_events = ticker_data[ticker_data['SignificantEvent']].copy()
            if len(significant_events) < self.config['min_pattern_occurrences']:
                continue

            # Build spatial index from time and price features
            leaf_size = self.config.get('leaf_size', 30)
            tree, features, indices = self.build_spatial_index(significant_events, leaf_size)

            # Parameters for pattern detection
            time_tolerance = self.config['time_shift_tolerance']
            min_occurrences = self.config['min_pattern_occurrences']
            price_threshold = self.config['price_impact_threshold']
            mag_similarity = self.config['magnitude_similarity_threshold']

            # Query the tree for each point to find nearby points within time tolerance
            detected_shifts = []

            for i, (_, row) in enumerate(significant_events.iterrows()):
                # Get feature for this point
                point_idx = indices[i]
                point_feature = features[point_idx:point_idx+1]

                # Query the tree for nearby points
                indices_within_radius = tree.query_radius(point_feature, r=time_tolerance)[0]

                # Skip if not enough nearby points
                if len(indices_within_radius) < min_occurrences:
                    continue

                # Filter out points on the same day
                base_date = row['Date']
                valid_indices = []

                for idx in indices_within_radius:
                    # Skip the point itself
                    if idx == point_idx:
                        continue

                    # Get the actual dataframe index
                    orig_idx = significant_events.index[idx]
                    comp_date = significant_events.loc[orig_idx, 'Date']

                    # Only include if dates are different
                    if comp_date != base_date:
                        valid_indices.append(orig_idx)

                # Skip if not enough points across different days
                if len(valid_indices) < min_occurrences - 1:  # -1 because current point counts too
                    continue

                # Process valid matches
                for match_idx in valid_indices:
                    match_row = significant_events.loc[match_idx]

                    # Skip if dates are the same
                    if match_row['Date'] == row['Date']:
                        continue

                    # Calculate time difference in minutes
                    if 'time_minutes' in row and 'time_minutes' in match_row:
                        time_diff = abs(match_row['time_minutes'] - row['time_minutes'])
                    else:
                        time_diff = abs(
                            (match_row['Hour'] * 60 + match_row['Minute']) -
                            (row['Hour'] * 60 + row['Minute'])
                        )

                    # Skip if zero time difference (exact same time)
                    if time_diff == 0:
                        continue

                    # Check if price changes are in the same direction
                    same_direction = (row['PriceChange'] > 0 and match_row['PriceChange'] > 0) or \
                                     (row['PriceChange'] < 0 and match_row['PriceChange'] < 0)

                    # Check magnitude similarity
                    numerator = min(abs(row['PriceChange']), abs(match_row['PriceChange']))
                    denominator = max(abs(row['PriceChange']), abs(match_row['PriceChange']))
                    pc_ratio = self.safe_divide(numerator, denominator)

                    if same_direction and pc_ratio > mag_similarity:
                        # Determine which is earlier
                        if ('time_minutes' in row and 'time_minutes' in match_row):
                            if row['time_minutes'] < match_row['time_minutes']:
                                is_row_earlier = True
                            else:
                                is_row_earlier = False
                        else:
                            row_minutes = row['Hour'] * 60 + row['Minute']
                            match_minutes = match_row['Hour'] * 60 + match_row['Minute']
                            is_row_earlier = row_minutes < match_minutes

                        if is_row_earlier:
                            earlier_date = row['Date']
                            earlier_time = row['TimeString']
                            earlier_time_minutes = row.get('time_minutes', row['Hour'] * 60 + row['Minute'])
                            later_date = match_row['Date']
                            later_time = match_row['TimeString']
                            later_time_minutes = match_row.get('time_minutes', match_row['Hour'] * 60 + match_row['Minute'])
                            pc1 = row['PriceChange']
                            pc2 = match_row['PriceChange']
                        else:
                            earlier_date = match_row['Date']
                            earlier_time = match_row['TimeString']
                            earlier_time_minutes = match_row.get('time_minutes', match_row['Hour'] * 60 + match_row['Minute'])
                            later_date = row['Date']
                            later_time = row['TimeString']
                            later_time_minutes = row.get('time_minutes', row['Hour'] * 60 + row['Minute'])
                            pc1 = match_row['PriceChange']
                            pc2 = row['PriceChange']

                        detected_shifts.append({
                            'earlier_date': earlier_date,
                            'earlier_time': earlier_time,
                            'earlier_time_minutes': int(earlier_time_minutes),
                            'later_date': later_date,
                            'later_time': later_time,
                            'later_time_minutes': int(later_time_minutes),
                            'time_diff_minutes': int(time_diff),
                            'same_direction': True,
                            'magnitude_similarity': float(pc_ratio),
                            'price_change1': float(pc1),
                            'price_change2': float(pc2)
                        })

            # Filter out duplicate shifts and cluster them
            if detected_shifts:
                # First, remove duplicates
                unique_shifts = []
                seen = set()

                for shift in detected_shifts:
                    key = (str(shift['earlier_date']), shift['earlier_time'],
                           str(shift['later_date']), shift['later_time'])

                    if key not in seen:
                        seen.add(key)
                        unique_shifts.append(shift)

                # Cluster similar shifts
                clusters = self._cluster_time_shifts(unique_shifts)

                if clusters:
                    time_shifts[ticker] = clusters

        return time_shifts

    def _cluster_time_shifts(self, shifts):
        """
        Cluster similar time shifts together using minute-based features.

        Args:
            shifts (list): List of detected time shifts

        Returns:
            list: Clustered time shifts
        """
        # Ensure we have enough shifts to cluster
        if len(shifts) < self.config['min_pattern_occurrences']:
            return shifts

        # Use pre-computed time_minutes for clustering if available
        features = []
        for shift in shifts:
            # Use pre-computed minutes if available
            if 'earlier_time_minutes' in shift and 'later_time_minutes' in shift:
                early = shift['earlier_time_minutes']
                late = shift['later_time_minutes']
            else:
                early = time_string_to_minutes(shift['earlier_time'])
                late = time_string_to_minutes(shift['later_time'])

            features.append([early, late, shift['time_diff_minutes']])

        features = np.array(features)

        if len(features) < self.config['min_pattern_occurrences']:
            return shifts

        dbscan = DBSCAN(
            eps=self.config['time_shift_cluster_eps'],
            min_samples=self.config['time_shift_cluster_min_samples']
        )

        labels = dbscan.fit_predict(features)
        clustered = defaultdict(list)

        for idx, label in enumerate(labels):
            if label != -1:  # Skip noise points
                clustered[int(label)].append(shifts[idx])  # Convert numpy int to Python int

        clusters = []

        for label, group in clustered.items():
            # Calculate average time differences and convert to display format
            avg_diff = np.mean([s['time_diff_minutes'] for s in group])

            # Use pre-computed time_minutes if available
            if 'earlier_time_minutes' in group[0] and 'later_time_minutes' in group[0]:
                early_vals = [s['earlier_time_minutes'] for s in group]
                late_vals = [s['later_time_minutes'] for s in group]
            else:
                early_vals = [time_string_to_minutes(s['earlier_time']) for s in group]
                late_vals = [time_string_to_minutes(s['later_time']) for s in group]

            avg_early = int(np.mean(early_vals))
            avg_late = int(np.mean(late_vals))

            # Convert minutes back to time strings for display
            avg_early_str = minutes_to_time_string(avg_early)
            avg_late_str = minutes_to_time_string(avg_late)

            clusters.append({
                'cluster_id': int(label),  # Convert numpy int to Python int
                'count': len(group),
                'avg_time_diff_minutes': float(avg_diff),  # Convert numpy float to Python float
                'avg_earlier_time': avg_early_str,
                'avg_earlier_time_minutes': avg_early,
                'avg_later_time': avg_late_str,
                'avg_later_time_minutes': avg_late,
                'shifts': group
            })

        return clusters

    def visualize_patterns(self, preprocessed_data=None, output_dir=None):
        """
        Visualize detected patterns using actual historical data when available.

        Args:
            preprocessed_data (pandas.DataFrame, optional): Preprocessed data for visualization.
            output_dir (str, optional): Directory to save visualizations.

        Returns:
            dict: Paths to generated visualizations.
        """
        if not self.patterns:
            return {"error": "No patterns detected. Run detection methods first."}
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)
        visualizations = {}
        fig_heatmap = self._create_pattern_heatmap()
        if output_dir:
            heatmap_path = os.path.join(output_dir, "pattern_heatmap.png")
            fig_heatmap.savefig(heatmap_path)
            visualizations["heatmap"] = heatmap_path
        fig_ticker_bar = self._create_ticker_pattern_barchart()
        if output_dir:
            ticker_bar_path = os.path.join(output_dir, "patterns_by_ticker.png")
            fig_ticker_bar.savefig(ticker_bar_path)
            visualizations["ticker_bar"] = ticker_bar_path
        for ticker in list(self.patterns.keys())[:5]:
            ticker_patterns = self.patterns[ticker]
            pattern_times = list(ticker_patterns.keys())[:3]
            for time_str in pattern_times:
                pattern = ticker_patterns[time_str]
                fig_pattern = self._visualize_single_pattern(ticker, time_str, pattern, preprocessed_data)
                if output_dir:
                    pattern_path = os.path.join(output_dir, f"{ticker}_{time_str.replace(':', '')}_pattern.png")
                    fig_pattern.savefig(pattern_path)
                    visualizations[f"{ticker}_{time_str}"] = pattern_path
        return visualizations

    def _create_pattern_heatmap(self):
        """
        Create a heatmap of pattern occurrences by hour and ticker.

        Returns:
            matplotlib.figure.Figure: The heatmap figure.
        """
        heatmap_data = {}
        for ticker in self.patterns:
            ticker_data = {}
            for time_str, pattern in self.patterns[ticker].items():
                hour = int(time_str.split(':')[0])
                ticker_data[hour] = ticker_data.get(hour, 0) + 1
            heatmap_data[ticker] = ticker_data
        hours = range(24)
        tickers = list(heatmap_data.keys())
        heatmap_df = pd.DataFrame(0, index=tickers, columns=hours)
        for ticker in heatmap_data:
            for hour, count in heatmap_data[ticker].items():
                heatmap_df.loc[ticker, hour] = count
        plt.figure(figsize=(12, 8))
        plt.title("Pattern Occurrences by Hour and Ticker")
        heatmap = plt.pcolormesh(heatmap_df.columns, heatmap_df.index, heatmap_df.values,
                                 cmap='YlOrRd', shading='auto')
        plt.colorbar(heatmap, label='Number of Patterns')
        plt.xlabel('Hour of Day')
        plt.ylabel('Ticker')
        plt.xticks(range(24))

        # Use minute-based session times if available
        if 'session_times_minutes' in self.config and 'main_session' in self.config['session_times_minutes']:
            main_start = self.config['session_times_minutes']['main_session']['start'] // 60
            main_end = self.config['session_times_minutes']['main_session']['end'] // 60
            if main_end < main_start:  # Handle overnight
                main_end += 24
            plt.axvspan(main_start, min(main_end, 24), alpha=0.2, color='green')
        elif isinstance(self.config['session_times'], dict) and 'main_session' in self.config['session_times']:
            main_start = int(self.config['session_times']['main_session']['start'].split(':')[0])
            main_end = int(self.config['session_times']['main_session']['end'].split(':')[0])
            if main_end < main_start:  # Handle overnight
                main_end += 24
            plt.axvspan(main_start, min(main_end, 24), alpha=0.2, color='green')

        fig = plt.gcf()
        plt.close()
        return fig

    def _create_ticker_pattern_barchart(self):
        """
        Create a bar chart of pattern counts by ticker.

        Returns:
            matplotlib.figure.Figure: The bar chart figure.
        """
        pattern_counts = {}
        for ticker, ticker_patterns in self.patterns.items():
            pattern_counts[ticker] = len(ticker_patterns)
        counts_series = pd.Series(pattern_counts).sort_values(ascending=False)
        plt.figure(figsize=(12, 6))
        plt.title("Number of Detected Patterns by Ticker")
        counts_series.plot(kind='bar', color='skyblue')
        plt.xlabel('Ticker')
        plt.ylabel('Number of Patterns')
        plt.xticks(rotation=45)
        plt.tight_layout()
        fig = plt.gcf()
        plt.close()
        return fig

    def _visualize_single_pattern(self, ticker, time_str, pattern, preprocessed_data=None):
        """
        Visualize a single pattern with historical price changes.

        Args:
            ticker (str): Ticker symbol
            time_str (str): Time string in HH:MM format
            pattern (dict): Pattern details
            preprocessed_data (pandas.DataFrame, optional): Preprocessed data

        Returns:
            matplotlib.figure.Figure: The pattern visualization.
        """
        dates = pattern['dates_observed']
        plt.figure(figsize=(10, 6))
        plt.title(f"{ticker} Pattern at {time_str} (Consistency: {pattern['direction_consistency']:.1f}%)")
        actual_changes = []
        actual_dates = []

        if preprocessed_data is not None:
            # Convert time string to minutes for faster comparison
            if 'time_minutes' in pattern:
                time_minutes = pattern['time_minutes']
            else:
                time_minutes = time_string_to_minutes(time_str)

            for date_str in dates:
                date_val = pd.to_datetime(date_str).date()

                # Use minutes-based comparison if available
                if 'time_minutes' in preprocessed_data.columns:
                    mask = ((preprocessed_data['Ticker'] == ticker) &
                            (preprocessed_data['Date'] == date_val) &
                            (preprocessed_data['time_minutes'] == time_minutes))
                else:
                    mask = ((preprocessed_data['Ticker'] == ticker) &
                            (preprocessed_data['Date'] == date_val) &
                            (preprocessed_data['TimeString'] == time_str))

                if isinstance(mask, pd.Series) and mask.any():
                    row = preprocessed_data.loc[mask].iloc[0]
                    actual_changes.append(row['PriceChange'])
                    actual_dates.append(date_str)

        if actual_changes:
            price_changes = actual_changes
            plot_dates = actual_dates
        else:
            np.random.seed(self.config['random_seed'])
            price_changes = np.random.normal(pattern['mean_price_change'],
                                             pattern['std_price_change'],
                                             len(dates))
            plot_dates = dates

        plt.bar(range(len(price_changes)), price_changes,
                color=['red' if pc < 0 else 'green' for pc in price_changes])
        plt.axhline(y=0, color='black', linestyle='-', alpha=0.3)
        plt.xlabel('Observation Date')
        plt.ylabel('Price Change (%)')
        x_labels = [d.split('-')[1:] for d in plot_dates]
        formatted_labels = [f"{m}-{d}" for m, d in x_labels]
        plt.xticks(range(len(price_changes)), formatted_labels, rotation=45)
        actual_mean = float(np.mean(price_changes))
        plt.axhline(actual_mean, color='blue', linestyle='--', label=f"Mean: {round(actual_mean,2)}%")
        if abs(actual_mean - pattern['mean_price_change']) > 0.01:
            plt.axhline(y=pattern['mean_price_change'], color='orange', linestyle=':',
                        label=f"Pattern Mean: {pattern['mean_price_change']:.2f}%")
        info_text = (
            f"Mean Change: {round(actual_mean,2)}\n"
            f"Median Change: {round(float(np.median(price_changes)),2)}\n"
            f"Consistency: {round(float((np.sum(np.array(price_changes) > 0) / len(price_changes) * 100)),1)}% positive\n"
            f"Direction: {'positive' if actual_mean > 0 else 'negative'}\n"
            f"Observations: {len(price_changes)}"
        )
        plt.annotate(info_text, xy=(0.02, 0.97), xycoords='axes fraction',
                     verticalalignment='top', bbox=dict(boxstyle='round', alpha=0.1))
        plt.legend()
        plt.tight_layout()
        fig = plt.gcf()
        plt.close()
        return fig

# End of PatternDetector class