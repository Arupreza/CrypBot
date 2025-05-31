import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from scipy import stats
import mplfinance as mpf
from matplotlib.lines import Line2D



#####  Chandelier  #####
def calculate_atr(df, length=1):
    """
    Calculate Average True Range (ATR)
    
    Parameters:
    df: pandas DataFrame - must have 'high', 'low', 'close' columns
    length: int - ATR period (default 1)
    
    Returns:
    pandas Series - ATR values
    """
    # Calculate True Range
    high_low = df['high'] - df['low']
    high_close_prev = abs(df['high'] - df['close'].shift())
    low_close_prev = abs(df['low'] - df['close'].shift())
    
    true_range = pd.concat([high_low, high_close_prev, low_close_prev], axis=1).max(axis=1)
    
    # Calculate ATR (Simple Moving Average of True Range)
    atr = true_range.rolling(window=length).mean()
    
    return atr


def chandelier_exit(df, atr_period=1, atr_multiplier=2.0, use_close=True):
    """
    Calculate Chandelier Exit indicator
    
    Parameters:
    df: pandas DataFrame - must have 'high', 'low', 'close' columns
    atr_period: int - ATR period (default 1)
    atr_multiplier: float - ATR multiplier (default 2.0)
    use_close: bool - use close price for extremums (default True)
    
    Returns:
    pandas DataFrame - original data with Chandelier Exit columns added
    """
    df_result = df.copy()
    
    # Calculate ATR
    atr = calculate_atr(df, atr_period) * atr_multiplier
    
    # Calculate highest and lowest values
    if use_close:
        highest = df['close'].rolling(window=atr_period).max()
        lowest = df['close'].rolling(window=atr_period).min()
    else:
        highest = df['high'].rolling(window=atr_period).max()
        lowest = df['low'].rolling(window=atr_period).min()
    
    # Initialize arrays
    long_stop = np.full(len(df), np.nan)
    short_stop = np.full(len(df), np.nan)
    direction = np.full(len(df), 1)  # Start with long direction
    
    # Calculate Chandelier Exit values
    for i in range(len(df)):
        if pd.isna(atr.iloc[i]) or pd.isna(highest.iloc[i]) or pd.isna(lowest.iloc[i]):
            continue
            
        # Calculate basic stops
        current_long_stop = highest.iloc[i] - atr.iloc[i]
        current_short_stop = lowest.iloc[i] + atr.iloc[i]
        
        # Apply Chandelier Exit logic
        if i > 0:
            # Long stop logic
            prev_long_stop = long_stop[i-1] if not pd.isna(long_stop[i-1]) else current_long_stop
            if df['close'].iloc[i-1] > prev_long_stop:
                long_stop[i] = max(current_long_stop, prev_long_stop)
            else:
                long_stop[i] = current_long_stop
                
            # Short stop logic
            prev_short_stop = short_stop[i-1] if not pd.isna(short_stop[i-1]) else current_short_stop
            if df['close'].iloc[i-1] < prev_short_stop:
                short_stop[i] = min(current_short_stop, prev_short_stop)
            else:
                short_stop[i] = current_short_stop
                
            # Direction logic
            prev_short_stop_val = short_stop[i-1] if not pd.isna(short_stop[i-1]) else current_short_stop
            prev_long_stop_val = long_stop[i-1] if not pd.isna(long_stop[i-1]) else current_long_stop
            
            if df['close'].iloc[i] > prev_short_stop_val:
                direction[i] = 1  # Long
            elif df['close'].iloc[i] < prev_long_stop_val:
                direction[i] = -1  # Short
            else:
                direction[i] = direction[i-1]  # Keep previous direction
        else:
            long_stop[i] = current_long_stop
            short_stop[i] = current_short_stop
            direction[i] = 1
    
    # Add results to dataframe
    df_result['atr'] = atr
    df_result['long_stop'] = long_stop
    df_result['short_stop'] = short_stop
    df_result['direction'] = direction
    
    # Create the actual Chandelier Exit line (show only active stop)
    df_result['chandelier_exit'] = np.where(df_result['direction'] == 1, 
                                            df_result['long_stop'], 
                                            df_result['short_stop'])
    
    # Identify buy/sell signals
    df_result['buy_signal'] = (df_result['direction'] == 1) & (df_result['direction'].shift() == -1)
    df_result['sell_signal'] = (df_result['direction'] == -1) & (df_result['direction'].shift() == 1)
    
    return df_result


