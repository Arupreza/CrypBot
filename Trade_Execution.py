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
import numpy as np

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
    
    def _find_swing_points(self, df, lookback=5):
        """
        Find swing highs and lows in price data
        
        Args:
            df: DataFrame with OHLCV data
            lookback: Number of periods to look back/forward for swing confirmation
        
        Returns:
            tuple: (swing_high, swing_low, swing_high_index, swing_low_index)
        """
        try:
            if len(df) < (lookback * 2 + 1):
                logger.warning("Not enough data for swing point calculation")
                return None, None, None, None
            
            highs = df['high'].values
            lows = df['low'].values
            
            # Find swing highs (peak higher than lookback periods before and after)
            swing_highs = []
            swing_high_indices = []
            
            for i in range(lookback, len(highs) - lookback):
                is_swing_high = True
                current_high = highs[i]
                
                # Check if current high is higher than lookback periods before and after
                for j in range(i - lookback, i + lookback + 1):
                    if j != i and highs[j] >= current_high:
                        is_swing_high = False
                        break
                
                if is_swing_high:
                    swing_highs.append(current_high)
                    swing_high_indices.append(i)
            
            # Find swing lows (trough lower than lookback periods before and after)
            swing_lows = []
            swing_low_indices = []
            
            for i in range(lookback, len(lows) - lookback):
                is_swing_low = True
                current_low = lows[i]
                
                # Check if current low is lower than lookback periods before and after
                for j in range(i - lookback, i + lookback + 1):
                    if j != i and lows[j] <= current_low:
                        is_swing_low = False
                        break
                
                if is_swing_low:
                    swing_lows.append(current_low)
                    swing_low_indices.append(i)
            
            # Get the most recent swing points
            recent_swing_high = swing_highs[-1] if swing_highs else None
            recent_swing_low = swing_lows[-1] if swing_lows else None
            recent_swing_high_index = swing_high_indices[-1] if swing_high_indices else None
            recent_swing_low_index = swing_low_indices[-1] if swing_low_indices else None
            
            # Additional validation: find the closest swing points to current price
            current_price = df['close'].iloc[-1]
            
            if swing_highs:
                # Find swing high above current price
                valid_swing_highs = [(high, idx) for high, idx in zip(swing_highs, swing_high_indices) if high > current_price]
                if valid_swing_highs:
                    # Get the lowest swing high above current price (nearest resistance)
                    recent_swing_high, recent_swing_high_index = min(valid_swing_highs, key=lambda x: x[0])
                else:
                    # If no swing high above current price, use the highest recent swing high
                    recent_swing_high = max(swing_highs)
                    recent_swing_high_index = swing_high_indices[swing_highs.index(recent_swing_high)]
            
            if swing_lows:
                # Find swing low below current price
                valid_swing_lows = [(low, idx) for low, idx in zip(swing_lows, swing_low_indices) if low < current_price]
                if valid_swing_lows:
                    # Get the highest swing low below current price (nearest support)
                    recent_swing_low, recent_swing_low_index = max(valid_swing_lows, key=lambda x: x[0])
                else:
                    # If no swing low below current price, use the lowest recent swing low
                    recent_swing_low = min(swing_lows)
                    recent_swing_low_index = swing_low_indices[swing_lows.index(recent_swing_low)]
            
            return recent_swing_high, recent_swing_low, recent_swing_high_index, recent_swing_low_index
            
        except Exception as e:
            logger.error(f"Error finding swing points: {e}")
            return None, None, None, None
    
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
            'SL_Type': pos['sl_type'],
            'ATR_TP': pos['atr_take_profit'],
            'Fixed_TP': pos['fixed_take_profit'],
            'Swing_High_TP': pos.get('swing_high_tp'),
            'Swing_Low_SL': pos.get('swing_low_sl'),
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
            'SL_Type': pos['sl_type'],
            'ATR_TP': pos['atr_take_profit'],
            'Fixed_TP': pos['fixed_take_profit'],
            'Swing_High_TP': pos.get('swing_high_tp'),
            'Swing_Low_SL': pos.get('swing_low_sl'),
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
            'SL_Type': pos['sl_type'],
            'ATR_TP': pos['atr_take_profit'],
            'Fixed_TP': pos['fixed_take_profit'],
            'Swing_High_TP': pos.get('swing_high_tp'),
            'Swing_Low_SL': pos.get('swing_low_sl'),
            'Exit_Price': exit_price,
            'Exit_Time': exit_time.strftime("%H:%M:%S"),
            'PnL_USD': pnl_usd,
            'PnL_Percent': pnl_percent,
            'Exit_Reason': exit_reason,
            'Trade_Duration_Minutes': duration_minutes,
            'Stop_Moved_Breakeven': pos['stop_moved_to_breakeven']
        }
        self._save_trade_to_csv(trade_data)

    def trade(self, coin_pair, amount, take_profit_ratio=2.0, use_fixed_tp=False, fixed_tp_percent=2.5, 
              use_swing_tp=False, use_swing_sl=False, swing_lookback=5):
        """
        Execute a trade with various take profit and stop loss options
        
        Take Profit Options:
        1. ATR-based: Uses custom risk/reward ratio with ATR (default 1:2)
        2. Fixed percentage: Custom percentage above entry price (default 2.5%)
        3. Swing High: Uses recent swing high as take profit target
        
        Stop Loss Options:
        1. ATR-based: Uses 1.5x ATR below entry (default)
        2. Swing Low: Uses recent swing low as stop loss
        
        Args:
            coin_pair: Trading pair (e.g., 'BTCUSDT')
            amount: Dollar amount to invest
            take_profit_ratio: ATR-based risk/reward ratio (default 1:2)
            use_fixed_tp: Use fixed percentage take profit
            fixed_tp_percent: Fixed TP percentage (default 2.5%)
            use_swing_tp: Use swing high as take profit
            use_swing_sl: Use swing low as stop loss
            swing_lookback: Periods for swing point calculation (default 5)
        
        Examples: 
        - trade('BTCUSDT', 100) - ATR-based TP/SL with 1:2 ratio
        - trade('ETHUSDT', 50, use_swing_tp=True) - Swing high TP, ATR SL
        - trade('ADAUSDT', 25, use_swing_sl=True) - ATR TP, swing low SL
        - trade('SOLUSDT', 75, use_swing_tp=True, use_swing_sl=True) - Both swing levels
        """
        try:
            logger.info(f"🚀 INITIATING TRADE: {coin_pair.upper()} with ${amount}")
            
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
            
            # Get OHLCV for ATR and swing point calculation
            try:
                ohlcv = self.exchange.fetch_ohlcv(symbol, self.timeframe, limit=100)  # More data for swing analysis
                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)
                atr_value = df['atr'].iloc[-1]
                logger.info(f"📊 ATR value: ${atr_value:.8f}")
                
                # Find swing points if needed
                swing_high, swing_low, swing_high_idx, swing_low_idx = None, None, None, None
                if use_swing_tp or use_swing_sl:
                    logger.info("🔍 Analyzing swing points...")
                    swing_high, swing_low, swing_high_idx, swing_low_idx = self._find_swing_points(df, swing_lookback)
                    
                    if swing_high:
                        logger.info(f"📈 Swing High found: ${swing_high:.8f}")
                    if swing_low:
                        logger.info(f"📉 Swing Low found: ${swing_low:.8f}")
                
            except Exception as e:
                logger.error(f"❌ Error fetching OHLCV: {e}")
                # Use fallback ATR calculation
                atr_value = current_price * 0.02  # 2% of current price as fallback
                logger.info(f"📊 Using fallback ATR: ${atr_value:.8f}")
                swing_high, swing_low = None, None
            
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
            
            # Determine stop loss
            if use_swing_sl and swing_low and swing_low < current_price:
                stop_loss = swing_low
                sl_type = "Swing Low"
                logger.info(f"🛑 Using swing low stop loss: ${stop_loss:.8f}")
            else:
                stop_loss = current_price - stop_distance
                sl_type = "ATR-based"
                if use_swing_sl:
                    logger.warning("⚠️ Swing low not found or invalid, using ATR stop loss")
            
            # Calculate all take profit levels
            atr_take_profit = current_price + (stop_distance * take_profit_ratio)
            fixed_take_profit = current_price * (1 + fixed_tp_percent / 100)
            swing_high_tp = swing_high if swing_high and swing_high > current_price else None
            
            # Determine which take profit to use
            if use_swing_tp and swing_high_tp:
                take_profit = swing_high_tp
                tp_type = "Swing High"
                logger.info(f"🎯 Using swing high take profit: ${take_profit:.8f}")
            elif use_fixed_tp:
                take_profit = fixed_take_profit
                tp_type = f"Fixed {fixed_tp_percent}%"
            else:
                take_profit = atr_take_profit
                tp_type = f"ATR-based (1:{take_profit_ratio})"
                if use_swing_tp:
                    logger.warning("⚠️ Swing high not found or invalid, using ATR take profit")
            
            logger.info(f"📊 Calculated levels:")
            logger.info(f"   Stop Loss ({sl_type}): ${stop_loss:.8f}")
            logger.info(f"   Take Profit ({tp_type}): ${take_profit:.8f}")
            
            # Validate risk/reward
            if take_profit <= current_price:
                logger.error(f"❌ Invalid take profit level: ${take_profit:.8f} (current: ${current_price:.8f})")
                return False
            
            if stop_loss >= current_price:
                logger.error(f"❌ Invalid stop loss level: ${stop_loss:.8f} (current: ${current_price:.8f})")
                return False
            
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
            
            # Store position with all levels
            self.positions[symbol] = {
                'coin': coin,
                'coin_pair': coin_pair,
                'entry_price': entry_price,
                'amount': position_size,
                'stop_loss': stop_loss,
                'take_profit': take_profit,
                'atr_take_profit': atr_take_profit,
                'fixed_take_profit': fixed_take_profit,
                'swing_high_tp': swing_high_tp,
                'swing_low_sl': swing_low if use_swing_sl else None,
                'entry_time': datetime.now(),
                'invested': amount,
                'take_profit_ratio': take_profit_ratio,
                'fixed_tp_percent': fixed_tp_percent,
                'stop_moved_to_breakeven': False,
                'use_fixed_tp': use_fixed_tp,
                'use_swing_tp': use_swing_tp,
                'use_swing_sl': use_swing_sl,
                'tp_type': tp_type,
                'sl_type': sl_type,
                'swing_lookback': swing_lookback
            }
            
            # Calculate risk/reward
            risk_distance = entry_price - stop_loss
            reward_distance = take_profit - entry_price
            actual_ratio = reward_distance / risk_distance if risk_distance > 0 else 0
            
            risk = risk_distance * position_size
            reward = reward_distance * position_size
            
            # Log final summary
            logger.info(f"✅ TRADE EXECUTED SUCCESSFULLY - {coin}")
            logger.info(f"💰 Entry Price: ${entry_price:.8f}")
            logger.info(f"📊 Amount: {position_size:.8f} {coin}")
            logger.info(f"💸 Invested: ${entry_price * position_size:.2f}")
            logger.info(f"🛑 Stop Loss ({sl_type}): ${stop_loss:.8f} (Risk: ${risk:.2f})")
            logger.info(f"🎯 Take Profit ({tp_type}): ${take_profit:.8f} (Reward: ${reward:.2f})")
            logger.info(f"⚖️  Risk/Reward: 1:{actual_ratio:.2f}")
            
            # Log alternative levels
            logger.info(f"🔄 Alternative Levels:")
            logger.info(f"   ATR TP: ${atr_take_profit:.8f}")
            logger.info(f"   Fixed TP: ${fixed_take_profit:.8f}")
            if swing_high_tp:
                logger.info(f"   Swing High TP: ${swing_high_tp:.8f}")
            if swing_low and use_swing_sl:
                logger.info(f"   Swing Low SL: ${swing_low:.8f}")
            
            # Record trade entry to CSV
            self._record_trade_entry(symbol, self.positions[symbol])
            
            logger.info("🎯 Trade is now being monitored automatically!")
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
        
        logger.info("📊 ACTIVE TRADES STATUS")
        
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
                
                logger.info(f"🪙 {pos['coin']}:")
                logger.info(f"   💰 Entry: ${pos['entry_price']:.8f} → Current: ${current:.8f}")
                logger.info(f"   📈 P&L: ${pnl:.2f} ({pnl_pct:+.2f}%) | Value: ${current_value:.2f}")
                logger.info(f"   🛑 Stop ({pos['sl_type']}): ${pos['stop_loss']:.8f} ({stop_distance:+.2f}%)")
                logger.info(f"   🎯 Target ({pos['tp_type']}): ${pos['take_profit']:.8f} ({target_distance:+.2f}%)")
                logger.info(f"   ⏱️  Time: {hours_passed:.1f}h | Breakeven: {'✅' if pos['stop_moved_to_breakeven'] else '❌'}")
                
                # Show alternative levels
                if pos.get('swing_high_tp') and pos['tp_type'] != "Swing High":
                    swing_distance = ((pos['swing_high_tp'] - current) / current) * 100
                    logger.info(f"   📈 Alt Swing TP: ${pos['swing_high_tp']:.8f} ({swing_distance:+.2f}%)")
                
                if not pos['stop_moved_to_breakeven'] and hours_passed < 1:
                    minutes_remaining = int((3600 - time_passed.total_seconds()) / 60)
                    logger.info(f"   ⏰ Breakeven move in: {minutes_remaining} minutes")
                
            except Exception as e:
                logger.error(f"❌ Error getting {symbol} status: {e}")
        
        # Portfolio summary
        total_pnl = total_current_value - total_invested
        total_pnl_pct = (total_pnl / total_invested * 100) if total_invested > 0 else 0
        
        logger.info(f"💼 PORTFOLIO SUMMARY")
        logger.info(f"   💸 Total Invested: ${total_invested:.2f}")
        logger.info(f"   💰 Current Value: ${total_current_value:.2f}")
        logger.info(f"   📈 Total P&L: ${total_pnl:.2f} ({total_pnl_pct:+.2f}%)")
    
    def switch_levels(self, coin_pair, switch_tp=None, switch_sl=None):
        """
        Switch between different take profit and stop loss types for an active position
        
        Args:
            coin_pair: Trading pair (e.g., 'BTCUSDT')
            switch_tp: 'atr', 'fixed', 'swing' or None to keep current
            switch_sl: 'atr', 'swing' or None to keep current
        """
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
            changes_made = False
            
            # Switch take profit type
            if switch_tp:
                if switch_tp.lower() == 'atr':
                    pos['take_profit'] = pos['atr_take_profit']
                    pos['tp_type'] = f"ATR-based (1:{pos['take_profit_ratio']})"
                    pos['use_fixed_tp'] = False
                    pos['use_swing_tp'] = False
                    changes_made = True
                    
                elif switch_tp.lower() == 'fixed':
                    pos['take_profit'] = pos['fixed_take_profit']
                    pos['tp_type'] = f"Fixed {pos['fixed_tp_percent']}%"
                    pos['use_fixed_tp'] = True
                    pos['use_swing_tp'] = False
                    changes_made = True
                    
                elif switch_tp.lower() == 'swing':
                    if pos['swing_high_tp']:
                        pos['take_profit'] = pos['swing_high_tp']
                        pos['tp_type'] = "Swing High"
                        pos['use_fixed_tp'] = False
                        pos['use_swing_tp'] = True
                        changes_made = True
                    else:
                        logger.warning("❌ No swing high available for take profit")
            
            # Switch stop loss type
            if switch_sl:
                if switch_sl.lower() == 'atr':
                    # Recalculate ATR stop loss
                    stop_distance = (pos['entry_price'] - pos['stop_loss']) if pos['sl_type'] != "ATR-based" else None
                    if stop_distance is None:
                        # Get fresh ATR data
                        try:
                            ohlcv = self.exchange.fetch_ohlcv(symbol, self.timeframe, limit=50)
                            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                            df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)
                            atr_value = df['atr'].iloc[-1]
                            stop_distance = atr_value * 1.5
                        except:
                            stop_distance = pos['entry_price'] * 0.03  # 3% fallback
                    
                    pos['stop_loss'] = pos['entry_price'] - stop_distance
                    pos['sl_type'] = "ATR-based"
                    pos['use_swing_sl'] = False
                    changes_made = True
                    
                elif switch_sl.lower() == 'swing':
                    if pos['swing_low_sl']:
                        pos['stop_loss'] = pos['swing_low_sl']
                        pos['sl_type'] = "Swing Low"
                        pos['use_swing_sl'] = True
                        changes_made = True
                    else:
                        logger.warning("❌ No swing low available for stop loss")
            
            if changes_made:
                logger.info(f"🔄 LEVELS SWITCHED - {coin}")
                logger.info(f"🛑 Stop Loss ({pos['sl_type']}): ${pos['stop_loss']:.8f}")
                logger.info(f"🎯 Take Profit ({pos['tp_type']}): ${pos['take_profit']:.8f}")
                return True
            else:
                logger.info(f"ℹ️ No changes made to {coin}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error switching levels: {e}")
            return False
    
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
            
            logger.info(f"🔄 CLOSING POSITION: {coin}")
            
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
                
                logger.info(f"✅ POSITION CLOSED - {coin}")
                logger.info(f"📊 Amount Sold: {sell_amount:.8f} {coin}")
                logger.info(f"💰 Exit Price: ${exit_price:.8f}")
                logger.info(f"💸 Total Received: ${total_received:.2f}")
                logger.info(f"📈 P&L: ${pnl:.2f} ({pnl_pct:+.2f}%)")
                
                # Record manual exit to CSV
                self._record_trade_exit(symbol, pos, exit_price, "MANUAL_CLOSE", sell_amount)
                
                del self.positions[symbol]
            else:
                logger.info(f"✅ SOLD ALL {coin}")
                logger.info(f"📊 Amount: {sell_amount:.8f} {coin}")
                logger.info(f"💰 Price: ${exit_price:.8f}")
                logger.info(f"💸 Total: ${total_received:.2f}")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error closing position: {e}")
            return False
    
    def switch_take_profit(self, coin_pair, use_fixed_tp=None):
        """Switch between ATR-based and fixed take profit for an active position (legacy function)"""
        return self.switch_levels(coin_pair, switch_tp='fixed' if use_fixed_tp else 'atr')
    
    def _monitor_loop(self):
        """Monitor positions automatically"""
        logger.info("👁️  Monitoring thread started")
        consecutive_errors = 0
        max_consecutive_errors = 5
        
        while self.monitoring:
            try:
                if not self.positions:
                    time.sleep(30)  # Sleep longer when no positions
                    consecutive_errors = 0
                    continue
                
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
                            logger.info(f"🛑 {stop_type} TRIGGERED - {pos['coin']} at ${current_price:.8f}")
                            
                            if self._execute_exit(symbol, pos, current_price, stop_type):
                                del self.positions[symbol]
                        
                        # Check take profit
                        elif current_price >= pos['take_profit']:
                            logger.info(f"🎯 TAKE PROFIT TRIGGERED - {pos['coin']} at ${current_price:.8f}")
                            
                            if self._execute_exit(symbol, pos, current_price, "TAKE_PROFIT"):
                                del self.positions[symbol]
                    
                    except Exception as e:
                        logger.error(f"❌ Error monitoring {symbol}: {e}")
                        consecutive_errors += 1
                
                # Reset error counter on successful loop
                consecutive_errors = 0
                time.sleep(30)  # Check every 30 seconds
                
            except Exception as e:
                consecutive_errors += 1
                logger.error(f"❌ Monitor loop error #{consecutive_errors}: {e}")
                
                if consecutive_errors >= max_consecutive_errors:
                    logger.error(f"❌ Too many consecutive errors ({consecutive_errors}), stopping monitor")
                    break
                
                time.sleep(60)  # Wait longer on error
        
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
            
            # Strategy performance breakdown
            atr_trades = exits[exits['TP_Type'].str.contains('ATR', na=False)]
            fixed_trades = exits[exits['TP_Type'].str.contains('Fixed', na=False)]
            swing_trades = exits[exits['TP_Type'].str.contains('Swing', na=False)]
            
            # Log summary
            logger.info(f"📊 TRADING SUMMARY REPORT - {date}")
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
            
            # Strategy breakdown
            if len(atr_trades) > 0:
                logger.info(f"📈 ATR Strategy: {len(atr_trades)} trades, P&L: ${atr_trades['PnL_USD'].sum():.2f}")
            if len(fixed_trades) > 0:
                logger.info(f"📊 Fixed Strategy: {len(fixed_trades)} trades, P&L: ${fixed_trades['PnL_USD'].sum():.2f}")
            if len(swing_trades) > 0:
                logger.info(f"🎯 Swing Strategy: {len(swing_trades)} trades, P&L: ${swing_trades['PnL_USD'].sum():.2f}")
            
            # Log trade details
            logger.info("📋 TRADE DETAILS:")
            for _, trade in exits.iterrows():
                pnl_emoji = "📈" if trade['PnL_USD'] > 0 else "📉" if trade['PnL_USD'] < 0 else "➖"
                tp_info = f"{trade['TP_Type']}" if pd.notna(trade['TP_Type']) else "Unknown"
                sl_info = f"{trade['SL_Type']}" if pd.notna(trade['SL_Type']) else "Unknown"
                logger.info(f"   {pnl_emoji} {trade['Coin']}: ${trade['PnL_USD']:.2f} ({trade['PnL_Percent']:+.1f}%) - TP:{tp_info}, SL:{sl_info} - {trade['Exit_Reason']}")
            
        except Exception as e:
            logger.error(f"❌ Error generating summary report: {e}")
    
    def stop_monitoring(self):
        """Stop the monitoring thread"""
        self.monitoring = False
        logger.info("🛑 Stopping monitoring...")
    
    def check_monitoring_status(self):
        """Check if monitoring is running properly"""
        logger.info(f"👁️  Monitoring Status: {'🟢 RUNNING' if self.monitoring else '🔴 STOPPED'}")
        logger.info(f"📊 Active Positions: {len(self.positions)}")
        logger.info(f"🧵 Thread Alive: {'✅' if hasattr(self, 'monitor_thread') and self.monitor_thread.is_alive() else '❌'}")
        
        if self.positions:
            logger.info("📋 Current Positions:")
            for symbol, pos in self.positions.items():
                logger.info(f"   • {pos['coin']} - Entry: ${pos['entry_price']:.6f} - TP: {pos['tp_type']} - SL: {pos['sl_type']}")
    
    def force_restart_monitoring(self):
        """Force restart monitoring thread"""
        try:
            # Stop current monitoring
            self.monitoring = False
            if hasattr(self, 'monitor_thread'):
                self.monitor_thread.join(timeout=5)
            
            # Start new monitoring
            self.monitoring = True
            self.monitor_thread = threading.Thread(target=self._monitor_loop)
            self.monitor_thread.daemon = True
            self.monitor_thread.start()
            
            logger.info("🔄 Monitoring forcefully restarted!")
                
        except Exception as e:
            logger.error(f"❌ Error restarting monitoring: {e}")
    
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
            if self.positions and not hasattr(self, 'monitor_thread') or not self.monitor_thread.is_alive():
                self.force_restart_monitoring()


