"""
Live Triple-Strategy Crypto Trading Bot
--------------------------------------
This script runs three independent strategies simultaneously:
  1. Chandelier_ZLSMA
  2. MSB_FIB
  3. Pivot Point Supertrend (PVS)

Each strategy uses 1/3 of your USDT balance (or a user-specified amount),
manages its own entry/exit logic, and writes trade reports to CSV files.

Requirements:
  • Python 3.7+
  • python-binance (for Binance trading)
  • gate-api (for Gate.io trading)
  • pandas
  • numpy
  • python-dotenv

Before running, create a “.env” file in the same directory with:

    # Binance API credentials (if you want to use Binance)
    BINANCE_API_KEY=your_binance_api_key
    BINANCE_API_SECRET=your_binance_api_secret

    # Gate.io API credentials (if you want to use Gate.io)
    GATEIO_API_KEY=your_gateio_api_key
    GATEIO_API_SECRET=your_gateio_api_secret

Drop your indicator modules (“Chandelier_ZLSMA.py”, “MSB_Fib.py”, 
“EMAs_50_200_PPS.py”) in the same folder. Each module must expose:

  • Chandelier_ZLSMA.py:
      calculate_zlsma(df, close_column='close', length=200)
      calculate_chandelier(df, atr_period=1, atr_multiplier=2.0)
      merge_zlsma_chandelier(df_zlsma, df_chandelier)

  • MSB_Fib.py:
      market_structure_order_fib(df)

  • EMAs_50_200_PPS.py:
      pivot_point_supertrend(df)

Once everything is in place, run:
    python live_trading_bot.py

The bot will fetch 15-minute bars, evaluate signals for all three strategies, 
and place market orders when entry/exit conditions are met. Trades are logged 
to CSV under “trade_reports/”.

"""

import os
import time
import math
import pandas as pd
import numpy as np
from datetime import datetime
from dotenv import load_dotenv

# ──────────────────────────────────────────────────────────────────────────────
# 1) IMPORT INDICATOR FUNCTIONS
# ──────────────────────────────────────────────────────────────────────────────

from Chandelier_ZLSMA import (
    calculate_zlsma,
    calculate_chandelier,
    merge_zlsma_chandelier
)
from MSB_Fib import market_structure_order_fib
from EMAs_50_200_PPS import pivot_point_supertrend

# ──────────────────────────────────────────────────────────────────────────────
# 2) SETUP: Load environment, create directories
# ──────────────────────────────────────────────────────────────────────────────

load_dotenv()

TRADES_DIR = "trade_reports"
os.makedirs(TRADES_DIR, exist_ok=True)

# ──────────────────────────────────────────────────────────────────────────────
# 3) EXCHANGE CLIENT: Binance & Gate.io Minimal Wrapper
# ──────────────────────────────────────────────────────────────────────────────