def calculate_chandelier(in_df, atr_period=1, atr_multiplier=2.0, 
                                timestamp_column=None, use_close=True, plot=True):
    """
    Load CSV file, calculate Chandelier Exit, and optionally plot the results
    
    Parameters:
    csv_file_path: str - path to your CSV file
    atr_period: int - ATR period (default 1)
    atr_multiplier: float - ATR multiplier (default 2.0)
    timestamp_column: str - name of the timestamp column (if None, will try to auto-detect)
    use_close: bool - use close price for extremums (default True)
    plot: bool - whether to plot the results (default True)
    
    Returns:
    pandas DataFrame - DataFrame with original data and Chandelier Exit columns
    """
    # Load the CSV file
    df = in_df
    
    # Check required columns
    required_cols = ['high', 'low', 'close']
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        print(f"Error: Missing required columns: {missing_cols}")
        print(f"Available columns: {list(df.columns)}")
        return None
    
    # Try to find timestamp column if not specified
    if timestamp_column is None:
        timestamp_candidates = ['timestamp', 'time', 'date', 'datetime', 'Date', 'Time', 'DateTime']
        for col in timestamp_candidates:
            if col in df.columns:
                timestamp_column = col
                break
    
    # Convert timestamp column to datetime if found
    if timestamp_column and timestamp_column in df.columns:
        df[timestamp_column] = pd.to_datetime(df[timestamp_column])
        x_axis = df[timestamp_column]
    else:
        x_axis = df.index
        print("Warning: No timestamp column found, using index for X-axis")
    
    print(f"Data loaded: {len(df)} rows")
    print(f"Calculating Chandelier Exit with ATR period {atr_period}, multiplier {atr_multiplier}...")
    
    # Calculate Chandelier Exit
    df_result = chandelier_exit(df, atr_period=atr_period, atr_multiplier=atr_multiplier, use_close=use_close)
    
    return df_result


##### ZLSMA #####

def linreg(data, length, offset=0):
    """
    Calculate Linear Regression (LSMA - Least Squares Moving Average)
    
    Parameters:
    data: pandas Series - input data (typically close prices)
    length: int - period for linear regression
    offset: int - offset for the regression line (default 0)
    
    Returns:
    pandas Series - linear regression values
    """
    result = []
    
    for i in range(len(data)):
        if i < length - 1:
            result.append(np.nan)
        else:
            # Get the window of data
            window = data.iloc[i-length+1:i+1].values
            
            # Create x values (time indices)
            x = np.arange(length)
            
            # Calculate linear regression
            slope, intercept, _, _, _ = stats.linregress(x, window)
            
            # Calculate the value at the end of the period plus offset
            reg_value = slope * (length - 1 + offset) + intercept
            result.append(reg_value)
    
    return pd.Series(result, index=data.index)