# Create bot instance with connection test - only if not already created
if 'bot' not in globals() or bot is None:
    bot = AutoTrader()
else:
    # Restart monitoring if it's stopped
    if not bot.monitoring:
        bot.restart_monitoring()
        
        
        
# # Enhanced Trading Bot Usage - Now with Swing High/Low Options

# # 1. BASIC TRADING OPTIONS
# # ATR-based take profit and stop loss (default)
# bot.trade('BTCUSDT', 100)

# # Fixed percentage take profit with ATR stop loss
# bot.trade('ETHUSDT', 50, use_fixed_tp=True, fixed_tp_percent=3.0)

# # 2. NEW SWING HIGH/LOW OPTIONS
# # Use swing high as take profit target
# bot.trade('BTCUSDT', 100, use_swing_tp=True)

# # Use swing low as stop loss
# bot.trade('ETHUSDT', 50, use_swing_sl=True)

# # Use both swing high TP and swing low SL
# bot.trade('ADAUSDT', 75, use_swing_tp=True, use_swing_sl=True)

# # Custom swing lookback period (default is 5)
# bot.trade('SOLUSDT', 60, use_swing_tp=True, swing_lookback=7)

# # 3. COMBINATION STRATEGIES
# # Swing high TP with ATR stop loss
# bot.trade('BNBUSDT', 80, use_swing_tp=True)

