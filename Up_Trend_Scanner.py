import ccxt
import pandas as pd
import numpy as np
from datetime import datetime
import time
import warnings
warnings.filterwarnings('ignore')

class BinanceUptrendScanner:
    def __init__(self, timeframe='5m', exchange='binance'):
        """
        Initialize the uptrend scanner using CCXT
        
        Parameters:
        - timeframe: Candle timeframe for analysis ('1m', '5m', '15m', '30m', '1h', '4h', '1d')
        - exchange: Exchange name (default: 'binance')
        """
        self.exchange_name = exchange
        self.exchange = getattr(ccxt, exchange)({
            'enableRateLimit': True,
            'options': {
                'defaultType': 'spot',
            }
        })
        self.timeframe = timeframe
        
    def load_markets(self):
        """Load market data"""
        if not self.exchange.markets:
            self.exchange.load_markets()
    
    def get_historical_data(self, symbol, limit=100):
        """Fetch historical OHLCV data for a symbol"""
        try:
            # Fetch OHLCV data
            ohlcv = self.exchange.fetch_ohlcv(symbol, self.timeframe, limit=limit)
            
            # Convert to DataFrame
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            
            return df
            
        except Exception as e:
            print(f"Error fetching data for {symbol}: {e}")
            return None
    
    def calculate_indicators(self, df):
        """Calculate technical indicators for trend detection"""
        if df is None or len(df) < 20:
            return None
            
        # Simple Moving Averages
        df['SMA_10'] = df['close'].rolling(window=10).mean()
        df['SMA_20'] = df['close'].rolling(window=20).mean()
        df['SMA_50'] = df['close'].rolling(window=50).mean() if len(df) >= 50 else np.nan
        
        # Exponential Moving Averages
        df['EMA_10'] = df['close'].ewm(span=10, adjust=False).mean()
        df['EMA_20'] = df['close'].ewm(span=20, adjust=False).mean()
        
        # RSI
        df['RSI'] = self.calculate_rsi(df['close'])
        
        # MACD
        df['MACD'], df['MACD_signal'], df['MACD_diff'] = self.calculate_macd(df['close'])
        
        # Volume indicators
        df['volume_sma'] = df['volume'].rolling(window=20).mean()
        df['volume_ratio'] = df['volume'] / df['volume_sma']
        
        # Bollinger Bands
        df['BB_middle'] = df['SMA_20']
        bb_std = df['close'].rolling(window=20).std()
        df['BB_upper'] = df['BB_middle'] + (bb_std * 2)
        df['BB_lower'] = df['BB_middle'] - (bb_std * 2)
        df['BB_width'] = df['BB_upper'] - df['BB_lower']
        
        return df
    
    def calculate_rsi(self, prices, period=14):
        """Calculate Relative Strength Index"""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    def calculate_macd(self, prices, fast=12, slow=26, signal=9):
        """Calculate MACD indicator"""
        ema_fast = prices.ewm(span=fast, adjust=False).mean()
        ema_slow = prices.ewm(span=slow, adjust=False).mean()
        macd = ema_fast - ema_slow
        macd_signal = macd.ewm(span=signal, adjust=False).mean()
        macd_diff = macd - macd_signal
        return macd, macd_signal, macd_diff
    
    def is_uptrending(self, df):
        """
        Determine if a coin is in an uptrend based on multiple criteria
        """
        if df is None or len(df) < 20:
            return False, {}
        
        latest = df.iloc[-1]
        
        # Calculate criteria
        criteria = {
            'price_above_sma20': latest['close'] > latest['SMA_20'],
            'sma10_above_sma20': latest['SMA_10'] > latest['SMA_20'],
            'ema_bullish': latest['EMA_10'] > latest['EMA_20'],
            'rsi_healthy': 40 < latest['RSI'] < 70,
            'macd_bullish': latest['MACD'] > latest['MACD_signal'],
            'volume_increasing': latest['volume_ratio'] > 1.2,
            'higher_lows': df['low'].iloc[-5:].min() > df['low'].iloc[-10:-5].min(),
            'above_bb_middle': latest['close'] > latest['BB_middle'],
            'momentum_strong': df['close'].iloc[-3:].mean() > df['close'].iloc[-6:-3].mean()
        }
        
        # Price momentum
        price_change_5 = (latest['close'] - df['close'].iloc[-5]) / df['close'].iloc[-5] * 100
        price_change_10 = (latest['close'] - df['close'].iloc[-10]) / df['close'].iloc[-10] * 100
        
        criteria['momentum_5_positive'] = price_change_5 > 0
        criteria['momentum_10_positive'] = price_change_10 > 0
        
        # Count how many criteria are met
        score = sum(criteria.values())
        
        # Consider it uptrending if at least 7 out of 11 criteria are met
        is_uptrend = score >= 7
        
        # Get 24h volume in USDT
        volume_24h = df['volume'].iloc[-24:].sum() if len(df) >= 24 else df['volume'].sum()
        volume_24h_usdt = volume_24h * latest['close']
        
        return is_uptrend, {
            'score': score,
            'price_change_5': round(price_change_5, 2),
            'price_change_10': round(price_change_10, 2),
            'current_price': latest['close'],
            'rsi': round(latest['RSI'], 2),
            'volume_ratio': round(latest['volume_ratio'], 2),
            'volume_24h_usdt': round(volume_24h_usdt, 2),
            'sma_20': round(latest['SMA_20'], 8),
            'ema_10': round(latest['EMA_10'], 8),
            'ema_20': round(latest['EMA_20'], 8),
            'macd': round(latest['MACD'], 8),
            'macd_signal': round(latest['MACD_signal'], 8),
            'bb_upper': round(latest['BB_upper'], 8),
            'bb_lower': round(latest['BB_lower'], 8),
            **{f'criteria_{k}': v for k, v in criteria.items()}
        }
    
    def scan_symbol(self, symbol):
        """Scan a single symbol for uptrend"""
        df = self.get_historical_data(symbol)
        if df is None:
            return None
            
        df = self.calculate_indicators(df)
        is_uptrend, analysis = self.is_uptrending(df)
        
        return {
            'symbol': symbol,
            'is_uptrending': is_uptrend,
            **analysis
        }
    
    def scan_symbols(self, symbols):
        """
        Scan a list of symbols and return DataFrame with all results
        
        Parameters:
        - symbols: List of trading pairs (e.g., ['BTC/USDT', 'ETH/USDT'] or ['BTCUSDT', 'ETHUSDT'])
        
        Returns:
        - DataFrame with all coins (uptrending and non-uptrending)
        """
        try:
            # Load markets if not loaded
            self.load_markets()
            
            # Convert symbol format if needed
            formatted_symbols = []
            for symbol in symbols:
                # Check if symbol needs formatting (no slash)
                if '/' not in symbol and symbol.endswith('USDT'):
                    # Convert BTCUSDT to BTC/USDT
                    base = symbol[:-4]  # Remove 'USDT'
                    formatted_symbol = f"{base}/USDT"
                    formatted_symbols.append(formatted_symbol)
                else:
                    formatted_symbols.append(symbol)
            
            print(f"Scanning {len(formatted_symbols)} symbols...")
            
            # Scan all symbols
            results = []
            for i, symbol in enumerate(formatted_symbols):
                if i % 10 == 0 and i > 0:
                    print(f"Progress: {i}/{len(formatted_symbols)}")
                
                result = self.scan_symbol(symbol)
                if result:
                    # Store original symbol format in result
                    result['original_symbol'] = symbols[i]
                    results.append(result)
                
                # Rate limiting
                if i % 3 == 0:
                    time.sleep(0.1)
            
            # Create DataFrame
            if results:
                df = pd.DataFrame(results)
                
                # Sort by score (descending)
                df = df.sort_values('score', ascending=False)
                
                # Add scan timestamp
                df['scan_time'] = datetime.now()
                
                # Reorder columns
                column_order = [
                    'symbol', 'original_symbol', 'is_uptrending', 'score', 'current_price', 'price_change_5', 
                    'price_change_10', 'rsi', 'volume_ratio', 'volume_24h_usdt', 'sma_20', 
                    'ema_10', 'ema_20', 'macd', 'macd_signal', 'bb_upper', 'bb_lower', 'scan_time'
                ]
                
                # Add criteria columns
                criteria_cols = [col for col in df.columns if col.startswith('criteria_')]
                column_order.extend(criteria_cols)
                
                # Reorder
                available_cols = [col for col in column_order if col in df.columns]
                df = df[available_cols]
                
                return df
            else:
                # Return empty DataFrame with correct structure
                return pd.DataFrame(columns=[
                    'symbol', 'is_uptrending', 'score', 'current_price', 'price_change_5', 
                    'price_change_10', 'rsi', 'volume_ratio', 'scan_time'
                ])
            
        except Exception as e:
            print(f"Error in scan: {e}")
            import traceback
            traceback.print_exc()
            return pd.DataFrame()


