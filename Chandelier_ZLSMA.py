import pandas as pd
import numpy as np
from scipy import stats

def linreg(data, length, offset=0):
    """
    Calculate Linear Regression (LSMA - Least Squares Moving Average)
    Enhanced to handle NaN values properly
    
    Parameters:
    data: pandas Series - input data (typically close prices)
    length: int - period for linear regression
    offset: int - offset for the regression line (default 0)
    
    Returns:
    pandas Series - linear regression values
    """
    result = np.full(len(data), np.nan)
    
    for i in range(len(data)):
        if i < length - 1:
            result[i] = np.nan
        else:
            # Get the window of data
            window_data = data.iloc[i-length+1:i+1]
            
            # Skip if there are any NaN values in the window
            if window_data.isna().any():
                result[i] = np.nan
                continue
                
            window = window_data.values
            
            # Create x values (time indices)
            x = np.arange(length)
            
            try:
                # Calculate linear regression
                slope, intercept, _, _, _ = stats.linregress(x, window)
                
                # Calculate the value at the end of the period plus offset
                reg_value = slope * (length - 1 + offset) + intercept
                result[i] = reg_value
            except:
                result[i] = np.nan
    
    return pd.Series(result, index=data.index)

def zlsma(data, length=32, offset=0):
    """
    Calculate Zero Lag LSMA - Fixed version matching Pine Script logic
    
    Pine Script equivalent:
    lsma = linreg(src, length, offset)
    lsma2 = linreg(lsma, length, offset)
    eq = lsma - lsma2
    zlsma = lsma + eq
    
    Parameters:
    data: pandas Series - input data (typically close prices)
    length: int - period for ZLSMA calculation (default 32, matching Pine Script)
    offset: int - offset parameter (default 0)
    
    Returns:
    pandas Series - ZLSMA values
    """
    # Check if we have enough data
    min_required = 2 * length - 1
    if len(data) < min_required:
        print(f"Warning: Need at least {min_required} data points for ZLSMA with length {length}")
        print(f"Available data points: {len(data)}")
        # Return NaN series if insufficient data
        return pd.Series(np.nan, index=data.index)
    
    print(f"Calculating ZLSMA with length {length}...")
    
    # Step 1: Calculate first LSMA
    lsma = linreg(data, length, offset)
    print(f"First LSMA calculated. Valid values: {(~lsma.isna()).sum()}")
    
    # Step 2: Calculate second LSMA from the first LSMA
    lsma2 = linreg(lsma, length, offset)
    print(f"Second LSMA calculated. Valid values: {(~lsma2.isna()).sum()}")
    
    # Step 3: Calculate the difference (eq = lsma - lsma2)
    eq = lsma - lsma2
    
    # Step 4: Calculate ZLSMA (zlsma = lsma + eq)
    zlsma_result = lsma + eq
    
    print(f"ZLSMA calculated. Valid values: {(~zlsma_result.isna()).sum()}")
    
    return zlsma_result

def calculate_zlsma(in_df, close_column='close', timestamp_column=None, length=32, plot=True):
    """
    Load DataFrame, calculate ZLSMA, and optionally plot the results
    
    Parameters:
    in_df: pandas DataFrame - input DataFrame
    close_column: str - name of the close price column (default 'close')
    timestamp_column: str - name of the timestamp column (if None, will try to auto-detect)
    length: int - ZLSMA length parameter (default 32, matching Pine Script)
    plot: bool - whether to plot the results (default True)
    
    Returns:
    pandas DataFrame - DataFrame with original data and ZLSMA column
    """
    # Load the DataFrame
    df = in_df.copy()
    
    # Try to find timestamp column if not specified
    if timestamp_column is None:
        # Common timestamp column names
        timestamp_candidates = ['timestamp', 'time', 'date', 'datetime', 'Date', 'Time', 'DateTime']
        for col in timestamp_candidates:
            if col in df.columns:
                timestamp_column = col
                break
    
    # Convert timestamp column to datetime if found
    if timestamp_column and timestamp_column in df.columns:
        df[timestamp_column] = pd.to_datetime(df[timestamp_column])
        x_axis = df[timestamp_column]
        x_label = 'Time'
    else:
        # Use index if no timestamp column found
        x_axis = df.index
        x_label = 'Candle Index'
        print("Warning: No timestamp column found, using index for X-axis")
        print(f"Available columns: {list(df.columns)}")
    
    print(f"Data loaded: {len(df)} rows")
    print(f"Calculating ZLSMA with length {length}...")
    
    # Calculate minimum required data points
    min_required = 2 * length - 1
    print(f"Note: ZLSMA needs at least {min_required} rows to start producing values")
    
    # Calculate ZLSMA
    df[f'zlsma_{length}'] = zlsma(df[close_column], length=length)
    
    # Check how many valid ZLSMA values we have
    valid_zlsma = df[f'zlsma_{length}'].dropna()
    print(f"Valid ZLSMA values: {len(valid_zlsma)} out of {len(df)} rows")
    
    if len(valid_zlsma) == 0:
        print("ERROR: No valid ZLSMA values calculated!")
        print(f"Make sure you have at least {min_required} data points.")
    
    return df

