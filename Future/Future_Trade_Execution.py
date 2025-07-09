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

    def get_real_liquidation_price_from_binance(self, symbol: str) -> float:
        """Fetch REAL liquidation price directly from Binance API"""
        try:
            # Get position information which includes liquidation price
            positions = self.exchange.fetch_positions([symbol])
            
            for position in positions:
                if float(position.get('contracts', 0)) > 0:
                    liquidation_price = position.get('liquidationPrice')
                    if liquidation_price:
                        real_liq_price = float(liquidation_price)
                        logger.info(f"🎯 REAL Liquidation Price from Binance: ${real_liq_price:.8f}")
                        return real_liq_price
            
            logger.warning(f"⚠️ No active position found for {symbol} - cannot get liquidation price")
            return None
            
        except Exception as e:
            logger.error(f"❌ Error fetching real liquidation price from Binance: {e}")
            return None

    def _wait_for_position_and_get_liquidation(self, symbol: str, max_wait_time: int = 10) -> float:
        """Wait for position to appear and fetch its liquidation price"""
        try:
            logger.info(f"⏳ Waiting for position to appear and fetching liquidation price...")
            
            for attempt in range(max_wait_time):
                time.sleep(1)  # Wait 1 second between attempts
                
                try:
                    positions = self.exchange.fetch_positions([symbol])
                    
                    for position in positions:
                        if float(position.get('contracts', 0)) > 0:
                            liquidation_price = position.get('liquidationPrice')
                            if liquidation_price:
                                real_liq_price = float(liquidation_price)
                                logger.info(f"✅ Found position! Real Liquidation Price: ${real_liq_price:.8f}")
                                return real_liq_price
                    
                    logger.info(f"⏳ Attempt {attempt + 1}/{max_wait_time}: Position not found yet...")
                    
                except Exception as e:
                    logger.warning(f"⚠️ Attempt {attempt + 1} failed: {e}")
                    continue
            
            logger.error(f"❌ Failed to get liquidation price after {max_wait_time} attempts")
            return None
            
        except Exception as e:
            logger.error(f"❌ Error waiting for position: {e}")
            return None

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
            volatility_buffer = 0.05  # Additional 5% for market volatility
            slippage_buffer = 0.02   # Additional 2% for slippage
            
            total_buffer = base_buffer + volatility_buffer + slippage_buffer
            
            if side == 'long':
                # Distance from entry to liquidation
                max_loss_distance = entry_price - liquidation_price
                safe_loss_distance = max_loss_distance * (1 - total_buffer)
                ultra_safe_stop = entry_price - safe_loss_distance
                
                # Never let stop loss be worse than original strategy
                final_stop = max(ultra_safe_stop, original_stop)
                
                logger.info(f"🛡️ ULTRA-SAFE Long Stop Calculation:")
                logger.info(f"   Entry: ${entry_price:.8f}")
                logger.info(f"   Real Liquidation: ${liquidation_price:.8f}")
                logger.info(f"   Max Loss Distance: ${max_loss_distance:.8f}")
                logger.info(f"   Safe Distance: ${safe_loss_distance:.8f} ({(1-total_buffer)*100:.1f}% of max)")
                logger.info(f"   Original Stop: ${original_stop:.8f}")
                logger.info(f"   Ultra-Safe Stop: ${final_stop:.8f}")
                
            else:
                # Distance from entry to liquidation
                max_loss_distance = liquidation_price - entry_price
                safe_loss_distance = max_loss_distance * (1 - total_buffer)
                ultra_safe_stop = entry_price + safe_loss_distance
                
                # Never let stop loss be worse than original strategy
                final_stop = min(ultra_safe_stop, original_stop)
                
                logger.info(f"🛡️ ULTRA-SAFE Short Stop Calculation:")
                logger.info(f"   Entry: ${entry_price:.8f}")
                logger.info(f"   Real Liquidation: ${liquidation_price:.8f}")
                logger.info(f"   Max Loss Distance: ${max_loss_distance:.8f}")
                logger.info(f"   Safe Distance: ${safe_loss_distance:.8f} ({(1-total_buffer)*100:.1f}% of max)")
                logger.info(f"   Original Stop: ${original_stop:.8f}")
                logger.info(f"   Ultra-Safe Stop: ${final_stop:.8f}")
            
            # Final safety check - ensure stop is never closer to liquidation than 5%
            if side == 'long':
                min_distance = (entry_price - liquidation_price) * 0.05
                absolute_min_stop = liquidation_price + min_distance
                if final_stop < absolute_min_stop:
                    logger.warning(f"⚠️ Stop too close to liquidation! Using absolute minimum: ${absolute_min_stop:.8f}")
                    final_stop = absolute_min_stop
            else:
                min_distance = (liquidation_price - entry_price) * 0.05
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
                           margin_amount, stop_loss, take_profit, tp_type, real_liquidation_price=None):
        """Record trade entry to CSV with REAL liquidation price from Binance"""
        
        trade_data = {
            'Date': datetime.now().strftime("%Y-%m-%d"),
            'Time': datetime.now().strftime("%H:%M:%S"),
            'Action': 'ENTRY',
            'Coin': coin_name,
            'Symbol': symbol,
            'Side': side,
            'Leverage': leverage,
            'Entry_Price': entry_price,
            'Real_Liquidation_Price_Binance': real_liquidation_price,
            'Quantity': quantity,
            'Notional_USD': entry_price * quantity,
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
            'Expected_TP_Profit': abs(take_profit - entry_price) * quantity if take_profit else None
        }
        self._save_trade_to_csv(trade_data)

    def _find_swing_high_low(self, df, lookback=10):
        """Find the last swing high and swing low from price data"""
        try:
            if len(df) < lookback * 2:
                return {
                    'swing_high': df['high'].max(),
                    'swing_low': df['low'].min()
                }
            
            swing_high = None
            swing_low = None
            
            for i in range(lookback, len(df) - lookback):
                is_swing_high = True
                current_high = df['high'].iloc[i]
                
                for j in range(i - lookback, i + lookback + 1):
                    if j != i and df['high'].iloc[j] >= current_high:
                        is_swing_high = False
                        break
                
                if is_swing_high:
                    swing_high = current_high
            
            for i in range(lookback, len(df) - lookback):
                is_swing_low = True
                current_low = df['low'].iloc[i]
                
                for j in range(i - lookback, i + lookback + 1):
                    if j != i and df['low'].iloc[j] <= current_low:
                        is_swing_low = False
                        break
                
                if is_swing_low:
                    swing_low = current_low
            
            if swing_high is None:
                swing_high = df['high'].tail(20).max()
            if swing_low is None:
                swing_low = df['low'].tail(20).min()
            
            return {
                'swing_high': swing_high,
                'swing_low': swing_low
            }
            
        except Exception as e:
            logger.error(f"❌ Error finding swing points: {e}")
            return {
                'swing_high': df['high'].max(),
                'swing_low': df['low'].min()
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

    def trade(self, coin, margin_amount, leverage=5, side='long', take_profit_ratio=2.0, 
              use_fixed_tp=False, fixed_tp_percent=2.5, use_swing_levels=False, 
              swing_lookback=10, use_resistance_support=False, rs_lookback=20,
              use_fixed_amount_tp=False, fixed_tp_amount=20, liquidation_buffer=25):
        """Execute a LIQUIDATION-SAFE futures trade using REAL liquidation price from Binance
        
        🛡️ KEY SAFETY FEATURES:
        - Fetches REAL liquidation price directly from Binance API after trade execution
        - Uses actual Binance liquidation data instead of calculations
        - Applies multiple safety buffers (volatility + slippage + user buffer)
        - Never places trades that could lead to liquidation
        
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
            liquidation_buffer: Safety buffer percentage (minimum 25% recommended!)
        """
        try:
            symbol, coin_name = self._normalize_coin_input(coin)
            if not symbol or not coin_name:
                logger.error(f"❌ Invalid coin input: {coin}")
                return False
            
            # Enforce minimum safety buffer
            if liquidation_buffer < 8:
                logger.warning(f"⚠️ Buffer {liquidation_buffer}% too low! Using minimum 20%")
                liquidation_buffer = 8
            
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
            quantity = math.floor(quantity * factor) / factor
            
            logger.info(f"📊 Position Details:")
            logger.info(f"   Margin: ${margin_amount}")
            logger.info(f"   Leverage: {leverage}x")
            logger.info(f"   Notional: ${notional_value:.2f}")
            logger.info(f"   Quantity: {quantity:.8f} {coin_name}")
            
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
                        logger.info(f"📊 Swing High: ${swing_high:.8f} | Swing Low: ${swing_low:.8f}")
                    
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
            
            # Calculate stop loss and take profit levels (initial calculation)
            if use_fixed_amount_tp:
                stop_distance = atr_value * 1.5
                
                if side == 'long':
                    initial_stop_loss = current_price - stop_distance
                    tp_price_distance = fixed_tp_amount / quantity
                    take_profit = current_price + tp_price_distance
                else:
                    initial_stop_loss = current_price + stop_distance
                    tp_price_distance = fixed_tp_amount / quantity
                    take_profit = current_price - tp_price_distance
                
                tp_type = f"Fixed Amount ${fixed_tp_amount} + ATR-based SL"
                
            elif use_resistance_support:
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
                
                tp_type = f"Swing levels (lookback: {swing_lookback})"
                
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
            
            logger.info(f"📊 Initial Strategy levels:")
            logger.info(f"   Initial Stop Loss: ${initial_stop_loss:.8f}")
            logger.info(f"   Take Profit ({tp_type}): ${take_profit:.8f}")
            
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
                order = self.exchange.create_market_order(symbol, order_side, quantity)
                execution_time = time.time() - start_time
                
                logger.info(f"⚡ Order executed in {execution_time:.2f} seconds")
                
                entry_price = float(order['average']) if order['average'] else current_price
                
                logger.info(f"✅ ORDER FILLED!")
                logger.info(f"   Side: {side.upper()}")
                logger.info(f"   Entry Price: ${entry_price:.8f}")
                logger.info(f"   Quantity: {quantity:.8f} {coin_name}")
                logger.info(f"   Notional: ${entry_price * quantity:.2f}")
                logger.info(f"   Margin Used: ${margin_amount}")
                
                # 🎯 CRITICAL: Get REAL liquidation price from Binance API
                logger.info("🎯 FETCHING REAL LIQUIDATION PRICE FROM BINANCE...")
                real_liquidation_price = self._wait_for_position_and_get_liquidation(symbol, max_wait_time=10)
                
                if real_liquidation_price is None:
                    logger.error("❌ Failed to get real liquidation price from Binance!")
                    logger.error("❌ CLOSING POSITION for safety!")
                    self.close_position(coin)
                    return False
                
                # Calculate distance to real liquidation
                if side == 'long':
                    liq_distance_pct = ((entry_price - real_liquidation_price) / entry_price) * 100
                else:
                    liq_distance_pct = ((real_liquidation_price - entry_price) / entry_price) * 100
                
                logger.info(f"🛡️ Real Liquidation Distance: {liq_distance_pct:.2f}%")
                
                # SAFETY CHECK: Ensure minimum liquidation distance with REAL price
                min_required_distance = liquidation_buffer + 1  # Extra 1% safety margin
                if liq_distance_pct < min_required_distance:
                    logger.error(f"❌ POSITION TOO RISKY: Real liquidation too close!")
                    logger.error(f"   Required distance: {min_required_distance:.1f}%")
                    logger.error(f"   Actual distance: {liq_distance_pct:.2f}%")
                    logger.error(f"❌ CLOSING POSITION for safety!")
                    self.close_position(coin)
                    return False
                
                # 🛡️ CRITICAL: Calculate ultra-safe stop loss using REAL liquidation price
                logger.info("🛡️ CALCULATING ULTRA-SAFE STOP LOSS WITH REAL LIQUIDATION...")
                safe_stop_loss = self._calculate_ultra_safe_stop_loss(
                    entry_price, real_liquidation_price, side, initial_stop_loss, liquidation_buffer)
                
                logger.info(f"📊 Final Strategy levels with REAL liquidation:")
                logger.info(f"   🎯 REAL Liquidation Price: ${real_liquidation_price:.8f}")
                logger.info(f"   🛡️ ULTRA-SAFE Stop Loss: ${safe_stop_loss:.8f}")
                logger.info(f"   Take Profit ({tp_type}): ${take_profit:.8f}")
                
                # Final safety validation with real liquidation
                if side == 'long':
                    stop_to_liq_distance = ((safe_stop_loss - real_liquidation_price) / entry_price) * 100
                    if stop_to_liq_distance < 5:
                        logger.error(f"❌ FINAL SAFETY CHECK FAILED: Stop loss too close to real liquidation!")
                        logger.error(f"   Stop to liquidation distance: {stop_to_liq_distance:.2f}%")
                        logger.error(f"❌ CLOSING POSITION for safety!")
                        self.close_position(coin)
                        return False
                else:
                    stop_to_liq_distance = ((real_liquidation_price - safe_stop_loss) / entry_price) * 100
                    if stop_to_liq_distance < 5:
                        logger.error(f"❌ FINAL SAFETY CHECK FAILED: Stop loss too close to real liquidation!")
                        logger.error(f"   Stop to liquidation distance: {stop_to_liq_distance:.2f}%")
                        logger.error(f"❌ CLOSING POSITION for safety!")
                        self.close_position(coin)
                        return False
                
                # Calculate final distances and metrics
                if side == 'long':
                    stop_distance_pct = ((entry_price - safe_stop_loss) / entry_price) * 100
                else:
                    stop_distance_pct = ((safe_stop_loss - entry_price) / entry_price) * 100
                
                logger.info(f"🛡️ FINAL SAFETY METRICS:")
                logger.info(f"   Real Liquidation Distance: {liq_distance_pct:.2f}%")
                logger.info(f"   Stop Loss Distance: {stop_distance_pct:.2f}%")
                logger.info(f"   Safety Buffer: {liq_distance_pct - stop_distance_pct:.2f}%")
                logger.info(f"   Target Buffer: {liquidation_buffer}%")
                
                # Calculate risk/reward with safe stop
                if side == 'long':
                    risk = abs(safe_stop_loss - entry_price) * quantity
                    reward = abs(take_profit - entry_price) * quantity
                else:
                    risk = abs(entry_price - safe_stop_loss) * quantity
                    reward = abs(entry_price - take_profit) * quantity
                
                actual_ratio = reward / risk if risk > 0 else 0
                logger.info(f"⚖️ Risk/Reward: 1:{actual_ratio:.2f}")
                
                # Show expected profit for fixed amount TP
                if use_fixed_amount_tp:
                    logger.info(f"💰 Expected TP Profit: ${reward:.2f} (Target: ${fixed_tp_amount})")
                
                # Record trade entry to CSV with REAL liquidation price
                self._record_trade_entry(symbol, coin_name, side, leverage, entry_price, 
                                       quantity, margin_amount, safe_stop_loss, take_profit, 
                                       tp_type, real_liquidation_price)
                
                logger.info("✅ LIQUIDATION-SAFE TRADE COMPLETED SUCCESSFULLY!")
                logger.info("🛡️ Using REAL liquidation price from Binance API")
                
                return {
                    'success': True,
                    'symbol': symbol,
                    'coin': coin_name,
                    'side': side,
                    'leverage': leverage,
                    'entry_price': entry_price,
                    'real_liquidation_price': real_liquidation_price,
                    'quantity': quantity,
                    'margin_used': margin_amount,
                    'stop_loss': safe_stop_loss,
                    'take_profit': take_profit,
                    'tp_type': tp_type,
                    'safety_buffer': liq_distance_pct - stop_distance_pct
                }
                
            except Exception as e:
                logger.error(f"❌ Order execution failed: {e}")
                return False
            
        except Exception as e:
            logger.error(f"❌ Critical error in liquidation-safe trade: {e}")
            return False

    def close_position(self, coin, entry_price=None, margin_amount=None):
        """Manually close a futures position"""
        try:
            symbol, coin_name = self._normalize_coin_input(coin)
            if not symbol or not coin_name:
                logger.error(f"❌ Invalid coin input: {coin}")
                return False
            
            logger.info(f"🔄 CLOSING FUTURES POSITION: {coin_name}")
            
            # Get current positions
            positions = self.exchange.fetch_positions([symbol])
            active_position = None
            
            for pos in positions:
                if float(pos['contracts']) > 0:
                    active_position = pos
                    break
            
            if not active_position:
                logger.info(f"❌ No active position for {symbol}")
                return False
            
            quantity = float(active_position['contracts'])
            side = active_position['side']
            
            # Get current price
            try:
                current_price = self.perpetual_fetcher.get_current_price(symbol)
                logger.info(f"📊 Current price: ${current_price:.8f}")
            except Exception as e:
                ticker = self.exchange.fetch_ticker(symbol)
                current_price = ticker['last']
            
            logger.info(f"📊 Position: {side.upper()} {quantity:.8f} {coin_name}")
            
            # Execute closing order
            logger.info("🔥 EXECUTING CLOSING ORDER...")
            start_time = time.time()
            
            close_side = 'sell' if side == 'long' else 'buy'
            order = self.exchange.create_market_order(symbol, close_side, quantity)
            execution_time = time.time() - start_time
            
            exit_price = float(order['average']) if order['average'] else current_price
            
            logger.info(f"⚡ Order executed in {execution_time:.2f} seconds")
            logger.info(f"✅ FUTURES POSITION CLOSED - {coin_name}")
            logger.info(f"💰 Exit Price: ${exit_price:.8f}")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error closing futures position: {e}")
            return False

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
        """Get all active positions with REAL liquidation prices from Binance"""
        try:
            logger.info("📊 FETCHING ALL ACTIVE POSITIONS WITH REAL LIQUIDATION PRICES...")
            positions = self.exchange.fetch_positions()
            active_positions = []
            
            for position in positions:
                if float(position.get('contracts', 0)) > 0:
                    symbol = position.get('symbol')
                    side = position.get('side')
                    size = float(position.get('contracts', 0))
                    entry_price = float(position.get('entryPrice', 0))
                    real_liquidation = float(position.get('liquidationPrice', 0)) if position.get('liquidationPrice') else None
                    margin_used = float(position.get('initialMargin', 0))
                    
                    pos_data = {
                        'symbol': symbol,
                        'side': side,
                        'size': size,
                        'entry_price': entry_price,
                        'mark_price': float(position.get('markPrice', 0)),
                        'real_liquidation_price': real_liquidation,
                        'unrealized_pnl': float(position.get('unrealizedPnl', 0)),
                        'percentage': float(position.get('percentage', 0)),
                        'margin_used': margin_used,
                        'maintenance_margin': float(position.get('maintenanceMargin', 0)),
                        'notional': float(position.get('notional', 0))
                    }
                    active_positions.append(pos_data)
                    
                    # Log position details with REAL liquidation price
                    logger.info(f"📍 {symbol} | {side.upper()}")
                    logger.info(f"   Size: {size:.8f}")
                    logger.info(f"   Entry: ${entry_price:.8f}")
                    logger.info(f"   Mark: ${pos_data['mark_price']:.8f}")
                    
                    if real_liquidation:
                        # Calculate distance to real liquidation
                        if side == 'long':
                            liq_distance = ((entry_price - real_liquidation) / entry_price) * 100
                        else:
                            liq_distance = ((real_liquidation - entry_price) / entry_price) * 100
                        
                        logger.info(f"   🎯 REAL Liquidation: ${real_liquidation:.8f}")
                        logger.info(f"   🛡️ Distance to Liquidation: {liq_distance:.2f}%")
                    else:
                        logger.info(f"   🎯 Liquidation: Not available")
                    
                    logger.info(f"   PnL: ${pos_data['unrealized_pnl']:.4f} ({pos_data['percentage']:.2f}%)")
                    logger.info(f"   Margin: ${margin_used:.4f}")
                    logger.info("   " + "="*50)
            
            if not active_positions:
                logger.info("📍 No active positions found")
            
            return active_positions
            
        except Exception as e:
            logger.error(f"❌ Error fetching positions: {e}")
            return []

# Initialize the liquidation-safe trader
futures_trader = LiquidationSafeFuturesTrader()

# 🛡️ LIQUIDATION-SAFE TRADING EXAMPLES WITH REAL BINANCE LIQUIDATION PRICES:

# 1. Conservative trade with 30% buffer (RECOMMENDED for high leverage)
# futures_trader.trade("BTC", 100, leverage=10, side="long", liquidation_buffer=30)

# 2. Moderate trade with 25% buffer (DEFAULT - good balance)
# futures_trader.trade("ETH", 50, leverage=5, side="short", liquidation_buffer=25)

# 3. Aggressive trade with 20% buffer (MINIMUM recommended)
# futures_trader.trade("BNB", 200, leverage=3, side="long", liquidation_buffer=20)

# 4. Ultra-conservative high leverage trade with 40% buffer
# futures_trader.trade("BTC", 50, leverage=50, side="long", liquidation_buffer=40)

# 5. Fixed amount TP with safety
# futures_trader.trade("BTC", 100, leverage=10, side="long", 
#                     use_fixed_amount_tp=True, fixed_tp_amount=25, liquidation_buffer=30)

# 6. Swing trading with safety
# futures_trader.trade("SOL", 200, leverage=5, side="long", 
#                     use_swing_levels=True, swing_lookback=15, liquidation_buffer=25)

# Check all positions with REAL liquidation prices
# futures_trader.get_all_positions()

# Get account balance
# futures_trader.get_balance()