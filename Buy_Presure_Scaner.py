import requests
import pandas as pd
import numpy as np
from datetime import datetime
import time
import json
from concurrent.futures import ThreadPoolExecutor, as_completed


class CompleteBinanceUSDTPressureScanner:
    def __init__(self):
        self.base_url = "https://api.binance.com/api/v3"
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        
    def get_all_usdt_pairs(self):
        """Get all active USDT trading pairs from Binance"""
        endpoint = f"{self.base_url}/exchangeInfo"
        
        try:
            response = self.session.get(endpoint)
            response.raise_for_status()
            data = response.json()
            
            # Filter for USDT pairs that are actively trading
            usdt_pairs = []
            for symbol_info in data['symbols']:
                if (symbol_info['symbol'].endswith('USDT') and 
                    symbol_info['status'] == 'TRADING' and
                    symbol_info['isSpotTradingAllowed']):
                    usdt_pairs.append(symbol_info['symbol'])
            
            return usdt_pairs
            
        except requests.exceptions.RequestException as e:
            return []
    
    def get_24hr_tickers(self):
        """Get 24hr ticker data for all symbols"""
        endpoint = f"{self.base_url}/ticker/24hr"
        
        try:
            response = self.session.get(endpoint)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            return []
    
    def filter_high_volume_pairs(self, min_volume_usdt=100000):
        """Filter USDT pairs by minimum 24h volume"""
        tickers = self.get_24hr_tickers()
        if not tickers:
            return []
        
        high_volume_pairs = []
        for ticker in tickers:
            symbol = ticker['symbol']
            if (symbol.endswith('USDT') and 
                float(ticker['quoteVolume']) >= min_volume_usdt):
                high_volume_pairs.append({
                    'symbol': symbol,
                    'volume': float(ticker['quoteVolume']),
                    'price_change': float(ticker['priceChangePercent']),
                    'last_price': float(ticker['lastPrice'])
                })
        
        # Sort by volume descending
        high_volume_pairs.sort(key=lambda x: x['volume'], reverse=True)
        return high_volume_pairs
    
    def get_kline_data(self, symbol, interval='1h', limit=20):
        """Get 1-hour kline data for a symbol"""
        endpoint = f"{self.base_url}/klines"
        params = {
            'symbol': symbol,
            'interval': interval,
            'limit': limit
        }
        
        try:
            response = self.session.get(endpoint, params=params)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            return None
    
    def calculate_buy_pressure(self, symbol):
        """Calculate buy pressure for a single symbol"""
        kline_data = self.get_kline_data(symbol)
        if not kline_data:
            return None
        
        try:
            # Process kline data
            df = pd.DataFrame(kline_data, columns=[
                'open_time', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_volume', 'trades_count', 'buy_base_volume',
                'buy_quote_volume', 'ignore'
            ])
            
            # Convert to numeric
            for col in ['open', 'high', 'low', 'close', 'volume', 'buy_base_volume', 'quote_volume']:
                df[col] = pd.to_numeric(df[col])
            
            # Calculate buy and sell volumes
            df['buy_volume'] = df['buy_base_volume']
            df['sell_volume'] = df['volume'] - df['buy_base_volume']
            
            # Calculate buy pressure percentage
            df['buy_pressure'] = (df['buy_volume'] / df['volume']) * 100
            df['sell_pressure'] = (df['sell_volume'] / df['volume']) * 100
            
            # Calculate price metrics
            df['price_change'] = ((df['close'] - df['open']) / df['open']) * 100
            df['high_low_range'] = ((df['high'] - df['low']) / df['open']) * 100
            
            # Get recent data (last 5 periods for trend analysis)
            recent_data = df.tail(5)
            latest = df.iloc[-1]
            
            # Calculate trend metrics
            buy_pressure_trend = recent_data['buy_pressure'].diff().mean()
            volume_trend = recent_data['volume'].pct_change().mean() * 100
            
            return {
                'symbol': symbol,
                'current_buy_pressure': latest['buy_pressure'],
                'current_sell_pressure': latest['sell_pressure'],
                'avg_buy_pressure_5periods': recent_data['buy_pressure'].mean(),
                'buy_pressure_trend': buy_pressure_trend,
                'latest_price_change': latest['price_change'],
                'latest_volume': latest['volume'],
                'volume_trend': volume_trend,
                'volatility': recent_data['high_low_range'].mean(),
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            return None
    
    def scan_multiple_symbols(self, symbols, max_workers=10):
        """Scan multiple symbols concurrently"""
        results = []
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            future_to_symbol = {
                executor.submit(self.calculate_buy_pressure, symbol): symbol 
                for symbol in symbols
            }
            
            # Collect results
            for future in as_completed(future_to_symbol):
                symbol = future_to_symbol[future]
                try:
                    result = future.result(timeout=10)
                    if result:
                        results.append(result)
                except Exception as e:
                    pass
                
                # Add small delay to avoid rate limits
                time.sleep(0.1)
        
        return results
    
    def get_dataframe(self, min_volume_usdt=500000, top_n=50):
        """Return DataFrame with buy pressure data"""
        
        # Step 1: Get high-volume USDT pairs
        high_volume_pairs = self.filter_high_volume_pairs(min_volume_usdt)
        if not high_volume_pairs:
            return pd.DataFrame()
        
        # Limit to top 100 by volume to avoid too many API calls
        symbols_to_scan = [pair['symbol'] for pair in high_volume_pairs[:100]]
        
        # Step 2: Calculate buy pressure for all symbols
        pressure_data = self.scan_multiple_symbols(symbols_to_scan)
        
        if not pressure_data:
            return pd.DataFrame()
        
        # Step 3: Create DataFrame
        df = pd.DataFrame(pressure_data)
        
        # Apply filters for quality coins (adjusted for 1-hour timeframe)
        filtered_df = df[
            (df['avg_buy_pressure_5periods'] >= 45) &  # At least 45% buy pressure
            (df['latest_volume'] >= 100) &  # Minimum volume
            (df['volatility'] <= 25)  # Higher volatility threshold for 1h
        ].copy()
        
        # Sort by average buy pressure
        filtered_df = filtered_df.sort_values('avg_buy_pressure_5periods', ascending=False)
        
        # Add ranking
        filtered_df.reset_index(drop=True, inplace=True)
        filtered_df.insert(0, 'rank', range(1, len(filtered_df) + 1))
        
        # Round numerical columns
        numerical_columns = [
            'current_buy_pressure', 'current_sell_pressure', 'avg_buy_pressure_5periods',
            'buy_pressure_trend', 'latest_price_change', 'volume_trend', 'volatility'
        ]
        
        for col in numerical_columns:
            if col in filtered_df.columns:
                filtered_df[col] = filtered_df[col].round(2)
        
        # Add signal classification (adjusted for 1-hour)
        filtered_df['signal'] = filtered_df.apply(self.classify_signal, axis=1)
        
        # Add momentum classification  
        filtered_df['momentum'] = filtered_df.apply(self.classify_momentum, axis=1)
        
        # Get top N results
        return filtered_df.head(top_n)
    
    def classify_signal(self, row):
        """Classify trading signal based on criteria (adjusted for 1-hour timeframe)"""
        if (row['avg_buy_pressure_5periods'] >= 62 and
            row['buy_pressure_trend'] >= 1.0 and
            row['volume_trend'] >= 8 and
            row['latest_price_change'] >= 0.5 and
            row['volatility'] <= 12):
            return 'STRONG_BUY'
        elif (row['avg_buy_pressure_5periods'] >= 55 and
            row['buy_pressure_trend'] >= 0.3 and
            row['volume_trend'] >= 0 and
            row['latest_price_change'] >= -0.5 and
            row['volatility'] <= 18):
            return 'BUY'
        elif (row['avg_buy_pressure_5periods'] >= 50 and
            row['buy_pressure_trend'] >= -0.3 and
            row['volume_trend'] >= -8):
            return 'WATCH'
        else:
            return 'AVOID'
    
    def classify_momentum(self, row):
        """Classify momentum strength (adjusted for 1-hour)"""
        trend = row['buy_pressure_trend']
        volume = row['volume_trend']
        price = row['latest_price_change']
        
        momentum_score = 0
        
        # Trend contribution (adjusted thresholds for 1h)
        if trend >= 2:
            momentum_score += 40
        elif trend >= 1:
            momentum_score += 30
        elif trend >= 0.5:
            momentum_score += 20
        else:
            momentum_score += 10
        
        # Volume contribution (adjusted for 1h)
        if volume >= 15:
            momentum_score += 30
        elif volume >= 5:
            momentum_score += 20
        elif volume >= 0:
            momentum_score += 15
        else:
            momentum_score += 5
        
        # Price contribution (adjusted for 1h)
        if price >= 1:
            momentum_score += 30
        elif price >= 0.5:
            momentum_score += 25
        elif price >= 0:
            momentum_score += 20
        else:
            momentum_score += 10
        
        if momentum_score >= 80:
            return "EXPLOSIVE"
        elif momentum_score >= 60:
            return "STRONG"
        elif momentum_score >= 40:
            return "GOOD"
        else:
            return "BUILDING"
        
def get_binance_dataframe(min_volume_usdt=1000000, top_n=25):
    """
    Simple function to get DataFrame only (1-hour timeframe)
    """
    scanner = CompleteBinanceUSDTPressureScanner()
    return scanner.get_dataframe(min_volume_usdt=min_volume_usdt, top_n=top_n)



#########  Use of Function  #########
    """
    binance_df = get_binance_dataframe(min_volume_usdt=1000000, top_n=50)
binance_df_filtered = binance_df[(binance_df['current_buy_pressure'] > 
                                binance_df['current_sell_pressure']) & 
                                (binance_df['momentum'] != "BUILDING") & 
                                (binance_df['buy_pressure_trend'] > 1) & 
                                (binance_df['momentum'] != "BUILDING") & 
                                (binance_df['buy_pressure_trend'] > 1) & 
                                (binance_df['volume_trend'] > 1)] 
    
    """