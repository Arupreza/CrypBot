import pandas as pd
import numpy as np

def calculate_ema(data, period):
    """Calculate Exponential Moving Average"""
    return data.ewm(span=period, adjust=False).mean()

def calculate_atr(high, low, close, period):
    """Calculate Average True Range"""
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = true_range.rolling(window=period).mean()
    return atr

def find_pivot_points(high, low, period):
    """Find pivot highs and lows"""
    pivot_high = high.rolling(window=2*period+1, center=True).max() == high
    pivot_low  = low.rolling(window=2*period+1, center=True).min() == low
    
    # Shift to align pivot points at the correct bar
    pivot_high = pivot_high.shift(period)
    pivot_low  = pivot_low.shift(period)
    
    return pivot_high, pivot_low

def pivot_point_supertrend(df, pivot_period=2, atr_factor=3, atr_period=10):
    """
    Calculate Pivot Point SuperTrend indicator with OHLCV data
    
    Parameters:
      df           : DataFrame with at least 'high', 'low', 'close' columns.
      pivot_period : Lookback on each side for pivot high/low (default: 2).
      atr_factor   : Multiplier for ATR which defines Up/Dn bands (default: 3).
      atr_period   : ATR rolling period (default: 10).
    
    Returns:
      result_df: DataFrame containing:
        ['open','high','low','close','volume',
         'EMA_50','EMA_200','ATR','center','Up','Dn','TUp','TDown','Trend',
         'Trailingsl','PVS_Buy','PVS_Sell']
    """
    df = df.copy()
    
    # ───── 1) EMAs ─────────────────────────────────────────────────────────────
    df['EMA_50']  = calculate_ema(df['close'], 50)
    df['EMA_200'] = calculate_ema(df['close'], 200)
    
    # ───── 2) ATR ──────────────────────────────────────────────────────────────
    df['ATR'] = calculate_atr(df['high'], df['low'], df['close'], atr_period)
    
    # ───── 3) Pivot High/Low ───────────────────────────────────────────────────
    pivot_high, pivot_low = find_pivot_points(df['high'], df['low'], pivot_period)
    ph = df['high'].where(pivot_high)
    pl = df['low'].where(pivot_low)
    
    # ───── 4) Center Line (weighted). Forward‐fill until first pivot appears ──
    center = [np.nan] * len(df)
    current_center = np.nan
    for i in range(len(df)):
        lastpp = None
        if not pd.isna(ph.iat[i]):
            lastpp = ph.iat[i]
        elif not pd.isna(pl.iat[i]):
            lastpp = pl.iat[i]
        
        if lastpp is not None:
            if pd.isna(current_center):
                current_center = lastpp
            else:
                # Weighted average: (old_center * 2 + new_pivot) / 3
                current_center = (current_center * 2 + lastpp) / 3
        
        center[i] = current_center
    
    df['center'] = pd.Series(center, index=df.index).ffill()
    
    # ───── 5) Upper/Lower Bands ────────────────────────────────────────────────
    df['Up'] = df['center'] - (atr_factor * df['ATR'])
    df['Dn'] = df['center'] + (atr_factor * df['ATR'])
    
    # ───── 6) Initialize TUp, TDown, Trend ────────────────────────────────────
    df['TUp']   = np.nan
    df['TDown'] = np.nan
    df['Trend'] = 0
    
    # Set the very first TUp/TDown = Up[0]/Dn[0], Trend=1 by convention
    df.at[df.index[0], 'TUp']   = df['Up'].iat[0]
    df.at[df.index[0], 'TDown'] = df['Dn'].iat[0]
    df.at[df.index[0], 'Trend'] = 1  # assume uptrend at start
    
    # ───── 7) Loop to compute TUp, TDown, Trend ──────────────────────────────
    for i in range(1, len(df)):
        prev_close = df['close'].iat[i-1]
        prev_TUp   = df['TUp'].iat[i-1]
        prev_TDown = df['TDown'].iat[i-1]
        
        # TUp: if previous close > previous TUp, then TUp = max(current Up, previous TUp)
        if prev_close > prev_TUp:
            df.at[df.index[i], 'TUp'] = max(df['Up'].iat[i], prev_TUp)
        else:
            df.at[df.index[i], 'TUp'] = df['Up'].iat[i]
        
        # TDown: if previous close < previous TDown, then TDown = min(current Dn, previous TDown)
        if prev_close < prev_TDown:
            df.at[df.index[i], 'TDown'] = min(df['Dn'].iat[i], prev_TDown)
        else:
            df.at[df.index[i], 'TDown'] = df['Dn'].iat[i]
        
        # Determine Trend: 
        #   If current close > previous TDown => uptrend (1)
        #   Else if current close < previous TUp => downtrend (-1)
        #   Otherwise, carry over previous trend (default to 1 if previous was 0)
        cur_close = df['close'].iat[i]
        if cur_close > prev_TDown:
            df.at[df.index[i], 'Trend'] = 1
        elif cur_close < prev_TUp:
            df.at[df.index[i], 'Trend'] = -1
        else:
            prev_tr = df['Trend'].iat[i-1]
            df.at[df.index[i], 'Trend'] = prev_tr if prev_tr != 0 else 1
    
    # ───── 8) Trailing Stop Line ───────────────────────────────────────────────
    df['Trailingsl'] = np.where(df['Trend'] == 1, df['TUp'], df['TDown'])
    
    # ───── 9) Buy / Sell Signals ───────────────────────────────────────────────
    df['prev_trend']  = df['Trend'].shift(1).fillna(method='bfill')
    df['PVS_Buy']     = (df['Trend'] == 1)  & (df['prev_trend'] == -1)
    df['PVS_Sell']    = (df['Trend'] == -1) & (df['prev_trend'] == 1)
    
    # ───── 10) Build final result DataFrame ───────────────────────────────────
    # Include both PVS_Buy and PVS_Sell so no KeyError later
    required_columns = [
        'open','high','low','close','volume',
        'EMA_50','EMA_200','ATR','center','Up','Dn','TUp','TDown',
        'Trend','Trailingsl','PVS_Buy','PVS_Sell'
    ]
    
    # If original df didn't have 'open' or 'volume', create them as NaN
    if 'open' not in df.columns:
        df['open'] = np.nan
    if 'volume' not in df.columns:
        df['volume'] = np.nan
    
    # Return a DataFrame containing all required columns (some may be NaN if not in original)
    result_df = df[required_columns].copy()
    return result_df


