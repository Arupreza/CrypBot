import ccxt
import pandas as pd
import talib as ta
import time
import logging
from datetime import datetime
import os
from dotenv import load_dotenv
import threading
import math
import requests
from typing import Dict, List

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
        self._symbol_cache = None  # Cache for available symbols
        self._last_cache_update = 0
        self._cache_duration = 3600  # Cache symbols for 1 hour
    
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
        self._update_symbol_cache()  # Ensure symbol cache is up-to-date
        
        # Handle different input formats
        if '/' in symbol:
            base_coin = symbol.split('/')[0]
            quote_coin = symbol.split('/')[1] if len(symbol.split('/')) > 1 else 'USDT'
            formatted_symbol = f"{base_coin}{quote_coin}"
        elif any(symbol.endswith(quote) for quote in ['USDT', 'BUSD', 'USDC', 'BTC', 'ETH', 'BNB']):
            formatted_symbol = symbol
        else:
            formatted_symbol = f"{symbol}USDT"

        # Extended symbol mappings for common cryptocurrencies
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
            # Add more mappings as needed
        }

        # Check if the input matches a mapped symbol
        if symbol in symbol_map:
            formatted_symbol = symbol_map[symbol]

        # Validate against cached symbols
        if formatted_symbol in self._symbol_cache:
            return formatted_symbol

        # Try alternative formats
        base_coin = formatted_symbol.replace('USDT', '').replace('BUSD', '').replace('USDC', '')
        alternative_formats = [
            f"{base_coin}USDT",
            f"{base_coin}BUSD",
            f"{base_coin}USDC",
        ]

        for alt_symbol in alternative_formats:
            if alt_symbol in self._symbol_cache:
                logger.info(f"✅ Found alternative symbol: {alt_symbol} for input: {symbol}")
                return alt_symbol

        # Suggest similar symbols
        similar_symbols = [s for s in self._symbol_cache if base_coin.lower() in s.lower()]
        if similar_symbols:
            logger.warning(f"❌ Symbol {formatted_symbol} not found. Similar symbols: {', '.join(similar_symbols[:5])}")
            logger.info(f"💡 Try using one of these symbols or check with futures_bot.list_available_symbols('{base_coin[:3]}')")
        else:
            logger.error(f"❌ Symbol {formatted_symbol} not found in Binance Futures markets")
            logger.info(f"💡 Popular futures symbols: BTCUSDT, ETHUSDT, BNBUSDT, ADAUSDT, SOLUSDT")
            logger.info(f"🔍 Use futures_bot.list_available_symbols('{base_coin[:3]}') to search")

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
                'limit': min(limit, 1500)  # Binance API limit
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
    
    def get_24hr_stats(self, symbol: str) -> Dict:
        """Get 24hr ticker statistics"""
        try:
            symbol = self._format_symbol(symbol)
            if not symbol:
                return {}
            url = f"{self.base_url}/fapi/v1/ticker/24hr"
            params = {'symbol': symbol.upper()}
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            return response.json()
        except requests.RequestException as e:
            logger.error(f"❌ Error fetching 24hr stats for {symbol}: {e}")
            return {}
    
    def get_all_24hr_stats(self) -> List:
        """Get 24hr stats for all symbols"""
        try:
            url = f"{self.base_url}/fapi/v1/ticker/24hr"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"❌ Error fetching all 24hr stats: {e}")
            return []
    
    def fetch_ticker(self, symbol: str) -> Dict:
        """Get ticker data in CCXT-compatible format"""
        try:
            stats = self.get_24hr_stats(symbol)
            if stats:
                return {
                    'last': float(stats['lastPrice']),
                    'percentage': float(stats['priceChangePercent'])
                }
            return None
        except Exception as e:
            logger.error(f"❌ Error fetching ticker for {symbol}: {e}")
            return None
    
    def fetch_ohlcv(self, symbol: str, timeframe: str = '1h', limit: int = 100) -> List:
        """Get OHLCV data in CCXT-compatible format"""
        try:
            df = self.get_klines(symbol, timeframe, limit)
            if df is not None and not df.empty:
                ohlcv = [
                    [
                        int(row['timestamp'].timestamp() * 1000),
                        float(row['open']),
                        float(row['high']),
                        float(row['low']),
                        float(row['close']),
                        float(row['volume'])
                    ] for _, row in df.iterrows()
                ]
                return ohlcv
            return []
        except Exception as e:
            logger.error(f"❌ Error fetching OHLCV for {symbol}: {e}")
            return []

