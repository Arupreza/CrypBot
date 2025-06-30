import os
import time
import asyncio
import json
import websockets
import csv
from datetime import datetime, timedelta
from dotenv import load_dotenv
from binance.client import Client
from binance.exceptions import BinanceAPIException
import pandas as pd

# Load environment variables
load_dotenv()

class EMACrossDetector:
    def __init__(self):
        self.ema9 = None
        self.ema15 = None
        self.prev_price = None
        self.prev_ema9 = None
        self.prev_ema15 = None
        self.multiplier9 = 2 / (9 + 1)  # 0.2
        self.multiplier15 = 2 / (15 + 1)  # 0.125

    def calculate_ema(self, price, prev_ema, multiplier):
        if prev_ema is None:
            return price
        return (price * multiplier) + (prev_ema * (1 - multiplier))

    def update(self, current_price):
        self.prev_ema9 = self.ema9
        self.prev_ema15 = self.ema15

        self.ema9 = self.calculate_ema(current_price, self.ema9, self.multiplier9)
        self.ema15 = self.calculate_ema(current_price, self.ema15, self.multiplier15)

        cross_info = self.detect_crosses(current_price)

        prev_price_temp = self.prev_price
        self.prev_price = current_price

        return {
            'price': current_price,
            'ema9': self.ema9,
            'ema15': self.ema15,
            'crosses': cross_info
        }

    def detect_crosses(self, current_price):
        crosses = []

        if self.prev_ema9 is None or self.prev_ema15 is None or self.prev_price is None:
            return crosses

        # Price crosses above both EMAs (bullish signal)
        if (self.prev_price <= self.prev_ema9 and self.prev_price <= self.prev_ema15 and
            current_price > self.ema9 and current_price > self.ema15):
            crosses.append({
                'type': 'PRICE_ABOVE_BOTH_EMAS',
                'signal': 'BULLISH',
                'message': f'Price ({current_price:.4f}) crossed ABOVE both EMA9 ({self.ema9:.4f}) and EMA15 ({self.ema15:.4f})',
                'price': current_price,
                'ema9': self.ema9,
                'ema15': self.ema15
            })

        # Price crosses below both EMAs (bearish signal)
        if (self.prev_price >= self.prev_ema9 and self.prev_price >= self.prev_ema15 and
            current_price < self.ema9 and current_price < self.ema15):
            crosses.append({
                'type': 'PRICE_BELOW_BOTH_EMAS',
                'signal': 'BEARISH',
                'message': f'Price ({current_price:.4f}) crossed BELOW both EMA9 ({self.ema9:.4f}) and EMA15 ({self.ema15:.4f})',
                'price': current_price,
                'ema9': self.ema9,
                'ema15': self.ema15
            })

        # EMA9 crosses above EMA15 (golden cross - bullish)
        if self.prev_ema9 <= self.prev_ema15 and self.ema9 > self.ema15:
            crosses.append({
                'type': 'EMA9_ABOVE_EMA15',
                'signal': 'BULLISH',
                'message': f'EMA9 ({self.ema9:.4f}) crossed ABOVE EMA15 ({self.ema15:.4f}) - Golden Cross',
                'price': current_price,
                'ema9': self.ema9,
                'ema15': self.ema15
            })

        # EMA9 crosses below EMA15 (death cross - bearish)
        if self.prev_ema9 >= self.prev_ema15 and self.ema9 < self.ema15:
            crosses.append({
                'type': 'EMA9_BELOW_EMA15',
                'signal': 'BEARISH',
                'message': f'EMA9 ({self.ema9:.4f}) crossed BELOW EMA15 ({self.ema15:.4f}) - Death Cross',
                'price': current_price,
                'ema9': self.ema9,
                'ema15': self.ema15
            })

        return crosses

    def reset(self):
        self.ema9 = None
        self.ema15 = None
        self.prev_price = None
        self.prev_ema9 = None
        self.prev_ema15 = None


