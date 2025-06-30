import ccxt
import pandas as pd
import pandas_ta as ta
import time
import logging
from datetime import datetime
import os
from dotenv import load_dotenv
import threading
import math

# For live display
try:
    from IPython.display import clear_output
    JUPYTER_ENV = True
except ImportError:
    JUPYTER_ENV = False
    def clear_output():
        # For terminal/console
        os.system('cls' if os.name == 'nt' else 'clear')

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
API_KEY = os.getenv('BINANCE_API_KEY')
API_SECRET = os.getenv('BINANCE_API_SECRET')

class AutoTrader:
    def __init__(self, reports_folder_path="./home/lisa/Arupreza/LiveBot/"):
        """Initialize auto trader with reports folder path"""
        # Initialize exchange with proper settings
        self.exchange = ccxt.binance({
            'enableRateLimit': True,
            'rateLimit': 100,  # Reduced rate limit for faster execution
            'options': {'defaultType': 'spot'},
            'apiKey': API_KEY,
            'secret': API_SECRET,
            'timeout': 10000,  # 10 second timeout
            'sandbox': False  # Make sure not in sandbox mode
        })
        
        # Test connection immediately
        try:
            self.exchange.load_markets()
            balance = self.exchange.fetch_balance()
            logger.info("✅ Connected to Binance successfully!")
            logger.info(f"💰 USDT Balance: ${balance['USDT']['free']:.2f}")
        except Exception as e:
            logger.error(f"❌ Connection failed: {e}")
            return
        
        # Trading parameters
        self.timeframe = '15m'
        
        # Reports folder path
        self.reports_folder = reports_folder_path
        self._create_reports_folder()
        
        # Track active positions
        self.positions = {}
        
        # Start monitoring
        self.monitoring = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()
        
        logger.info(f"🤖 Auto Trader Ready! Reports will be saved to: {self.reports_folder}")
    
    def _create_reports_folder(self):
        """Create reports folder if it doesn't exist"""
        try:
            if not os.path.exists(self.reports_folder):
                os.makedirs(self.reports_folder)
                logger.info(f"Created reports folder: {self.reports_folder}")
        except Exception as e:
            logger.error(f"Error creating reports folder: {e}")
    
    def _save_trade_to_csv(self, trade_data):
        """Save trade data to date-wise CSV file"""
        try:
            # Get today's date for filename
            today = datetime.now().strftime("%Y-%m-%d")
            csv_filename = f"trading_report_{today}.csv"
            csv_filepath = os.path.join(self.reports_folder, csv_filename)
            
            # Create DataFrame from trade data
            df_new = pd.DataFrame([trade_data])
            
            # Check if file exists
            if os.path.exists(csv_filepath):
                # Read existing data and append
                df_existing = pd.read_csv(csv_filepath)
                df_combined = pd.concat([df_existing, df_new], ignore_index=True)
            else:
                # Create new file
                df_combined = df_new
            
            # Save to CSV
            df_combined.to_csv(csv_filepath, index=False)
            logger.info(f"📊 Trade data saved to: {csv_filename}")
            
        except Exception as e:
            logger.error(f"Error saving trade to CSV: {e}")
    
    def _record_trade_entry(self, symbol, pos):
        """Record trade entry to CSV"""
        trade_data = {
            'Date': datetime.now().strftime("%Y-%m-%d"),
            'Time': datetime.now().strftime("%H:%M:%S"),
            'Action': 'ENTRY',
            'Coin': pos['coin'],
            'Symbol': symbol,
            'Entry_Price': pos['entry_price'],
            'Amount': pos['amount'],
            'Invested_USD': pos['invested'],
            'Stop_Loss': pos['stop_loss'],
            'Take_Profit': pos['take_profit'],
            'TP_Type': pos['tp_type'],
            'ATR_TP': pos['atr_take_profit'],
            'Fixed_TP': pos['fixed_take_profit'],
            'Exit_Price': None,
            'Exit_Time': None,
            'PnL_USD': None,
            'PnL_Percent': None,
            'Exit_Reason': None,
            'Trade_Duration_Minutes': None,
            'Stop_Moved_Breakeven': False
        }
        self._save_trade_to_csv(trade_data)
    
    def _record_breakeven_move(self, symbol, pos):
        """Record when stop loss is moved to breakeven"""
        trade_data = {
            'Date': datetime.now().strftime("%Y-%m-%d"),
            'Time': datetime.now().strftime("%H:%M:%S"),
            'Action': 'BREAKEVEN_MOVE',
            'Coin': pos['coin'],
            'Symbol': symbol,
            'Entry_Price': pos['entry_price'],
            'Amount': pos['amount'],
            'Invested_USD': pos['invested'],
            'Stop_Loss': pos['stop_loss'],
            'Take_Profit': pos['take_profit'],
            'TP_Type': pos['tp_type'],
            'ATR_TP': pos['atr_take_profit'],
            'Fixed_TP': pos['fixed_take_profit'],
            'Exit_Price': None,
            'Exit_Time': None,
            'PnL_USD': None,
            'PnL_Percent': None,
            'Exit_Reason': 'STOP_MOVED_TO_BREAKEVEN',
            'Trade_Duration_Minutes': int((datetime.now() - pos['entry_time']).total_seconds() / 60),
            'Stop_Moved_Breakeven': True
        }
        self._save_trade_to_csv(trade_data)
    
    def _record_trade_exit(self, symbol, pos, exit_price, exit_reason, sell_amount=None):
        """Record trade exit to CSV"""
        exit_time = datetime.now()
        if sell_amount is None:
            sell_amount = pos['amount']
        
        # Calculate P&L
        pnl_usd = (exit_price - pos['entry_price']) * sell_amount
        pnl_percent = ((exit_price - pos['entry_price']) / pos['entry_price']) * 100
        
        # Calculate trade duration
        duration = exit_time - pos['entry_time']
        duration_minutes = int(duration.total_seconds() / 60)
        
        trade_data = {
            'Date': exit_time.strftime("%Y-%m-%d"),
            'Time': exit_time.strftime("%H:%M:%S"),
            'Action': 'EXIT',
            'Coin': pos['coin'],
            'Symbol': symbol,
            'Entry_Price': pos['entry_price'],
            'Amount': sell_amount,
            'Invested_USD': pos['invested'],
            'Stop_Loss': pos['stop_loss'],
            'Take_Profit': pos['take_profit'],
            'TP_Type': pos['tp_type'],
            'ATR_TP': pos['atr_take_profit'],
            'Fixed_TP': pos['fixed_take_profit'],
            'Exit_Price': exit_price,
            'Exit_Time': exit_time.strftime("%H:%M:%S"),
            'PnL_USD': pnl_usd,
            'PnL_Percent': pnl_percent,
            'Exit_Reason': exit_reason,
            'Trade_Duration_Minutes': duration_minutes,
            'Stop_Moved_Breakeven': pos['stop_moved_to_breakeven']
        }
        self._save_trade_to_csv(trade_data)
    
    def _display_live_status(self):
        """Display live status of all positions"""
        try:
            if not self.positions:
                return
            
            # Clear output for live update
            clear_output()
            
            print("=" * 80)
            print(f"🤖 LIVE TRADING DASHBOARD - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print("=" * 80)
            
            total_invested = 0
            total_current_value = 0
            
            for symbol, pos in self.positions.items():
                try:
                    ticker = self.exchange.fetch_ticker(symbol)
                    current = ticker['last']
                    
                    pnl = (current - pos['entry_price']) * pos['amount']
                    pnl_pct = ((current - pos['entry_price']) / pos['entry_price']) * 100
                    current_value = current * pos['amount']
                    
                    total_invested += pos['invested']
                    total_current_value += current_value
                    
                    # Calculate distances to stop and target
                    stop_distance = ((current - pos['stop_loss']) / current) * 100
                    target_distance = ((pos['take_profit'] - current) / current) * 100
                    
                    # Time tracking
                    time_passed = datetime.now() - pos['entry_time']
                    hours_passed = time_passed.total_seconds() / 3600
                    
                    # Status indicators
                    pnl_indicator = "📈" if pnl > 0 else "📉" if pnl < 0 else "➖"
                    breakeven_status = "✅" if pos['stop_moved_to_breakeven'] else "❌"
                    
                    print(f"\n🪙 {pos['coin']} ({pos['tp_type']}):")
                    print(f"   💰 ${pos['entry_price']:.6f} → ${current:.6f} | {pnl_indicator} ${pnl:.2f} ({pnl_pct:+.2f}%)")
                    print(f"   🛑 Stop: ${pos['stop_loss']:.6f} ({stop_distance:+.2f}%)")
                    print(f"   🎯 Target: ${pos['take_profit']:.6f} ({target_distance:+.2f}%)")
                    print(f"   ⏱️  {hours_passed:.1f}h | Breakeven: {breakeven_status}")
                    
                    if not pos['stop_moved_to_breakeven'] and hours_passed < 1:
                        minutes_remaining = int((3600 - time_passed.total_seconds()) / 60)
                        print(f"   ⏰ Breakeven move in: {minutes_remaining} minutes")
                    
                except Exception as e:
                    print(f"   ❌ Error fetching {symbol}: {e}")
            
            # Portfolio summary
            total_pnl = total_current_value - total_invested
            total_pnl_pct = (total_pnl / total_invested * 100) if total_invested > 0 else 0
            
            print("\n" + "=" * 80)
            print("💼 PORTFOLIO SUMMARY")
            print(f"   💸 Invested: ${total_invested:.2f} | 💰 Value: ${total_current_value:.2f}")
            print(f"   📈 Total P&L: ${total_pnl:.2f} ({total_pnl_pct:+.2f}%)")
            print("=" * 80)
            print("🔄 Refreshing every 10 seconds... (Press Ctrl+C to stop)")
            
        except Exception as e:
            print(f"❌ Error displaying live status: {e}")

    def trade(self, coin_pair, amount, take_profit_ratio=2.0, use_fixed_tp=False, fixed_tp_percent=2.5):
        """
        Execute a trade with coin pair, dollar amount, and take profit options
        
        Take Profit Options:
        1. ATR-based: Uses custom risk/reward ratio with ATR (default 1:2)
        2. Fixed percentage: Custom percentage above entry price (default 2.5%)
        
        Examples: 
        - trade('BTCUSDT', 100) - ATR-based with 1:2 risk/reward ratio
        - trade('BTCUSDT', 100, 3.0) - ATR-based with 1:3 risk/reward ratio
        - trade('ETHUSDT', 50, use_fixed_tp=True) - Fixed 2.5% take profit
        - trade('ADAUSDT', 25, use_fixed_tp=True, fixed_tp_percent=3.0) - Fixed 3.0% TP
        - trade('SOLUSDT', 75, 1.5, True, 4.5) - Fixed 4.5% TP (ATR ratio ignored)
        """
        try:
            logger.info(f"\n{'='*60}")
            logger.info(f"🚀 INITIATING TRADE: {coin_pair.upper()} with ${amount}")
            logger.info(f"{'='*60}")
            
            # Convert BTCUSDT to BTC/USDT format
            coin_pair = coin_pair.upper()
            if coin_pair.endswith('USDT'):
                coin = coin_pair[:-4]  # Remove USDT
                symbol = f"{coin}/USDT"
            else:
                # If not in correct format, assume it's just the coin name
                symbol = f"{coin_pair}/USDT"
                coin = coin_pair
            
            logger.info(f"📊 Processing {symbol}...")
            
            # Check if already in position
            if symbol in self.positions:
                logger.warning(f"❌ Already trading {symbol}")
                return False
            
            # Check balance first
            logger.info("💰 Checking balance...")
            balance = self.exchange.fetch_balance()
            usdt_balance = balance['USDT']['free']
            
            if usdt_balance < amount:
                logger.error(f"❌ Insufficient balance. Have ${usdt_balance:.2f}, need ${amount}")
                return False
            
            logger.info(f"✅ Balance sufficient: ${usdt_balance:.2f}")
            
            # Get current price and market data
            logger.info("📈 Fetching market data...")
            
            # Get current ticker for immediate price
            ticker = self.exchange.fetch_ticker(symbol)
            current_price = ticker['last']
            logger.info(f"📊 Current price: ${current_price:.8f}")
            
            # Get OHLCV for ATR calculation
            try:
                ohlcv = self.exchange.fetch_ohlcv(symbol, self.timeframe, limit=50)
                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)
                atr_value = df['atr'].iloc[-1]
                logger.info(f"📊 ATR value: ${atr_value:.8f}")
            except Exception as e:
                logger.error(f"❌ Error fetching OHLCV: {e}")
                # Use fallback ATR calculation
                atr_value = current_price * 0.02  # 2% of current price as fallback
                logger.info(f"📊 Using fallback ATR: ${atr_value:.8f}")
            
            # Get market info and calculate position size
            logger.info("🔢 Calculating position size...")
            markets = self.exchange.load_markets()
            market = markets[symbol]
            
            # Calculate raw position size
            position_size = amount / current_price
            
            # Handle precision
            precision = market['precision']['amount']
            if isinstance(precision, float):
                precision = int(-1 * math.log10(precision))
            
            # Round down to avoid exceeding amount
            factor = 10 ** precision
            position_size = math.floor(position_size * factor) / factor
            
            logger.info(f"📊 Position size: {position_size:.8f} {coin}")
            
            # Check minimum order size
            min_amount = market['limits']['amount']['min']
            if position_size < min_amount:
                logger.error(f"❌ Position size too small: {position_size:.8f} (min: {min_amount})")
                return False
            
            # Calculate levels BEFORE order
            stop_distance = atr_value * 1.5
            stop_loss = current_price - stop_distance
            
            # Calculate both take profit levels
            atr_take_profit = current_price + (stop_distance * take_profit_ratio)
            fixed_take_profit = current_price * (1 + fixed_tp_percent / 100)
            
            # Determine which take profit to use
            if use_fixed_tp:
                take_profit = fixed_take_profit
                tp_type = f"Fixed {fixed_tp_percent}%"
            else:
                take_profit = atr_take_profit
                tp_type = f"ATR-based (1:{take_profit_ratio})"
            
            logger.info(f"📊 Calculated levels:")
            logger.info(f"   Stop Loss: ${stop_loss:.8f}")
            logger.info(f"   Take Profit ({tp_type}): ${take_profit:.8f}")
            
            # Execute buy order IMMEDIATELY
            logger.info("🔥 EXECUTING BUY ORDER...")
            start_time = time.time()
            
            try:
                # Use market order for instant execution
                order = self.exchange.create_market_order(symbol, 'buy', position_size)
                execution_time = time.time() - start_time
                logger.info(f"⚡ Order executed in {execution_time:.2f} seconds")
                
                # Get actual fill price
                if order['average']:
                    entry_price = float(order['average'])
                else:
                    # Fallback to current price if average not available
                    entry_price = current_price
                
                logger.info(f"✅ ORDER FILLED!")
                logger.info(f"   Entry Price: ${entry_price:.8f}")
                logger.info(f"   Amount: {position_size:.8f} {coin}")
                logger.info(f"   Total Cost: ${entry_price * position_size:.2f}")
                
            except Exception as e:
                logger.error(f"❌ Order execution failed: {e}")
                return False
            
            # Recalculate levels with actual entry price if different
            if abs(entry_price - current_price) > (current_price * 0.001):  # If more than 0.1% difference
                logger.info("🔄 Recalculating levels with actual entry price...")
                stop_distance = atr_value * 1.5
                stop_loss = entry_price - stop_distance
                
                atr_take_profit = entry_price + (stop_distance * take_profit_ratio)
                fixed_take_profit = entry_price * (1 + fixed_tp_percent / 100)
                
                if use_fixed_tp:
                    take_profit = fixed_take_profit
                else:
                    take_profit = atr_take_profit
            
            # Store position
            self.positions[symbol] = {
                'coin': coin,
                'coin_pair': coin_pair,
                'entry_price': entry_price,
                'amount': position_size,
                'stop_loss': stop_loss,
                'take_profit': take_profit,
                'atr_take_profit': atr_take_profit,
                'fixed_take_profit': fixed_take_profit,
                'entry_time': datetime.now(),
                'invested': amount,
                'take_profit_ratio': take_profit_ratio,
                'fixed_tp_percent': fixed_tp_percent,
                'stop_moved_to_breakeven': False,
                'use_fixed_tp': use_fixed_tp,
                'tp_type': tp_type
            }
            
            # Calculate risk/reward
            risk = stop_distance * position_size
            if use_fixed_tp:
                reward = (fixed_take_profit - entry_price) * position_size
                actual_ratio = (fixed_take_profit - entry_price) / stop_distance
            else:
                reward = (stop_distance * take_profit_ratio) * position_size
                actual_ratio = take_profit_ratio
            
            # Display final summary
            logger.info(f"\n{'='*60}")
            logger.info(f"✅ TRADE EXECUTED SUCCESSFULLY - {coin}")
            logger.info(f"{'='*60}")
            logger.info(f"💰 Entry Price: ${entry_price:.8f}")
            logger.info(f"📊 Amount: {position_size:.8f} {coin}")
            logger.info(f"💸 Invested: ${entry_price * position_size:.2f}")
            logger.info(f"🛑 Stop Loss: ${stop_loss:.8f} (Risk: ${risk:.2f})")
            logger.info(f"🎯 Take Profit: ${take_profit:.8f} (Reward: ${reward:.2f})")
            logger.info(f"📈 Type: {tp_type}")
            logger.info(f"⚖️  Risk/Reward: 1:{actual_ratio:.2f}")
            logger.info(f"🔄 ATR TP: ${atr_take_profit:.8f} | Fixed TP: ${fixed_take_profit:.8f}")
            logger.info(f"{'='*60}\n")
            
            # Record trade entry to CSV
            self._record_trade_entry(symbol, self.positions[symbol])
            
            logger.info("🎯 Trade is now being monitored automatically!")
            logger.info("📱 Live dashboard will start displaying in 10 seconds...")
            return True
            
        except Exception as e:
            logger.error(f"❌ Critical error in trade execution: {e}")
            logger.error(f"Error type: {type(e).__name__}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False
    
    def status(self):
        """Show status of all positions"""
        if not self.positions:
            logger.info("📋 No active trades")
            return
        
        logger.info(f"\n{'='*70}")
        logger.info("📊 ACTIVE TRADES STATUS")
        logger.info(f"{'='*70}")
        
        total_invested = 0
        total_current_value = 0
        
        for symbol, pos in self.positions.items():
            try:
                ticker = self.exchange.fetch_ticker(symbol)
                current = ticker['last']
                
                pnl = (current - pos['entry_price']) * pos['amount']
                pnl_pct = ((current - pos['entry_price']) / pos['entry_price']) * 100
                current_value = current * pos['amount']
                
                total_invested += pos['invested']
                total_current_value += current_value
                
                # Calculate distances to stop and target
                stop_distance = ((current - pos['stop_loss']) / current) * 100
                target_distance = ((pos['take_profit'] - current) / current) * 100
                
                # Time tracking
                time_passed = datetime.now() - pos['entry_time']
                hours_passed = time_passed.total_seconds() / 3600
                
                logger.info(f"\n🪙 {pos['coin']}:")
                logger.info(f"   💰 Entry: ${pos['entry_price']:.8f} → Current: ${current:.8f}")
                logger.info(f"   📈 P&L: ${pnl:.2f} ({pnl_pct:+.2f}%) | Value: ${current_value:.2f}")
                logger.info(f"   🛑 Stop: ${pos['stop_loss']:.8f} ({stop_distance:+.2f}%)")
                logger.info(f"   🎯 Target: ${pos['take_profit']:.8f} ({target_distance:+.2f}%)")
                logger.info(f"   📊 TP Type: {pos['tp_type']}")
                logger.info(f"   ⏱️  Time: {hours_passed:.1f}h | Breakeven: {'✅' if pos['stop_moved_to_breakeven'] else '❌'}")
                
                if not pos['stop_moved_to_breakeven'] and hours_passed < 1:
                    minutes_remaining = int((3600 - time_passed.total_seconds()) / 60)
                    logger.info(f"   ⏰ Breakeven move in: {minutes_remaining} minutes")
                
            except Exception as e:
                logger.error(f"❌ Error getting {symbol} status: {e}")
        
        # Portfolio summary
        total_pnl = total_current_value - total_invested
        total_pnl_pct = (total_pnl / total_invested * 100) if total_invested > 0 else 0
        
        logger.info(f"\n{'='*70}")
        logger.info(f"💼 PORTFOLIO SUMMARY")
        logger.info(f"   💸 Total Invested: ${total_invested:.2f}")
        logger.info(f"   💰 Current Value: ${total_current_value:.2f}")
        logger.info(f"   📈 Total P&L: ${total_pnl:.2f} ({total_pnl_pct:+.2f}%)")
        logger.info(f"{'='*70}\n")
    
    def close(self, coin_pair):
        """Manually close a position - sells all available balance"""
        try:
            # Convert BTCUSDT to BTC/USDT format
            coin_pair = coin_pair.upper()
            if coin_pair.endswith('USDT'):
                coin = coin_pair[:-4]
                symbol = f"{coin}/USDT"
            else:
                symbol = f"{coin_pair}/USDT"
                coin = coin_pair
            
            logger.info(f"\n🔄 CLOSING POSITION: {coin}")
            
            # Get actual balance of the coin
            balance = self.exchange.fetch_balance()
            coin_balance = balance[coin]['free']
            
            if coin_balance <= 0:
                logger.info(f"❌ No {coin} balance to sell")
                if symbol in self.positions:
                    del self.positions[symbol]
                return False
            
            # Get market info
            markets = self.exchange.load_markets()
            market = markets[symbol]
            min_amount = market['limits']['amount']['min']
            
            if coin_balance < min_amount:
                logger.info(f"❌ Balance too small: {coin_balance:.8f} {coin} (min: {min_amount})")
                if symbol in self.positions:
                    del self.positions[symbol]
                return False
            
            # Get precision and calculate sell amount
            precision = market['precision']['amount']
            if isinstance(precision, float):
                precision = int(-1 * math.log10(precision))
            
            # Round down to avoid exceeding balance
            factor = 10 ** precision
            sell_amount = math.floor(coin_balance * 0.999 * factor) / factor  # Use 99.9% to be safe
            
            # Get current price
            ticker = self.exchange.fetch_ticker(symbol)
            current = ticker['last']
            
            logger.info(f"📊 Available: {coin_balance:.8f} {coin}")
            logger.info(f"📊 Selling: {sell_amount:.8f} {coin}")
            logger.info(f"💰 Price: ${current:.8f}")
            
            # Execute sell order
            logger.info("🔥 EXECUTING SELL ORDER...")
            start_time = time.time()
            
            order = self.exchange.create_market_order(symbol, 'sell', sell_amount)
            execution_time = time.time() - start_time
            
            exit_price = float(order['average']) if order['average'] else current
            total_received = exit_price * sell_amount
            
            logger.info(f"⚡ Order executed in {execution_time:.2f} seconds")
            
            # Calculate P&L if position exists
            if symbol in self.positions:
                pos = self.positions[symbol]
                pnl = (exit_price - pos['entry_price']) * sell_amount
                pnl_pct = ((exit_price - pos['entry_price']) / pos['entry_price']) * 100
                
                logger.info(f"\n{'='*60}")
                logger.info(f"✅ POSITION CLOSED - {coin}")
                logger.info(f"{'='*60}")
                logger.info(f"📊 Amount Sold: {sell_amount:.8f} {coin}")
                logger.info(f"💰 Exit Price: ${exit_price:.8f}")
                logger.info(f"💸 Total Received: ${total_received:.2f}")
                logger.info(f"📈 P&L: ${pnl:.2f} ({pnl_pct:+.2f}%)")
                logger.info(f"{'='*60}\n")
                
                # Record manual exit to CSV
                self._record_trade_exit(symbol, pos, exit_price, "MANUAL_CLOSE", sell_amount)
                
                del self.positions[symbol]
            else:
                logger.info(f"\n{'='*60}")
                logger.info(f"✅ SOLD ALL {coin}")
                logger.info(f"📊 Amount: {sell_amount:.8f} {coin}")
                logger.info(f"💰 Price: ${exit_price:.8f}")
                logger.info(f"💸 Total: ${total_received:.2f}")
                logger.info(f"{'='*60}\n")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error closing position: {e}")
            return False
    
    def switch_take_profit(self, coin_pair, use_fixed_tp=None):
        """Switch between ATR-based and fixed take profit for an active position"""
        try:
            # Convert BTCUSDT to BTC/USDT format
            coin_pair = coin_pair.upper()
            if coin_pair.endswith('USDT'):
                coin = coin_pair[:-4]
                symbol = f"{coin}/USDT"
            else:
                symbol = f"{coin_pair}/USDT"
                coin = coin_pair
            
            if symbol not in self.positions:
                logger.warning(f"❌ No active position for {symbol}")
                return False
            
            pos = self.positions[symbol]
            
            # Determine new take profit setting
            if use_fixed_tp is None:
                new_use_fixed = not pos['use_fixed_tp']
            else:
                new_use_fixed = use_fixed_tp
            
            # Update take profit
            if new_use_fixed:
                pos['take_profit'] = pos['fixed_take_profit']
                pos['tp_type'] = f"Fixed {pos['fixed_tp_percent']}%"
            else:
                pos['take_profit'] = pos['atr_take_profit']
                pos['tp_type'] = f"ATR-based (1:{pos['take_profit_ratio']})"
            
            pos['use_fixed_tp'] = new_use_fixed
            
            logger.info(f"\n🔄 SWITCHED TAKE PROFIT - {coin}")
            logger.info(f"🎯 New Take Profit: ${pos['take_profit']:.8f}")
            logger.info(f"📊 Type: {pos['tp_type']}")
            
            alternative_tp = pos['atr_take_profit'] if new_use_fixed else pos['fixed_take_profit']
            alternative_type = f"ATR (1:{pos['take_profit_ratio']})" if new_use_fixed else f"Fixed ({pos['fixed_tp_percent']}%)"
            logger.info(f"🔄 Alternative TP: ${alternative_tp:.8f} ({alternative_type})\n")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error switching take profit: {e}")
            return False
    
    def _monitor_loop(self):
        """Monitor positions automatically with live status display"""
        logger.info("👁️  Monitoring thread started")
        consecutive_errors = 0
        max_consecutive_errors = 5
        
        while self.monitoring:
            try:
                if not self.positions:
                    time.sleep(10)  # Sleep longer when no positions
                    consecutive_errors = 0
                    continue
                
                # Display live status every 10 seconds
                self._display_live_status()
                
                for symbol, pos in list(self.positions.items()):
                    try:
                        ticker = self.exchange.fetch_ticker(symbol)
                        current_price = ticker['last']
                        
                        # Check for breakeven move (after 1 hour)
                        if not pos['stop_moved_to_breakeven']:
                            time_passed = datetime.now() - pos['entry_time']
                            if time_passed.total_seconds() >= 3600:  # 1 hour
                                if current_price > pos['entry_price']:
                                    pos['stop_loss'] = pos['entry_price']
                                    pos['stop_moved_to_breakeven'] = True
                                    logger.info(f"⏰ {pos['coin']} - Stop moved to breakeven at ${pos['entry_price']:.8f}")
                                    self._record_breakeven_move(symbol, pos)
                        
                        # Check stop loss
                        if current_price <= pos['stop_loss']:
                            stop_type = "BREAKEVEN" if pos['stop_moved_to_breakeven'] and pos['stop_loss'] == pos['entry_price'] else "STOP_LOSS"
                            logger.info(f"\n🛑 {stop_type} TRIGGERED - {pos['coin']} at ${current_price:.8f}")
                            
                            if self._execute_exit(symbol, pos, current_price, stop_type):
                                del self.positions[symbol]
                        
                        # Check take profit
                        elif current_price >= pos['take_profit']:
                            logger.info(f"\n🎯 TAKE PROFIT TRIGGERED - {pos['coin']} at ${current_price:.8f}")
                            
                            if self._execute_exit(symbol, pos, current_price, "TAKE_PROFIT"):
                                del self.positions[symbol]
                    
                    except Exception as e:
                        logger.error(f"❌ Error monitoring {symbol}: {e}")
                        consecutive_errors += 1
                
                # Reset error counter on successful loop
                consecutive_errors = 0
                time.sleep(10)  # Check every 10 seconds
                
            except Exception as e:
                consecutive_errors += 1
                logger.error(f"❌ Monitor loop error #{consecutive_errors}: {e}")
                
                if consecutive_errors >= max_consecutive_errors:
                    logger.error(f"❌ Too many consecutive errors ({consecutive_errors}), stopping monitor")
                    break
                
                time.sleep(30)  # Wait longer on error
        
        logger.info("👁️  Monitoring thread stopped")
    
    def _execute_exit(self, symbol, pos, current_price, exit_reason):
        """Execute exit order with proper error handling"""
        try:
            # Get actual balance
            balance = self.exchange.fetch_balance()
            coin_balance = balance[pos['coin']]['free']
            
            if coin_balance <= 0:
                logger.warning(f"⚠️  No {pos['coin']} balance to sell")
                return True
            
            # Get market info
            markets = self.exchange.load_markets()
            market = markets[symbol]
            min_amount = market['limits']['amount']['min']
            
            if coin_balance < min_amount:
                logger.warning(f"⚠️  Balance too small: {coin_balance:.8f} {pos['coin']}")
                return True
            
            # Calculate sell amount with precision
            precision = market['precision']['amount']
            if isinstance(precision, float):
                precision = int(-1 * math.log10(precision))
            
            factor = 10 ** precision
            sell_amount = math.floor(coin_balance * 0.999 * factor) / factor
            
            # Execute sell order
            logger.info(f"🔥 Executing {exit_reason} sell: {sell_amount:.8f} {pos['coin']}")
            
            order = self.exchange.create_market_order(symbol, 'sell', sell_amount)
            exit_price = float(order['average']) if order['average'] else current_price
            
            # Calculate final P&L
            pnl = (exit_price - pos['entry_price']) * sell_amount
            pnl_pct = ((exit_price - pos['entry_price']) / pos['entry_price']) * 100
            
            logger.info(f"✅ {exit_reason} executed!")
            logger.info(f"   Exit Price: ${exit_price:.8f}")
            logger.info(f"   Amount: {sell_amount:.8f} {pos['coin']}")
            logger.info(f"   P&L: ${pnl:.2f} ({pnl_pct:+.2f}%)")
            
            # Record exit
            self._record_trade_exit(symbol, pos, exit_price, exit_reason, sell_amount)
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error executing exit for {symbol}: {e}")
            return False
    
    def generate_summary_report(self, date=None):
        """Generate summary report for a specific date or today"""
        try:
            if date is None:
                date = datetime.now().strftime("%Y-%m-%d")
            
            csv_filename = f"trading_report_{date}.csv"
            csv_filepath = os.path.join(self.reports_folder, csv_filename)
            
            if not os.path.exists(csv_filepath):
                logger.info(f"📊 No trading data found for {date}")
                return
            
            # Read the CSV
            df = pd.read_csv(csv_filepath)
            
            # Filter only exit trades for P&L calculation
            exits = df[df['Action'] == 'EXIT'].copy()
            
            if exits.empty:
                logger.info(f"📊 No completed trades found for {date}")
                return
            
            # Calculate summary statistics
            total_trades = len(exits)
            winning_trades = len(exits[exits['PnL_USD'] > 0])
            losing_trades = len(exits[exits['PnL_USD'] < 0])
            breakeven_trades = len(exits[exits['PnL_USD'] == 0])
            
            total_pnl = exits['PnL_USD'].sum()
            win_rate = (winning_trades / total_trades) * 100 if total_trades > 0 else 0
            
            avg_win = exits[exits['PnL_USD'] > 0]['PnL_USD'].mean() if winning_trades > 0 else 0
            avg_loss = exits[exits['PnL_USD'] < 0]['PnL_USD'].mean() if losing_trades > 0 else 0
            
            # Best and worst trades
            best_trade = exits['PnL_USD'].max() if not exits.empty else 0
            worst_trade = exits['PnL_USD'].min() if not exits.empty else 0
            
            # Average trade duration
            avg_duration = exits['Trade_Duration_Minutes'].mean() if 'Trade_Duration_Minutes' in exits.columns else 0
            
            # Print summary
            logger.info(f"\n{'='*70}")
            logger.info(f"📊 TRADING SUMMARY REPORT - {date}")
            logger.info(f"{'='*70}")
            logger.info(f"📈 Total Trades: {total_trades}")
            logger.info(f"✅ Winning Trades: {winning_trades}")
            logger.info(f"❌ Losing Trades: {losing_trades}")
            logger.info(f"➖ Breakeven Trades: {breakeven_trades}")
            logger.info(f"🎯 Win Rate: {win_rate:.1f}%")
            logger.info(f"💰 Total P&L: ${total_pnl:.2f}")
            logger.info(f"📊 Average Win: ${avg_win:.2f}")
            logger.info(f"📊 Average Loss: ${avg_loss:.2f}")
            logger.info(f"🏆 Best Trade: ${best_trade:.2f}")
            logger.info(f"💔 Worst Trade: ${worst_trade:.2f}")
            logger.info(f"⏱️  Average Duration: {avg_duration:.0f} minutes")
            if avg_loss != 0:
                logger.info(f"⚖️  Risk/Reward Ratio: 1:{abs(avg_win/avg_loss):.2f}")
            logger.info(f"{'='*70}\n")
            
            # Show trade details
            logger.info("📋 TRADE DETAILS:")
            for _, trade in exits.iterrows():
                pnl_emoji = "📈" if trade['PnL_USD'] > 0 else "📉" if trade['PnL_USD'] < 0 else "➖"
                logger.info(f"   {pnl_emoji} {trade['Coin']}: ${trade['PnL_USD']:.2f} ({trade['PnL_Percent']:+.1f}%) - {trade['Exit_Reason']}")
            logger.info("")
            
        except Exception as e:
            logger.error(f"❌ Error generating summary report: {e}")
    
    def stop_monitoring(self):
        """Stop the monitoring thread"""
        self.monitoring = False
        logger.info("🛑 Stopping monitoring...")
    
    def restart_monitoring(self):
        """Restart monitoring if stopped"""
        if not self.monitoring:
            self.monitoring = True
            self.monitor_thread = threading.Thread(target=self._monitor_loop)
            self.monitor_thread.daemon = True
            self.monitor_thread.start()
            logger.info("🔄 Monitoring restarted!")
        else:
            logger.info("👁️  Monitoring is already running")


# Create bot instance with connection test
bot = AutoTrader()