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

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
API_KEY = os.getenv('BINANCE_API_KEY')
API_SECRET = os.getenv('BINANCE_API_SECRET')

class FuturesAutoTrader:
    def __init__(self, reports_folder_path="./home/lisa/Arupreza/LiveBot/"):
        """Initialize futures auto trader with reports folder path"""
        # Initialize exchange for futures trading
        self.exchange = ccxt.binance({
            'enableRateLimit': True,
            'rateLimit': 100,
            'options': {
                'defaultType': 'future',  # Changed to future for USDT-M
                'hedgeMode': False,  # One-way position mode
            },
            'apiKey': API_KEY,
            'secret': API_SECRET,
            'timeout': 10000,
            'sandbox': False
        })
        
        # Test connection immediately
        try:
            self.exchange.load_markets()
            balance = self.exchange.fetch_balance()
            logger.info("✅ Connected to Binance Futures successfully!")
            logger.info(f"💰 USDT Balance: ${balance['USDT']['free']:.2f}")
            logger.info(f"💼 Available Margin: ${balance['USDT']['free']:.2f}")
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
        
        logger.info(f"🤖 Futures Auto Trader Ready! Reports will be saved to: {self.reports_folder}")
    
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
            today = datetime.now().strftime("%Y-%m-%d")
            csv_filename = f"futures_trading_report_{today}.csv"
            csv_filepath = os.path.join(self.reports_folder, csv_filename)
            
            df_new = pd.DataFrame([trade_data])
            
            if os.path.exists(csv_filepath):
                df_existing = pd.read_csv(csv_filepath)
                df_combined = pd.concat([df_existing, df_new], ignore_index=True)
            else:
                df_combined = df_new
            
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
            'Side': pos['side'],
            'Leverage': pos['leverage'],
            'Entry_Price': pos['entry_price'],
            'Quantity': pos['quantity'],
            'Notional_USD': pos['notional'],
            'Margin_Used': pos['margin_used'],
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
            'Side': pos['side'],
            'Leverage': pos['leverage'],
            'Entry_Price': pos['entry_price'],
            'Quantity': pos['quantity'],
            'Notional_USD': pos['notional'],
            'Margin_Used': pos['margin_used'],
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
    
    def _record_trade_exit(self, symbol, pos, exit_price, exit_reason):
        """Record trade exit to CSV"""
        exit_time = datetime.now()
        
        # Calculate P&L for futures
        if pos['side'] == 'long':
            pnl_usd = (exit_price - pos['entry_price']) * pos['quantity']
        else:  # short
            pnl_usd = (pos['entry_price'] - exit_price) * pos['quantity']
            
        pnl_percent = (pnl_usd / pos['margin_used']) * 100
        
        duration = exit_time - pos['entry_time']
        duration_minutes = int(duration.total_seconds() / 60)
        
        trade_data = {
            'Date': exit_time.strftime("%Y-%m-%d"),
            'Time': exit_time.strftime("%H:%M:%S"),
            'Action': 'EXIT',
            'Coin': pos['coin'],
            'Symbol': symbol,
            'Side': pos['side'],
            'Leverage': pos['leverage'],
            'Entry_Price': pos['entry_price'],
            'Quantity': pos['quantity'],
            'Notional_USD': pos['notional'],
            'Margin_Used': pos['margin_used'],
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

    def _find_swing_high_low(self, df, lookback=10):
        """
        Find the last swing high and swing low from price data
        
        Parameters:
        - df: DataFrame with OHLCV data
        - lookback: Number of periods to look back for swing detection
        
        Returns:
        - dict with 'swing_high' and 'swing_low' prices
        """
        try:
            if len(df) < lookback * 2:
                logger.warning("⚠️ Not enough data for swing detection, using fallback")
                return {
                    'swing_high': df['high'].max(),
                    'swing_low': df['low'].min()
                }
            
            swing_high = None
            swing_low = None
            
            # Find swing highs (peaks)
            for i in range(lookback, len(df) - lookback):
                is_swing_high = True
                current_high = df['high'].iloc[i]
                
                # Check if current high is higher than lookback periods before and after
                for j in range(i - lookback, i + lookback + 1):
                    if j != i and df['high'].iloc[j] >= current_high:
                        is_swing_high = False
                        break
                
                if is_swing_high:
                    swing_high = current_high
            
            # Find swing lows (valleys)
            for i in range(lookback, len(df) - lookback):
                is_swing_low = True
                current_low = df['low'].iloc[i]
                
                # Check if current low is lower than lookback periods before and after
                for j in range(i - lookback, i + lookback + 1):
                    if j != i and df['low'].iloc[j] <= current_low:
                        is_swing_low = False
                        break
                
                if is_swing_low:
                    swing_low = current_low
            
            # If no swing points found, use recent highs/lows
            if swing_high is None:
                swing_high = df['high'].tail(20).max()
                logger.info("📊 No swing high found, using recent high")
            
            if swing_low is None:
                swing_low = df['low'].tail(20).min()
                logger.info("📊 No swing low found, using recent low")
            
            return {
                'swing_high': swing_high,
                'swing_low': swing_low
            }
            
        except Exception as e:
            logger.error(f"❌ Error finding swing points: {e}")
            # Fallback to simple high/low
            return {
                'swing_high': df['high'].max(),
                'swing_low': df['low'].min()
            }
    
    def trade(self, coin_pair, margin_amount, leverage=5, side='long', take_profit_ratio=2.0, use_fixed_tp=False, fixed_tp_percent=2.5, use_swing_levels=False, swing_lookback=10):
        """
        Execute a futures trade with isolated margin
        
        Parameters:
        - coin_pair: Trading pair (e.g., 'BTCUSDT')
        - margin_amount: USD amount to use as margin
        - leverage: Leverage multiplier (1-125x depending on symbol)
        - side: 'long' or 'short'
        - take_profit_ratio: Risk/reward ratio for ATR-based TP
        - use_fixed_tp: Use fixed percentage TP instead of ATR
        - fixed_tp_percent: Fixed TP percentage
        
        Examples:
        - trade('BTCUSDT', 100, 5, 'long') - Long BTC with $100 margin at 5x leverage
        - trade('ETHUSDT', 50, 10, 'short') - Short ETH with $50 margin at 10x leverage
        - trade('ADAUSDT', 25, 3, 'long', use_fixed_tp=True, fixed_tp_percent=3.0)
        """
        try:
            logger.info(f"🚀 INITIATING FUTURES TRADE: {coin_pair.upper()} {side.upper()} with ${margin_amount} margin at {leverage}x")
            
            # Convert to proper symbol format
            coin_pair = coin_pair.upper()
            if not coin_pair.endswith('USDT'):
                coin_pair += 'USDT'
            
            symbol = coin_pair  # Futures uses BTCUSDT format directly
            coin = coin_pair.replace('USDT', '')
            
            logger.info(f"📊 Processing {symbol} - {side.upper()} position...")
            
            # Check if already in position
            if symbol in self.positions:
                logger.warning(f"❌ Already trading {symbol}")
                return False
            
            # Validate side
            if side.lower() not in ['long', 'short']:
                logger.error(f"❌ Invalid side: {side}. Use 'long' or 'short'")
                return False
            
            side = side.lower()
            
            # Check balance
            logger.info("💰 Checking balance...")
            balance = self.exchange.fetch_balance()
            usdt_balance = balance['USDT']['free']
            
            if usdt_balance < margin_amount:
                logger.error(f"❌ Insufficient balance. Have ${usdt_balance:.2f}, need ${margin_amount}")
                return False
            
            logger.info(f"✅ Balance sufficient: ${usdt_balance:.2f}")
            
            # Get market info and set leverage
            logger.info("📈 Fetching market data...")
            markets = self.exchange.load_markets()
            market = markets[symbol]
            
            # Set leverage for this symbol
            try:
                self.exchange.set_leverage(leverage, symbol)
                logger.info(f"⚡ Leverage set to {leverage}x for {symbol}")
            except Exception as e:
                logger.warning(f"⚠️ Could not set leverage: {e}")
            
            # Set margin mode to isolated
            try:
                self.exchange.set_margin_mode('isolated', symbol)
                logger.info(f"🔒 Margin mode set to isolated for {symbol}")
            except Exception as e:
                logger.warning(f"⚠️ Could not set margin mode: {e}")
            
            # Get current price
            ticker = self.exchange.fetch_ticker(symbol)
            current_price = ticker['last']
            logger.info(f"📊 Current price: ${current_price:.8f}")
            
            # Calculate position size
            notional_value = margin_amount * leverage
            quantity = notional_value / current_price
            
            # Handle precision
            precision = market['precision']['amount']
            if isinstance(precision, float):
                precision = int(-1 * math.log10(precision))
            
            factor = 10 ** precision
            quantity = math.floor(quantity * factor) / factor
            
            logger.info(f"📊 Position Details:")
            logger.info(f"   Margin: ${margin_amount}")
            logger.info(f"   Leverage: {leverage}x")
            logger.info(f"   Notional: ${notional_value:.2f}")
            logger.info(f"   Quantity: {quantity:.8f} {coin}")
            
            # Check minimum order size
            min_amount = market['limits']['amount']['min']
            if quantity < min_amount:
                logger.error(f"❌ Position size too small: {quantity:.8f} (min: {min_amount})")
                return False
            
            # Get OHLCV for ATR and swing calculation
            try:
                ohlcv = self.exchange.fetch_ohlcv(symbol, self.timeframe, limit=100)  # Increased limit for swing detection
                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)
                atr_value = df['atr'].iloc[-1]
                
                # Find swing levels if requested
                if use_swing_levels:
                    swing_levels = self._find_swing_high_low(df, swing_lookback)
                    swing_high = swing_levels['swing_high']
                    swing_low = swing_levels['swing_low']
                    logger.info(f"📊 Swing High: ${swing_high:.8f} | Swing Low: ${swing_low:.8f}")
                
                logger.info(f"📊 ATR value: ${atr_value:.8f}")
            except Exception as e:
                logger.error(f"❌ Error fetching OHLCV: {e}")
                atr_value = current_price * 0.02  # 2% fallback
                use_swing_levels = False  # Disable swing levels on error
                logger.info(f"📊 Using fallback ATR: ${atr_value:.8f}")
            
            # Calculate stop loss and take profit levels
            if use_swing_levels:
                # Use swing levels for TP/SL
                if side == 'long':
                    stop_loss = swing_low
                    swing_take_profit = swing_high
                    # Ensure swing levels make sense
                    if stop_loss >= current_price:
                        stop_loss = current_price * 0.97  # 3% below as fallback
                        logger.warning("⚠️ Swing low above entry, using 3% stop loss")
                    if swing_take_profit <= current_price:
                        swing_take_profit = current_price * 1.05  # 5% above as fallback
                        logger.warning("⚠️ Swing high below entry, using 5% take profit")
                else:  # short
                    stop_loss = swing_high
                    swing_take_profit = swing_low
                    # Ensure swing levels make sense
                    if stop_loss <= current_price:
                        stop_loss = current_price * 1.03  # 3% above as fallback
                        logger.warning("⚠️ Swing high below entry, using 3% stop loss")
                    if swing_take_profit >= current_price:
                        swing_take_profit = current_price * 0.95  # 5% below as fallback
                        logger.warning("⚠️ Swing low above entry, using 5% take profit")
                
                # Calculate ATR and fixed levels as alternatives
                stop_distance = abs(current_price - stop_loss)
                if side == 'long':
                    atr_take_profit = current_price + (stop_distance * take_profit_ratio)
                    fixed_take_profit = current_price * (1 + fixed_tp_percent / 100)
                else:
                    atr_take_profit = current_price - (stop_distance * take_profit_ratio)
                    fixed_take_profit = current_price * (1 - fixed_tp_percent / 100)
                
                take_profit = swing_take_profit
                tp_type = f"Swing levels (lookback: {swing_lookback})"
                
            else:
                # Use ATR-based or fixed percentage levels
                stop_distance = atr_value * 1.5
                
                if side == 'long':
                    stop_loss = current_price - stop_distance
                    atr_take_profit = current_price + (stop_distance * take_profit_ratio)
                    fixed_take_profit = current_price * (1 + fixed_tp_percent / 100)
                    swing_take_profit = swing_high if 'swing_high' in locals() else current_price * 1.05
                else:  # short
                    stop_loss = current_price + stop_distance
                    atr_take_profit = current_price - (stop_distance * take_profit_ratio)
                    fixed_take_profit = current_price * (1 - fixed_tp_percent / 100)
                    swing_take_profit = swing_low if 'swing_low' in locals() else current_price * 0.95
                
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
            
            # Execute the futures order
            logger.info("🔥 EXECUTING FUTURES ORDER...")
            start_time = time.time()
            
            try:
                order_side = 'buy' if side == 'long' else 'sell'
                order = self.exchange.create_market_order(symbol, order_side, quantity)
                execution_time = time.time() - start_time
                
                logger.info(f"⚡ Order executed in {execution_time:.2f} seconds")
                
                # Get actual fill price
                if order['average']:
                    entry_price = float(order['average'])
                else:
                    entry_price = current_price
                
                logger.info(f"✅ FUTURES ORDER FILLED!")
                logger.info(f"   Side: {side.upper()}")
                logger.info(f"   Entry Price: ${entry_price:.8f}")
                logger.info(f"   Quantity: {quantity:.8f} {coin}")
                logger.info(f"   Notional: ${entry_price * quantity:.2f}")
                logger.info(f"   Margin Used: ${margin_amount}")
                
            except Exception as e:
                logger.error(f"❌ Order execution failed: {e}")
                return False
            
            # Recalculate levels with actual entry price if needed
            if abs(entry_price - current_price) > (current_price * 0.001):
                logger.info("🔄 Recalculating levels with actual entry price...")
                
                if use_swing_levels:
                    # Swing levels don't change with entry price, but validate them
                    if side == 'long':
                        if stop_loss >= entry_price:
                            stop_loss = entry_price * 0.97
                            logger.warning("⚠️ Adjusted swing stop loss for actual entry")
                        if swing_take_profit <= entry_price:
                            swing_take_profit = entry_price * 1.05
                            logger.warning("⚠️ Adjusted swing take profit for actual entry")
                    else:  # short
                        if stop_loss <= entry_price:
                            stop_loss = entry_price * 1.03
                            logger.warning("⚠️ Adjusted swing stop loss for actual entry")
                        if swing_take_profit >= entry_price:
                            swing_take_profit = entry_price * 0.95
                            logger.warning("⚠️ Adjusted swing take profit for actual entry")
                    
                    take_profit = swing_take_profit
                    
                    # Recalculate ATR and fixed alternatives with actual entry
                    stop_distance = abs(entry_price - stop_loss)
                    if side == 'long':
                        atr_take_profit = entry_price + (stop_distance * take_profit_ratio)
                        fixed_take_profit = entry_price * (1 + fixed_tp_percent / 100)
                    else:
                        atr_take_profit = entry_price - (stop_distance * take_profit_ratio)
                        fixed_take_profit = entry_price * (1 - fixed_tp_percent / 100)
                
                else:
                    # Recalculate ATR and fixed levels
                    if side == 'long':
                        stop_loss = entry_price - stop_distance
                        atr_take_profit = entry_price + (stop_distance * take_profit_ratio)
                        fixed_take_profit = entry_price * (1 + fixed_tp_percent / 100)
                    else:
                        stop_loss = entry_price + stop_distance
                        atr_take_profit = entry_price - (stop_distance * take_profit_ratio)
                        fixed_take_profit = entry_price * (1 - fixed_tp_percent / 100)
                    
                    if use_fixed_tp:
                        take_profit = fixed_take_profit
                    else:
                        take_profit = atr_take_profit
            
            # Store position
            self.positions[symbol] = {
                'coin': coin,
                'coin_pair': coin_pair,
                'side': side,
                'leverage': leverage,
                'entry_price': entry_price,
                'quantity': quantity,
                'notional': entry_price * quantity,
                'margin_used': margin_amount,
                'stop_loss': stop_loss,
                'take_profit': take_profit,
                'atr_take_profit': atr_take_profit,
                'fixed_take_profit': fixed_take_profit,
                'entry_time': datetime.now(),
                'take_profit_ratio': take_profit_ratio,
                'fixed_tp_percent': fixed_tp_percent,
                'stop_moved_to_breakeven': False,
                'use_fixed_tp': use_fixed_tp,
                'tp_type': tp_type
            }
            
            # Calculate risk/reward
            if side == 'long':
                risk = stop_distance * quantity
                reward = (take_profit - entry_price) * quantity if use_fixed_tp else (stop_distance * take_profit_ratio) * quantity
            else:
                risk = stop_distance * quantity
                reward = (entry_price - take_profit) * quantity if use_fixed_tp else (stop_distance * take_profit_ratio) * quantity
            
            actual_ratio = reward / risk if risk > 0 else 0
            
            # Log final summary
            logger.info(f"✅ FUTURES TRADE EXECUTED - {coin} {side.upper()}")
            logger.info(f"💰 Entry Price: ${entry_price:.8f}")
            logger.info(f"📊 Quantity: {quantity:.8f} {coin}")
            logger.info(f"💸 Notional: ${entry_price * quantity:.2f}")
            logger.info(f"💼 Margin Used: ${margin_amount}")
            logger.info(f"⚡ Leverage: {leverage}x")
            logger.info(f"🛑 Stop Loss: ${stop_loss:.8f} (Risk: ${risk:.2f})")
            logger.info(f"🎯 Take Profit: ${take_profit:.8f} (Reward: ${reward:.2f})")
            logger.info(f"📈 Type: {tp_type}")
            logger.info(f"⚖️ Risk/Reward: 1:{actual_ratio:.2f}")
            
            # Record trade entry
            self._record_trade_entry(symbol, self.positions[symbol])
            
            logger.info("🎯 Futures trade is now being monitored automatically!")
            return True
            
        except Exception as e:
            logger.error(f"❌ Critical error in futures trade execution: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False
    
    def status(self):
        """Show status of all positions"""
        if not self.positions:
            logger.info("📋 No active futures trades")
            return
        
        logger.info("📊 ACTIVE FUTURES POSITIONS STATUS")
        
        total_margin_used = 0
        total_unrealized_pnl = 0
        
        for symbol, pos in self.positions.items():
            try:
                ticker = self.exchange.fetch_ticker(symbol)
                current = ticker['last']
                
                # Calculate P&L based on side
                if pos['side'] == 'long':
                    pnl = (current - pos['entry_price']) * pos['quantity']
                else:  # short
                    pnl = (pos['entry_price'] - current) * pos['quantity']
                
                pnl_pct = (pnl / pos['margin_used']) * 100
                
                total_margin_used += pos['margin_used']
                total_unrealized_pnl += pnl
                
                # Calculate distances to stop and target
                if pos['side'] == 'long':
                    stop_distance = ((current - pos['stop_loss']) / current) * 100
                    target_distance = ((pos['take_profit'] - current) / current) * 100
                else:
                    stop_distance = ((pos['stop_loss'] - current) / current) * 100
                    target_distance = ((current - pos['take_profit']) / current) * 100
                
                # Time tracking
                time_passed = datetime.now() - pos['entry_time']
                hours_passed = time_passed.total_seconds() / 3600
                
                logger.info(f"🪙 {pos['coin']} ({pos['side'].upper()}) - {pos['leverage']}x:")
                logger.info(f"   💰 Entry: ${pos['entry_price']:.8f} → Current: ${current:.8f}")
                logger.info(f"   📈 P&L: ${pnl:.2f} ({pnl_pct:+.2f}%) | Margin: ${pos['margin_used']:.2f}")
                logger.info(f"   🛑 Stop: ${pos['stop_loss']:.8f} ({stop_distance:+.2f}%)")
                logger.info(f"   🎯 Target: ${pos['take_profit']:.8f} ({target_distance:+.2f}%)")
                logger.info(f"   📊 TP Type: {pos['tp_type']}")
                logger.info(f"   ⏱️ Time: {hours_passed:.1f}h | Breakeven: {'✅' if pos['stop_moved_to_breakeven'] else '❌'}")
                
            except Exception as e:
                logger.error(f"❌ Error getting {symbol} status: {e}")
        
        # Portfolio summary
        total_pnl_pct = (total_unrealized_pnl / total_margin_used * 100) if total_margin_used > 0 else 0
        
        logger.info(f"💼 FUTURES PORTFOLIO SUMMARY")
        logger.info(f"   💸 Total Margin Used: ${total_margin_used:.2f}")
        logger.info(f"   📈 Unrealized P&L: ${total_unrealized_pnl:.2f} ({total_pnl_pct:+.2f}%)")
    
    def close(self, coin_pair):
        """Manually close a futures position"""
        try:
            coin_pair = coin_pair.upper()
            if not coin_pair.endswith('USDT'):
                coin_pair += 'USDT'
            
            symbol = coin_pair
            coin = coin_pair.replace('USDT', '')
            
            logger.info(f"🔄 CLOSING FUTURES POSITION: {coin}")
            
            if symbol not in self.positions:
                logger.info(f"❌ No active position for {symbol}")
                return False
            
            pos = self.positions[symbol]
            
            # Get current price
            ticker = self.exchange.fetch_ticker(symbol)
            current = ticker['last']
            
            logger.info(f"📊 Position: {pos['side'].upper()} {pos['quantity']:.8f} {coin}")
            logger.info(f"💰 Current Price: ${current:.8f}")
            
            # Execute closing order (opposite side)
            logger.info("🔥 EXECUTING CLOSING ORDER...")
            start_time = time.time()
            
            close_side = 'sell' if pos['side'] == 'long' else 'buy'
            order = self.exchange.create_market_order(symbol, close_side, pos['quantity'])
            execution_time = time.time() - start_time
            
            exit_price = float(order['average']) if order['average'] else current
            
            # Calculate final P&L
            if pos['side'] == 'long':
                pnl = (exit_price - pos['entry_price']) * pos['quantity']
            else:
                pnl = (pos['entry_price'] - exit_price) * pos['quantity']
            
            pnl_pct = (pnl / pos['margin_used']) * 100
            
            logger.info(f"⚡ Order executed in {execution_time:.2f} seconds")
            logger.info(f"✅ FUTURES POSITION CLOSED - {coin}")
            logger.info(f"💰 Exit Price: ${exit_price:.8f}")
            logger.info(f"📈 P&L: ${pnl:.2f} ({pnl_pct:+.2f}%)")
            
            # Record manual exit
            self._record_trade_exit(symbol, pos, exit_price, "MANUAL_CLOSE")
            
            del self.positions[symbol]
            return True
            
        except Exception as e:
            logger.error(f"❌ Error closing futures position: {e}")
            return False
    
    def _monitor_loop(self):
        """Monitor futures positions automatically"""
        logger.info("👁️ Futures monitoring thread started")
        consecutive_errors = 0
        max_consecutive_errors = 5
        
        while self.monitoring:
            try:
                if not self.positions:
                    time.sleep(30)
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
                                if (pos['side'] == 'long' and current_price > pos['entry_price']) or \
                                   (pos['side'] == 'short' and current_price < pos['entry_price']):
                                    pos['stop_loss'] = pos['entry_price']
                                    pos['stop_moved_to_breakeven'] = True
                                    logger.info(f"⏰ {pos['coin']} - Stop moved to breakeven at ${pos['entry_price']:.8f}")
                                    self._record_breakeven_move(symbol, pos)
                        
                        # Check stop loss
                        stop_triggered = False
                        if pos['side'] == 'long' and current_price <= pos['stop_loss']:
                            stop_triggered = True
                        elif pos['side'] == 'short' and current_price >= pos['stop_loss']:
                            stop_triggered = True
                        
                        if stop_triggered:
                            stop_type = "BREAKEVEN" if pos['stop_moved_to_breakeven'] and pos['stop_loss'] == pos['entry_price'] else "STOP_LOSS"
                            logger.info(f"🛑 {stop_type} TRIGGERED - {pos['coin']} at ${current_price:.8f}")
                            
                            if self._execute_futures_exit(symbol, pos, current_price, stop_type):
                                del self.positions[symbol]
                        
                        # Check take profit
                        elif ((pos['side'] == 'long' and current_price >= pos['take_profit']) or 
                              (pos['side'] == 'short' and current_price <= pos['take_profit'])):
                            logger.info(f"🎯 TAKE PROFIT TRIGGERED - {pos['coin']} at ${current_price:.8f}")
                            
                            if self._execute_futures_exit(symbol, pos, current_price, "TAKE_PROFIT"):
                                del self.positions[symbol]
                    
                    except Exception as e:
                        logger.error(f"❌ Error monitoring {symbol}: {e}")
                        consecutive_errors += 1
                
                consecutive_errors = 0
                time.sleep(30)
                
            except Exception as e:
                consecutive_errors += 1
                logger.error(f"❌ Monitor loop error #{consecutive_errors}: {e}")
                
                if consecutive_errors >= max_consecutive_errors:
                    logger.error(f"❌ Too many consecutive errors, stopping monitor")
                    break
                
                time.sleep(60)
        
        logger.info("👁️ Futures monitoring thread stopped")
    
    def _execute_futures_exit(self, symbol, pos, current_price, exit_reason):
        """Execute futures exit order"""
        try:
            logger.info(f"🔥 Executing {exit_reason} exit: {pos['side']} {pos['quantity']:.8f} {pos['coin']}")
            
            close_side = 'sell' if pos['side'] == 'long' else 'buy'
            order = self.exchange.create_market_order(symbol, close_side, pos['quantity'])
            exit_price = float(order['average']) if order['average'] else current_price
            
            # Calculate final P&L
            if pos['side'] == 'long':
                pnl = (exit_price - pos['entry_price']) * pos['quantity']
            else:
                pnl = (pos['entry_price'] - exit_price) * pos['quantity']
            
            pnl_pct = (pnl / pos['margin_used']) * 100
            
            logger.info(f"✅ {exit_reason} executed!")
            logger.info(f"   Exit Price: ${exit_price:.8f}")
            logger.info(f"   P&L: ${pnl:.2f} ({pnl_pct:+.2f}%)")
            
            # Record exit
            self._record_trade_exit(symbol, pos, exit_price, exit_reason)
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error executing futures exit for {symbol}: {e}")
            return False
    
    def switch_take_profit(self, coin_pair, tp_type=None):
        """
        Switch between different take profit types for an active position
        
        Parameters:
        - coin_pair: Trading pair
        - tp_type: 'atr', 'fixed', 'swing', or None to cycle through options
        """
        try:
            coin_pair = coin_pair.upper()
            if not coin_pair.endswith('USDT'):
                coin_pair += 'USDT'
            
            symbol = coin_pair
            coin = coin_pair.replace('USDT', '')
            
            if symbol not in self.positions:
                logger.warning(f"❌ No active position for {symbol}")
                return False
            
            pos = self.positions[symbol]
            
            # Determine new take profit type
            if tp_type is None:
                # Cycle through options
                if pos['use_swing_levels']:
                    new_tp_type = 'atr'
                elif pos['use_fixed_tp']:
                    new_tp_type = 'swing' if pos.get('swing_take_profit') else 'atr'
                else:  # currently ATR
                    new_tp_type = 'fixed'
            else:
                new_tp_type = tp_type.lower()
            
            # Update take profit based on type
            if new_tp_type == 'swing' and pos.get('swing_take_profit'):
                pos['take_profit'] = pos['swing_take_profit']
                pos['tp_type'] = f"Swing levels (lookback: {pos.get('swing_lookback', 'N/A')})"
                pos['use_swing_levels'] = True
                pos['use_fixed_tp'] = False
            elif new_tp_type == 'fixed':
                pos['take_profit'] = pos['fixed_take_profit']
                pos['tp_type'] = f"Fixed {pos['fixed_tp_percent']}%"
                pos['use_swing_levels'] = False
                pos['use_fixed_tp'] = True
            else:  # ATR
                pos['take_profit'] = pos['atr_take_profit']
                pos['tp_type'] = f"ATR-based (1:{pos['take_profit_ratio']})"
                pos['use_swing_levels'] = False
                pos['use_fixed_tp'] = False
            
            logger.info(f"🔄 SWITCHED TAKE PROFIT - {coin}")
            logger.info(f"🎯 New Take Profit: ${pos['take_profit']:.8f}")
            logger.info(f"📊 Type: {pos['tp_type']}")
            
            # Show alternatives
            alternatives = []
            if pos.get('atr_take_profit') and not (not pos['use_swing_levels'] and not pos['use_fixed_tp']):
                alternatives.append(f"ATR: ${pos['atr_take_profit']:.8f}")
            if pos.get('fixed_take_profit') and not pos['use_fixed_tp']:
                alternatives.append(f"Fixed: ${pos['fixed_take_profit']:.8f}")
            if pos.get('swing_take_profit') and not pos['use_swing_levels']:
                alternatives.append(f"Swing: ${pos['swing_take_profit']:.8f}")
            
            if alternatives:
                logger.info(f"🔄 Alternatives: {' | '.join(alternatives)}")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error switching take profit: {e}")
            return False
    
    def set_leverage(self, coin_pair, leverage):
        """Set leverage for a specific symbol"""
        try:
            coin_pair = coin_pair.upper()
            if not coin_pair.endswith('USDT'):
                coin_pair += 'USDT'
            
            symbol = coin_pair
            
            self.exchange.set_leverage(leverage, symbol)
            logger.info(f"⚡ Leverage set to {leverage}x for {symbol}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error setting leverage: {e}")
            return False
    
    def get_account_info(self):
        """Get futures account information"""
        try:
            balance = self.exchange.fetch_balance()
            positions = self.exchange.fetch_positions()
            
            # Filter only positions with size > 0
            active_positions = [pos for pos in positions if float(pos['contracts']) > 0]
            
            logger.info("💼 FUTURES ACCOUNT INFO")
            logger.info(f"💰 USDT Balance: ${balance['USDT']['free']:.2f}")
            logger.info(f"💼 Used Margin: ${balance['USDT']['used']:.2f}")
            logger.info(f"📊 Total Balance: ${balance['USDT']['total']:.2f}")
            
            if active_positions:
                logger.info(f"📈 Active Positions: {len(active_positions)}")
                for pos in active_positions:
                    side = "LONG" if pos['side'] == 'long' else "SHORT"
                    pnl = pos['unrealizedPnl'] or 0
                    logger.info(f"   • {pos['symbol']}: {side} ${pnl:+.2f}")
            else:
                logger.info("📊 No active positions")
                
            return balance
            
        except Exception as e:
            logger.error(f"❌ Error getting account info: {e}")
            return None
    
    def generate_summary_report(self, date=None):
        """Generate summary report for futures trading"""
        try:
            if date is None:
                date = datetime.now().strftime("%Y-%m-%d")
            
            csv_filename = f"futures_trading_report_{date}.csv"
            csv_filepath = os.path.join(self.reports_folder, csv_filename)
            
            if not os.path.exists(csv_filepath):
                logger.info(f"📊 No futures trading data found for {date}")
                return
            
            # Read the CSV
            df = pd.read_csv(csv_filepath)
            
            # Filter only exit trades for P&L calculation
            exits = df[df['Action'] == 'EXIT'].copy()
            
            if exits.empty:
                logger.info(f"📊 No completed futures trades found for {date}")
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
            
            # Leverage statistics
            avg_leverage = exits['Leverage'].mean() if 'Leverage' in exits.columns else 0
            
            # Side distribution
            long_trades = len(exits[exits['Side'] == 'long']) if 'Side' in exits.columns else 0
            short_trades = len(exits[exits['Side'] == 'short']) if 'Side' in exits.columns else 0
            
            # Log summary
            logger.info(f"📊 FUTURES TRADING SUMMARY - {date}")
            logger.info(f"📈 Total Trades: {total_trades}")
            logger.info(f"📊 Long Trades: {long_trades} | Short Trades: {short_trades}")
            logger.info(f"✅ Winning Trades: {winning_trades}")
            logger.info(f"❌ Losing Trades: {losing_trades}")
            logger.info(f"➖ Breakeven Trades: {breakeven_trades}")
            logger.info(f"🎯 Win Rate: {win_rate:.1f}%")
            logger.info(f"💰 Total P&L: ${total_pnl:.2f}")
            logger.info(f"📊 Average Win: ${avg_win:.2f}")
            logger.info(f"📊 Average Loss: ${avg_loss:.2f}")
            logger.info(f"🏆 Best Trade: ${best_trade:.2f}")
            logger.info(f"💔 Worst Trade: ${worst_trade:.2f}")
            logger.info(f"⏱️ Average Duration: {avg_duration:.0f} minutes")
            logger.info(f"⚡ Average Leverage: {avg_leverage:.1f}x")
            if avg_loss != 0:
                logger.info(f"⚖️ Risk/Reward Ratio: 1:{abs(avg_win/avg_loss):.2f}")
            
            # Log trade details
            logger.info("📋 TRADE DETAILS:")
            for _, trade in exits.iterrows():
                pnl_emoji = "📈" if trade['PnL_USD'] > 0 else "📉" if trade['PnL_USD'] < 0 else "➖"
                side_info = f" ({trade['Side'].upper()})" if 'Side' in trade else ""
                leverage_info = f" {trade['Leverage']:.0f}x" if 'Leverage' in trade else ""
                logger.info(f"   {pnl_emoji} {trade['Coin']}{side_info}{leverage_info}: ${trade['PnL_USD']:.2f} ({trade['PnL_Percent']:+.1f}%) - {trade['Exit_Reason']}")
            
        except Exception as e:
            logger.error(f"❌ Error generating futures summary report: {e}")
    
    def stop_monitoring(self):
        """Stop the monitoring thread"""
        self.monitoring = False
        logger.info("🛑 Stopping futures monitoring...")
    
    def check_monitoring_status(self):
        """Check if monitoring is running properly"""
        logger.info(f"👁️ Futures Monitoring Status: {'🟢 RUNNING' if self.monitoring else '🔴 STOPPED'}")
        logger.info(f"📊 Active Positions: {len(self.positions)}")
        logger.info(f"🧵 Thread Alive: {'✅' if hasattr(self, 'monitor_thread') and self.monitor_thread.is_alive() else '❌'}")
        
        if self.positions:
            logger.info("📋 Current Positions:")
            for symbol, pos in self.positions.items():
                logger.info(f"   • {pos['coin']} {pos['side'].upper()} {pos['leverage']}x - Entry: ${pos['entry_price']:.6f}")
    
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
            
            logger.info("🔄 Futures monitoring forcefully restarted!")
                
        except Exception as e:
            logger.error(f"❌ Error restarting futures monitoring: {e}")
    
    def restart_monitoring(self):
        """Restart monitoring if stopped"""
        if not self.monitoring:
            self.monitoring = True
            self.monitor_thread = threading.Thread(target=self._monitor_loop)
            self.monitor_thread.daemon = True
            self.monitor_thread.start()
            logger.info("🔄 Futures monitoring restarted!")
        else:
            logger.info("👁️ Futures monitoring is already running")
            if self.positions and (not hasattr(self, 'monitor_thread') or not self.monitor_thread.is_alive()):
                self.force_restart_monitoring()


# Create futures bot instance - only if not already created
if 'futures_bot' not in globals() or futures_bot is None:
    futures_bot = FuturesAutoTrader()
else:
    # Restart monitoring if it's stopped
    if not futures_bot.monitoring:
        futures_bot.restart_monitoring()

# Usage Examples:
"""
# Long trade examples with different TP/SL methods:

# 1. ATR-based levels (default)
futures_bot.trade('BTCUSDT', 100, 5, 'long')  
futures_bot.trade('ETHUSDT', 50, 10, 'long', take_profit_ratio=3.0)  # 1:3 risk/reward

# 2. Fixed percentage levels
futures_bot.trade('BTCUSDT', 100, 5, 'long', use_fixed_tp=True, fixed_tp_percent=3.0)
futures_bot.trade('ADAUSDT', 25, 3, 'long', use_fixed_tp=True, fixed_tp_percent=2.5)

# 3. Swing-based levels (NEW!)
futures_bot.trade('BTCUSDT', 100, 5, 'long', use_swing_levels=True)  # TP = last swing high, SL = last swing low
futures_bot.trade('ETHUSDT', 50, 10, 'long', use_swing_levels=True, swing_lookback=15)  # Custom lookback period

# Short trade examples:
futures_bot.trade('BTCUSDT', 100, 5, 'short', use_swing_levels=True)  # TP = last swing low, SL = last swing high
futures_bot.trade('ETHUSDT', 50, 8, 'short', use_fixed_tp=True, fixed_tp_percent=4.0)

# Switch between TP types for active positions:
futures_bot.switch_take_profit('BTCUSDT', 'swing')  # Switch to swing levels
futures_bot.switch_take_profit('ETHUSDT', 'fixed')  # Switch to fixed %
futures_bot.switch_take_profit('ADAUSDT', 'atr')    # Switch to ATR-based
futures_bot.switch_take_profit('SOLUSDT')           # Cycle through all options

# Other commands:
futures_bot.status()  # Check all positions with their TP/SL types
futures_bot.close('BTCUSDT')  # Close BTC position
futures_bot.get_account_info()  # Check account balance
futures_bot.generate_summary_report()  # Generate daily report
"""