import requests
import pandas as pd
import numpy as np
from datetime import datetime
import time
from concurrent.futures import ThreadPoolExecutor, as_completed


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
            'XRP': 'XRPUSDT',
            'LTC': 'LTCUSDT',
            'BCH': 'BCHUSDT',
            'UNI': 'UNIUSDT',
            'VET': 'VETUSDT'
        }
        
        # If it's a simple symbol, convert to USDT pair
        if symbol in symbol_map:
            return symbol_map[symbol]
        
        # If it doesn't end with USDT, BUSD, etc., assume it needs USDT
        if not any(symbol.endswith(quote) for quote in ['USDT', 'BUSD', 'USDC']):
            return f"{symbol}USDT"
        
        return symbol
    
    def get_klines(self, symbol, interval='1h', limit=20):
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
            
            # Convert to DataFrame format matching spot format
            df = pd.DataFrame(data, columns=[
                'open_time', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_volume', 'trades_count', 'buy_base_volume',
                'buy_quote_volume', 'ignore'
            ])
            
            return df
            
        except requests.RequestException as e:
            print(f"Error fetching perpetual data for {symbol}: {e}")
            return None


class BinanceUSDTPressureScanner:
    def __init__(self):
        self.base_url = "https://api.binance.com/api/v3"
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        self.perpetual_fetcher = BinancePerpetualFetcher()
        
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
            'XRP': 'XRPUSDT',
            'LTC': 'LTCUSDT',
            'BCH': 'BCHUSDT',
            'UNI': 'UNIUSDT',
            'VET': 'VETUSDT'
        }
        
        # If it's a simple symbol, convert to USDT pair
        if symbol in symbol_map:
            return symbol_map[symbol]
        
        # If it doesn't end with USDT, BUSD, etc., assume it needs USDT
        if not any(symbol.endswith(quote) for quote in ['USDT', 'BUSD', 'USDC']):
            return f"{symbol}USDT"
        
        return symbol
        
    def get_kline_data(self, symbol, interval='1h', limit=20, market_type='spot'):
        """Get kline data for a symbol from spot or perpetual market"""
        symbol = self._format_symbol(symbol)
        
        if market_type == 'perpetual':
            return self.perpetual_fetcher.get_klines(symbol, interval, limit)
        
        # Spot market (default)
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
            print(f"Error fetching spot data for {symbol}: {e}")
            return None
    
    def calculate_buy_pressure(self, symbol, market_type='spot'):
        """Calculate buy pressure for a single symbol"""
        if market_type == 'perpetual':
            kline_data = self.get_kline_data(symbol, market_type='perpetual')
            if kline_data is None:
                return None
            df = kline_data  # Already a DataFrame from perpetual fetcher
        else:
            kline_data = self.get_kline_data(symbol, market_type='spot')
            if not kline_data:
                return None
            
            # Process kline data for spot
            df = pd.DataFrame(kline_data, columns=[
                'open_time', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_volume', 'trades_count', 'buy_base_volume',
                'buy_quote_volume', 'ignore'
            ])
        
        try:
            # Convert to numeric
            for col in ['open', 'high', 'low', 'close', 'volume', 'buy_base_volume', 'quote_volume']:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col])
            
            # Handle missing buy_base_volume for perpetual (estimate from volume)
            if 'buy_base_volume' not in df.columns or df['buy_base_volume'].isna().all():
                # Estimate buy volume as 50% for perpetual markets (placeholder)
                df['buy_base_volume'] = df['volume'] * 0.5
                print(f"Warning: Using estimated buy volume for {symbol} ({market_type})")
            
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
                'symbol': self._format_symbol(symbol),
                'market_type': market_type,
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
            print(f"Error calculating buy pressure for {symbol} ({market_type}): {e}")
            return None
    
    def scan_multiple_symbols(self, symbols, include_both_markets=True, max_workers=10):
        """Scan multiple symbols concurrently from both spot and perpetual markets"""
        results = []
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            future_to_symbol = {}
            
            for symbol in symbols:
                if include_both_markets:
                    # Submit both spot and perpetual for each symbol
                    spot_future = executor.submit(self.calculate_buy_pressure, symbol, 'spot')
                    perp_future = executor.submit(self.calculate_buy_pressure, symbol, 'perpetual')
                    future_to_symbol[spot_future] = (symbol, 'spot')
                    future_to_symbol[perp_future] = (symbol, 'perpetual')
                else:
                    # Only spot market
                    spot_future = executor.submit(self.calculate_buy_pressure, symbol, 'spot')
                    future_to_symbol[spot_future] = (symbol, 'spot')
            
            # Collect results
            for future in as_completed(future_to_symbol):
                symbol, market_type = future_to_symbol[future]
                try:
                    result = future.result(timeout=15)
                    if result:
                        results.append(result)
                except Exception as e:
                    print(f"Error processing {symbol} ({market_type}): {e}")
                    pass
                
                # Add small delay to avoid rate limits
                time.sleep(0.1)
        
        return results
    
    def get_dataframe(self, symbols, include_both_markets=True, apply_filters=True, top_n=50):
        """Return DataFrame with buy pressure data for given symbols"""
        
        # Step 1: Calculate buy pressure for all input symbols
        pressure_data = self.scan_multiple_symbols(symbols, include_both_markets)
        
        if not pressure_data:
            print("No data retrieved for any symbols")
            return pd.DataFrame()
        
        # Step 2: Create DataFrame
        df = pd.DataFrame(pressure_data)
        
        # Apply filters for quality coins (optional)
        if apply_filters:
            filtered_df = df[
                (df['avg_buy_pressure_5periods'] >= 45) &  # At least 45% buy pressure
                (df['latest_volume'] >= 100) &  # Minimum volume
                (df['volatility'] <= 25)  # Higher volatility threshold for 1h
            ].copy()
        else:
            filtered_df = df.copy()
        
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


def get_binance_buy_sell_pressure(symbols, include_both_markets=True, apply_filters=True, top_n=50):
    """
    Get buy pressure DataFrame for specified symbols from spot and perpetual markets
    
    Args:
        symbols (list): List of trading symbols (e.g., ['BTCUSDT', 'ETHUSDT', 'SOLUSDT'])
        include_both_markets (bool): If True, includes both spot and perpetual data for each symbol
                                If False, only includes spot data (default: True)
        apply_filters (bool): Whether to apply quality filters (default: True)
        top_n (int): Number of top results to return
    
    Returns:
        pandas.DataFrame: Buy pressure analysis with columns:
            - rank: Ranking by buy pressure
            - symbol: Trading pair symbol
            - market_type: 'spot' or 'perpetual'
            - current_buy_pressure: Current buy pressure %
            - current_sell_pressure: Current sell pressure %
            - avg_buy_pressure_5periods: Average buy pressure over 5 periods
            - buy_pressure_trend: Trend in buy pressure
            - latest_price_change: Latest price change %
            - latest_volume: Latest volume
            - volume_trend: Volume trend %
            - volatility: Price volatility
            - signal: Trading signal (STRONG_BUY, BUY, WATCH, AVOID)
            - momentum: Momentum classification (EXPLOSIVE, STRONG, GOOD, BUILDING)
            - timestamp: Analysis timestamp
            
    Example:
        Input: ['BTCUSDT', 'ETHUSDT']
        Output: DataFrame with 4 rows (2 spot + 2 perpetual entries)
    """
    scanner = BinanceUSDTPressureScanner()
    return scanner.get_dataframe(symbols=symbols, include_both_markets=include_both_markets, 
                                apply_filters=apply_filters, top_n=top_n)
    
    
