import ccxt
import pandas as pd
import numpy as np
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
    result = np.full(len(data), np.nan)
    
    for i in range(len(data)):
        if i < length - 1:
            result[i] = np.nan
        else:
            window_data = data.iloc[i-length+1:i+1]
            
            if window_data.isna().any():
                result[i] = np.nan
                continue
                
            window = window_data.values
            x = np.arange(length)
            
            try:
                slope, intercept, _, _, _ = stats.linregress(x, window)
                reg_value = slope * (length - 1 + offset) + intercept
                result[i] = reg_value
            except:
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
        return pd.Series(np.nan, index=data.index)
    
    lsma = linreg(data, length, offset)
    lsma2 = linreg(lsma, length, offset)
    eq = lsma - lsma2
    zlsma_result = lsma + eq
    
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
    else:
        x_axis = df.index
    
    min_required = 2 * length - 1
    df[f'zlsma_{length}'] = zlsma(df[close_column], length=length)
    
    return df

def fetch_binance_data(symbol, timeframe='15m', limit=500):
    """
    Fetch historical candlestick data from Binance for a given symbol.
    
    Parameters:
    symbol: str - Trading pair (e.g., 'BTCUSDT')
    timeframe: str - Candlestick timeframe (default '15m')
    limit: int - Number of candles to fetch (default 500)
    
    Returns:
    pandas DataFrame - OHLCV data with timestamp and close price
    """
    try:
        exchange = ccxt.binance()
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        
        return df
    except Exception:
        return None

def filter_coins_above_zlsma(symbols, length=200, timeframe='15m', limit=500):
    """
    Calculate ZLSMA(200) for a list of symbols and filter those with current price > ZLSMA.
    
    Parameters:
    symbols: list - List of tradingėd
    pairs (e.g., ['BTCUSDT', 'ETHUSDT'])
    length: int - ZLSMA period (default 200)
    timeframe: str - Candlestick timeframe (default '15m')
    limit: int - Number of candles to fetch (default 500)
    
    Returns:
    pandas DataFrame - Filtered coins with current price and ZLSMA values
    """
    results = []
    
    for symbol in symbols:
        df = fetch_binance_data(symbol, timeframe, limit)
        if df is None or len(df) < 2 * length - 1:
            continue
        
        df = calculate_zlsma(df, close_column='close', timestamp_column='timestamp', length=length, plot=False)
        
        latest_row = df.iloc[-1]
        current_price = latest_row['close']
        zlsma_value = latest_row[f'zlsma_{length}']
        
        if pd.isna(zlsma_value):
            continue
        
        if current_price > zlsma_value:
            results.append({
                'symbol': symbol,
                'current_price': current_price,
                'zlsma_200': zlsma_value,
                'price_above_zlsma': current_price - zlsma_value
            })
    
    if results:
        results_df = pd.DataFrame(results)
        results_df = results_df.sort_values(by='price_above_zlsma', ascending=False)
        return results_df
    return pd.DataFrame()


######## Chandelier ########

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

