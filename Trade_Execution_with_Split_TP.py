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
        Enhanced ATR Trading Bot with Tiered Take Profit Strategy - Trades USDT pairs only
        """
        self.exchange = None  # Will be initialized in buy_signal
        
        # Trading parameters
        self.timeframe = '15m'
        self.atr_period = 14
        self.max_stop_percent = 2.0  # Reduced for scalping
        self.min_stop_percent = 0.2
        
        # Tiered take profit settings
        self.tp1_percent = 0.5   # First target: 0.5%
        self.tp2_percent = 1.2   # Second target: 1.2%
        self.tp3_percent = 2.5   # Third target: 2.5%
        
        # Position allocation per tier
        self.tp1_allocation = 0.5  # 50% of position
        self.tp2_allocation = 0.3  # 30% of position
        self.tp3_allocation = 0.2  # 20% of position (will be trailed)
        
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
        
        logger.info("Enhanced ATR Trading Bot with Tiered Take Profit initialized successfully")
    
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
                    'Stop_Loss', 'TP1_Price', 'TP2_Price', 'TP3_Price', 
                    'TP1_Hit', 'TP2_Hit', 'TP3_Hit', 'ATR_Percent', 'Multiplier'
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
                    trade_data.get('tp1_price', ''),
                    trade_data.get('tp2_price', ''),
                    trade_data.get('tp3_price', ''),
                    trade_data.get('tp1_hit', ''),
                    trade_data.get('tp2_hit', ''),
                    trade_data.get('tp3_hit', ''),
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
    
    def get_dynamic_stop_percent(self, atr_value, current_price):
        """Dynamic stop loss based on ATR volatility"""
        atr_percentage = (atr_value / current_price) * 100
        
        if atr_percentage < 1.0:
            return 0.4  # Low volatility - tighter stop
        elif atr_percentage <= 2.5:
            return 0.6  # Normal volatility
        else:
            return 0.8  # High volatility - wider stop
    
    def calculate_tiered_levels(self, entry_price, atr_value):
        """Calculate tiered take profit levels and dynamic stop loss"""
        atr_percentage = (atr_value / entry_price) * 100
        
        # Dynamic stop loss based on volatility
        stop_percent = self.get_dynamic_stop_percent(atr_value, entry_price)
        stop_price = entry_price * (1 - stop_percent / 100)
        
        # Tiered take profit levels - percentage based for crypto scalping
        tp1_price = entry_price * (1 + self.tp1_percent / 100)  # 0.5%
        tp2_price = entry_price * (1 + self.tp2_percent / 100)  # 1.2%
        tp3_price = entry_price * (1 + self.tp3_percent / 100)  # 2.5%
        
        return {
            'stop_price': round(stop_price, 8),
            'tp1_price': round(tp1_price, 8),
            'tp2_price': round(tp2_price, 8),
            'tp3_price': round(tp3_price, 8),
            'atr_percent': atr_percentage,
            'stop_percent': stop_percent
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
        Enhanced buy signal with tiered take profit strategy
        
        Args:
            base_symbol (str): Base currency (e.g., 'BTC', 'ETH')
            trade_amount_usdt (float): Total amount to invest in USDT
        """
        try:
            # Initialize exchange
            self._initialize_exchange()
            
            # Convert base symbol to USDT pair
            symbol = f"{base_symbol.upper()}/USDT"
            
            logger.info(f"🚀 BUY SIGNAL: {symbol}")
            logger.info(f"💰 Investment Amount: {trade_amount_usdt} USDT")
            logger.info(f"🌐 Trading on Real account with Tiered Take Profit")
            
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
            
            # Calculate tiered levels
            levels = self.calculate_tiered_levels(current_price, atr_value)
            
            # Calculate position size based on investment amount
            total_position_size = trade_amount_usdt / current_price
            total_position_size = round(total_position_size, 8)
            
            if total_position_size <= 0:
                return {'success': False, 'message': 'Invalid position size'}
            
            # Calculate tier sizes
            tp1_size = round(total_position_size * self.tp1_allocation, 8)
            tp2_size = round(total_position_size * self.tp2_allocation, 8)
            tp3_size = round(total_position_size * self.tp3_allocation, 8)
            
            # Adjust for rounding differences
            total_allocated = tp1_size + tp2_size + tp3_size
            if total_allocated != total_position_size:
                tp1_size = total_position_size - tp2_size - tp3_size
            
            # Display trade details
            risk_amount = (current_price - levels['stop_price']) * total_position_size
            potential_tp1 = (levels['tp1_price'] - current_price) * tp1_size
            potential_tp2 = (levels['tp2_price'] - current_price) * tp2_size
            potential_tp3 = (levels['tp3_price'] - current_price) * tp3_size
            total_potential = potential_tp1 + potential_tp2 + potential_tp3
            
            logger.info(f"📊 Current Price: {current_price}")
            logger.info(f"📊 Total Position Size: {total_position_size}")
            logger.info(f"📊 Stop Loss: {levels['stop_price']} ({levels['stop_percent']:.1f}%) - Risk: ${risk_amount:.2f}")
            logger.info(f"📊 TP1 ({self.tp1_percent}%): {levels['tp1_price']} - Size: {tp1_size} - Profit: ${potential_tp1:.2f}")
            logger.info(f"📊 TP2 ({self.tp2_percent}%): {levels['tp2_price']} - Size: {tp2_size} - Profit: ${potential_tp2:.2f}")
            logger.info(f"📊 TP3 ({self.tp3_percent}%): {levels['tp3_price']} - Size: {tp3_size} - Profit: ${potential_tp3:.2f}")
            logger.info(f"📊 Total Potential Profit: ${total_potential:.2f}")
            logger.info(f"📊 ATR%: {levels['atr_percent']:.2f}%")
            
            # Execute market buy order
            entry_order = self.place_market_order(symbol, 'buy', total_position_size)
            if not entry_order:
                return {'success': False, 'message': 'Failed to place entry order'}
            
            # Get actual fill price
            entry_price = float(entry_order['average']) if entry_order['average'] else current_price
            
            # Recalculate levels with actual entry price
            levels = self.calculate_tiered_levels(entry_price, atr_value)
            
            # Place stop loss order
            stop_order = self.place_stop_loss_order(
                symbol, 'sell', total_position_size, levels['stop_price']
            )
            
            # Place tiered take profit orders
            tp1_order = self.place_take_profit_order(
                symbol, 'sell', tp1_size, levels['tp1_price']
            )
            
            tp2_order = self.place_take_profit_order(
                symbol, 'sell', tp2_size, levels['tp2_price']
            )
            
            tp3_order = self.place_take_profit_order(
                symbol, 'sell', tp3_size, levels['tp3_price']
            )
            
            # Generate unique trade ID
            trade_id = str(uuid.uuid4())
            
            # Store position data
            self.active_positions[symbol] = {
                'trade_id': trade_id,
                'side': 'buy',
                'total_amount': total_position_size,
                'remaining_amount': total_position_size,
                'entry_price': entry_price,
                'stop_price': levels['stop_price'],
                'tp1_price': levels['tp1_price'],
                'tp2_price': levels['tp2_price'],
                'tp3_price': levels['tp3_price'],
                'tp1_size': tp1_size,
                'tp2_size': tp2_size,
                'tp3_size': tp3_size,
                'entry_order_id': entry_order['id'],
                'stop_order_id': stop_order['id'] if stop_order else None,
                'tp1_order_id': tp1_order['id'] if tp1_order else None,
                'tp2_order_id': tp2_order['id'] if tp2_order else None,
                'tp3_order_id': tp3_order['id'] if tp3_order else None,
                'tp1_hit': False,
                'tp2_hit': False,
                'tp3_hit': False,
                'entry_time': datetime.now(),
                'atr_percent': levels['atr_percent'],
                'stop_percent': levels['stop_percent'],
                'stop_moved_to_breakeven': False,
                'investment_amount': trade_amount_usdt,
                'risk_amount': risk_amount,
                'total_potential_profit': total_potential,
                'realized_profit': 0.0
            }
            
            # Log trade to CSV
            self._log_trade_to_csv({
                'trade_id': trade_id,
                'symbol': symbol,
                'side': 'buy',
                'entry_time': self.active_positions[symbol]['entry_time'].strftime('%Y-%m-%d %H:%M:%S'),
                'entry_price': entry_price,
                'amount': total_position_size,
                'stop_price': levels['stop_price'],
                'tp1_price': levels['tp1_price'],
                'tp2_price': levels['tp2_price'],
                'tp3_price': levels['tp3_price'],
                'atr_percent': levels['atr_percent'],
                'multiplier': levels['stop_percent']
            })
            
            logger.info(f"✅ Tiered position opened for {symbol}")
            logger.info(f"📈 Entry: {entry_price}")
            logger.info(f"🎯 Strategy: 50% @ {self.tp1_percent}%, 30% @ {self.tp2_percent}%, 20% @ {self.tp3_percent}%")
            
            return {
                'success': True,
                'symbol': symbol,
                'strategy': 'Tiered Take Profit',
                'investment_amount': trade_amount_usdt,
                'total_position_size': total_position_size,
                'entry_price': entry_price,
                'stop_price': levels['stop_price'],
                'tp_levels': {
                    'tp1': {'price': levels['tp1_price'], 'size': tp1_size, 'percent': self.tp1_percent},
                    'tp2': {'price': levels['tp2_price'], 'size': tp2_size, 'percent': self.tp2_percent},
                    'tp3': {'price': levels['tp3_price'], 'size': tp3_size, 'percent': self.tp3_percent}
                },
                'risk_amount': risk_amount,
                'total_potential_profit': total_potential,
                'atr_percent': levels['atr_percent']
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
            
            # Cancel all pending orders
            for order_type in ['stop_order_id', 'tp1_order_id', 'tp2_order_id', 'tp3_order_id']:
                if position.get(order_type):
                    self.cancel_order(position[order_type], symbol)
            
            # Close remaining position with market order
            if position['remaining_amount'] > 0:
                close_order = self.place_market_order(symbol, 'sell', position['remaining_amount'])
                
                if close_order:
                    exit_price = float(close_order['average']) if close_order['average'] else 0
                    final_pnl = (exit_price - position['entry_price']) * position['remaining_amount']
                    total_pnl = position['realized_profit'] + final_pnl
                    
                    logger.info(f"✅ Position closed manually for {symbol}")
                    logger.info(f"💰 Total P&L: ${total_pnl:.2f}")
                    
                    del self.active_positions[symbol]
                    return {
                        'success': True, 
                        'message': 'Position closed',
                        'total_pnl': total_pnl,
                        'exit_price': exit_price
                    }
            else:
                del self.active_positions[symbol]
                return {
                    'success': True,
                    'message': 'Position already fully closed via take profits',
                    'total_pnl': position['realized_profit']
                }
                
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
                        unrealized_pnl = (current_price - pos['entry_price']) * pos['remaining_amount']
                        total_pnl = pos['realized_profit'] + unrealized_pnl
                        pnl_percent = ((current_price - pos['entry_price']) / pos['entry_price']) * 100
                        
                        return {
                            'symbol': symbol,
                            'strategy': 'Tiered Take Profit',
                            'investment_amount': pos['investment_amount'],
                            'total_position_size': pos['total_amount'],
                            'remaining_amount': pos['remaining_amount'],
                            'entry_price': pos['entry_price'],
                            'current_price': current_price,
                            'stop_price': pos['stop_price'],
                            'tp_levels': {
                                'tp1': {'price': pos['tp1_price'], 'hit': pos['tp1_hit']},
                                'tp2': {'price': pos['tp2_price'], 'hit': pos['tp2_hit']},
                                'tp3': {'price': pos['tp3_price'], 'hit': pos['tp3_hit']}
                            },
                            'realized_profit': round(pos['realized_profit'], 2),
                            'unrealized_pnl': round(unrealized_pnl, 2),
                            'total_pnl': round(total_pnl, 2),
                            'pnl_percent': round(pnl_percent, 2),
                            'entry_time': pos['entry_time'].strftime('%Y-%m-%d %H:%M:%S'),
                            'stop_moved': pos['stop_moved_to_breakeven'],
                            'atr_percent': pos['atr_percent']
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
        """Check if stop should be moved to breakeven after TP1 is hit"""
        try:
            # Move to breakeven only after TP1 is hit
            if not position['tp1_hit']:
                return False
                
            # Re-initialize exchange
            self._initialize_exchange()
            
            # Get current price
            atr_data = self.calculate_atr(symbol, limit=5)
            if not atr_data:
                return False
                
            _, current_price, _ = atr_data
            
            # Check if still in profit and not already moved
            in_profit = current_price > position['entry_price']
                
            return in_profit and not position.get('stop_moved_to_breakeven', False)
            
        except Exception as e:
            logger.error(f"Error checking trailing stop: {e}")
            return False
    
    def _move_stop_to_breakeven(self, symbol, position):
        """Move stop loss to breakeven after TP1 is hit"""
        try:
            # Re-initialize exchange
            self._initialize_exchange()
            
            # Cancel existing stop loss
            if position.get('stop_order_id'):
                self.cancel_order(position['stop_order_id'], symbol)
            
            # Place new stop at breakeven
            breakeven_price = position['entry_price']
            
            new_stop_order = self.place_stop_loss_order(
                symbol, 'sell', position['remaining_amount'], breakeven_price
            )
            
            if new_stop_order:
                position['stop_order_id'] = new_stop_order['id']
                position['stop_price'] = breakeven_price
                position['stop_moved_to_breakeven'] = True
                
                logger.info(f"🔄 Stop moved to breakeven for {symbol}: {breakeven_price}")
                
        except Exception as e:
            logger.error(f"Error moving stop to breakeven: {e}")
    
    def _monitor_positions(self):
        """Enhanced monitoring for tiered take profit positions"""
        while self.monitoring:
            try:
                for symbol in list(self.active_positions.keys()):
                    position = self.active_positions[symbol]
                    
                    # Re-initialize exchange
                    self._initialize_exchange()
                    
                    # Check if stop should be moved to breakeven (after TP1)
                    if self._check_trailing_stop(symbol, position):
                        self._move_stop_to_breakeven(symbol, position)
                    
                    # Check if orders are filled
                    position_closed = False
                    
                    # Check stop loss
                    if position.get('stop_order_id') and position['remaining_amount'] > 0:
                        try:
                            order_status = self.exchange.fetch_order(position['stop_order_id'], symbol)
                            if order_status['status'] == 'filled':
                                actual_loss = (float(order_status['average']) - position['entry_price']) * position['remaining_amount'] if order_status['average'] else 0
                                exit_price = float(order_status['average']) if order_status['average'] else position['stop_price']
                                
                                total_pnl = position['realized_profit'] + actual_loss
                                
                                # Log final trade to CSV
                                self._log_trade_to_csv({
                                    'trade_id': position['trade_id'],
                                    'symbol': symbol,
                                    'side': 'buy',
                                    'entry_time': position['entry_time'].strftime('%Y-%m-%d %H:%M:%S'),
                                    'exit_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                                    'entry_price': position['entry_price'],
                                    'exit_price': exit_price,
                                    'amount': position['total_amount'],
                                    'profit_loss': total_pnl,
                                    'stop_price': position['stop_price'],
                                    'tp1_price': position['tp1_price'],
                                    'tp2_price': position['tp2_price'],
                                    'tp3_price': position['tp3_price'],
                                    'tp1_hit': position['tp1_hit'],
                                    'tp2_hit': position['tp2_hit'],
                                    'tp3_hit': position['tp3_hit'],
                                    'atr_percent': position['atr_percent'],
                                    'multiplier': position['stop_percent']
                                })
                                
                                logger.info(f"🛑 Stop loss hit for {symbol} - Total P&L: ${total_pnl:.2f}")
                                
                                # Cancel remaining TP orders
                                for tp_order in ['tp1_order_id', 'tp2_order_id', 'tp3_order_id']:
                                    if position.get(tp_order):
                                        self.cancel_order(position[tp_order], symbol)
                                
                                del self.active_positions[symbol]
                                position_closed = True
                        except:
                            pass
                    
                    if not position_closed:
                        # Check TP1
                        if position.get('tp1_order_id') and not position['tp1_hit']:
                            try:
                                order_status = self.exchange.fetch_order(position['tp1_order_id'], symbol)
                                if order_status['status'] == 'filled':
                                    tp1_profit = (float(order_status['average']) - position['entry_price']) * position['tp1_size'] if order_status['average'] else 0
                                    position['realized_profit'] += tp1_profit
                                    position['remaining_amount'] -= position['tp1_size']
                                    position['tp1_hit'] = True
                                    
                                    logger.info(f"🎯 TP1 hit for {symbol} - Profit: ${tp1_profit:.2f} ({self.tp1_percent}%)")
                                    
                                    # Update stop loss amount
                                    if position.get('stop_order_id'):
                                        self.cancel_order(position['stop_order_id'], symbol)
                                        new_stop = self.place_stop_loss_order(symbol, 'sell', position['remaining_amount'], position['stop_price'])
                                        if new_stop:
                                            position['stop_order_id'] = new_stop['id']
                            except:
                                pass
                        
                        # Check TP2
                        if position.get('tp2_order_id') and not position['tp2_hit']:
                            try:
                                order_status = self.exchange.fetch_order(position['tp2_order_id'], symbol)
                                if order_status['status'] == 'filled':
                                    tp2_profit = (float(order_status['average']) - position['entry_price']) * position['tp2_size'] if order_status['average'] else 0
                                    position['realized_profit'] += tp2_profit
                                    position['remaining_amount'] -= position['tp2_size']
                                    position['tp2_hit'] = True
                                    
                                    logger.info(f"🎯 TP2 hit for {symbol} - Profit: ${tp2_profit:.2f} ({self.tp2_percent}%)")
                                    
                                    # Update stop loss amount
                                    if position.get('stop_order_id'):
                                        self.cancel_order(position['stop_order_id'], symbol)
                                        new_stop = self.place_stop_loss_order(symbol, 'sell', position['remaining_amount'], position['stop_price'])
                                        if new_stop:
                                            position['stop_order_id'] = new_stop['id']
                            except:
                                pass
                        
                        # Check TP3
                        if position.get('tp3_order_id') and not position['tp3_hit']:
                            try:
                                order_status = self.exchange.fetch_order(position['tp3_order_id'], symbol)
                                if order_status['status'] == 'filled':
                                    tp3_profit = (float(order_status['average']) - position['entry_price']) * position['tp3_size'] if order_status['average'] else 0
                                    position['realized_profit'] += tp3_profit
                                    position['remaining_amount'] -= position['tp3_size']
                                    position['tp3_hit'] = True
                                    
                                    logger.info(f"🎯 TP3 hit for {symbol} - Profit: ${tp3_profit:.2f} ({self.tp3_percent}%)")
                                    logger.info(f"✅ All targets hit for {symbol} - Total Profit: ${position['realized_profit']:.2f}")
                                    
                                    # Log final successful trade to CSV
                                    self._log_trade_to_csv({
                                        'trade_id': position['trade_id'],
                                        'symbol': symbol,
                                        'side': 'buy',
                                        'entry_time': position['entry_time'].strftime('%Y-%m-%d %H:%M:%S'),
                                        'exit_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                                        'entry_price': position['entry_price'],
                                        'exit_price': position['tp3_price'],
                                        'amount': position['total_amount'],
                                        'profit_loss': position['realized_profit'],
                                        'stop_price': position['stop_price'],
                                        'tp1_price': position['tp1_price'],
                                        'tp2_price': position['tp2_price'],
                                        'tp3_price': position['tp3_price'],
                                        'tp1_hit': position['tp1_hit'],
                                        'tp2_hit': position['tp2_hit'],
                                        'tp3_hit': position['tp3_hit'],
                                        'atr_percent': position['atr_percent'],
                                        'multiplier': position['stop_percent']
                                    })
                                    
                                    # Cancel stop loss as position is fully closed
                                    if position.get('stop_order_id'):
                                        self.cancel_order(position['stop_order_id'], symbol)
                                    
                                    # Position fully closed
                                    if position['remaining_amount'] <= 0:
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
if __name__ == "__main__":
    # Initialize bot
    bot = SimpleATRTradingBot()
    
    print("🤖 Enhanced ATR Trading Bot with Tiered Take Profit Ready!")
    print("\n📋 Strategy Overview:")
    print("   • 50% of position exits at 0.5% profit (TP1)")
    print("   • 30% of position exits at 1.2% profit (TP2)")
    print("   • 20% of position exits at 2.5% profit (TP3)")
    print("   • Stop loss moves to breakeven after TP1 is hit")
    print("   • Dynamic stop loss based on ATR volatility (0.4-0.8%)")
    print("\n📋 How to use:")
    print("   bot.buy_signal('BTC', 1000)   # Trade $1000 in BTC/USDT")
    print("   bot.buy_signal('ETH', 500)    # Trade $500 in ETH/USDT") 
    print("   bot.get_position_status()     # Check all positions")
    print("   bot.close_position('BTC')     # Close BTC/USDT position manually")
    
    # Example usage:
    """
    # Enhanced buy signals with tiered take profit
    result = bot.buy_signal('BTC', 1000)    # Trade $1000 in Bitcoin
    result = bot.buy_signal('ETH', 500)     # Trade $500 in Ethereum
    result = bot.buy_signal('SOL', 300)     # Trade $300 in Solana
    
    # Check positions with detailed TP status
    status = bot.get_position_status()
    print(status)
    
    # Check specific position
    btc_status = bot.get_position_status('BTC')
    print(btc_status)
    
    # Example output:
    # {
    #   'symbol': 'BTC/USDT',
    #   'strategy': 'Tiered Take Profit',
    #   'tp_levels': {
    #     'tp1': {'price': 50250.0, 'hit': True},
    #     'tp2': {'price': 50600.0, 'hit': False},
    #     'tp3': {'price': 51250.0, 'hit': False}
    #   },
    #   'realized_profit': 125.50,
    #   'unrealized_pnl': 45.30,
    #   'total_pnl': 170.80,
    #   'remaining_amount': 0.015,  # BTC remaining after TP1
    #   'stop_moved': True          # Stop moved to breakeven
    # }
    """