class ExchangeClient:
    """
    Minimal unified client for Binance or Gate.io spot trading.
    Supports:
      • get_balance(asset)
      • get_ohlcv(symbol, limit=201, interval='15m')
      • place_market_buy(symbol, usdt_amount)
      • place_market_sell(symbol, quantity)
    """

    def __init__(self, exchange_name: str):
        self.name = exchange_name.lower()
        self._connect()

    def _connect(self):
        if self.name == 'binance':
            from binance.client import Client
            api_key = os.getenv('BINANCE_API_KEY')
            api_secret = os.getenv('BINANCE_API_SECRET')
            if not (api_key and api_secret):
                raise RuntimeError("Missing BINANCE_API_KEY or BINANCE_API_SECRET in .env")
            self.client = Client(api_key, api_secret, testnet=False)
            print("✅ Connected to Binance")

        elif self.name == 'gateio':
            import gate_api
            api_key = os.getenv('GATEIO_API_KEY')
            api_secret = os.getenv('GATEIO_API_SECRET')
            if not (api_key and api_secret):
                raise RuntimeError("Missing GATEIO_API_KEY or GATEIO_API_SECRET in .env")
            conf = gate_api.Configuration(
                host="https://api.gateio.ws/api/v4",
                key=api_key, secret=api_secret
            )
            self.client = gate_api.SpotApi(gate_api.ApiClient(conf))
            print("✅ Connected to Gate.io")

        else:
            raise ValueError("Supported exchanges: 'binance', 'gateio'")

    def get_balance(self, asset='USDT') -> float:
        """Return available free balance for a given asset (e.g. 'USDT' or 'BTC')."""
        try:
            if self.name == 'binance':
                bal = self.client.get_asset_balance(asset=asset)
                return float(bal['free']) if bal else 0.0
            else:  # gateio
                accounts = self.client.list_spot_accounts()
                for acct in accounts:
                    if acct.currency.upper() == asset.upper():
                        return float(acct.available)
                return 0.0
        except Exception as e:
            print(f"❌ get_balance error ({asset}): {e}")
            return 0.0

    def get_ohlcv(self, symbol='BTCUSDT', limit=201, interval='15m') -> pd.DataFrame:
        """
        Fetch OHLCV data as a DataFrame.
        Returns columns: ['open','high','low','close','volume'] indexed by datetime.
        """
        try:
            if self.name == 'binance':
                from binance.client import Client
                interval_map = {
                    '1m': Client.KLINE_INTERVAL_1MINUTE,
                    '3m': Client.KLINE_INTERVAL_3MINUTE,
                    '5m': Client.KLINE_INTERVAL_5MINUTE,
                    '15m': Client.KLINE_INTERVAL_15MINUTE,
                    '30m': Client.KLINE_INTERVAL_30MINUTE,
                    '1h': Client.KLINE_INTERVAL_1HOUR,
                    '4h': Client.KLINE_INTERVAL_4HOUR,
                    '1d': Client.KLINE_INTERVAL_1DAY,
                }
                k = self.client.get_klines(
                    symbol=symbol,
                    interval=interval_map.get(interval, Client.KLINE_INTERVAL_15MINUTE),
                    limit=limit
                )
                df = pd.DataFrame(k, columns=[
                    'timestamp','open','high','low','close','volume',
                    'close_time','quote_vol','num_trades',
                    'taker_base_vol','taker_quote_vol','ignore'
                ])
                for col in ['open','high','low','close','volume']:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
                df.set_index('datetime', inplace=True)
                return df[['open','high','low','close','volume']]

            else:  # gateio
                import gate_api
                pair = symbol.replace('USDT', '_USDT')
                data = []
                candles = self.client.list_candlesticks(
                    currency_pair=pair, interval=interval, limit=limit
                )
                # gate_api returns [timestamp (sec), vol, close, low, high, open]
                for c in candles:
                    ts_ms = int(c[0]) * 1000
                    data.append([
                        pd.to_datetime(ts_ms, unit='ms'),
                        float(c[5]),  # open
                        float(c[4]),  # high
                        float(c[3]),  # low
                        float(c[2]),  # close
                        float(c[1])   # volume
                    ])
                df = pd.DataFrame(data, columns=['datetime','open','high','low','close','volume'])
                df.set_index('datetime', inplace=True)
                df.sort_index(inplace=True)
                return df

        except Exception as e:
            print(f"❌ get_ohlcv error: {e}")
            return pd.DataFrame()

    def place_market_buy(self, symbol: str, usdt_amount: float) -> bool:
        """
        Place a market BUY order using approximately 'usdt_amount' USDT.
        Returns True on success, False otherwise.
        """
        try:
            if usdt_amount <= 0:
                print("❌ buy: invalid USDT amount")
                return False

            if self.name == 'binance':
                qty_usdt = usdt_amount * 0.999  # small slippage buffer
                self.client.order_market_buy(symbol=symbol, quoteOrderQty=qty_usdt)
                return True

            else:  # gateio
                import gate_api
                pair = symbol.replace('USDT', '_USDT')
                amt = round(usdt_amount * 0.999, 8)
                order = gate_api.Order(
                    currency_pair=pair, type='market', side='buy',
                    amount=str(amt), price='0'
                )
                self.client.create_order(order)
                return True

        except Exception as e:
            print(f"❌ place_market_buy error: {e}")
            return False

    def place_market_sell(self, symbol: str, quantity: float) -> bool:
        """
        Place a market SELL order of 'quantity' base asset.
        Returns True on success, False otherwise.
        """
        try:
            if quantity <= 0:
                print("❌ sell: invalid quantity")
                return False

            base = symbol.replace('USDT', '')
            if self.name == 'binance':
                info = self.client.get_symbol_info(symbol)
                # find LOT_SIZE filter to determine step size
                step_filter = next(
                    f for f in info['filters'] if f['filterType'] == 'LOT_SIZE'
                )
                step_size = float(step_filter['stepSize'])
                if step_size >= 1:
                    precision = 0
                else:
                    precision = len(str(step_size).split('.')[-1].rstrip('0'))
                qty = math.floor(quantity * (10**precision)) / (10**precision)
                if qty <= 0:
                    print("❌ sell: quantity rounds to zero")
                    return False
                self.client.order_market_sell(symbol=symbol, quantity=f"{qty:.{precision}f}")
                return True

            else:  # gateio
                import gate_api
                pair = symbol.replace('USDT', '_USDT')
                amt = round(quantity, 8)
                if amt <= 0:
                    print("❌ sell: quantity rounds to zero")
                    return False
                order = gate_api.Order(
                    currency_pair=pair, type='market', side='sell',
                    amount=str(amt), price='0'
                )
                self.client.create_order(order)
                return True

        except Exception as e:
            print(f"❌ place_market_sell error: {e}")
            return False