def zlsma(data, length=200, offset=0):
    """
    Calculate Zero Lag LSMA
    
    Parameters:
    data: pandas Series - input data (typically close prices)
    length: int - period for ZLSMA calculation (default 200)
    offset: int - offset parameter (default 0)
    
    Returns:
    pandas Series - ZLSMA values
    """
    # If we don't have enough data for the full length, use what we have
    effective_length = min(length, len(data) // 3)  # Use 1/3 of available data as max
    
    if effective_length < 10:  # Minimum reasonable length
        effective_length = min(10, len(data) // 2)
    
    if len(data) < effective_length * 2:
        print(f"Warning: Not enough data for ZLSMA. Using simple moving average instead.")
        return data.rolling(window=min(20, len(data)//2)).mean()
    
    print(f"Using effective ZLSMA length: {effective_length} (requested: {length})")
    
    # Reset index to ensure we're working with integer indices
    data_reset = data.reset_index(drop=True)
    
    # First LSMA
    lsma1 = linreg(data_reset, effective_length, offset)
    
    # Second LSMA applied to the first LSMA (need to drop NaN values first)
    lsma1_clean = lsma1.dropna()
    if len(lsma1_clean) < effective_length:
        print(f"Warning: Insufficient data for second LSMA. Using first LSMA only.")
        return lsma1
    
    lsma2 = linreg(lsma1_clean, effective_length, offset)
    
    # Initialize result array
    result = np.full(len(data), np.nan)
    
    # Calculate ZLSMA starting from the point where we have both LSMA values
    start_index = 2 * (effective_length - 1)  # Need 2*(length-1) periods for both LSMAs
    
    if len(data) > start_index:
        # Get valid portions of both LSMA series
        for i in range(start_index, len(data)):
            lsma1_idx = i
            lsma2_idx = i - (effective_length - 1)  # lsma2 starts later
            
            if (lsma1_idx < len(lsma1) and lsma2_idx < len(lsma2) and 
                not pd.isna(lsma1.iloc[lsma1_idx]) and not pd.isna(lsma2.iloc[lsma2_idx])):
                
                # Calculate: eq = lsma1 - lsma2, zlsma = lsma1 + eq
                eq = lsma1.iloc[lsma1_idx] - lsma2.iloc[lsma2_idx]
                result[i] = lsma1.iloc[lsma1_idx] + eq
    
    return pd.Series(result, index=data.index)


def calculate_zlsma(in_df, close_column='close', timestamp_column=None, length=200, plot=True):
    """
    Load CSV file, calculate ZLSMA, and optionally plot the results
    
    Parameters:
    csv_file_path: str - path to your CSV file
    close_column: str - name of the close price column (default 'close')
    timestamp_column: str - name of the timestamp column (if None, will try to auto-detect)
    length: int - ZLSMA length parameter (default 200)
    plot: bool - whether to plot the results (default True)
    
    Returns:
    pandas DataFrame - DataFrame with original data and ZLSMA column
    """
    # Load the CSV file
    df = in_df
    
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
    print(f"Note: ZLSMA needs at least {2*(length-1)} rows to start producing values")
    
    # Calculate ZLSMA
    df[f'zlsma_{length}'] = zlsma(df[close_column], length=length)
    
    # Check how many valid ZLSMA values we have
    valid_zlsma = df[f'zlsma_{length}'].dropna()
    print(f"Valid ZLSMA values: {len(valid_zlsma)} out of {len(df)} rows")
    
    
    return df


#####   Marge Chandelier with ZLSMA   #####

def merge_zlsma_chandelier(
    df_zlsma: pd.DataFrame,
    df_chandelier: pd.DataFrame,
    on: str = "timestamp",
    how: str = "inner"
) -> pd.DataFrame:
    """
    Merge ZLSMA DataFrame with Chandelier exit signals.

    Parameters
    ----------
    df_zlsma : pd.DataFrame
        DataFrame containing the ZLSMA series (must include `on` column).
    df_chandelier : pd.DataFrame
        DataFrame containing chandelier signals and ATR (must include `on` column).
    on : str, default "timestamp"
        Column name to join on.
    how : str, default "inner"
        Type of merge: 'inner', 'left', 'right', or 'outer'.

    Returns
    -------
    pd.DataFrame
        The merged DataFrame including all ZLSMA columns plus:
        ['atr','long_stop','short_stop','direction','chandelier_exit','buy_signal','sell_signal']
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

def plot_chandelier_zlsma(
    df: pd.DataFrame,
    zlsma_col: str = 'zlsma_200',
    buy_marker_size: int = 100,
    sell_marker_size: int = 100,
    highlight_marker_size: int = 200
) -> None:
    """
    Plot a merged chandelier + ZLSMA DataFrame (output of merge_chandelier_with_zlsma)
    with buy/sell markers and legend.
    
    Args:
        df:                    Merged DataFrame with columns
                            ['open','high','low','close','buy_signal','sell_signal', zlsma_col].
        zlsma_col:             Name of the ZLSMA column in df.
        buy_marker_size:       Size of the buy scatter marker.
        sell_marker_size:      Size of the sell scatter marker.
        highlight_marker_size: Size of the highlighted buy > ZLSMA marker.
    """
    # Compute marker positions
    buy_y           = np.where(df['buy_signal'] == 1,  df['low'] * 0.995, np.nan)
    sell_y          = np.where(df['sell_signal'] == 1, df['high'] * 1.005, np.nan)
    buy_above_zlsma = np.where(
        (df['buy_signal'] == 1) & (df['close'] > df[zlsma_col]),
        df['low'] * 0.99,
        np.nan
    )

    # Build addplots with labels for legend
    apds = [
        mpf.make_addplot(df[zlsma_col],     type='line',  width=1.5, label=f'{zlsma_col}'),
        mpf.make_addplot(buy_y,             type='scatter', marker='^', markersize=buy_marker_size,      label='Buy Signal'),
        mpf.make_addplot(sell_y,            type='scatter', marker='v', markersize=sell_marker_size,     label='Sell Signal'),
        mpf.make_addplot(buy_above_zlsma,   type='scatter', marker='*', markersize=highlight_marker_size, label='Buy > ZLSMA'),
    ]

    # Plot
    fig, axes = mpf.plot(
        df,
        type='candle',
        addplot=apds,
        style='charles',
        title="Chandelier Stops + ZLSMA",
        ylabel='Price (USD)',
        volume=False,
        tight_layout=True,
        figscale=1.5,
        returnfig=True
    )

    # Add legend on the price panel
    axes[0].legend(loc='upper left')
    
    
    

####   Trade Exicution   ####

def run_chandelier_zlsma_backtest(
    in_df: pd.DataFrame,
    zlsma_col: str = 'zlsma_200',
    window: int = 40,
    stop_loss_buffer: float = 0.998,
    trailing_stop_pct: float = 0.02,
    initial_capital: float = 5000.0,
) -> (pd.DataFrame, dict):
    """
    Backtest entries above ZLSMA with a static + trailing stop,
    using a fixed dollar amount per trade.
    
    Returns:
    trades_df: DataFrame indexed by entry_time with columns:
    ['exit_time','entry_price','exit_price','static_stop',
    'peak_price','profit_amount','equity']
    summary: dict with keys:
        'start_capital','end_capital','total_return',
        'total_return_pct','num_trades','num_wins',
        'num_losses','win_rate','total_profit_amount',
        'average_profit_amount'
    """
    df = in_df.copy()
    df.set_index('timestamp', inplace=True)
    df['support'] = df['low'].rolling(window=window, min_periods=1).min()

    # entry signals
    cond = (df['buy_signal'] == 1) & (df['close'] > df[zlsma_col])
    signals = df.loc[cond]

    equity = initial_capital
    trades = []

    for entry_time, sig in signals.iterrows():
        entry_price = sig['low'] * 0.99
        static_stop = sig['support'] * stop_loss_buffer

        peak_price = entry_price
        exit_price = None
        exit_time  = None

        # walk forward
        for t, row in df.loc[entry_time:].iterrows():
            high, low = row['high'], row['low']
            peak_price = max(peak_price, high)
            trailing_stop = peak_price * (1 - trailing_stop_pct)

            if low <= static_stop:
                exit_price, exit_time = static_stop, t
                break
            if low <= trailing_stop:
                exit_price, exit_time = trailing_stop, t
                break

        # no stop hit
        if exit_price is None:
            exit_time  = df.index[-1]
            exit_price = df.iloc[-1]['close']

        # compute P/L for fixed-size trade
        units         = initial_capital / entry_price
        profit_amount = units * (exit_price - entry_price)
        equity       += profit_amount

        trades.append({
            'entry_time':    entry_time,
            'exit_time':     exit_time,
            'entry_price':   entry_price,
            'exit_price':    exit_price,
            'static_stop':   static_stop,
            'peak_price':    peak_price,
            'profit_amount': profit_amount,
            'equity':        equity,
        })

    trades_df = pd.DataFrame(trades).set_index('entry_time')

    # summary
    profit_series         = trades_df['profit_amount']
    num_trades            = len(profit_series)
    num_wins              = (profit_series > 0).sum()
    num_losses            = (profit_series <= 0).sum()
    win_rate              = num_wins / num_trades * 100 if num_trades else 0.0
    total_profit_amount   = profit_series.sum()
    average_profit_amount = profit_series.mean() if num_trades else 0.0
    final_capital         = equity
    total_return          = final_capital - initial_capital
    total_return_pct      = total_return / initial_capital * 100

    summary = {
        'start_capital':        initial_capital,
        'end_capital':          final_capital,
        'total_return':         total_return,
        'total_return_pct':     total_return_pct,
        'num_trades':           num_trades,
        'num_wins':             num_wins,
        'num_losses':           num_losses,
        'win_rate':             win_rate,
        'total_profit_amount':  total_profit_amount,
        'average_profit_amount': average_profit_amount
    }

    return trades_df, summary