import pandas as pd
import numpy as np
from typing import Tuple
import warnings
warnings.filterwarnings('ignore')

def market_structure_order_fib(df, zigzag_len=9, fib_factor=0.273):
    """
    Market Structure Break & Order Block detector
    
    Parameters:
    df: DataFrame with columns ['open', 'high', 'low', 'close']
    zigzag_len: Length for ZigZag calculation (default: 9)
    fib_factor: Fibonacci factor for breakout confirmation (default: 0.273)
    
    Returns:
    DataFrame with additional columns:
    - green_break_above: True when price breaks above green zones
    - red_break_below: True when price breaks below red zones
    - zone_type: Type of zone broken ('Bu-OB', 'Be-OB', 'Bu-BB', 'Be-BB')
    - zone_high: High of the broken zone
    - zone_low: Low of the broken zone
    - msb_signal: Market structure break signals (+1 bullish, -1 bearish)
    """
    
    if not all(col in df.columns for col in ['open', 'high', 'low', 'close']):
        raise ValueError("DataFrame must contain columns: 'open', 'high', 'low', 'close'")
    
    df = df.copy().reset_index(drop=True)
    
    def detect_zigzag_pivots(data):
        """Detect ZigZag pivot points"""
        # Calculate rolling highs and lows
        rolling_high = data['high'].rolling(window=zigzag_len*2+1, center=True).max()
        rolling_low = data['low'].rolling(window=zigzag_len*2+1, center=True).min()
        
        # Detect pivot highs and lows
        data['pivot_high'] = (data['high'] == rolling_high) & (data['high'].shift(zigzag_len) < data['high']) & (data['high'].shift(-zigzag_len) < data['high'])
        data['pivot_low'] = (data['low'] == rolling_low) & (data['low'].shift(zigzag_len) > data['low']) & (data['low'].shift(-zigzag_len) > data['low'])
        
        return data
    
    def find_order_block(data, start_idx, end_idx, block_type):
        """Find order block between two indices"""
        if pd.isna(start_idx) or pd.isna(end_idx) or start_idx >= end_idx:
            return None
            
        start_idx, end_idx = int(start_idx), int(end_idx)
        start_idx = max(0, start_idx)
        end_idx = min(len(data) - 1, end_idx)
        
        if start_idx >= end_idx:
            return None
        
        segment = data.iloc[start_idx:end_idx+1].copy()
        
        if block_type in ['bu_ob', 'bu_bb']:  # Bullish blocks - look for red candles
            red_candles = segment[segment['open'] > segment['close']]
        else:  # Bearish blocks - look for green candles
            red_candles = segment[segment['open'] < segment['close']]
        
        if red_candles.empty:
            return None
        
        # Get the last qualifying candle
        ob_candle = red_candles.iloc[-1]
        ob_idx = ob_candle.name
        
        return {
            'start_idx': ob_idx,
            'end_idx': ob_idx,
            'high': ob_candle['high'],
            'low': ob_candle['low'],
            'type': block_type
        }
    
    # Detect pivots
    df = detect_zigzag_pivots(df)
    
    # Get pivot points
    pivot_highs = df[df['pivot_high']].copy()
    pivot_lows = df[df['pivot_low']].copy()
    
    # Initialize result columns
    df['green_break_above'] = False
    df['red_break_below'] = False
    df['zone_type'] = ''
    df['zone_high'] = np.nan
    df['zone_low'] = np.nan
    df['msb_signal'] = 0
    df['market_structure'] = 0
    
    if len(pivot_highs) < 2 or len(pivot_lows) < 2:
        return df
    
    # Process each bar
    current_market = 1
    active_zones = []
    
    for i in range(len(df)):
        # Update trend based on pivots
        recent_highs = pivot_highs[pivot_highs.index <= i].tail(2)
        recent_lows = pivot_lows[pivot_lows.index <= i].tail(2)
        
        if len(recent_highs) >= 2 and len(recent_lows) >= 2:
            h0_idx, h1_idx = recent_highs.index[-1], recent_highs.index[-2]
            l0_idx, l1_idx = recent_lows.index[-1], recent_lows.index[-2]
            
            h0, h1 = recent_highs.iloc[-1]['high'], recent_highs.iloc[-2]['high']
            l0, l1 = recent_lows.iloc[-1]['low'], recent_lows.iloc[-2]['low']
            
            # Market structure break logic
            if current_market == 1:  # Bullish market
                # Check for bearish MSB: price breaks below previous low with fib confirmation
                if (l0 < l1 and df.loc[i, 'close'] < l0 and 
                    df.loc[i, 'low'] < l0 - abs(h0 - l1) * fib_factor):
                    current_market = -1
                    df.loc[i, 'msb_signal'] = -1
                    
                    # Create order blocks
                    bu_ob = find_order_block(df, h1_idx, l0_idx, 'bu_ob')
                    bu_bb = find_order_block(df, l1_idx - zigzag_len, h1_idx, 'bu_bb')
                    
                    if bu_ob:
                        active_zones.append({**bu_ob, 'created_at': i, 'active': True})
                    if bu_bb:
                        active_zones.append({**bu_bb, 'created_at': i, 'active': True})
            
            elif current_market == -1:  # Bearish market
                # Check for bullish MSB: price breaks above previous high with fib confirmation
                if (h0 > h1 and df.loc[i, 'close'] > h0 and 
                    df.loc[i, 'high'] > h0 + abs(h1 - l0) * fib_factor):
                    current_market = 1
                    df.loc[i, 'msb_signal'] = 1
                    
                    # Create order blocks
                    be_ob = find_order_block(df, l1_idx, h0_idx, 'be_ob')
                    be_bb = find_order_block(df, h1_idx - zigzag_len, l1_idx, 'be_bb')
                    
                    if be_ob:
                        active_zones.append({**be_ob, 'created_at': i, 'active': True})
                    if be_bb:
                        active_zones.append({**be_bb, 'created_at': i, 'active': True})
        
        # Check active zones
        current_price = df.loc[i, 'close']
        zones_to_remove = []
        
        for j, zone in enumerate(active_zones):
            if not zone['active']:
                continue
            
            zone_high, zone_low = zone['high'], zone['low']
            zone_type = zone['type']
            
            # Check for zone breaks
            if zone_type in ['bu_ob', 'bu_bb']:  # Green/Bullish zones
                if current_price > zone_high:  # Break ABOVE green zone
                    df.loc[i, 'green_break_above'] = True
                    df.loc[i, 'zone_type'] = zone_type.upper().replace('_', '-')  # 'BU-OB' or 'BU-BB'
                    df.loc[i, 'zone_high'] = zone_high
                    df.loc[i, 'zone_low'] = zone_low
                    zone['active'] = False
                    zones_to_remove.append(j)
                elif current_price < zone_low:  # Zone invalidated
                    zone['active'] = False
                    zones_to_remove.append(j)
            
            elif zone_type in ['be_ob', 'be_bb']:  # Red/Bearish zones
                if current_price < zone_low:  # Break BELOW red zone
                    df.loc[i, 'red_break_below'] = True
                    df.loc[i, 'zone_type'] = zone_type.upper().replace('_', '-')  # 'BE-OB' or 'BE-BB'
                    df.loc[i, 'zone_high'] = zone_high
                    df.loc[i, 'zone_low'] = zone_low
                    zone['active'] = False
                    zones_to_remove.append(j)
                elif current_price > zone_high:  # Zone invalidated
                    zone['active'] = False
                    zones_to_remove.append(j)
        
        # Remove inactive zones
        for j in sorted(zones_to_remove, reverse=True):
            active_zones.pop(j)
        
        df.loc[i, 'market_structure'] = current_market
    
    # Clean up temporary columns
    df.drop(['pivot_high', 'pivot_low'], axis=1, inplace=True, errors='ignore')
    
    return df