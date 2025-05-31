import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import mplfinance as mpf
from scipy import stats

#####  Revised calculate_zlsma  #####

def linreg(data: pd.Series, length: int, offset: int = 0) -> pd.Series:
    """
    Compute linear‐regression‐based moving average over a rolling window.
    Returns a pd.Series of the same length as `data`.
    """
    n = len(data)
    result = [np.nan] * n

    for i in range(n):
        if i < length - 1:
            continue
        window = data.iloc[i - length + 1 : i + 1].values
        x = np.arange(length)
        slope, intercept, *_ = stats.linregress(x, window)
        reg_val = slope * (length - 1 + offset) + intercept
        result[i] = reg_val

    return pd.Series(result, index=data.index)


def zlsma(data: pd.Series, length: int = 200, offset: int = 0) -> pd.Series:
    """
    Zero‐lag LSMA (two‐pass linear regression).
    Returns a pd.Series indexed like `data`.
    """
    n = len(data)
    effective_length = min(length, n // 3)
    if effective_length < 10:
        effective_length = min(10, n // 2)

    # If not enough data for two passes, fallback to a short SMA:
    if n < 2 * effective_length:
        print("Warning: Not enough data for full ZLSMA. Using a simple moving average fallback.")
        return data.rolling(window=max(1, min(20, n // 2))).mean()

    # Reset index so that linreg sees indices 0..n-1
    data_reset = data.reset_index(drop=True)
    lsma1 = linreg(data_reset, effective_length, offset)
    lsma1_clean = lsma1.dropna()

    if len(lsma1_clean) < effective_length:
        # Fallback if second pass can’t run
        return lsma1.reindex(data.index)

    lsma2 = linreg(lsma1_clean, effective_length, offset)
    result = [np.nan] * n
    start_idx = 2 * (effective_length - 1)

    for i in range(start_idx, n):
        lsma1_val = lsma1.iloc[i]
        lsma2_val = lsma2.iloc[i - (effective_length - 1)]
        if not np.isnan(lsma1_val) and not np.isnan(lsma2_val):
            eq = lsma1_val - lsma2_val
            result[i] = lsma1_val + eq

    return pd.Series(result, index=data.index)


def calculate_zlsma(
    in_df: pd.DataFrame,
    close_column: str = 'close',
    timestamp_column: str = None,
    length: int = 200,
    plot: bool = False
) -> pd.DataFrame:
    """
    Given a DataFrame `in_df` that has at least the `close_column`,
    this function:
      1. Attempts to locate a timestamp column among common names.
      2. If none is found, checks if the index is already a DatetimeIndex:
         - If yes, uses the index as 'timestamp' quietly.
         - If not, injects `df['timestamp'] = df.index` and prints a warning.
      3. Computes a new column named `zlsma_{length}` via `zlsma(...)`.
      4. Returns a DataFrame that includes all original columns plus:
         - `'timestamp'`
         - `f'zlsma_{length}'`.
    """
    df = in_df.copy()

    # 1) Detect a timestamp column if the user did not explicitly pass one
    if timestamp_column is None:
        for cand in ['timestamp', 'time', 'date', 'datetime', 'Date', 'Time', 'DateTime']:
            if cand in df.columns:
                timestamp_column = cand
                break

    # 2) If we found a timestamp column, convert it to datetime and copy into 'timestamp'
    if timestamp_column is not None and (timestamp_column in df.columns):
        df[timestamp_column] = pd.to_datetime(df[timestamp_column])
        df['timestamp'] = df[timestamp_column]

    else:
        # 3) If no timestamp column found, check if index is a DatetimeIndex
        if isinstance(df.index, pd.DatetimeIndex):
            # Use the index as 'timestamp' without warning
            df['timestamp'] = df.index
        else:
            # Neither timestamp column nor datetime index → inject index but warn
            df['timestamp'] = df.index
            print("Warning: No timestamp column found in ZLSMA. Using index as 'timestamp'.")

    # 4) Verify the close column exists
    if close_column not in df.columns:
        raise ValueError(f"calculate_zlsma: Missing required close column '{close_column}'.")

    # 5) Compute ZLSMA
    z_col = f"zlsma_{length}"
    print(f"Calculating ZLSMA with length = {length} ...")
    df[z_col] = zlsma(df[close_column], length=length)

    valid_count = df[z_col].dropna().shape[0]
    print(f"Valid {z_col} values: {valid_count} out of {len(df)} rows.")

    return df


#####  Revised calculate_chandelier  #####

def calculate_atr(df: pd.DataFrame, length: int = 1) -> pd.Series:
    """
    Calculate Average True Range (ATR). Returns a pd.Series.
    """
    high_low       = df['high'] - df['low']
    high_close_prev = (df['high'] - df['close'].shift()).abs()
    low_close_prev  = (df['low']  - df['close'].shift()).abs()

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
      - 'buy_signal'
      - 'sell_signal'
    """
    df_result = df.copy()

    # 1) Compute ATR * multiplier
    atr_raw = calculate_atr(df, length=atr_period)
    atr = atr_raw * atr_multiplier

    # 2) Compute rolling highest/lowest (either on 'close' or on 'high'/'low')
    if use_close:
        highest = df['close'].rolling(window=atr_period).max()
        lowest  = df['close'].rolling(window=atr_period).min()
    else:
        highest = df['high'].rolling(window=atr_period).max()
        lowest  = df['low'].rolling(window=atr_period).min()

    n = len(df)
    long_stop_array  = np.full(n, np.nan)
    short_stop_array = np.full(n, np.nan)
    direction_array  = np.full(n, 1)  # start as long

    for i in range(n):
        if pd.isna(atr.iloc[i]) or pd.isna(highest.iloc[i]) or pd.isna(lowest.iloc[i]):
            continue

        curr_long  = highest.iloc[i] - atr.iloc[i]
        curr_short = lowest.iloc[i]  + atr.iloc[i]

        if i == 0:
            long_stop_array[i]  = curr_long
            short_stop_array[i] = curr_short
            direction_array[i]  = 1
        else:
            # Long stop logic
            prev_long = long_stop_array[i - 1] if not pd.isna(long_stop_array[i - 1]) else curr_long
            if df['close'].iloc[i - 1] > prev_long:
                long_stop_array[i] = max(curr_long, prev_long)
            else:
                long_stop_array[i] = curr_long

            # Short stop logic
            prev_short = short_stop_array[i - 1] if not pd.isna(short_stop_array[i - 1]) else curr_short
            if df['close'].iloc[i - 1] < prev_short:
                short_stop_array[i] = min(curr_short, prev_short)
            else:
                short_stop_array[i] = curr_short

            # Direction flip logic
            prev_short_val = short_stop_array[i - 1] if not pd.isna(short_stop_array[i - 1]) else curr_short
            prev_long_val  = long_stop_array[i - 1]  if not pd.isna(long_stop_array[i - 1])  else curr_long

            if df['close'].iloc[i] > prev_short_val:
                direction_array[i] = 1   # go long
            elif df['close'].iloc[i] < prev_long_val:
                direction_array[i] = -1  # go short
            else:
                direction_array[i] = direction_array[i - 1]

    # 3) Attach to df_result
    df_result['atr']              = atr
    df_result['long_stop']        = long_stop_array
    df_result['short_stop']       = short_stop_array
    df_result['direction']        = direction_array
    df_result['chandelier_exit']  = np.where(direction_array == 1, long_stop_array, short_stop_array)

    # 4) Generate buy/sell signals (1 if flip occurs on that bar, else 0)
    df_result['buy_signal']  = ((df_result['direction'] == 1)  & (df_result['direction'].shift() == -1)).astype(int)
    df_result['sell_signal'] = ((df_result['direction'] == -1) & (df_result['direction'].shift() == 1 )).astype(int)

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

    # 1) Detect timestamp column if user didn't supply one
    if timestamp_column is None:
        for cand in ['timestamp', 'time', 'date', 'datetime', 'Date', 'Time', 'DateTime']:
            if cand in df.columns:
                timestamp_column = cand
                break

    if timestamp_column is not None and (timestamp_column in df.columns):
        # We found a real timestamp column → convert and copy into 'timestamp'
        df[timestamp_column] = pd.to_datetime(df[timestamp_column])
        df['timestamp'] = df[timestamp_column]
    else:
        # No timestamp column in df. Check if index is a DatetimeIndex:
        if isinstance(df.index, pd.DatetimeIndex):
            df['timestamp'] = df.index  # quietly use index
        else:
            # Neither a timestamp column nor datetime index → inject index
            df['timestamp'] = df.index
            print("Warning: No timestamp column found in Chandelier. Using index as 'timestamp'.")

    # 2) Verify required columns exist
    missing = [c for c in ['high','low','close'] if c not in df.columns]
    if missing:
        raise ValueError(f"calculate_chandelier: Missing required columns: {missing}")

    # 3) Compute Chandelier Exit
    df_ch = chandelier_exit(df, atr_period=atr_period, atr_multiplier=atr_multiplier, use_close=use_close)

    # 4) Make sure 'timestamp' is in the result
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
    Merge ZLSMA DataFrame with Chandelier exit DataFrame on 'timestamp'.
    Expects both to contain a column named `on` (default: 'timestamp').
    """
    cols_to_add = [
        on,
        "atr",
        "long_stop",
        "short_stop",
        "direction",
        "chandelier_exit",
        "buy_signal",
        "sell_signal",
    ]

    return pd.merge(
        df_zlsma,
        df_chandelier[cols_to_add],
        on=on,
        how=how
    )
