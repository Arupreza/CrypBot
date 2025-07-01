import pandas as pd
import ccxt
import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime, timedelta
import warnings
from scipy import stats
warnings.filterwarnings('ignore')



def calculate_atr(df: pd.DataFrame, length: int = 1) -> pd.Series:
    """
    Calculate Average True Range (ATR). Returns a pd.Series.
    """
    high_low = df['high'] - df['low']
    high_close_prev = (df['high'] - df['close'].shift()).abs()
    low_close_prev = (df['low'] - df['close'].shift()).abs()

    true_range = pd.concat([high_low, high_close_prev, low_close_prev], axis=1).max(axis=1)
    atr = true_range.rolling(window=length).mean()
    return atr

def chandelier_exit(
    df: pd.DataFrame,
    atr_period: int = 1,
    atr_multiplier: float = 2.0,
    use_close: bool = True
) -> pd.DataFrame:
    """
    Calculate Chandelier Exit with accurate signals and smoothing
    """
    df_result = df.copy()

    # Compute ATR
    atr_raw = calculate_atr(df, length=atr_period)
    atr = atr_raw * atr_multiplier

    # Compute rolling highest/lowest
    if use_close:
        highest = df['close'].rolling(window=atr_period).max()
        lowest = df['close'].rolling(window=atr_period).min()
    else:
        highest = df['high'].rolling(window=atr_period).max()
        lowest = df['low'].rolling(window=atr_period).min()

    n = len(df)
    long_stop_array = np.full(n, np.nan)
    short_stop_array = np.full(n, np.nan)
    direction_array = np.full(n, 1)

    for i in range(n):
        if pd.isna(atr.iloc[i]) or pd.isna(highest.iloc[i]) or pd.isna(lowest.iloc[i]):
            continue

        curr_long = highest.iloc[i] - atr.iloc[i]
        curr_short = lowest.iloc[i] + atr.iloc[i]

        if i == 0:
            long_stop_array[i] = curr_long
            short_stop_array[i] = curr_short
            direction_array[i] = 1
        else:
            prev_long = long_stop_array[i - 1] if not pd.isna(long_stop_array[i - 1]) else curr_long
            if df['close'].iloc[i - 1] > prev_long:
                long_stop_array[i] = max(curr_long, prev_long)
            else:
                long_stop_array[i] = curr_long

            prev_short = short_stop_array[i - 1] if not pd.isna(short_stop_array[i - 1]) else curr_short
            if df['close'].iloc[i - 1] < prev_short:
                short_stop_array[i] = min(curr_short, prev_short)
            else:
                short_stop_array[i] = curr_short

            prev_short_val = short_stop_array[i - 1] if not pd.isna(short_stop_array[i - 1]) else curr_short
            prev_long_val = long_stop_array[i - 1] if not pd.isna(long_stop_array[i - 1]) else curr_long

            if df['close'].iloc[i] > prev_short_val:
                direction_array[i] = 1
            elif df['close'].iloc[i] < prev_long_val:
                direction_array[i] = -1
            else:
                direction_array[i] = direction_array[i - 1]

    df_result['atr'] = atr
    df_result['long_stop'] = long_stop_array
    df_result['short_stop'] = short_stop_array
    df_result['direction'] = direction_array
    df_result['chandelier_exit'] = np.where(direction_array == 1, long_stop_array, short_stop_array)
    
    # Apply smoothing to reduce noise
    df_result['direction_smooth'] = df_result['direction'].rolling(window=3, center=True).apply(
        lambda x: 1 if x.mean() > 0 else -1, raw=False
    ).fillna(df_result['direction'])
    
    df_result['buy_signal'] = (df_result['direction_smooth'] == 1).astype(int)
    df_result['sell_signal'] = (df_result['direction_smooth'] == -1).astype(int)

    return df_result

def fetch_crypto_data(symbol, timeframe='15m', limit=200):
    """
    Fetch crypto/USDT historical data from Binance
    """
    try:
        symbol = symbol.upper()
        if not symbol.endswith('/USDT'):
            if symbol.endswith('USDT'):
                symbol = symbol[:-4] + '/USDT'
            else:
                symbol = symbol + '/USDT'
        
        exchange = ccxt.binance()
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        
        return df, symbol
    except Exception as e:
        print(f"Error fetching {symbol} data: {e}")
        return None, symbol