# Simple function to scan your coin list
def up_trend_scanner(coin_list, timeframe='5m', exchange='binance', uptrend_only=True):
    """
    Scan a list of coins and return DataFrame
    
    Parameters:
    - coin_list: List of symbols (e.g., ['BTC/USDT', 'ETH/USDT', 'BNB/USDT'])
    - timeframe: Candle timeframe ('1m', '5m', '15m', '30m', '1h', '4h', '1d')
    - exchange: Exchange name (default: 'binance')
    - uptrend_only: If True, return only uptrending coins; if False, return all
    
    Returns:
    - DataFrame with coin analysis
    """
    scanner = BinanceUptrendScanner(timeframe=timeframe, exchange=exchange)
    df = scanner.scan_symbols(coin_list)
    
    if uptrend_only and not df.empty:
        # Filter only uptrending coins
        df = df[df['is_uptrending'] == True].copy()
    
    return df


# Helper function to create symbol list from base currencies
def create_symbol_list(base_currencies, quote_currency='USDT'):
    """
    Helper to create symbol list from base currencies
    
    Example:
    create_symbol_list(['BTC', 'ETH', 'BNB']) -> ['BTC/USDT', 'ETH/USDT', 'BNB/USDT']
    """
    return [f"{base}/{quote_currency}" for base in base_currencies]


# Helper function to convert Binance format to CCXT format
def convert_binance_symbols(binance_symbols):
    """
    Convert Binance format symbols to CCXT format
    
    Example:
    convert_binance_symbols(['BTCUSDT', 'ETHUSDT']) -> ['BTC/USDT', 'ETH/USDT']
    """
    ccxt_symbols = []
    for symbol in binance_symbols:
        if symbol.endswith('USDT'):
            base = symbol[:-4]
            ccxt_symbols.append(f"{base}/USDT")
        elif symbol.endswith('BTC'):
            base = symbol[:-3]
            ccxt_symbols.append(f"{base}/BTC")
        elif symbol.endswith('ETH'):
            base = symbol[:-3]
            ccxt_symbols.append(f"{base}/ETH")
        else:
            # If format is unknown, keep as is
            ccxt_symbols.append(symbol)
    return ccxt_symbols