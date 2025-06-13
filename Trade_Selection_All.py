import pandas as pd
import numpy as np
import requests
import time
from datetime import datetime, timedelta
import warnings
import concurrent.futures
from threading import Lock
import json
warnings.filterwarnings('ignore')

class BinanceAllUSDTScalpingFilter:
    def __init__(self, max_workers=10, delay_between_requests=0.05, weight_profile='balanced'):
        self.base_url = "https://api.binance.com/api/v3"
        self.klines_url = "https://api.binance.com/api/v3/klines"
        self.ticker_url = "https://api.binance.com/api/v3/ticker/24hr"
        self.orderbook_url = "https://api.binance.com/api/v3/depth"
        self.max_workers = max_workers
        self.delay_between_requests = delay_between_requests
        self.request_lock = Lock()
        self.request_count = 0
        # NEW: Allow user to select weight profile ('balanced', 'volatile', 'trending')
        self.weight_profile = weight_profile
        # NEW: Store market volatility for dynamic weighting
        self.market_volatility = None

    def safe_request(self, url, params=None, timeout=10):
        """Thread-safe request with rate limiting"""
        with self.request_lock:
            self.request_count += 1
            if self.request_count % 10 == 0:
                time.sleep(self.delay_between_requests * 5)
            else:
                time.sleep(self.delay_between_requests)
        
        try:
            response = requests.get(url, params=params, timeout=timeout)
            return response
        except Exception as e:
            return None
    
    def get_all_usdt_pairs(self):
        """Get ALL USDT trading pairs from Binance with comprehensive filtering"""
        try:
            response = self.safe_request(f"{self.base_url}/exchangeInfo")
            
            if not response or response.status_code != 200:
                return []
            
            exchange_info = response.json()
            usdt_pairs = []
            stablecoins = [
                'GUSDUSDT', 'FRAXUSDT', 'USDDUSDT', 'MIMUSDT', 'LUSDUSDT', 'FEIUSDT', 'HUSDUSDT', 'SUSDUSDT', 'OUSDUSDT',
                'USTCUSDT', 'VAIUSDT', 'DOLAUSDT', 'ALUSDUSDT', 'MUSDUSDT', 'DUSDUSDT', 'CUSDUSDT', 'NUSDUSDT', 'ZUSDUSDT', 'EURUSDT'
            ]
            
            for symbol in exchange_info['symbols']:
                if (symbol['quoteAsset'] == 'USDT' and 
                    symbol['status'] == 'TRADING'):
                    
                    permissions = symbol.get('permissions', [])
                    if ('SPOT' in permissions or 
                        'MARGIN' in permissions or 
                        len(permissions) == 0):
                        
                        symbol_name = symbol['symbol']
                        base_asset = symbol['baseAsset']
                        
                        skip_patterns = ['UP', 'DOWN', 'BULL', 'BEAR', 'HALF', 'HEDGE']
                        if (not any(pattern in base_asset for pattern in skip_patterns) and 
                            symbol_name not in stablecoins):
                            usdt_pairs.append(symbol_name)
            
            print(f"Found {len(usdt_pairs)} total USDT trading pairs")
            
            return usdt_pairs
            
        except Exception as e:
            return []
    
    def get_comprehensive_24h_stats(self, target_symbols=None):
        """Get 24h statistics for ALL symbols or specific targets"""
        try:
            response = self.safe_request(self.ticker_url)
            
            if not response or response.status_code != 200:
                return {}
            
            data = response.json()
            stats_dict = {}
            processed_count = 0
            
            for item in data:
                symbol = item['symbol']
                
                if target_symbols and symbol not in target_symbols:
                    continue
                
                if not symbol.endswith('USDT'):
                    continue
                
                try:
                    stats_dict[symbol] = {
                        'volume': float(item['quoteVolume']),
                        'price_change_pct': float(item['priceChangePercent']),
                        'high': float(item['highPrice']),
                        'low': float(item['lowPrice']),
                        'last_price': float(item['lastPrice']),
                        'bid_price': float(item['bidPrice']),
                        'ask_price': float(item['askPrice']),
                        'count': int(item['count']),
                        'open_price': float(item['openPrice']),
                        'weighted_avg_price': float(item['weightedAvgPrice']),
                        'prev_close_price': float(item['prevClosePrice']),
                        'bid_qty': float(item['bidQty']),
                        'ask_qty': float(item['askQty'])
                    }
                    processed_count += 1
                    
                except (ValueError, KeyError) as e:
                    continue
            
            return stats_dict
            
        except Exception as e:
            return {}
    
    def get_klines_data(self, symbol, interval='15m', limit=100):
        """Get klines data for technical analysis with better error handling"""
        try:
            params = {
                'symbol': symbol,
                'interval': interval,
                'limit': limit
            }
            
            response = self.safe_request(self.klines_url, params=params)
            if not response or response.status_code != 200:
                return None
                
            data = response.json()
            
            if not data or len(data) < 20:
                return None
            
            df = pd.DataFrame(data, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_volume', 'trades_count', 'taker_buy_volume',
                'taker_buy_quote_volume', 'ignore'
            ])
            
            numeric_columns = ['open', 'high', 'low', 'close', 'volume', 'quote_volume']
            for col in numeric_columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            
            if df[numeric_columns].isnull().any().any():
                return None
            
            return df
            
        except Exception as e:
            return None
    
    def calculate_rsi(self, prices, period=14):
        """Calculate RSI indicator with better error handling"""
        try:
            if len(prices) < period + 1:
                return 50
                
            delta = prices.diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
            
            loss = loss.replace(0, 0.000001)
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            
            return rsi.iloc[-1] if not pd.isna(rsi.iloc[-1]) else 50
        except:
            return 50
    
    def calculate_atr(self, df, period=14):
        """Calculate Average True Range with error handling"""
        try:
            if len(df) < period + 1:
                return 0
                
            high = df['high']
            low = df['low']
            close = df['close']
            
            tr1 = high - low
            tr2 = abs(high - close.shift())
            tr3 = abs(low - close.shift())
            
            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            atr = tr.rolling(window=period).mean().iloc[-1]
            
            return atr if not pd.isna(atr) else 0
        except:
            return 0
    
    # NEW: Calculate EMA for trend confirmation
    def calculate_ema(self, prices, period):
        """Calculate Exponential Moving Average"""
        try:
            return prices.ewm(span=period, adjust=False).mean().iloc[-1] if len(prices) >= period else np.nan
        except:
            return np.nan
    
    # NEW: Calculate ADX for trend strength
    def calculate_adx(self, df, period=14):
        """Calculate Average Directional Index for trend strength"""
        try:
            if len(df) < period * 2:
                return 0
                
            high = df['high']
            low = df['low']
            close = df['close']
            
            plus_dm = high.diff()
            minus_dm = -low.diff()
            
            plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0)
            minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0)
            
            tr = self.calculate_atr(df, period=1)
            tr = tr.replace(0, 0.000001)
            
            plus_di = 100 * (plus_dm.rolling(window=period).mean() / tr)
            minus_di = 100 * (minus_dm.rolling(window=period).mean() / tr)
            
            dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
            adx = dx.rolling(window=period).mean().iloc[-1]
            
            return adx if not pd.isna(adx) else 0
        except:
            return 0
    
    def calculate_volatility(self, df):
        """Calculate price volatility percentage"""
        try:
            if len(df) < 10:
                return 0
                
            returns = df['close'].pct_change().dropna()
            if len(returns) == 0:
                return 0
                
            volatility = returns.std() * np.sqrt(len(returns)) * 100
            return volatility if not pd.isna(volatility) else 0
        except:
            return 0
    
    # NEW: Estimate market-wide volatility for dynamic weighting
    def estimate_market_volatility(self, stats_dict):
        """Calculate average volatility across all USDT pairs"""
        try:
            volatilities = [self.calculate_volatility(self.get_klines_data(symbol)) 
                           for symbol in list(stats_dict.keys())[:20]]  # Sample 20 pairs
            volatilities = [v for v in volatilities if v > 0]
            return np.mean(volatilities) if volatilities else 1.0
        except:
            return 1.0
    
    def calculate_volume_profile(self, df):
        """Calculate volume-related metrics"""
        try:
            if len(df) < 20:
                return 0, 1.0, 0.5
                
            recent_volume = df['volume'].tail(20).mean()
            volume_trend = df['volume'].tail(10).mean() / df['volume'].tail(20).mean()
            
            df['price_range'] = df['high'] - df['low']
            df['price_range'] = df['price_range'].replace(0, 0.000001)
            df['close_position'] = (df['close'] - df['low']) / df['price_range']
            buy_pressure = df['close_position'].tail(20).mean()
            
            return (recent_volume if not pd.isna(recent_volume) else 0,
                   volume_trend if not pd.isna(volume_trend) else 1.0,
                   buy_pressure if not pd.isna(buy_pressure) else 0.5)
        except:
            return 0, 1.0, 0.5
    
    def analyze_symbol_parallel(self, symbol_stats_pair):
        """Analyze a single symbol - designed for parallel processing"""
        symbol, stats = symbol_stats_pair
        
        try:
            df = self.get_klines_data(symbol)
            if df is None or len(df) < 30:
                return None
            
            current_price = df['close'].iloc[-1]
            rsi = self.calculate_rsi(df['close'])
            atr = self.calculate_atr(df)
            volatility = self.calculate_volatility(df)
            
            recent_volume, volume_trend, buy_pressure = self.calculate_volume_profile(df)
            
            price_momentum = ((current_price - df['close'].iloc[-20]) / df['close'].iloc[-20] * 100 
                            if len(df) >= 20 else 0)
            
            bid_price = stats.get('bid_price', current_price)
            ask_price = stats.get('ask_price', current_price)
            spread_pct = ((ask_price - bid_price) / bid_price * 100) if bid_price > 0 else 0.1
            
            # NEW: Calculate EMAs and ADX for trend confirmation
            ema9 = self.calculate_ema(df['close'], 9)
            ema21 = self.calculate_ema(df['close'], 21)
            adx = self.calculate_adx(df)
            
            # NEW: Determine trend direction (1 for bullish, -1 for bearish, 0 for neutral)
            trend_direction = 1 if (ema9 > ema21 and not pd.isna(ema9) and not pd.isna(ema21)) else \
                             -1 if (ema9 < ema21 and not pd.isna(ema9) and not pd.isna(ema21)) else 0
            trend_strength = adx
            
            analysis = {
                'symbol': symbol,
                'current_price': current_price,
                'volume_24h': stats.get('volume', 0),
                'price_change_24h': stats.get('price_change_pct', 0),
                'rsi': rsi,
                'atr': atr,
                'volatility': volatility,
                'volume_trend': volume_trend,
                'buy_pressure': buy_pressure,
                'price_momentum': price_momentum,
                'spread_pct': spread_pct,
                'trade_count': stats.get('count', 0),
                'weighted_avg_price': stats.get('weighted_avg_price', current_price),
                'price_range_24h': ((stats.get('high', current_price) - stats.get('low', current_price)) 
                                  / stats.get('low', current_price) * 100) if stats.get('low', 0) > 0 else 0,
                'trend_direction': trend_direction,
                'trend_strength': trend_strength
            }
            
            return analysis
            
        except Exception as e:
            return None
    
    def calculate_enhanced_scalping_score(self, analysis):
        """Enhanced scalping score calculation with dynamic weights and trend confirmation"""
        score = 0
        
        # NEW: Adjust weights based on weight_profile and market volatility
        if self.market_volatility is None:
            weights = {
                'volume': 15, 'volatility': 20, 'rsi': 15, 'volume_trend': 10,
                'buy_pressure': 8, 'spread': -10, 'trades': 10, 'momentum': 10,
                'price_range': 5, 'trend': 12
            }
        else:
            # Dynamic weight adjustment based on market volatility
            if self.weight_profile == 'volatile' or self.market_volatility < 1.0:
                weights = {
                    'volume': 12, 'volatility': 25, 'rsi': 15, 'volume_trend': 8,
                    'buy_pressure': 8, 'spread': -8, 'trades': 8, 'momentum': 12,
                    'price_range': 5, 'trend': 10
                }
            elif self.weight_profile == 'trending' or self.market_volatility > 3.0:
                weights = {
                    'volume': 15, 'volatility': 15, 'rsi': 12, 'volume_trend': 10,
                    'buy_pressure': 8, 'spread': -10, 'trades': 10, 'momentum': 10,
                    'price_range': 5, 'trend': 15
                }
            else:  # balanced
                weights = {
                    'volume': 15, 'volatility': 20, 'rsi': 15, 'volume_trend': 10,
                    'buy_pressure': 8, 'spread': -10, 'trades': 10, 'momentum': 10,
                    'price_range': 5, 'trend': 12
                }
        
        # MODIFIED: Reduced volume weight, added mid-tier rewards
        volume = analysis['volume_24h']
        if volume > 500_000_000:
            score += 15 * weights['volume'] / 15
        elif volume > 100_000_000:
            score += 13 * weights['volume'] / 15
        elif volume > 50_000_000:
            score += 11 * weights['volume'] / 15
        elif volume > 10_000_000:
            score += 9 * weights['volume'] / 15
        elif volume > 5_000_000:
            score += 7 * weights['volume'] / 15
        elif volume > 1_000_000:
            score += 5 * weights['volume'] / 15
        elif volume > 500_000:
            score += 3 * weights['volume'] / 15
        
        # MODIFIED: Wider volatility range for low-volatility markets
        vol = analysis['volatility']
        volatility_threshold = 1.0 if self.market_volatility is None or self.market_volatility < 1.0 else 1.5
        if volatility_threshold <= vol <= volatility_threshold + 3:
            score += 20 * weights['volatility'] / 20
        elif volatility_threshold - 0.5 <= vol <= volatility_threshold + 5:
            score += 18 * weights['volatility'] / 20
        elif volatility_threshold - 0.7 <= vol <= volatility_threshold + 7:
            score += 15 * weights['volatility'] / 20
        elif volatility_threshold - 1.0 <= vol <= volatility_threshold + 10:
            score += 12 * weights['volatility'] / 20
        elif vol < volatility_threshold - 1.0:
            score += 5 * weights['volatility'] / 20
        else:
            score += 8 * weights['volatility'] / 20
        
        rsi = analysis['rsi']
        if rsi < 25 or rsi > 75:
            score += 15 * weights['rsi'] / 15
        elif rsi < 30 or rsi > 70:
            score += 12 * weights['rsi'] / 15
        elif rsi < 35 or rsi > 65:
            score += 8 * weights['rsi'] / 15
        else:
            score += 5 * weights['rsi'] / 15
        
        vol_trend = analysis['volume_trend']
        if vol_trend > 1.5:
            score += 10 * weights['volume_trend'] / 10
        elif vol_trend > 1.3:
            score += 8 * weights['volume_trend'] / 10
        elif vol_trend > 1.2:
            score += 6 * weights['volume_trend'] / 10
        elif vol_trend > 1.1:
            score += 4 * weights['volume_trend'] / 10
        elif vol_trend >= 1.0:
            score += 2 * weights['volume_trend'] / 10
        
        bp = analysis['buy_pressure']
        if bp > 0.7:
            score += 8 * weights['buy_pressure'] / 8
        elif bp > 0.6:
            score += 6 * weights['buy_pressure'] / 8
        elif bp > 0.5:
            score += 4 * weights['buy_pressure'] / 8
        elif bp > 0.4:
            score += 2 * weights['buy_pressure'] / 8
        
        # MODIFIED: Reduced spread penalty for high-momentum pairs
        spread = analysis['spread_pct']
        momentum = abs(analysis['price_momentum'])
        spread_penalty = weights['spread']
        if momentum > 2.0:
            spread_penalty *= 0.5  # Halve penalty for high-momentum pairs
        if spread > 1.0:
            score += -10 * spread_penalty / -10
        elif spread > 0.5:
            score += -7 * spread_penalty / -10
        elif spread > 0.3:
            score += -4 * spread_penalty / -10
        elif spread > 0.1:
            score += -2 * spread_penalty / -10
        
        trades = analysis['trade_count']
        if trades > 500_000:
            score += 12 * weights['trades'] / 10
        elif trades > 200_000:
            score += 10 * weights['trades'] / 10
        elif trades > 100_000:
            score += 8 * weights['trades'] / 10
        elif trades > 50_000:
            score += 6 * weights['trades'] / 10
        elif trades > 20_000:
            score += 4 * weights['trades'] / 10
        elif trades > 5_000:
            score += 2 * weights['trades'] / 10
        
        if 0.5 <= momentum <= 2:
            score += 10 * weights['momentum'] / 10
        elif 0.2 <= momentum <= 4:
            score += 8 * weights['momentum'] / 10
        elif momentum <= 6:
            score += 5 * weights['momentum'] / 10
        elif momentum > 10:
            score -= 5 * weights['momentum'] / 10
        
        price_range = analysis['price_range_24h']
        if 2 <= price_range <= 8:
            score += 5 * weights['price_range'] / 5
        elif 1 <= price_range <= 12:
            score += 3 * weights['price_range'] / 5
        
        # NEW: Add trend confirmation score
        trend_direction = analysis['trend_direction']
        trend_strength = analysis['trend_strength']
        if trend_strength > 25 and trend_direction != 0:
            score += 12 * weights['trend'] / 12
        elif trend_strength > 20 and trend_direction != 0:
            score += 8 * weights['trend'] / 12
        elif trend_strength > 15 and trend_direction != 0:
            score += 4 * weights['trend'] / 12
        
        return max(0, min(score, 100))
    
    def filter_all_usdt_pairs(self, min_volume=100_000, top_n=50, 
                             use_parallel=True, volume_filter_first=True, use_percentile_volume=False):
        """Main function to analyze ALL USDT pairs with adaptive volume filter"""
        
        all_symbols = self.get_all_usdt_pairs()
        if not all_symbols:
            return []
        
        all_stats = self.get_comprehensive_24h_stats(all_symbols)
        if not all_stats:
            return []
        
        # NEW: Set market volatility for dynamic weighting
        self.market_volatility = self.estimate_market_volatility(all_stats)
        
        # MODIFIED: Adaptive volume filter using percentile
        if volume_filter_first:
            if use_percentile_volume:
                volumes = [stats['volume'] for stats in all_stats.values()]
                min_volume = np.percentile(volumes, 25) if volumes else min_volume  # Bottom 25% cutoff
            volume_filtered = {
                symbol: stats for symbol, stats in all_stats.items()
                if stats['volume'] >= min_volume
            }
        else:
            volume_filtered = all_stats
        
        if not volume_filtered:
            volume_filtered = all_stats
        
        analysis_pairs = list(volume_filtered.items())
        
        max_analysis = min(len(analysis_pairs), 200)
        analysis_pairs = analysis_pairs[:max_analysis]
        
        results = []
        
        if use_parallel and len(analysis_pairs) > 20:
            with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                batch_size = 20
                for i in range(0, len(analysis_pairs), batch_size):
                    batch = analysis_pairs[i:i+batch_size]
                    
                    future_to_symbol = {
                        executor.submit(self.analyze_symbol_parallel, pair): pair[0] 
                        for pair in batch
                    }
                    
                    for future in concurrent.futures.as_completed(future_to_symbol):
                        result = future.result()
                        if result:
                            result['scalping_score'] = self.calculate_enhanced_scalping_score(result)
                            results.append(result)
                    
                    if i + batch_size < len(analysis_pairs):
                        time.sleep(1)
        else:
            for symbol, stats in analysis_pairs:
                analysis = self.analyze_symbol_parallel((symbol, stats))
                if analysis:
                    analysis['scalping_score'] = self.calculate_enhanced_scalping_score(analysis)
                    results.append(analysis)
        
        if not results:
            return []
        
        results.sort(key=lambda x: x['scalping_score'], reverse=True)
        
        return results[:top_n]
    
    def display_comprehensive_results(self, results):
        """Display comprehensive results with enhanced formatting"""
        if not results:
            return
        
        json_results = []
        for result in results:
            json_result = {k: float(v) if isinstance(v, (int, float, np.integer, np.floating)) else v 
                        for k, v in result.items()}
            json_results.append(json_result)
        
        self.save_results_to_file(json_results)
    
    def save_results_to_file(self, results):
        """Save results to JSON file for further analysis"""
        try:
            filename = f"binance_all_usdt_scalping_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            
            with open(filename, 'w') as f:
                json.dump(results, f, indent=2)
                
        except Exception as e:
            pass

if __name__ == "__main__":
    # MODIFIED: Allow selection of weight profile and percentile volume filter
    scalping_filter = BinanceAllUSDTScalpingFilter(
        max_workers=8,
        delay_between_requests=0.1,
        weight_profile='volatile'  # Options: 'balanced', 'volatile', 'trending'
    )
    
    print("Scanning ALL Binance USDT pairs for scalping opportunities...")
    
    best_coins = scalping_filter.filter_all_usdt_pairs(
        min_volume=50_000,
        top_n=30,
        use_parallel=True,
        volume_filter_first=False,
        use_percentile_volume=True  # NEW: Use percentile-based volume filter
    )
    
    scalping_filter.display_comprehensive_results(best_coins)
    
    high_volume_coins = scalping_filter.filter_all_usdt_pairs(
        min_volume=1_000_000,
        top_n=20,
        use_parallel=True,
        volume_filter_first=True,
        use_percentile_volume=False
    )
    
    print("Used parallel processing for maximum efficiency")