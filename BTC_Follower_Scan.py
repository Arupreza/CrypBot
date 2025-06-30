import ccxt
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import time

def analyze_coins_btc_direction(coin_symbols_list, directional_accuracy_threshold=0.70):
    """
    Analyze specific coins to see if they follow BTC direction
    
    Args:
        coin_symbols_list: List of coin symbols in ADAUSDT format (e.g., ['ADAUSDT', 'ETHUSDT', 'BNBUSDT'])
        directional_accuracy_threshold: Minimum % of time coin moves same direction as BTC
    
    Returns:
        pandas DataFrame with analysis results
    """
    
    # Initialize Binance exchange
    exchange = ccxt.binance({
        'rateLimit': 1200,
        'enableRateLimit': True,
    })
    
    # Convert symbols to CCXT format (ADAUSDT -> ADA/USDT)
    ccxt_symbols = []
    original_symbols = []
    for symbol in coin_symbols_list:
        if symbol.endswith('USDT'):
            base = symbol[:-4]  # Remove 'USDT'
            ccxt_symbol = f"{base}/USDT"
            ccxt_symbols.append(ccxt_symbol)
            original_symbols.append(symbol)
        else:
            ccxt_symbols.append(symbol)
            original_symbols.append(symbol.replace('/', ''))
    
    try:
        # Fetch BTC/USDT 5-minute data for last 4 hours (48 candles)
        btc_symbol = 'BTC/USDT'
        since = exchange.milliseconds() - 4 * 60 * 60 * 1000  # 4 hours ago
        
        btc_ohlcv = exchange.fetch_ohlcv(btc_symbol, '5m', since=since, limit=48)
        
        if len(btc_ohlcv) < 10:
            return pd.DataFrame()
        
        # Calculate BTC directional moves (up/down)
        btc_directions = []
        btc_changes = []
        
        for i in range(1, len(btc_ohlcv)):
            prev_close = btc_ohlcv[i-1][4]
            curr_close = btc_ohlcv[i][4]
            change_pct = (curr_close - prev_close) / prev_close * 100
            
            btc_changes.append(change_pct)
            
            # 1 for up, -1 for down, 0 for no significant change
            if change_pct > 0.1:  # More than 0.1% up
                btc_directions.append(1)
            elif change_pct < -0.1:  # More than 0.1% down
                btc_directions.append(-1)
            else:
                btc_directions.append(0)  # Sideways/no clear direction
        
        # Results list to store analysis for each coin
        results = []
        
        # Analyze each coin
        for i, (ccxt_symbol, original_symbol) in enumerate(zip(ccxt_symbols, original_symbols)):
            try:
                # Skip BTC itself
                if ccxt_symbol == btc_symbol:
                    continue
                
                # Fetch coin data
                coin_ohlcv = exchange.fetch_ohlcv(ccxt_symbol, '5m', since=since, limit=48)
                
                if len(coin_ohlcv) < 10:
                    results.append({
                        'symbol': original_symbol,
                        'directional_accuracy': 0.0,
                        'correlation': 0.0,
                        'valid_moves': 0,
                        'same_direction_moves': 0,
                        'opposite_direction_moves': 0,
                        'sideways_moves': 0,
                        'avg_move_magnitude': 0.0,
                        'follows_btc': False,
                        'consolidation_status': 'Unknown',
                        'is_consolidation': False,
                        'range_4h_pct': 0.0,
                        'volatility': 0.0,
                        'status': 'Insufficient data'
                    })
                    continue
                
                # Calculate coin directional moves
                coin_directions = []
                coin_changes = []
                
                for j in range(1, len(coin_ohlcv)):
                    prev_close = coin_ohlcv[j-1][4]
                    curr_close = coin_ohlcv[j][4]
                    change_pct = (curr_close - prev_close) / prev_close * 100
                    
                    coin_changes.append(change_pct)
                    if change_pct > 0.1:
                        coin_directions.append(1)
                    elif change_pct < -0.1:
                        coin_directions.append(-1)
                    else:
                        coin_directions.append(0)
                
                # Ensure both arrays have same length
                min_length = min(len(btc_directions), len(coin_directions))
                if min_length < 5:
                    results.append({
                        'symbol': original_symbol,
                        'directional_accuracy': 0.0,
                        'correlation': 0.0,
                        'valid_moves': 0,
                        'same_direction_moves': 0,
                        'opposite_direction_moves': 0,
                        'sideways_moves': 0,
                        'avg_move_magnitude': 0.0,
                        'follows_btc': False,
                        'status': 'Insufficient valid moves'
                    })
                    continue
                
                btc_subset = btc_directions[:min_length]
                coin_subset = coin_directions[:min_length]
                btc_changes_subset = btc_changes[:min_length]
                coin_changes_subset = coin_changes[:min_length]
                
                # Calculate directional statistics
                same_direction_count = 0
                opposite_direction_count = 0
                sideways_count = 0
                valid_moves = 0
                
                for k in range(min_length):
                    # Only count periods where BTC had a clear direction (not sideways)
                    if btc_subset[k] != 0:
                        valid_moves += 1
                        if btc_subset[k] == coin_subset[k]:
                            same_direction_count += 1
                        elif coin_subset[k] == 0:
                            sideways_count += 1
                        else:
                            opposite_direction_count += 1
                
                if valid_moves < 3:  # Need at least 3 valid moves to analyze
                    results.append({
                        'symbol': original_symbol,
                        'directional_accuracy': 0.0,
                        'correlation': 0.0,
                        'valid_moves': valid_moves,
                        'same_direction_moves': same_direction_count,
                        'opposite_direction_moves': opposite_direction_count,
                        'sideways_moves': sideways_count,
                        'avg_move_magnitude': 0.0,
                        'follows_btc': False,
                        'consolidation_status': 'Unknown',
                        'is_consolidation': False,
                        'range_4h_pct': 0.0,
                        'volatility': 0.0,
                        'status': 'Too few valid moves'
                    })
                    continue
                
                directional_accuracy = same_direction_count / valid_moves
                
                # Calculate correlation coefficient
                try:
                    correlation = np.corrcoef(btc_changes_subset, coin_changes_subset)[0, 1]
                    if np.isnan(correlation):
                        correlation = 0.0
                except:
                    correlation = 0.0
                
                # Calculate average move magnitude when following BTC
                following_moves = []
                for k in range(min_length):
                    if btc_subset[k] != 0 and btc_subset[k] == coin_subset[k]:
                        following_moves.append(abs(coin_changes_subset[k]))
                
                avg_following_magnitude = np.mean(following_moves) if following_moves else 0.0
                
                # Check if coin is in consolidation (4-hour analysis)
                coin_4h_high = max([candle[2] for candle in coin_ohlcv])  # highest high
                coin_4h_low = min([candle[3] for candle in coin_ohlcv])   # lowest low
                coin_4h_range_pct = ((coin_4h_high - coin_4h_low) / coin_4h_low) * 100
                
                # Calculate volatility (standard deviation of price changes)
                coin_volatility = np.std(coin_changes_subset) if len(coin_changes_subset) > 0 else 0
                
                # Consolidation criteria
                is_consolidation = (
                    coin_4h_range_pct < 5.0 and  # Less than 5% range in 4 hours
                    coin_volatility < 1.5         # Low volatility (std dev < 1.5%)
                )
                
                # Determine consolidation status
                if is_consolidation:
                    consolidation_status = "Consolidation"
                elif coin_4h_range_pct > 10.0:
                    consolidation_status = "High Volatility"
                else:
                    consolidation_status = "Normal Range"
                
                # Determine if coin follows BTC
                follows_btc = directional_accuracy >= directional_accuracy_threshold
                
                # Determine status
                if follows_btc:
                    status = 'Follows BTC'
                elif directional_accuracy >= 0.6:
                    status = 'Partially follows BTC'
                elif directional_accuracy <= 0.4:
                    status = 'Moves opposite to BTC'
                else:
                    status = 'Independent movement'
                
                results.append({
                    'symbol': original_symbol,
                    'directional_accuracy': round(directional_accuracy, 3),
                    'correlation': round(correlation, 3),
                    'valid_moves': valid_moves,
                    'same_direction_moves': same_direction_count,
                    'opposite_direction_moves': opposite_direction_count,
                    'sideways_moves': sideways_count,
                    'avg_move_magnitude': round(avg_following_magnitude, 3),
                    'follows_btc': follows_btc,
                    'consolidation_status': consolidation_status,
                    'is_consolidation': is_consolidation,
                    'range_4h_pct': round(coin_4h_range_pct, 2),
                    'volatility': round(coin_volatility, 3),
                    'status': status
                })
                
                # Rate limiting
                time.sleep(0.2)
                
            except Exception as e:
                results.append({
                    'symbol': original_symbol,
                    'directional_accuracy': 0.0,
                    'correlation': 0.0,
                    'valid_moves': 0,
                    'same_direction_moves': 0,
                    'opposite_direction_moves': 0,
                    'sideways_moves': 0,
                    'avg_move_magnitude': 0.0,
                    'follows_btc': False,
                    'consolidation_status': 'Unknown',
                    'is_consolidation': False,
                    'range_4h_pct': 0.0,
                    'volatility': 0.0,
                    'status': f'Error: {str(e)}'
                })
                continue
        
        # Create DataFrame
        df = pd.DataFrame(results)
        
        # Sort by directional accuracy (highest first)
        df = df.sort_values('directional_accuracy', ascending=False).reset_index(drop=True)
        
        return df
        
    except Exception as e:
        return pd.DataFrame()