def only_chandelier(symbol, timeframe='15m', limit=200, atr_period=1, atr_multiplier=2.0, use_close=True):
    """
    Main function to fetch crypto data and calculate Chandelier Exit
    """
    df, trading_pair = fetch_crypto_data(symbol, timeframe, limit)
    
    if df is None:
        print(f"Failed to fetch {trading_pair} data")
        return None
    
    df_result = chandelier_exit(
        df,
        atr_period=atr_period,
        atr_multiplier=atr_multiplier,
        use_close=use_close
    )
    
    return df_result

def calculate_chandelier_data(df, atr_period=1, atr_multiplier=2.0):
    """
    Calculate Chandelier Exit on the dataframe
    """
    df_result = chandelier_exit(df, atr_period=atr_period, atr_multiplier=atr_multiplier)
    return df_result

def display_live_trade_with_graph(csv_file_path, exchange_name='binance', show_graph=True):
    """
    Display current trade situation with visual graph including Chandelier Exit signals
    
    Args:
        csv_file_path (str): Path to the CSV file
        exchange_name (str): Exchange name for live price fetching
        show_graph (bool): Whether to display the graph
    """
    try:
        # Initialize exchange
        exchange = getattr(ccxt, exchange_name)({
            'sandbox': False,
            'rateLimit': 1200,
            'enableRateLimit': True,
        })
        
        # Read CSV and get last ENTRY trade
        df = pd.read_csv(csv_file_path)
        entry_trades = df[df['Action'] == 'ENTRY']
        
        if entry_trades.empty:
            print("❌ No ENTRY trades found in the data")
            return
        
        # Get the last entry trade
        trade = entry_trades.iloc[-1]
        
        # Extract trade data
        symbol = trade['Symbol']
        entry_price = float(trade['Entry_Price'])
        amount = float(trade['Amount'])
        invested_usd = float(trade['Invested_USD'])
        stop_loss = float(trade['Stop_Loss']) if pd.notna(trade['Stop_Loss']) else None
        take_profit = float(trade['Take_Profit']) if pd.notna(trade['Take_Profit']) else None
        entry_date = trade['Date']
        entry_time = trade['Time']
        
        # Extract coin symbol for analysis
        coin_symbol = trade['Coin'] if 'Coin' in trade else symbol.split('/')[0]
        
        # Get current price and historical data
        try:
            ticker = exchange.fetch_ticker(symbol)
            current_price = ticker['last']
            price_change_24h = ticker['percentage']
            
            # Fetch historical data for graph (extended period for better analysis)
            ohlcv = exchange.fetch_ohlcv(symbol, '1h', limit=100)
            historical_data = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            historical_data['datetime'] = pd.to_datetime(historical_data['timestamp'], unit='ms')
            
            # Calculate Chandelier Exit for the trading pair
            chandelier_data = calculate_chandelier_data(
                historical_data, 
                atr_period=1,
                atr_multiplier=2.0
            )
            
            # Fetch BTC data for comparison and Chandelier Exit analysis
            btc_ohlcv = exchange.fetch_ohlcv('BTC/USDT', '15m', limit=200)
            btc_data = pd.DataFrame(btc_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            btc_data['datetime'] = pd.to_datetime(btc_data['timestamp'], unit='ms')
            btc_ticker = exchange.fetch_ticker('BTC/USDT')
            btc_price_change_24h = btc_ticker['percentage']
            
            # Calculate Chandelier Exit for BTC
            btc_chandelier_data = calculate_chandelier_data(
                btc_data,
                atr_period=1,
                atr_multiplier=2.0
            )
            
        except Exception as e:
            print(f"⚠️ Could not fetch live data: {e}")
            current_price = None
            price_change_24h = None
            historical_data = None
            btc_data = None
            btc_price_change_24h = None
            btc_chandelier_data = None
        
        # Calculate current situation
        if current_price:
            current_value = amount * current_price
            pnl_usd = current_value - invested_usd
            pnl_percent = (pnl_usd / invested_usd) * 100
            price_change_from_entry = ((current_price - entry_price) / entry_price) * 100
            
            # Check BTC Chandelier Exit signals
            btc_chandelier_signal = ""
            
            if btc_chandelier_data is not None and len(btc_chandelier_data) > 0:
                latest_btc_data = btc_chandelier_data.iloc[-1]
                
                # BTC Chandelier Exit signals (using smoothed direction)
                if latest_btc_data['direction_smooth'] == 1:
                    btc_chandelier_signal = "🟢 BTC CHANDELIER BUY SIGNAL"
                elif latest_btc_data['direction_smooth'] == -1:
                    btc_chandelier_signal = "🔴 BTC CHANDELIER SELL SIGNAL"
            
            # Determine overall trade status
            if stop_loss and current_price <= stop_loss:
                status = "🔴 STOP LOSS HIT"
                status_color = "red"
            elif take_profit and current_price >= take_profit:
                status = "🟢 TAKE PROFIT HIT"
                status_color = "green"
            elif pnl_percent > 0:
                status = "🟢 IN PROFIT"
                status_color = "green"
            else:
                status = "🔴 IN LOSS"
                status_color = "red"
        else:
            status = "⚪ PRICE DATA UNAVAILABLE"
            status_color = "gray"
            btc_chandelier_signal = ""
        
        # Display trade situation (text)
        print("\n" + "="*70)
        print(f"📊 LIVE TRADE STATUS - {trade['Coin'].upper()}")
        print("="*70)
        
        print(f"\n📍 TRADE INFO:")
        print(f"   Symbol: {symbol}")
        print(f"   Entry Date: {entry_date} {entry_time}")
        print(f"   Entry Price: ${entry_price:.8f}")
        print(f"   Amount: {amount:.2f} {trade['Coin']}")
        print(f"   Invested: ${invested_usd:.2f}")
        
        if current_price:
            print(f"\n💰 CURRENT SITUATION:")
            print(f"   Current Price: ${current_price:.8f}")
            print(f"   Current Value: ${current_value:.2f}")
            print(f"   P&L: ${pnl_usd:+.2f} ({pnl_percent:+.2f}%)")
            print(f"   Price Change from Entry: {price_change_from_entry:+.2f}%")
            if price_change_24h:
                print(f"   24h Market Change: {price_change_24h:+.2f}%")
            if btc_price_change_24h:
                print(f"   BTC 24h Change: {btc_price_change_24h:+.2f}%")
        
        print(f"\n🎯 TARGETS:")
        if stop_loss:
            sl_distance = ((current_price - stop_loss) / stop_loss * 100) if current_price else 0
            print(f"   Stop Loss: ${stop_loss:.8f} ({sl_distance:+.2f}% away)")
        else:
            print(f"   Stop Loss: Not Set")
            
        if take_profit:
            tp_distance = ((take_profit - current_price) / current_price * 100) if current_price else 0
            print(f"   Take Profit: ${take_profit:.8f} ({tp_distance:+.2f}% away)")
        else:
            print(f"   Take Profit: Not Set")
        
        print(f"\n📈 TECHNICAL SIGNALS:")
        if btc_chandelier_signal:
            print(f"   {btc_chandelier_signal}")
        
        print(f"\n🚨 STATUS: {status}")
        
        # Create the graph
        if show_graph and historical_data is not None and current_price:
            create_enhanced_trade_graph(historical_data, btc_chandelier_data, entry_price, current_price, 
                                    stop_loss, take_profit, symbol, status_color, entry_date, 
                                    entry_time)
        
        print("="*70)
        
    except Exception as e:
        print(f"❌ Error: {str(e)}")

def create_enhanced_trade_graph(historical_data, btc_chandelier_data, entry_price, current_price, stop_loss, 
                            take_profit, symbol, status_color, entry_date, entry_time):
    """
    Create enhanced visual graph with BTC price line and Chandelier Exit direction
    """
    try:
        # Create figure with subplots
        fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(16, 12), 
                                        gridspec_kw={'height_ratios': [2, 1, 1]})
        fig.suptitle(f'{symbol} - Trade Analysis with BTC Chandelier Exit Direction', 
                    fontsize=16, fontweight='bold')
        
        # Main price chart (top subplot)
        ax1.plot(historical_data['datetime'], historical_data['close'], 
                color='#2E86AB', linewidth=2.5, label=f'{symbol} Price')
        
        # Add horizontal lines for key levels
        ax1.axhline(y=entry_price, color='blue', linestyle='--', linewidth=2, 
                label=f'Entry: ${entry_price:.6f}', alpha=0.8)
        
        if stop_loss:
            ax1.axhline(y=stop_loss, color='red', linestyle='--', linewidth=2, 
                    label=f'Stop Loss: ${stop_loss:.6f}', alpha=0.8)
        
        if take_profit:
            ax1.axhline(y=take_profit, color='green', linestyle='--', linewidth=2, 
                    label=f'Take Profit: ${take_profit:.6f}', alpha=0.8)
        
        # Formatting price chart
        ax1.set_ylabel(f'{symbol} Price (USDT)', fontsize=12, fontweight='bold')
        ax1.set_title(f'{symbol} Price Movement', fontsize=14)
        ax1.legend(loc='upper left', bbox_to_anchor=(0.01, 0.99), fontsize=9, framealpha=0.9)
        ax1.grid(True, alpha=0.3)
        ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'${x:.6f}'))
        
        # BTC price chart (middle subplot)
        if btc_chandelier_data is not None:
            ax2.plot(btc_chandelier_data['datetime'], btc_chandelier_data['close'], 
                    color='#F7931A', linewidth=2.5, label='BTC Price')
            
            ax2.set_ylabel('BTC Price (USDT)', fontsize=12, fontweight='bold')
            ax2.set_title('Bitcoin Price Movement', fontsize=12)
            ax2.legend(loc='upper right', bbox_to_anchor=(0.99, 0.99), fontsize=9, framealpha=0.9)
            ax2.grid(True, alpha=0.3)
            ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'${x:,.0f}'))
        
        # BTC Chandelier direction indicator (bottom subplot)
        if btc_chandelier_data is not None:
            direction_colors = ['red' if d == -1 else 'green' for d in btc_chandelier_data['direction_smooth']]
            ax3.bar(btc_chandelier_data['datetime'], btc_chandelier_data['direction_smooth'], 
                    color=direction_colors, alpha=0.7, width=pd.Timedelta(minutes=15))
            ax3.set_ylabel('BTC Chandelier Direction', fontsize=12, fontweight='bold')
            ax3.set_xlabel('Time', fontsize=12)
            ax3.set_title('BTC Chandelier Exit Direction - 15min Candles (Green=Buy, Red=Sell)', fontsize=12)
            ax3.set_ylim(-1.5, 1.5)
            ax3.grid(True, alpha=0.3)
            ax3.axhline(y=0, color='black', linewidth=0.5)
        
        # Add comprehensive statistics text box
        stats_text = create_comprehensive_stats(entry_price, current_price, stop_loss, take_profit, 
                                            btc_chandelier_data)
        ax1.text(0.02, 0.02, stats_text, transform=ax1.transAxes, fontsize=9,
                verticalalignment='bottom', bbox=dict(boxstyle='round', facecolor='lightblue', alpha=0.9))
        
        plt.tight_layout()
        plt.show()
        
    except Exception as e:
        print(f"⚠️ Error creating enhanced graph: {e}")