# Keep the rest of the functions unchanged...
def calculate_atr(df: pd.DataFrame, length: int = 1) -> pd.Series:
    """
    Calculate Average True Range (ATR). Returns a pd.Series.
    """
    high_low = df['high'] - df['low']
    high_close_prev = (df['high'] - df['close'].shift()).abs()
    low_close_prev = (df['low'] - df['close'].shift()).abs()

    true_range = pd.concat([high_low, high_close_prev, low_close_prev], axis=1).max(axis=1)
    atr = true_range.rolling(window=length).mean()
    return atr

def chandelier_exit(
    df: pd.DataFrame,
    atr_period: int = 1,
    atr_multiplier: float = 2.0,
    use_close: bool = True
) -> pd.DataFrame:
    """
    Given a DataFrame with at least 'high','low','close', this returns a copy of `df` with:
    - 'atr'
    - 'long_stop'
    - 'short_stop'
    - 'direction'
    - 'chandelier_exit'
    - 'buy_signal' (1 for entire duration while direction is long)
    - 'sell_signal' (1 for entire duration while direction is short)
    """
    df_result = df.copy()

    # Compute ATR
    atr_raw = calculate_atr(df, length=atr_period)
    atr = atr_raw * atr_multiplier

    # Compute rolling highest/lowest
    if use_close:
        highest = df['close'].rolling(window=atr_period).max()
        lowest = df['close'].rolling(window=atr_period).min()
    else:
        highest = df['high'].rolling(window=atr_period).max()
        lowest = df['low'].rolling(window=atr_period).min()

    n = len(df)
    long_stop_array = np.full(n, np.nan)
    short_stop_array = np.full(n, np.nan)
    direction_array = np.full(n, 1)

    for i in range(n):
        if pd.isna(atr.iloc[i]) or pd.isna(highest.iloc[i]) or pd.isna(lowest.iloc[i]):
            continue

        curr_long = highest.iloc[i] - atr.iloc[i]
        curr_short = lowest.iloc[i] + atr.iloc[i]

        if i == 0:
            long_stop_array[i] = curr_long
            short_stop_array[i] = curr_short
            direction_array[i] = 1
        else:
            prev_long = long_stop_array[i - 1] if not pd.isna(long_stop_array[i - 1]) else curr_long
            if df['close'].iloc[i - 1] > prev_long:
                long_stop_array[i] = max(curr_long, prev_long)
            else:
                long_stop_array[i] = curr_long

            prev_short = short_stop_array[i - 1] if not pd.isna(short_stop_array[i - 1]) else curr_short
            if df['close'].iloc[i - 1] < prev_short:
                short_stop_array[i] = min(curr_short, prev_short)
            else:
                short_stop_array[i] = curr_short

            prev_short_val = short_stop_array[i - 1] if not pd.isna(short_stop_array[i - 1]) else curr_short
            prev_long_val = long_stop_array[i - 1] if not pd.isna(long_stop_array[i - 1]) else curr_long

            if df['close'].iloc[i] > prev_short_val:
                direction_array[i] = 1
            elif df['close'].iloc[i] < prev_long_val:
                direction_array[i] = -1
            else:
                direction_array[i] = direction_array[i - 1]

    df_result['atr'] = atr
    df_result['long_stop'] = long_stop_array
    df_result['short_stop'] = short_stop_array
    df_result['direction'] = direction_array
    df_result['chandelier_exit'] = np.where(direction_array == 1, long_stop_array, short_stop_array)
    df_result['buy_signal'] = (df_result['direction'] == 1).astype(int)
    df_result['sell_signal'] = (df_result['direction'] == -1).astype(int)

    return df_result

