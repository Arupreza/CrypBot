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
        """Calculate precise liquidation price using Binance's exact formula - FIXED VERSION"""
        try:
            notional_value = abs(entry_price * quantity)
            mmr, cum = self._get_maintenance_margin_rate(symbol, notional_value)
            
            # Binance's exact liquidation formula for isolated margin:
            wb = margin_amount  # Wallet Balance (isolated margin)
            
            if side == 'long':
                # For long positions: Liquidation Price = (WB - cum) / (quantity * (1 + MMR))
                liquidation_price = (wb - cum) / (abs(quantity) * (1 + mmr))
            else:
                # For short positions: FIXED FORMULA
                # Liquidation Price = (WB - cum + quantity * entry_price) / (quantity * (1 - MMR))
                liquidation_price = (wb - cum + abs(quantity) * entry_price) / (abs(quantity) * (1 - mmr))
            
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
            volatility_buffer = 0.02  # 2% for market volatility
            slippage_buffer = 0.02    # 2% for slippage
            
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

    def trade(self, coin, margin_amount, leverage=5, side='long', take_profit_ratio=2.0, 
              use_fixed_tp=False, fixed_tp_percent=2.5, use_swing_levels=False, 
              swing_lookback=10, liquidation_buffer=5, fixed_tp_dollars=None, 
              use_atr_stoploss=False, atr_multiplier=1.5):
        """Execute a LIQUIDATION-SAFE futures trade
        
        🛡️ KEY SAFETY FEATURES:
        - Pre-calculates liquidation price using Binance's exact formula (FIXED for shorts)
        - Uses tiered maintenance margin rates
        - Applies multiple safety buffers (volatility + slippage + user buffer)
        
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
            liquidation_buffer: Safety buffer percentage (minimum 5% recommended!)
            fixed_tp_dollars: Fixed dollar amount for take profit (overrides other TP methods)
            use_atr_stoploss: Whether to use ATR-based stop loss
            atr_multiplier: Multiplier for ATR-based stop loss (default 1.5)
        """
        try:
            symbol, coin_name = self._normalize_coin_input(coin)
            if not symbol or not coin_name:
                logger.error(f"❌ Invalid coin input: {coin}")
                return False
            
            # Enforce minimum safety buffer to 5%
            if liquidation_buffer < 5:
                logger.warning(f"⚠️ Buffer {liquidation_buffer}% too low! Using minimum 5%")
                liquidation_buffer = 5
            
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
                    df['atr'] = ta.ATR(df['high'], df['low'], df['close'], timeperiod=14)
                    atr_value = df['atr'].iloc[-1]
                    
                    if use_swing_levels:
                        swing_levels = self._find_swing_high_low(df, swing_lookback)
                        swing_high = swing_levels['swing_high']
                        swing_low = swing_levels['swing_low']
                        swing_high_index = swing_levels['swing_high_index']
                        swing_low_index = swing_levels['swing_low_index']
                        logger.info(f"📊 LAST Swing High: ${swing_high:.8f} (index: {swing_high_index})")
                        logger.info(f"📊 LAST Swing Low: ${swing_low:.8f} (index: {swing_low_index})")
                    
                    logger.info(f"📊 ATR value: ${atr_value:.8f}")
                else:
                    raise Exception("No chart data received")
                    
            except Exception as e:
                logger.error(f"❌ Error fetching chart data: {e}")
                atr_value = current_price * 0.02
                use_swing_levels = False
                logger.info(f"📊 Using fallback ATR: ${atr_value:.8f}")
            
            # Calculate stop loss and take profit levels
            if use_swing_levels:
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
                
            elif fixed_tp_dollars:
                # FIXED DOLLAR TAKE PROFIT
                dollar_per_unit = fixed_tp_dollars / abs(quantity)
                
                if side == 'long':
                    take_profit = current_price + dollar_per_unit
                else:
                    take_profit = current_price - dollar_per_unit
                
                tp_type = f"Fixed ${fixed_tp_dollars} profit"
                
                # Set stop loss based on ATR or fallback
                if use_atr_stoploss:
                    stop_distance = atr_value * atr_multiplier
                    if side == 'long':
                        initial_stop_loss = current_price - stop_distance
                    else:
                        initial_stop_loss = current_price + stop_distance
                else:
                    # Default stop loss
                    if side == 'long':
                        initial_stop_loss = current_price * 0.97  # 3% stop
                    else:
                        initial_stop_loss = current_price * 1.03  # 3% stop
                
            else:
                # ATR-BASED STOP LOSS with other TP methods
                if use_atr_stoploss:
                    stop_distance = atr_value * atr_multiplier
                    
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
                else:
                    # Original logic for backward compatibility
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
            if use_atr_stoploss:
                logger.info(f"   🎯 ATR-based SL (ATR: ${atr_value:.8f} × {atr_multiplier})")
            if fixed_tp_dollars:
                logger.info(f"   💰 Fixed Dollar TP: ${fixed_tp_dollars}")
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
                
                # Record trade entry to CSV
                self._record_trade_entry(symbol, coin_name, side, leverage, entry_price, 
                                       quantity, margin_amount, safe_stop_loss, take_profit, 
                                       tp_type, calculated_liquidation_price)
                
                logger.info("📝 Trade recorded successfully")
                logger.info("⚠️ Note: No automatic monitoring - you'll need to manually manage TP/SL")
                
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
                    'safety_buffer': actual_liq_distance - stop_distance_pct
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

    def get_balance(self):
        """Get account balance"""
        try:
            balance = self.exchange.fetch_balance()
            
            logger.info("💼 FUTURES ACCOUNT BALANCE")
            logger.info(f"💰 USDT Free: ${balance['USDT']['free']:.2f}")
            logger.info(f"💼 USDT Used: ${balance['USDT']['used']:.2f}")
            logger.info(f"📊 USDT Total: ${balance['USDT']['total']:.2f}")
            
            return balance
        except Exception as e:
            logger.error(f"❌ Error getting balance: {e}")
            return None

    def get_all_positions(self):
        """Get all active positions"""
        try:
            logger.info("📊 FETCHING ALL ACTIVE POSITIONS...")
            
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
                        'notional': float(position.get('notional', 0))
                    }
                    active_positions.append(pos_data)
                    
                    logger.info(f"📍 {pos_data['symbol']} | {pos_data['side'].upper()}")
                    logger.info(f"   Size: {pos_data['position_amount']:.8f}")
                    logger.info(f"   Entry: ${pos_data['entry_price']:.8f}")
                    logger.info(f"   Mark: ${pos_data['mark_price']:.8f}")
                    logger.info(f"   PnL: ${pos_data['unrealized_pnl']:.4f} ({pos_data['percentage']:.2f}%)")
                    logger.info("   " + "="*50)
            
            if not active_positions:
                logger.info("📍 No active positions found")
            else:
                logger.info(f"📍 Found {len(active_positions)} active position(s)")
                
                # Summary
                total_unrealized = sum(pos['unrealized_pnl'] for pos in active_positions)
                logger.info(f"💰 Total Unrealized PnL: ${total_unrealized:.2f}")
            
            return active_positions
            
        except Exception as e:
            logger.error(f"❌ Error fetching positions: {e}")
            return []

