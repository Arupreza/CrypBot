import requests
import pandas as pd
import numpy as np
from typing import List, Dict, Optional
import time
import warnings
warnings.filterwarnings('ignore')

# Binance interval mappings
INTERVAL_MAP = {
    '1m': '1m',
    '3m': '3m', 
    '5m': '5m',
    '15m': '15m',
    '30m': '30m',
    '1h': '1h',
    '2h': '2h',
    '4h': '4h',
    '6h': '6h',
    '8h': '8h',
    '12h': '12h',
    '1d': '1d',
    '3d': '3d',
    '1w': '1w',
    '1M': '1M',
    # Alternative formats
    '1hour': '1h',
    '4hour': '4h',
    '24hour': '1d',
    'daily': '1d',
    'hourly': '1h'
}

def get_binance_symbols() -> List[str]:
    """Get all USDT trading pairs from Binance"""
    try:
        response = requests.get("https://api.binance.com/api/v3/exchangeInfo")
        data = response.json()
        
        symbols = []
        for symbol_info in data['symbols']:
            if (symbol_info['status'] == 'TRADING' and 
                symbol_info['symbol'].endswith('USDT') and
                symbol_info['symbol'] != 'USDT'):
                symbols.append(symbol_info['symbol'])
        
        return symbols
    except Exception as e:
        print(f"Error fetching symbols: {e}")
        return []

def get_klines_data(symbol: str, interval: str = "1h", limit: int = 100) -> List:
    """
    Get candlestick data for a symbol
    
    Parameters:
    -----------
    symbol : str
        Trading pair symbol
    interval : str
        Time interval (1m, 5m, 15m, 30m, 1h, 2h, 4h, 6h, 8h, 12h, 1d, 3d, 1w, 1M)
    limit : int
        Number of data points to fetch
    """
    try:
        # Normalize interval
        normalized_interval = INTERVAL_MAP.get(interval.lower(), interval)
        
        params = {
            'symbol': symbol,
            'interval': normalized_interval,
            'limit': limit
        }
        
        response = requests.get("https://api.binance.com/api/v3/klines", params=params)
        if response.status_code == 200:
            return response.json()
        return []
    except Exception as e:
        print(f"Error fetching data for {symbol}: {e}")
        return []

def calculate_rsi(prices: List[float], period: int = 14) -> Optional[float]:
    """Calculate RSI (Relative Strength Index)"""
    if len(prices) < period + 1:
        return None
        
    prices = np.array(prices)
    deltas = np.diff(prices)
    
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])
    
    # Calculate subsequent RSI values using Wilder's smoothing
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    
    if avg_loss == 0:
        return 100
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    
    return rsi

def get_interval_hours(interval: str) -> float:
    """Convert interval to hours for calculations"""
    interval = INTERVAL_MAP.get(interval.lower(), interval)
    
    hour_map = {
        '1m': 1/60, '3m': 3/60, '5m': 5/60, '15m': 15/60, '30m': 30/60,
        '1h': 1, '2h': 2, '4h': 4, '6h': 6, '8h': 8, '12h': 12,
        '1d': 24, '3d': 72, '1w': 168, '1M': 720
    }
    return hour_map.get(interval, 1)