# ──────────────────────────────────────────────────────────────────────────────
# 4) STRATEGY CLASS: Holds Position State & Logging
# ──────────────────────────────────────────────────────────────────────────────

class Strategy:
    """
    Encapsulates a single strategy's position state and reporting.
    Tracks only 'long' positions in this implementation.
    """
    def __init__(self, name: str):
        self.name = name
        self.position = None      # None or 'long'
        self.entry_price = None
        self.stop_loss = None
        self.take_profit = None
        self.entry_time = None

    def open_long(self, client: ExchangeClient, symbol: str,
                  usdt_size: float, entry_price: float,
                  stop_loss: float, take_profit: float):
        """
        Place a market buy, then record state.
        Uses 'usdt_size' USDT for the order.
        """
        if client.place_market_buy(symbol, usdt_size):
            self.position    = 'long'
            self.entry_price = entry_price
            self.stop_loss   = stop_loss
            self.take_profit = take_profit
            self.entry_time  = datetime.now()
            print(f"✅ [{self.name}] OPEN LONG @ {entry_price:.2f} | SL={stop_loss:.2f} | TP={take_profit:.2f}")

    def close_long(self, client: ExchangeClient, symbol: str,
                   exit_price: float, reason: str):
        """
        Place a market sell of (balance_of_base / 3) coins, then reset state
        and write trade report. Assumes equal division among 3 strategies.
        """
        if self.position != 'long':
            return

        base = symbol.replace('USDT', '')
        total_base = client.get_balance(base)
        qty = total_base / 3.0
        if qty <= 0:
            print(f"❌ [{self.name}] close_long: no {base} to sell")
            return

        if client.place_market_sell(symbol, qty):
            pnl_pct = (exit_price - self.entry_price) / self.entry_price * 100
            pnl_usd = exit_price - self.entry_price

            # Prepare trade record
            record = {
                'timestamp'   : datetime.now(),
                'strategy'    : self.name,
                'symbol'      : symbol,
                'entry_time'  : self.entry_time,
                'exit_time'   : datetime.now(),
                'entry_price' : self.entry_price,
                'exit_price'  : exit_price,
                'stop_loss'   : self.stop_loss,
                'take_profit' : self.take_profit,
                'pnl_percent' : pnl_pct,
                'pnl_dollar'  : pnl_usd,
                'exit_reason' : reason,
                'duration'    : str(datetime.now() - self.entry_time),
            }

            # Save to daily CSV
            fname = os.path.join(TRADES_DIR, f"trades_{datetime.now():%Y%m%d}.csv")
            df = pd.DataFrame([record])
            if os.path.exists(fname):
                df.to_csv(fname, mode='a', header=False, index=False)
            else:
                df.to_csv(fname, mode='w', header=True, index=False)

            print(f"❌ [{self.name}] CLOSED LONG @ {exit_price:.2f} | Reason: {reason} | PnL: {pnl_pct:.2f}%")

            # Reset
            self.position    = None
            self.entry_price = None
            self.stop_loss   = None
            self.take_profit = None
            self.entry_time  = None

