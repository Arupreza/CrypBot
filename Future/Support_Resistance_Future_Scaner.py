import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import time
from typing import List, Dict, Tuple

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
    
    def get_exchange_info(self) -> Dict:
        """Get exchange information to validate symbols"""
        try:
            url = f"{self.base_url}/fapi/v1/exchangeInfo"
            response = requests.get(url)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Error fetching exchange info: {e}")
            return {}
    
    def get_klines(self, symbol, interval='1h', limit=200):
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
    
    def get_current_price(self, symbol):
        """Get current price"""
        try:
            symbol = self._format_symbol(symbol)
            url = f"{self.base_url}/fapi/v1/ticker/price"
            params = {'symbol': symbol.upper()}
            response = requests.get(url, params=params)
            response.raise_for_status()
            
            data = response.json()
            return float(data['price'])
        except requests.RequestException as e:
            print(f"Error fetching current price for {symbol}: {e}")
            return 0.0
    
    def get_24hr_stats(self, symbol):
        """Get 24hr ticker statistics"""
        try:
            symbol = self._format_symbol(symbol)
            url = f"{self.base_url}/fapi/v1/ticker/24hr"
            params = {'symbol': symbol.upper()}
            response = requests.get(url, params=params)
            response.raise_for_status()
            
            return response.json()
        except requests.RequestException as e:
            print(f"Error fetching 24hr stats for {symbol}: {e}")
            return {}
    
    def get_all_24hr_stats(self):
        """Get 24hr stats for all symbols"""
        try:
            url = f"{self.base_url}/fapi/v1/ticker/24hr"
            response = requests.get(url)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            print(f"Error fetching all 24hr stats: {e}")
            return []