class BinanceEMAAnalyzer:
    def __init__(self):
        # Get API credentials from environment variables
        self.api_key = os.getenv('BINANCE_API_KEY')
        self.api_secret = os.getenv('BINANCE_API_SECRET')
        
        if not self.api_key or not self.api_secret:
            raise ValueError("Please set BINANCE_API_KEY and BINANCE_API_SECRET in your .env file")
        
        # Initialize Binance client
        self.client = Client(self.api_key, self.api_secret)
        self.detector = EMACrossDetector()
        self.current_symbol = None
        self.is_running = False
        self.csv_filename = None
        self.start_time = None
        self.end_time = None
        self.signal_count = 0
        
    def create_csv_file(self, symbol_pair):
        """Create CSV file for logging candle data"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.csv_filename = f"ema_analysis_{symbol_pair}_{timestamp}.csv"
        
        # Create CSV with headers
        with open(self.csv_filename, 'w', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerow([
                'Timestamp', 'Symbol', 'Close_Price', 'EMA9', 'EMA15', 
                'Price_Above_EMA9', 'Price_Above_EMA15', 'Price_Above_Both_EMAs',
                'EMA9_Above_EMA15', 'Signal_Type'
            ])
        
        print(f"📝 CSV file created: {self.csv_filename}")
        return self.csv_filename
    
    def log_candle_to_csv(self, symbol_pair, result, timestamp):
        """Log every closed candle data to CSV file"""
        if not self.csv_filename:
            return
        
        try:
            price = result['price']
            ema9 = result['ema9']
            ema15 = result['ema15']
            
            # Check conditions
            price_above_ema9 = price > ema9
            price_above_ema15 = price > ema15
            price_above_both = price_above_ema9 and price_above_ema15
            ema9_above_ema15 = ema9 > ema15
            
            # Determine signal type
            signal_type = "NEUTRAL"
            if price_above_both and ema9_above_ema15:
                signal_type = "STRONG_BULLISH"
                self.signal_count += 1
            elif price_above_both:
                signal_type = "BULLISH_PRICE"
                self.signal_count += 1
            elif ema9_above_ema15:
                signal_type = "BULLISH_TREND"
            elif price < ema9 and price < ema15:
                signal_type = "BEARISH"
            
            with open(self.csv_filename, 'a', newline='', encoding='utf-8') as file:
                writer = csv.writer(file)
                writer.writerow([
                    timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                    symbol_pair,
                    f"{price:.4f}",
                    f"{ema9:.4f}",
                    f"{ema15:.4f}",
                    price_above_ema9,
                    price_above_ema15,
                    price_above_both,
                    ema9_above_ema15,
                    signal_type
                ])
            
            # Special logging for price above both EMAs
            if price_above_both:
                print(f"💾 Candle closed above both EMAs - Logged to CSV (Entry #{self.signal_count})")
            
        except Exception as e:
            print(f"❌ Error logging to CSV: {e}")
        
    def validate_symbol(self, symbol):
        """Validate if the symbol exists on Binance"""
        try:
            symbol_pair = f"{symbol.upper()}USDT"
            ticker = self.client.get_symbol_ticker(symbol=symbol_pair)
            return symbol_pair, float(ticker['price'])
        except BinanceAPIException as e:
            print(f"❌ Error: Symbol {symbol}USDT not found or invalid")
            return None, None
    
    def get_historical_data(self, symbol_pair, limit=50):
        """Get historical kline data for EMA initialization"""
        try:
            klines = self.client.get_klines(
                symbol=symbol_pair,
                interval=Client.KLINE_INTERVAL_15MINUTE,
                limit=limit
            )
            
            historical_data = []
            for kline in klines:
                historical_data.append({
                    'timestamp': kline[0],
                    'open': float(kline[1]),
                    'high': float(kline[2]),
                    'low': float(kline[3]),
                    'close': float(kline[4]),
                    'volume': float(kline[5])
                })
            
            return historical_data
        except BinanceAPIException as e:
            print(f"❌ Error fetching historical data: {e}")
            return None

    def initialize_emas(self, symbol_pair):
        """Initialize EMAs with historical data"""
        print(f"📊 Initializing EMAs for {symbol_pair}...")
        
        historical_data = self.get_historical_data(symbol_pair)
        if not historical_data:
            return False
        
        self.detector.reset()
        
        for candle in historical_data:
            self.detector.update(candle['close'])
        
        print(f"✅ EMAs initialized with {len(historical_data)} historical candles")
        print(f"📈 Current EMA9: {self.detector.ema9:.4f}")
        print(f"📈 Current EMA15: {self.detector.ema15:.4f}")
        
        return True

    def get_duration_input(self):
        """Get analysis duration from user"""
        print("\n⏰ Duration Options:")
        print("1. 1 hour")
        print("2. 6 hours")
        print("3. 12 hours") 
        print("4. 24 hours")
        print("5. Custom (enter hours)")
        
        while True:
            choice = input("\n👉 Select duration (1-5): ").strip()
            
            if choice == '1':
                return 1
            elif choice == '2':
                return 6
            elif choice == '3':
                return 12
            elif choice == '4':
                return 24
            elif choice == '5':
                try:
                    hours = float(input("Enter hours (e.g., 0.5 for 30 minutes): "))
                    if hours > 0:
                        return hours
                    else:
                        print("❌ Please enter a positive number")
                except ValueError:
                    print("❌ Please enter a valid number")
            else:
                print("❌ Invalid choice. Please select 1-5")

    def check_time_limit(self):
        """Check if analysis should continue based on time limit"""
        if self.end_time and datetime.now() >= self.end_time:
            return False
        return True

    def display_session_info(self, symbol_pair, duration_hours):
        """Display session information"""
        self.start_time = datetime.now()
        self.end_time = self.start_time + timedelta(hours=duration_hours)
        
        print(f"\n📋 ANALYSIS SESSION INFO")
        print(f"{'='*50}")
        print(f"🎯 Symbol: {symbol_pair}")
        print(f"⏰ Duration: {duration_hours} hour(s)")
        print(f"🕐 Start Time: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"🏁 End Time: {self.end_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"📊 Timeframe: 15-minute candles")
        print(f"📈 Indicators: EMA9, EMA15")
        print(f"📝 CSV File: {self.csv_filename}")
        print(f"{'='*50}")

    def display_progress(self):
        """Display analysis progress"""
        if self.start_time and self.end_time:
            now = datetime.now()
            total_duration = self.end_time - self.start_time
            elapsed = now - self.start_time
            remaining = self.end_time - now
            
            progress_percent = (elapsed.total_seconds() / total_duration.total_seconds()) * 100
            
            print(f"\n📊 PROGRESS UPDATE")
            print(f"⏱️  Elapsed: {str(elapsed).split('.')[0]}")
            print(f"⏳ Remaining: {str(remaining).split('.')[0]}")
            print(f"📈 Progress: {progress_percent:.1f}%")
            print(f"🚨 Candles Above Both EMAs: {self.signal_count}")

    async def websocket_handler(self, symbol_pair):
        """Handle WebSocket connection for real-time data"""
        stream_name = f"{symbol_pair.lower()}@kline_15m"
        url = f"wss://stream.binance.com:9443/ws/{stream_name}"
        
        print(f"🔌 Connecting to WebSocket: {url}")
        
        try:
            async with websockets.connect(url) as websocket:
                print(f"✅ Connected to {symbol_pair} 15m kline stream")
                
                # Display progress every 30 minutes
                last_progress_update = datetime.now()
                
                async for message in websocket:
                    if not self.is_running or not self.check_time_limit():
                        print(f"\n⏰ Analysis time completed!")
                        break
                        
                    data = json.loads(message)
                    kline = data['k']
                    
                    # Only process closed candles
                    if kline['x']:  # is_closed
                        close_price = float(kline['c'])
                        close_time = datetime.fromtimestamp(kline['T'] / 1000)
                        
                        result = self.detector.update(close_price)
                        
                        # Log every candle to CSV
                        self.log_candle_to_csv(symbol_pair, result, close_time)
                        
                        # Display current status
                        self.display_status(symbol_pair, result, close_time)
                        
                        # Check for crosses and alerts (optional display)
                        if result['crosses']:
                            self.handle_alerts(symbol_pair, result['crosses'], close_time)
                    
                    # Show progress update every 30 minutes
                    if datetime.now() - last_progress_update >= timedelta(minutes=30):
                        self.display_progress()
                        last_progress_update = datetime.now()
                        
        except Exception as e:
            print(f"❌ WebSocket error: {e}")

    def display_status(self, symbol_pair, result, timestamp):
        """Display current market status"""
        trend = "🟢 BULLISH" if result['ema9'] > result['ema15'] else "🔴 BEARISH"
        
        print(f"\n{'='*60}")
        print(f"🕐 {timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"💰 {symbol_pair}: ${result['price']:.4f}")
        print(f"📊 EMA9: {result['ema9']:.4f} | EMA15: {result['ema15']:.4f}")
        print(f"📈 Trend: {trend}")
        
        # Show time remaining
        if self.end_time:
            remaining = self.end_time - datetime.now()
            print(f"⏳ Time Remaining: {str(remaining).split('.')[0]}")
        
        print(f"🚨 Candles Above Both EMAs: {self.signal_count}")
        print(f"{'='*60}")

    def handle_alerts(self, symbol_pair, crosses, timestamp):
        """Handle and display trading alerts"""
        for cross in crosses:
            signal_emoji = "🚀" if cross['signal'] == 'BULLISH' else "⚠️"
            
            print(f"\n{signal_emoji} TRADING ALERT #{self.signal_count + 1} {signal_emoji}")
            print(f"Time: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"Symbol: {symbol_pair}")
            print(f"Signal: {cross['signal']}")
            print(f"Message: {cross['message']}")
            print(f"{'🚀' if cross['signal'] == 'BULLISH' else '📉'} Recommendation: {'CONSIDER BUYING' if cross['signal'] == 'BULLISH' else 'CONSIDER SELLING'}")
            
            # Log to CSV (no longer needed here as we log every candle)
            # self.log_signal_to_csv(symbol_pair, cross, timestamp)
            
            print("="*60)

    def start_analysis(self, symbol, duration_hours):
        """Start the EMA analysis for a given symbol and duration"""
        # Validate symbol
        symbol_pair, current_price = self.validate_symbol(symbol)
        if not symbol_pair:
            return
        
        # Create CSV file
        self.create_csv_file(symbol_pair)
        
        print(f"🎯 Starting analysis for {symbol_pair}")
        print(f"💵 Current price: ${current_price:.4f}")
        
        # Initialize EMAs
        if not self.initialize_emas(symbol_pair):
            print("❌ Failed to initialize EMAs")
            return
        
        # Display session info
        self.display_session_info(symbol_pair, duration_hours)
        
        self.current_symbol = symbol_pair
        self.is_running = True
        self.signal_count = 0
        
        # Start WebSocket connection
        try:
            asyncio.run(self.websocket_handler(symbol_pair))
        except KeyboardInterrupt:
            print("\n⏹️  Analysis stopped by user")
        except Exception as e:
            print(f"❌ Error during analysis: {e}")
        finally:
            self.is_running = False
            self.display_final_summary()

    def display_final_summary(self):
        """Display final analysis summary"""
        if not self.start_time:
            return
            
        end_time = datetime.now()
        total_duration = end_time - self.start_time
        
        print(f"\n📊 ANALYSIS SUMMARY")
        print(f"{'='*50}")
        print(f"🎯 Symbol: {self.current_symbol}")
        print(f"🕐 Start Time: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"🏁 End Time: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"⏱️  Total Duration: {str(total_duration).split('.')[0]}")
        print(f"🚨 Total Candles Above Both EMAs: {self.signal_count}")
        print(f"📝 CSV File: {self.csv_filename}")
        
        if self.csv_filename and os.path.exists(self.csv_filename):
            file_size = os.path.getsize(self.csv_filename)
            print(f"📁 File Size: {file_size} bytes")
        
        print(f"{'='*50}")
        
        if self.signal_count > 0:
            print(f"✅ Analysis completed successfully!")
            print(f"📋 Found {self.signal_count} candles that closed above both EMAs")
            print(f"📋 Check {self.csv_filename} for complete candle data")
        else:
            print(f"ℹ️  No candles closed above both EMAs during this period")

    def stop_analysis(self):
        """Stop the current analysis"""
        self.is_running = False
        print("⏹️  Stopping analysis...")

    def get_account_info(self):
        """Get account information (optional feature)"""
        try:
            account = self.client.get_account()
            print(f"📊 Account Status: {account['accountType']}")
            print(f"💼 Can Trade: {account['canTrade']}")
            return account
        except BinanceAPIException as e:
            print(f"❌ Error getting account info: {e}")
            return None


def main():
    """Main interactive function"""
    print("🚀 Binance EMA Cross Analyzer with CSV Logging")
    print("=" * 50)
    
    try:
        analyzer = BinanceEMAAnalyzer()
        print("✅ Binance API connection established")
        
    except Exception as e:
        print(f"❌ Failed to initialize: {e}")
        print("Please check your .env file contains:")
        print("BINANCE_API_KEY=your_api_key_here")
        print("BINANCE_API_SECRET=your_api_secret_here")
        return
    
    while True:
        print("\n" + "="*50)
        print("📋 Options:")
        print("1. Start EMA analysis")
        print("2. Exit")
        
        choice = input("\n👉 Enter your choice (1-2): ").strip()
        
        if choice == '1':
            # Get symbol input
            symbol = input("💰 Enter coin symbol (e.g., BTC, ETH, ADA): ").strip().upper()
            if not symbol:
                print("❌ Please enter a valid symbol")
                continue
            
            # Get duration input
            duration = analyzer.get_duration_input()
            
            print(f"\n🎯 Starting analysis for {symbol}USDT...")
            print(f"⏰ Duration: {duration} hour(s)")
            print("📊 Using 15-minute candles with EMA9 and EMA15")
            print("💾 Every candle will be saved to CSV file")
            print("🎯 Special focus on candles closing above both EMAs")
            print("⏹️  Press Ctrl+C to stop analysis early\n")
            
            analyzer.start_analysis(symbol, duration)
                
        elif choice == '2':
            print("👋 Goodbye!")
            break
        else:
            print("❌ Invalid choice. Please try again.")


if __name__ == "__main__":
    main()