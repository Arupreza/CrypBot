import requests
import pandas as pd
import numpy as np
from datetime import datetime
import time

class BTCTrendAnalyzer:
    def __init__(self, symbol="BTCUSDT", interval="15m", limit=50):
        self.base_url = "https://api.binance.com/api/v3"
        self.symbol = symbol
        self.interval = interval
        self.limit = limit
        self.retry_attempts = 3
        self.retry_delay = 5  # seconds

    def get_klines(self):
        """
        Fetch candlestick data from Binance API with retry logic
        """
        url = f"{self.base_url}/klines"
        params = {
            'symbol': self.symbol,
            'interval': self.interval,
            'limit': self.limit
        }

        for attempt in range(self.retry_attempts):
            try:
                response = requests.get(url, params=params)
                response.raise_for_status()
                data = response.json()

                # Convert to DataFrame
                df = pd.DataFrame(data, columns=[
                    'timestamp', 'open', 'high', 'low', 'close', 'volume',
                    'close_time', 'quote_asset_volume', 'number_of_trades',
                    'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'
                ])

                # Convert to proper data types
                numeric_cols = ['open', 'high', 'low', 'close', 'volume',
                            'quote_asset_volume', 'taker_buy_base_asset_volume',
                            'taker_buy_quote_asset_volume']
                df[numeric_cols] = df[numeric_cols].astype(float)
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                df['close_time'] = pd.to_datetime(df['close_time'], unit='ms')

                return df

            except requests.exceptions.HTTPError as e:
                if response.status_code == 429:  # Rate limit exceeded
                    time.sleep(self.retry_delay * (2 ** attempt))  # Exponential backoff
                else:
                    return None
            except Exception:
                return None
        return None

    def calculate_ema(self, data, period):
        """Calculate Exponential Moving Average"""
        return data.ewm(span=period, adjust=False).mean()

    def calculate_rsi(self, data, period=14):
        """Calculate RSI with division-by-zero protection"""
        delta = data.diff()
        gain = delta.where(delta > 0, 0).rolling(window=period).mean()
        loss = -delta.where(delta < 0, 0).rolling(window=period).mean()
        rs = gain / (loss + 1e-10)  # Add small constant to avoid division by zero
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def calculate_macd(self, data, fast=12, slow=26, signal=9):
        """Calculate MACD"""
        ema_fast = self.calculate_ema(data, fast)
        ema_slow = self.calculate_ema(data, slow)
        macd = ema_fast - ema_slow
        signal_line = self.calculate_ema(macd, signal)
        histogram = macd - signal_line
        return macd, signal_line, histogram

    def analyze_trend(self):
        """
        Analyze trend and return UP or DOWN
        """
        df = self.get_klines()
        if df is None:
            return "ERROR"

        # Calculate indicators
        df['ema_9'] = self.calculate_ema(df['close'], 9)
        df['ema_21'] = self.calculate_ema(df['close'], 21)
        df['rsi'] = self.calculate_rsi(df['close'])
        macd, signal, histogram = self.calculate_macd(df['close'])
        df['macd'] = macd
        df['macd_signal'] = signal
        df['macd_histogram'] = histogram

        # Get latest and previous values
        latest = df.iloc[-1]
        prev = df.iloc[-2]

        # Scoring system
        score = 0

        # 1. EMA Crossover (Weight: 3)
        score += 3 if latest['ema_9'] > latest['ema_21'] else -3

        # 2. Price vs EMA (Weight: 2)
        score += 2 if latest['close'] > latest['ema_9'] else -2

        # 3. MACD Signal (Weight: 2)
        score += 2 if latest['macd'] > latest['macd_signal'] else -2

        # 4. MACD Momentum (Weight: 1)
        score += 1 if latest['macd_histogram'] > prev['macd_histogram'] else -1

        # 5. RSI Momentum (Weight: 1)
        if 30 < latest['rsi'] < 70:
            score += 1 if latest['rsi'] > prev['rsi'] else -1
        elif latest['rsi'] > 70:  # Overbought
            score -= 2
        elif latest['rsi'] < 30:  # Oversold
            score += 2

        # 6. Price momentum (Weight: 1)
        score += 1 if latest['close'] > prev['close'] else -1

        # 7. Volume confirmation (Weight: 1)
        avg_volume = df['volume'].tail(10).mean()
        if latest['volume'] > avg_volume:
            score += 1 if latest['close'] > prev['close'] else -1

        return "UP" if score > 0 else "DOWN"
    
def out_trend():
    analyzer = BTCTrendAnalyzer()
    trend = analyzer.analyze_trend()
    return trend