# Initialize the liquidation-safe trader
futures_trader = LiquidationSafeFuturesTrader()

# 🛡️ LIQUIDATION-SAFE TRADING EXAMPLES:

# 1. Test JUP short with fixed $10 profit and ATR stop loss
# futures_trader.trade("JUP", 10, leverage=20, side="short", fixed_tp_dollars=10, use_atr_stoploss=True, atr_multiplier=2.0)

# 2. BTC long with fixed $50 profit and ATR stop loss
# futures_trader.trade("BTC", 100, leverage=10, side="long", fixed_tp_dollars=50, use_atr_stoploss=True, atr_multiplier=1.5)

# 3. ETH short with fixed $25 profit and conservative ATR stop
# futures_trader.trade("ETH", 50, leverage=5, side="short", fixed_tp_dollars=25, use_atr_stoploss=True, atr_multiplier=1.2)

# 4. SOL long with ATR-based stop loss only (no fixed dollar TP)
# futures_trader.trade("SOL", 25, leverage=8, side="long", use_atr_stoploss=True, atr_multiplier=1.8, use_fixed_tp=True, fixed_tp_percent=3.0)

# 5. Traditional trade (backward compatibility)
# futures_trader.trade("BTC", 100, leverage=10, side="long", liquidation_buffer=5)

# 6. Check balance
# futures_trader.get_balance()

# 7. Check all positions
# futures_trader.get_all_positions()

# 8. Close a position manually
# futures_trader.close_position("BTC", reason="MANUAL_EXIT")

# logger.info("🚀 Enhanced Liquidation-Safe Futures Trader Ready!")
# logger.info("✨ Key Features:")
# logger.info("   🛡️ Precise liquidation price calculation for both long and short positions")
# logger.info("   💰 Fixed dollar-based take profit option")
# logger.info("   🎯 ATR-based stop loss with customizable multiplier")
# logger.info("   📊 Enhanced safety buffers and validation")
# logger.info("   🛡️ Minimum 5% liquidation safety buffer")
# logger.info("   📝 Trade recording to CSV files")
# logger.info("")
# logger.info("💡 New Trading Options:")
# logger.info("   📈 Use fixed_tp_dollars=X for exact dollar profit targets")
# logger.info("   📉 Use use_atr_stoploss=True for volatility-based stop losses")
# logger.info("   ⚙️ Customize atr_multiplier for stop loss sensitivity")
# logger.info("")
# logger.info("⚠️ Note: No automatic monitoring - you'll need to manually manage TP/SL orders")
# logger.info("🎯 Ready for advanced futures trading!")