class FuturesAutoTrader:
    def __init__(self, reports_folder_path="./home/lisa/Arupreza/LiveBot/"):
        """Initialize futures auto trader with reports folder path"""
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
            logger.info(f"💼 Available Margin: ${balance['USDT']['free']:.2f}")
        except Exception as e:
            logger.error(f"❌ Connection failed: {e}")
            return
        
        self.timeframe = '15m'
        self.reports_folder = reports_folder_path
        self._create_reports_folder()
        self.positions = {}
        self.monitoring = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()
        
        logger.info(f"🤖 Futures Auto Trader Ready! Reports will be saved to: {self.reports_folder}")
        logger.info("📊 Using Binance Perpetual Futures chart data")
    
    def _normalize_coin_input(self, coin_input: str) -> tuple:
        """Simple normalization - just validate the symbol exists"""
        try:
            # Clean up the input
            symbol = coin_input.upper().strip()
            
            # Update symbol cache to ensure we have latest symbols
            self.perpetual_fetcher._update_symbol_cache()
            
            # If it's already in correct format and exists, use it
            if symbol in self.perpetual_fetcher._symbol_cache:
                base_coin = symbol.replace('USDT', '').replace('BUSD', '').replace('USDC', '')
                logger.info(f"📊 Using symbol: {symbol} (base: {base_coin})")
                return symbol, base_coin
            
            # If not found, try adding USDT if it doesn't have a quote currency
            if not any(symbol.endswith(quote) for quote in ['USDT', 'BUSD', 'USDC', 'BTC', 'ETH', 'BNB']):
                symbol_with_usdt = f"{symbol}USDT"
                if symbol_with_usdt in self.perpetual_fetcher._symbol_cache:
                    base_coin = symbol
                    logger.info(f"📊 Auto-corrected to: {symbol_with_usdt} (base: {base_coin})")
                    return symbol_with_usdt, base_coin
            
            # Symbol not found
            base_coin = symbol.replace('USDT', '').replace('BUSD', '').replace('USDC', '')
            similar_symbols = [s for s in self.perpetual_fetcher._symbol_cache if base_coin.lower() in s.lower()]
            
            if similar_symbols:
                logger.error(f"❌ Symbol {symbol} not found. Similar symbols: {', '.join(similar_symbols[:5])}")
            else:
                logger.error(f"❌ Symbol {symbol} not found in Binance Futures")
            
            return None, None
            
        except Exception as e:
            logger.error(f"❌ Error normalizing symbol '{coin_input}': {e}")
            return None, None
    
    def get_futures_symbol_format(self, coin: str) -> str:
        """Get the exact futures symbol format for a coin"""
        try:
            symbol, base_coin = self._normalize_coin_input(coin)
            if symbol:
                logger.info(f"📊 Futures symbol for {base_coin}: {symbol}")
                return symbol
            return None
        except Exception as e:
            logger.error(f"❌ Error getting futures symbol format: {e}")
            return None
    
    def list_available_symbols(self, search_term: str = None) -> List:
        """List available futures trading symbols"""
        try:
            markets = self.exchange.load_markets()
            futures_symbols = [symbol for symbol in markets.keys() if markets[symbol]['type'] == 'future']
            
            if search_term:
                search_term = search_term.upper()
                filtered_symbols = [s for s in futures_symbols if search_term in s]
                logger.info(f"🔍 Futures symbols containing '{search_term}':")
                for symbol in filtered_symbols[:20]:
                    logger.info(f"   • {symbol}")
                return filtered_symbols
            else:
                logger.info(f"📊 Total available futures symbols: {len(futures_symbols)}")
                logger.info("🔥 Popular futures symbols:")
                popular = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'ADAUSDT', 'SOLUSDT', 
                          'DOTUSDT', 'MATICUSDT', 'LINKUSDT', 'AVAXUSDT', 'ATOMUSDT']
                for symbol in popular:
                    if symbol in futures_symbols:
                        logger.info(f"   ✅ {symbol}")
                    else:
                        logger.info(f"   ❌ {symbol} (not available)")
                return futures_symbols
                
        except Exception as e:
            logger.error(f"❌ Error listing symbols: {e}")
            return []
    
    def check_symbol_availability(self, coin: str) -> bool:
        """Check if a symbol is available for futures trading"""
        try:
            symbol, coin_name = self._normalize_coin_input(coin)
            if symbol and coin_name:
                logger.info(f"✅ {coin_name} ({symbol}) is available for futures trading")
                stats = self.get_perpetual_stats(coin)
                if stats:
                    logger.info(f"💰 Current price: ${float(stats.get('lastPrice', 0)):.8f}")
                    logger.info(f"📊 24h volume: {float(stats.get('volume', 0)):,.0f}")
                return True
            return False
        except Exception as e:
            logger.error(f"❌ Error checking symbol availability: {e}")
            return False

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
            'Use_Breakeven': pos['use_breakeven'],
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
            'Use_Breakeven': pos['use_breakeven'],
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
        
        if pos['side'] == 'long':
            pnl_usd = (exit_price - pos['entry_price']) * pos['quantity']
        else:
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
            'Use_Breakeven': pos['use_breakeven'],
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
        """Find the last swing high and swing low from price data"""
        try:
            if len(df) < lookback * 2:
                logger.warning("⚠️ Not enough data for swing detection, using fallback")
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
            return {
                'swing_high': df['high'].max(),
                'swing_low': df['low'].min()
            }

    def trade(self, coin, margin_amount, leverage=5, side='long', take_profit_ratio=2.0, use_fixed_tp=False, fixed_tp_percent=2.5, use_swing_levels=False, swing_lookback=10, use_breakeven=True):
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
            use_breakeven: Whether to move stop to breakeven after 1 hour (True/False)
        """
        try:
            symbol, coin_name = self._normalize_coin_input(coin)
            if not symbol or not coin_name:
                logger.error(f"❌ Invalid coin input: {coin}")
                return False
            
            logger.info(f"🚀 INITIATING FUTURES TRADE: {coin_name} {side.upper()} with ${margin_amount} margin at {leverage}x")
            logger.info(f"📊 Processing {symbol} - {side.upper()} position...")
            logger.info(f"⚖️ Breakeven Move: {'✅ ENABLED' if use_breakeven else '❌ DISABLED'}")
            
            if symbol in self.positions:
                logger.warning(f"❌ Already trading {symbol}")
                return False
            
            side = side.lower()
            if side not in ['long', 'short']:
                logger.error(f"❌ Invalid side: {side}. Use 'long' or 'short'")
                return False
            
            balance = self.exchange.fetch_balance()
            usdt_balance = balance['USDT']['free']
            
            if usdt_balance < margin_amount:
                logger.error(f"❌ Insufficient balance. Have ${usdt_balance:.2f}, need ${margin_amount}")
                return False
            
            logger.info(f"✅ Balance sufficient: ${usdt_balance:.2f}")
            
            # Load markets and check if symbol exists in CCXT
            markets = self.exchange.load_markets()
            market = None
            
            # Try to get market info from CCXT
            if symbol in markets:
                market = markets[symbol]
                logger.info(f"📊 Found market info in CCXT for {symbol}")
            else:
                # Symbol not in CCXT markets, but we know it exists from perpetual fetcher
                logger.warning(f"⚠️ {symbol} not found in CCXT markets, using fallback market info")
                
                # Create a fallback market structure with reasonable defaults
                market = {
                    'precision': {'amount': 8, 'price': 8},
                    'limits': {
                        'amount': {'min': 0.001, 'max': 1000000},
                        'price': {'min': 0.00000001, 'max': 1000000},
                        'cost': {'min': 1, 'max': 1000000}
                    }
                }
            
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
            
            try:
                current_price = self.perpetual_fetcher.get_current_price(symbol)
                logger.info(f"📊 Current price (perpetual): ${current_price:.8f}")
            except Exception as e:
                logger.warning(f"⚠️ Perpetual price failed, using CCXT: {e}")
                ticker = self.exchange.fetch_ticker(symbol)
                current_price = ticker['last']
                logger.info(f"📊 Current price (CCXT): ${current_price:.8f}")
            
            notional_value = margin_amount * leverage
            quantity = notional_value / current_price
            
            # Use precision from market info (fallback to 8 if not available)
            precision = market['precision']['amount']
            if isinstance(precision, float):
                precision = int(-1 * math.log10(precision))
            elif precision is None:
                precision = 8  # Default precision
            
            factor = 10 ** precision
            quantity = math.floor(quantity * factor) / factor
            
            logger.info(f"📊 Position Details:")
            logger.info(f"   Margin: ${margin_amount}")
            logger.info(f"   Leverage: {leverage}x")
            logger.info(f"   Notional: ${notional_value:.2f}")
            logger.info(f"   Quantity: {quantity:.8f} {coin_name}")
            
            # Use minimum amount from market info (fallback to reasonable default)
            min_amount = market['limits']['amount']['min'] if market['limits']['amount']['min'] else 0.001
            if quantity < min_amount:
                logger.error(f"❌ Position size too small: {quantity:.8f} (min: {min_amount})")
                return False
            
            try:
                logger.info("📈 Fetching perpetual futures chart data...")
                df = self.perpetual_fetcher.get_klines(symbol, self.timeframe, 100)
                
                if df is not None and not df.empty:
                    df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)
                    atr_value = df['atr'].iloc[-1]
                    
                    if use_swing_levels:
                        swing_levels = self._find_swing_high_low(df, swing_lookback)
                        swing_high = swing_levels['swing_high']
                        swing_low = swing_levels['swing_low']
                        logger.info(f"📊 Swing High: ${swing_high:.8f} | Swing Low: ${swing_low:.8f}")
                    
                    logger.info(f"📊 ATR value: ${atr_value:.8f}")
                    logger.info(f"📊 Using perpetual futures chart data ({len(df)} candles)")
                else:
                    raise Exception("No perpetual chart data received")
                    
            except Exception as e:
                logger.error(f"❌ Error fetching perpetual chart data: {e}")
                logger.info("🔄 Falling back to CCXT data...")
                
                try:
                    ohlcv = self.exchange.fetch_ohlcv(symbol, self.timeframe, limit=100)
                    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                    df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)
                    atr_value = df['atr'].iloc[-1]
                    
                    if use_swing_levels:
                        swing_levels = self._find_swing_high_low(df, swing_lookback)
                        swing_high = swing_levels['swing_high']
                        swing_low = swing_levels['swing_low']
                        logger.info(f"📊 Swing High: ${swing_high:.8f} | Swing Low: ${swing_low:.8f}")
                    
                    logger.info(f"📊 ATR value: ${atr_value:.8f} (from CCXT fallback)")
                except Exception as e2:
                    logger.error(f"❌ CCXT fallback also failed: {e2}")
                    atr_value = current_price * 0.02
                    use_swing_levels = False
                    logger.info(f"📊 Using hardcoded fallback ATR: ${atr_value:.8f}")
            
            # Calculate stop loss and take profit levels
            if use_swing_levels:
                if side == 'long':
                    stop_loss = swing_low
                    swing_take_profit = swing_high
                    if stop_loss >= current_price:
                        stop_loss = current_price * 0.97
                        logger.warning("⚠️ Swing low above entry, using 3% stop loss")
                    if swing_take_profit <= current_price:
                        swing_take_profit = current_price * 1.05
                        logger.warning("⚠️ Swing high below entry, using 5% take profit")
                else:
                    stop_loss = swing_high
                    swing_take_profit = swing_low
                    if stop_loss <= current_price:
                        stop_loss = current_price * 1.03
                        logger.warning("⚠️ Swing high below entry, using 3% stop loss")
                    if swing_take_profit >= current_price:
                        swing_take_profit = current_price * 0.95
                        logger.warning("⚠️ Swing low above entry, using 5% take profit")
                
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
                stop_distance = atr_value * 1.5
                
                if side == 'long':
                    stop_loss = current_price - stop_distance
                    atr_take_profit = current_price + (stop_distance * take_profit_ratio)
                    fixed_take_profit = current_price * (1 + fixed_tp_percent / 100)
                    swing_take_profit = swing_high if 'swing_high' in locals() else current_price * 1.05
                else:
                    stop_loss = current_price + stop_distance
                    atr_take_profit = current_price - (stop_distance * take_profit_ratio)
                    fixed_take_profit = current_price * (1 - fixed_tp_percent / 100)
                    swing_take_profit = swing_low if 'swing_low' in locals() else current_price * 0.95
                
                if use_fixed_tp:
                    take_profit = fixed_take_profit
                    tp_type = f"Fixed {fixed_tp_percent}%"
                else:
                    take_profit = atr_take_profit
                    tp_type = f"ATR-based (1:{take_profit_ratio})"
            
            logger.info(f"📊 Calculated levels:")
            logger.info(f"   Stop Loss: ${stop_loss:.8f}")
            logger.info(f"   Take Profit ({tp_type}): ${take_profit:.8f}")
            
            logger.info("🔥 EXECUTING FUTURES ORDER...")
            start_time = time.time()
            
            try:
                order_side = 'buy' if side == 'long' else 'sell'
                order = self.exchange.create_market_order(symbol, order_side, quantity)
                execution_time = time.time() - start_time
                
                logger.info(f"⚡ Order executed in {execution_time:.2f} seconds")
                
                entry_price = float(order['average']) if order['average'] else current_price
                
                logger.info(f"✅ FUTURES ORDER FILLED!")
                logger.info(f"   Side: {side.upper()}")
                logger.info(f"   Entry Price: ${entry_price:.8f}")
                logger.info(f"   Quantity: {quantity:.8f} {coin_name}")
                logger.info(f"   Notional: ${entry_price * quantity:.2f}")
                logger.info(f"   Margin Used: ${margin_amount}")
                
            except Exception as e:
                logger.error(f"❌ Order execution failed: {e}")
                return False
            
            # Recalculate levels with actual entry price if needed
            if abs(entry_price - current_price) > (current_price * 0.001):
                logger.info("🔄 Recalculating levels with actual entry price...")
                
                if use_swing_levels:
                    if side == 'long':
                        if stop_loss >= entry_price:
                            stop_loss = entry_price * 0.97
                            logger.warning("⚠️ Adjusted swing stop loss for actual entry")
                        if swing_take_profit <= entry_price:
                            swing_take_profit = entry_price * 1.05
                            logger.warning("⚠️ Adjusted swing take profit for actual entry")
                    else:
                        if stop_loss <= entry_price:
                            stop_loss = entry_price * 1.03
                            logger.warning("⚠️ Adjusted swing stop loss for actual entry")
                        if swing_take_profit >= entry_price:
                            swing_take_profit = entry_price * 0.95
                            logger.warning("⚠️ Adjusted swing take profit for actual entry")
                    
                    take_profit = swing_take_profit
                    
                    stop_distance = abs(entry_price - stop_loss)
                    if side == 'long':
                        atr_take_profit = entry_price + (stop_distance * take_profit_ratio)
                        fixed_take_profit = entry_price * (1 + fixed_tp_percent / 100)
                    else:
                        atr_take_profit = entry_price - (stop_distance * take_profit_ratio)
                        fixed_take_profit = entry_price * (1 - fixed_tp_percent / 100)
                
                else:
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
            
            # Store position information
            self.positions[symbol] = {
                'coin': coin_name,
                'coin_pair': symbol,
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
                'use_swing_levels': use_swing_levels,
                'swing_lookback': swing_lookback,
                'tp_type': tp_type,
                'use_breakeven': use_breakeven  # NEW: Store breakeven preference
            }
            
            if 'swing_take_profit' in locals():
                self.positions[symbol]['swing_take_profit'] = swing_take_profit
            
            # Calculate risk/reward
            if side == 'long':
                risk = stop_distance * quantity
                reward = (take_profit - entry_price) * quantity if use_fixed_tp else (stop_distance * take_profit_ratio) * quantity
            else:
                risk = stop_distance * quantity
                reward = (entry_price - take_profit) * quantity if use_fixed_tp else (stop_distance * take_profit_ratio) * quantity
            
            actual_ratio = reward / risk if risk > 0 else 0
            
            logger.info(f"✅ FUTURES TRADE EXECUTED - {coin_name} {side.upper()}")
            logger.info(f"💰 Entry Price: ${entry_price:.8f}")
            logger.info(f"📊 Quantity: {quantity:.8f} {coin_name}")
            logger.info(f"💸 Notional: ${entry_price * quantity:.2f}")
            logger.info(f"💼 Margin Used: ${margin_amount}")
            logger.info(f"⚡ Leverage: {leverage}x")
            logger.info(f"🛑 Stop Loss: ${stop_loss:.8f} (Risk: ${risk:.2f})")
            logger.info(f"🎯 Take Profit: ${take_profit:.8f} (Reward: ${reward:.2f})")
            logger.info(f"📈 Type: {tp_type}")
            logger.info(f"⚖️ Risk/Reward: 1:{actual_ratio:.2f}")
            logger.info(f"⚖️ Breakeven Move: {'✅ ENABLED' if use_breakeven else '❌ DISABLED'}")
            logger.info(f"📊 Data Source: Binance Perpetual Futures API")
            
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
                try:
                    current = self.perpetual_fetcher.get_current_price(symbol)
                    logger.debug(f"📊 Using perpetual price for {symbol}: ${current:.8f}")
                except Exception as e:
                    logger.warning(f"⚠️ Perpetual price failed for {symbol}, using CCXT: {e}")
                    ticker = self.exchange.fetch_ticker(symbol)
                    current = ticker['last']
                
                if pos['side'] == 'long':
                    pnl = (current - pos['entry_price']) * pos['quantity']
                else:
                    pnl = (pos['entry_price'] - current) * pos['quantity']
                
                pnl_pct = (pnl / pos['margin_used']) * 100
                
                total_margin_used += pos['margin_used']
                total_unrealized_pnl += pnl
                
                if pos['side'] == 'long':
                    stop_distance = ((current - pos['stop_loss']) / current) * 100
                    target_distance = ((pos['take_profit'] - current) / current) * 100
                else:
                    stop_distance = ((pos['stop_loss'] - current) / current) * 100
                    target_distance = ((current - pos['take_profit']) / current) * 100
                
                time_passed = datetime.now() - pos['entry_time']
                hours_passed = time_passed.total_seconds() / 3600
                
                breakeven_status = "✅ ENABLED" if pos.get('use_breakeven', True) else "❌ DISABLED"
                
                logger.info(f"🪙 {pos['coin']} ({pos['side'].upper()}) - {pos['leverage']}x:")
                logger.info(f"   💰 Entry: ${pos['entry_price']:.8f} → Current: ${current:.8f}")
                logger.info(f"   📈 P&L: ${pnl:.2f} ({pnl_pct:+.2f}%) | Margin: ${pos['margin_used']:.2f}")
                logger.info(f"   🛑 Stop: ${pos['stop_loss']:.8f} ({stop_distance:+.2f}%)")
                logger.info(f"   🎯 Target: ${pos['take_profit']:.8f} ({target_distance:+.2f}%)")
                logger.info(f"   📊 TP Type: {pos['tp_type']}")
                logger.info(f"   ⏱️ Time: {hours_passed:.1f}h | Breakeven: {'✅' if pos['stop_moved_to_breakeven'] else '❌'}")
                logger.info(f"   ⚖️ Auto-Breakeven: {breakeven_status}")
                
            except Exception as e:
                logger.error(f"❌ Error getting {symbol} status: {e}")
        
        total_pnl_pct = (total_unrealized_pnl / total_margin_used * 100) if total_margin_used > 0 else 0
        
        logger.info(f"💼 FUTURES PORTFOLIO SUMMARY")
        logger.info(f"   💸 Total Margin Used: ${total_margin_used:.2f}")
        logger.info(f"   📈 Unrealized P&L: ${total_unrealized_pnl:.2f} ({total_pnl_pct:+.2f}%)")
        logger.info(f"   📊 Data Source: Binance Perpetual Futures API")
    
    def close(self, coin):
        """Manually close a futures position"""
        try:
            symbol, coin_name = self._normalize_coin_input(coin)
            if not symbol or not coin_name:
                logger.error(f"❌ Invalid coin input: {coin}")
                return False
            
            logger.info(f"🔄 CLOSING FUTURES POSITION: {coin_name}")
            
            if symbol not in self.positions:
                logger.info(f"❌ No active position for {symbol}")
                return False
            
            pos = self.positions[symbol]
            
            try:
                current = self.perpetual_fetcher.get_current_price(symbol)
                logger.info(f"📊 Current price (perpetual): ${current:.8f}")
            except Exception as e:
                logger.warning(f"⚠️ Perpetual price failed, using CCXT: {e}")
                ticker = self.exchange.fetch_ticker(symbol)
                current = ticker['last']
                logger.info(f"📊 Current price (CCXT): ${current:.8f}")
            
            logger.info(f"📊 Position: {pos['side'].upper()} {pos['quantity']:.8f} {coin_name}")
            
            logger.info("🔥 EXECUTING CLOSING ORDER...")
            start_time = time.time()
            
            close_side = 'sell' if pos['side'] == 'long' else 'buy'
            order = self.exchange.create_market_order(symbol, close_side, pos['quantity'])
            execution_time = time.time() - start_time
            
            exit_price = float(order['average']) if order['average'] else current
            
            if pos['side'] == 'long':
                pnl = (exit_price - pos['entry_price']) * pos['quantity']
            else:
                pnl = (pos['entry_price'] - exit_price) * pos['quantity']
            
            pnl_pct = (pnl / pos['margin_used']) * 100
            
            logger.info(f"⚡ Order executed in {execution_time:.2f} seconds")
            logger.info(f"✅ FUTURES POSITION CLOSED - {coin_name}")
            logger.info(f"💰 Exit Price: ${exit_price:.8f}")
            logger.info(f"📈 P&L: ${pnl:.2f} ({pnl_pct:+.2f}%)")
            
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
                        try:
                            current_price = self.perpetual_fetcher.get_current_price(symbol)
                        except Exception as e:
                            logger.warning(f"⚠️ Perpetual price failed for {symbol}, using CCXT: {e}")
                            ticker = self.exchange.fetch_ticker(symbol)
                            current_price = ticker['last']
                        
                        # MODIFIED: Check if breakeven is enabled before moving stop
                        if not pos['stop_moved_to_breakeven'] and pos.get('use_breakeven', True):
                            time_passed = datetime.now() - pos['entry_time']
                            if time_passed.total_seconds() >= 3600:  # 1 hour
                                if (pos['side'] == 'long' and current_price > pos['entry_price']) or \
                                   (pos['side'] == 'short' and current_price < pos['entry_price']):
                                    pos['stop_loss'] = pos['entry_price']
                                    pos['stop_moved_to_breakeven'] = True
                                    logger.info(f"⏰ {pos['coin']} - Stop moved to breakeven at ${pos['entry_price']:.8f}")
                                    self._record_breakeven_move(symbol, pos)
                        
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
            
            if pos['side'] == 'long':
                pnl = (exit_price - pos['entry_price']) * pos['quantity']
            else:
                pnl = (pos['entry_price'] - exit_price) * pos['quantity']
            
            pnl_pct = (pnl / pos['margin_used']) * 100
            
            logger.info(f"✅ {exit_reason} executed!")
            logger.info(f"   Exit Price: ${exit_price:.8f}")
            logger.info(f"   P&L: ${pnl:.2f} ({pnl_pct:+.2f}%)")
            
            self._record_trade_exit(symbol, pos, exit_price, exit_reason)
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error executing futures exit for {symbol}: {e}")
            return False
    
    def switch_take_profit(self, coin, tp_type=None):
        """Switch between different take profit types for an active position"""
        try:
            symbol, coin_name = self._normalize_coin_input(coin)
            if not symbol or not coin_name:
                logger.error(f"❌ Invalid coin input: {coin}")
                return False
            
            if symbol not in self.positions:
                logger.warning(f"❌ No active position for {symbol}")
                return False
            
            pos = self.positions[symbol]
            
            if tp_type is None:
                if pos.get('use_swing_levels', False):
                    new_tp_type = 'atr'
                elif pos.get('use_fixed_tp', False):
                    new_tp_type = 'swing' if pos.get('swing_take_profit') else 'atr'
                else:
                    new_tp_type = 'fixed'
            else:
                new_tp_type = tp_type.lower()
            
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
            else:
                pos['take_profit'] = pos['atr_take_profit']
                pos['tp_type'] = f"ATR-based (1:{pos['take_profit_ratio']})"
                pos['use_swing_levels'] = False
                pos['use_fixed_tp'] = False
            
            logger.info(f"🔄 SWITCHED TAKE PROFIT - {coin_name}")
            logger.info(f"🎯 New Take Profit: ${pos['take_profit']:.8f}")
            logger.info(f"📊 Type: {pos['tp_type']}")
            
            alternatives = []
            if pos.get('atr_take_profit') and not (not pos.get('use_swing_levels', False) and not pos.get('use_fixed_tp', False)):
                alternatives.append(f"ATR: ${pos['atr_take_profit']:.8f}")
            if pos.get('fixed_take_profit') and not pos.get('use_fixed_tp', False):
                alternatives.append(f"Fixed: ${pos['fixed_take_profit']:.8f}")
            if pos.get('swing_take_profit') and not pos.get('use_swing_levels', False):
                alternatives.append(f"Swing: ${pos['swing_take_profit']:.8f}")
            
            if alternatives:
                logger.info(f"🔄 Alternatives: {' | '.join(alternatives)}")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error switching take profit: {e}")
            return False

    def toggle_breakeven(self, coin, enable=None):
        """Toggle or set breakeven functionality for an active position
        
        Args:
            coin: Trading symbol
            enable: True to enable, False to disable, None to toggle
        """
        try:
            symbol, coin_name = self._normalize_coin_input(coin)
            if not symbol or not coin_name:
                logger.error(f"❌ Invalid coin input: {coin}")
                return False
            
            if symbol not in self.positions:
                logger.warning(f"❌ No active position for {symbol}")
                return False
            
            pos = self.positions[symbol]
            
            if enable is None:
                # Toggle current state
                pos['use_breakeven'] = not pos.get('use_breakeven', True)
            else:
                # Set specific state
                pos['use_breakeven'] = bool(enable)
            
            status = "✅ ENABLED" if pos['use_breakeven'] else "❌ DISABLED"
            logger.info(f"⚖️ BREAKEVEN TOGGLE - {coin_name}")
            logger.info(f"⚖️ Auto-Breakeven: {status}")
            
            if pos['use_breakeven'] and pos['stop_moved_to_breakeven']:
                logger.info("ℹ️ Note: Stop has already been moved to breakeven")
            elif not pos['use_breakeven']:
                logger.info("ℹ️ Note: Stop will NOT be moved to breakeven automatically")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error toggling breakeven: {e}")
            return False
    
    def set_leverage(self, coin, leverage):
        """Set leverage for a specific symbol"""
        try:
            symbol, coin_name = self._normalize_coin_input(coin)
            if not symbol or not coin_name:
                logger.error(f"❌ Invalid coin input: {coin}")
                return False
            
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
            
            active_positions = [pos for pos in positions if float(pos['contracts']) > 0]
            
            logger.info("💼 FUTURES ACCOUNT INFO")
            logger.info(f"💰 USDT Balance: ${balance['USDT']['free']:.2f}")
            logger.info(f"💼 Used Margin: ${balance['USDT']['used']:.2f}")
            logger.info(f"📊 Total Balance: ${balance['USDT']['total']:.2f}")
            logger.info(f"📊 Data Source: Binance Perpetual Futures API")
            
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
            
            df = pd.read_csv(csv_filepath)
            
            exits = df[df['Action'] == 'EXIT'].copy()
            
            if exits.empty:
                logger.info(f"📊 No completed futures trades found for {date}")
                return
            
            total_trades = len(exits)
            winning_trades = len(exits[exits['PnL_USD'] > 0])
            losing_trades = len(exits[exits['PnL_USD'] < 0])
            breakeven_trades = len(exits[exits['PnL_USD'] == 0])
            
            total_pnl = exits['PnL_USD'].sum()
            win_rate = (winning_trades / total_trades) * 100 if total_trades > 0 else 0
            
            avg_win = exits[exits['PnL_USD'] > 0]['PnL_USD'].mean() if winning_trades > 0 else 0
            avg_loss = exits[exits['PnL_USD'] < 0]['PnL_USD'].mean() if losing_trades > 0 else 0
            
            best_trade = exits['PnL_USD'].max() if not exits.empty else 0
            worst_trade = exits['PnL_USD'].min() if not exits.empty else 0
            
            avg_duration = exits['Trade_Duration_Minutes'].mean() if 'Trade_Duration_Minutes' in exits.columns else 0
            avg_leverage = exits['Leverage'].mean() if 'Leverage' in exits.columns else 0
            
            long_trades = len(exits[exits['Side'] == 'long']) if 'Side' in exits.columns else 0
            short_trades = len(exits[exits['Side'] == 'short']) if 'Side' in exits.columns else 0
            
            # Count breakeven-enabled trades
            breakeven_enabled_trades = len(exits[exits['Use_Breakeven'] == True]) if 'Use_Breakeven' in exits.columns else 0
            breakeven_disabled_trades = len(exits[exits['Use_Breakeven'] == False]) if 'Use_Breakeven' in exits.columns else 0
            
            logger.info(f"📊 FUTURES TRADING SUMMARY - {date}")
            logger.info(f"📈 Total Trades: {total_trades}")
            logger.info(f"📊 Long Trades: {long_trades} | Short Trades: {short_trades}")
            logger.info(f"⚖️ Breakeven Enabled: {breakeven_enabled_trades} | Disabled: {breakeven_disabled_trades}")
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
            logger.info(f"📊 Data Source: Binance Perpetual Futures API")
            if avg_loss != 0:
                logger.info(f"⚖️ Risk/Reward Ratio: 1:{abs(avg_win/avg_loss):.2f}")
            
            logger.info("📋 TRADE DETAILS:")
            for _, trade in exits.iterrows():
                pnl_emoji = "📈" if trade['PnL_USD'] > 0 else "📉" if trade['PnL_USD'] < 0 else "➖"
                side_info = f" ({trade['Side'].upper()})" if 'Side' in trade else ""
                leverage_info = f" {trade['Leverage']:.0f}x" if 'Leverage' in trade else ""
                breakeven_info = f" [BE: {'✅' if trade.get('Use_Breakeven', True) else '❌'}]" if 'Use_Breakeven' in trade else ""
                logger.info(f"   {pnl_emoji} {trade['Coin']}{side_info}{leverage_info}{breakeven_info}: ${trade['PnL_USD']:.2f} ({trade['PnL_Percent']:+.1f}%) - {trade['Exit_Reason']}")
            
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
        logger.info(f"📊 Data Source: Binance Perpetual Futures API")
        
        if self.positions:
            logger.info("📋 Current Positions:")
            for symbol, pos in self.positions.items():
                breakeven_status = "✅" if pos.get('use_breakeven', True) else "❌"
                logger.info(f"   • {pos['coin']} {pos['side'].upper()} {pos['leverage']}x - Entry: ${pos['entry_price']:.6f} [BE: {breakeven_status}]")
    
    def force_restart_monitoring(self):
        """Force restart monitoring thread"""
        try:
            self.monitoring = False
            if hasattr(self, 'monitor_thread'):
                self.monitor_thread.join(timeout=5)
            
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

# Initialize the bot
if 'futures_bot' not in globals() or futures_bot is None:
    futures_bot = FuturesAutoTrader()
else:
    if not futures_bot.monitoring:
        futures_bot.restart_monitoring()

# Example usage with breakeven control:

# Long trade with breakeven enabled (default)
# futures_bot.trade("BTC", 100, leverage=10, side="long", take_profit_ratio=2.0, use_breakeven=True)

# Short trade with breakeven disabled
# futures_bot.trade("ETH", 50, leverage=5, side="short", use_fixed_tp=True, fixed_tp_percent=3.0, use_breakeven=False)

# Long trade using swing levels with breakeven disabled
# futures_bot.trade("BNB", 200, leverage=3, side="long", use_swing_levels=True, swing_lookback=15, use_breakeven=False)

# Toggle breakeven for an existing position
# futures_bot.toggle_breakeven("BTC")  # Toggle current state
# futures_bot.toggle_breakeven("BTC", True)  # Enable breakeven
# futures_bot.toggle_breakeven("BTC", False)  # Disable breakeven

# Check status (now shows breakeven status)
# futures_bot.status()

# Generate report (now includes breakeven statistics)
# futures_bot.generate_summary_report()