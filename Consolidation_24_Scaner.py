import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import time

class ConsolidationAnalyzer:
    def __init__(self):
        self.base_url = "https://api.binance.com/api/v3"
    
    def get_all_trading_pairs(self):
        """Get all active trading pairs from Binance"""
        try:
            response = requests.get(f"{self.base_url}/exchangeInfo")
            data = response.json()
            
            # Filter active USDT pairs only
            active_usdt_pairs = []
            for symbol_info in data['symbols']:
                if (symbol_info['status'] == 'TRADING' and 
                    symbol_info['symbol'].endswith('USDT') and
                    symbol_info['quoteAsset'] == 'USDT'):
                    active_usdt_pairs.append(symbol_info['symbol'])
            
            print(f"Found {len(active_usdt_pairs)} active USDT trading pairs")
            return active_usdt_pairs
            
        except Exception as e:
            print(f"Error fetching exchange info: {e}")
            return []
    
    def get_24h_ticker_data(self):
        """Get 24h ticker data for all symbols"""
        try:
            response = requests.get(f"{self.base_url}/ticker/24hr")
            data = response.json()
            
            # Filter USDT pairs and create a dictionary for quick lookup
            usdt_tickers = {}
            for ticker in data:
                if ticker['symbol'].endswith('USDT'):
                    usdt_tickers[ticker['symbol']] = ticker
            
            return usdt_tickers
            
        except Exception as e:
            print(f"Error fetching 24h ticker data: {e}")
            return {}
    
    def get_kline_data(self, symbol, interval='1h', limit=24):
        """Get kline/candlestick data for the last 24 hours"""
        try:
            params = {
                'symbol': symbol,
                'interval': interval,
                'limit': limit
            }
            response = requests.get(f"{self.base_url}/klines", params=params)
            data = response.json()
            
            if not data:
                return pd.DataFrame()
            
            df = pd.DataFrame(data, columns=[
                'open_time', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_asset_volume', 'number_of_trades',
                'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'
            ])
            
            # Convert to numeric
            numeric_columns = ['open', 'high', 'low', 'close', 'volume']
            for col in numeric_columns:
                df[col] = pd.to_numeric(df[col])
            
            return df
        except Exception as e:
            print(f"Error fetching kline data for {symbol}: {e}")
            return pd.DataFrame()
    
    def calculate_24h_metrics(self, df, ticker_data):
        """Calculate volatility and movement metrics for 24 hours"""
        if df.empty:
            return None
        
        try:
            # Basic price metrics
            current_price = float(ticker_data['lastPrice'])
            price_change_24h = float(ticker_data['priceChangePercent'])
            volume_24h = float(ticker_data['quoteVolume'])
            
            # Price range metrics (24h)
            high_24h = df['high'].max()
            low_24h = df['low'].min()
            price_range_24h = ((high_24h - low_24h) / current_price) * 100
            
            # Average candle body and wick analysis
            candle_bodies = abs(df['close'] - df['open']) / df['close'] * 100
            avg_candle_body = candle_bodies.mean()
            
            # Volatility indicators
            returns = df['close'].pct_change().dropna()
            volatility = returns.std() * 100 if len(returns) > 1 else 0
            
            # True Range calculation for ATR
            if len(df) > 1:
                high_low = df['high'] - df['low']
                high_close_prev = abs(df['high'] - df['close'].shift(1))
                low_close_prev = abs(df['low'] - df['close'].shift(1))
                true_range = pd.concat([high_low, high_close_prev, low_close_prev], axis=1).max(axis=1)
                atr = true_range.mean()
                atr_percentage = (atr / current_price) * 100
            else:
                atr_percentage = 0
            
            # Movement consistency
            if len(returns) > 0:
                positive_moves = (returns > 0).sum()
                negative_moves = (returns < 0).sum()
                total_moves = len(returns)
                directional_strength = abs(positive_moves - negative_moves) / total_moves
            else:
                directional_strength = 0
            
            # Volume profile
            avg_volume = df['volume'].mean()
            recent_volume = df['volume'].tail(6).mean()  # Last 6 hours
            volume_surge = (recent_volume / avg_volume) if avg_volume > 0 else 1
            
            return {
                'current_price': current_price,
                'price_change_24h': price_change_24h,
                'volume_24h': volume_24h,
                'price_range_24h': price_range_24h,
                'avg_candle_body': avg_candle_body,
                'volatility': volatility,
                'atr_percentage': atr_percentage,
                'directional_strength': directional_strength,
                'volume_surge': volume_surge,
                'high_24h': high_24h,
                'low_24h': low_24h
            }
            
        except Exception as e:
            print(f"Error calculating metrics: {e}")
            return None
    
    def is_consolidating(self, metrics, thresholds=None):
        """Determine if a coin is in consolidation based on 24h criteria"""
        if not metrics:
            return True
        
        # Consolidation thresholds for 24h analysis
        if thresholds is None:
            thresholds = {
                'max_price_range': 4.0,          # Max 4% range in 24h
                'max_volatility': 2.5,           # Max 2.5% hourly volatility
                'max_atr_percentage': 2.0,       # Max 2% ATR
                'max_abs_price_change': 3.0,     # Max 3% absolute price change
                'min_directional_strength': 0.2, # Minimum directional movement
                'max_avg_candle_body': 1.5,      # Max 1.5% average candle body
                'min_volume_threshold': 10000    # Minimum volume filter
            }
        
        # Filter out very low volume coins first
        if metrics['volume_24h'] < thresholds['min_volume_threshold']:
            return True  # Consider low volume as consolidating
        
        consolidation_score = 0
        total_criteria = 6
        
        # Check each consolidation criterion
        if metrics['price_range_24h'] < thresholds['max_price_range']:
            consolidation_score += 1
        
        if metrics['volatility'] < thresholds['max_volatility']:
            consolidation_score += 1
        
        if metrics['atr_percentage'] < thresholds['max_atr_percentage']:
            consolidation_score += 1
        
        if abs(metrics['price_change_24h']) < thresholds['max_abs_price_change']:
            consolidation_score += 1
        
        if metrics['directional_strength'] < thresholds['min_directional_strength']:
            consolidation_score += 1
            
        if metrics['avg_candle_body'] < thresholds['max_avg_candle_body']:
            consolidation_score += 1
        
        # Consider consolidating if 4 or more indicators suggest low activity
        return consolidation_score >= 4
    
    def analyze_all_coins(self, custom_thresholds=None, top_count=50):
        """Analyze ALL Binance coins and find non-consolidating ones"""
        print("Step 1: Fetching all trading pairs...")
        all_pairs = self.get_all_trading_pairs()
        
        if not all_pairs:
            print("Failed to fetch trading pairs")
            return []
        
        print("Step 2: Fetching 24h ticker data...")
        ticker_data = self.get_24h_ticker_data()
        
        if not ticker_data:
            print("Failed to fetch ticker data")
            return []
        
        print(f"Step 3: Analyzing {len(all_pairs)} coins for consolidation...")
        results = []
        failed_count = 0
        
        for i, symbol in enumerate(all_pairs, 1):
            if i % 50 == 0:
                print(f"Progress: {i}/{len(all_pairs)} coins analyzed...")
            
            # Skip if no ticker data
            if symbol not in ticker_data:
                continue
            
            # Get 24h kline data
            df = self.get_kline_data(symbol, '1h', 24)
            
            if df.empty:
                failed_count += 1
                continue
            
            # Calculate metrics
            metrics = self.calculate_24h_metrics(df, ticker_data[symbol])
            
            if not metrics:
                failed_count += 1
                continue
            
            # Check if consolidating
            is_consolidating = self.is_consolidating(metrics, custom_thresholds)
            
            result = {
                'symbol': symbol,
                'is_consolidating': is_consolidating,
                **metrics
            }
            
            results.append(result)
            
            # Small delay to avoid rate limiting
            time.sleep(0.02)
        
        print(f"Analysis complete! Processed {len(results)} coins, {failed_count} failed")
        
        # Filter NON-consolidating coins
        non_consolidating = [coin for coin in results if not coin['is_consolidating']]
        
        # Sort by volume and movement strength
        non_consolidating.sort(key=lambda x: (x['volume_24h'] * abs(x['price_change_24h'])), reverse=True)
        
        print(f"Found {len(non_consolidating)} non-consolidating coins")
        
        return non_consolidating[:top_count]
    
    def display_results(self, coins, show_count=25):
        """Return the results in a DataFrame instead of printing it"""
        if not coins:
            print("No non-consolidating coins found!")
            return None
        
        display_coins = coins[:show_count]
        
        # Create DataFrame for better formatting
        df = pd.DataFrame(display_coins)
        
        # Select and format columns for display
        display_df = df[[ 
            'symbol', 'current_price', 'price_change_24h', 'price_range_24h', 
            'volatility', 'atr_percentage', 'volume_24h', 'volume_surge'
        ]].copy()
        
        # Add rank
        display_df.insert(0, 'Rank', range(1, len(display_df) + 1))
        
        # Format columns
        display_df['volume_24h'] = display_df['volume_24h'].apply(lambda x: f"${x:,.0f}")
        display_df['current_price'] = display_df['current_price'].apply(lambda x: f"${x:.6f}")
        
        # Format percentage columns
        for col in ['price_change_24h', 'price_range_24h', 'volatility', 'atr_percentage']:
            display_df[col] = display_df[col].apply(lambda x: f"{x:.2f}%")
        
        # Format volume surge
        display_df['volume_surge'] = display_df['volume_surge'].apply(lambda x: f"{x:.1f}x")
        
        # Rename columns for display
        display_df.columns = [
            'rank', 'symbol', 'price', '24h_Change', '24h_Range', 
            'volatility', 'ATR %', '24h_Volume', 'vol_Surge'
        ]
        
        return display_df
    
    
        #########  Use of Function  #########
    """
    analyzer = ConsolidationAnalyzer()
    non_consolidating_coins = analyzer.analyze_all_coins( 
            top_count=250  # Get top 100, display top 25
        )
    CON_DF = analyzer.display_results(non_consolidating_coins, show_count=50)
    
    """