# # ATR take profit with swing low stop loss  
# bot.trade('DOTUSDT', 45, use_swing_sl=True)

# # Fixed TP with swing low SL
# bot.trade('LINKUSDT', 90, use_fixed_tp=True, fixed_tp_percent=4.0, use_swing_sl=True)

# # All options combined (swing levels take priority if available)
# bot.trade('MATICUSDT', 55, take_profit_ratio=2.5, use_fixed_tp=True, 
#           fixed_tp_percent=3.5, use_swing_tp=True, use_swing_sl=True, swing_lookback=6)

# # 4. ENHANCED POSITION MANAGEMENT
# # Switch between different take profit types
# bot.switch_levels('BTCUSDT', switch_tp='swing')    # Switch to swing high TP
# bot.switch_levels('BTCUSDT', switch_tp='atr')      # Switch to ATR TP
# bot.switch_levels('BTCUSDT', switch_tp='fixed')    # Switch to fixed % TP

# # Switch between different stop loss types
# bot.switch_levels('ETHUSDT', switch_sl='swing')    # Switch to swing low SL
# bot.switch_levels('ETHUSDT', switch_sl='atr')      # Switch to ATR SL

# # Switch both TP and SL simultaneously
# bot.switch_levels('ADAUSDT', switch_tp='swing', switch_sl='swing')

