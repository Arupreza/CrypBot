import pandas as pd
import numpy as np
import requests
from scipy import stats
from datetime import datetime
import time
import warnings
warnings.filterwarnings('ignore')

######## ZLSMA ########

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
    if len(data) < length:
        return pd.Series(np.nan, index=data.index)
    
    result = np.full(len(data), np.nan)
    
    for i in range(len(data)):
        if i < length - 1:
            result[i] = np.nan
        else:
            start_idx = i - length + 1
            end_idx = i + 1
            window_data = data.iloc[start_idx:end_idx]
            
            # Skip if any NaN values in the window
            if window_data.isna().any():
                result[i] = np.nan
                continue
                
            window = window_data.values
            x = np.arange(length)
            
            try:
                # Use numpy polyfit which is more robust
                coeffs = np.polyfit(x, window, 1)
                slope, intercept = coeffs
                reg_value = slope * (length - 1 + offset) + intercept
                result[i] = reg_value
            except (np.linalg.LinAlgError, ValueError):
                result[i] = np.nan
    
    return pd.Series(result, index=data.index)

def zlsma(data, length=32, offset=0):
    """
    Calculate Zero Lag LSMA - Fixed version matching Pine Script logic
    
    Parameters:
    data: pandas Series - input data (typically close prices)
    length: int - period for ZLSMA calculation (default 32)
    offset: int - offset parameter (default 0)
    
    Returns:
    pandas Series - ZLSMA values
    """
    min_required = 2 * length - 1
    if len(data) < min_required:
        print(f"ZLSMA: Need at least {min_required} data points, got {len(data)}")
        return pd.Series(np.nan, index=data.index)
    
    # Reset index to ensure proper calculation
    data_reset = data.reset_index(drop=True)
    
    lsma = linreg(data_reset, length, offset)
    lsma2 = linreg(lsma, length, offset)
    eq = lsma - lsma2
    zlsma_result = lsma + eq
    
    # Restore original index
    zlsma_result.index = data.index
    
    return zlsma_result

def calculate_zlsma(in_df, close_column='close', timestamp_column=None, length=32, plot=True):
    """
    Load DataFrame, calculate ZLSMA, and optionally plot the results
    
    Parameters:
    in_df: pandas DataFrame - input DataFrame
    close_column: str - name of the close price column (default 'close')
    timestamp_column: str - name of the timestamp column (if None, will try to auto-detect)
    length: int - ZLSMA length parameter (default 32)
    plot: bool - whether to plot the results (default True)
    
    Returns:
    pandas DataFrame - DataFrame with original data and ZLSMA column
    """
    df = in_df.copy()
    
    if timestamp_column is None:
        timestamp_candidates = ['timestamp', 'time', 'date', 'datetime', 'Date', 'Time', 'DateTime']
        for col in timestamp_candidates:
            if col in df.columns:
                timestamp_column = col
                break
    
    if timestamp_column and timestamp_column in df.columns:
        df[timestamp_column] = pd.to_datetime(df[timestamp_column])
    
    min_required = 2 * length - 1
    df[f'zlsma_{length}'] = zlsma(df[close_column], length=length)
    
    return df

######## Chandelier Exit ########

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
    Main function to calculate Chandelier Exit with proper timestamp handling
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

######## Data Fetching ########