# ──────────────────────────────────────────────────────────────────────────────
# 5) HELPER FUNCTIONS: ATR & Swing Levels
# ──────────────────────────────────────────────────────────────────────────────

def calculate_atr(df: pd.DataFrame, period: int = 14) -> float:
    """Return last ATR value over 'period' bars."""
    df2 = df.copy()
    df2['hl'] = df2['high'] - df2['low']
    df2['hc'] = (df2['high'] - df2['close'].shift(1)).abs()
    df2['lc'] = (df2['low']  - df2['close'].shift(1)).abs()
    df2['tr'] = df2[['hl','hc','lc']].max(axis=1)
    return df2['tr'].rolling(period).mean().iloc[-1]

def get_swing_levels(df: pd.DataFrame, lookback: int = 20):
    """
    Compute recent swing high & swing low over last 'lookback' candles.
    Returns: (swing_high, swing_low)
    """
    swing_low  = df['low'].tail(lookback).min()
    swing_high = df['high'].tail(lookback).max()
    return swing_high, swing_low

# ──────────────────────────────────────────────────────────────────────────────
# 6) INSTANTIATE STRATEGIES
# ──────────────────────────────────────────────────────────────────────────────

strategy_chandelier = Strategy("CHANDELIER_ZLSMA")
strategy_msb       = Strategy("MSB_FIB")
strategy_pvs       = Strategy("PIVOT_POINT_SUPERTREND")

# ──────────────────────────────────────────────────────────────────────────────
# 7) CORE LOGIC: Analyze Signals & Manage Each Strategy
# ──────────────────────────────────────────────────────────────────────────────