# # 5. ENHANCED STATUS MONITORING
# bot.status()  # Now shows TP/SL types and alternative levels

# # 6. TRADE FUNCTION PARAMETERS EXPLAINED:
# """
# bot.trade(coin_pair, amount, take_profit_ratio=2.0, use_fixed_tp=False, 
#           fixed_tp_percent=2.5, use_swing_tp=False, use_swing_sl=False, swing_lookback=5)

# NEW Parameters:
# - use_swing_tp: Boolean - Use swing high as take profit (default False)
# - use_swing_sl: Boolean - Use swing low as stop loss (default False)  
# - swing_lookback: Integer - Periods for swing point calculation (default 5)

# Priority Order:
# 1. Take Profit: Swing High > Fixed % > ATR-based
# 2. Stop Loss: Swing Low > ATR-based

# Examples with NEW options:
# bot.trade('BTCUSDT', 100, use_swing_tp=True)                    # Swing high TP, ATR SL
# bot.trade('ETHUSDT', 50, use_swing_sl=True)                     # ATR TP, swing low SL
# bot.trade('ADAUSDT', 75, use_swing_tp=True, use_swing_sl=True)  # Both swing levels
# bot.trade('SOLUSDT', 60, use_swing_tp=True, swing_lookback=8)   # Custom lookback period
# """