class Binance_Support_Resistance_Perpetual_Scanner:
    def __init__(self):
        self.fetcher = BinancePerpetualFetcher()
        
    def get_active_symbols(self) -> List[str]:
        """Get all active USDT perpetual futures symbols"""
        exchange_info = self.fetcher.get_exchange_info()
        symbols = []
        
        if 'symbols' in exchange_info:
            for symbol_info in exchange_info['symbols']:
                if (symbol_info['status'] == 'TRADING' and 
                    symbol_info['contractType'] == 'PERPETUAL' and
                    symbol_info['symbol'].endswith('USDT')):
                    symbols.append(symbol_info['symbol'])
        
        return sorted(symbols)
    
    def get_klines(self, symbol: str, interval: str = "1h", limit: int = 200) -> pd.DataFrame:
        """Get historical kline data using BinancePerpetualFetcher"""
        return self.fetcher.get_klines(symbol, interval, limit)
    
    def get_current_price(self, symbol: str) -> float:
        """Get current price using BinancePerpetualFetcher"""
        return self.fetcher.get_current_price(symbol)
    
    def get_24hr_stats(self, symbol: str) -> Dict:
        """Get 24hr ticker statistics using BinancePerpetualFetcher"""
        return self.fetcher.get_24hr_stats(symbol)
    
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
    
    def calculate_volume_profile(self, df: pd.DataFrame, bins: int = 20) -> Tuple[List[float], List[float]]:
        """Calculate volume profile to identify high volume price levels"""
        price_min = df['low'].min()
        price_max = df['high'].max()
        price_range = np.linspace(price_min, price_max, bins + 1)
        
        volume_profile = []
        price_levels = []
        
        for i in range(len(price_range) - 1):
            level_low = price_range[i]
            level_high = price_range[i + 1]
            level_mid = (level_low + level_high) / 2
            
            # Calculate volume for this price level
            volume_sum = 0
            for _, row in df.iterrows():
                if level_low <= row['low'] <= level_high or level_low <= row['high'] <= level_high:
                    volume_sum += row['volume']
            
            price_levels.append(level_mid)
            volume_profile.append(volume_sum)
        
        return price_levels, volume_profile
    
    def scan_coin(self, symbol: str) -> Dict:
        """Scan a single perpetual contract for support/resistance levels"""
        print(f"Scanning {symbol}...")
        
        # Get price data using BinancePerpetualFetcher
        df = self.get_klines(symbol)
        if df is None or df.empty:
            return {'symbol': symbol, 'error': 'Failed to fetch data'}
        
        # Get current price and 24hr stats using BinancePerpetualFetcher
        current_price = df['close'].iloc[-1]
        stats_24hr = self.get_24hr_stats(symbol)
        
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
        
        # Calculate volume profile
        price_levels, volume_profile = self.calculate_volume_profile(df)
        max_volume_idx = np.argmax(volume_profile)
        poc_price = price_levels[max_volume_idx]  # Point of Control
        
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
        
        # Extract additional perpetual-specific data
        change_24h = float(stats_24hr.get('priceChangePercent', 0))
        volume_24h = float(stats_24hr.get('volume', 0))
        quote_volume_24h = float(stats_24hr.get('quoteVolume', 0))
        
        return {
            'symbol': symbol,
            'current_price': current_price,
            'signal': signal,
            'rsi': round(current_rsi, 2),
            'change_24h': round(change_24h, 2),
            'volume_24h': volume_24h,
            'quote_volume_24h': quote_volume_24h,
            'near_support': near_support,
            'support_level': support_level if near_support else None,
            'support_strength': support_strength,
            'near_resistance': near_resistance,
            'resistance_level': resistance_level if near_resistance else None,
            'resistance_strength': resistance_strength,
            'total_support_levels': len(support_levels),
            'total_resistance_levels': len(resistance_levels),
            'poc_price': poc_price,  # Point of Control from volume profile
            'near_poc': abs(current_price - poc_price) / poc_price <= 0.01,
            'contract_type': 'PERPETUAL'
        }
    
    def scan_multiple_coins(self, coin_list: List[str], delay: float = 0.1) -> List[Dict]:
        """Scan multiple perpetual contracts with rate limiting"""
        results = []
        
        for symbol in coin_list:
            try:
                # Auto-format symbol if needed
                formatted_symbol = self.fetcher._format_symbol(symbol)
                result = self.scan_coin(formatted_symbol)
                results.append(result)
                
                # Rate limiting to avoid API limits
                time.sleep(delay)
                
            except Exception as e:
                print(f"Error scanning {symbol}: {e}")
                results.append({'symbol': symbol, 'error': str(e)})
        
        return results
    
    def scan_top_volume_coins(self, top_n: int = 50) -> List[Dict]:
        """Scan top volume perpetual contracts"""
        # Get all active symbols
        all_symbols = self.get_active_symbols()
        
        # Get 24hr stats for all symbols using BinancePerpetualFetcher
        try:
            tickers = self.fetcher.get_all_24hr_stats()
            
            # Filter and sort by volume
            usdt_tickers = [t for t in tickers if t['symbol'].endswith('USDT') and t['symbol'] in all_symbols]
            sorted_tickers = sorted(usdt_tickers, key=lambda x: float(x['quoteVolume']), reverse=True)
            
            # Get top N symbols
            top_symbols = [t['symbol'] for t in sorted_tickers[:top_n]]
            
            return self.scan_multiple_coins(top_symbols)
            
        except Exception as e:
            print(f"Error getting top volume coins: {e}")
            return []
    
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
            elif filter_type == "strong_resistance":
                if result['signal'] == "STRONG_RESISTANCE":
                    filtered.append(result)
            elif filter_type == "all_signals":
                if result['signal'] != "NEUTRAL":
                    filtered.append(result)
            elif filter_type == "high_volume":
                if result['quote_volume_24h'] > 100000000:  # 100M+ USDT volume
                    filtered.append(result)
            elif filter_type == "near_poc":
                if result['near_poc']:
                    filtered.append(result)
        
        return filtered
    
    def display_results(self, results: List[Dict]):
        """Display results in a formatted table"""
        if not results:
            print("No coins found matching the criteria.")
            return
        
        print(f"\n{'Symbol':<15} {'Price':<12} {'Signal':<18} {'RSI':<6} {'24h%':<8} {'Volume(M)':<12} {'Level':<12} {'Str':<4}")
        print("-" * 100)
        
        for result in results:
            if 'error' in result:
                print(f"{result['symbol']:<15} {'ERROR':<12} {result['error']:<18}")
                continue
            
            level = ""
            if result['near_support']:
                level = f"{result['support_level']:.6f}"
            elif result['near_resistance']:
                level = f"{result['resistance_level']:.6f}"
            
            strength = ""
            if result['near_support']:
                strength = str(result['support_strength'])
            elif result['near_resistance']:
                strength = str(result['resistance_strength'])
            
            volume_m = result['quote_volume_24h'] / 1000000  # Convert to millions
            
            print(f"{result['symbol']:<15} {result['current_price']:<12.6f} {result['signal']:<18} "
                f"{result['rsi']:<6.2f} {result['change_24h']:<8.2f} {volume_m:<12.1f} {level:<12} {strength:<4}")


# # Usage Examples:
# if __name__ == "__main__":
#     scanner = Binance_Support_Resistance_Perpetual_Scanner()

#     print("🚀 Perpetual Support/Resistance Scanner")
#     print("=" * 50)

#     # Example 1: Scan specific perpetual contracts (supports auto-formatting)
#     print("\n📊 Scanning specific coins...")
#     coins = ['BTC', 'ETH', 'ADA', 'SOL', 'DOGE']  # Will auto-convert to BTCUSDT, ETHUSDT, etc.
#     results = scanner.scan_multiple_coins(coins)
#     scanner.display_results(results)

#     # Example 2: Scan top 20 volume perpetual contracts
#     print("\n📈 Scanning top 20 volume perpetual contracts...")
#     results = scanner.scan_top_volume_coins(20)
#     filtered_results = scanner.filter_results(results, "all_signals")
#     scanner.display_results(filtered_results)

#     # Example 3: Get strong support signals only
#     print("\n💪 Strong support signals:")
#     strong_support = scanner.filter_results(results, "strong_support")
#     scanner.display_results(strong_support)

#     # Example 4: Get all active USDT perpetual contracts
#     print(f"\n📋 Getting all active symbols...")
#     active_symbols = scanner.get_active_symbols()
#     print(f"Found {len(active_symbols)} active USDT perpetual contracts")
#     print(f"First 10: {active_symbols[:10]}")