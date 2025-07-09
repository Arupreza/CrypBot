import pandas as pd
import numpy as np
import ccxt
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

class SmartMoneyScanner:
    def __init__(self, exchange_name='binance'):
        """
        Initialize the Smart Money Concept Scanner
        
        Args:
            exchange_name (str): Exchange name (default: 'binance')
        """
        self.exchange = getattr(ccxt, exchange_name)({
            'sandbox': False,  # Set to True for testnet
            'rateLimit': 1200,  # Milliseconds between requests
            'enableRateLimit': True,
        })
        
    def get_historical_data(self, symbol, timeframe='4h', limit=500):
        """
        Get historical OHLCV data for a symbol
        
        Args:
            symbol (str): Trading pair symbol (e.g., 'BTCUSDT')
            timeframe (str): Timeframe ('1m', '5m', '15m', '1h', '4h', '1d', etc.)
            limit (int): Number of candles to retrieve
            
        Returns:
            pd.DataFrame: OHLCV data
        """
        try:
            # Convert Binance format to CCXT format (BTCUSDT -> BTC/USDT)
            if '/' not in symbol:
                # Common quote currencies for conversion
                quote_currencies = ['USDT', 'BUSD', 'BTC', 'ETH', 'BNB', 'USDC']
                ccxt_symbol = symbol
                
                for quote in quote_currencies:
                    if symbol.endswith(quote):
                        base = symbol[:-len(quote)]
                        ccxt_symbol = f"{base}/{quote}"
                        break
            else:
                ccxt_symbol = symbol
            
            # Fetch OHLCV data using ccxt
            ohlcv = self.exchange.fetch_ohlcv(ccxt_symbol, timeframe, limit=limit)
            
            # Convert to DataFrame
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            # Convert timestamp to datetime
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            
            # Ensure numeric types
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            
            return df
            
        except Exception as e:
            print(f"Error fetching data for {symbol}: {e}")
            return None
    
    def identify_market_structure(self, df):
        """
        Identify market structure: uptrend, downtrend, or sideways
        
        Args:
            df (pd.DataFrame): OHLCV data
            
        Returns:
            str: Market structure ('uptrend', 'downtrend', 'sideways')
        """
        if len(df) < 50:
            return 'insufficient_data'
        
        # Calculate swing highs and lows
        highs = df['high'].rolling(window=10, center=True).max() == df['high']
        lows = df['low'].rolling(window=10, center=True).min() == df['low']
        
        recent_highs = df[highs]['high'].tail(3)
        recent_lows = df[lows]['low'].tail(3)
        
        if len(recent_highs) >= 2 and len(recent_lows) >= 2:
            # Check for higher highs and higher lows (uptrend)
            hh = recent_highs.iloc[-1] > recent_highs.iloc[-2]
            hl = recent_lows.iloc[-1] > recent_lows.iloc[-2]
            
            # Check for lower highs and lower lows (downtrend)
            lh = recent_highs.iloc[-1] < recent_highs.iloc[-2]
            ll = recent_lows.iloc[-1] < recent_lows.iloc[-2]
            
            if hh and hl:
                return 'uptrend'
            elif lh and ll:
                return 'downtrend'
            else:
                return 'sideways'
        
        return 'sideways'
    
    def identify_order_blocks(self, df, lookback=20):
        """
        Identify order blocks (institutional demand/supply zones)
        
        Args:
            df (pd.DataFrame): OHLCV data
            lookback (int): Lookback period for identifying order blocks
            
        Returns:
            dict: Order block levels and types
        """
        order_blocks = {'bullish': [], 'bearish': []}
        
        for i in range(lookback, len(df)):
            current_candle = df.iloc[i]
            
            # Look for strong bullish candles with high volume
            if (current_candle['close'] > current_candle['open'] and
                current_candle['volume'] > df['volume'].rolling(20).mean().iloc[i] * 1.5 and
                (current_candle['close'] - current_candle['open']) / current_candle['open'] > 0.02):
                
                order_blocks['bullish'].append({
                    'timestamp': df.index[i],
                    'high': current_candle['high'],
                    'low': current_candle['low'],
                    'strength': current_candle['volume'] / df['volume'].rolling(20).mean().iloc[i]
                })
            
            # Look for strong bearish candles with high volume
            elif (current_candle['close'] < current_candle['open'] and
                  current_candle['volume'] > df['volume'].rolling(20).mean().iloc[i] * 1.5 and
                  (current_candle['open'] - current_candle['close']) / current_candle['open'] > 0.02):
                
                order_blocks['bearish'].append({
                    'timestamp': df.index[i],
                    'high': current_candle['high'],
                    'low': current_candle['low'],
                    'strength': current_candle['volume'] / df['volume'].rolling(20).mean().iloc[i]
                })
        
        return order_blocks
    
    def identify_fair_value_gaps(self, df):
        """
        Identify Fair Value Gaps (FVG) - gaps in price action
        
        Args:
            df (pd.DataFrame): OHLCV data
            
        Returns:
            list: Fair value gaps
        """
        fvgs = []
        
        for i in range(2, len(df)):
            prev_candle = df.iloc[i-2]
            current_candle = df.iloc[i-1]
            next_candle = df.iloc[i]
            
            # Bullish FVG: prev_high < next_low
            if prev_candle['high'] < next_candle['low']:
                fvgs.append({
                    'type': 'bullish_fvg',
                    'timestamp': df.index[i],
                    'upper': next_candle['low'],
                    'lower': prev_candle['high'],
                    'size': next_candle['low'] - prev_candle['high']
                })
            
            # Bearish FVG: prev_low > next_high
            elif prev_candle['low'] > next_candle['high']:
                fvgs.append({
                    'type': 'bearish_fvg',
                    'timestamp': df.index[i],
                    'upper': prev_candle['low'],
                    'lower': next_candle['high'],
                    'size': prev_candle['low'] - next_candle['high']
                })
        
        return fvgs
    
    def identify_liquidity_grabs(self, df, lookback=20):
        """
        Identify liquidity grabs (false breakouts)
        
        Args:
            df (pd.DataFrame): OHLCV data
            lookback (int): Lookback period
            
        Returns:
            list: Liquidity grab signals
        """
        liquidity_grabs = []
        
        # Calculate support and resistance levels
        highs = df['high'].rolling(window=lookback).max()
        lows = df['low'].rolling(window=lookback).min()
        
        for i in range(lookback, len(df)):
            current = df.iloc[i]
            prev_high = highs.iloc[i-1]
            prev_low = lows.iloc[i-1]
            
            # Bearish liquidity grab (false breakout above resistance)
            if (current['high'] > prev_high and 
                current['close'] < prev_high and
                current['volume'] > df['volume'].rolling(20).mean().iloc[i]):
                
                liquidity_grabs.append({
                    'type': 'bearish_liquidity_grab',
                    'timestamp': df.index[i],
                    'level': prev_high,
                    'confidence': min(current['volume'] / df['volume'].rolling(20).mean().iloc[i], 3.0)
                })
            
            # Bullish liquidity grab (false breakdown below support)
            elif (current['low'] < prev_low and 
                  current['close'] > prev_low and
                  current['volume'] > df['volume'].rolling(20).mean().iloc[i]):
                
                liquidity_grabs.append({
                    'type': 'bullish_liquidity_grab',
                    'timestamp': df.index[i],
                    'level': prev_low,
                    'confidence': min(current['volume'] / df['volume'].rolling(20).mean().iloc[i], 3.0)
                })
        
        return liquidity_grabs
    
    def calculate_break_of_structure(self, df):
        """
        Calculate Break of Structure (BOS) and Change of Character (CHoCH)
        
        Args:
            df (pd.DataFrame): OHLCV data
            
        Returns:
            dict: BOS and CHoCH signals
        """
        structure_breaks = {'bos': [], 'choch': []}
        
        # Find swing highs and lows
        swing_high_idx = []
        swing_low_idx = []
        
        for i in range(5, len(df)-5):
            if df['high'].iloc[i] == df['high'].iloc[i-5:i+6].max():
                swing_high_idx.append(i)
            if df['low'].iloc[i] == df['low'].iloc[i-5:i+6].min():
                swing_low_idx.append(i)
        
        # Analyze structure breaks
        for i in range(len(df)):
            current_price = df['close'].iloc[i]
            
            # Check for break of structure above previous highs
            recent_highs = [df['high'].iloc[idx] for idx in swing_high_idx if idx < i]
            if recent_highs and current_price > max(recent_highs[-2:]):
                structure_breaks['bos'].append({
                    'type': 'bullish_bos',
                    'timestamp': df.index[i],
                    'level': max(recent_highs[-2:]),
                    'strength': (current_price - max(recent_highs[-2:])) / max(recent_highs[-2:])
                })
            
            # Check for break of structure below previous lows
            recent_lows = [df['low'].iloc[idx] for idx in swing_low_idx if idx < i]
            if recent_lows and current_price < min(recent_lows[-2:]):
                structure_breaks['bos'].append({
                    'type': 'bearish_bos',
                    'timestamp': df.index[i],
                    'level': min(recent_lows[-2:]),
                    'strength': (min(recent_lows[-2:]) - current_price) / min(recent_lows[-2:])
                })
        
        return structure_breaks
    
    def calculate_smc_score(self, symbol_data):
        """
        Calculate overall Smart Money Concept score
        
        Args:
            symbol_data (dict): All SMC analysis data for a symbol
            
        Returns:
            dict: SMC scores and signals
        """
        scores = {
            'bullish_score': 0,
            'bearish_score': 0,
            'overall_bias': 'neutral',
            'confidence': 0,
            'signals': []
        }
        
        # Market structure weighting (40%)
        if symbol_data['market_structure'] == 'uptrend':
            scores['bullish_score'] += 40
        elif symbol_data['market_structure'] == 'downtrend':
            scores['bearish_score'] += 40
        
        # Order blocks weighting (25%)
        recent_bullish_obs = [ob for ob in symbol_data['order_blocks']['bullish'][-3:]]
        recent_bearish_obs = [ob for ob in symbol_data['order_blocks']['bearish'][-3:]]
        
        if recent_bullish_obs:
            avg_strength = np.mean([ob['strength'] for ob in recent_bullish_obs])
            scores['bullish_score'] += min(25, avg_strength * 10)
        
        if recent_bearish_obs:
            avg_strength = np.mean([ob['strength'] for ob in recent_bearish_obs])
            scores['bearish_score'] += min(25, avg_strength * 10)
        
        # Liquidity grabs weighting (20%)
        recent_liq_grabs = symbol_data['liquidity_grabs'][-5:]
        for grab in recent_liq_grabs:
            if grab['type'] == 'bullish_liquidity_grab':
                scores['bullish_score'] += min(20, grab['confidence'] * 5)
            else:
                scores['bearish_score'] += min(20, grab['confidence'] * 5)
        
        # Structure breaks weighting (15%)
        recent_bos = symbol_data['structure_breaks']['bos'][-3:]
        for bos in recent_bos:
            if bos['type'] == 'bullish_bos':
                scores['bullish_score'] += min(15, bos['strength'] * 100)
            else:
                scores['bearish_score'] += min(15, bos['strength'] * 100)
        
        # Determine overall bias
        total_score = scores['bullish_score'] + scores['bearish_score']
        if total_score > 0:
            scores['confidence'] = min(100, total_score)
            
            if scores['bullish_score'] > scores['bearish_score'] * 1.2:
                scores['overall_bias'] = 'bullish'
            elif scores['bearish_score'] > scores['bullish_score'] * 1.2:
                scores['overall_bias'] = 'bearish'
            else:
                scores['overall_bias'] = 'neutral'
        
        # Generate specific signals
        if scores['overall_bias'] == 'bullish' and scores['confidence'] > 60:
            scores['signals'].append('STRONG_BUY')
        elif scores['overall_bias'] == 'bullish' and scores['confidence'] > 40:
            scores['signals'].append('BUY')
        elif scores['overall_bias'] == 'bearish' and scores['confidence'] > 60:
            scores['signals'].append('STRONG_SELL')
        elif scores['overall_bias'] == 'bearish' and scores['confidence'] > 40:
            scores['signals'].append('SELL')
        else:
            scores['signals'].append('HOLD')
        
        return scores
    
    def scan_coins(self, coin_list, timeframe='4h'):
        """
        Scan multiple coins for Smart Money Concept signals
        
        Args:
            coin_list (list): List of trading pairs to scan (e.g., ['BTCUSDT', 'ETHUSDT'])
            timeframe (str): Timeframe for analysis
            
        Returns:
            pd.DataFrame: Results dataframe with SMC analysis
        """
        results = []
        
        for symbol in coin_list:
            try:
                print(f"Scanning {symbol}...")
                
                # Get historical data
                df = self.get_historical_data(symbol, timeframe)
                if df is None or len(df) < 100:
                    continue
                
                # Perform SMC analysis
                market_structure = self.identify_market_structure(df)
                order_blocks = self.identify_order_blocks(df)
                fvgs = self.identify_fair_value_gaps(df)
                liquidity_grabs = self.identify_liquidity_grabs(df)
                structure_breaks = self.calculate_break_of_structure(df)
                
                # Compile symbol data
                symbol_data = {
                    'market_structure': market_structure,
                    'order_blocks': order_blocks,
                    'fvgs': fvgs,
                    'liquidity_grabs': liquidity_grabs,
                    'structure_breaks': structure_breaks
                }
                
                # Calculate SMC score
                smc_scores = self.calculate_smc_score(symbol_data)
                
                # Get current price
                current_price = df['close'].iloc[-1]
                
                # Compile results
                result = {
                    'symbol': symbol,
                    'current_price': current_price,
                    'market_structure': market_structure,
                    'overall_bias': smc_scores['overall_bias'],
                    'confidence': round(smc_scores['confidence'], 2),
                    'bullish_score': round(smc_scores['bullish_score'], 2),
                    'bearish_score': round(smc_scores['bearish_score'], 2),
                    'signals': ', '.join(smc_scores['signals']),
                    'bullish_order_blocks': len(order_blocks['bullish']),
                    'bearish_order_blocks': len(order_blocks['bearish']),
                    'recent_fvgs': len([fvg for fvg in fvgs[-10:]]),
                    'liquidity_grabs': len(liquidity_grabs[-5:]),
                    'structure_breaks': len(structure_breaks['bos'][-3:]),
                    'volume_trend': 'increasing' if df['volume'].tail(5).mean() > df['volume'].tail(20).mean() else 'decreasing',
                    'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                
                results.append(result)
                
            except Exception as e:
                print(f"Error scanning {symbol}: {e}")
                continue
        
        # Create DataFrame and sort by confidence
        results_df = pd.DataFrame(results)
        if not results_df.empty:
            results_df = results_df.sort_values('confidence', ascending=False)
        
        return results_df
    
    def get_top_signals(self, results_df, signal_type='all', min_confidence=50):
        """
        Filter and return top signals based on criteria
        
        Args:
            results_df (pd.DataFrame): Results from scan_coins
            signal_type (str): 'bullish', 'bearish', or 'all'
            min_confidence (float): Minimum confidence level
            
        Returns:
            pd.DataFrame: Filtered results
        """
        if results_df.empty:
            return results_df
        
        # Filter by confidence
        filtered_df = results_df[results_df['confidence'] >= min_confidence].copy()
        
        # Filter by signal type
        if signal_type == 'bullish':
            filtered_df = filtered_df[filtered_df['overall_bias'] == 'bullish']
        elif signal_type == 'bearish':
            filtered_df = filtered_df[filtered_df['overall_bias'] == 'bearish']
        
        return filtered_df

# Example usage
def main():
    # Initialize scanner (no API keys needed for public data!)
    scanner = SmartMoneyScanner(exchange_name='binance')
    
    # Define coins to scan (Binance format: BTCUSDT)
    coins_to_scan = [
        'BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'ADAUSDT', 'DOTUSDT',
        'LINKUSDT', 'LTCUSDT', 'BCHUSDT', 'XLMUSDT', 'EOSUSDT',
        'TRXUSDT', 'ETCUSDT', 'XMRUSDT', 'DASHUSDT', 'NEOUSDT'
    ]
    
    # Scan coins
    print("Starting Smart Money Concept scan...")
    results = scanner.scan_coins(coins_to_scan, timeframe='4h')
    
    # Display results
    if not results.empty:
        print("\n=== SMART MONEY CONCEPT SCAN RESULTS ===")
        print(results[['symbol', 'overall_bias', 'confidence', 'signals', 'market_structure']].to_string(index=False))
        
        # Get top bullish signals
        bullish_signals = scanner.get_top_signals(results, 'bullish', min_confidence=60)
        if not bullish_signals.empty:
            print("\n=== TOP BULLISH SIGNALS ===")
            print(bullish_signals[['symbol', 'confidence', 'signals', 'current_price']].to_string(index=False))
        
        # Get top bearish signals
        bearish_signals = scanner.get_top_signals(results, 'bearish', min_confidence=60)
        if not bearish_signals.empty:
            print("\n=== TOP BEARISH SIGNALS ===")
            print(bearish_signals[['symbol', 'confidence', 'signals', 'current_price']].to_string(index=False))
    else:
        print("No results found.")

# Additional utility functions
def get_available_symbols(exchange_name='binance', quote_currency='USDT'):
    """Get all available trading symbols from the exchange in Binance format"""
    try:
        exchange = getattr(ccxt, exchange_name)()
        markets = exchange.load_markets()
        
        # Convert CCXT format to Binance format and filter by quote currency
        binance_symbols = []
        for symbol in markets.keys():
            if f'/{quote_currency}' in symbol:
                binance_format = symbol.replace('/', '')
                binance_symbols.append(binance_format)
        
        return sorted(binance_symbols)
    except Exception as e:
        print(f"Error getting symbols: {e}")
        return []

def scan_top_volume_pairs(scanner, quote_currency='USDT', top_n=20, timeframe='4h'):
    """Scan top volume pairs for a specific quote currency"""
    try:
        # Get all symbols in Binance format
        all_symbols = get_available_symbols('binance', quote_currency)
        
        if not all_symbols:
            print("No symbols found")
            return pd.DataFrame()
        
        # Convert to CCXT format for getting ticker data
        ccxt_symbols = [f"{symbol[:-len(quote_currency)]}/{quote_currency}" for symbol in all_symbols[:50]]
        
        # Get 24h ticker data to sort by volume
        tickers = scanner.exchange.fetch_tickers(ccxt_symbols)
        
        # Sort by volume and get top N, convert back to Binance format
        sorted_pairs = sorted(tickers.items(), key=lambda x: x[1]['quoteVolume'] or 0, reverse=True)
        top_pairs = [pair[0].replace('/', '') for pair in sorted_pairs[:top_n]]
        
        print(f"Scanning top {top_n} volume pairs...")
        return scanner.scan_coins(top_pairs, timeframe)
        
    except Exception as e:
        print(f"Error getting top volume pairs: {e}")
        return pd.DataFrame()

if __name__ == "__main__":
    main()