# # 7. LEVEL SWITCHING FUNCTION:
# """
# bot.switch_levels(coin_pair, switch_tp=None, switch_sl=None)

# Parameters:
# - switch_tp: 'atr', 'fixed', 'swing' or None
# - switch_sl: 'atr', 'swing' or None

# Examples:
# bot.switch_levels('BTCUSDT', switch_tp='swing')          # Change to swing high TP
# bot.switch_levels('ETHUSDT', switch_sl='swing')          # Change to swing low SL
# bot.switch_levels('ADAUSDT', 'swing', 'swing')           # Change both to swing levels
# """

# # 8. HOW SWING LEVELS WORK:
# """
# Swing High Take Profit:
# - Analyzes recent price data to find swing highs (peaks)
# - Uses the most relevant swing high above current price as resistance
# - Provides natural take profit levels based on market structure

# Swing Low Stop Loss:
# - Analyzes recent price data to find swing lows (troughs)
# - Uses the most relevant swing low below current price as support
# - Provides natural stop loss levels based on market structure

# Lookback Period:
# - Default 5 periods means a point must be higher/lower than 5 periods before and after
# - Larger values (7-10) find more significant swing points but may be further away
# - Smaller values (3-4) find closer swing points but may be less reliable
# """

# # 9. AUTOMATIC FALLBACKS:
# """
# The bot automatically handles cases where swing levels aren't available:

# If swing high not found or invalid:
# - Falls back to ATR-based or fixed percentage take profit
# - Logs warning and shows what method is being used instead

# If swing low not found or invalid:
# - Falls back to ATR-based stop loss
# - Logs warning and shows fallback method

# This ensures trades always execute even if swing analysis fails.
# """

# # 10. ENHANCED REPORTING:
# """
# CSV reports now include:
# - TP_Type: "ATR-based", "Fixed %", or "Swing High"
# - SL_Type: "ATR-based" or "Swing Low" 
# - Swing_High_TP: The swing high level if calculated
# - Swing_Low_SL: The swing low level if calculated

# Summary reports show performance breakdown by strategy type.
# """

# # EXAMPLE TRADING SCENARIOS:

# # Scenario 1: Breakout trader using swing levels
# bot.trade('BTCUSDT', 200, use_swing_tp=True, use_swing_sl=True)

# # Scenario 2: Conservative trader with tight fixed stops
# bot.trade('ETHUSDT', 100, use_fixed_tp=True, fixed_tp_percent=2.0, use_swing_sl=True)

# # Scenario 3: Momentum trader with wide ATR levels
# bot.trade('SOLUSDT', 150, take_profit_ratio=3.0, swing_lookback=3)

# # Scenario 4: Adaptive trader who switches based on conditions
# bot.trade('ADAUSDT', 80, use_swing_tp=True)
# # Later switch if market conditions change:
# bot.switch_levels('ADAUSDT', switch_tp='fixed')  # Switch to fixed TP if swing level too far