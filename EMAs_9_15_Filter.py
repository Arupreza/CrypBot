import ccxt
import pandas as pd
import numpy as np
from datetime import datetime
import time
import warnings
warnings.filterwarnings('ignore')

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

def calculate_ema(data, period):
    """Calculate Exponential Moving Average"""
    return data.ewm(span=period, adjust=False).mean()

def calculate_ema_cross(in_df, ema9_period=9, ema15_period=15, close_column='close', timestamp_column=None):
    """
    Calculate EMA9 and EMA15 with cross detection
    
    Parameters:
    in_df: pandas DataFrame - input DataFrame
    ema9_period: int - EMA9 period (default 9)
    ema15_period: int - EMA15 period (default 15)
    close_column: str - name of the close price column (default 'close')
    timestamp_column: str - name of the timestamp column (if None, will try to auto-detect)
    
    Returns:
    pandas DataFrame - DataFrame with original data and EMA columns
    """
    df = in_df.copy()
    
    # Handle timestamp column
    if timestamp_column is None:
        timestamp_candidates = ['timestamp', 'time', 'date', 'datetime', 'Date', 'Time', 'DateTime']
        for col in timestamp_candidates:
            if col in df.columns:
                timestamp_column = col
                break
    
    if timestamp_column and timestamp_column in df.columns:
        df[timestamp_column] = pd.to_datetime(df[timestamp_column])
    
    # Calculate EMAs
    df['ema9'] = calculate_ema(df[close_column], ema9_period)
    df['ema15'] = calculate_ema(df[close_column], ema15_period)
    
    # Calculate EMA cross signals
    df['ema9_above_ema15'] = df['ema9'] > df['ema15']
    df['ema9_below_ema15'] = df['ema9'] < df['ema15']
    
    # Detect crossovers - ENHANCED LOGIC
    # Golden cross: EMA9 crosses above EMA15
    df['golden_cross'] = (df['ema9'] > df['ema15']) & (df['ema9'].shift(1) <= df['ema15'].shift(1))
    # Death cross: EMA9 crosses below EMA15
    df['death_cross'] = (df['ema9'] < df['ema15']) & (df['ema9'].shift(1) >= df['ema15'].shift(1))
    
    # Price above/below EMAs
    df['price_above_ema9'] = df[close_column] > df['ema9']
    df['price_above_ema15'] = df[close_column] > df['ema15']
    df['price_above_both_emas'] = df['price_above_ema9'] & df['price_above_ema15']
    
    # EMA signal (1 for bullish, -1 for bearish, 0 for neutral)
    df['ema_signal'] = 0
    df.loc[df['ema9_above_ema15'] & df['price_above_both_emas'], 'ema_signal'] = 1
    df.loc[df['ema9_below_ema15'] & (~df['price_above_both_emas']), 'ema_signal'] = -1
    
    # Add EMA difference for strength analysis
    df['ema_diff'] = df['ema9'] - df['ema15']
    df['ema_diff_pct'] = (df['ema_diff'] / df['ema15']) * 100
    
    return df