def analyze_strategies(df: pd.DataFrame, client: ExchangeClient,
                       symbol: str, usdt_size: float):
    """
    For each of the three strategies, check entry/exit conditions and
    place orders accordingly.
    """
    current_price = df['close'].iloc[-1]
    print(f"\n[{datetime.now():%Y-%m-%d %H:%M:%S}] Current Price: {current_price:.2f}")

    # ─── 1) CHANDELIER_ZLSMA ─────────────────────────────────────────────────────
    try:
        df_zlsma = calculate_zlsma(df, close_column='close', length=200)
        df_chand = calculate_chandelier(df, atr_period=1, atr_multiplier=2.0)
        df_merge = merge_zlsma_chandelier(df_zlsma, df_chand)

        if not df_merge.empty:
            latest_zlsma = df_merge['zlsma_200'].iloc[-1]
            buy_signal   = df_merge['buy_signal'].iloc[-1] == 1
            sell_signal  = df_merge['sell_signal'].iloc[-1] == 1

            # ENTRY
            if strategy_chandelier.position is None:
                if buy_signal and current_price > latest_zlsma:
                    swing_high, swing_low = get_swing_levels(df, lookback=20)
                    atr_val = calculate_atr(df, period=14)
                    stop_loss = swing_low - atr_val
                    if stop_loss < current_price:
                        strategy_chandelier.open_long(
                            client, symbol, usdt_size,
                            entry_price=current_price,
                            stop_loss=stop_loss,
                            take_profit=swing_high
                        )
            else:
                # EXIT: SL/TP or sell_signal
                sl_hit = current_price <= strategy_chandelier.stop_loss
                tp_hit = current_price >= strategy_chandelier.take_profit
                if sl_hit:
                    strategy_chandelier.close_long(client, symbol, current_price, "SL Hit")
                elif tp_hit:
                    strategy_chandelier.close_long(client, symbol, current_price, "TP Hit")
                elif sell_signal:
                    strategy_chandelier.close_long(client, symbol, current_price, "Sell Signal")
    except Exception as e:
        print(f"❌ [CHANDELIER_ZLSMA] error: {e}")

    # ─── 2) MSB_FIB ───────────────────────────────────────────────────────────────
    try:
        df_msb = market_structure_order_fib(df)
        if df_msb is not None and not df_msb.empty:
            green_break = df_msb['green_break_above'].iloc[-1] == True
            red_break   = df_msb['red_break_below'].iloc[-1] == True

            # ENTRY
            if strategy_msb.position is None:
                if green_break:
                    swing_high, swing_low = get_swing_levels(df, lookback=20)
                    atr_val = calculate_atr(df, period=14)
                    stop_loss = swing_low - atr_val
                    if stop_loss < current_price:
                        strategy_msb.open_long(
                            client, symbol, usdt_size,
                            entry_price=current_price,
                            stop_loss=stop_loss,
                            take_profit=swing_high
                        )
            else:
                # EXIT: SL/TP or red_break
                sl_hit = current_price <= strategy_msb.stop_loss
                tp_hit = current_price >= strategy_msb.take_profit
                if sl_hit:
                    strategy_msb.close_long(client, symbol, current_price, "SL Hit")
                elif tp_hit:
                    strategy_msb.close_long(client, symbol, current_price, "TP Hit")
                elif red_break:
                    strategy_msb.close_long(client, symbol, current_price, "Red Break Exit")
    except Exception as e:
        print(f"❌ [MSB_FIB] error: {e}")

    # ─── 3) PIVOT POINT SUPERTREND ───────────────────────────────────────────────
    try:
        df_pvs = pivot_point_supertrend(df)
        if df_pvs is None or df_pvs.empty:
            print("   🎯 [PVS] No data returned.")
        else:
            cols = list(df_pvs.columns)
            print("   🎯 [PVS] Columns:", cols)

            # 1) If there's a 'Signal' column with +1/-1:
            if 'Signal' in cols:
                last_sig = df_pvs['Signal'].iloc[-1]
                latest_pvs_buy  = (last_sig == 1)
                latest_pvs_sell = (last_sig == -1)
            else:
                # 2) Fallback: look for any of these names:
                latest_pvs_buy  = False
                latest_pvs_sell = False
                for c in ['PVS_Buy','pvs_buy','Buy','buy_signal','signal_buy']:
                    if c in cols:
                        val = df_pvs[c].iloc[-1]
                        latest_pvs_buy = (val == 1 or val is True)
                        break
                for c in ['PVS_Sell','pvs_sell','Sell','sell_signal','signal_sell']:
                    if c in cols:
                        val = df_pvs[c].iloc[-1]
                        latest_pvs_sell = (val == 1 or val is True)
                        break

            # Compute EMAs for entry/exit
            ema50  = df['close'].ewm(span=50).mean().iloc[-1]
            ema200 = df['close'].ewm(span=200).mean().iloc[-1]

            # ENTRY
            if strategy_pvs.position is None:
                if latest_pvs_buy and current_price > ema50 and current_price > ema200:
                    # For PVS, SL=EMA50 and TP=EMA50 (0.2% band for exit)
                    strategy_pvs.open_long(
                        client, symbol, usdt_size,
                        entry_price=current_price,
                        stop_loss=ema50,
                        take_profit=ema50
                    )
            else:
                dist_to_ema50 = abs(current_price - ema50) / current_price
                if dist_to_ema50 <= 0.002:
                    reason = "EMA50 TP" if current_price > strategy_pvs.entry_price else "EMA50 SL"
                    strategy_pvs.close_long(client, symbol, current_price, reason)
                elif latest_pvs_sell:
                    strategy_pvs.close_long(client, symbol, current_price, "PVS Sell")

    except Exception as e:
        print(f"❌ [PIVOT_POINT_SUPERTREND] error: {e}")

    # ─── PRINT SUMMARY OF ACTIVE POSITIONS ────────────────────────────────────────
    active = 0
    for strat in (strategy_chandelier, strategy_msb, strategy_pvs):
        if strat.position == 'long':
            active += 1
            pnl_pct = (current_price - strat.entry_price) / strat.entry_price * 100
            print(f"   • [{strat.name}] LONG | PnL: {pnl_pct:.2f}%")
        else:
            print(f"   • [{strat.name}] no position")
    print(f"Active Positions: {active}/3")
    print("-" * 80)