def get_coin_data(symbol: str, interval: str = "1h", lookback_hours: int = 24) -> Optional[Dict]:
    """
    Get RSI and price data for a single coin
    
    Parameters:
    -----------
    symbol : str
        Trading pair symbol
    interval : str
        Time interval for analysis
    lookback_hours : int
        How many hours back to look for price comparison
    """
    
    # Calculate how many data points we need
    interval_hours = get_interval_hours(interval)
    lookback_periods = max(int(lookback_hours / interval_hours), 1)
    
    # Fetch enough data for RSI calculation + lookback
    limit = max(50, lookback_periods + 20)  # Ensure we have enough for RSI
    
    klines = get_klines_data(symbol, interval=interval, limit=limit)
    
    if not klines:
        return None
        
    # Extract data
    closing_prices = [float(kline[4]) for kline in klines]
    volumes = [float(kline[5]) for kline in klines]
    high_prices = [float(kline[2]) for kline in klines]
    low_prices = [float(kline[3]) for kline in klines]
    
    # Calculate RSI
    rsi = calculate_rsi(closing_prices)
    
    if rsi is None:
        return None
    
    # Get price information
    current_price = closing_prices[-1]
    
    # Price comparison based on lookback period
    if len(closing_prices) > lookback_periods:
        price_lookback = closing_prices[-lookback_periods-1]
    else:
        price_lookback = closing_prices[0]
    
    change_period = ((current_price - price_lookback) / price_lookback) * 100
    
    # Get volume and high/low for the lookback period
    lookback_data = min(lookback_periods, len(volumes))
    volume_period = sum(volumes[-lookback_data:])
    high_period = max(high_prices[-lookback_data:])
    low_period = min(low_prices[-lookback_data:])
    
    return {
        'symbol': symbol,
        'coin': symbol.replace('USDT', ''),
        'current_price': current_price,
        'rsi': rsi,
        'interval': interval,
        'lookback_hours': lookback_hours,
        f'change_{lookback_hours}h': change_period,
        f'volume_{lookback_hours}h': volume_period,
        f'high_{lookback_hours}h': high_period,
        f'low_{lookback_hours}h': low_period,
        'price_from_low': ((current_price - low_period) / low_period) * 100,
        'price_from_high': ((current_price - high_period) / high_period) * 100
    }

def get_low_rsi_coins(rsi_threshold: float = 30.0,
                    interval: str = "1h", 
                    lookback_hours: int = 24,
                    min_volume: float = 0, 
                    verbose: bool = True,
                    max_coins: Optional[int] = None) -> pd.DataFrame:
    """
    Get coins with RSI below threshold and return as DataFrame
    
    Parameters:
    -----------
    rsi_threshold : float, default 30.0
        RSI threshold below which coins will be filtered
    interval : str, default "1h"
        Time interval for RSI calculation (1m, 5m, 15m, 30m, 1h, 2h, 4h, 6h, 8h, 12h, 1d, etc.)
    lookback_hours : int, default 24
        Hours to look back for price change calculation
    min_volume : float, default 0
        Minimum volume filter for the lookback period
    verbose : bool, default True
        Print progress messages
    max_coins : int, optional
        Maximum number of coins to analyze (for testing)
    
    Returns:
    --------
    pandas.DataFrame
        DataFrame containing filtered coins with their data
    """
    
    if verbose:
        print(f"🚀 Fetching coins with RSI below {rsi_threshold}")
        print(f"📊 Interval: {interval}, Lookback: {lookback_hours} hours")
        print("=" * 60)
    
    # Get all symbols
    symbols = get_binance_symbols()
    if max_coins:
        symbols = symbols[:max_coins]
    
    if verbose:
        print(f"📈 Analyzing {len(symbols)} USDT pairs...")
    
    coins_data = []
    processed = 0
    errors = 0
    
    for symbol in symbols:
        try:
            coin_data = get_coin_data(symbol, interval=interval, lookback_hours=lookback_hours)
            processed += 1
            
            if coin_data and coin_data['rsi'] < rsi_threshold:
                volume_key = f'volume_{lookback_hours}h'
                if coin_data[volume_key] >= min_volume:
                    coins_data.append(coin_data)
                    if verbose:
                        print(f"✓ {coin_data['symbol']}: RSI {coin_data['rsi']:.2f}, "
                            f"{lookback_hours}h Change: {coin_data[f'change_{lookback_hours}h']:.2f}%")
            
            # Progress indicator
            if verbose and processed % 100 == 0:
                print(f"   Processed {processed}/{len(symbols)} coins... (Errors: {errors})")
            
            # Rate limiting
            time.sleep(0.05)
            
        except Exception as e:
            errors += 1
            if verbose and errors <= 5:  # Only show first 5 errors
                print(f"❌ Error processing {symbol}: {e}")
            continue
    
    # Create DataFrame
    if coins_data:
        df = pd.DataFrame(coins_data)
        df = df.sort_values('rsi').reset_index(drop=True)
        
        if verbose:
            print(f"\n✅ Found {len(df)} coins with RSI below {rsi_threshold}")
            print(f"📊 Analyzed {processed} coins with {errors} errors")
            print("=" * 60)
        
        return df
    else:
        if verbose:
            print(f"\n❌ No coins found with RSI below {rsi_threshold}")
            print(f"📊 Analyzed {processed} coins with {errors} errors")
        return pd.DataFrame()