def calculate_chandelier(
    in_df: pd.DataFrame,
    atr_period: int = 1,
    atr_multiplier: float = 2.0,
    timestamp_column: str = None,
    use_close: bool = True,
    plot: bool = False
) -> pd.DataFrame:
    """
    Given a DataFrame `in_df` with at least ['high','low','close'], this function:
    1. Attempts to detect a timestamp column among common names.
    2. If none is found, checks if the index is a DatetimeIndex:
        - If yes, uses index as 'timestamp' silently.
        - If no, injects index as 'timestamp' with a warning.
    3. Calls `chandelier_exit(...)` internally.
    4. Returns a DataFrame with all original columns plus:
        ['timestamp','atr','long_stop','short_stop','direction',
        'chandelier_exit','buy_signal','sell_signal'].
    """
    df = in_df.copy()

    # Detect timestamp column
    if timestamp_column is None:
        for cand in ['timestamp', 'time', 'date', 'datetime', 'Date', 'Time', 'DateTime']:
            if cand in df.columns:
                timestamp_column = cand
                break

    if timestamp_column is not None and timestamp_column in df.columns:
        df[timestamp_column] = pd.to_datetime(df[timestamp_column])
        df['timestamp'] = df[timestamp_column]
    else:
        if isinstance(df.index, pd.DatetimeIndex):
            df['timestamp'] = df.index
        else:
            df['timestamp'] = df.index
            print("Warning: No timestamp column found in Chandelier. Using index as 'timestamp'.")

    # Verify required columns
    missing = [c for c in ['high', 'low', 'close'] if c not in df.columns]
    if missing:
        raise ValueError(f"calculate_chandelier: Missing required columns: {missing}")

    # Compute Chandelier Exit
    df_ch = chandelier_exit(df, atr_period=atr_period, atr_multiplier=atr_multiplier, use_close=use_close)

    # Ensure timestamp is included
    if 'timestamp' not in df_ch.columns:
        df_ch['timestamp'] = df_ch.index

    return df_ch

def merge_zlsma_chandelier(
    df_zlsma: pd.DataFrame,
    df_chandelier: pd.DataFrame,
    on: str = "timestamp",
    how: str = "inner"
) -> pd.DataFrame:
    """
    Simple merge of two DataFrames on timestamp column.
    """
    df_zlsma_clean = df_zlsma.copy()
    df_chandelier_clean = df_chandelier.copy()
    
    # Reset index to avoid ambiguity with timestamp
    if df_zlsma_clean.index.name == on or on in str(df_zlsma_clean.index.names):
        if on in df_zlsma_clean.columns:
            df_zlsma_clean = df_zlsma_clean.reset_index(drop=True)
        else:
            df_zlsma_clean = df_zlsma_clean.reset_index()
    
    if df_chandelier_clean.index.name == on or on in str(df_chandelier_clean.index.names):
        if on in df_chandelier_clean.columns:
            df_chandelier_clean = df_chandelier_clean.reset_index(drop=True)
        else:
            df_chandelier_clean = df_chandelier_clean.reset_index()
    
    # Remove duplicate columns
    if df_zlsma_clean.columns.duplicated().any():
        df_zlsma_clean = df_zlsma_clean.loc[:, ~df_zlsma_clean.columns.duplicated()]
    
    if df_chandelier_clean.columns.duplicated().any():
        df_chandelier_clean = df_chandelier_clean.loc[:, ~df_chandelier_clean.columns.duplicated()]
    
    # Verify timestamp column
    if on not in df_zlsma_clean.columns:
        raise ValueError(f"Column '{on}' not found in ZLSMA DataFrame. Available columns: {list(df_zlsma_clean.columns)}")
    
    if on not in df_chandelier_clean.columns:
        raise ValueError(f"Column '{on}' not found in Chandelier DataFrame. Available columns: {list(df_chandelier_clean.columns)}")
    
    # Merge
    merged_df = pd.merge(
        df_zlsma_clean,
        df_chandelier_clean,
        on=on,
        how=how,
        suffixes=('', '_chandelier')
    )
    
    return merged_df

# Example usage:
"""
# For ZLSMA with length 200:
df_zlsma = calculate_zlsma(df, close_column='close', length=200)

# For ZLSMA with default length 32 (matching Pine Script):
df_zlsma = calculate_zlsma(df, close_column='close', length=32)

df_chandelier = calculate_chandelier(df, atr_period=1, atr_multiplier=2.0)
merged_chandelier_zlsma = merge_zlsma_chandelier(df_zlsma, df_chandelier)
merged_chandelier_zlsma = merged_chandelier_zlsma[["timestamp", "close", "zlsma_200", "buy_signal", "sell_signal"]]
"""