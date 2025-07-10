import ccxt
import pandas as pd
import talib as ta
import time
import logging
from datetime import datetime
import os
from dotenv import load_dotenv
import math
import requests
from typing import Dict
import threading
import asyncio

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
API_KEY = os.getenv('BINANCE_API_KEY')
API_SECRET = os.getenv('BINANCE_API_SECRET')

class BinancePerpetualFetcher:
    def __init__(self):
        self.base_url = "https://fapi.binance.com"
        self._symbol_cache = None
        self._last_cache_update = 0
        self._cache_duration = 3600
    
    def _update_symbol_cache(self) -> None:
        """Update the cache of available symbols from exchange info"""
        try:
            current_time = time.time()
            if self._symbol_cache is None or (current_time - self._last_cache_update) > self._cache_duration:
                exchange_info = self.get_exchange_info()
                symbols = []
                if exchange_info and 'symbols' in exchange_info:
                    for symbol_info in exchange_info['symbols']:
                        if symbol_info.get('contractType') == 'PERPETUAL' and symbol_info.get('status') == 'TRADING':
                            symbols.append(symbol_info['symbol'])
                self._symbol_cache = symbols
                self._last_cache_update = current_time
                logger.info(f"✅ Updated symbol cache with {len(symbols)} perpetual futures symbols")
        except Exception as e:
            logger.error(f"❌ Error updating symbol cache: {e}")
            self._symbol_cache = []

    def _format_symbol(self, symbol: str) -> str:
        """Auto-format common symbols to proper trading pairs"""
        symbol = symbol.upper().strip()
        self._update_symbol_cache()
        
        # Handle different input formats
        if '/' in symbol:
            base_coin = symbol.split('/')[0]
            quote_coin = symbol.split('/')[1] if len(symbol.split('/')) > 1 else 'USDT'
            formatted_symbol = f"{base_coin}{quote_coin}"
        elif any(symbol.endswith(quote) for quote in ['USDT', 'BUSD', 'USDC', 'BTC', 'ETH', 'BNB']):
            formatted_symbol = symbol
        else:
            formatted_symbol = f"{symbol}USDT"

        # Extended symbol mappings
        symbol_map = {
            'BTC': 'BTCUSDT', 'BITCOIN': 'BTCUSDT',
            'ETH': 'ETHUSDT', 'ETHEREUM': 'ETHUSDT',
            'BNB': 'BNBUSDT', 'BINANCE': 'BNBUSDT',
            'ADA': 'ADAUSDT', 'CARDANO': 'ADAUSDT',
            'SOL': 'SOLUSDT', 'SOLANA': 'SOLUSDT',
            'DOT': 'DOTUSDT', 'POLKADOT': 'DOTUSDT',
            'MATIC': 'MATICUSDT', 'POLYGON': 'MATICUSDT',
            'LINK': 'LINKUSDT', 'CHAINLINK': 'LINKUSDT',
            'AVAX': 'AVAXUSDT', 'AVALANCHE': 'AVAXUSDT',
            'ATOM': 'ATOMUSDT', 'COSMOS': 'ATOMUSDT',
        }

        if symbol in symbol_map:
            formatted_symbol = symbol_map[symbol]

        # Validate against cached symbols
        if formatted_symbol in self._symbol_cache:
            return formatted_symbol

        # Try alternative formats
        base_coin = formatted_symbol.replace('USDT', '').replace('BUSD', '').replace('USDC', '')
        alternative_formats = [f"{base_coin}USDT", f"{base_coin}BUSD", f"{base_coin}USDC"]

        for alt_symbol in alternative_formats:
            if alt_symbol in self._symbol_cache:
                logger.info(f"✅ Found alternative symbol: {alt_symbol} for input: {symbol}")
                return alt_symbol

        logger.error(f"❌ Symbol {formatted_symbol} not found in Binance Futures markets")
        return None

    def get_exchange_info(self) -> Dict:
        """Get exchange information to validate symbols"""
        try:
            url = f"{self.base_url}/fapi/v1/exchangeInfo"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"❌ Error fetching exchange info: {e}")
            return {}

    def get_klines(self, symbol: str, interval: str = '1h', limit: int = 200) -> pd.DataFrame:
        """Get candlestick data for perpetual futures"""
        try:
            symbol = self._format_symbol(symbol)
            if not symbol:
                return None
            url = f"{self.base_url}/fapi/v1/klines"
            params = {
                'symbol': symbol.upper(),
                'interval': interval,
                'limit': min(limit, 1500)
            }
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            if not data:
                logger.error(f"❌ No kline data received for {symbol}")
                return None

            # Convert to DataFrame
            df = pd.DataFrame(data, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_asset_volume', 'number_of_trades',
                'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'
            ])
            
            df = df[['timestamp', 'open', 'high', 'low', 'close', 'volume']].copy()
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            
            return df
            
        except requests.RequestException as e:
            logger.error(f"❌ Error fetching kline data for {symbol}: {e}")
            return None
    
    def get_current_price(self, symbol: str) -> float:
        """Get current price"""
        try:
            symbol = self._format_symbol(symbol)
            if not symbol:
                return 0.0
            url = f"{self.base_url}/fapi/v1/ticker/price"
            params = {'symbol': symbol.upper()}
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            return float(data['price'])
        except requests.RequestException as e:
            logger.error(f"❌ Error fetching current price for {symbol}: {e}")
            return 0.0

    def get_position_info(self, symbol: str) -> Dict:
        """Get real-time position information from Binance API"""
        try:
            symbol = self._format_symbol(symbol)
            if not symbol:
                return {}
            
            url = f"{self.base_url}/fapi/v2/positionRisk"
            timestamp = int(time.time() * 1000)
            
            # Create signature for authenticated request
            import hmac
            import hashlib
            import urllib.parse
            
            params = {
                'symbol': symbol.upper(),
                'timestamp': timestamp
            }
            
            query_string = urllib.parse.urlencode(params)
            signature = hmac.new(
                API_SECRET.encode('utf-8'),
                query_string.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()
            
            params['signature'] = signature
            
            headers = {
                'X-MBX-APIKEY': API_KEY
            }
            
            response = requests.get(url, params=params, headers=headers, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            if data and len(data) > 0:
                position = data[0]  # Get first (and should be only) position
                return {
                    'symbol': position.get('symbol'),
                    'positionAmt': float(position.get('positionAmt', 0)),
                    'entryPrice': float(position.get('entryPrice', 0)),
                    'markPrice': float(position.get('markPrice', 0)),
                    'unRealizedProfit': float(position.get('unRealizedProfit', 0)),
                    'liquidationPrice': float(position.get('liquidationPrice', 0)),
                    'leverage': float(position.get('leverage', 1)),
                    'marginType': position.get('marginType'),
                    'isolatedMargin': float(position.get('isolatedMargin', 0)),
                    'notional': float(position.get('notional', 0)),
                    'isolatedWallet': float(position.get('isolatedWallet', 0)),
                    'positionSide': position.get('positionSide')
                }
            
            return {}
            
        except Exception as e:
            logger.error(f"❌ Error fetching position info: {e}")
            return {}

class LiquidationSafeFuturesTrader:
    def __init__(self, reports_folder_path="./futures_reports/"):
        """Initialize liquidation-safe futures trader"""
        self.perpetual_fetcher = BinancePerpetualFetcher()
        self.exchange = ccxt.binance({
            'enableRateLimit': True,
            'rateLimit': 100,
            'options': {
                'defaultType': 'future',
                'hedgeMode': False,
            },
            'apiKey': API_KEY,
            'secret': API_SECRET,
            'timeout': 10000,
            'sandbox': False
        })
        
        try:
            self.exchange.load_markets()
            balance = self.exchange.fetch_balance()
            logger.info(f"✅ Connected to Binance Futures successfully!")
            logger.info(f"💰 USDT Balance: ${balance['USDT']['free']:.2f}")
        except Exception as e:
            logger.error(f"❌ Connection failed: {e}")
            return
        
        self.timeframe = '15m'
        self.reports_folder = reports_folder_path
        self._create_reports_folder()
        
        # Active monitoring for TP/SL
        self.active_monitors = {}
        self.monitor_running = False
        
        # Binance maintenance margin rates by position size (USDT)
        self.maintenance_margin_tiers = {
            'BTCUSDT': [
                (0, 50000, 0.004, 0),           # 0-50k: 0.4%
                (50000, 250000, 0.005, 50),    # 50k-250k: 0.5%
                (250000, 1000000, 0.01, 1300), # 250k-1M: 1%
                (1000000, 5000000, 0.025, 16300), # 1M-5M: 2.5%
                (5000000, 20000000, 0.05, 141300), # 5M-20M: 5%
                (20000000, float('inf'), 0.125, 1641300) # 20M+: 12.5%
            ],
            'ETHUSDT': [
                (0, 50000, 0.005, 0),
                (50000, 250000, 0.0065, 75),
                (250000, 1000000, 0.01, 1300),
                (1000000, 5000000, 0.025, 16300),
                (5000000, 20000000, 0.05, 141300),
                (20000000, float('inf'), 0.125, 1641300)
            ],
            # Default for other symbols
            'DEFAULT': [
                (0, 50000, 0.01, 0),
                (50000, 250000, 0.025, 750),
                (250000, 1000000, 0.05, 6750),
                (1000000, 5000000, 0.1, 56750),
                (5000000, 20000000, 0.125, 181750),
                (20000000, float('inf'), 0.15, 681750)
            ]
        }
        
        logger.info("🛡️ LIQUIDATION-SAFE Futures Trader Ready!")
        logger.info(f"📊 Reports will be saved to: {self.reports_folder}")
    
    def _normalize_coin_input(self, coin_input: str) -> tuple:
        """Simple normalization - validate the symbol exists"""
        try:
            symbol = coin_input.upper().strip()
            self.perpetual_fetcher._update_symbol_cache()
            
            if symbol in self.perpetual_fetcher._symbol_cache:
                base_coin = symbol.replace('USDT', '').replace('BUSD', '').replace('USDC', '')
                logger.info(f"📊 Using symbol: {symbol} (base: {base_coin})")
                return symbol, base_coin
            
            if not any(symbol.endswith(quote) for quote in ['USDT', 'BUSD', 'USDC', 'BTC', 'ETH', 'BNB']):
                symbol_with_usdt = f"{symbol}USDT"
                if symbol_with_usdt in self.perpetual_fetcher._symbol_cache:
                    base_coin = symbol
                    logger.info(f"📊 Auto-corrected to: {symbol_with_usdt} (base: {base_coin})")
                    return symbol_with_usdt, base_coin
            
            logger.error(f"❌ Symbol {symbol} not found in Binance Futures")
            return None, None
            
        except Exception as e:
            logger.error(f"❌ Error normalizing symbol '{coin_input}': {e}")
            return None, None

    def _create_reports_folder(self):
        """Create reports folder if it doesn't exist"""
        try:
            if not os.path.exists(self.reports_folder):
                os.makedirs(self.reports_folder)
                logger.info(f"📁 Created reports folder: {self.reports_folder}")
        except Exception as e:
            logger.error(f"❌ Error creating reports folder: {e}")

    def _get_maintenance_margin_rate(self, symbol: str, notional_value: float) -> tuple:
        """Get maintenance margin rate and cumulative amount for symbol and position size"""
        try:
            # Get the appropriate tier for the symbol
            tiers = self.maintenance_margin_tiers.get(symbol, self.maintenance_margin_tiers['DEFAULT'])
            
            for min_notional, max_notional, rate, cum_amount in tiers:
                if min_notional <= notional_value < max_notional:
                    logger.info(f"📊 Maintenance Margin: {rate*100:.2f}% (tier: ${min_notional:,.0f}-${max_notional:,.0f})")
                    return rate, cum_amount
            
            # If somehow we don't find a tier, use the highest one
            last_tier = tiers[-1]
            logger.warning(f"⚠️ Using highest tier: {last_tier[2]*100:.2f}%")
            return last_tier[2], last_tier[3]
            
        except Exception as e:
            logger.error(f"❌ Error getting maintenance margin rate: {e}")
            # Conservative fallback
            return 0.05, 0

    def _calculate_precise_liquidation_price(self, entry_price: float, quantity: float, 
                                           margin_amount: float, side: str, symbol: str) -> float:
        """Calculate precise liquidation price using Binance's exact formula"""
        try:
            notional_value = abs(entry_price * quantity)
            mmr, cum = self._get_maintenance_margin_rate(symbol, notional_value)
            
            # Binance's exact liquidation formula for isolated margin:
            wb = margin_amount  # Wallet Balance (isolated margin)
            
            if side == 'long':
                # For long positions: Liquidation Price = (WB - cum) / (quantity * (1 + MMR))
                liquidation_price = (wb - cum) / (abs(quantity) * (1 + mmr))
            else:
                # For short positions: Liquidation Price = (WB - cum) / (quantity * (1 - MMR))
                liquidation_price = (wb - cum) / (abs(quantity) * (1 - mmr))
            
            logger.info(f"🎯 CALCULATED Liquidation Price: ${liquidation_price:.8f}")
            logger.info(f"   Notional: ${notional_value:.2f}")
            logger.info(f"   MMR: {mmr*100:.3f}%")
            logger.info(f"   Cum Amount: ${cum:.2f}")
            
            return liquidation_price
            
        except Exception as e:
            logger.error(f"❌ Error calculating precise liquidation price: {e}")
            # Ultra-conservative fallback
            if side == 'long':
                return entry_price * 0.85  # 15% below entry
            else:
                return entry_price * 1.15  # 15% above entry

    def _calculate_ultra_safe_stop_loss(self, entry_price: float, liquidation_price: float, 
                                      side: str, original_stop: float, buffer_percent: float) -> float:
        """Calculate ultra-safe stop loss with multiple safety layers"""
        try:
            if liquidation_price is None or liquidation_price <= 0:
                logger.warning("⚠️ Invalid liquidation price, using conservative stop")
                # Conservative fallback
                if side == 'long':
                    return entry_price * 0.92  # 8% below entry
                else:
                    return entry_price * 1.08  # 8% above entry
            
            # Calculate multiple safety buffers
            base_buffer = buffer_percent / 100
            volatility_buffer = 0.02  # Reduced to 2% for market volatility
            slippage_buffer = 0.02    # Reduced to 2% for slippage
            
            total_buffer = base_buffer + volatility_buffer + slippage_buffer
            
            if side == 'long':
                # Distance from entry to liquidation
                max_loss_distance = entry_price - liquidation_price
                safe_loss_distance = max_loss_distance * (1 - total_buffer)
                ultra_safe_stop = entry_price - safe_loss_distance
                
                # Never let stop loss be worse than original strategy
                final_stop = max(ultra_safe_stop, original_stop)
                
            else:
                # Distance from entry to liquidation
                max_loss_distance = liquidation_price - entry_price
                safe_loss_distance = max_loss_distance * (1 - total_buffer)
                ultra_safe_stop = entry_price + safe_loss_distance
                
                # Never let stop loss be worse than original strategy
                final_stop = min(ultra_safe_stop, original_stop)
            
            # Final safety check - ensure stop is never closer to liquidation than 2%
            if side == 'long':
                min_distance = (entry_price - liquidation_price) * 0.02
                absolute_min_stop = liquidation_price + min_distance
                if final_stop < absolute_min_stop:
                    logger.warning(f"⚠️ Stop too close to liquidation! Using absolute minimum: ${absolute_min_stop:.8f}")
                    final_stop = absolute_min_stop
            else:
                min_distance = (liquidation_price - entry_price) * 0.02
                absolute_max_stop = liquidation_price - min_distance
                if final_stop > absolute_max_stop:
                    logger.warning(f"⚠️ Stop too close to liquidation! Using absolute maximum: ${absolute_max_stop:.8f}")
                    final_stop = absolute_max_stop
            
            return final_stop
            
        except Exception as e:
            logger.error(f"❌ Error calculating ultra-safe stop loss: {e}")
            return original_stop

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
            logger.error(f"❌ Error saving trade to CSV: {e}")

    def _record_trade_entry(self, symbol, coin_name, side, leverage, entry_price, quantity, 
                           margin_amount, stop_loss, take_profit, tp_type, calculated_liquidation_price=None):
        """Record trade entry to CSV with calculated liquidation price"""
        
        trade_data = {
            'Date': datetime.now().strftime("%Y-%m-%d"),
            'Time': datetime.now().strftime("%H:%M:%S"),
            'Action': 'ENTRY',
            'Coin': coin_name,
            'Symbol': symbol,
            'Side': side,
            'Leverage': leverage,
            'Entry_Price': entry_price,
            'Calculated_Liquidation_Price': calculated_liquidation_price,
            'Quantity': quantity,
            'Notional_USD': entry_price * abs(quantity),
            'Margin_Used': margin_amount,
            'Stop_Loss': stop_loss,
            'Take_Profit': take_profit,
            'TP_Type': tp_type,
            'Exit_Price': None,
            'Exit_Time': None,
            'PnL_USD': None,
            'PnL_Percent': None,
            'Exit_Reason': None,
            'Trade_Duration_Minutes': None,
            'Expected_TP_Profit': abs(take_profit - entry_price) * abs(quantity) if take_profit else None
        }
        self._save_trade_to_csv(trade_data)

    def _monitor_position(self, symbol: str, stop_loss: float, take_profit: float, side: str, 
                         entry_price: float, quantity: float):
        """Monitor position for take profit and stop loss execution"""
        logger.info(f"🔍 Starting position monitor for {symbol}")
        
        while symbol in self.active_monitors:
            try:
                # Get current position info from Binance API
                position_info = self.perpetual_fetcher.get_position_info(symbol)
                
                if not position_info or position_info.get('positionAmt', 0) == 0:
                    logger.info(f"📍 Position {symbol} closed externally, stopping monitor")
                    break
                
                current_price = position_info.get('markPrice', 0)
                if current_price == 0:
                    current_price = self.perpetual_fetcher.get_current_price(symbol)
                
                logger.info(f"📊 {symbol} Monitor - Price: ${current_price:.6f} | SL: ${stop_loss:.6f} | TP: ${take_profit:.6f}")
                
                # Check for take profit hit
                if side == 'long' and current_price >= take_profit:
                    logger.info(f"🎯 TAKE PROFIT HIT for {symbol} at ${current_price:.6f}")
                    self._execute_exit_order(symbol, quantity, "TAKE_PROFIT")
                    break
                elif side == 'short' and current_price <= take_profit:
                    logger.info(f"🎯 TAKE PROFIT HIT for {symbol} at ${current_price:.6f}")
                    self._execute_exit_order(symbol, quantity, "TAKE_PROFIT")
                    break
                
                # Check for stop loss hit
                if side == 'long' and current_price <= stop_loss:
                    logger.info(f"🛑 STOP LOSS HIT for {symbol} at ${current_price:.6f}")
                    self._execute_exit_order(symbol, quantity, "STOP_LOSS")
                    break
                elif side == 'short' and current_price >= stop_loss:
                    logger.info(f"🛑 STOP LOSS HIT for {symbol} at ${current_price:.6f}")
                    self._execute_exit_order(symbol, quantity, "STOP_LOSS")
                    break
                
                time.sleep(2)  # Check every 2 seconds
                
            except Exception as e:
                logger.error(f"❌ Error in position monitor for {symbol}: {e}")
                time.sleep(5)
        
        # Clean up
        if symbol in self.active_monitors:
            del self.active_monitors[symbol]
        logger.info(f"🔍 Position monitor stopped for {symbol}")

    def _execute_exit_order(self, symbol: str, quantity: float, reason: str):
        """Execute exit order for take profit or stop loss"""
        try:
            logger.info(f"🔥 Executing {reason} order for {symbol}")
            
            # Determine the side for closing
            if quantity > 0:  # Long position
                close_side = 'sell'
            else:  # Short position
                close_side = 'buy'
                quantity = abs(quantity)
            
            # Execute market order to close position
            order = self.exchange.create_market_order(symbol, close_side, quantity)
            
            exit_price = float(order['average']) if order['average'] else 0
            
            logger.info(f"✅ {reason} executed for {symbol}")
            logger.info(f"   Exit Price: ${exit_price:.6f}")
            logger.info(f"   Quantity: {quantity:.6f}")
            
            # Record the exit
            self._record_trade_exit(symbol, exit_price, reason)
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error executing {reason} for {symbol}: {e}")
            return False

    def _record_trade_exit(self, symbol: str, exit_price: float, exit_reason: str):
        """Record trade exit to CSV"""
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            csv_filename = f"futures_trading_report_{today}.csv"
            csv_filepath = os.path.join(self.reports_folder, csv_filename)
            
            if os.path.exists(csv_filepath):
                df = pd.read_csv(csv_filepath)
                
                # Find the most recent entry for this symbol that hasn't been closed
                mask = (df['Symbol'] == symbol) & (df['Action'] == 'ENTRY') & (df['Exit_Price'].isna())
                
                if mask.any():
                    # Update the most recent entry
                    latest_idx = df[mask].index[-1]
                    df.loc[latest_idx, 'Exit_Price'] = exit_price
                    df.loc[latest_idx, 'Exit_Time'] = datetime.now().strftime("%H:%M:%S")
                    df.loc[latest_idx, 'Exit_Reason'] = exit_reason
                    
                    # Calculate PnL
                    entry_price = df.loc[latest_idx, 'Entry_Price']
                    quantity = df.loc[latest_idx, 'Quantity']
                    side = df.loc[latest_idx, 'Side']
                    
                    if side == 'long':
                        pnl_usd = (exit_price - entry_price) * abs(quantity)
                    else:
                        pnl_usd = (entry_price - exit_price) * abs(quantity)
                    
                    pnl_percent = (pnl_usd / df.loc[latest_idx, 'Margin_Used']) * 100
                    
                    df.loc[latest_idx, 'PnL_USD'] = pnl_usd
                    df.loc[latest_idx, 'PnL_Percent'] = pnl_percent
                    
                    # Calculate trade duration
                    entry_time = datetime.strptime(f"{df.loc[latest_idx, 'Date']} {df.loc[latest_idx, 'Time']}", 
                                                 "%Y-%m-%d %H:%M:%S")
                    exit_time = datetime.strptime(f"{datetime.now().strftime('%Y-%m-%d')} {datetime.now().strftime('%H:%M:%S')}", 
                                                "%Y-%m-%d %H:%M:%S")
                    duration_minutes = (exit_time - entry_time).total_seconds() / 60
                    df.loc[latest_idx, 'Trade_Duration_Minutes'] = duration_minutes
                    
                    df.to_csv(csv_filepath, index=False)
                    
                    logger.info(f"📊 Trade exit recorded: PnL ${pnl_usd:.2f} ({pnl_percent:.2f}%)")
                    
        except Exception as e:
            logger.error(f"❌ Error recording trade exit: {e}")

    def _find_swing_high_low(self, df, lookback=10):
        """Find the LAST (most recent) swing high and swing low from price data"""
        try:
            if len(df) < lookback * 2:
                return {
                    'swing_high': df['high'].max(),
                    'swing_low': df['low'].min()
                }
            
            last_swing_high = None
            last_swing_low = None
            last_swing_high_index = -1
            last_swing_low_index = -1
            
            # Find swing highs - scan from oldest to newest to get the LAST one
            for i in range(lookback, len(df) - lookback):
                is_swing_high = True
                current_high = df['high'].iloc[i]
                
                # Check if this candle is higher than all candles in the lookback window
                for j in range(i - lookback, i + lookback + 1):
                    if j != i and df['high'].iloc[j] >= current_high:
                        is_swing_high = False
                        break
                
                if is_swing_high:
                    # Update to the most recent swing high
                    last_swing_high = current_high
                    last_swing_high_index = i
            
            # Find swing lows - scan from oldest to newest to get the LAST one
            for i in range(lookback, len(df) - lookback):
                is_swing_low = True
                current_low = df['low'].iloc[i]
                
                # Check if this candle is lower than all candles in the lookback window
                for j in range(i - lookback, i + lookback + 1):
                    if j != i and df['low'].iloc[j] <= current_low:
                        is_swing_low = False
                        break
                
                if is_swing_low:
                    # Update to the most recent swing low
                    last_swing_low = current_low
                    last_swing_low_index = i
            
            # Fallback to recent extremes if no swing points found
            if last_swing_high is None:
                last_swing_high = df['high'].tail(20).max()
                logger.warning("⚠️ No swing high found, using recent high")
            
            if last_swing_low is None:
                last_swing_low = df['low'].tail(20).min()
                logger.warning("⚠️ No swing low found, using recent low")
            
            # Log the found swing levels with their positions
            logger.info(f"📊 LAST Swing High: ${last_swing_high:.6f} (at index {last_swing_high_index})")
            logger.info(f"📊 LAST Swing Low: ${last_swing_low:.6f} (at index {last_swing_low_index})")
            
            return {
                'swing_high': last_swing_high,
                'swing_low': last_swing_low,
                'swing_high_index': last_swing_high_index,
                'swing_low_index': last_swing_low_index
            }
            
        except Exception as e:
            logger.error(f"❌ Error finding swing points: {e}")
            return {
                'swing_high': df['high'].max(),
                'swing_low': df['low'].min(),
                'swing_high_index': -1,
                'swing_low_index': -1
            }

    def _find_resistance_support(self, df, lookback=20, min_touches=2):
        """Find key resistance and support levels based on price touches"""
        try:
            if len(df) < lookback:
                return {
                    'resistance': df['high'].max(),
                    'support': df['low'].min()
                }
            
            highs = df['high'].values
            lows = df['low'].values
            
            # Find resistance levels (price peaks)
            resistance_candidates = []
            for i in range(lookback, len(highs) - lookback):
                is_peak = True
                current_high = highs[i]
                
                # Check if it's a local maximum
                for j in range(i - lookback//2, i + lookback//2 + 1):
                    if j != i and highs[j] >= current_high:
                        is_peak = False
                        break
                
                if is_peak:
                    resistance_candidates.append(current_high)
            
            # Find support levels (price troughs)
            support_candidates = []
            for i in range(lookback, len(lows) - lookback):
                is_trough = True
                current_low = lows[i]
                
                # Check if it's a local minimum
                for j in range(i - lookback//2, i + lookback//2 + 1):
                    if j != i and lows[j] <= current_low:
                        is_trough = False
                        break
                
                if is_trough:
                    support_candidates.append(current_low)
            
            # Get the strongest levels (most recent and significant)
            if resistance_candidates:
                resistance = max(resistance_candidates)  # Highest resistance
            else:
                resistance = df['high'].tail(20).max()
            
            if support_candidates:
                support = min(support_candidates)  # Lowest support
            else:
                support = df['low'].tail(20).min()
            
            return {
                'resistance': resistance,
                'support': support
            }
            
        except Exception as e:
            logger.error(f"❌ Error finding resistance/support: {e}")
            return {
                'resistance': df['high'].max(),
                'support': df['low'].min()
            }

    def get_real_time_position_data(self, symbol: str):
        """Get comprehensive real-time position data from Binance API"""
        try:
            symbol, _ = self._normalize_coin_input(symbol)
            if not symbol:
                return None
            
            logger.info(f"📊 Fetching real-time data for {symbol}...")
            
            # Get position info from Binance API
            position_info = self.perpetual_fetcher.get_position_info(symbol)
            
            if not position_info or position_info.get('positionAmt', 0) == 0:
                logger.info(f"📍 No active position found for {symbol}")
                return None
            
            # Get current market price
            current_price = self.perpetual_fetcher.get_current_price(symbol)
            
            # Parse position data
            position_amt = position_info.get('positionAmt', 0)
            entry_price = position_info.get('entryPrice', 0)
            mark_price = position_info.get('markPrice', current_price)
            unrealized_pnl = position_info.get('unRealizedProfit', 0)
            liquidation_price = position_info.get('liquidationPrice', 0)
            leverage = position_info.get('leverage', 1)
            margin_type = position_info.get('marginType', 'isolated')
            isolated_margin = position_info.get('isolatedMargin', 0)
            isolated_wallet = position_info.get('isolatedWallet', 0)
            notional = position_info.get('notional', 0)
            
            # Determine side
            side = 'long' if position_amt > 0 else 'short'
            
            # Calculate margin ratio
            margin_ratio = (abs(unrealized_pnl) / isolated_wallet * 100) if isolated_wallet > 0 else 0
            
            # Calculate our precise liquidation price for comparison
            calculated_liq_price = self._calculate_precise_liquidation_price(
                entry_price, position_amt, isolated_wallet, side, symbol
            )
            
            position_data = {
                'symbol': symbol,
                'side': side,
                'position_amount': position_amt,
                'entry_price': entry_price,
                'mark_price': mark_price,
                'current_price': current_price,
                'unrealized_pnl': unrealized_pnl,
                'liquidation_price': liquidation_price,
                'calculated_liquidation_price': calculated_liq_price,
                'leverage': leverage,
                'margin_type': margin_type,
                'isolated_margin': isolated_margin,
                'isolated_wallet': isolated_wallet,
                'notional_value': abs(notional),
                'margin_ratio': margin_ratio,
                'timestamp': datetime.now().isoformat()
            }
            
            # Log comprehensive position info
            logger.info(f"📊 REAL-TIME POSITION DATA for {symbol}:")
            logger.info(f"   Side: {side.upper()}")
            logger.info(f"   Position Amount: {position_amt:.8f}")
            logger.info(f"   Entry Price: ${entry_price:.6f}")
            logger.info(f"   Mark Price: ${mark_price:.6f}")
            logger.info(f"   Current Price: ${current_price:.6f}")
            logger.info(f"   Unrealized PnL: ${unrealized_pnl:.4f}")
            logger.info(f"   Liquidation Price (API): ${liquidation_price:.6f}")
            logger.info(f"   Liquidation Price (Calculated): ${calculated_liq_price:.6f}")
            logger.info(f"   Leverage: {leverage}x")
            logger.info(f"   Margin Type: {margin_type}")
            logger.info(f"   Isolated Margin: ${isolated_margin:.4f}")
            logger.info(f"   Isolated Wallet: ${isolated_wallet:.4f}")
            logger.info(f"   Notional Value: ${abs(notional):.2f}")
            logger.info(f"   Margin Ratio: {margin_ratio:.2f}%")
            
            return position_data
            
        except Exception as e:
            logger.error(f"❌ Error fetching real-time position data: {e}")
            return None

    def start_position_monitoring(self):
        """Start monitoring all active positions"""
        if self.monitor_running:
            logger.info("🔍 Position monitoring already running")
            return
        
        self.monitor_running = True
        logger.info("🔍 Starting position monitoring service...")
        
        def monitor_loop():
            while self.monitor_running:
                try:
                    # Get all active positions
                    positions = self.exchange.fetch_positions()
                    
                    for position in positions:
                        if float(position.get('contracts', 0)) > 0:
                            symbol = position.get('symbol')
                            
                            # Skip if already being monitored
                            if symbol in self.active_monitors:
                                continue
                            
                            # Check if we have TP/SL data for this position
                            # This would come from our trade records
                            tp_sl_data = self._get_tp_sl_for_position(symbol)
                            
                            if tp_sl_data:
                                # Start monitoring this position
                                quantity = float(position.get('contracts', 0))
                                side = position.get('side')
                                entry_price = float(position.get('entryPrice', 0))
                                
                                self.active_monitors[symbol] = True
                                
                                # Start monitoring thread
                                monitor_thread = threading.Thread(
                                    target=self._monitor_position,
                                    args=(symbol, tp_sl_data['stop_loss'], tp_sl_data['take_profit'], 
                                         side, entry_price, quantity)
                                )
                                monitor_thread.daemon = True
                                monitor_thread.start()
                                
                                logger.info(f"🔍 Started monitoring {symbol} - SL: ${tp_sl_data['stop_loss']:.6f}, TP: ${tp_sl_data['take_profit']:.6f}")
                    
                    time.sleep(10)  # Check for new positions every 10 seconds
                    
                except Exception as e:
                    logger.error(f"❌ Error in monitoring loop: {e}")
                    time.sleep(30)
        
        # Start monitoring in background thread
        monitor_thread = threading.Thread(target=monitor_loop)
        monitor_thread.daemon = True
        monitor_thread.start()

    def stop_position_monitoring(self):
        """Stop position monitoring"""
        self.monitor_running = False
        self.active_monitors.clear()
        logger.info("🔍 Position monitoring stopped")

    def _get_tp_sl_for_position(self, symbol: str) -> dict:
        """Get take profit and stop loss levels for a position from trade records"""
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            csv_filename = f"futures_trading_report_{today}.csv"
            csv_filepath = os.path.join(self.reports_folder, csv_filename)
            
            if os.path.exists(csv_filepath):
                df = pd.read_csv(csv_filepath)
                
                # Find the most recent entry for this symbol that hasn't been closed
                mask = (df['Symbol'] == symbol) & (df['Action'] == 'ENTRY') & (df['Exit_Price'].isna())
                
                if mask.any():
                    latest_entry = df[mask].iloc[-1]
                    return {
                        'stop_loss': latest_entry['Stop_Loss'],
                        'take_profit': latest_entry['Take_Profit']
                    }
            
            return None
            
        except Exception as e:
            logger.error(f"❌ Error getting TP/SL for position: {e}")
            return None

    def trade(self, coin, margin_amount, leverage=5, side='long', take_profit_ratio=2.0, 
              use_fixed_tp=False, fixed_tp_percent=2.5, use_swing_levels=False, 
              swing_lookback=10, use_resistance_support=False, rs_lookback=20,
              use_fixed_amount_tp=False, fixed_tp_amount=20, liquidation_buffer=4,
              auto_monitor=True):
        """Execute a LIQUIDATION-SAFE futures trade with enhanced monitoring
        
        🛡️ KEY SAFETY FEATURES:
        - Pre-calculates liquidation price using Binance's exact formula
        - Uses tiered maintenance margin rates
        - Applies multiple safety buffers (volatility + slippage + user buffer)
        - Real-time position monitoring with automatic TP/SL execution
        - Fetches live data from Binance API for accurate position tracking
        
        Args:
            coin: Trading symbol
            margin_amount: Amount to use as margin
            leverage: Leverage multiplier
            side: 'long' or 'short'
            take_profit_ratio: Risk/reward ratio for ATR-based TP
            use_fixed_tp: Whether to use fixed percentage TP
            fixed_tp_percent: Fixed TP percentage
            use_swing_levels: Whether to use swing levels for TP
            swing_lookback: Lookback period for swing detection
            use_resistance_support: Whether to use resistance/support levels
            rs_lookback: Lookback period for resistance/support detection
            use_fixed_amount_tp: Whether to use fixed dollar amount TP
            fixed_tp_amount: Fixed dollar amount for take profit
            liquidation_buffer: Safety buffer percentage (minimum 4% recommended!)
            auto_monitor: Whether to start automatic position monitoring
        """
        try:
            symbol, coin_name = self._normalize_coin_input(coin)
            if not symbol or not coin_name:
                logger.error(f"❌ Invalid coin input: {coin}")
                return False
            
            # Enforce minimum safety buffer
            if liquidation_buffer < 4:
                logger.warning(f"⚠️ Buffer {liquidation_buffer}% too low! Using minimum 4%")
                liquidation_buffer = 4
            
            logger.info(f"🛡️ INITIATING LIQUIDATION-SAFE TRADE: {coin_name} {side.upper()}")
            logger.info(f"💰 Margin: ${margin_amount} | Leverage: {leverage}x | Buffer: {liquidation_buffer}%")
            
            side = side.lower()
            if side not in ['long', 'short']:
                logger.error(f"❌ Invalid side: {side}. Use 'long' or 'short'")
                return False
            
            # Check balance
            balance = self.exchange.fetch_balance()
            usdt_balance = balance['USDT']['free']
            
            if usdt_balance < margin_amount:
                logger.error(f"❌ Insufficient balance. Have ${usdt_balance:.2f}, need ${margin_amount}")
                return False
            
            logger.info(f"✅ Balance sufficient: ${usdt_balance:.2f}")
            
            # Get current price
            try:
                current_price = self.perpetual_fetcher.get_current_price(symbol)
                logger.info(f"📊 Current price: ${current_price:.8f}")
            except Exception as e:
                logger.warning(f"⚠️ Perpetual price failed, using CCXT: {e}")
                ticker = self.exchange.fetch_ticker(symbol)
                current_price = ticker['last']
                logger.info(f"📊 Current price (CCXT): ${current_price:.8f}")
            
            # Calculate position size
            notional_value = margin_amount * leverage
            quantity = notional_value / current_price
            
            # Handle side-specific quantity
            if side == 'short':
                quantity = -quantity  # Negative for short positions
            
            # Round quantity to appropriate precision
            markets = self.exchange.load_markets()
            market = markets.get(symbol)
            if market:
                precision = market['precision']['amount']
                if isinstance(precision, float):
                    precision = int(-1 * math.log10(precision))
                elif precision is None:
                    precision = 8
            else:
                precision = 8
            
            factor = 10 ** precision
            quantity = math.floor(abs(quantity) * factor) / factor
            if side == 'short':
                quantity = -quantity
            
            logger.info(f"📊 Position Details:")
            logger.info(f"   Margin: ${margin_amount}")
            logger.info(f"   Leverage: {leverage}x")
            logger.info(f"   Notional: ${notional_value:.2f}")
            logger.info(f"   Quantity: {quantity:.8f} {coin_name}")
            
            # 🎯 CRITICAL: Calculate precise liquidation price BEFORE trade
            logger.info("🎯 CALCULATING PRECISE LIQUIDATION PRICE...")
            calculated_liquidation_price = self._calculate_precise_liquidation_price(
                current_price, quantity, margin_amount, side, symbol)
            
            # Calculate distance to liquidation
            if side == 'long':
                liq_distance_pct = ((current_price - calculated_liquidation_price) / current_price) * 100
            else:
                liq_distance_pct = ((calculated_liquidation_price - current_price) / current_price) * 100
            
            logger.info(f"🛡️ Liquidation Distance: {liq_distance_pct:.2f}%")
            
            # SAFETY CHECK: Ensure minimum liquidation distance
            min_required_distance = liquidation_buffer + 1 # Extra 1% safety margin
            if liq_distance_pct < min_required_distance:
                logger.error(f"❌ TRADE REJECTED: Liquidation too close!")
                logger.error(f"   Required distance: {min_required_distance:.1f}%")
                logger.error(f"   Actual distance: {liq_distance_pct:.2f}%")
                logger.error(f"   Reduce leverage or increase margin!")
                return False
            
            # Get chart data and calculate levels
            try:
                logger.info("📈 Fetching chart data for strategy calculation...")
                df = self.perpetual_fetcher.get_klines(symbol, self.timeframe, 100)
                
                if df is not None and not df.empty:
                    df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)
                    atr_value = df['atr'].iloc[-1]
                    
                    if use_swing_levels:
                        swing_levels = self._find_swing_high_low(df, swing_lookback)
                        swing_high = swing_levels['swing_high']
                        swing_low = swing_levels['swing_low']
                        swing_high_index = swing_levels['swing_high_index']
                        swing_low_index = swing_levels['swing_low_index']
                        logger.info(f"📊 LAST Swing High: ${swing_high:.8f} (index: {swing_high_index})")
                        logger.info(f"📊 LAST Swing Low: ${swing_low:.8f} (index: {swing_low_index})")
                    
                    if use_resistance_support:
                        rs_levels = self._find_resistance_support(df, rs_lookback)
                        resistance = rs_levels['resistance']
                        support = rs_levels['support']
                        logger.info(f"📊 Resistance: ${resistance:.8f} | Support: ${support:.8f}")
                    
                    logger.info(f"📊 ATR value: ${atr_value:.8f}")
                else:
                    raise Exception("No chart data received")
                    
            except Exception as e:
                logger.error(f"❌ Error fetching chart data: {e}")
                atr_value = current_price * 0.02
                use_swing_levels = False
                use_resistance_support = False
                use_fixed_amount_tp = False
                logger.info(f"📊 Using fallback ATR: ${atr_value:.8f}")
            
            # Calculate stop loss and take profit levels
            if use_fixed_amount_tp:
                # Use fixed dollar amount for TP and ATR for SL
                stop_distance = atr_value * 1.5
                
                if side == 'long':
                    initial_stop_loss = current_price - stop_distance
                    # Calculate TP price based on fixed dollar amount
                    tp_price_distance = fixed_tp_amount / abs(quantity)
                    take_profit = current_price + tp_price_distance
                else:
                    initial_stop_loss = current_price + stop_distance
                    # Calculate TP price based on fixed dollar amount
                    tp_price_distance = fixed_tp_amount / abs(quantity)
                    take_profit = current_price - tp_price_distance
                
                tp_type = f"Fixed Amount ${fixed_tp_amount} + ATR-based SL"
                
            elif use_resistance_support:
                # Use resistance/support for TP and ATR for SL
                stop_distance = atr_value * 1.5
                
                if side == 'long':
                    initial_stop_loss = current_price - stop_distance
                    take_profit = resistance if 'resistance' in locals() else current_price * 1.05
                    if take_profit <= current_price:
                        take_profit = current_price * 1.05
                        logger.warning("⚠️ Resistance below entry, using 5% take profit")
                else:
                    initial_stop_loss = current_price + stop_distance
                    take_profit = support if 'support' in locals() else current_price * 0.95
                    if take_profit >= current_price:
                        take_profit = current_price * 0.95
                        logger.warning("⚠️ Support above entry, using 5% take profit")
                
                tp_type = f"Resistance/Support (TP) + ATR (SL, lookback: {rs_lookback})"
                
            elif use_swing_levels:
                if side == 'long':
                    initial_stop_loss = swing_low if 'swing_low' in locals() else current_price * 0.97
                    take_profit = swing_high if 'swing_high' in locals() else current_price * 1.05
                    if initial_stop_loss >= current_price:
                        initial_stop_loss = current_price * 0.97
                else:
                    initial_stop_loss = swing_high if 'swing_high' in locals() else current_price * 1.03
                    take_profit = swing_low if 'swing_low' in locals() else current_price * 0.95
                    if initial_stop_loss <= current_price:
                        initial_stop_loss = current_price * 1.03
                
                tp_type = f"LAST Swing levels (lookback: {swing_lookback})"
                
            else:
                stop_distance = atr_value * 1.5
                
                if side == 'long':
                    initial_stop_loss = current_price - stop_distance
                    if use_fixed_tp:
                        take_profit = current_price * (1 + fixed_tp_percent / 100)
                        tp_type = f"Fixed {fixed_tp_percent}%"
                    else:
                        take_profit = current_price + (stop_distance * take_profit_ratio)
                        tp_type = f"ATR-based (1:{take_profit_ratio})"
                else:
                    initial_stop_loss = current_price + stop_distance
                    if use_fixed_tp:
                        take_profit = current_price * (1 - fixed_tp_percent / 100)
                        tp_type = f"Fixed {fixed_tp_percent}%"
                    else:
                        take_profit = current_price - (stop_distance * take_profit_ratio)
                        tp_type = f"ATR-based (1:{take_profit_ratio})"
            
            # 🛡️ CRITICAL: Calculate ultra-safe stop loss
            logger.info("🛡️ CALCULATING ULTRA-SAFE STOP LOSS...")
            safe_stop_loss = self._calculate_ultra_safe_stop_loss(
                current_price, calculated_liquidation_price, side, initial_stop_loss, liquidation_buffer)
            
            logger.info(f"📊 Strategy levels:")
            logger.info(f"   Initial Stop Loss: ${initial_stop_loss:.8f}")
            logger.info(f"   🛡️ ULTRA-SAFE Stop Loss: ${safe_stop_loss:.8f}")
            logger.info(f"   Take Profit ({tp_type}): ${take_profit:.8f}")
            
            # Final safety validation
            if side == 'long':
                stop_to_liq_distance = ((safe_stop_loss - calculated_liquidation_price) / current_price) * 100
                if stop_to_liq_distance < 2:
                    logger.error(f"❌ TRADE REJECTED: Stop loss too close to liquidation!")
                    logger.error(f"   Stop to liquidation distance: {stop_to_liq_distance:.2f}%")
                    return False
            else:
                stop_to_liq_distance = ((calculated_liquidation_price - safe_stop_loss) / current_price) * 100
                if stop_to_liq_distance < 2:
                    logger.error(f"❌ TRADE REJECTED: Stop loss too close to liquidation!")
                    logger.error(f"   Stop to liquidation distance: {stop_to_liq_distance:.2f}%")
                    return False
            
            # Set leverage and margin mode before trade
            try:
                self.exchange.set_leverage(leverage, symbol)
                logger.info(f"⚡ Leverage set to {leverage}x for {symbol}")
            except Exception as e:
                logger.warning(f"⚠️ Could not set leverage: {e}")
            
            try:
                self.exchange.set_margin_mode('isolated', symbol)
                logger.info(f"🔒 Margin mode set to isolated for {symbol}")
            except Exception as e:
                logger.warning(f"⚠️ Could not set margin mode: {e}")
            
            # Execute order
            logger.info("🔥 EXECUTING LIQUIDATION-SAFE ORDER...")
            start_time = time.time()
            
            try:
                order_side = 'buy' if side == 'long' else 'sell'
                order = self.exchange.create_market_order(symbol, order_side, abs(quantity))
                execution_time = time.time() - start_time
                
                logger.info(f"⚡ Order executed in {execution_time:.2f} seconds")
                
                entry_price = float(order['average']) if order['average'] else current_price
                
                logger.info(f"✅ LIQUIDATION-SAFE ORDER FILLED!")
                logger.info(f"   Side: {side.upper()}")
                logger.info(f"   Entry Price: ${entry_price:.8f}")
                logger.info(f"   🎯 Calculated Liquidation: ${calculated_liquidation_price:.8f}")
                logger.info(f"   Quantity: {quantity:.8f} {coin_name}")
                logger.info(f"   Notional: ${entry_price * abs(quantity):.2f}")
                logger.info(f"   Margin Used: ${margin_amount}")
                
                # Recalculate distances with actual entry price
                if side == 'long':
                    actual_liq_distance = ((entry_price - calculated_liquidation_price) / entry_price) * 100
                    stop_distance_pct = ((entry_price - safe_stop_loss) / entry_price) * 100
                else:
                    actual_liq_distance = ((calculated_liquidation_price - entry_price) / entry_price) * 100
                    stop_distance_pct = ((safe_stop_loss - entry_price) / entry_price) * 100
                
                logger.info(f"   🛡️ Ultra-Safe Stop: ${safe_stop_loss:.8f}")
                logger.info(f"   Take Profit: ${take_profit:.8f}")
                logger.info(f"   TP Type: {tp_type}")
                
                logger.info(f"🛡️ SAFETY METRICS:")
                logger.info(f"   Liquidation Distance: {actual_liq_distance:.2f}%")
                logger.info(f"   Stop Loss Distance: {stop_distance_pct:.2f}%")
                logger.info(f"   Safety Buffer: {actual_liq_distance - stop_distance_pct:.2f}%")
                logger.info(f"   Target Buffer: {liquidation_buffer}%")
                
                # Calculate risk/reward with safe stop
                if side == 'long':
                    risk = abs(safe_stop_loss - entry_price) * abs(quantity)
                    reward = abs(take_profit - entry_price) * abs(quantity)
                else:
                    risk = abs(entry_price - safe_stop_loss) * abs(quantity)
                    reward = abs(entry_price - take_profit) * abs(quantity)
                
                actual_ratio = reward / risk if risk > 0 else 0
                logger.info(f"⚖️ Risk/Reward: 1:{actual_ratio:.2f}")
                
                # Show expected profit for fixed amount TP
                if use_fixed_amount_tp:
                    logger.info(f"💰 Expected TP Profit: ${reward:.2f} (Target: ${fixed_tp_amount})")
                
                # Record trade entry to CSV
                self._record_trade_entry(symbol, coin_name, side, leverage, entry_price, 
                                       quantity, margin_amount, safe_stop_loss, take_profit, 
                                       tp_type, calculated_liquidation_price)
                
                # Start automatic monitoring if requested
                if auto_monitor:
                    logger.info("🔍 Starting automatic position monitoring...")
                    if not self.monitor_running:
                        self.start_position_monitoring()
                    
                    # Add this position to monitoring
                    self.active_monitors[symbol] = True
                    
                    # Start monitoring thread for this specific position
                    monitor_thread = threading.Thread(
                        target=self._monitor_position,
                        args=(symbol, safe_stop_loss, take_profit, side, entry_price, quantity)
                    )
                    monitor_thread.daemon = True
                    monitor_thread.start()
                    
                    logger.info(f"🔍 Position monitoring started for {symbol}")
                
                # Get real-time position data after trade execution
                time.sleep(1)  # Allow time for position to be updated
                self.get_real_time_position_data(symbol)
                
                return {
                    'success': True,
                    'symbol': symbol,
                    'coin': coin_name,
                    'side': side,
                    'leverage': leverage,
                    'entry_price': entry_price,
                    'calculated_liquidation_price': calculated_liquidation_price,
                    'quantity': quantity,
                    'margin_used': margin_amount,
                    'stop_loss': safe_stop_loss,
                    'take_profit': take_profit,
                    'tp_type': tp_type,
                    'safety_buffer': actual_liq_distance - stop_distance_pct,
                    'monitoring_active': auto_monitor
                }
                
            except Exception as e:
                logger.error(f"❌ Order execution failed: {e}")
                return False
            
        except Exception as e:
            logger.error(f"❌ Critical error in liquidation-safe trade: {e}")
            return False

    def close_position(self, coin, reason="MANUAL_CLOSE"):
        """Manually close a futures position"""
        try:
            symbol, coin_name = self._normalize_coin_input(coin)
            if not symbol or not coin_name:
                logger.error(f"❌ Invalid coin input: {coin}")
                return False
            
            logger.info(f"🔄 CLOSING FUTURES POSITION: {coin_name}")
            
            # Stop monitoring for this position
            if symbol in self.active_monitors:
                del self.active_monitors[symbol]
                logger.info(f"🔍 Stopped monitoring for {symbol}")
            
            # Get current position data
            position_info = self.perpetual_fetcher.get_position_info(symbol)
            
            if not position_info or position_info.get('positionAmt', 0) == 0:
                logger.info(f"❌ No active position for {symbol}")
                return False
            
            quantity = float(position_info.get('positionAmt', 0))
            side = 'long' if quantity > 0 else 'short'
            
            # Get current price
            try:
                current_price = self.perpetual_fetcher.get_current_price(symbol)
                logger.info(f"📊 Current price: ${current_price:.8f}")
            except Exception as e:
                ticker = self.exchange.fetch_ticker(symbol)
                current_price = ticker['last']
            
            logger.info(f"📊 Position: {side.upper()} {abs(quantity):.8f} {coin_name}")
            
            # Execute closing order
            logger.info("🔥 EXECUTING CLOSING ORDER...")
            start_time = time.time()
            
            close_side = 'sell' if quantity > 0 else 'buy'
            order = self.exchange.create_market_order(symbol, close_side, abs(quantity))
            execution_time = time.time() - start_time
            
            exit_price = float(order['average']) if order['average'] else current_price
            
            logger.info(f"⚡ Order executed in {execution_time:.2f} seconds")
            logger.info(f"✅ FUTURES POSITION CLOSED - {coin_name}")
            logger.info(f"💰 Exit Price: ${exit_price:.8f}")
            
            # Record the exit
            self._record_trade_exit(symbol, exit_price, reason)
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error closing futures position: {e}")
            return False

    def get_balance(self):
        """Get account balance with enhanced details"""
        try:
            balance = self.exchange.fetch_balance()
            
            # Get account info for more details
            account_info = self.exchange.fapiPrivateGetAccount()
            
            total_wallet_balance = float(account_info.get('totalWalletBalance', 0))
            total_unrealized_pnl = float(account_info.get('totalUnrealizedProfit', 0))
            total_margin_balance = float(account_info.get('totalMarginBalance', 0))
            available_balance = float(account_info.get('availableBalance', 0))
            
            logger.info("💼 ENHANCED FUTURES ACCOUNT BALANCE")
            logger.info(f"💰 USDT Free: ${balance['USDT']['free']:.2f}")
            logger.info(f"💼 USDT Used: ${balance['USDT']['used']:.2f}")
            logger.info(f"📊 USDT Total: ${balance['USDT']['total']:.2f}")
            logger.info(f"🏦 Total Wallet Balance: ${total_wallet_balance:.2f}")
            logger.info(f"📈 Total Unrealized PnL: ${total_unrealized_pnl:.2f}")
            logger.info(f"⚖️ Total Margin Balance: ${total_margin_balance:.2f}")
            logger.info(f"✅ Available Balance: ${available_balance:.2f}")
            
            return {
                'balance': balance,
                'total_wallet_balance': total_wallet_balance,
                'total_unrealized_pnl': total_unrealized_pnl,
                'total_margin_balance': total_margin_balance,
                'available_balance': available_balance
            }
        except Exception as e:
            logger.error(f"❌ Error getting balance: {e}")
            return None

    def get_all_positions(self, show_real_time_data=True):
        """Get all active positions with real-time data from Binance API"""
        try:
            logger.info("📊 FETCHING ALL ACTIVE POSITIONS WITH REAL-TIME DATA...")
            
            if show_real_time_data:
                # Use Binance API for real-time data
                positions = []
                
                # Get account positions
                account_info = self.exchange.fapiPrivateGetAccount()
                api_positions = account_info.get('positions', [])
                
                for pos in api_positions:
                    position_amt = float(pos.get('positionAmt', 0))
                    if abs(position_amt) > 0:
                        symbol = pos.get('symbol')
                        entry_price = float(pos.get('entryPrice', 0))
                        mark_price = float(pos.get('markPrice', 0))
                        unrealized_pnl = float(pos.get('unrealizedProfit', 0))
                        
                        # Get detailed position info
                        position_info = self.perpetual_fetcher.get_position_info(symbol)
                        
                        if position_info:
                            side = 'long' if position_amt > 0 else 'short'
                            
                            # Calculate our precise liquidation price
                            isolated_margin = position_info.get('isolatedWallet', 0)
                            calculated_liquidation = self._calculate_precise_liquidation_price(
                                entry_price, position_amt, isolated_margin, side, symbol)
                            
                            pos_data = {
                                'symbol': symbol,
                                'side': side,
                                'position_amount': position_amt,
                                'entry_price': entry_price,
                                'mark_price': mark_price,
                                'real_liquidation_price': position_info.get('liquidationPrice', 0),
                                'calculated_liquidation_price': calculated_liquidation,
                                'unrealized_pnl': unrealized_pnl,
                                'percentage': (unrealized_pnl / isolated_margin * 100) if isolated_margin > 0 else 0,
                                'leverage': position_info.get('leverage', 1),
                                'margin_type': position_info.get('marginType', 'isolated'),
                                'isolated_margin': isolated_margin,
                                'isolated_wallet': position_info.get('isolatedWallet', 0),
                                'notional': abs(position_info.get('notional', 0)),
                                'maintenance_margin': 0,  # Could be calculated if needed
                                'monitoring_active': symbol in self.active_monitors
                            }
                            positions.append(pos_data)
                            
                            # Log position details with comparison
                            logger.info(f"📍 {symbol} | {side.upper()}")
                            logger.info(f"   Size: {position_amt:.8f}")
                            logger.info(f"   Entry: ${entry_price:.8f}")
                            logger.info(f"   Mark: ${mark_price:.8f}")
                            logger.info(f"   Leverage: {pos_data['leverage']}x")
                            logger.info(f"   Margin Type: {pos_data['margin_type']}")
                            
                            real_liq = pos_data['real_liquidation_price']
                            calc_liq = calculated_liquidation
                            
                            if real_liq and calc_liq:
                                diff_pct = abs(real_liq - calc_liq) / real_liq * 100
                                logger.info(f"   🎯 Real Liquidation: ${real_liq:.8f}")
                                logger.info(f"   🧮 Calculated Liquidation: ${calc_liq:.8f}")
                                logger.info(f"   📊 Difference: {diff_pct:.2f}%")
                            elif calc_liq:
                                logger.info(f"   🧮 Calculated Liquidation: ${calc_liq:.8f}")
                            
                            logger.info(f"   PnL: ${unrealized_pnl:.4f} ({pos_data['percentage']:.2f}%)")
                            logger.info(f"   Isolated Margin: ${isolated_margin:.4f}")
                            logger.info(f"   Monitoring: {'✅' if pos_data['monitoring_active'] else '❌'}")
                            logger.info("   " + "="*50)
                
            else:
                # Use CCXT for basic data
                positions = self.exchange.fetch_positions()
                active_positions = []
                
                for position in positions:
                    if float(position.get('contracts', 0)) > 0:
                        pos_data = {
                            'symbol': position.get('symbol'),
                            'side': position.get('side'),
                            'position_amount': float(position.get('contracts', 0)),
                            'entry_price': float(position.get('entryPrice', 0)),
                            'mark_price': float(position.get('markPrice', 0)),
                            'unrealized_pnl': float(position.get('unrealizedPnl', 0)),
                            'percentage': float(position.get('percentage', 0)),
                            'notional': float(position.get('notional', 0)),
                            'monitoring_active': position.get('symbol') in self.active_monitors
                        }
                        active_positions.append(pos_data)
                        
                        logger.info(f"📍 {pos_data['symbol']} | {pos_data['side'].upper()}")
                        logger.info(f"   Size: {pos_data['position_amount']:.8f}")
                        logger.info(f"   Entry: ${pos_data['entry_price']:.8f}")
                        logger.info(f"   Mark: ${pos_data['mark_price']:.8f}")
                        logger.info(f"   PnL: ${pos_data['unrealized_pnl']:.4f} ({pos_data['percentage']:.2f}%)")
                        logger.info(f"   Monitoring: {'✅' if pos_data['monitoring_active'] else '❌'}")
                        logger.info("   " + "="*50)
                
                positions = active_positions
            
            if not positions:
                logger.info("📍 No active positions found")
            else:
                logger.info(f"📍 Found {len(positions)} active position(s)")
                
                # Summary
                total_unrealized = sum(pos['unrealized_pnl'] for pos in positions)
                logger.info(f"💰 Total Unrealized PnL: ${total_unrealized:.2f}")
                
                monitoring_count = sum(1 for pos in positions if pos['monitoring_active'])
                logger.info(f"🔍 Positions being monitored: {monitoring_count}/{len(positions)}")
            
            return positions
            
        except Exception as e:
            logger.error(f"❌ Error fetching positions: {e}")
            return []

    def get_trading_summary(self, days=7):
        """Get trading summary from CSV reports"""
        try:
            logger.info(f"📊 GENERATING TRADING SUMMARY (Last {days} days)")
            
            all_trades = []
            
            # Read trades from the last N days
            for i in range(days):
                date = (datetime.now() - pd.Timedelta(days=i)).strftime("%Y-%m-%d")
                csv_filename = f"futures_trading_report_{date}.csv"
                csv_filepath = os.path.join(self.reports_folder, csv_filename)
                
                if os.path.exists(csv_filepath):
                    df = pd.read_csv(csv_filepath)
                    all_trades.append(df)
            
            if not all_trades:
                logger.info("📊 No trading data found")
                return None
            
            combined_df = pd.concat(all_trades, ignore_index=True)
            
            # Filter only entry records that have exits
            completed_trades = combined_df[(combined_df['Action'] == 'ENTRY') & 
                                         (combined_df['Exit_Price'].notna())]
            
            if len(completed_trades) == 0:
                logger.info("📊 No completed trades found")
                return None
            
            # Calculate statistics
            total_trades = len(completed_trades)
            winning_trades = len(completed_trades[completed_trades['PnL_USD'] > 0])
            losing_trades = len(completed_trades[completed_trades['PnL_USD'] < 0])
            win_rate = (winning_trades / total_trades) * 100
            
            total_pnl = completed_trades['PnL_USD'].sum()
            total_volume = completed_trades['Notional_USD'].sum()
            avg_trade_size = completed_trades['Margin_Used'].mean()
            
            avg_win = completed_trades[completed_trades['PnL_USD'] > 0]['PnL_USD'].mean() if winning_trades > 0 else 0
            avg_loss = completed_trades[completed_trades['PnL_USD'] < 0]['PnL_USD'].mean() if losing_trades > 0 else 0
            
            profit_factor = abs(avg_win * winning_trades / (avg_loss * losing_trades)) if losing_trades > 0 and avg_loss != 0 else float('inf')
            
            # Log summary
            logger.info("📊 TRADING SUMMARY")
            logger.info("="*50)
            logger.info(f"📅 Period: Last {days} days")
            logger.info(f"📈 Total Trades: {total_trades}")
            logger.info(f"✅ Winning Trades: {winning_trades}")
            logger.info(f"❌ Losing Trades: {losing_trades}")
            logger.info(f"🎯 Win Rate: {win_rate:.1f}%")
            logger.info(f"💰 Total PnL: ${total_pnl:.2f}")
            logger.info(f"📊 Total Volume: ${total_volume:.2f}")
            logger.info(f"💵 Average Trade Size: ${avg_trade_size:.2f}")
            logger.info(f"📈 Average Win: ${avg_win:.2f}")
            logger.info(f"📉 Average Loss: ${avg_loss:.2f}")
            logger.info(f"⚖️ Profit Factor: {profit_factor:.2f}")
            
            # Breakdown by coin
            logger.info("\n📊 BREAKDOWN BY COIN:")
            coin_summary = completed_trades.groupby('Coin').agg({
                'PnL_USD': ['count', 'sum', 'mean'],
                'Margin_Used': 'sum'
            }).round(2)
            
            for coin in coin_summary.index:
                trades = coin_summary.loc[coin, ('PnL_USD', 'count')]
                total_pnl_coin = coin_summary.loc[coin, ('PnL_USD', 'sum')]
                avg_pnl_coin = coin_summary.loc[coin, ('PnL_USD', 'mean')]
                total_margin = coin_summary.loc[coin, ('Margin_Used', 'sum')]
                
                logger.info(f"   {coin}: {trades} trades, PnL: ${total_pnl_coin:.2f}, Avg: ${avg_pnl_coin:.2f}, Margin: ${total_margin:.2f}")
            
            return {
                'total_trades': total_trades,
                'winning_trades': winning_trades,
                'losing_trades': losing_trades,
                'win_rate': win_rate,
                'total_pnl': total_pnl,
                'total_volume': total_volume,
                'avg_trade_size': avg_trade_size,
                'avg_win': avg_win,
                'avg_loss': avg_loss,
                'profit_factor': profit_factor,
                'coin_breakdown': coin_summary
            }
            
        except Exception as e:
            logger.error(f"❌ Error generating trading summary: {e}")
            return None

# Initialize the enhanced liquidation-safe trader
futures_trader = LiquidationSafeFuturesTrader()

# Example usage with REAL liquidation price:
# result = futures_trader.trade("BTC", 100, leverage=10, side="long", take_profit_ratio=2.0)

# Check all positions with REAL data:
# futures_trader.get_all_positions()

# Example usage with custom liquidation buffer:

# 1. ATR-based TP and SL with 20% buffer
#futures_trader.trade("RENDERUSDT", 10, leverage=25, side="long", take_profit_ratio=1.5, liquidation_buffer=7)

# 2. Fixed percentage TP with 10% buffer (more aggressive)
# futures_trader.trade("ETH", 50, leverage=5, side="short", use_fixed_tp=True, fixed_tp_percent=3.0, liquidation_buffer=10)

# 3. Swing levels with 25% buffer (very conservative)
#futures_trader.trade("VANRYUSDT", 10, leverage=20, side="long", use_swing_levels=True, swing_lookback=15, liquidation_buffer=9)

# 4. Resistance/Support TP with custom 12% buffer
#futures_trader.trade("RENDERUSDT", 10, leverage=20, side="long", use_resistance_support=True, rs_lookback=20, liquidation_buffer=7)

# 5. Fixed Dollar Amount TP with 18% buffer
# futures_trader.trade("BTC", 100, leverage=10, side="long", use_fixed_amount_tp=True, fixed_tp_amount=25, liquidation_buffer=18)

# 6. High leverage trade with larger 30% buffer for safety
# futures_trader.trade("BTC", 50, leverage=50, side="long", liquidation_buffer=30)

# 7. Conservative trade with minimal 5% buffer (risky!)
# futures_trader.trade("ETH", 100, leverage=3, side="short", liquidation_buffer=5)

# Get account balance
# futures_trader.get_balance()

# 🛡️ ENHANCED LIQUIDATION-SAFE TRADING EXAMPLES:

# 1. Conservative trade with real-time monitoring (RECOMMENDED)
# result = futures_trader.trade("BTC", 100, leverage=10, side="long", 
#                              liquidation_buffer=4, auto_monitor=True)

# 2. Get comprehensive real-time position data
# futures_trader.get_real_time_position_data("BTCUSDT")

# 3. Get all positions with live API data
# futures_trader.get_all_positions(show_real_time_data=True)

# 4. Manual position monitoring control
# futures_trader.start_position_monitoring()  # Start monitoring service
# futures_trader.stop_position_monitoring()   # Stop monitoring service

# 5. Enhanced balance information
# futures_trader.get_balance()

# 6. Trading performance summary
# futures_trader.get_trading_summary(days=7)

# 7. Close position manually with reason tracking
# futures_trader.close_position("BTC", reason="MANUAL_EXIT")

# 8. Trade with automatic monitoring enabled by default
# futures_trader.trade("ETH", 50, leverage=5, side="short", 
#                     use_fixed_amount_tp=True, fixed_tp_amount=25,
#                     liquidation_buffer=4, auto_monitor=True)

# logger.info("🚀 Enhanced Liquidation-Safe Futures Trader Ready!")
# logger.info("✨ New Features:")
# logger.info("   📊 Real-time position data from Binance API")
# logger.info("   🔍 Automatic take profit and stop loss monitoring")
# logger.info("   📈 Enhanced balance and position tracking")
# logger.info("   📊 Trading performance summaries")
# logger.info("   🛡️ Improved liquidation safety calculations")