def create_comprehensive_stats(entry_price, current_price, stop_loss, take_profit, 
                            btc_chandelier_data):
    """
    Create comprehensive statistics including BTC Chandelier analysis
    """
    price_change = ((current_price - entry_price) / entry_price) * 100
    
    stats = f"📊 Trade Stats:\n"
    stats += f"Price Change: {price_change:+.2f}%\n"
    
    if stop_loss:
        sl_distance = ((current_price - stop_loss) / stop_loss) * 100
        stats += f"SL Distance: {sl_distance:+.2f}%\n"
    
    if take_profit:
        tp_distance = ((take_profit - current_price) / current_price) * 100
        stats += f"TP Distance: {tp_distance:+.2f}%\n"
    
    if stop_loss and take_profit:
        risk = entry_price - stop_loss
        reward = take_profit - entry_price
        rr_ratio = reward / risk if risk > 0 else 0
        stats += f"R:R Ratio: 1:{rr_ratio:.2f}\n"
    
    # Add BTC Chandelier analysis
    if btc_chandelier_data is not None and len(btc_chandelier_data) > 0:
        latest = btc_chandelier_data.iloc[-1]
        direction_str = "BULLISH" if latest['direction_smooth'] == 1 else "BEARISH"
        stats += f"\n₿ BTC Chandelier:\n"
        stats += f"Direction: {direction_str}\n"
        
        # Add BTC price info
        btc_change = ((btc_chandelier_data['close'].iloc[-1] - btc_chandelier_data['close'].iloc[0]) / btc_chandelier_data['close'].iloc[0]) * 100
        stats += f"BTC Change: {btc_change:+.2f}%\n"
    
    return stats

# Usage example:
# display_live_trade_with_graph('your_trades.csv')