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

class FuturesTrader:
    def __init__(self, reports_folder_path="./futures_reports/"):
        """Initialize futures trader"""
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
        
        logger.info("🤖 Futures Trader Ready!")
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
                           margin_amount, stop_loss, take_profit, tp_type):
        """Record trade entry to CSV"""
        liquidation_price = self._calculate_liquidation_price(entry_price, leverage, side)
        
        trade_data = {
            'Date': datetime.now().strftime("%Y-%m-%d"),
            'Time': datetime.now().strftime("%H:%M:%S"),
            'Action': 'ENTRY',
            'Coin': coin_name,
            'Symbol': symbol,
            'Side': side,
            'Leverage': leverage,
            'Entry_Price': entry_price,
            'Liquidation_Price': liquidation_price,
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

    def _record_trade_exit(self, symbol, coin_name, side, entry_price, quantity, 
                          margin_amount, exit_price, exit_reason):
        """Record trade exit to CSV"""
        exit_time = datetime.now()
        
        if side == 'long':
            pnl_usd = (exit_price - entry_price) * quantity
        else:
            pnl_usd = (entry_price - exit_price) * quantity
            
        pnl_percent = (pnl_usd / margin_amount) * 100
        
        trade_data = {
            'Date': exit_time.strftime("%Y-%m-%d"),
            'Time': exit_time.strftime("%H:%M:%S"),
            'Action': 'EXIT',
            'Coin': coin_name,
            'Symbol': symbol,
            'Side': side,
            'Leverage': None,
            'Entry_Price': entry_price,
            'Quantity': quantity,
            'Notional_USD': entry_price * quantity,
            'Margin_Used': margin_amount,
            'Stop_Loss': None,
            'Take_Profit': None,
            'TP_Type': None,
            'Exit_Price': exit_price,
            'Exit_Time': exit_time.strftime("%H:%M:%S"),
            'PnL_USD': pnl_usd,
            'PnL_Percent': pnl_percent,
            'Exit_Reason': exit_reason,
            'Trade_Duration_Minutes': None
        }
        self._save_trade_to_csv(trade_data)

    def _calculate_liquidation_price(self, entry_price, leverage, side, margin_rate=0.004):
        """Calculate liquidation price for isolated margin
        
        Args:
            entry_price: Entry price of the position
            leverage: Leverage used
            side: 'long' or 'short'
            margin_rate: Maintenance margin rate (0.4% for most pairs)
        
        Returns:
            Liquidation price
        """
        try:
            if side == 'long':
                # For long: Liquidation = Entry * (1 - 1/leverage + margin_rate)
                liquidation_price = entry_price * (1 - (1/leverage) + margin_rate)
            else:
                # For short: Liquidation = Entry * (1 + 1/leverage - margin_rate)
                liquidation_price = entry_price * (1 + (1/leverage) - margin_rate)
            
            return liquidation_price
            
        except Exception as e:
            logger.error(f"❌ Error calculating liquidation price: {e}")
            # Conservative fallback
            if side == 'long':
                return entry_price * 0.92  # 8% below entry
            else:
                return entry_price * 1.08  # 8% above entry

    def _get_safe_stop_loss(self, entry_price, liquidation_price, side, atr_stop_loss, buffer_percent=10):
        """Get safe stop loss that's well before liquidation
        
        Args:
            entry_price: Entry price
            liquidation_price: Calculated liquidation price
            side: 'long' or 'short'
            atr_stop_loss: ATR-based stop loss
            buffer_percent: Safety buffer percentage before liquidation (default 10%)
        
        Returns:
            Safe stop loss price
        """
        try:
            # Calculate buffer distance from liquidation
            if side == 'long':
                buffer_distance = (entry_price - liquidation_price) * (buffer_percent / 100)
                max_safe_stop = liquidation_price + buffer_distance
                
                # Use the safer of ATR stop or max safe stop
                safe_stop = min(atr_stop_loss, max_safe_stop) if atr_stop_loss > max_safe_stop else max_safe_stop
                
                logger.info(f"📊 Long position safety check:")
                logger.info(f"   Liquidation: ${liquidation_price:.8f}")
                logger.info(f"   Max Safe Stop: ${max_safe_stop:.8f} ({buffer_percent}% buffer)")
                logger.info(f"   ATR Stop: ${atr_stop_loss:.8f}")
                logger.info(f"   Selected Stop: ${safe_stop:.8f}")
                
            else:
                buffer_distance = (liquidation_price - entry_price) * (buffer_percent / 100)
                max_safe_stop = liquidation_price - buffer_distance
                
                # Use the safer of ATR stop or max safe stop
                safe_stop = max(atr_stop_loss, max_safe_stop) if atr_stop_loss < max_safe_stop else max_safe_stop
                
                logger.info(f"📊 Short position safety check:")
                logger.info(f"   Liquidation: ${liquidation_price:.8f}")
                logger.info(f"   Max Safe Stop: ${max_safe_stop:.8f} ({buffer_percent}% buffer)")
                logger.info(f"   ATR Stop: ${atr_stop_loss:.8f}")
                logger.info(f"   Selected Stop: ${safe_stop:.8f}")
            
            return safe_stop
            
        except Exception as e:
            logger.error(f"❌ Error calculating safe stop loss: {e}")
            return atr_stop_loss

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
              use_fixed_amount_tp=False, fixed_tp_amount=20, liquidation_buffer=10):
        """Execute a futures trade with isolated margin
        
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
            use_resistance_support: Whether to use resistance/support levels (TP at resistance/support, SL at ATR)
            rs_lookback: Lookback period for resistance/support detection
            use_fixed_amount_tp: Whether to use fixed dollar amount TP
            fixed_tp_amount: Fixed dollar amount for take profit (e.g., $20)
            liquidation_buffer: Safety buffer percentage before liquidation (default 10%)
        """
        try:
            symbol, coin_name = self._normalize_coin_input(coin)
            if not symbol or not coin_name:
                logger.error(f"❌ Invalid coin input: {coin}")
                return False
            
            logger.info(f"🚀 INITIATING FUTURES TRADE: {coin_name} {side.upper()} with ${margin_amount} margin at {leverage}x")
            
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
            
            # Set leverage and margin mode
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
                logger.info("📈 Fetching chart data...")
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
            
            # Calculate stop loss and take profit levels
            if use_fixed_amount_tp:
                # Use fixed dollar amount for TP and ATR for SL
                stop_distance = atr_value * 1.5
                
                if side == 'long':
                    stop_loss = current_price - stop_distance  # ATR-based stop loss
                    # Calculate TP price based on fixed dollar amount
                    tp_price_distance = fixed_tp_amount / quantity
                    take_profit = current_price + tp_price_distance
                else:
                    stop_loss = current_price + stop_distance  # ATR-based stop loss
                    # Calculate TP price based on fixed dollar amount
                    tp_price_distance = fixed_tp_amount / quantity
                    take_profit = current_price - tp_price_distance
                
                tp_type = f"Fixed Amount ${fixed_tp_amount} + ATR-based SL"
                
            elif use_resistance_support:
                # Use resistance/support for TP and ATR for SL
                stop_distance = atr_value * 1.5
                
                if side == 'long':
                    stop_loss = current_price - stop_distance  # ATR-based stop loss
                    take_profit = resistance if 'resistance' in locals() else current_price * 1.05
                    if take_profit <= current_price:
                        take_profit = current_price * 1.05
                        logger.warning("⚠️ Resistance below entry, using 5% take profit")
                else:
                    stop_loss = current_price + stop_distance  # ATR-based stop loss
                    take_profit = support if 'support' in locals() else current_price * 0.95
                    if take_profit >= current_price:
                        take_profit = current_price * 0.95
                        logger.warning("⚠️ Support above entry, using 5% take profit")
                
                tp_type = f"Resistance/Support (TP) + ATR (SL, lookback: {rs_lookback})"
                
            elif use_swing_levels:
                if side == 'long':
                    stop_loss = swing_low if 'swing_low' in locals() else current_price * 0.97
                    take_profit = swing_high if 'swing_high' in locals() else current_price * 1.05
                    if stop_loss >= current_price:
                        stop_loss = current_price * 0.97
                else:
                    stop_loss = swing_high if 'swing_high' in locals() else current_price * 1.03
                    take_profit = swing_low if 'swing_low' in locals() else current_price * 0.95
                    if stop_loss <= current_price:
                        stop_loss = current_price * 1.03
                
                tp_type = f"Swing levels (lookback: {swing_lookback})"
                
            else:
                stop_distance = atr_value * 1.5
                
                if side == 'long':
                    stop_loss = current_price - stop_distance
                    if use_fixed_tp:
                        take_profit = current_price * (1 + fixed_tp_percent / 100)
                        tp_type = f"Fixed {fixed_tp_percent}%"
                    else:
                        take_profit = current_price + (stop_distance * take_profit_ratio)
                        tp_type = f"ATR-based (1:{take_profit_ratio})"
                else:
                    stop_loss = current_price + stop_distance
                    if use_fixed_tp:
                        take_profit = current_price * (1 - fixed_tp_percent / 100)
                        tp_type = f"Fixed {fixed_tp_percent}%"
                    else:
                        take_profit = current_price - (stop_distance * take_profit_ratio)
                        tp_type = f"ATR-based (1:{take_profit_ratio})"
            
            logger.info(f"📊 Calculated levels:")
            logger.info(f"   Stop Loss: ${stop_loss:.8f}")
            logger.info(f"   Take Profit ({tp_type}): ${take_profit:.8f}")
            
            # Execute order
            logger.info("🔥 EXECUTING FUTURES ORDER...")
            start_time = time.time()
            
            try:
                order_side = 'buy' if side == 'long' else 'sell'
                order = self.exchange.create_market_order(symbol, order_side, quantity)
                execution_time = time.time() - start_time
                
                logger.info(f"⚡ Order executed in {execution_time:.2f} seconds")
                
                entry_price = float(order['average']) if order['average'] else current_price
                
                # Calculate liquidation price for safety
                liquidation_price = self._calculate_liquidation_price(entry_price, leverage, side)
                
                logger.info(f"✅ FUTURES ORDER FILLED!")
                logger.info(f"   Side: {side.upper()}")
                logger.info(f"   Entry Price: ${entry_price:.8f}")
                logger.info(f"   Liquidation Price: ${liquidation_price:.8f}")
                logger.info(f"   Quantity: {quantity:.8f} {coin_name}")
                logger.info(f"   Notional: ${entry_price * quantity:.2f}")
                logger.info(f"   Margin Used: ${margin_amount}")
                
                # Recalculate stop loss with liquidation safety
                original_stop_loss = stop_loss
                stop_loss = self._get_safe_stop_loss(entry_price, liquidation_price, side, stop_loss, liquidation_buffer)
                
                if abs(stop_loss - original_stop_loss) > (entry_price * 0.001):  # If stop changed significantly
                    logger.warning(f"⚠️ Stop loss adjusted for liquidation safety!")
                    logger.warning(f"   Original Stop: ${original_stop_loss:.8f}")
                    logger.warning(f"   Safe Stop: ${stop_loss:.8f}")
                    
                    # Recalculate take profit if using ratio-based strategies
                    if not use_fixed_tp and not use_swing_levels and not use_resistance_support and not use_fixed_amount_tp:
                        stop_distance = abs(entry_price - stop_loss)
                        if side == 'long':
                            take_profit = entry_price + (stop_distance * take_profit_ratio)
                        else:
                            take_profit = entry_price - (stop_distance * take_profit_ratio)
                        logger.info(f"   Adjusted Take Profit: ${take_profit:.8f}")
                
                logger.info(f"   Stop Loss: ${stop_loss:.8f}")
                logger.info(f"   Take Profit: ${take_profit:.8f}")
                logger.info(f"   TP Type: {tp_type}")
                
                # Calculate distance to liquidation
                if side == 'long':
                    liq_distance = ((entry_price - liquidation_price) / entry_price) * 100
                    stop_distance_pct = ((entry_price - stop_loss) / entry_price) * 100
                else:
                    liq_distance = ((liquidation_price - entry_price) / entry_price) * 100
                    stop_distance_pct = ((stop_loss - entry_price) / entry_price) * 100
                
                logger.info(f"🛡️ Liquidation Distance: {liq_distance:.2f}%")
                logger.info(f"🛑 Stop Loss Distance: {stop_distance_pct:.2f}%")
                logger.info(f"🛡️ Safety Buffer: {liq_distance - stop_distance_pct:.2f}%")
                
                # Calculate risk/reward
                if side == 'long':
                    risk = abs(stop_loss - entry_price) * quantity
                    reward = abs(take_profit - entry_price) * quantity
                else:
                    risk = abs(entry_price - stop_loss) * quantity
                    reward = abs(entry_price - take_profit) * quantity
                
                actual_ratio = reward / risk if risk > 0 else 0
                logger.info(f"⚖️ Risk/Reward: 1:{actual_ratio:.2f}")
                
                # Show expected profit for fixed amount TP
                if use_fixed_amount_tp:
                    logger.info(f"💰 Expected TP Profit: ${reward:.2f} (Target: ${fixed_tp_amount})")
                
                # Record trade entry to CSV
                self._record_trade_entry(symbol, coin_name, side, leverage, entry_price, 
                                       quantity, margin_amount, stop_loss, take_profit, tp_type)
                
                return {
                    'success': True,
                    'symbol': symbol,
                    'coin': coin_name,
                    'side': side,
                    'leverage': leverage,
                    'entry_price': entry_price,
                    'liquidation_price': liquidation_price,
                    'quantity': quantity,
                    'margin_used': margin_amount,
                    'stop_loss': stop_loss,
                    'take_profit': take_profit,
                    'tp_type': tp_type
                }
                
            except Exception as e:
                logger.error(f"❌ Order execution failed: {e}")
                return False
            
        except Exception as e:
            logger.error(f"❌ Critical error in futures trade execution: {e}")
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
            
            # Record trade exit to CSV if entry details provided
            if entry_price and margin_amount:
                self._record_trade_exit(symbol, coin_name, side, entry_price, quantity, 
                                      margin_amount, exit_price, "MANUAL_CLOSE")
            
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