class BinanceChandelierScanner:
    def __init__(self, api_key=None, api_secret=None):
        """Initialize Binance connection"""
        self.exchange = ccxt.binance({
            'apiKey': api_key,
            'secret': api_secret,
            'sandbox': False,
            'rateLimit': 1200,
            'enableRateLimit': True,
        })
        
    def get_usdt_pairs(self):
        """Get all active USDT trading pairs, excluding stablecoins"""
        stablecoins = [
            'GUSDUSDT', 'FRAXUSDT', 'USDDUSDT', 'MIMUSDT', 'LUSDUSDT', 'FEIUSDT', 'HUSDUSDT', 
            'SUSDUSDT', 'OUSDUSDT', 'USTCUSDT', 'VAIUSDT', 'DOLAUSDT', 'ALUSDUSDT', 'MUSDUSDT', 
            'DUSDUSDT', 'CUSDUSDT', 'NUSDUSDT', 'ZUSDUSDT', 'EURUSDT'
        ]
        try:
            markets = self.exchange.load_markets()
            usdt_pairs = []
            for symbol in markets.keys():
                if (symbol.endswith('/USDT') and 
                    markets[symbol]['active'] and 
                    markets[symbol]['spot']):
                    # Convert to Binance format: BTC/USDT -> BTCUSDT
                    binance_symbol = symbol.replace('/', '')
                    if binance_symbol not in stablecoins:
                        usdt_pairs.append(binance_symbol)
            
            # Filter out leveraged tokens
            filtered_pairs = [pair for pair in usdt_pairs 
                            if not any(x in pair for x in ['UP', 'DOWN', 'BEAR', 'BULL'])]
            return filtered_pairs
        except:
            return []
    
    def get_klines(self, symbol, timeframe='15m', limit=200):
        """Fetch OHLCV data for a symbol"""
        try:
            # Convert back to ccxt format for API call
            ccxt_symbol = symbol[:-4] + '/' + symbol[-4:]  # BTCUSDT -> BTC/USDT
            
            ohlcv = self.exchange.fetch_ohlcv(ccxt_symbol, timeframe, limit=limit)
            if not ohlcv or len(ohlcv) < 50:
                return None
                
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            return df
        except:
            return None
    
    def count_consecutive_buy_signals(self, df):
        """
        Count how many consecutive candles the current buy signal has been active
        Returns: (is_currently_buy, consecutive_count, signal_start_idx)
        """
        if df is None or len(df) < 2:
            return False, 0, None
        
        # Check if current signal is buy
        current_signal = df['buy_signal'].iloc[-1]
        if current_signal != 1:
            return False, 0, None
        
        # Count consecutive buy signals from the end
        consecutive_count = 0
        signal_start_idx = None
        
        for i in range(len(df) - 1, -1, -1):
            if df['buy_signal'].iloc[i] == 1:
                consecutive_count += 1
                signal_start_idx = i
            else:
                break
        
        return True, consecutive_count, signal_start_idx
    
    def scan_pairs(self, timeframe='15m', limit=200, max_buy_candles=3):
        """
        Scan USDT pairs for Chandelier Exit buy signals active for <= max_buy_candles
        """
        usdt_pairs = self.get_usdt_pairs()
        results = []
        
        for i, symbol in enumerate(usdt_pairs):
            try:
                # Get price data
                df = self.get_klines(symbol, timeframe, limit)
                if df is None:
                    continue
                
                # Calculate Chandelier Exit using your exact algorithm
                df = calculate_chandelier(
                    df, 
                    atr_period=1, 
                    atr_multiplier=2.0, 
                    use_close=True
                )
                
                # Check current signal status
                is_buy, consecutive_count, signal_start_idx = self.count_consecutive_buy_signals(df)
                
                if is_buy and consecutive_count <= max_buy_candles:
                    current_price = df['close'].iloc[-1]
                    if current_price > 30:
                        continue
                        
                    signal_start_time = df['timestamp'].iloc[signal_start_idx]
                    current_time = df['timestamp'].iloc[-1]
                    
                    # Get the sell signal that preceded this buy (if any)
                    prev_sell_idx = None
                    for j in range(signal_start_idx - 1, -1, -1):
                        if df['sell_signal'].iloc[j] == 1:
                            prev_sell_idx = j
                            break
                    
                    results.append({
                        'symbol': symbol,
                        'current_price': current_price,
                        'current_signal': 'BUY',
                        'buy_candles_count': consecutive_count,
                        'signal_start_time': signal_start_time,
                        'current_time': current_time,
                        'prev_sell_time': df['timestamp'].iloc[prev_sell_idx] if prev_sell_idx else None,
                        'prev_sell_price': df['close'].iloc[prev_sell_idx] if prev_sell_idx else None,
                        'atr_value': df['atr'].iloc[-1],
                        'long_stop': df['long_stop'].iloc[-1],
                        'short_stop': df['short_stop'].iloc[-1]
                    })
                
                # Rate limiting
                time.sleep(0.1)
                
            except:
                continue
        
        return results
    
    def display_results(self, results):
        """Return scanning results"""
        return results

def main():
    """Main function"""
    try:
        scanner = BinanceChandelierScanner()
        
        # Test connection
        markets = scanner.exchange.load_markets()
        
        # Run scan
        results = scanner.scan_pairs(
            timeframe='15m',      # 15-minute candles
            limit=200,            # Enough data for signals
            max_buy_candles=3     # Filter: ≤3 candles of buy signal
        )
        
        # Get results
        final_results = scanner.display_results(results)
        
        # Convert to DataFrame
        df_results = pd.DataFrame(final_results) if final_results else pd.DataFrame()
        
        return df_results
        
    except:
        return pd.DataFrame()

if __name__ == "__main__":
    df_results = main()
    


