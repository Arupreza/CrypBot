import requests
import pandas as pd
import numpy as np
import ccxt
from scipy import stats
from datetime import datetime
import time
import warnings
warnings.filterwarnings('ignore')

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
            'ATOM': 'ATOMUSDT'
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
            response = requests.get(url, params=params)
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

######## ZLSMA ########

def linreg(data, length, offset=0):
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
    min_required = 2 * length - 1
    if len(data) < min_required:
        return pd.Series(np.nan, index=data.index)
    
    lsma = linreg(data, length, offset)
    lsma2 = linreg(lsma, length, offset)
    eq = lsma - lsma2
    zlsma_result = lsma + eq
    
    return zlsma_result

def calculate_zlsma(in_df, close_column='close', timestamp_column=None, length=32, plot=False):
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

def fetch_perpetual_data(symbol, timeframe='15m', limit=500):
    """Fetch perpetual data using BinancePerpetualFetcher"""
    try:
        fetcher = BinancePerpetualFetcher()
        df = fetcher.get_klines(symbol, interval=timeframe, limit=limit)
        return df
    except Exception as e:
        print(f"Error fetching perpetual data for {symbol}: {e}")
        return None

def check_price_vs_zlsma_perpetual(symbol, length=200, timeframe='15m', limit=500, trade_type='long'):
    """
    Check ZLSMA condition - NO candle count limitation here
    This function only checks if current price is above/below ZLSMA based on trade_type
    """
    df = fetch_perpetual_data(symbol, timeframe, limit)
    if df is None or len(df) < 2 * length - 1:
        return None
    
    df = calculate_zlsma(df, close_column='close', timestamp_column='timestamp', length=length, plot=False)
    
    latest_row = df.iloc[-1]
    current_price = latest_row['close']
    zlsma_value = latest_row[f'zlsma_{length}']
    
    if pd.isna(zlsma_value):
        return None
    
    # Simple ZLSMA condition check - no candle count involved
    if trade_type.lower() == 'long':
        condition_met = current_price > zlsma_value
        price_distance = current_price - zlsma_value
    else:  # short
        condition_met = current_price < zlsma_value
        price_distance = zlsma_value - current_price
    
    if condition_met:
        return {
            'symbol': symbol,
            'current_price': current_price,
            'zlsma_200': zlsma_value,
            'price_distance_zlsma': price_distance,
            'trade_type': trade_type.upper(),
            'contract_type': 'PERPETUAL'
        }
    
    return None

######## Simplified Momentum Indicator (replacing Chandelier Exit) ########

def simple_momentum_signal(df: pd.DataFrame, lookback: int = 10) -> pd.DataFrame:
    """
    Simplified momentum signal without ATR calculations
    Uses simple price momentum and moving average crossovers
    """
    df_result = df.copy()
    
    # Simple momentum calculation
    df_result['momentum'] = df['close'].pct_change(lookback)
    
    # Simple moving averages for trend direction
    df_result['sma_fast'] = df['close'].rolling(window=5).mean()
    df_result['sma_slow'] = df['close'].rolling(window=20).mean()
    
    # Generate signals based on momentum and trend
    # Buy signal: positive momentum + fast MA > slow MA
    buy_condition = (
        (df_result['momentum'] > 0) & 
        (df_result['sma_fast'] > df_result['sma_slow']) &
        (df_result['close'] > df_result['sma_fast'])
    )
    
    # Sell signal: negative momentum + fast MA < slow MA
    sell_condition = (
        (df_result['momentum'] < 0) & 
        (df_result['sma_fast'] < df_result['sma_slow']) &
        (df_result['close'] < df_result['sma_fast'])
    )
    
    df_result['buy_signal'] = buy_condition.astype(int)
    df_result['sell_signal'] = sell_condition.astype(int)
    
    # Direction based on signals
    df_result['direction'] = np.where(buy_condition, 1, np.where(sell_condition, -1, 0))
    
    return df_result

def calculate_simple_momentum(in_df: pd.DataFrame, lookback: int = 10, timestamp_column: str = None) -> pd.DataFrame:
    df = in_df.copy()

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

    missing = [c for c in ['high', 'low', 'close'] if c not in df.columns]
    if missing:
        raise ValueError(f"calculate_simple_momentum: Missing required columns: {missing}")

    df_momentum = simple_momentum_signal(df, lookback=lookback)

    if 'timestamp' not in df_momentum.columns:
        df_momentum['timestamp'] = df_momentum.index

    return df_momentum

