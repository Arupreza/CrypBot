import pandas as pd
import numpy as np
import requests
from datetime import datetime, timedelta
import time
import warnings
warnings.filterwarnings('ignore')

class CryptoLongTradeScanner:
    """
    Enhanced scanner that identifies LONG trade opportunities using Binance live data
    """
    
    def __init__(self):
        # Original consolidation parameters
        self.timeframe = '15m'
        self.lookback_periods = 20
        self.volatility_threshold = 0.5
        self.volume_stability_threshold = 0.4
        self.range_threshold = 1.0
        
        # Long trade specific parameters
        self.breakout_threshold = 0.2  # 0.2% above resistance
        self.volume_spike_multiplier = 1.5  # 50% above average
        self.trend_ma_period = 50  # 50 period MA for trend
        
        # Binance API endpoint
        self.base_url = "https://api.binance.com/api/v3"
        
    def fetch_binance_klines(self, symbol: str, interval: str = '15m', limit: int = 500) -> pd.DataFrame:
        """
        Fetch kline/candlestick data from Binance
        """
        try:
            # Format symbol for Binance (e.g., BTC -> BTCUSDT)
            if not symbol.endswith('USDT'):
                symbol = f"{symbol.upper()}USDT"
            
            # Binance klines endpoint
            url = f"{self.base_url}/klines"
            
            params = {
                'symbol': symbol,
                'interval': interval,
                'limit': limit
            }
            
            response = requests.get(url, params=params)
            
            if response.status_code != 200:
                raise ValueError(f"Error fetching data: {response.text}")
            
            data = response.json()
            
            # Check if data is empty
            if not data:
                raise ValueError(f"No data received for {symbol}")
            
            # Convert to DataFrame
            df = pd.DataFrame(data, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_volume', 'trades', 'taker_buy_base',
                'taker_buy_quote', 'ignore'
            ])
            
            # Convert to proper data types
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df['Open'] = df['open'].astype(float)
            df['High'] = df['high'].astype(float)
            df['Low'] = df['low'].astype(float)
            df['Close'] = df['close'].astype(float)
            df['Volume'] = df['volume'].astype(float)
            
            # Set timestamp as index
            df.set_index('timestamp', inplace=True)
            
            # Keep only required columns
            df = df[['Open', 'High', 'Low', 'Close', 'Volume']]
            
            return df
            
        except Exception as e:
            print(f"Error fetching Binance data for {symbol}: {e}")
            return pd.DataFrame()
    
    def get_current_price(self, symbol: str) -> float:
        """Get current price from Binance ticker"""
        try:
            if not symbol.endswith('USDT'):
                symbol = f"{symbol.upper()}USDT"
            
            url = f"{self.base_url}/ticker/price"
            params = {'symbol': symbol}
            
            response = requests.get(url, params=params)
            if response.status_code == 200:
                return float(response.json()['price'])
            return 0
        except:
            return 0
    
    def calculate_consolidation_metrics(self, df: pd.DataFrame) -> dict:
        """Calculate key metrics for consolidation detection"""
        recent_df = df.tail(self.lookback_periods).copy()
        
        if len(recent_df) < self.lookback_periods:
            return {'error': 'Insufficient data'}
        
        # Price Range Analysis
        high = recent_df['High'].max()
        low = recent_df['Low'].min()
        avg_price = recent_df['Close'].mean()
        
        # Avoid division by zero
        if avg_price == 0:
            return {'error': 'Invalid price data'}
        
        price_range_pct = ((high - low) / avg_price) * 100
        
        # Volatility
        price_volatility = (recent_df['Close'].std() / avg_price) * 100
        
        # Bollinger Bands
        sma = recent_df['Close'].rolling(window=10).mean()
        std = recent_df['Close'].rolling(window=10).std()
        bb_upper = sma + (std * 2)
        bb_lower = sma - (std * 2)
        
        # Handle NaN values in Bollinger Bands
        bb_width_series = ((bb_upper - bb_lower) / sma * 100)
        bb_width = bb_width_series.iloc[-1] if not bb_width_series.empty and not pd.isna(bb_width_series.iloc[-1]) else 0
        
        # Volume Analysis
        volume_mean = recent_df['Volume'].mean()
        volume_std = recent_df['Volume'].std()
        volume_cv = volume_std / volume_mean if volume_mean > 0 else 1
        
        # Support and Resistance
        resistance = recent_df['High'].quantile(0.9)
        support = recent_df['Low'].quantile(0.1)
        
        resistance_touches = (recent_df['High'] >= resistance * 0.99).sum()
        support_touches = (recent_df['Low'] <= support * 1.01).sum()
        
        # Get current price
        current_price = recent_df['Close'].iloc[-1]
        
        return {
            'price_range_pct': price_range_pct,
            'volatility': price_volatility,
            'bb_width': bb_width,
            'volume_cv': volume_cv,
            'resistance_touches': resistance_touches,
            'support_touches': support_touches,
            'current_price': current_price,
            'resistance': resistance,
            'support': support,
            'volume_mean': volume_mean,
            'current_volume': recent_df['Volume'].iloc[-1]
        }
    
    def detect_consolidation(self, metrics: dict) -> tuple:
        """Determine if crypto is in consolidation"""
        if 'error' in metrics:
            return False, 0
        
        consolidation_score = 0
        max_score = 6
        
        if metrics['price_range_pct'] < self.range_threshold:
            consolidation_score += 2
        if metrics['volatility'] < self.volatility_threshold:
            consolidation_score += 1
        if metrics['bb_width'] < 2.0 and metrics['bb_width'] > 0:
            consolidation_score += 1
        if metrics['volume_cv'] < self.volume_stability_threshold:
            consolidation_score += 1
        if metrics['resistance_touches'] >= 2 and metrics['support_touches'] >= 2:
            consolidation_score += 1
        
        is_consolidating = consolidation_score >= 4
        
        return is_consolidating, consolidation_score
    
    def check_breakout_conditions(self, df: pd.DataFrame, metrics: dict, symbol: str) -> dict:
        """Check if conditions are favorable for a LONG trade"""
        
        # Get current and previous candle
        current_candle = df.iloc[-1]
        prev_candle = df.iloc[-2] if len(df) > 1 else current_candle
        
        # Calculate moving average for trend
        if len(df) >= self.trend_ma_period:
            ma = df['Close'].rolling(window=self.trend_ma_period).mean().iloc[-1]
        else:
            # Use a shorter MA if not enough data
            available_periods = min(20, len(df))
            ma = df['Close'].rolling(window=available_periods).mean().iloc[-1]
        
        # Get live price for most accurate breakout detection
        live_price = self.get_current_price(symbol)
        if live_price == 0:
            live_price = current_candle['Close']
        
        # Breakout detection with live price
        breakout_above_resistance = live_price > metrics['resistance'] * (1 + self.breakout_threshold/100)
        volume_spike = metrics['current_volume'] > metrics['volume_mean'] * self.volume_spike_multiplier
        
        # Trend direction
        uptrend = live_price > ma if not pd.isna(ma) else True
        
        # Check if we just broke out of consolidation
        recent_consolidation = False
        if len(df) > self.lookback_periods + 5:
            # Check if there was consolidation in the last 5 candles
            for i in range(1, 6):
                test_df = df.iloc[:-i]
                if len(test_df) >= self.lookback_periods:
                    test_metrics = self.calculate_consolidation_metrics(test_df)
                    if 'error' not in test_metrics:
                        was_consolidating, _ = self.detect_consolidation(test_metrics)
                        if was_consolidating:
                            recent_consolidation = True
                            break
        
        return {
            'breakout_above_resistance': breakout_above_resistance,
            'volume_spike': volume_spike,
            'uptrend': uptrend,
            'recent_consolidation': recent_consolidation,
            'distance_from_resistance': ((live_price - metrics['resistance']) / metrics['resistance']) * 100,
            'ma_value': ma if not pd.isna(ma) else 0,
            'live_price': live_price
        }
    
    def get_24h_stats(self, symbol: str) -> dict:
        """Get 24hr statistics from Binance"""
        try:
            if not symbol.endswith('USDT'):
                symbol = f"{symbol.upper()}USDT"
            
            url = f"{self.base_url}/ticker/24hr"
            params = {'symbol': symbol}
            
            response = requests.get(url, params=params)
            if response.status_code == 200:
                data = response.json()
                return {
                    'price_change_percent': float(data['priceChangePercent']),
                    'volume_24h': float(data['volume']),
                    'high_24h': float(data['highPrice']),
                    'low_24h': float(data['lowPrice'])
                }
        except:
            pass
        return {}
    
    def generate_long_signal(self, symbol: str) -> str:
        """Main function - generates LONG trade signals"""
        
        # Clean symbol input
        symbol = symbol.strip().upper()
        
        # Fetch data from Binance
        df = self.fetch_binance_klines(symbol)
        if df.empty:
            return f"ERROR: Cannot fetch data for {symbol} from Binance. Make sure the symbol exists."
        
        # Calculate metrics
        metrics = self.calculate_consolidation_metrics(df)
        if 'error' in metrics:
            return f"ERROR: {metrics['error']}"
        
        # Check consolidation
        is_consolidating, consolidation_score = self.detect_consolidation(metrics)
        
        # Check breakout conditions
        breakout_conditions = self.check_breakout_conditions(df, metrics, symbol)
        
        # Get 24h stats
        stats_24h = self.get_24h_stats(symbol)
        
        # Generate output
        output = f"\n{'='*60}\n"
        output += f"🔴 BINANCE LIVE - LONG TRADE SIGNAL SCANNER\n"
        output += f"Symbol: {symbol.upper()}{'USDT' if not symbol.endswith('USDT') else ''}\n"
        output += f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
        output += f"{'='*60}\n\n"
        
        # Add 24h stats if available
        if stats_24h:
            output += f"📊 24H STATISTICS:\n"
            output += f"├─ 24h Change: {stats_24h['price_change_percent']:.2f}%\n"
            output += f"├─ 24h High: ${stats_24h['high_24h']:.2f}\n"
            output += f"├─ 24h Low: ${stats_24h['low_24h']:.2f}\n"
            output += f"└─ 24h Volume: {stats_24h['volume_24h']:,.0f}\n\n"
        
        # Determine signal
        signal = "NO SIGNAL"
        signal_strength = 0
        
        # Use live price from breakout conditions
        live_price = breakout_conditions['live_price']
        
        if is_consolidating:
            signal = "WAIT - IN CONSOLIDATION"
            output += f"📊 CONSOLIDATION DETECTED (Score: {consolidation_score}/6)\n"
            output += f"├─ Price Range: {metrics['price_range_pct']:.2f}%\n"
            output += f"├─ Live Price: ${live_price:.2f}\n"
            output += f"├─ Resistance: ${metrics['resistance']:.2f}\n"
            output += f"├─ Support: ${metrics['support']:.2f}\n"
            output += f"└─ Wait for breakout above ${metrics['resistance']:.2f}\n\n"
            
        elif breakout_conditions['breakout_above_resistance'] and breakout_conditions['volume_spike']:
            signal = "STRONG BUY SIGNAL"
            signal_strength = 3
            output += f"🚀 STRONG LONG SIGNAL - BREAKOUT DETECTED!\n"
            output += f"├─ Price broke resistance: ${metrics['resistance']:.2f}\n"
            output += f"├─ Live Price: ${live_price:.2f}\n"
            output += f"├─ Volume spike confirmed: {metrics['current_volume']/metrics['volume_mean']:.1f}x average\n"
            output += f"└─ Distance from resistance: +{breakout_conditions['distance_from_resistance']:.2f}%\n\n"
            
        elif breakout_conditions['recent_consolidation'] and breakout_conditions['breakout_above_resistance']:
            signal = "BUY SIGNAL"
            signal_strength = 2
            output += f"✅ LONG SIGNAL - Recent consolidation breakout\n"
            output += f"├─ Price above resistance: ${live_price:.2f}\n"
            output += f"├─ Resistance level: ${metrics['resistance']:.2f}\n"
            output += f"└─ Consider entry with stop at ${metrics['resistance']:.2f}\n\n"
            
        elif not is_consolidating and breakout_conditions['uptrend']:
            signal = "TREND FOLLOWING"
            signal_strength = 1
            output += f"📈 TRENDING MARKET - Look for pullback entry\n"
            output += f"├─ Live Price: ${live_price:.2f}\n"
            output += f"├─ Trend MA: ${breakout_conditions['ma_value']:.2f}\n"
            output += f"└─ Wait for pullback to support levels\n\n"
            
        else:
            output += f"⚠️ NO CLEAR LONG SIGNAL\n"
            output += f"├─ Live Price: ${live_price:.2f}\n"
            output += f"└─ Market conditions unclear\n\n"
        
        # Risk Management
        if signal_strength > 0:
            stop_loss = metrics['support'] if not is_consolidating else metrics['support'] * 0.99
            take_profit_1 = live_price * 1.01  # 1% TP1
            take_profit_2 = live_price * 1.02  # 2% TP2
            
            # Calculate risk-reward ratio
            risk = abs((live_price - stop_loss) / live_price * 100)
            reward1 = abs((take_profit_1 - live_price) / live_price * 100)
            rr_ratio = reward1 / risk if risk > 0 else 0
            
            output += f"📊 RISK MANAGEMENT:\n"
            output += f"├─ Entry: ${live_price:.2f}\n"
            output += f"├─ Stop Loss: ${stop_loss:.2f} (-{risk:.2f}%)\n"
            output += f"├─ TP1 (50%): ${take_profit_1:.2f} (+1.0%)\n"
            output += f"├─ TP2 (50%): ${take_profit_2:.2f} (+2.0%)\n"
            output += f"└─ Risk/Reward: 1:{rr_ratio:.1f}\n\n"
        
        output += f"SIGNAL: {signal}\n"
        output += f"{'='*60}\n"
        
        return output

