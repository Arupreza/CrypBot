import requests
import pandas as pd
import json
from datetime import datetime

def fetch_binance_gainers(limit=20):
    """
    Fetch top gainers from Binance API
    
    Args:
        limit (int): Number of top gainers to return (default: 10)
    
    Returns:
        list: List of top gaining cryptocurrencies
    """
    try:
        # Binance API endpoint for 24hr ticker price change statistics
        url = "https://api.binance.com/api/v3/ticker/24hr"
        
        # Make the API request
        response = requests.get(url)
        response.raise_for_status()  # Raise an exception for bad status codes
        
        # Parse JSON response
        data = response.json()
        
        # Filter only USDT pairs and convert percentage strings to floats
        usdt_pairs = []
        for coin in data:
            if coin['symbol'].endswith('USDT'):
                try:
                    price_change_percent = float(coin['priceChangePercent'])
                    # Only include coins with positive price change
                    if price_change_percent > 0:
                        usdt_pairs.append({
                            'symbol': coin['symbol'],
                            'price': float(coin['lastPrice']),
                            'price_change_percent': price_change_percent,
                            'price_change': float(coin['priceChange']),
                            'volume': float(coin['volume']),
                            'quote_volume': float(coin['quoteVolume']),
                            'high_price': float(coin['highPrice']),
                            'low_price': float(coin['lowPrice'])
                        })
                except (ValueError, KeyError):
                    # Skip coins with invalid data
                    continue
        
        # Sort by price change percentage (descending)
        top_gainers = sorted(usdt_pairs, key=lambda x: x['price_change_percent'], reverse=True)
        
        # Return top N gainers
        return top_gainers[:limit]
        
    except requests.exceptions.RequestException as e:
        print(f"Error fetching data from Binance API: {e}")
        return []
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON response: {e}")
        return []

def display_gainers(gainers):
    """
    Return a DataFrame of the top gainers in a formatted table
    
    Args:
        gainers (list): List of top gaining cryptocurrencies
    
    Returns:
        pd.DataFrame: Formatted DataFrame with gainers data
    """
    if not gainers:
        print("No gainers data available.")
        return None
    
    # Prepare the data for DataFrame
    data = []
    for i, coin in enumerate(gainers, 1):
        symbol = coin['symbol'].replace('USDT', '')
        price = f"${coin['price']:.4f}" if coin['price'] < 1 else f"${coin['price']:.2f}"
        change_percent = f"+{coin['price_change_percent']:.2f}%"
        volume = f"{coin['volume']:,.0f}"
        
        data.append([i, symbol, price, change_percent, volume])
    
    # Create DataFrame
    df = pd.DataFrame(data, columns=["Rank", "Symbol", "Price (USDT)", "Change %", "Volume"])
    
    # Add a timestamp for the display
    df['Timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    return df

def get_specific_coin_data(symbol):
    """
    Get specific coin data from Binance
    
    Args:
        symbol (str): Trading pair symbol (e.g., 'BTCUSDT')
    
    Returns:
        dict: Coin data or None if not found
    """
    try:
        url = f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol.upper()}"
        response = requests.get(url)
        response.raise_for_status()
        
        data = response.json()
        return {
            'symbol': data['symbol'],
            'price': float(data['lastPrice']),
            'price_change_percent': float(data['priceChangePercent']),
            'price_change': float(data['priceChange']),
            'volume': float(data['volume']),
            'high_price': float(data['highPrice']),
            'low_price': float(data['lowPrice'])
        }
    except requests.exceptions.RequestException as e:
        print(f"Error fetching data for {symbol}: {e}")
        return None
    
    
    
        #########  Use of Function  #########
    """
    top_gainers = fetch_binance_gainers(limit=25)
    top_gainers = display_gainers(top_gainers)
    
    """