class SimplePerpetualScanner:
    def __init__(self):
        self.fetcher = BinancePerpetualFetcher()
    
    def get_perpetual_klines(self, symbol, timeframe='15m', limit=100):
        """Get perpetual klines data"""
        try:
            df = self.fetcher.get_klines(symbol, interval=timeframe, limit=limit)
            if df is None or len(df) < 30:
                return None
            return df
        except Exception as e:
            print(f"Error fetching perpetual data for {symbol}: {e}")
            return None
    
    def count_consecutive_signals(self, df, signal_type='buy'):
        """Count consecutive signals - THIS IS WHERE max_signal_candles applies"""
        if df is None or len(df) < 2:
            return False, 0, None
        
        signal_column = f"{signal_type}_signal"
        current_signal = df[signal_column].iloc[-1]
        if current_signal != 1:
            return False, 0, None
        
        consecutive_count = 0
        signal_start_idx = None
        
        # Count consecutive signals from the latest candle backward
        for i in range(len(df) - 1, -1, -1):
            if df[signal_column].iloc[i] == 1:
                consecutive_count += 1
                if signal_start_idx is None:
                    signal_start_idx = i
            else:
                break
        
        return True, consecutive_count, signal_start_idx
    
    def check_momentum_signal_perpetual(self, symbol, timeframe='15m', limit=100, max_signal_candles=3, trade_type='long'):
        """
        Check momentum signal with candle count limitation
        max_signal_candles ONLY applies here for momentum signals
        """
        try:
            df = self.get_perpetual_klines(symbol, timeframe, limit)
            if df is None:
                return None
            
            df = calculate_simple_momentum(df, lookback=10)
            
            signal_type = 'buy' if trade_type.lower() == 'long' else 'sell'
            is_signal_active, consecutive_count, signal_start_idx = self.count_consecutive_signals(df, signal_type)
            
            # KEY CHANGE: max_signal_candles only applies to momentum signals
            if is_signal_active and consecutive_count <= max_signal_candles:
                current_price = df['close'].iloc[-1]
                signal_start_time = df['timestamp'].iloc[signal_start_idx]
                current_time = df['timestamp'].iloc[-1]
                
                opposite_signal_type = 'sell' if signal_type == 'buy' else 'buy'
                prev_opposite_idx = None
                for j in range(signal_start_idx - 1, -1, -1):
                    if df[f'{opposite_signal_type}_signal'].iloc[j] == 1:
                        prev_opposite_idx = j
                        break
                
                return {
                    'symbol': symbol,
                    'current_price': current_price,
                    'current_signal': signal_type.upper(),
                    'signal_candles_count': consecutive_count,
                    'signal_start_time': signal_start_time,
                    'current_time': current_time,
                    'prev_opposite_time': df['timestamp'].iloc[prev_opposite_idx] if prev_opposite_idx else None,
                    'prev_opposite_price': df['close'].iloc[prev_opposite_idx] if prev_opposite_idx else None,
                    'momentum': df['momentum'].iloc[-1],
                    'sma_fast': df['sma_fast'].iloc[-1],
                    'sma_slow': df['sma_slow'].iloc[-1],
                    'market_type': 'PERPETUAL',
                    'trade_type': trade_type.upper(),
                    'contract_type': 'PERPETUAL'
                }
            
            return None
            
        except Exception as e:
            print(f"Error checking momentum signal for {symbol}: {e}")
            return None