def get_all_coins_rsi(interval: str = "1h",
                    lookback_hours: int = 24,
                    min_volume: float = 0, 
                    verbose: bool = True,
                    max_coins: Optional[int] = None) -> pd.DataFrame:
    """
    Get RSI data for all coins and return as DataFrame
    
    Parameters:
    -----------
    interval : str, default "1h"
        Time interval for RSI calculation
    lookback_hours : int, default 24
        Hours to look back for price change calculation
    min_volume : float, default 0
        Minimum volume filter
    verbose : bool, default True
        Print progress messages
    max_coins : int, optional
        Maximum number of coins to analyze
    
    Returns:
    --------
    pandas.DataFrame
        DataFrame containing all coins with their RSI data
    """
    
    if verbose:
        print(f"🚀 Fetching RSI data for all coins")
        print(f"📊 Interval: {interval}, Lookback: {lookback_hours} hours")
        print("=" * 50)
    
    # Get all symbols
    symbols = get_binance_symbols()
    if max_coins:
        symbols = symbols[:max_coins]
    
    if verbose:
        print(f"📈 Analyzing {len(symbols)} USDT pairs...")
    
    coins_data = []
    processed = 0
    errors = 0
    
    for symbol in symbols:
        try:
            coin_data = get_coin_data(symbol, interval=interval, lookback_hours=lookback_hours)
            processed += 1
            
            if coin_data:
                volume_key = f'volume_{lookback_hours}h'
                if coin_data[volume_key] >= min_volume:
                    coins_data.append(coin_data)
            
            # Progress indicator
            if verbose and processed % 100 == 0:
                print(f"   Processed {processed}/{len(symbols)} coins... (Errors: {errors})")
            
            # Rate limiting
            time.sleep(0.05)
            
        except Exception as e:
            errors += 1
            if verbose and errors <= 5:
                print(f"❌ Error processing {symbol}: {e}")
            continue
    
    # Create DataFrame
    if coins_data:
        df = pd.DataFrame(coins_data)
        df = df.sort_values('rsi').reset_index(drop=True)
        
        if verbose:
            print(f"\n✅ Retrieved data for {len(df)} coins")
            print(f"📊 Analyzed {processed} coins with {errors} errors")
            print("=" * 50)
        
        return df
    else:
        if verbose:
            print(f"\n❌ No coin data retrieved")
            print(f"📊 Analyzed {processed} coins with {errors} errors")
        return pd.DataFrame()