class BinancePerpetualFetcher:
    def __init__(self):
        self.base_url = "https://fapi.binance.com"
    
    def _format_symbol(self, symbol):
        """Auto-format common symbols to proper trading pairs"""
        symbol = symbol.upper().strip()
        
        # Common symbol mappings
        symbol_map = {
            'BTC': 'BTCUSDT',
            'ETH': 'ETHUSDT', 
            'BNB': 'BNBUSDT',
            'ADA': 'ADAUSDT',
            'SOL': 'SOLUSDT',
            'DOT': 'DOTUSDT',
            'MATIC': 'MATICUSDT',
            'LINK': 'LINKUSDT',
            'AVAX': 'AVAXUSDT',
            'ATOM': 'ATOMUSDT',
            'NEAR': 'NEARUSDT',
            'FTM': 'FTMUSDT',
            'UNI': 'UNIUSDT',
            'AAVE': 'AAVEUSDT',
            'ALGO': 'ALGOUSDT',
            'XRP': 'XRPUSDT',
            'LTC': 'LTCUSDT',
            'BCH': 'BCHUSDT',
            'ETC': 'ETCUSDT',
            'TRX': 'TRXUSDT'
        }
        
        # If it's a simple symbol, convert to USDT pair
        if symbol in symbol_map:
            return symbol_map[symbol]
        
        # If it doesn't end with USDT, BUSD, etc., assume it needs USDT
        if not any(symbol.endswith(quote) for quote in ['USDT', 'BUSD', 'USDC']):
            return f"{symbol}USDT"
        
        return symbol
    
    def get_klines(self, symbol, interval='15m', limit=500):
        """Get candlestick data for perpetual futures"""
        try:
            symbol = self._format_symbol(symbol)
            url = f"{self.base_url}/fapi/v1/klines"
            params = {
                'symbol': symbol.upper(),
                'interval': interval,
                'limit': limit
            }
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            if not data:
                return None
            
            # Convert to DataFrame format
            df = pd.DataFrame(data, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_asset_volume', 'number_of_trades',
                'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'
            ])
            
            # Keep only needed columns and convert types
            df = df[['timestamp', 'open', 'high', 'low', 'close', 'volume']].copy()
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            
            return df
            
        except requests.RequestException as e:
            print(f"Error fetching perpetual data for {symbol}: {e}")
            return None
        except Exception as e:
            print(f"Unexpected error for {symbol}: {e}")
            return None

def fetch_binance_data(symbol, timeframe='15m', limit=500):
    """
    Fetch historical candlestick data from Binance Perpetual Futures
    
    Parameters:
    symbol: str - Trading pair (e.g., 'BTCUSDT' or 'BTC')
    timeframe: str - Candlestick timeframe (default '15m')
    limit: int - Number of candles to fetch (default 500)
    
    Returns:
    pandas DataFrame - OHLCV data with timestamp and close price
    """
    fetcher = BinancePerpetualFetcher()
    return fetcher.get_klines(symbol, timeframe, limit)

######## Signal Detection Functions ########

def check_chandelier_buy_signal(df, max_signal_candles):
    """
    Check if current signal is buy and within max_signal_candles limit
    Returns: (is_buy, consecutive_count)
    """
    if df is None or len(df) < 2:
        return False, 0
    
    current_signal = df['buy_signal'].iloc[-1]
    if current_signal != 1:
        return False, 0
    
    # Count consecutive buy signals from the end
    consecutive_count = 0
    for i in range(len(df) - 1, -1, -1):
        if df['buy_signal'].iloc[i] == 1:
            consecutive_count += 1
        else:
            break
    
    return consecutive_count <= max_signal_candles, consecutive_count

def check_chandelier_sell_signal(df, max_signal_candles):
    """
    Check if current signal is sell and within max_signal_candles limit
    Returns: (is_sell, consecutive_count)
    """
    if df is None or len(df) < 2:
        return False, 0
    
    current_signal = df['sell_signal'].iloc[-1]
    if current_signal != 1:
        return False, 0
    
    # Count consecutive sell signals from the end
    consecutive_count = 0
    for i in range(len(df) - 1, -1, -1):
        if df['sell_signal'].iloc[i] == 1:
            consecutive_count += 1
        else:
            break
    
    return consecutive_count <= max_signal_candles, consecutive_count

def find_buy_signal_start(df):
    """Find the index where the current buy signal started"""
    if df is None or len(df) < 2:
        return None
    
    signal_start_idx = None
    for i in range(len(df) - 1, -1, -1):
        if df['buy_signal'].iloc[i] == 1:
            signal_start_idx = i
        else:
            break
    
    return signal_start_idx

def find_sell_signal_start(df):
    """Find the index where the current sell signal started"""
    if df is None or len(df) < 2:
        return None
    
    signal_start_idx = None
    for i in range(len(df) - 1, -1, -1):
        if df['sell_signal'].iloc[i] == 1:
            signal_start_idx = i
        else:
            break
    
    return signal_start_idx

def find_previous_sell_signal(df, signal_start_idx):
    """Find the previous sell signal before current buy signal"""
    if df is None or signal_start_idx is None:
        return {'prev_sell_time': None, 'prev_sell_price': None}
    
    for i in range(signal_start_idx - 1, -1, -1):
        if df['sell_signal'].iloc[i] == 1:
            return {
                'prev_sell_time': df['timestamp'].iloc[i],
                'prev_sell_price': df['close'].iloc[i]
            }
    
    return {'prev_sell_time': None, 'prev_sell_price': None}