class BinanceEMAAnalyzer:
    def __init__(self, api_key=None, api_secret=None):
        """Initialize Binance connection"""
        self.exchange = ccxt.binance({
            'apiKey': api_key,
            'secret': api_secret,
            'sandbox': False,
            'rateLimit': 1200,
            'enableRateLimit': True,
        })
        
    def normalize_symbol(self, symbol):
        """Convert symbol to proper format (e.g., 'BTC' -> 'BTCUSDT', 'BTCUSDT' -> 'BTCUSDT')"""
        symbol = symbol.upper().strip()
        
        # If it doesn't end with USDT, add it
        if not symbol.endswith('USDT'):
            symbol = symbol + 'USDT'
            
        return symbol
    
    def get_klines(self, symbol, timeframe='15m', limit=200):
        """Fetch OHLCV data for a symbol"""
        try:
            # Convert to ccxt format for API call
            ccxt_symbol = symbol[:-4] + '/' + symbol[-4:]  # BTCUSDT -> BTC/USDT
            
            ohlcv = self.exchange.fetch_ohlcv(ccxt_symbol, timeframe, limit=limit)
            if not ohlcv or len(ohlcv) < 50:
                return None
                
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            return df
        except Exception as e:
            print(f"Error fetching data for {symbol}: {str(e)}")
            return None
    
    def check_ema_cross_within_candles(self, df, max_candles=3):
        """
        Enhanced function to check if golden cross occurred within specified candles
        AND current price is above both EMAs
        
        Returns: (is_valid_signal, candles_since_cross, cross_details)
        """
        if df is None or len(df) < 20:  # Need at least 20 candles for reliable EMA
            return False, 0, None
        
        # Find all golden cross points
        golden_cross_indices = df[df['golden_cross'] == True].index.tolist()
        
        if not golden_cross_indices:
            return False, 0, None
        
        # Get the most recent golden cross
        latest_cross_idx = golden_cross_indices[-1]
        current_idx = df.index[-1]
        candles_since_cross = current_idx - latest_cross_idx
        
        # Check if cross is within the specified window
        if candles_since_cross > max_candles:
            return False, candles_since_cross, None
        
        # Verify current conditions
        current_row = df.iloc[-1]
        
        # All conditions must be met:
        # 1. EMA9 is above EMA15 (maintained after cross)
        # 2. Current price is above both EMAs
        # 3. Cross happened within max_candles
        if (current_row['ema9_above_ema15'] and 
            current_row['price_above_both_emas']):
            
            cross_details = {
                'cross_index': latest_cross_idx,
                'cross_time': df.iloc[latest_cross_idx]['timestamp'],
                'cross_price': df.iloc[latest_cross_idx]['close'],
                'ema9_at_cross': df.iloc[latest_cross_idx]['ema9'],
                'ema15_at_cross': df.iloc[latest_cross_idx]['ema15'],
                'price_change_since_cross': ((current_row['close'] - df.iloc[latest_cross_idx]['close']) / 
                                            df.iloc[latest_cross_idx]['close'] * 100)
            }
            
            return True, candles_since_cross, cross_details
        
        return False, candles_since_cross, None
    
    def analyze_symbols(self, symbols, timeframe='15m', limit=200, max_cross_candles=3, max_price=None):
        """
        Analyze specific symbols for EMA golden cross signals
        
        Parameters:
        symbols: list - List of symbols to analyze
        timeframe: str - Candlestick timeframe
        limit: int - Number of candles to fetch
        max_cross_candles: int - Maximum candles since golden cross
        max_price: float - Maximum price filter
        
        Returns:
        list - Analysis results for qualifying symbols
        """
        if not symbols:
            return []
            
        results = []
        
        print(f"Analyzing {len(symbols)} symbols...")
        
        for i, symbol in enumerate(symbols):
            try:
                # Normalize symbol format
                normalized_symbol = self.normalize_symbol(symbol)
                
                # Get price data
                df = self.get_klines(normalized_symbol, timeframe, limit)
                if df is None:
                    continue
                
                # Get current price
                current_price = df['close'].iloc[-1]
                
                # Apply price filter if specified
                if max_price is not None and current_price >= max_price:
                    continue
                
                # Calculate EMA indicators
                df = calculate_ema_cross(df)
                
                # Check for valid EMA cross signal
                is_valid, candles_since, cross_details = self.check_ema_cross_within_candles(
                    df, max_cross_candles
                )
                
                current_row = df.iloc[-1]
                
                # Only add to results if it meets ALL criteria
                if is_valid:
                    result = {
                        'symbol': normalized_symbol,
                        'current_price': current_price,
                        'ema9': current_row['ema9'],
                        'ema15': current_row['ema15'],
                        'candles_since_cross': candles_since,
                        'has_valid_signal': is_valid,
                        'cross_time': cross_details['cross_time'] if cross_details else None,
                        'cross_price': cross_details['cross_price'] if cross_details else None,
                        'price_change_pct': cross_details['price_change_since_cross'] if cross_details else None,
                        'current_time': current_row['timestamp'],
                        'ema_diff_pct': current_row['ema_diff_pct'],
                        'volume': current_row['volume']
                    }
                    
                    results.append(result)
                    print(f"✓ {normalized_symbol}: Valid signal found! (Cross {candles_since} candles ago)")
                
                # Rate limiting
                time.sleep(0.1)
                
            except Exception as e:
                print(f"Error analyzing {symbol}: {str(e)}")
                continue
        
        return results
    
    def display_results(self, results):
        """Display analysis results in a formatted way"""
        if not results:
            print("\nNo symbols found matching the criteria.")
            return []
        
        # Sort by candles since cross (most recent first)
        results.sort(key=lambda x: x['candles_since_cross'])
        
        print(f"\n{'='*80}")
        print(f"Found {len(results)} symbols with valid EMA cross signals:")
        print(f"{'='*80}\n")
        
        for r in results:
            print(f"Symbol: {r['symbol']}")
            print(f"  Current Price: ${r['current_price']:.8f}")
            print(f"  EMA9: ${r['ema9']:.8f} | EMA15: ${r['ema15']:.8f}")
            print(f"  Candles Since Cross: {r['candles_since_cross']}")
            print(f"  Cross Price: ${r['cross_price']:.8f}")
            print(f"  Price Change Since Cross: {r['price_change_pct']:.8f}%")
            print(f"  EMA Difference: {r['ema_diff_pct']:.8f}%")
            print(f"  Cross Time: {r['cross_time']}")
            print(f"  Volume: {r['volume']:.8f}")
            print("-" * 40)
        
        return results

def EMAs_9_15_Filter(
    symbols,
    timeframe='15m', 
    limit=200, 
    max_cross_candles=3, 
    max_price=None,
    show_details=True
):
    """
    Filter specific coins for EMA9 golden cross above EMA15 within specified candles
    with current price above both EMAs
    
    Parameters:
    symbols: list - List of symbols to analyze (e.g., ['BTC', 'ETH', 'ADA'])
    timeframe: str - Candlestick timeframe (default '15m')
    limit: int - Number of candles to fetch (default 200)
    max_cross_candles: int - Maximum candles since golden cross (default 3)
    max_price: float - Maximum price filter (default None for no filter)
    show_details: bool - Print detailed results (default True)
    
    Returns:
    pandas DataFrame - Filtered coins meeting ALL criteria
    """
    try:
        if not symbols:
            print("No symbols provided.")
            return pd.DataFrame()
        
        # Initialize analyzer
        analyzer = BinanceEMAAnalyzer()
        
        # Load markets
        print("Loading Binance markets...")
        analyzer.exchange.load_markets()
        
        # Analyze symbols for EMA conditions
        raw_results = analyzer.analyze_symbols(
            symbols=symbols,
            timeframe=timeframe,
            limit=limit,
            max_cross_candles=max_cross_candles,
            max_price=max_price
        )
        
        # Display results if requested
        if show_details:
            final_results = analyzer.display_results(raw_results)
        else:
            final_results = raw_results
        
        # Convert to DataFrame
        df_results = pd.DataFrame(final_results) if final_results else pd.DataFrame()
        
        if not df_results.empty:
            # Sort by candles since cross (most recent cross first)
            df_results = df_results.sort_values('candles_since_cross', ascending=True)
        
        return df_results
        
    except Exception as e:
        print(f"Error in EMAs_9_15_Filter: {str(e)}")
        return pd.DataFrame()