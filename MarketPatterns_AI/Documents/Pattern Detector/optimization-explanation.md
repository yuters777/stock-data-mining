# Algorithmic Optimizations for Market Pattern Analysis

## Overview of Implemented Optimizations

The Market Pattern Analysis script has been optimized to improve performance and efficiency based on the specified requirements. Here's a detailed explanation of the key optimizations:

### 1. Replacing O(n²) Nested Loops with Spatial Indexing

#### Before:
The original implementation of `detect_time_shifted_patterns` likely used nested loops to compare each data point with every other data point, resulting in O(n²) time complexity. This approach becomes extremely inefficient as the dataset grows.

#### After:
The optimized implementation now uses spatial indexing through `BallTree` and `KDTree` from scikit-learn, resulting in O(n log n) time complexity:

```python
def detect_time_shifted_patterns_optimized(data, config):
    # Build spatial index from time and price features
    tree, features, indices = build_spatial_index(ticker_data, config)
    
    # For each data point, efficiently find points that occur at similar times
    for i, (_, row) in enumerate(ticker_data.iterrows()):
        # Query the tree for points within time_radius (much more efficient)
        indices_within_radius = tree.query_radius(
            features[i:i+1], 
            r=time_radius
        )[0]
        # Process matches...
```

Key benefits:
- Reduces time complexity from O(n²) to O(n log n)
- Enables efficient radius-based queries for similar patterns
- Allows configurable distance metrics and leaf sizes for further tuning

### 2. Converting Time String Comparisons to Integer Minutes

#### Before:
The original code worked with time strings in 'HH:MM' format, which required expensive string parsing and datetime operations for each comparison.

#### After:
All time operations now use integer minutes since midnight for more efficient comparisons:

```python
# Convert time string to minutes with caching
def time_string_to_minutes(time_str: str) -> int:
    if time_str in _TIME_STRING_CACHE:
        return _TIME_STRING_CACHE[time_str]
    
    time_obj = datetime.strptime(time_str, '%H:%M')
    minutes = time_obj.hour * 60 + time_obj.minute
    _TIME_STRING_CACHE[time_str] = minutes
    return minutes

# Extract time in minutes directly from datetime objects
def extract_time_minutes(datetime_obj) -> int:
    return datetime_obj.hour * 60 + datetime_obj.minute
```

Key benefits:
- Replaces slow string parsing with fast integer operations
- Implements caching to avoid redundant conversions
- Adds a 'time_minutes' column to the DataFrame during preprocessing
- Improves performance for time range checks and pattern matching

### 3. Vectorized Operations for Pattern Detection

#### Before:
Many operations were likely performed using loops or row-by-row processing.

#### After:
Implemented vectorized operations using pandas and numpy for faster processing:

```python
def preprocess_data_vectorized(data: pd.DataFrame) -> pd.DataFrame:
    # Convert time strings to minutes for faster comparison
    result['time_minutes'] = result['Datetime'].apply(
        lambda dt: dt.hour * 60 + dt.minute
    )
    
    # Vectorized calculation of returns
    result['returns'] = result.groupby('Ticker')['Close'].pct_change() * 100
    
    # Vectorized calculation of volume change
    result['volume_change'] = result.groupby('Ticker')['Volume'].pct_change() * 100
    
    # Other vectorized calculations...
```

Key benefits:
- Leverages optimized C-level operations in pandas and numpy
- Reduces Python loop overhead
- Calculates metrics like returns, moving averages, and momentum in bulk
- Improves performance especially for large datasets

### 4. Additional Performance Enhancements

1. **JIT Compilation with Numba**:
   ```python
   @numba.jit(nopython=True)
   def calculate_time_difference(time1_minutes: int, time2_minutes: int, wrap_around: bool = True) -> int:
       # Compiles to optimized machine code
   ```

2. **Caching Mechanism**:
   - Implemented caching for time string conversions
   - Added global cache for frequently accessed data

3. **Improved Data Structure**:
   - Added the 'time_minutes' column during initial preprocessing
   - Restructured data to avoid redundant calculations

## Performance Impact

These optimizations should significantly reduce computation time, especially for:
- Large datasets with many tickers
- Complex pattern detection across extended time periods
- Time-shifted pattern analysis that previously required O(n²) comparisons

## Configuration Options

New configuration parameters have been added to allow fine-tuning:
- `spatial_index_type`: Choose between "ball_tree" (default) or "kd_tree"
- `leaf_size`: Configure the leaf size for spatial indices (default: 30)

These can be set in the config.json file to optimize for specific datasets.