def find_previous_buy_signal(df, signal_start_idx):
    """Find the previous buy signal before current sell signal"""
    if df is None or signal_start_idx is None:
        return {'prev_buy_time': None, 'prev_buy_price': None}
    
    for i in range(signal_start_idx - 1, -1, -1):
        if df['buy_signal'].iloc[i] == 1:
            return {
                'prev_buy_time': df['timestamp'].iloc[i],
                'prev_buy_price': df['close'].iloc[i]
            }
    
    return {'prev_buy_time': None, 'prev_buy_price': None}

######## Main Analysis Functions ########

def analyze_single_coin(symbol, timeframe='15m', chandelier_limit=200, zlsma_limit=1000, 
                       atr_period=1, atr_multiplier=2.0, zlsma_length=200, max_signal_candles=3,
                       signal_type='both'):
    """
    Analyze a single coin with both Chandelier Exit and ZLSMA indicators (Perpetual Futures)
    
    Parameters:
    symbol: str - Trading pair (e.g., 'BTCUSDT' or 'BTC')
    timeframe: str - Timeframe for analysis (default '15m')
    chandelier_limit: int - Number of candles for Chandelier analysis (default 200)
    zlsma_limit: int - Number of candles for ZLSMA calculation (default 1000)
    atr_period: int - ATR period for Chandelier (default 1)
    atr_multiplier: float - ATR multiplier for Chandelier (default 2.0)
    zlsma_length: int - ZLSMA period (default 200)
    max_signal_candles: int - Maximum consecutive signal candles to consider (default 3)
    signal_type: str - 'buy', 'sell', or 'both' (default 'both')
    
    Returns:
    dict - Analysis results or None if failed
    """
    try:
        # Normalize symbol
        if isinstance(symbol, str):
            symbol = symbol.upper().strip()
            if not symbol.endswith('USDT') and '/' not in symbol:
                symbol = f"{symbol}USDT"
        
        #print(f"Analyzing {symbol} (PERP)...")
        
        # Calculate minimum required data for ZLSMA
        min_required = 2 * zlsma_length - 1
        actual_limit = max(zlsma_limit, min_required + 50)  # Add buffer
        
        #print(f"  Fetching {actual_limit} candles for ZLSMA calculation...")
        
        # Step 1: Fetch data for ZLSMA (needs more data)
        df_zlsma = fetch_binance_data(symbol, timeframe, actual_limit)
        if df_zlsma is None:
            print(f"  Failed to fetch ZLSMA data for {symbol}")
            return None
        
        #print(f"  Got {len(df_zlsma)} candles, calculating ZLSMA({zlsma_length})...")
        
        # Step 2: Calculate ZLSMA
        df_zlsma = calculate_zlsma(df_zlsma, close_column='close', timestamp_column='timestamp', 
                                  length=zlsma_length, plot=False)
        
        # Get current price and ZLSMA value
        latest_zlsma = df_zlsma.iloc[-1]
        current_price = latest_zlsma['close']
        zlsma_value = latest_zlsma[f'zlsma_{zlsma_length}']
        
        #print(f"  Current price: {current_price:.4f}, ZLSMA: {zlsma_value}")
        
        if pd.isna(zlsma_value):
            print(f"  {symbol}: ZLSMA value is still NaN - insufficient data or calculation error")
            # Try to find the last valid ZLSMA value
            zlsma_series = df_zlsma[f'zlsma_{zlsma_length}']
            valid_zlsma = zlsma_series.dropna()
            if len(valid_zlsma) > 0:
                zlsma_value = valid_zlsma.iloc[-1]
                print(f"  Using last valid ZLSMA: {zlsma_value:.4f}")
            else:
                print(f"  No valid ZLSMA values found - skipping {symbol}")
                return None
        
        # Step 3: Fetch data for Chandelier Exit (can use less data)
        df_chandelier = fetch_binance_data(symbol, timeframe, chandelier_limit)
        if df_chandelier is None:
            print(f"  Failed to fetch Chandelier data for {symbol}")
            return None
        
        # Step 4: Calculate Chandelier Exit
        df_chandelier = calculate_chandelier(
            df_chandelier,
            atr_period=atr_period,
            atr_multiplier=atr_multiplier,
            use_close=True
        )
        
        # Step 5: Check both buy and sell signals
        buy_active, buy_count = check_chandelier_buy_signal(df_chandelier, max_signal_candles)
        sell_active, sell_count = check_chandelier_sell_signal(df_chandelier, max_signal_candles)
        
        # Determine which signal to process based on signal_type
        signal_to_process = None
        if signal_type == 'buy' and buy_active:
            signal_to_process = 'BUY'
        elif signal_type == 'sell' and sell_active:
            signal_to_process = 'SELL'
        elif signal_type == 'both':
            if buy_active:
                signal_to_process = 'BUY'
            elif sell_active:
                signal_to_process = 'SELL'
        
        if not signal_to_process:
            #print(f"  {symbol}: No active {signal_type} signal")
            return None
        
        # Step 6: Apply ZLSMA filter based on signal direction
        if signal_to_process == 'BUY':
            if current_price <= zlsma_value:
                #print(f"  {symbol}: BUY signal but price {current_price:.4f} not above ZLSMA {zlsma_value:.4f}")
                return None
            consecutive_count = buy_count
            signal_start_idx = find_buy_signal_start(df_chandelier)
        else:  # SELL signal
            if current_price >= zlsma_value:
                #print(f"  {symbol}: SELL signal but price {current_price:.4f} not below ZLSMA {zlsma_value:.4f}")
                return None
            consecutive_count = sell_count
            signal_start_idx = find_sell_signal_start(df_chandelier)
        
        # Step 7: Compile results
        result = {
            'symbol': symbol,
            'current_price': current_price,
            'zlsma_value': zlsma_value,
            'price_vs_zlsma': current_price - zlsma_value,
            'zlsma_percentage': ((current_price - zlsma_value) / zlsma_value) * 100,
            'current_signal': signal_to_process,
            'signal_candles_count': consecutive_count,
            'signal_start_time': df_chandelier['timestamp'].iloc[signal_start_idx] if signal_start_idx else None,
            'current_time': df_chandelier['timestamp'].iloc[-1],
            'atr_value': df_chandelier['atr'].iloc[-1],
            'long_stop': df_chandelier['long_stop'].iloc[-1],
            'short_stop': df_chandelier['short_stop'].iloc[-1],
            'chandelier_exit': df_chandelier['chandelier_exit'].iloc[-1]
        }
        
        # Add previous opposite signal info
        if signal_to_process == 'BUY':
            prev_signal_info = find_previous_sell_signal(df_chandelier, signal_start_idx)
            result.update(prev_signal_info)
            #print(f"  ✓ {symbol}: BUY signal ({consecutive_count} candles), Price above ZLSMA by {result['zlsma_percentage']:.2f}%")
        else:
            prev_signal_info = find_previous_buy_signal(df_chandelier, signal_start_idx)
            result.update(prev_signal_info)
            #print(f"  ✓ {symbol}: SELL signal ({consecutive_count} candles), Price below ZLSMA by {abs(result['zlsma_percentage']):.2f}%")
        
        return result
        
    except Exception as e:
        print(f"  Error analyzing {symbol}: {e}")
        import traceback
        traceback.print_exc()
        return None