# ──────────────────────────────────────────────────────────────────────────────
# Example Usage / Quick Test
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Create a sample OHLCV DataFrame to test
    dates = pd.date_range('2025-01-01', periods=300, freq='D')
    np.random.seed(42)
    
    # Random-walk close price, then high/low around it
    close_prices = 100 + np.cumsum(np.random.randn(300) * 0.5)
    high_prices  = close_prices + np.random.rand(300) * 2
    low_prices   = close_prices - np.random.rand(300) * 2
    open_prices  = close_prices + np.random.randn(300) * 0.3
    volumes      = np.random.randint(1000, 10000, size=300)
    
    sample_df = pd.DataFrame({
        'date': dates,
        'open': open_prices,
        'high': high_prices,
        'low': low_prices,
        'close': close_prices,
        'volume': volumes
    }).set_index('date')
    
    # Calculate Pivot Point SuperTrend
    result = pivot_point_supertrend(sample_df)
    
    # Print first few rows
    print("First 10 rows of Pivot Point SuperTrend result:")
    print(result.head(10))
    print("\nColumns in result:", list(result.columns))
    
    # Verify that both PVS_Buy and PVS_Sell exist
    print(f"\nNumber of PVS_Buy signals:  {result['PVS_Buy'].sum()}")
    print(f"Number of PVS_Sell signals: {result['PVS_Sell'].sum()}")