def get_current_btc_trend():
    """Get current BTC trend for prediction"""
    exchange = ccxt.binance({'rateLimit': 1200, 'enableRateLimit': True})
    
    try:
        # Get last 30 minutes of BTC data
        since = exchange.milliseconds() - 30 * 60 * 1000
        btc_ohlcv = exchange.fetch_ohlcv('BTC/USDT', '5m', since=since, limit=6)
        
        if len(btc_ohlcv) < 2:
            return "Unknown", 0.0
        
        # Check recent trend
        recent_changes = []
        for i in range(1, len(btc_ohlcv)):
            prev_close = btc_ohlcv[i-1][4]
            curr_close = btc_ohlcv[i][4]
            change_pct = (curr_close - prev_close) / prev_close * 100
            recent_changes.append(change_pct)
        
        avg_change = sum(recent_changes) / len(recent_changes)
        
        if avg_change > 0.1:
            return "UP", avg_change
        elif avg_change < -0.1:
            return "DOWN", avg_change
        else:
            return "SIDEWAYS", avg_change
            
    except:
        return "Unknown", 0.0

def btc_trend_coins(coin_list, threshold=0.70):
    """
    Main function to analyze your coins
    
    Args:
        coin_list: List of coin symbols in ADAUSDT format
        threshold: Directional accuracy threshold (default 0.70 = 70%)
        
    Returns:
        DataFrame with analysis results
    """
    df = analyze_coins_btc_direction(coin_list, threshold)
    return df

# Example usage
#results_df = analyze_my_coins(my_coins)