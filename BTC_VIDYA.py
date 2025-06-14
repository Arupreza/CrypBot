import pandas as pd
import numpy as np
import requests
from datetime import datetime, timedelta
from typing import Union

def fetch_binance_klines(symbol: str = "BTCUSDT", interval: str = "30m", limit: int = 1000):
    """
    Fetch kline data from Binance API
    
    Parameters:
    symbol: Trading pair (default: "BTCUSDT")
    interval: Kline interval (default: "30m")
    limit: Number of klines to fetch (max 1000, default: 1000)
    
    Returns:
    DataFrame with OHLCV data
    """
    base_url = "https://api.binance.com/api/v3/klines"
    
    params = {
        'symbol': symbol,
        'interval': interval,
        'limit': limit
    }
    
    try:
        response = requests.get(base_url, params=params, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        
        # Convert to DataFrame
        df = pd.DataFrame(data, columns=[
            'open_time', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_asset_volume', 'number_of_trades',
            'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'
        ])
        
        # Convert relevant columns to float
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # Convert timestamps
        df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
        df['close_time'] = pd.to_datetime(df['close_time'], unit='ms')
        
        # Keep only required columns
        df = df[['open_time', 'open', 'high', 'low', 'close', 'volume']].copy()
        
        # Set index to timestamp
        df.set_index('open_time', inplace=True)
        
        return df
        
    except requests.exceptions.RequestException as e:
        return None
    except Exception as e:
        return None

def volumatic_vidya_signal(df: pd.DataFrame, 
                        vidya_length: int = 10,
                        vidya_momentum: int = 20,
                        band_distance: float = 2.0,
                        atr_length: int = 200,
                        sma_length: int = 15,
                        verbose: bool = False) -> str:
    """
    Calculate Volumatic VIDYA signal for BTC 30min candles
    
    Parameters:
    df: DataFrame with columns ['open', 'high', 'low', 'close', 'volume']
    vidya_length: Length of the VIDYA calculation (default: 10)
    vidya_momentum: Momentum length for VIDYA (default: 20)
    band_distance: Distance factor for upper/lower bands (default: 2.0)
    atr_length: ATR calculation length (default: 200)
    sma_length: SMA smoothing length (default: 15)
    verbose: Print debug information (default: False)
    
    Returns:
    str: "Green" if trend is up, "Red" if trend is down
    """
    
    def calculate_atr(high, low, close, length):
        """Calculate Average True Range"""
        high_low = high - low
        high_close = np.abs(high - close.shift(1))
        low_close = np.abs(low - close.shift(1))
        
        true_range = np.maximum(high_low, np.maximum(high_close, low_close))
        return true_range.rolling(window=length, min_periods=1).mean()
    
    def calculate_vidya(src, vidya_length, vidya_momentum, sma_length):
        """Calculate VIDYA exactly as in the original Pine Script"""
        # Calculate momentum (price change)
        momentum = src.diff()
        
        # Calculate positive and negative momentum sums over vidya_momentum period
        pos_momentum = np.where(momentum >= 0, momentum, 0.0)
        neg_momentum = np.where(momentum < 0, -momentum, 0.0)
        
        # Use pandas rolling sum for exact replication
        sum_pos_momentum = pd.Series(pos_momentum, index=src.index).rolling(window=vidya_momentum, min_periods=1).sum()
        sum_neg_momentum = pd.Series(neg_momentum, index=src.index).rolling(window=vidya_momentum, min_periods=1).sum()
        
        # Calculate CMO (Chande Momentum Oscillator) - exactly as in Pine Script
        total_momentum = sum_pos_momentum + sum_neg_momentum
        cmo = np.where(total_momentum != 0, 
                      100 * (sum_pos_momentum - sum_neg_momentum) / total_momentum, 
                    0)
        abs_cmo = np.abs(cmo)
        
        # Calculate alpha
        alpha = 2 / (vidya_length + 1)
        
        # Calculate VIDYA recursively - exactly as in Pine Script
        vidya_values = np.zeros(len(src))
        vidya_prev = 0.0
        
        for i in range(len(src)):
            if i == 0 or np.isnan(src.iloc[i]):
                vidya_values[i] = src.iloc[i] if not np.isnan(src.iloc[i]) else 0
            else:
                adaptive_factor = alpha * abs_cmo[i] / 100
                vidya_values[i] = adaptive_factor * src.iloc[i] + (1 - adaptive_factor) * vidya_prev
            vidya_prev = vidya_values[i]
        
        # Apply SMA smoothing of 15 periods as in original
        vidya_series = pd.Series(vidya_values, index=src.index)
        return vidya_series.rolling(window=sma_length, min_periods=1).mean()
    
    # Ensure we have enough data
    required_data = max(atr_length, vidya_momentum, sma_length) + 50
    if len(df) < required_data:
        return "Red"  # Default to Red if insufficient data
    
    # Extract OHLCV data
    high = df['high'].copy()
    low = df['low'].copy()
    close = df['close'].copy()
    source = close  # Using close as source like original
    
    # Calculate ATR with 200 period
    atr_value = calculate_atr(high, low, close, atr_length)
    
    # Calculate VIDYA
    vidya_value = calculate_vidya(source, vidya_length, vidya_momentum, sma_length)
    
    # Calculate upper and lower bands based on VIDYA and ATR
    upper_band = vidya_value + atr_value * band_distance
    lower_band = vidya_value - atr_value * band_distance
    
    # Initialize trend tracking arrays
    is_trend_up = np.zeros(len(df), dtype=bool)
    smoothed_value = np.full(len(df), np.nan)
    
    # Process trend detection exactly as in Pine Script
    for i in range(1, len(df)):
        # Detect crossovers - exactly as in original Pine Script logic
        crossover_upper = (source.iloc[i] > upper_band.iloc[i] and 
                        source.iloc[i-1] <= upper_band.iloc[i-1])
        crossunder_lower = (source.iloc[i] < lower_band.iloc[i] and 
                        source.iloc[i-1] >= lower_band.iloc[i-1])
        
        # Update trend state
        if crossover_upper:
            is_trend_up[i] = True
        elif crossunder_lower:
            is_trend_up[i] = False
        else:
            is_trend_up[i] = is_trend_up[i-1]
        
        # Set smoothed value based on trend - exactly as in Pine Script
        trend_changed = is_trend_up[i] != is_trend_up[i-1]
        
        if trend_changed:
            smoothed_value[i] = np.nan
        elif is_trend_up[i]:
            smoothed_value[i] = lower_band.iloc[i]
        else:  # not is_trend_up[i]
            smoothed_value[i] = upper_band.iloc[i]
    
    # Get the latest trend state - this is what determines Green vs Red
    latest_trend = is_trend_up[-1]
    
    return "Green" if latest_trend else "Red"

def get_btc_volumatic_signal(verbose: bool = True) -> str:
    """
    Fetch BTC 30min data from Binance and calculate Volumatic VIDYA signal
    
    Parameters:
    verbose: Print detailed information (default: True)
    
    Returns:
    str: "Green" if trend is up, "Red" if trend is down, "Error" if failed
    """
    
    # Fetch data from Binance
    df = fetch_binance_klines(symbol="BTCUSDT", interval="30m", limit=1000)
    
    if df is None or len(df) == 0:
        return "Error"
    
    # Calculate signal
    signal = volumatic_vidya_signal(df, verbose=verbose)
    
    return signal