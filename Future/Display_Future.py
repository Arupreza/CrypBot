import pandas as pd
import requests
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from matplotlib.dates import DateFormatter
import numpy as np
from datetime import datetime, timedelta
import warnings
from scipy import stats
import threading
import time
warnings.filterwarnings('ignore')

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
            'JTO': 'JTOUSDT'
        }
        
        # If it's a simple symbol, convert to USDT pair
        if symbol in symbol_map:
            return symbol_map[symbol]
        
        # If it doesn't end with USDT, BUSD, etc., assume it needs USDT
        if not any(symbol.endswith(quote) for quote in ['USDT', 'BUSD', 'USDC']):
            return f"{symbol}USDT"
        
        return symbol
    
    def get_ticker(self, symbol):
        """Get current ticker data"""
        try:
            symbol = self._format_symbol(symbol)
            url = f"{self.base_url}/fapi/v1/ticker/24hr"
            params = {'symbol': symbol.upper()}
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            ticker = {
                'last': float(data['lastPrice']),
                'percentage': float(data['priceChangePercent'])
            }
            return ticker
            
        except requests.RequestException as e:
            print(f"❌ Error fetching ticker for {symbol}: {e}")
            return None
    
    def get_klines(self, symbol, interval='1h', limit=100):
        """Get candlestick data for perpetual futures"""
        try:
            symbol = self._format_symbol(symbol)
            url = f"{self.base_url}/fapi/v1/klines"
            params = {
                'symbol': symbol.upper(),
                'interval': interval,
                'limit': limit
            }
            
            response = requests.get(url, params=params, timeout=15)
            response.raise_for_status()
            
            data = response.json()
            if not data:
                return None
            
            # Convert to CCXT-like OHLCV format
            ohlcv = []
            for candle in data:
                ohlcv.append([
                    int(candle[0]),  # timestamp
                    float(candle[1]),  # open
                    float(candle[2]),  # high
                    float(candle[3]),  # low
                    float(candle[4]),  # close
                    float(candle[5])   # volume
                ])
            
            return ohlcv
            
        except requests.RequestException as e:
            print(f"❌ Error fetching klines for {symbol}: {e}")
            return None

def calculate_atr(df: pd.DataFrame, length: int = 1) -> pd.Series:
    """Calculate Average True Range (ATR). Returns a pd.Series."""
    high_low = df['high'] - df['low']
    high_close_prev = (df['high'] - df['close'].shift()).abs()
    low_close_prev = (df['low'] - df['close'].shift()).abs()

    true_range = pd.concat([high_low, high_close_prev, low_close_prev], axis=1).max(axis=1)
    atr = true_range.rolling(window=length).mean()
    return atr

def chandelier_exit(df: pd.DataFrame, atr_period: int = 1, atr_multiplier: float = 2.0, use_close: bool = True) -> pd.DataFrame:
    """Calculate Chandelier Exit with accurate signals and smoothing"""
    df_result = df.copy()

    # Compute ATR
    atr_raw = calculate_atr(df, length=atr_period)
    atr = atr_raw * atr_multiplier

    # Compute rolling highest/lowest
    if use_close:
        highest = df['close'].rolling(window=atr_period).max()
        lowest = df['close'].rolling(window=atr_period).min()
    else:
        highest = df['high'].rolling(window=atr_period).max()
        lowest = df['low'].rolling(window=atr_period).min()

    n = len(df)
    long_stop_array = np.full(n, np.nan)
    short_stop_array = np.full(n, np.nan)
    direction_array = np.full(n, 1)

    for i in range(n):
        if pd.isna(atr.iloc[i]) or pd.isna(highest.iloc[i]) or pd.isna(lowest.iloc[i]):
            continue

        curr_long = highest.iloc[i] - atr.iloc[i]
        curr_short = lowest.iloc[i] + atr.iloc[i]

        if i == 0:
            long_stop_array[i] = curr_long
            short_stop_array[i] = curr_short
            direction_array[i] = 1
        else:
            prev_long = long_stop_array[i - 1] if not pd.isna(long_stop_array[i - 1]) else curr_long
            if df['close'].iloc[i - 1] > prev_long:
                long_stop_array[i] = max(curr_long, prev_long)
            else:
                long_stop_array[i] = curr_long

            prev_short = short_stop_array[i - 1] if not pd.isna(short_stop_array[i - 1]) else curr_short
            if df['close'].iloc[i - 1] < prev_short:
                short_stop_array[i] = min(curr_short, prev_short)
            else:
                short_stop_array[i] = curr_short

            prev_short_val = short_stop_array[i - 1] if not pd.isna(short_stop_array[i - 1]) else curr_short
            prev_long_val = long_stop_array[i - 1] if not pd.isna(long_stop_array[i - 1]) else curr_long

            if df['close'].iloc[i] > prev_short_val:
                direction_array[i] = 1
            elif df['close'].iloc[i] < prev_long_val:
                direction_array[i] = -1
            else:
                direction_array[i] = direction_array[i - 1]

    df_result['atr'] = atr
    df_result['long_stop'] = long_stop_array
    df_result['short_stop'] = short_stop_array
    df_result['direction'] = direction_array
    df_result['chandelier_exit'] = np.where(direction_array == 1, long_stop_array, short_stop_array)
    
    # Apply smoothing to reduce noise
    df_result['direction_smooth'] = df_result['direction'].rolling(window=3, center=True).apply(
        lambda x: 1 if x.mean() > 0 else -1, raw=False
    ).fillna(df_result['direction'])
    
    df_result['buy_signal'] = (df_result['direction_smooth'] == 1).astype(int)
    df_result['sell_signal'] = (df_result['direction_smooth'] == -1).astype(int)

    return df_result

