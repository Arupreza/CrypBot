import requests
import time
import json
from datetime import datetime
import pandas as pd

def fetch_binance_15min_candles(symbol="BTCUSDT", limit=15):
    """
    Fetch 15-minute OHLCV candlestick data from Binance API
    
    Args:
        symbol (str): Trading pair symbol (default: BTCUSDT)
        limit (int): Number of candles to fetch (default: 15)
    
    Returns:
        pd.DataFrame: DataFrame with OHLCV candlestick data or None if error
    """
    base_url = "https://api.binance.com/api/v3/klines"
    
    params = {
        'symbol': symbol,
        'interval': '15m',
        'limit': limit
    }
    
    try:
        response = requests.get(base_url, params=params, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        
        # Format the data as OHLCV DataFrame
        ohlcv_data = []
        for candle in data:
            ohlcv_candle = {
                'timestamp': datetime.fromtimestamp(candle[0] / 1000),
                'open': float(candle[1]),
                'high': float(candle[2]),
                'low': float(candle[3]),
                'close': float(candle[4]),
                'volume': float(candle[5])
            }
            ohlcv_data.append(ohlcv_candle)
        
        # Create DataFrame
        df = pd.DataFrame(ohlcv_data)
        df.set_index('timestamp', inplace=True)
        
        return df
        
    except requests.exceptions.RequestException as e:
        print(f"Error fetching data: {e}")
        return None
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON: {e}")
        return None

def live_candle_monitor(symbol="BTCUSDT", limit=15, interval_seconds=10, return_data=False):
    """
    Continuously fetch and display live 15-minute OHLCV candle data every 10 seconds
    
    Args:
        symbol (str): Trading pair symbol
        limit (int): Number of candles to fetch
        interval_seconds (int): Fetch interval in seconds
        return_data (bool): If True, returns data instead of printing
    
    Returns:
        dict: Data dictionary if return_data=True, None otherwise
    """
    # Store initial messages in variables
    start_message = f"Starting live OHLCV monitoring for {symbol} - 15min candles"
    fetch_message = f"Fetching {limit} candles every {interval_seconds} seconds"
    stop_instruction = "Press Ctrl+C to stop\n"
    
    if not return_data:
        # Print from variables
        print(start_message)
        print(fetch_message)
        print(stop_instruction)
    
    try:
        while True:
            # Store current time in variable
            current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            fetch_header = f"\n--- Fetching data at {current_time} ---"
            
            if not return_data:
                print(fetch_header)
            
            # Store fetched data in variable first
            candles_df = fetch_binance_15min_candles(symbol, limit)
            
            if candles_df is not None and not candles_df.empty:
                # Store all data processing results in variables FIRST
                latest_candle = candles_df.iloc[-1]
                latest_timestamp = candles_df.index[-1]
                latest_open = latest_candle['open']
                latest_high = latest_candle['high']
                latest_low = latest_candle['low']
                latest_close = latest_candle['close']
                latest_volume = latest_candle['volume']
                df_shape = candles_df.shape
                df_columns = list(candles_df.columns)
                
                # Store formatted timestamp in variable
                formatted_timestamp = latest_timestamp.strftime('%Y-%m-%d %H:%M:%S')
                
                # Store all display messages in variables FIRST
                candle_header = f"Latest 15min OHLCV candle for {symbol}:"
                timestamp_msg = f"Timestamp: {formatted_timestamp}"
                open_msg = f"Open (O): ${latest_open:.2f}"
                high_msg = f"High (H): ${latest_high:.2f}"
                low_msg = f"Low (L): ${latest_low:.2f}"
                close_msg = f"Close (C): ${latest_close:.2f}"
                volume_msg = f"Volume (V): {latest_volume:.2f}"
                shape_msg = f"\nDataFrame shape: {df_shape}"
                columns_msg = f"Columns: {df_columns}"
                
                # Store all data in a dictionary
                output_data = {
                    'dataframe': candles_df,
                    'latest_candle': latest_candle,
                    'latest_timestamp': latest_timestamp,
                    'formatted_timestamp': formatted_timestamp,
                    'latest_open': latest_open,
                    'latest_high': latest_high,
                    'latest_low': latest_low,
                    'latest_close': latest_close,
                    'latest_volume': latest_volume,
                    'df_shape': df_shape,
                    'df_columns': df_columns,
                    'messages': {
                        'candle_header': candle_header,
                        'timestamp_msg': timestamp_msg,
                        'open_msg': open_msg,
                        'high_msg': high_msg,
                        'low_msg': low_msg,
                        'close_msg': close_msg,
                        'volume_msg': volume_msg,
                        'shape_msg': shape_msg,
                        'columns_msg': columns_msg,
                        'fetch_header': fetch_header
                    }
                }
                
                if return_data:
                    return output_data
                else:
                    # Print from all the stored variables
                    print(candle_header)
                    print(timestamp_msg)
                    print(open_msg)
                    print(high_msg)
                    print(low_msg)
                    print(close_msg)
                    print(volume_msg)
                    print(shape_msg)
                    print(columns_msg)
                
                # Optionally display the entire DataFrame
                # dataframe_display = f"\nFull DataFrame:\n{candles_df}"
                # print(dataframe_display)
            else:
                # Store error message in variable first
                error_message = "Failed to fetch candle data"
                error_data = {
                    'error': True,
                    'error_message': error_message,
                    'timestamp': current_time
                }
                
                if return_data:
                    return error_data
                else:
                    print(error_message)
            
            if return_data:
                break  # Exit after one fetch when returning data
                
            time.sleep(interval_seconds)
            
    except KeyboardInterrupt:
        # Store stop message in variable first
        stop_message = "\nStopping live monitor..."
        if not return_data:
            print(stop_message)
        return None

def get_live_candle_data(symbol="BTCUSDT", limit=15):
    """
    Get a single fetch of live candle data that can be stored in a variable
    
    Args:
        symbol (str): Trading pair symbol
        limit (int): Number of candles to fetch
    
    Returns:
        dict: Dictionary containing all candle data and formatted messages
    """
    return live_candle_monitor(symbol, limit, 10, return_data=True)

def get_single_fetch(symbol="BTCUSDT", limit=15):
    """
    Get a single fetch of 15-minute OHLCV candle data
    
    Args:
        symbol (str): Trading pair symbol
        limit (int): Number of candles to fetch
    
    Returns:
        pd.DataFrame: OHLCV candlestick data as DataFrame
    """
    return fetch_binance_15min_candles(symbol, limit)

"""# Example usage
if __name__ == "__main__":
    # Option 1: Single OHLCV fetch as DataFrame
    print("Single OHLCV fetch example:")
    
    # Store data in variable first
    df = get_single_fetch("BTCUSDT", 15)
    
    if df is not None and not df.empty:
        # Store values in variables
        df_shape = df.shape
        df_columns = list(df.columns)
        latest_candle = df.iloc[-1]
        first_few_rows = df.head()
        
        # Print from variables
        print(f"Fetched DataFrame shape: {df_shape}")
        print("DataFrame columns:", df_columns)
        print("\nLatest OHLCV candle:")
        print(latest_candle)
        print("\nFirst few rows:")
        print(first_few_rows)
    
    separator = "\n" + "="*50 + "\n"
    print(separator)
    
    # Option 2: Get live candle data in variable then print
    print("Live candle data stored in variable example:")
    
    # Store the output in a variable
    out = get_live_candle_data("BTCUSDT", 15)
    
    if out and not out.get('error', False):
        # Print from the stored variable
        print(out['messages']['candle_header'])
        print(out['messages']['timestamp_msg'])
        print(out['messages']['open_msg'])
        print(out['messages']['high_msg'])
        print(out['messages']['low_msg'])
        print(out['messages']['close_msg'])
        print(out['messages']['volume_msg'])
        print(out['messages']['shape_msg'])
        print(out['messages']['columns_msg'])
        
        # You can also access the raw data
        print(f"\nRaw close price: {out['latest_close']}")
        print(f"Raw DataFrame shape: {out['df_shape']}")
    
    print(separator)"""
    
    # Option 3: Continuous monitoring (traditional way)
    # Uncomment the line below to start live monitoring
    # live_candle_monitor("BTCUSDT", 15, 10)