def Chandelier_ZLSMA_Scan(coin_list, timeframe='15m', chandelier_limit=200, zlsma_limit=1000,
                       atr_period=1, atr_multiplier=2.0, zlsma_length=200, max_signal_candles=3,
                       signal_type='both'):
    """
    Scan multiple coins with Chandelier Exit and ZLSMA analysis (Perpetual Futures)
    
    Parameters:
    coin_list: list - List of coins to scan (e.g., ['BTC', 'ETH', 'ADA'] or ['BTCUSDT', 'ETHUSDT'])
    timeframe: str - Timeframe for analysis (default '15m')
    chandelier_limit: int - Number of candles for Chandelier analysis (default 200)
    zlsma_limit: int - Number of candles for ZLSMA calculation (default 1000)
    atr_period: int - ATR period for Chandelier (default 1)
    atr_multiplier: float - ATR multiplier for Chandelier (default 2.0)
    zlsma_length: int - ZLSMA period (default 200)
    max_signal_candles: int - Maximum consecutive signal candles to consider (default 3)
    signal_type: str - 'buy', 'sell', or 'both' (default 'both')
    
    Returns:
    pandas DataFrame - Scan results sorted by signal_candles_count
    """
    if not coin_list:
        print("No coins provided for scanning")
        return pd.DataFrame()
    
    signal_desc = signal_type.upper() if signal_type != 'both' else 'BUY/SELL'
    
    #print(f"Starting scan of {len(coin_list)} coins on PERPETUAL FUTURES...")
    #print(f"Parameters: {timeframe} timeframe, ZLSMA({zlsma_length}), Chandelier({atr_period}, {atr_multiplier})")
    #print(f"Looking for: {signal_desc} signals, Max signal candles: {max_signal_candles}")
    #print("-" * 80)
    
    results = []
    
    for i, coin in enumerate(coin_list, 1):
        #print(f"[{i}/{len(coin_list)}] ", end="")
        
        result = analyze_single_coin(
            coin, timeframe, chandelier_limit, zlsma_limit,
            atr_period, atr_multiplier, zlsma_length, max_signal_candles, signal_type
        )
        
        if result:
            results.append(result)
        
        # Rate limiting
        time.sleep(0.1)
    
    print("-" * 80)
    print(f"Scan complete. Found {len(results)} coins matching criteria.")
    
    if results:
        df = pd.DataFrame(results)
        df = df.sort_values('signal_candles_count')
        return df
    else:
        return pd.DataFrame()

