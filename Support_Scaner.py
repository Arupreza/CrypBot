import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import time
from typing import List, Dict, Tuple

class BinanceSupportScanner:
    def __init__(self):
        self.base_url = "https://api.binance.com/api/v3"
        
    def get_klines(self, symbol: str, interval: str = "1h", limit: int = 200) -> pd.DataFrame:
        """Get historical kline data from Binance"""
        try:
            url = f"{self.base_url}/klines"
            params = {
                'symbol': symbol,
                'interval': interval,
                'limit': limit
            }
            
            response = requests.get(url, params=params)
            response.raise_for_status()
            
            data = response.json()
            
            # Convert to DataFrame
            df = pd.DataFrame(data, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_volume', 'trades', 'buy_base_volume',
                'buy_quote_volume', 'ignore'
            ])
            
            # Convert to appropriate data types
            numeric_columns = ['open', 'high', 'low', 'close', 'volume']
            for col in numeric_columns:
                df[col] = pd.to_numeric(df[col])
            
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            
            return df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
            
        except Exception as e:
            print(f"Error fetching data for {symbol}: {e}")
            return None
    
    def find_support_resistance_levels(self, df: pd.DataFrame, window: int = 20) -> Tuple[List[float], List[float]]:
        """Find support and resistance levels using pivot points"""
        highs = df['high'].values
        lows = df['low'].values
        
        support_levels = []
        resistance_levels = []
        
        # Find local minima (support) and maxima (resistance)
        for i in range(window, len(df) - window):
            # Support level (local minimum)
            if lows[i] == min(lows[i-window:i+window+1]):
                support_levels.append(lows[i])
            
            # Resistance level (local maximum)
            if highs[i] == max(highs[i-window:i+window+1]):
                resistance_levels.append(highs[i])
        
        # Remove duplicates and sort
        support_levels = sorted(list(set([round(level, 8) for level in support_levels])))
        resistance_levels = sorted(list(set([round(level, 8) for level in resistance_levels])))
        
        return support_levels, resistance_levels
    
    def calculate_level_strength(self, df: pd.DataFrame, level: float, tolerance: float = 0.002) -> int:
        """Calculate how many times price has touched a level (strength indicator)"""
        touches = 0
        for _, row in df.iterrows():
            if abs(row['low'] - level) / level <= tolerance or abs(row['high'] - level) / level <= tolerance:
                touches += 1
        return touches
    
    def is_near_support_level(self, current_price: float, support_levels: List[float], 
                             tolerance: float = 0.01) -> Tuple[bool, float]:
        """Check if current price is near a support level"""
        for level in support_levels:
            if abs(current_price - level) / level <= tolerance and current_price >= level * (1 - tolerance):
                return True, level
        return False, 0
    
    def is_near_resistance_level(self, current_price: float, resistance_levels: List[float], 
                                tolerance: float = 0.01) -> Tuple[bool, float]:
        """Check if current price is near a resistance level"""
        for level in resistance_levels:
            if abs(current_price - level) / level <= tolerance and current_price <= level * (1 + tolerance):
                return True, level
        return False, 0
    
    def calculate_rsi(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Calculate RSI indicator"""
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    def scan_coin(self, symbol: str) -> Dict:
        """Scan a single coin for support/resistance levels"""
        print(f"Scanning {symbol}...")
        
        # Get price data
        df = self.get_klines(symbol)
        if df is None or df.empty:
            return {'symbol': symbol, 'error': 'Failed to fetch data'}
        
        # Get current price
        current_price = df['close'].iloc[-1]
        
        # Find support and resistance levels
        support_levels, resistance_levels = self.find_support_resistance_levels(df)
        
        # Calculate RSI
        rsi = self.calculate_rsi(df)
        current_rsi = rsi.iloc[-1] if not rsi.empty else 50
        
        # Check if near support level
        near_support, support_level = self.is_near_support_level(current_price, support_levels)
        
        # Check if near resistance level  
        near_resistance, resistance_level = self.is_near_resistance_level(current_price, resistance_levels)
        
        # Calculate level strength
        support_strength = 0
        resistance_strength = 0
        
        if near_support:
            support_strength = self.calculate_level_strength(df, support_level)
        
        if near_resistance:
            resistance_strength = self.calculate_level_strength(df, resistance_level)
        
        # Determine signal
        signal = "NEUTRAL"
        if near_support and current_rsi < 40:
            signal = "STRONG_SUPPORT"
        elif near_support and current_rsi < 50:
            signal = "SUPPORT"
        elif near_resistance and current_rsi > 60:
            signal = "RESISTANCE"
        elif near_resistance and current_rsi > 70:
            signal = "STRONG_RESISTANCE"
        
        return {
            'symbol': symbol,
            'current_price': current_price,
            'signal': signal,
            'rsi': round(current_rsi, 2),
            'near_support': near_support,
            'support_level': support_level if near_support else None,
            'support_strength': support_strength,
            'near_resistance': near_resistance,
            'resistance_level': resistance_level if near_resistance else None,
            'resistance_strength': resistance_strength,
            'total_support_levels': len(support_levels),
            'total_resistance_levels': len(resistance_levels)
        }
    
    def scan_multiple_coins(self, coin_list: List[str], delay: float = 0.1) -> List[Dict]:
        """Scan multiple coins with rate limiting"""
        results = []
        
        for symbol in coin_list:
            try:
                result = self.scan_coin(symbol)
                results.append(result)
                
                # Rate limiting to avoid API limits
                time.sleep(delay)
                
            except Exception as e:
                print(f"Error scanning {symbol}: {e}")
                results.append({'symbol': symbol, 'error': str(e)})
        
        return results
    
    def filter_results(self, results: List[Dict], filter_type: str = "support") -> List[Dict]:
        """Filter results based on criteria"""
        filtered = []
        
        for result in results:
            if 'error' in result:
                continue
                
            if filter_type == "support":
                if result['signal'] in ["SUPPORT", "STRONG_SUPPORT"]:
                    filtered.append(result)
            elif filter_type == "resistance":
                if result['signal'] in ["RESISTANCE", "STRONG_RESISTANCE"]:
                    filtered.append(result)
            elif filter_type == "strong_support":
                if result['signal'] == "STRONG_SUPPORT":
                    filtered.append(result)
            elif filter_type == "all_signals":
                if result['signal'] != "NEUTRAL":
                    filtered.append(result)
        
        return filtered
    
    def display_results(self, results: List[Dict]):
        """Display results in a formatted table"""
        if not results:
            print("No coins found matching the criteria.")
            return
        
        print(f"\n{'Symbol':<12} {'Price':<12} {'Signal':<18} {'RSI':<6} {'Level':<12} {'Strength':<8}")
        print("-" * 80)
        
        for result in results:
            if 'error' in result:
                print(f"{result['symbol']:<12} {'ERROR':<12} {result['error']:<18}")
                continue
            
            level = ""
            if result['near_support']:
                level = f"{result['support_level']:.8f}"
            elif result['near_resistance']:
                level = f"{result['resistance_level']:.8f}"
            
            strength = ""
            if result['near_support']:
                strength = str(result['support_strength'])
            elif result['near_resistance']:
                strength = str(result['resistance_strength'])
            
            print(f"{result['symbol']:<12} {result['current_price']:<12.8f} {result['signal']:<18} "
                f"{result['rsi']:<6.2f} {level:<12} {strength:<8}")
            
            
# scanner = BinanceSupportScanner()
# results_df = scanner.scan_multiple_coins(coins)