import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import time

class BinanceVolatilityCalculator:
    def __init__(self):
        self.base_url = "https://api.binance.com/api/v3"
    
    def get_usdt_pairs(self):
        """Get all USDT trading pairs from Binance"""
        try:
            url = f"{self.base_url}/exchangeInfo"
            response = requests.get(url)
            data = response.json()
            
            usdt_pairs = []
            for symbol in data['symbols']:
                if (symbol['quoteAsset'] == 'USDT' and 
                    symbol['status'] == 'TRADING' and 
                    symbol['isSpotTradingAllowed']):
                    usdt_pairs.append(symbol['symbol'])
            
            print(f"Found {len(usdt_pairs)} USDT pairs")
            return usdt_pairs
        
        except Exception as e:
            print(f"Error fetching USDT pairs: {e}")
            return []
    
    def get_kline_data(self, symbol, interval='5m', limit=48):
        """Get kline/candlestick data for a symbol (48 x 5min = 4 hours)"""
        try:
            url = f"{self.base_url}/klines"
            params = {
                'symbol': symbol,
                'interval': interval,
                'limit': limit
            }
            
            response = requests.get(url, params=params)
            data = response.json()
            
            # Convert to DataFrame
            df = pd.DataFrame(data, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_volume', 'trades', 'taker_buy_base',
                'taker_buy_quote', 'ignore'
            ])
            
            # Convert price columns to float
            price_cols = ['open', 'high', 'low', 'close']
            df[price_cols] = df[price_cols].astype(float)
            df['volume'] = df['volume'].astype(float)
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            
            return df
        
        except Exception as e:
            print(f"Error fetching data for {symbol}: {e}")
            return None
    
    def calculate_4hour_volatility(self, df):
        """Calculate volatility metrics for 4-hour period"""
        if df is None or len(df) < 2:
            return None
        
        # Calculate returns (price change percentage between intervals)
        df['returns'] = df['close'].pct_change()
        
        # Remove NaN values
        returns = df['returns'].dropna()
        
        if len(returns) < 2:
            return None
        
        # Calculate 4-hour price change
        price_4h_ago = df['close'].iloc[0]
        current_price = df['close'].iloc[-1]
        price_change_4h = ((current_price - price_4h_ago) / price_4h_ago) * 100
        
        # Calculate volatility metrics optimized for 4-hour period
        volatility_metrics = {
            # Standard deviation of returns (annualized for 5-min intervals)
            'std_volatility': returns.std() * np.sqrt(288 * 365),  # 288 = 5min intervals per day
            
            # Average price range volatility (high-low spread)
            'price_range_volatility': ((df['high'] - df['low']) / df['close']).mean() * 100,
            
            # Maximum single-period price swing
            'max_single_move': max(abs(returns.max()), abs(returns.min())) * 100,
            
            # Maximum drawdown in the 4-hour period
            'max_drawdown_4h': self.calculate_max_drawdown(df['close']) * 100,
            
            # Coefficient of variation (risk per unit of return)
            'coefficient_of_variation': returns.std() / abs(returns.mean()) if returns.mean() != 0 else float('inf'),
            
            # 4-hour absolute price change
            'price_change_4h': abs(price_change_4h),
            
            # Volatility score (combines multiple factors)
            'volatility_score': self.calculate_volatility_score(df, returns),
            
            # Trading activity (volume-weighted)
            'volume_volatility': (df['volume'] * abs(df['returns'].fillna(0))).sum() / df['volume'].sum()
        }
        
        return volatility_metrics
    
    def calculate_volatility_score(self, df, returns):
        """Calculate a composite volatility score for 4-hour period"""
        # Normalize different volatility measures and combine them
        std_score = returns.std() * 100
        range_score = ((df['high'] - df['low']) / df['close']).mean() * 100
        move_score = max(abs(returns.max()), abs(returns.min())) * 100
        
        # Weighted combination
        volatility_score = (std_score * 0.5) + (range_score * 0.3) + (move_score * 0.2)
        return volatility_score
    
    def calculate_max_drawdown(self, prices):
        """Calculate maximum drawdown"""
        peak = prices.expanding().max()
        drawdown = (prices - peak) / peak
        return abs(drawdown.min())
    
    def get_top_volatile_coins_4h(self, top_n=25):
        """Get top N volatile coins based on last 4 hours of 15-minute data"""
        
        print(f"Fetching last 4 hours of 15-minute data for volatility calculation...")
        print(f"Analysis time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Get all USDT pairs
        usdt_pairs = self.get_usdt_pairs()
        
        if not usdt_pairs:
            return pd.DataFrame()
        
        volatility_data = []
        processed = 0
        
        # Process each pair (with rate limiting)
        for i, symbol in enumerate(usdt_pairs):
            try:
                # Rate limiting to avoid API limits (Binance allows 1200 requests/minute)
                if i % 20 == 0 and i > 0:
                    print(f"Processed {processed}/{len(usdt_pairs)} pairs... ({(processed/len(usdt_pairs)*100):.1f}%)")
                    time.sleep(1)  # Brief pause to respect rate limits
                
                # Get last 4 hours of 15-minute data (48 intervals)
                df = self.get_kline_data(symbol, interval='15m', limit=48)
                
                if df is not None and len(df) >= 10:  # Need at least 10 data points
                    # Calculate 4-hour volatility
                    vol_metrics = self.calculate_4hour_volatility(df)
                    
                    if vol_metrics and vol_metrics['volatility_score'] > 0:
                        current_price = df['close'].iloc[-1]
                        start_price = df['close'].iloc[0]
                        total_volume = df['volume'].sum()
                        
                        volatility_data.append({
                            'symbol': symbol,
                            'coin': symbol.replace('USDT', ''),
                            'current_price': current_price,
                            'start_price_4h': start_price,
                            'price_change_4h': vol_metrics['price_change_4h'],
                            'volatility_score': vol_metrics['volatility_score'],
                            'std_volatility': vol_metrics['std_volatility'],
                            'price_range_volatility': vol_metrics['price_range_volatility'],
                            'max_single_move': vol_metrics['max_single_move'],
                            'max_drawdown_4h': vol_metrics['max_drawdown_4h'],
                            'volume_4h': total_volume,
                            'volume_volatility': vol_metrics['volume_volatility'],
                            'data_points': len(df)
                        })
                        processed += 1
            
            except Exception as e:
                print(f"Error processing {symbol}: {e}")
                continue
        
        # Create DataFrame and sort by volatility score
        df_volatility = pd.DataFrame(volatility_data)
        
        if df_volatility.empty:
            print("No volatility data collected!")
            return df_volatility
        
        # Filter out coins with very low trading volume (likely low liquidity)
        # Keep coins with volume > 1000 USDT in 4 hours
        df_volatility = df_volatility[df_volatility['volume_4h'] > 1000]
        
        # Sort by volatility score (composite measure)
        df_volatility = df_volatility.sort_values('volatility_score', ascending=False)
        
        # Get top N
        top_volatile = df_volatility.head(top_n).copy()
        
        # Add ranking
        top_volatile['rank'] = range(1, len(top_volatile) + 1)
        
        print(f"\nAnalysis complete! Found {len(df_volatility)} qualifying coins.")
        
        return top_volatile
    
    
    #########  Use of Function  #########
    """
    calculator = BinanceVolatilityCalculator()
    top_volatile = calculator.get_top_volatile_coins_4h(top_n=25)
    
    """