def calculate_chandelier_data(df, atr_period=1, atr_multiplier=2.0):
    """Calculate Chandelier Exit on the dataframe"""
    df_result = chandelier_exit(df, atr_period=atr_period, atr_multiplier=atr_multiplier)
    return df_result

class RealTimeTradeTracker:
    def __init__(self, csv_file_path):
        self.csv_file_path = csv_file_path
        self.fetcher = BinancePerpetualFetcher()
        self.fig = None
        self.ax1 = None
        self.ax2 = None
        self.ax3 = None
        self.lines = {}
        self.hlines = {}
        self.bars = None
        self.is_running = False
        self.trade_data = None
        self.current_price = None
        self.historical_data = None
        self.btc_chandelier_data = None
        self.update_count = 0
        
        # Initialize trade data
        self.load_trade_data()
        
    def load_trade_data(self):
        """Load trade data from CSV"""
        try:
            df = pd.read_csv(self.csv_file_path)
            
            entry_trades = df[df['Action'] == 'ENTRY']
            
            if entry_trades.empty:
                return False
            
            # Get the last entry trade
            trade = entry_trades.iloc[-1]
            
            self.trade_data = {
                'symbol': trade['Symbol'],
                'entry_price': float(trade['Entry_Price']),
                'quantity': float(trade['Quantity']),
                'notional_usd': float(trade['Notional_USD']),
                'margin_used': float(trade['Margin_Used']),
                'leverage': float(trade['Leverage']),
                'stop_loss': float(trade['Stop_Loss']) if pd.notna(trade['Stop_Loss']) else None,
                'take_profit': float(trade['Take_Profit']) if pd.notna(trade['Take_Profit']) else None,
                'side': trade['Side'],
                'entry_date': trade['Date'],
                'entry_time': trade['Time'],
                'coin_symbol': trade['Coin'].replace('/', '') if '/' in trade['Coin'] else trade['Coin']
            }
            
            return True
            
        except Exception as e:
            print(f"❌ Error loading trade data: {e}")
            return False
    
    def fetch_live_data(self):
        """Fetch live price data"""
        try:
            if not self.trade_data:
                return False
                
            # Get current price
            formatted_symbol = self.trade_data['symbol'].replace('/', '')
            
            ticker = self.fetcher.get_ticker(formatted_symbol)
            
            if ticker:
                self.current_price = ticker['last']
                
                # Fetch historical data
                ohlcv = self.fetcher.get_klines(formatted_symbol, '1h', 100)
                if ohlcv:
                    self.historical_data = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                    self.historical_data['datetime'] = pd.to_datetime(self.historical_data['timestamp'], unit='ms')
                else:
                    return False
                
                # Fetch BTC data
                btc_ohlcv = self.fetcher.get_klines('BTCUSDT', '15m', 200)
                if btc_ohlcv:
                    btc_data = pd.DataFrame(btc_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                    btc_data['datetime'] = pd.to_datetime(btc_data['timestamp'], unit='ms')
                    self.btc_chandelier_data = calculate_chandelier_data(btc_data, atr_period=1, atr_multiplier=2.0)
                
                self.update_count += 1
                return True
            else:
                return False
            
        except Exception as e:
            print(f"❌ Error fetching live data: {e}")
            return False
    
    def setup_plot(self):
        """Setup the initial plot structure"""
        plt.style.use('dark_background')
        
        self.fig, (self.ax1, self.ax2, self.ax3) = plt.subplots(3, 1, figsize=(16, 12), 
                                                        gridspec_kw={'height_ratios': [2, 1, 1]})
        
        self.fig.suptitle(f'{self.trade_data["symbol"]} - {self.trade_data["side"].upper()} {self.trade_data["leverage"]}x Real-Time Trade Tracker', 
                         fontsize=16, fontweight='bold', color='white')
        
        # Setup main price chart
        self.ax1.set_ylabel(f'{self.trade_data["symbol"]} Price (USDT)', fontsize=12, fontweight='bold')
        self.ax1.set_title(f'{self.trade_data["symbol"]} Price Movement - LIVE UPDATE', fontsize=14)
        self.ax1.grid(True, alpha=0.3)
        
        # Setup BTC chart
        self.ax2.set_ylabel('BTC Price (USDT)', fontsize=12, fontweight='bold')
        self.ax2.set_title('Bitcoin Price Movement', fontsize=12)
        self.ax2.grid(True, alpha=0.3)
        
        # Setup Chandelier chart
        self.ax3.set_ylabel('BTC Chandelier Direction', fontsize=12, fontweight='bold')
        self.ax3.set_xlabel('Time', fontsize=12)
        self.ax3.set_title('BTC Chandelier Exit Direction (Green=Buy, Red=Sell)', fontsize=12)
        self.ax3.set_ylim(-1.5, 1.5)
        self.ax3.grid(True, alpha=0.3)
        self.ax3.axhline(y=0, color='white', linewidth=0.5)
        
        # Initialize empty lines
        self.lines['price'], = self.ax1.plot([], [], color='#00ff41', linewidth=2.5, label=f'{self.trade_data["symbol"]} Price')
        self.lines['btc'], = self.ax2.plot([], [], color='#F7931A', linewidth=2.5, label='BTC Price')
        
        # Add horizontal lines for trade levels
        self.hlines['entry'] = self.ax1.axhline(y=self.trade_data['entry_price'], color='blue', linestyle='--', 
                                               linewidth=2, label=f'Entry: ${self.trade_data["entry_price"]:.6f}', alpha=0.8)
        
        if self.trade_data['stop_loss']:
            self.hlines['sl'] = self.ax1.axhline(y=self.trade_data['stop_loss'], color='red', linestyle='--', 
                                                linewidth=2, label=f'Stop Loss: ${self.trade_data["stop_loss"]:.6f}', alpha=0.8)
        
        if self.trade_data['take_profit']:
            self.hlines['tp'] = self.ax1.axhline(y=self.trade_data['take_profit'], color='green', linestyle='--', 
                                                linewidth=2, label=f'Take Profit: ${self.trade_data["take_profit"]:.6f}', alpha=0.8)
        
        # Current price line removed per user request
        
        # Add legends
        self.ax1.legend(loc='upper left', fontsize=16, framealpha=0.9)
        self.ax2.legend(loc='upper left', fontsize=16, framealpha=0.9)
        
        # Format axes
        self.ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'${x:.6f}'))
        self.ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'${x:,.0f}'))
        
        plt.tight_layout()
        
    def update_plot(self, frame):
        """Update plot with new data - called by animation"""
        if not self.is_running:
            return
            
        # Fetch new data
        if not self.fetch_live_data():
            return
        
        if self.historical_data is not None and len(self.historical_data) > 0 and self.current_price is not None:
            # Update main price line
            self.lines['price'].set_data(self.historical_data['datetime'], self.historical_data['close'])
            
            # Current price line removed
            
            # Auto-scale y-axis for better visibility
            prices = self.historical_data['close'].tolist() + [self.current_price]
            if self.trade_data['stop_loss']:
                prices.append(self.trade_data['stop_loss'])
            if self.trade_data['take_profit']:
                prices.append(self.trade_data['take_profit'])
            
            price_min, price_max = min(prices), max(prices)
            padding = (price_max - price_min) * 0.1
            self.ax1.set_ylim(price_min - padding, price_max + padding)
            
            # Update x-axis
            self.ax1.set_xlim(self.historical_data['datetime'].min(), self.historical_data['datetime'].max())
            
        # Update BTC data
        if self.btc_chandelier_data is not None and len(self.btc_chandelier_data) > 0:
            # Update BTC price line
            self.lines['btc'].set_data(self.btc_chandelier_data['datetime'], self.btc_chandelier_data['close'])
            
            # Auto-scale BTC y-axis
            btc_min, btc_max = self.btc_chandelier_data['close'].min(), self.btc_chandelier_data['close'].max()
            btc_padding = (btc_max - btc_min) * 0.05
            self.ax2.set_ylim(btc_min - btc_padding, btc_max + btc_padding)
            self.ax2.set_xlim(self.btc_chandelier_data['datetime'].min(), self.btc_chandelier_data['datetime'].max())
            
            # Update Chandelier direction bars
            self.ax3.clear()
            direction_colors = ['red' if d == -1 else 'green' for d in self.btc_chandelier_data['direction_smooth']]
            self.ax3.bar(self.btc_chandelier_data['datetime'], self.btc_chandelier_data['direction_smooth'], 
                        color=direction_colors, alpha=0.7, width=pd.Timedelta(minutes=15))
            self.ax3.set_ylabel('BTC Chandelier Direction', fontsize=12, fontweight='bold')
            self.ax3.set_xlabel('Time', fontsize=12)
            self.ax3.set_title('BTC Chandelier Exit Direction (Green=Buy, Red=Sell)', fontsize=12)
            self.ax3.set_ylim(-1.5, 1.5)
            self.ax3.grid(True, alpha=0.3)
            self.ax3.axhline(y=0, color='white', linewidth=0.5)
            
        # Update title with current stats
        if self.current_price:
            price_change = ((self.current_price - self.trade_data['entry_price']) / self.trade_data['entry_price']) * 100
            if self.trade_data['side'].lower() == 'long':
                pnl_percent = price_change * self.trade_data['leverage']
            else:
                pnl_percent = -price_change * self.trade_data['leverage']
            
            status = "🟢 PROFIT" if pnl_percent > 0 else "🔴 LOSS"
            self.fig.suptitle(f'{self.trade_data["symbol"]} - {self.trade_data["side"].upper()} {self.trade_data["leverage"]}x | {status} {pnl_percent:+.2f}% | ${self.current_price:.6f}', 
                             fontsize=16, fontweight='bold', color='green' if pnl_percent > 0 else 'red')
        
        # Redraw legend with updated current price
        self.ax1.legend(loc='upper left', fontsize=16, framealpha=0.9)
        
        return [self.lines['price'], self.lines['btc']]
    
    def start_tracking(self, update_interval=5000):  # 5 seconds
        """Start real-time tracking"""
        if not self.trade_data:
            print("❌ No trade data available")
            return
            
        print(f"🚀 Starting real-time tracking for {self.trade_data['symbol']}")
        print(f"📊 Updates every {update_interval/1000} seconds")
        print("🎯 Close the plot window to stop tracking")
        
        # Initial data fetch
        print("📡 Performing initial data fetch...")
        if not self.fetch_live_data():
            print("❌ Initial data fetch failed!")
            return
            
        self.is_running = True
        self.setup_plot()
        
        # Initial plot update
        self.update_plot(0)
        
        # Create animation
        ani = animation.FuncAnimation(
            self.fig, 
            self.update_plot, 
            interval=update_interval,
            blit=False,
            cache_frame_data=False
        )
        
        try:
            plt.show()
        except KeyboardInterrupt:
            pass
        finally:
            self.is_running = False

def track_perpetual_trade_realtime(CSV_PATH, update_interval=5):
    """
    Start real-time perpetual trade tracking with smooth updates
    
    Args:
        csv_path (str): Path to your trades CSV file
        update_interval (int): Update interval in seconds (default: 5)
    """
    tracker = RealTimeTradeTracker(CSV_PATH)
    tracker.start_tracking(update_interval * 1000)  # Convert to milliseconds

# Alternative function for single update (non-real-time)
def display_trade_snapshot(csv_file_path):
    """
    Display a single snapshot of the trade (non-updating version)
    """
    tracker = RealTimeTradeTracker(csv_file_path)
    if tracker.load_trade_data() and tracker.fetch_live_data():
        tracker.setup_plot()
        tracker.update_plot(0)  # Single update
        plt.show()
    else:
        print("❌ Could not load trade data or fetch live prices")

# Usage examples:
# For real-time tracking: track_perpetual_trade_realtime('your_trades.csv', update_interval=5)
# For single snapshot: display_trade_snapshot('your_trades.csv')