######## Convenience Functions ########

def scan_buy_signals_only(coin_list, **kwargs):
    """Convenience function to scan for buy signals only"""
    return Chandelier_ZLSMA_Scan(coin_list, signal_type='buy', **kwargs)

def scan_sell_signals_only(coin_list, **kwargs):
    """Convenience function to scan for sell signals only"""
    return Chandelier_ZLSMA_Scan(coin_list, signal_type='sell', **kwargs)

def scan_all_signals(coin_list, **kwargs):
    """Convenience function to scan for both buy and sell signals"""
    return Chandelier_ZLSMA_Scan(coin_list, signal_type='both', **kwargs)

######## Advanced Scanner Class ########

class PerpetualFuturesScanner:
    """
    Advanced scanner class for Binance Perpetual Futures with Chandelier Exit and ZLSMA
    """
    
    def __init__(self, atr_period=1, atr_multiplier=2.0, zlsma_length=200):
        self.atr_period = atr_period
        self.atr_multiplier = atr_multiplier
        self.zlsma_length = zlsma_length
        self.fetcher = BinancePerpetualFetcher()
        
    def scan_coins(self, coin_list, timeframe='15m', max_signal_candles=3, signal_type='both'):
        """Scan coins with current settings"""
        return Chandelier_ZLSMA_Scan(
            coin_list=coin_list,
            timeframe=timeframe,
            atr_period=self.atr_period,
            atr_multiplier=self.atr_multiplier,
            zlsma_length=self.zlsma_length,
            max_signal_candles=max_signal_candles,
            signal_type=signal_type
        )
    
    def analyze_coin(self, symbol, timeframe='15m', max_signal_candles=3, signal_type='both'):
        """Analyze a single coin with current settings"""
        return analyze_single_coin(
            symbol=symbol,
            timeframe=timeframe,
            atr_period=self.atr_period,
            atr_multiplier=self.atr_multiplier,
            zlsma_length=self.zlsma_length,
            max_signal_candles=max_signal_candles,
            signal_type=signal_type
        )
    
    def update_settings(self, atr_period=None, atr_multiplier=None, zlsma_length=None):
        """Update scanner settings"""
        if atr_period is not None:
            self.atr_period = atr_period
        if atr_multiplier is not None:
            self.atr_multiplier = atr_multiplier
        if zlsma_length is not None:
            self.zlsma_length = zlsma_length
            
            

# results_both = Chandelier_ZLSMA_Scan(
#     coin_list=custom_coins,
#     timeframe='15m',
#     chandelier_limit=200,
#     zlsma_limit=500,
#     atr_period=1,
#     atr_multiplier=2.0,
#     zlsma_length=200,
#     max_signal_candles=3,
#     signal_type='both'
# )


# results_buy = Chandelier_ZLSMA_Scan(
#     coin_list=custom_coins,
#     signal_type='buy'
# )



# results_sell = Chandelier_ZLSMA_Scan(
#     coin_list=custom_coins,
#     signal_type='sell'
# )