def scan_perpetual_simple(symbols, timeframe='15m', zlsma_length=200, zlsma_limit=500, momentum_limit=100, max_signal_candles=3, trade_type='both'):
    """
    Modified perpetual scan with clear separation:
    1. max_signal_candles applies ONLY to momentum signals (Step 1)
    2. ZLSMA check is independent of candle count (Step 2)
    
    Parameters:
    symbols: list - List of symbols to scan (e.g., ['BTCUSDT', 'ETHUSDT'])
    timeframe: str - Timeframe for analysis (default '15m')
    zlsma_length: int - ZLSMA period (default 200)
    zlsma_limit: int - Candles for ZLSMA calculation (default 500)
    momentum_limit: int - Candles for momentum analysis (default 100)
    max_signal_candles: int - Max consecutive signal candles (ONLY for momentum, default 3)
    trade_type: str - 'long', 'short', or 'both' (default 'both')
    
    Returns:
    pandas DataFrame - Filtered results
    """
    if not symbols:
        return pd.DataFrame()
    
    trade_types_to_check = []
    if trade_type.lower() in ['long', 'both']:
        trade_types_to_check.append('long')
    if trade_type.lower() in ['short', 'both']:
        trade_types_to_check.append('short')
    
    if not trade_types_to_check:
        print("Invalid trade_type. Must be 'long', 'short', or 'both'")
        return pd.DataFrame()
    
    # Normalize symbol names
    fetcher = BinancePerpetualFetcher()
    normalized_coins = []
    for coin in symbols:
        normalized_symbol = fetcher._format_symbol(coin)
        normalized_coins.append(normalized_symbol)
    
    all_final_results = []
    
    for current_trade_type in trade_types_to_check:
        print(f"\n🔍 Scanning for {current_trade_type.upper()} opportunities...")
        
        # Step 1: Momentum Signal Filter (WITH max_signal_candles limit)
        scanner = SimplePerpetualScanner()
        momentum_passed_coins = []
        momentum_results = []
        
        print(f"⚡ Step 1: Checking Momentum signals (max {max_signal_candles} candles) on {len(normalized_coins)} coins...")
        
        for symbol in normalized_coins:
            momentum_result = scanner.check_momentum_signal_perpetual(
                symbol,
                timeframe=timeframe,
                limit=momentum_limit,
                max_signal_candles=max_signal_candles,  # Only applies to momentum
                trade_type=current_trade_type
            )
            
            if momentum_result is not None:
                momentum_passed_coins.append(symbol)
                momentum_results.append(momentum_result)
                print(f"✅ {symbol} passed Momentum filter ({momentum_result['signal_candles_count']} candles)")
            
            time.sleep(0.05)
        
        if not momentum_passed_coins:
            print(f"❌ No coins passed Momentum filter (within {max_signal_candles} candles) for {current_trade_type}")
            continue
        
        print(f"📊 {len(momentum_passed_coins)} coins passed Momentum filter")
        
        # Step 2: ZLSMA Filter (NO candle count limitation)
        print(f"📈 Step 2: Checking ZLSMA {zlsma_length} condition (no candle limit) on {len(momentum_passed_coins)} coins...")
        
        for symbol in momentum_passed_coins:
            zlsma_result = check_price_vs_zlsma_perpetual(
                symbol, 
                length=zlsma_length, 
                timeframe=timeframe, 
                limit=zlsma_limit,
                trade_type=current_trade_type
            )
            
            if zlsma_result is not None:
                # Combine Momentum and ZLSMA data
                momentum_data = next((c for c in momentum_results if c['symbol'] == symbol), None)
                
                if momentum_data:
                    combined_result = {**momentum_data, **{
                        f'zlsma_{zlsma_length}': zlsma_result['zlsma_200'],
                        'price_distance_zlsma': zlsma_result['price_distance_zlsma']
                    }}
                    all_final_results.append(combined_result)
                    print(f"🎯 {symbol} - FINAL CANDIDATE! Passed both filters!")
            else:
                print(f"❌ {symbol} failed ZLSMA {zlsma_length} filter")
            
            time.sleep(0.05)
    
    if not all_final_results:
        print("❌ No trading opportunities found after both filters")
        return pd.DataFrame()
    
    # Create results DataFrame
    results_df = pd.DataFrame(all_final_results)
    results_df = results_df.sort_values(['trade_type', 'signal_candles_count', 'price_distance_zlsma'], 
                                    ascending=[True, True, False])
    
    print(f"\n🎉 Found {len(results_df)} final trading opportunities!")
    print(f"💡 Note: max_signal_candles={max_signal_candles} was applied only to momentum signals")
    print(f"📊 ZLSMA {zlsma_length} filter was applied without candle count limitation")
    
    return results_df


# # Example usage with clear explanation
# if __name__ == "__main__":
#     # Example symbols to scan
#     symbols = ['BTC', 'ETH', 'BNB', 'ADA', 'SOL', 'DOT', 'MATIC', 'LINK', 'AVAX', 'ATOM']
    
#     print("="*80)
#     print("PERPETUAL SCANNER - MODIFIED LOGIC")
#     print("="*80)
#     print("Step 1: Momentum Signal Check (max_signal_candles=3 applies here)")
#     print("Step 2: ZLSMA 200 Check (no candle limitation)")
#     print("="*80)
    
#     # Run the scan
#     start_time = time.time()
    
#     results = scan_perpetual_simple(
#         symbols=symbols,
#         timeframe='15m',
#         zlsma_length=200,      # ZLSMA period
#         zlsma_limit=500,       # Candles for ZLSMA calculation
#         momentum_limit=100,    # Candles for momentum analysis
#         max_signal_candles=3,  # ONLY applies to momentum signals
#         trade_type='both'      # 'long', 'short', or 'both'
#     )
    
#     scan_time = time.time() - start_time
    
#     if not results.empty:
#         print("\n" + "="*80)
#         print("FINAL RESULTS:")
#         print("="*80)
#         for idx, row in results.iterrows():
#             print(f"\n🎯 {row['symbol']} - {row['trade_type']} Signal")
#             print(f"   Current Price: ${row['current_price']:.4f}")
#             print(f"   Momentum Signal Candles: {row['signal_candles_count']} (≤3)")
#             print(f"   ZLSMA 200: ${row['zlsma_200']:.4f}")
#             print(f"   Price Distance from ZLSMA: ${row['price_distance_zlsma']:.4f}")
#             print(f"   Momentum: {row['momentum']:.4f}")
#     else:
#         print("\n❌ No opportunities found!")
    
#     print(f"\n⏱️ Total scan time: {scan_time:.2f} seconds")
#     print(f"📊 Average time per symbol: {scan_time/len(symbols):.2f} seconds")