def analyze_rsi_dataframe(df: pd.DataFrame, rsi_threshold: float = 30.0) -> None:
    """
    Analyze and display RSI DataFrame statistics
    
    Parameters:
    -----------
    df : pandas.DataFrame
        DataFrame with coin RSI data
    rsi_threshold : float
        RSI threshold for analysis
    """
    
    if df.empty:
        print("❌ DataFrame is empty")
        return
    
    # Get dynamic column names based on lookback period
    change_col = [col for col in df.columns if col.startswith('change_')][0]
    volume_col = [col for col in df.columns if col.startswith('volume_')][0]
    
    lookback_hours = df['lookback_hours'].iloc[0] if 'lookback_hours' in df.columns else 24
    interval = df['interval'].iloc[0] if 'interval' in df.columns else '1h'
    
    print(f"\n📈 RSI ANALYSIS SUMMARY")
    print(f"📊 Interval: {interval}, Lookback: {lookback_hours} hours")
    print("=" * 60)
    print(f"Total coins analyzed: {len(df)}")
    print(f"Coins with RSI < {rsi_threshold}: {len(df[df['rsi'] < rsi_threshold])}")
    print(f"Coins with RSI < 20 (Extremely Oversold): {len(df[df['rsi'] < 20])}")
    print(f"Coins with RSI > 70 (Overbought): {len(df[df['rsi'] > 70])}")
    print(f"Coins with RSI > 80 (Extremely Overbought): {len(df[df['rsi'] > 80])}")
    
    print(f"\n📊 RSI STATISTICS:")
    print(f"Average RSI: {df['rsi'].mean():.2f}")
    print(f"Median RSI: {df['rsi'].median():.2f}")
    print(f"Lowest RSI: {df['rsi'].min():.2f} ({df.loc[df['rsi'].idxmin(), 'symbol']})")
    print(f"Highest RSI: {df['rsi'].max():.2f} ({df.loc[df['rsi'].idxmax(), 'symbol']})")
    
    print(f"\n💰 PRICE CHANGE STATISTICS ({lookback_hours}h):")
    print(f"Average Change: {df[change_col].mean():.2f}%")
    print(f"Best Performer: {df[change_col].max():.2f}% ({df.loc[df[change_col].idxmax(), 'symbol']})")
    print(f"Worst Performer: {df[change_col].min():.2f}% ({df.loc[df[change_col].idxmin(), 'symbol']})")

# Quick utility functions with time parameters
def quick_oversold_scan(rsi_threshold: float = 30.0, 
                    interval: str = "1h",
                    lookback_hours: int = 24,
                    top_n: int = 10) -> pd.DataFrame:
    """Quick scan for most oversold coins with custom timeframe"""
    df = get_low_rsi_coins(rsi_threshold, interval=interval, 
                        lookback_hours=lookback_hours, verbose=False)
    return df.head(top_n) if not df.empty else df

def get_extreme_rsi_coins(min_rsi: float = 0, 
                        max_rsi: float = 100,
                        interval: str = "1h",
                        lookback_hours: int = 24) -> pd.DataFrame:
    """Get coins within specific RSI range with custom timeframe"""
    df = get_all_coins_rsi(interval=interval, lookback_hours=lookback_hours, verbose=False)
    if not df.empty:
        return df[(df['rsi'] >= min_rsi) & (df['rsi'] <= max_rsi)]
    return df

def compare_timeframes(symbol: str, intervals: List[str] = ["1h", "4h", "1d"]) -> pd.DataFrame:
    """Compare RSI across different timeframes for a single coin"""
    results = []
    
    for interval in intervals:
        coin_data = get_coin_data(symbol, interval=interval, lookback_hours=24)
        if coin_data:
            results.append({
                'symbol': symbol,
                'interval': interval,
                'rsi': coin_data['rsi'],
                'current_price': coin_data['current_price'],
                'change_24h': coin_data['change_24h']
            })
    
    return pd.DataFrame(results)


# Example usage with different timeframes:
"""
# 4-hour RSI analysis
oversold_4h = get_low_rsi_coins(rsi_threshold=30, interval="4h", lookback_hours=24)

# Daily RSI analysis
oversold_daily = get_low_rsi_coins(rsi_threshold=30, interval="1d", lookback_hours=168)  # 1 week lookback

# 15-minute RSI for scalping
oversold_15m = get_low_rsi_coins(rsi_threshold=25, interval="15m", lookback_hours=4)

# All coins with 4-hour timeframe
all_coins_4h = get_all_coins_rsi(interval="4h", lookback_hours=48)

# Quick scans
top_oversold_4h = quick_oversold_scan(30, interval="4h", lookback_hours=24, top_n=5)
extremely_oversold_daily = get_extreme_rsi_coins(0, 20, interval="1d", lookback_hours=168)

# Compare timeframes for a specific coin
btc_comparison = compare_timeframes("BTCUSDT", ["1h", "4h", "1d"])

# Analysis
analyze_rsi_dataframe(oversold_4h)
"""