# Initialize the trader
futures_trader = FuturesTrader()

# Example usage:
# Entry trade (automatically saves to CSV)
# result = futures_trader.trade("BTC", 100, leverage=10, side="long", take_profit_ratio=2.0)

# Exit trade (provide entry details for complete CSV record)
# if result and result['success']:
#     futures_trader.close_position("BTC", 
#                                  entry_price=result['entry_price'], 
#                                  margin_amount=result['margin_used'])

# Trading Strategy Examples:

# 1. ATR-based TP and SL (default)
# futures_trader.trade("ETH", 50, leverage=5, side="short", take_profit_ratio=2.0)

# 2. Fixed percentage TP with ATR-based SL
# futures_trader.trade("ETH", 50, leverage=5, side="short", use_fixed_tp=True, fixed_tp_percent=3.0)

# 3. Swing levels for both TP and SL
# futures_trader.trade("BNB", 200, leverage=3, side="long", use_swing_levels=True, swing_lookback=15)

# 4. Resistance/Support TP with ATR-based SL
# futures_trader.trade("BTC", 100, leverage=10, side="long", use_resistance_support=True, rs_lookback=20)

# 5. NEW: Fixed Dollar Amount TP with ATR-based SL
# futures_trader.trade("BTC", 100, leverage=10, side="long", use_fixed_amount_tp=True, fixed_tp_amount=25)
# futures_trader.trade("ETH", 200, leverage=5, side="short", use_fixed_amount_tp=True, fixed_tp_amount=50)

# futures_trader.get_balance()