# ──────────────────────────────────────────────────────────────────────────────
# 8) MAIN ENTRY & MENU
# ──────────────────────────────────────────────────────────────────────────────

def main():
    print("\n🚀 Live Triple-Strategy Crypto Trading Bot")
    print("   Each strategy uses ~1/3 of USDT balance or user-specified amount.\n")

    # 1) Choose exchange
    while True:
        exch = input("Choose exchange (binance/gateio): ").strip().lower()
        if exch in ('binance', 'gateio'):
            break
        print("❌ Please enter 'binance' or 'gateio'.")

    # 2) Choose trading pair
    symbol = input("Enter trading pair (e.g. BTCUSDT, ETHUSDT): ").strip().upper()
    if not symbol.endswith('USDT'):
        print("❌ Symbol must end with 'USDT'. Exiting.")
        return

    # 3) Choose amount (total USDT to split among 3 strategies)
    while True:
        amt = input("Total USDT amount (or 'all' for full balance): ").strip().lower()
        if amt == 'all':
            usdt_amount = None
            break
        try:
            usdt_amount = float(amt)
            if usdt_amount < 3 * 6:
                print("❌ Minimum total is $18 (i.e. $6 per strategy).")
                continue
            break
        except:
            print("❌ Invalid number. Try again.")

    # 4) Initialize client and show balances
    try:
        client = ExchangeClient(exch)
    except Exception as e:
        print(f"❌ Failed to connect to exchange: {e}")
        return

    usdt_balance = client.get_balance('USDT')
    if usdt_balance <= 0:
        print("❌ No USDT balance available. Fund your account and try again.")
        return

    allocated_per_strategy = usdt_balance / 3.0 if usdt_amount is None else usdt_amount / 3.0
    print(f"\n💰 USDT Balance: {usdt_balance:.2f}")
    print(f"   → Each strategy will use ~{allocated_per_strategy:.2f} USDT")

    # 5) Main menu loop
    while True:
        print("\n1) Check Signals Immediately")
        print("2) Start Live Auto-Trading  (press Ctrl+C to stop)")
        print("3) Show Balances")
        print("4) Exit")
        choice = input("Select (1-4): ").strip()

        if choice == '1':
            df = client.get_ohlcv(symbol, limit=201, interval='15m')
            if df.empty:
                print("❌ Failed to fetch OHLCV data.")
            else:
                analyze_strategies(df, client, symbol, allocated_per_strategy)

        elif choice == '2':
            print("\n🚀 Starting live auto-trading… (Ctrl+C to stop)\n")
            try:
                while True:
                    df = client.get_ohlcv(symbol, limit=201, interval='15m')
                    if not df.empty:
                        analyze_strategies(df, client, symbol, allocated_per_strategy)
                    time.sleep(900)  # 15 minutes delay
            except KeyboardInterrupt:
                print("\n🛑 Auto-trading stopped by user.")

        elif choice == '3':
            usdt_bal = client.get_balance('USDT')
            base_asset = symbol.replace('USDT', '')
            base_bal = client.get_balance(base_asset)
            print(f"\n💰 Balances:")
            print(f"   USDT: {usdt_bal:.4f}")
            print(f"   {base_asset}: {base_bal:.6f}")

        elif choice == '4':
            print("👋 Goodbye.")
            break

        else:
            print("❌ Please select 1, 2, 3, or 4.")

if __name__ == "__main__":
    main()