# Simple functions for easy use
def should_long(symbol: str) -> bool:
    """Returns True if there's a long signal"""
    scanner = CryptoLongTradeScanner()
    result = scanner.generate_long_signal(symbol)
    return "BUY SIGNAL" in result

def get_long_signal(symbol: str) -> str:
    """Get detailed long trade analysis"""
    scanner = CryptoLongTradeScanner()
    return scanner.generate_long_signal(symbol)

def scan_multiple_cryptos(cryptos: list) -> dict:
    """Scan multiple cryptocurrencies and return their signals"""
    scanner = CryptoLongTradeScanner()
    results = {}
    
    for crypto in cryptos:
        try:
            result = scanner.generate_long_signal(crypto)
            if "STRONG BUY SIGNAL" in result:
                results[crypto] = "🚀 STRONG BUY"
            elif "BUY SIGNAL" in result:
                results[crypto] = "✅ BUY"
            elif "WAIT - IN CONSOLIDATION" in result:
                results[crypto] = "📊 CONSOLIDATING"
            elif "TREND FOLLOWING" in result:
                results[crypto] = "📈 TRENDING"
            else:
                results[crypto] = "❌ NO SIGNAL"
        except Exception as e:
            results[crypto] = f"❌ ERROR: {str(e)}"
        
        # Small delay to respect API limits
        time.sleep(0.1)
    
    return results

# Example usage
if __name__ == "__main__":
    # Check single crypto with live Binance data
    print(get_long_signal("BTC"))
    
    # Quick scan multiple cryptos
    # cryptos = ["BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOT"]
    # print("\n🔴 BINANCE LIVE SCAN FOR LONG OPPORTUNITIES:")
    # print("="*50)
    # results = scan_multiple_cryptos(cryptos)
    # for crypto, status in results.items():
    #     print(f"{crypto}: {status}")