import ccxt
import pandas as pd
import numpy as np
import time
from datetime import datetime, timedelta
import logging
from typing import Dict, List, Optional, Tuple
import os
from dotenv import load_dotenv
import csv
import threading
import sys
from io import StringIO

# Load environment variables from .env file
load_dotenv()

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class BinanceTradingBot:
    def __init__(self, testnet: bool = True):
        """
        Initialize the trading bot with Binance API credentials from environment variables
        
        Args:
            testnet: Use testnet for testing
        """
        api_key = os.getenv('BINANCE_API_KEY')
        api_secret = os.getenv('BINANCE_API_SECRET')
        
        if not api_key or not api_secret:
            raise ValueError("BINANCE_API_KEY and BINANCE_API_SECRET must be set in .env file")
        
        self.exchange = ccxt.binance({
            'apiKey': api_key,
            'secret': api_secret,
            'sandbox': testnet,
            'enableRateLimit': True,
        })
        
        self.testnet = testnet
        self.positions = []
        self.trade_history = []
        self.csv_file = "trade_history.csv"  # Use a single CSV file
        self._initialize_csv()

    def _initialize_csv(self):
        """Initialize CSV file with headers if it doesn't exist"""
        if not os.path.exists(self.csv_file):
            try:
                with open(self.csv_file, 'w', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow([
                        'Timestamp', 'Symbol', 'Mode', 'Entry_Price', 'Exit_Price',
                        'Quantity', 'USDT_Amount', 'Profit_Loss_USDT', 'Profit_Loss_Percent',
                        'Entry_Time', 'Exit_Time'
                    ])
                logger.info(f"Created new CSV file: {self.csv_file}")
            except Exception as e:
                logger.error(f"Error creating CSV file: {e}")

    def _save_trade_to_csv(self, trade: Dict):
        """Save trade details to CSV"""
        try:
            with open(self.csv_file, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    trade['symbol'],
                    'Testnet' if self.testnet else 'Real',
                    trade.get('entry_price', ''),
                    trade.get('exit_price', ''),
                    trade.get('quantity', ''),
                    trade.get('usdt_amount', ''),
                    trade.get('pnl_usdt', ''),
                    trade.get('pnl_percent', ''),
                    trade.get('entry_time', ''),
                    trade.get('exit_time', '')
                ])
            logger.info(f"Saved trade to CSV: {trade['symbol']}")
        except Exception as e:
            logger.error(f"Error saving trade to CSV: {e}")

    def get_swing_points(self, symbol: str, timeframe: str = '15m', lookback: int = 50) -> Tuple[float, float]:
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, limit=lookback)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            highs = df['high'].values
            lows = df['low'].values
            
            swing_high = 0
            for i in range(len(highs) - 3, 2, -1):
                if highs[i] > highs[i-1] and highs[i] > highs[i+1] and highs[i] > highs[i-2] and highs[i] > highs[i+2]:
                    swing_high = highs[i]
                    break
            
            swing_low = float('inf')
            for i in range(len(lows) - 3, 2, -1):
                if lows[i] < lows[i-1] and lows[i] < lows[i+1] and lows[i] < lows[i-2] and lows[i] < lows[i+2]:
                    swing_low = lows[i]
                    break
            
            if swing_high == 0:
                swing_high = df['high'].max()
            if swing_low == float('inf'):
                swing_low = df['low'].min()
                
            logger.info(f"Swing points for {symbol}: High={swing_high}, Low={swing_low}")
            return swing_low, swing_high
            
        except Exception as e:
            logger.error(f"Error getting swing points: {e}")
            return None, None

    def is_bullish_candle(self, symbol: str, timeframe: str = '15m') -> bool:
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, limit=2)
            latest_candle = ohlcv[-1]
            open_price = latest_candle[1]
            close_price = latest_candle[4]
            is_bullish = close_price > open_price
            logger.info(f"Checking candle for {symbol}: Open={open_price}, Close={close_price}, Bullish={is_bullish}")
            return is_bullish
        except Exception as e:
            logger.error(f"Error checking candle: {e}")
            return False

    def get_current_price(self, symbol: str) -> float:
        try:
            ticker = self.exchange.fetch_ticker(symbol)
            return ticker['last']
        except Exception as e:
            logger.error(f"Error getting current price: {e}")
            return None

    def simulate_buy_order(self, symbol: str, usdt_amount: float) -> Dict:
        """Simulate a market buy order for testnet mode"""
        try:
            current_price = self.get_current_price(symbol)
            if current_price is None:
                return None
                
            quantity = usdt_amount / current_price
            market_info = self.exchange.load_markets()[symbol]
            quantity = self.exchange.amount_to_precision(symbol, quantity)
            
            order = {
                'symbol': symbol,
                'price': current_price,
                'amount': float(quantity),
                'filled': float(quantity),
                'average': current_price,
                'timestamp': datetime.now().timestamp() * 1000,
                'datetime': datetime.now().isoformat()
            }
            
            logger.info(f"Simulated buy: {quantity} {symbol.split('/')[0]} with {usdt_amount} USDT at {current_price}")
            return order
        except Exception as e:
            logger.error(f"Error simulating buy order: {e}")
            return None

    def place_market_buy_order(self, symbol: str, usdt_amount: float) -> Dict:
        if self.testnet:
            return self.simulate_buy_order(symbol, usdt_amount)
            
        try:
            current_price = self.get_current_price(symbol)
            if current_price is None:
                return None
                
            quantity = usdt_amount / current_price
            market_info = self.exchange.load_markets()[symbol]
            quantity = self.exchange.amount_to_precision(symbol, quantity)
            
            order = self.exchange.create_market_buy_order(symbol, float(quantity))
            logger.info(f"Market buy order placed: {order}")
            return order
        except Exception as e:
            logger.error(f"Error placing buy order: {e}")
            return None

    def simulate_sell_order(self, symbol: str, quantity: float, exit_price: float) -> Dict:
        """Simulate a market sell order for testnet mode"""
        try:
            quantity = self.exchange.amount_to_precision(symbol, quantity)
            order = {
                'symbol': symbol,
                'price': exit_price,
                'amount': float(quantity),
                'filled': float(quantity),
                'average': exit_price,
                'timestamp': datetime.now().timestamp() * 1000,
                'datetime': datetime.now().isoformat()
            }
            logger.info(f"Simulated sell: {quantity} {symbol.split('/')[0]} at {exit_price}")
            return order
        except Exception as e:
            logger.error(f"Error simulating sell order: {e}")
            return None

    def place_market_sell_order(self, symbol: str, quantity: float, exit_price: float = None) -> Dict:
        if self.testnet:
            exit_price = exit_price or self.get_current_price(symbol)
            return self.simulate_sell_order(symbol, quantity, exit_price)
            
        try:
            quantity = self.exchange.amount_to_precision(symbol, quantity)
            order = self.exchange.create_market_sell_order(symbol, float(quantity))
            logger.info(f"Market sell order placed: {order}")
            return order
        except Exception as e:
            logger.error(f"Error placing sell order: {e}")
            return None

    def dynamic_stop_loss(self, position: Dict):
        try:
            symbol = position['symbol']
            entry_price = position['entry_price']
            current_stop = position['stop_loss']
            quantity = position['quantity']
            stop_moved_to_entry = False
            
            # Initialize with latest candle's timestamp
            ohlcv = self.exchange.fetch_ohlcv(symbol, '15m', limit=1)
            last_candle_time = ohlcv[-1]['timestamp'] / 1000  # Convert ms to seconds
            logger.info(f"Starting dynamic stop loss for {symbol} - Entry: {entry_price}, Stop: {current_stop}, Last candle time: {datetime.fromtimestamp(last_candle_time)}")
            
            while position in self.positions:
                current_price = self.get_current_price(symbol)
                if current_price is None:
                    time.sleep(0.1)
                    continue
                
                # Fetch latest candle
                ohlcv = self.exchange.fetch_ohlcv(symbol, '15m', limit=1)
                latest_candle = ohlcv[-1]
                timestamp = latest_candle['timestamp'] / 1000  # Convert ms to seconds
                
                # Check if a new 15-minute candle has closed
                if timestamp > last_candle_time and not stop_moved_to_entry:
                    logger.info(f"New candle detected at {datetime.fromtimestamp(timestamp)}")
                    if self.is_bullish_candle(symbol):
                        # Move stop loss to 0.2% below entry price
                        current_stop = entry_price * 0.998
                        stop_moved_to_entry = True
                        position['stop_loss'] = current_stop
                        last_candle_time = timestamp
                        logger.info(f"Stop loss moved to: {current_stop} (0.2% below entry price) after bullish candle")
                
                # Check if stop loss is hit with a small buffer
                if current_price <= current_stop * 1.002:  # Allow 0.2% buffer above stop loss
                    logger.info(f"Stop loss triggered at {current_price}, closing position")
                    sell_order = self.place_market_sell_order(symbol, quantity, current_price)
                    
                    if sell_order:
                        position['exit_price'] = current_price
                        position['exit_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        position['pnl_usdt'] = (current_price - entry_price) * quantity
                        position['pnl_percent'] = (position['pnl_usdt'] / position['usdt_amount']) * 100
                        self.trade_history.append(position.copy())
                        self._save_trade_to_csv(position)
                    
                    self.positions.remove(position)
                    break
                
                time.sleep(0.1)
        except Exception as e:
            logger.error(f"Error in dynamic stop loss: {e}")

    def trailing_take_profit(self, position: Dict, trail_percent: float = 2.0):
        try:
            symbol = position['symbol']
            current_tp = position['take_profit']
            quantity = position['quantity']
            highest_price = 0
            trailing_active = False
            
            logger.info(f"Starting trailing take profit for {symbol} - Initial TP: {current_tp}")
            
            while position in self.positions:
                current_price = self.get_current_price(symbol)
                if current_price is None:
                    time.sleep(1)
                    continue
                
                if not trailing_active and current_price >= current_tp:
                    trailing_active = True
                    highest_price = current_price
                    logger.info(f"Trailing take profit activated at {current_price}")
                
                if trailing_active:
                    if current_price > highest_price:
                        highest_price = current_price
                        new_tp = highest_price * (1 - trail_percent / 100)
                        if new_tp > current_tp:
                            current_tp = new_tp
                            position['take_profit'] = current_tp
                            logger.info(f"Trailing TP updated: {current_tp} (Highest: {highest_price})")
                    
                    if current_price <= current_tp:
                        logger.info(f"Trailing take profit triggered at {current_price}, closing position")
                        sell_order = self.place_market_sell_order(symbol, quantity, current_price)
                        
                        if sell_order:
                            position['exit_price'] = current_price
                            position['exit_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                            position['pnl_usdt'] = (current_price - position['entry_price']) * quantity
                            position['pnl_percent'] = (position['pnl_usdt'] / position['usdt_amount']) * 100
                            self.trade_history.append(position.copy())
                            self._save_trade_to_csv(position)
                        
                        self.positions.remove(position)
                        break
                
                elif current_price >= current_tp:
                    logger.info(f"Initial take profit hit at {current_price}, closing position")
                    sell_order = self.place_market_sell_order(symbol, quantity, current_price)
                    
                    if sell_order:
                        position['exit_price'] = current_price
                        position['exit_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        position['pnl_usdt'] = (current_price - position['entry_price']) * quantity
                        position['pnl_percent'] = (position['pnl_usdt'] / position['usdt_amount']) * 100
                        self.trade_history.append(position.copy())
                        self._save_trade_to_csv(position)
                    
                    self.positions.remove(position)
                    break
                
                time.sleep(2)
        except Exception as e:
            logger.error(f"Error in trailing take profit: {e}")

    def execute_trade(self, base_currency: str, usdt_amount: float, trail_percent: float = 2.0):
        try:
            symbol = f"{base_currency}/USDT"
            swing_low, swing_high = self.get_swing_points(symbol)
            
            if swing_low is None or swing_high is None:
                logger.error("Could not determine swing points, aborting trade")
                return False
            
            buy_order = self.place_market_buy_order(symbol, usdt_amount)
            if buy_order is None:
                logger.error("Failed to place buy order")
                return False
            
            entry_price = buy_order.get('average') or buy_order.get('price') or self.get_current_price(symbol)
            quantity = buy_order.get('filled') or buy_order.get('amount') or (usdt_amount / entry_price)
            
            position = {
                'symbol': symbol,
                'entry_price': entry_price,
                'quantity': quantity,
                'usdt_amount': usdt_amount,
                'stop_loss': swing_low,
                'take_profit': swing_high,
                'entry_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            
            self.positions.append(position)
            logger.info(f"Position opened: {quantity} {base_currency} at {entry_price} USDT")
            
            stop_loss_thread = threading.Thread(target=self.dynamic_stop_loss, args=(position,))
            stop_loss_thread.daemon = True
            stop_loss_thread.start()
            
            take_profit_thread = threading.Thread(target=self.trailing_take_profit, args=(position, trail_percent))
            take_profit_thread.daemon = True
            take_profit_thread.start()
            
            logger.info(f"Trade setup complete for {symbol}")
            logger.info(f"Entry: {entry_price} USDT, Quantity: {quantity} {base_currency}")
            logger.info(f"Stop Loss: {swing_low} USDT, Take Profit: {swing_high} USDT")
            
            return True
        except Exception as e:
            logger.error(f"Error executing trade: {e}")
            return False

def get_user_input():
    """Get interactive user input"""
    print("\nBinance Trading Bot")
    print("-------------------")
    
    while True:
        mode = input("Select mode (1: Testnet, 2: Real Trade): ").strip()
        if mode in ['1', '2']:
            testnet = mode == '1'
            break
        print("Invalid input. Enter 1 for Testnet or 2 for Real Trade.")
    
    while True:
        symbol = input("Enter coin symbol (e.g., BTC, ETH, ADA): ").strip().upper()
        if symbol:
            break
        print("Coin symbol cannot be empty.")
    
    while True:
        try:
            usdt_amount = float(input("Enter USDT amount to trade: ").strip())
            if usdt_amount > 0:
                break
            print("USDT amount must be positive.")
        except ValueError:
            print("Invalid number. Enter a valid USDT amount.")
    
    return testnet, symbol, usdt_amount

def main():
    testnet, base_currency, usdt_amount = get_user_input()
    trail_percent = 2.5
    
    bot = BinanceTradingBot(testnet=testnet)
    
    print(f"\nStarting {'Testnet' if testnet else 'Real'} trade for {base_currency}/USDT")
    print(f"USDT Amount: {usdt_amount}")
    
    success = bot.execute_trade(base_currency, usdt_amount, trail_percent)
    
    if success:
        print(f"Trade initiated successfully for {base_currency}/USDT")
        print(f"Results will be saved to {bot.csv_file}")
        
        symbol = f"{base_currency}/USDT"
        while any(p['symbol'] == symbol for p in bot.positions):
            for position in bot.positions:
                if position['symbol'] == symbol:
                    current_price = bot.get_current_price(symbol)
                    if current_price:
                        pnl = (current_price - position['entry_price']) * position['quantity']
                        pnl_percent = (pnl / position['usdt_amount']) * 100
                        print(f"\nPosition Status: {base_currency}/USDT")
                        print(f"Entry Price: ${position['entry_price']:.2f}")
                        print(f"Current Price: ${current_price:.2f}")
                        print(f"Current Stop Loss: ${position['stop_loss']:.2f}")
                        print(f"Current Take Profit: ${position['take_profit']:.2f}")
                        print(f"PnL: ${pnl:.2f} ({pnl_percent:.2f}%)")
            time.sleep(10)
    else:
        print("Trade execution failed")

if __name__ == "__main__":
    main()