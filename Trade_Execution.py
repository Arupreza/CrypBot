import ccxt
import pandas as pd
import pandas_ta as ta
import time
import logging
from datetime import datetime, timedelta
import json
import threading
import os
import csv
from dotenv import load_dotenv
import uuid
import numpy as np

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
API_KEY = os.getenv('BINANCE_API_KEY')
API_SECRET = os.getenv('BINANCE_API_SECRET')

class SimpleATRTradingBot:
    def __init__(self):
        """
        Simple ATR Trading Bot - Trades USDT pairs only
        """
        self.exchange = None  # Will be initialized in buy_signal
        
        # Trading parameters
        self.timeframe = '15m'
        self.atr_period = 14
        self.max_stop_percent = 5.0
        self.min_stop_percent = 0.2
        self.risk_reward_ratio = 2.5
        self.candles_to_trail = 2
        
        # Active positions tracking
        self.active_positions = {}
        
        # Trade history CSV setup
        self.trade_history_file = 'trade_history.csv'
        self._initialize_trade_history_csv()
        
        # Start monitoring thread
        self.monitoring = True
        self.monitor_thread = threading.Thread(target=self._monitor_positions)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()
        
        logger.info("Simple ATR Trading Bot initialized successfully")
    
    def _initialize_exchange(self):
        """Initialize exchange with real account"""
        if not API_KEY or not API_SECRET:
            raise ValueError("API Key or Secret not found in .env file")
        
        config = {
            'enableRateLimit': True,
            'options': {
                'defaultType': 'spot'
            },
            'apiKey': API_KEY,
            'secret': API_SECRET
        }
        
        logger.info("Initializing Binance Real exchange")
        self.exchange = ccxt.binance(config)

    def _initialize_trade_history_csv(self):
        """Initialize trade history CSV file if it doesn't exist"""
        if not os.path.exists(self.trade_history_file):
            with open(self.trade_history_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'Trade_ID', 'Symbol', 'Side', 'Entry_Time', 'Exit_Time', 
                    'Entry_Price', 'Exit_Price', 'Amount', 'Profit_Loss',
                    'Stop_Loss', 'Take_Profit', 'ATR_Percent', 'Multiplier'
                ])
    
    def _log_trade_to_csv(self, trade_data):
        """Log trade to CSV file"""
        try:
            with open(self.trade_history_file, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    trade_data.get('trade_id', ''),
                    trade_data.get('symbol', ''),
                    trade_data.get('side', ''),
                    trade_data.get('entry_time', ''),
                    trade_data.get('exit_time', ''),
                    trade_data.get('entry_price', ''),
                    trade_data.get('exit_price', ''),
                    trade_data.get('amount', ''),
                    trade_data.get('profit_loss', ''),
                    trade_data.get('stop_price', ''),
                    trade_data.get('take_profit', ''),
                    trade_data.get('atr_percent', ''),
                    trade_data.get('multiplier', '')
                ])
        except Exception as e:
            logger.error(f"Error logging trade to CSV: {e}")
    
    def calculate_atr(self, symbol, limit=50):
        """Calculate ATR for given symbol using pandas-ta"""
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, self.timeframe, limit=limit)
            
            if len(ohlcv) < self.atr_period:
                logger.error(f"Insufficient data for ATR calculation: {len(ohlcv)} candles")
                return None
            
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            # Calculate ATR using pandas-ta
            df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=self.atr_period)
            
            current_atr = df['atr'].iloc[-1]
            current_price = df['close'].iloc[-1]
            
            return current_atr, current_price, df
            
        except Exception as e:
            logger.error(f"Error calculating ATR for {symbol}: {e}")
            return None
    
    def get_universal_atr_multiplier(self, atr_value, current_price):
        """Universal ATR Multiplier System"""
        atr_percentage = (atr_value / current_price) * 100
        
        if atr_percentage < 1.0:
            multiplier = 1.5  # Low volatility
        elif atr_percentage <= 3.0:
            multiplier = 1.0  # Normal volatility
        else:
            multiplier = 0.7  # High volatility
            
        return multiplier, atr_percentage
    
    def calculate_levels(self, entry_price, atr_value):
        """Calculate stop loss and take profit levels for LONG position"""
        multiplier, atr_percent = self.get_universal_atr_multiplier(atr_value, entry_price)
        
        # Calculate stop distance
        stop_distance = atr_value * multiplier
        
        # Apply safety limits
        max_stop_distance = entry_price * (self.max_stop_percent / 100)
        min_stop_distance = entry_price * (self.min_stop_percent / 100)
        stop_distance = min(max(stop_distance, min_stop_distance), max_stop_distance)
        
        # Calculate levels for LONG position
        stop_price = entry_price - stop_distance
        take_profit = entry_price + (stop_distance * self.risk_reward_ratio)
        
        return {
            'stop_price': round(stop_price, 8),
            'take_profit': round(take_profit, 8),
            'stop_distance': stop_distance,
            'atr_percent': atr_percent,
            'multiplier': multiplier
        }
    
    def get_account_balance(self, asset='USDT'):
        """Get account balance"""
        try:
            balance = self.exchange.fetch_balance()
            return float(balance[asset]['free'])
        except Exception as e:
            logger.error(f"Error fetching balance: {e}")
            return 0
    
    def place_market_order(self, symbol, side, amount):
        """Place market order"""
        try:
            order = self.exchange.create_market_order(symbol, side, amount)
            logger.info(f"✅ Market order executed: {side.upper()} {amount} {symbol}")
            return order
        except Exception as e:
            logger.error(f"❌ Error placing market order: {e}")
            return None
    
    def place_stop_loss_order(self, symbol, side, amount, stop_price):
        """Place stop loss order"""
        try:
            order = self.exchange.create_order(
                symbol=symbol,
                type='stop_loss_limit',
                side=side,
                amount=amount,
                price=stop_price * 0.99 if side == 'sell' else stop_price * 1.01,
                params={'stopPrice': stop_price}
            )
            logger.info(f"🛡️ Stop loss set: {side.upper()} {amount} {symbol} at {stop_price}")
            return order
        except Exception as e:
            logger.error(f"❌ Error placing stop loss: {e}")
            return None
    
    def place_take_profit_order(self, symbol, side, amount, take_profit_price):
        """Place take profit order"""
        try:
            order = self.exchange.create_limit_order(symbol, side, amount, take_profit_price)
            logger.info(f"🎯 Take profit set: {side.upper()} {amount} {symbol} at {take_profit_price}")
            return order
        except Exception as e:
            logger.error(f"❌ Error placing take profit: {e}")
            return None
    
    def cancel_order(self, order_id, symbol):
        """Cancel an order"""
        try:
            result = self.exchange.cancel_order(order_id, symbol)
            logger.info(f"❌ Order cancelled: {order_id}")
            return result
        except Exception as e:
            logger.error(f"Error cancelling order {order_id}: {e}")
            return None
    
    def buy_signal(self, base_symbol, trade_amount_usdt):
        """
        Simple buy signal - accepts base symbol and amount to invest
        
        Args:
            base_symbol (str): Base currency (e.g., 'BTC', 'ETH')
            trade_amount_usdt (float): Total amount to invest in USDT
            
        Example:
            bot.buy_signal('BTC', 1000)   # Trade $1000 in BTC/USDT
            bot.buy_signal('ETH', 500)    # Trade $500 in ETH/USDT
        """
        try:
            # Initialize exchange
            self._initialize_exchange()
            
            # Convert base symbol to USDT pair
            symbol = f"{base_symbol.upper()}/USDT"
            
            logger.info(f"🚀 BUY SIGNAL: {symbol}")
            logger.info(f"💰 Investment Amount: {trade_amount_usdt} USDT")
            logger.info(f"🌐 Trading on Real account")
            
            # Check if position already exists
            if symbol in self.active_positions:
                logger.warning(f"⚠️ Position already exists for {symbol}")
                return {'success': False, 'message': 'Position already exists'}
            
            # Check balance
            balance = self.get_account_balance('USDT')
            if balance < trade_amount_usdt:
                logger.error(f"❌ Insufficient balance. Available: {balance} USDT, Required: {trade_amount_usdt} USDT")
                return {'success': False, 'message': 'Insufficient balance'}
            
            # Get current price and calculate ATR
            atr_data = self.calculate_atr(symbol)
            if not atr_data:
                return {'success': False, 'message': 'Failed to calculate ATR'}
            
            atr_value, current_price, _ = atr_data
            
            # Calculate stop loss and take profit levels
            levels = self.calculate_levels(current_price, atr_value)
            
            # Calculate position size based on investment amount
            position_size = trade_amount_usdt / current_price
            position_size = round(position_size, 8)
            
            if position_size <= 0:
                return {'success': False, 'message': 'Invalid position size'}
            
            # Display trade details
            risk_amount = (current_price - levels['stop_price']) * position_size
            potential_profit = (levels['take_profit'] - current_price) * position_size
            
            logger.info(f"📊 Current Price: {current_price}")
            logger.info(f"📊 Position Size: {position_size}")
            logger.info(f"📊 Stop Loss: {levels['stop_price']} (Risk: ${risk_amount:.2f})")
            logger.info(f"📊 Take Profit: {levels['take_profit']} (Potential: ${potential_profit:.2f})")
            logger.info(f"📊 ATR%: {levels['atr_percent']:.2f}% | Multiplier: {levels['multiplier']}x")
            
            # Execute market buy order
            entry_order = self.place_market_order(symbol, 'buy', position_size)
            if not entry_order:
                return {'success': False, 'message': 'Failed to place entry order'}
            
            # Get actual fill price
            entry_price = float(entry_order['average']) if entry_order['average'] else current_price
            
            # Recalculate levels with actual entry price
            levels = self.calculate_levels(entry_price, atr_value)
            
            # Recalculate actual risk and profit
            actual_risk = (entry_price - levels['stop_price']) * position_size
            actual_potential = (levels['take_profit'] - entry_price) * position_size
            
            # Place stop loss and take profit orders
            stop_order = self.place_stop_loss_order(
                symbol, 'sell', position_size, levels['stop_price']
            )
            
            tp_order = self.place_take_profit_order(
                symbol, 'sell', position_size, levels['take_profit']
            )
            
            # Generate unique trade ID
            trade_id = str(uuid.uuid4())
            
            # Store position data
            self.active_positions[symbol] = {
                'trade_id': trade_id,
                'side': 'buy',
                'amount': position_size,
                'entry_price': entry_price,
                'stop_price': levels['stop_price'],
                'take_profit': levels['take_profit'],
                'entry_order_id': entry_order['id'],
                'stop_order_id': stop_order['id'] if stop_order else None,
                'tp_order_id': tp_order['id'] if tp_order else None,
                'entry_time': datetime.now(),
                'atr_percent': levels['atr_percent'],
                'multiplier': levels['multiplier'],
                'stop_moved_to_breakeven': False,
                'investment_amount': trade_amount_usdt,
                'risk_amount': actual_risk,
                'potential_profit': actual_potential
            }
            
            # Log trade to CSV
            self._log_trade_to_csv({
                'trade_id': trade_id,
                'symbol': symbol,
                'side': 'buy',
                'entry_time': self.active_positions[symbol]['entry_time'].strftime('%Y-%m-%d %H:%M:%S'),
                'entry_price': entry_price,
                'amount': position_size,
                'stop_price': levels['stop_price'],
                'take_profit': levels['take_profit'],
                'atr_percent': levels['atr_percent'],
                'multiplier': levels['multiplier']
            })
            
            logger.info(f"✅ Position opened for {symbol}")
            logger.info(f"📈 Entry: {entry_price}")
            logger.info(f"🛡️ Stop: {levels['stop_price']} (Risk: ${actual_risk:.2f})")
            logger.info(f"🎯 Target: {levels['take_profit']} (Profit: ${actual_potential:.2f})")
            
            return {
                'success': True,
                'symbol': symbol,
                'investment_amount': trade_amount_usdt,
                'position_size': position_size,
                'entry_price': entry_price,
                'stop_price': levels['stop_price'],
                'take_profit': levels['take_profit'],
                'risk_amount': actual_risk,
                'potential_profit': actual_potential,
                'risk_reward_ratio': f"1:{actual_potential/actual_risk:.1f}",
                'atr_percent': levels['atr_percent'],
                'multiplier': levels['multiplier']
            }
            
        except Exception as e:
            logger.error(f"❌ Error executing buy signal: {e}")
            return {'success': False, 'message': str(e)}
    
    def close_position(self, base_symbol):
        """Manually close a position"""
        try:
            symbol = f"{base_symbol.upper()}/USDT"
            if symbol not in self.active_positions:
                logger.warning(f"⚠️ No active position found for {symbol}")
                return {'success': False, 'message': 'No active position'}
            
            position = self.active_positions[symbol]
            
            # Re-initialize exchange
            self._initialize_exchange()
            
            # Cancel pending orders
            if position.get('stop_order_id'):
                self.cancel_order(position['stop_order_id'], symbol)
            if position.get('tp_order_id'):
                self.cancel_order(position['tp_order_id'], symbol)
            
            # Close position with market order
            close_order = self.place_market_order(symbol, 'sell', position['amount'])
            
            if close_order:
                # Calculate actual P&L
                exit_price = float(close_order['average']) if close_order['average'] else 0
                actual_pnl = (exit_price - position['entry_price']) * position['amount']
                
                # Update trade history in CSV
                self._log_trade_to_csv({
                    'trade_id': position['trade_id'],
                    'symbol': symbol,
                    'side': 'buy',
                    'entry_time': position['entry_time'].strftime('%Y-%m-%d %H:%M:%S'),
                    'exit_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'entry_price': position['entry_price'],
                    'exit_price': exit_price,
                    'amount': position['amount'],
                    'profit_loss': actual_pnl,
                    'stop_price': position['stop_price'],
                    'take_profit': position['take_profit'],
                    'atr_percent': position['atr_percent'],
                    'multiplier': position['multiplier']
                })
                
                logger.info(f"✅ Position closed manually for {symbol}")
                logger.info(f"💰 P&L: ${actual_pnl:.2f}")
                
                del self.active_positions[symbol]
                return {
                    'success': True, 
                    'message': 'Position closed',
                    'pnl': actual_pnl,
                    'exit_price': exit_price
                }
            else:
                return {'success': False, 'message': 'Failed to close position'}
                
        except Exception as e:
            logger.error(f"❌ Error closing position: {e}")
            return {'success': False, 'message': str(e)}
    
    def get_position_status(self, base_symbol=None):
        """Get status of positions"""
        try:
            if base_symbol:
                symbol = f"{base_symbol.upper()}/USDT"
                if symbol in self.active_positions:
                    pos = self.active_positions[symbol]
                    # Re-initialize exchange
                    self._initialize_exchange()
                    # Get current price for PnL calculation
                    atr_data = self.calculate_atr(symbol, limit=5)
                    if atr_data:
                        _, current_price, _ = atr_data
                        unrealized_pnl = (current_price - pos['entry_price']) * pos['amount']
                        pnl_percent = ((current_price - pos['entry_price']) / pos['entry_price']) * 100
                        
                        return {
                            'symbol': symbol,
                            'investment_amount': pos['investment_amount'],
                            'position_size': pos['amount'],
                            'entry_price': pos['entry_price'],
                            'current_price': current_price,
                            'stop_price': pos['stop_price'],
                            'take_profit': pos['take_profit'],
                            'unrealized_pnl': round(unrealized_pnl, 2),
                            'pnl_percent': round(pnl_percent, 2),
                            'risk_amount': round(pos['risk_amount'], 2),
                            'potential_profit': round(pos['potential_profit'], 2),
                            'entry_time': pos['entry_time'].strftime('%Y-%m-%d %H:%M:%S'),
                            'stop_moved': pos['stop_moved_to_breakeven'],
                            'atr_percent': pos['atr_percent'],
                            'multiplier': pos['multiplier']
                        }
                else:
                    return {'message': f'No active position for {symbol}'}
            else:
                # Return all positions
                all_positions = {}
                for sym in self.active_positions:
                    all_positions[sym] = self.get_position_status(sym.split('/')[0])
                return all_positions
                
        except Exception as e:
            logger.error(f"Error getting position status: {e}")
            return {'error': str(e)}
    
    def _check_trailing_stop(self, symbol, position):
        """Check if stop should be moved to breakeven after 2 candles"""
        try:
            # Re-initialize exchange
            self._initialize_exchange()
            
            # Check if 2 candles (30 minutes) have passed
            current_time = datetime.now()
            time_diff = current_time - position['entry_time']
            
            if time_diff < timedelta(minutes=30):
                return False
            
            # Get current price
            atr_data = self.calculate_atr(symbol, limit=5)
            if not atr_data:
                return False
                
            _, current_price, _ = atr_data
            
            # Check if in profit
            in_profit = current_price > position['entry_price']
                
            return in_profit and not position.get('stop_moved_to_breakeven', False)
            
        except Exception as e:
            logger.error(f"Error checking trailing stop: {e}")
            return False
    
    def _move_stop_to_breakeven(self, symbol, position):
        """Move stop loss to breakeven (entry price)"""
        try:
            # Re-initialize exchange
            self._initialize_exchange()
            
            # Cancel existing stop loss
            if position.get('stop_order_id'):
                self.cancel_order(position['stop_order_id'], symbol)
            
            # Place new stop at breakeven
            breakeven_price = position['entry_price']
            
            new_stop_order = self.place_stop_loss_order(
                symbol, 'sell', position['amount'], breakeven_price
            )
            
            if new_stop_order:
                position['stop_order_id'] = new_stop_order['id']
                position['stop_price'] = breakeven_price
                position['stop_moved_to_breakeven'] = True
                
                # Update trade history in CSV with new stop price
                self._log_trade_to_csv({
                    'trade_id': position['trade_id'],
                    'symbol': symbol,
                    'side': 'buy',
                    'entry_time': position['entry_time'].strftime('%Y-%m-%d %H:%M:%S'),
                    'entry_price': position['entry_price'],
                    'amount': position['amount'],
                    'stop_price': breakeven_price,
                    'take_profit': position['take_profit'],
                    'atr_percent': position['atr_percent'],
                    'multiplier': position['multiplier']
                })
                
                logger.info(f"🔄 Stop moved to breakeven for {symbol}: {breakeven_price}")
                
        except Exception as e:
            logger.error(f"Error moving stop to breakeven: {e}")
    
    def _monitor_positions(self):
        """Background monitoring of positions"""
        while self.monitoring:
            try:
                for symbol in list(self.active_positions.keys()):
                    position = self.active_positions[symbol]
                    
                    # Re-initialize exchange
                    self._initialize_exchange()
                    
                    # Check trailing stop condition (move to breakeven after 2 candles in profit)
                    if self._check_trailing_stop(symbol, position):
                        self._move_stop_to_breakeven(symbol, position)
                    
                    # Check if orders are filled
                    position_closed = False
                    
                    # Check stop loss
                    if position.get('stop_order_id'):
                        try:
                            order_status = self.exchange.fetch_order(position['stop_order_id'], symbol)
                            if order_status['status'] == 'filled':
                                actual_loss = (float(order_status['average']) - position['entry_price']) * position['amount'] if order_status['average'] else position['risk_amount']
                                exit_price = float(order_status['average']) if order_status['average'] else position['stop_price']
                                
                                # Log trade to CSV
                                self._log_trade_to_csv({
                                    'trade_id': position['trade_id'],
                                    'symbol': symbol,
                                    'side': 'buy',
                                    'entry_time': position['entry_time'].strftime('%Y-%m-%d %H:%M:%S'),
                                    'exit_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                                    'entry_price': position['entry_price'],
                                    'exit_price': exit_price,
                                    'amount': position['amount'],
                                    'profit_loss': actual_loss,
                                    'stop_price': position['stop_price'],
                                    'take_profit': position['take_profit'],
                                    'atr_percent': position['atr_percent'],
                                    'multiplier': position['multiplier']
                                })
                                
                                logger.info(f"🛑 Stop loss hit for {symbol} - Loss: ${actual_loss:.2f}")
                                if position.get('tp_order_id'):
                                    self.cancel_order(position['tp_order_id'], symbol)
                                del self.active_positions[symbol]
                                position_closed = True
                        except:
                            pass
                    
                    # Check take profit
                    if not position_closed and position.get('tp_order_id'):
                        try:
                            order_status = self.exchange.fetch_order(position['tp_order_id'], symbol)
                            if order_status['status'] == 'filled':
                                actual_profit = (float(order_status['average']) - position['entry_price']) * position['amount'] if order_status['average'] else position['potential_profit']
                                exit_price = float(order_status['average']) if order_status['average'] else position['take_profit']
                                
                                # Log trade to CSV
                                self._log_trade_to_csv({
                                    'trade_id': position['trade_id'],
                                    'symbol': symbol,
                                    'side': 'buy',
                                    'entry_time': position['entry_time'].strftime('%Y-%m-%d %H:%M:%S'),
                                    'exit_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                                    'entry_price': position['entry_price'],
                                    'exit_price': exit_price,
                                    'amount': position['amount'],
                                    'profit_loss': actual_profit,
                                    'stop_price': position['stop_price'],
                                    'take_profit': position['take_profit'],
                                    'atr_percent': position['atr_percent'],
                                    'multiplier': position['multiplier']
                                })
                                
                                logger.info(f"🎯 Take profit hit for {symbol} - Profit: ${actual_profit:.2f}")
                                if position.get('stop_order_id'):
                                    self.cancel_order(position['stop_order_id'], symbol)
                                del self.active_positions[symbol]
                        except:
                            pass
                
                time.sleep(30)  # Check every 30 seconds
                
            except Exception as e:
                logger.error(f"Error in position monitoring: {e}")
                time.sleep(60)
    
    def stop_monitoring(self):
        """Stop the monitoring thread"""
        self.monitoring = False
        logger.info("Position monitoring stopped")

# Example usage
# if __name__ == "__main__":
    # Initialize bot
#    bot = SimpleATRTradingBot()
    
#   print("🤖 Simple ATR Trading Bot Ready!")
#   print("\n📋 How to use:")
#    print("   bot.buy_signal('BTC', 1000)   # Trade $1000 in BTC/USDT")
#    print("   bot.buy_signal('ETH', 500)    # Trade $500 in ETH/USDT") 
#    print("   bot.get_position_status()     # Check all positions")
#    print("   bot.close_position('BTC')     # Close BTC/USDT position manually")
    
    # Example usage:
    """
    # Simple buy signals - just give coin name and investment amount
    result = bot.buy_signal('BTC', 1000)    # Trade $1000 in Bitcoin
    result = bot.buy_signal('ETH', 500)     # Trade $500 in Ethereum
    result = bot.buy_signal('SOL', 300)     # Trade $300 in Solana
    
    # Check positions
    status = bot.get_position_status()
    print(status)
    
    # Check specific position
    btc_status = bot.get_position_status('BTC')
    print(btc_status)
    """