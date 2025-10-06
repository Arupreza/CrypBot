import pandas as pd
import numpy as np
import ccxt
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

class SmartMoneyScanner:
    def __init__(self, exchange_name='binance', market_type='spot'):
        """
        Initialize the Smart Money Concept Scanner
        
        Args:
            exchange_name (str): Exchange name (default: 'binance')
            market_type (str): 'spot' or 'future' (perpetual contracts)
        """
        self.market_type = market_type
        
        # Configure exchange based on market type
        if market_type == 'future':
            self.exchange = getattr(ccxt, exchange_name)({
                'sandbox': False,
                'rateLimit': 1200,
                'enableRateLimit': True,
                'options': {
                    'defaultType': 'future'  # Enables perpetual contracts
                }
            })
            print(f"✅ Initialized for Binance PERPETUAL CONTRACTS")
        else:
            self.exchange = getattr(ccxt, exchange_name)({
                'sandbox': False,
                'rateLimit': 1200,
                'enableRateLimit': True,
                'options': {
                    'defaultType': 'spot'  # Enables spot trading
                }
            })
            print(f"✅ Initialized for Binance SPOT TRADING")
        
    def get_historical_data(self, symbol, timeframe='4h', limit=500):
        """
        Get historical OHLCV data for a symbol (works for both spot and perpetual)
        
        Args:
            symbol (str): Trading pair symbol (e.g., 'BTCUSDT')
            timeframe (str): Timeframe ('1m', '5m', '15m', '1h', '4h', '1d', etc.)
            limit (int): Number of candles to retrieve
            
        Returns:
            pd.DataFrame: OHLCV data
        """
        try:
            # Convert Binance format to CCXT format
            if '/' not in symbol:
                quote_currencies = ['USDT', 'BUSD', 'BTC', 'ETH', 'BNB', 'USDC']
                ccxt_symbol = symbol
                
                for quote in quote_currencies:
                    if symbol.endswith(quote):
                        base = symbol[:-len(quote)]
                        
                        if self.market_type == 'future':
                            # For perpetual contracts: BTC/USDT:USDT format
                            ccxt_symbol = f"{base}/{quote}:{quote}"
                        else:
                            # For spot: BTC/USDT format
                            ccxt_symbol = f"{base}/{quote}"
                        break
            else:
                ccxt_symbol = symbol
            
            # Fetch OHLCV data using ccxt
            ohlcv = self.exchange.fetch_ohlcv(ccxt_symbol, timeframe, limit=limit)
            
            # Convert to DataFrame
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            # Convert timestamp to datetime
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            
            # Ensure numeric types
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            
            return df
            
        except Exception as e:
            print(f"Error fetching data for {symbol} ({self.market_type}): {e}")
            return None
    
    def get_market_info(self, symbol):
        """
        Get additional market information (funding rate for perpetual, etc.)
        """
        try:
            if self.market_type == 'future':
                # Convert to CCXT format
                if '/' not in symbol:
                    quote_currencies = ['USDT', 'BUSD', 'USDC']
                    for quote in quote_currencies:
                        if symbol.endswith(quote):
                            base = symbol[:-len(quote)]
                            ccxt_symbol = f"{base}/{quote}:{quote}"
                            break
                else:
                    ccxt_symbol = symbol
                
                # Get funding rate for perpetual contracts
                funding_info = self.exchange.fetch_funding_rate(ccxt_symbol)
                return {
                    'market_type': 'Perpetual Contract',
                    'funding_rate': funding_info.get('fundingRate', 0) * 100,  # Convert to percentage
                    'next_funding': funding_info.get('fundingDatetime', 'N/A')
                }
            else:
                return {
                    'market_type': 'Spot Trading',
                    'funding_rate': 'N/A (Spot)',
                    'next_funding': 'N/A (Spot)'
                }
        except Exception as e:
            return {
                'market_type': self.market_type,
                'funding_rate': 'Error fetching',
                'next_funding': 'Error fetching'
            }
    
    def identify_fair_value_gaps(self, df):
        """
        IMPROVED: Identify Fair Value Gaps with proper invalidation tracking
        """
        fvgs = []
        
        for i in range(2, len(df)):
            prev_candle = df.iloc[i-2]
            current_candle = df.iloc[i-1]
            next_candle = df.iloc[i]
            
            # Bullish FVG: prev_high < next_low (gap up)
            if prev_candle['high'] < next_candle['low']:
                gap_size = next_candle['low'] - prev_candle['high']
                gap_percentage = (gap_size / prev_candle['high']) * 100
                
                fvgs.append({
                    'type': 'bullish_fvg',
                    'timestamp': df.index[i],
                    'upper': next_candle['low'],
                    'lower': prev_candle['high'],
                    'size': gap_size,
                    'size_percentage': gap_percentage,
                    'volume_confirmation': current_candle['volume'] > df['volume'].rolling(20).mean().iloc[i],
                    'candle_index': i,
                    'status': 'active',  # NEW: Track FVG status
                    'invalidated_at': None,
                    'invalidation_reason': None,
                    'fill_percentage': 0.0
                })
            
            # Bearish FVG: prev_low > next_high (gap down)
            elif prev_candle['low'] > next_candle['high']:
                gap_size = prev_candle['low'] - next_candle['high']
                gap_percentage = (gap_size / prev_candle['low']) * 100
                
                fvgs.append({
                    'type': 'bearish_fvg',
                    'timestamp': df.index[i],
                    'upper': prev_candle['low'],
                    'lower': next_candle['high'],
                    'size': gap_size,
                    'size_percentage': gap_percentage,
                    'volume_confirmation': current_candle['volume'] > df['volume'].rolling(20).mean().iloc[i],
                    'candle_index': i,
                    'status': 'active',  # NEW: Track FVG status
                    'invalidated_at': None,
                    'invalidation_reason': None,
                    'fill_percentage': 0.0
                })
        
        # IMPROVED: Check for FVG invalidation with proper logic
        for fvg in fvgs:
            if fvg['status'] == 'active':  # Only check active FVGs
                fvg_index = fvg['candle_index']
                subsequent_candles = df.iloc[fvg_index+1:]
                
                for j, candle in subsequent_candles.iterrows():
                    invalidated = False
                    
                    if fvg['type'] == 'bullish_fvg':
                        # Bullish FVG invalidation conditions
                        if candle['low'] <= fvg['upper']:  # Price touches or enters FVG
                            
                            # Calculate fill percentage
                            if candle['low'] <= fvg['lower']:
                                # Completely filled - INVALIDATED
                                fvg['fill_percentage'] = 100.0
                                fvg['status'] = 'invalidated'
                                fvg['invalidation_reason'] = 'completely_filled'
                                invalidated = True
                            else:
                                # Partially filled
                                fill_level = (fvg['upper'] - candle['low']) / (fvg['upper'] - fvg['lower'])
                                fvg['fill_percentage'] = fill_level * 100
                                
                                # Invalidate if filled more than 70% (more conservative)
                                if fvg['fill_percentage'] > 70:
                                    fvg['status'] = 'invalidated'
                                    fvg['invalidation_reason'] = 'partially_filled_>70%'
                                    invalidated = True
                                else:
                                    fvg['status'] = 'partially_filled'
                            
                            if invalidated:
                                fvg['invalidated_at'] = j
                                break
                    
                    elif fvg['type'] == 'bearish_fvg':
                        # Bearish FVG invalidation conditions
                        if candle['high'] >= fvg['lower']:  # Price touches or enters FVG
                            
                            # Calculate fill percentage
                            if candle['high'] >= fvg['upper']:
                                # Completely filled - INVALIDATED
                                fvg['fill_percentage'] = 100.0
                                fvg['status'] = 'invalidated'
                                fvg['invalidation_reason'] = 'completely_filled'
                                invalidated = True
                            else:
                                # Partially filled
                                fill_level = (candle['high'] - fvg['lower']) / (fvg['upper'] - fvg['lower'])
                                fvg['fill_percentage'] = fill_level * 100
                                
                                # Invalidate if filled more than 70% (more conservative)
                                if fvg['fill_percentage'] > 70:
                                    fvg['status'] = 'invalidated'
                                    fvg['invalidation_reason'] = 'partially_filled_>70%'
                                    invalidated = True
                                else:
                                    fvg['status'] = 'partially_filled'
                            
                            if invalidated:
                                fvg['invalidated_at'] = j
                                break
        
        return fvgs
    
    def check_current_price_in_fvg(self, df, fvgs):
        """
        IMPROVED: Check if current price is in FVG with proper invalidation handling
        """
        if not fvgs or len(df) == 0:
            return {'in_fvg': False, 'fvg_details': None}
        
        current_price = df['close'].iloc[-1]
        current_candle = df.iloc[-1]
        
        # IMPROVED: Only consider ACTIVE FVGs (not invalidated)
        active_fvgs = [fvg for fvg in fvgs if 
                       fvg['status'] == 'active' and  # Only active FVGs
                       len(df) - fvg['candle_index'] <= 50]  # Recent FVGs
        
        for fvg in active_fvgs:
            # IMPROVED: Check if current price would invalidate this FVG
            would_invalidate = False
            
            if fvg['type'] == 'bullish_fvg':
                if current_candle['low'] <= fvg['upper']:
                    # Price is touching/entering the FVG
                    if current_candle['low'] <= fvg['lower']:
                        # Would completely fill - FVG is invalidated
                        would_invalidate = True
                    else:
                        # Partially in FVG - check if too much filled
                        fill_level = (fvg['upper'] - current_candle['low']) / (fvg['upper'] - fvg['lower'])
                        if fill_level > 0.7:  # More than 70% filled
                            would_invalidate = True
            
            elif fvg['type'] == 'bearish_fvg':
                if current_candle['high'] >= fvg['lower']:
                    # Price is touching/entering the FVG
                    if current_candle['high'] >= fvg['upper']:
                        # Would completely fill - FVG is invalidated
                        would_invalidate = True
                    else:
                        # Partially in FVG - check if too much filled
                        fill_level = (current_candle['high'] - fvg['lower']) / (fvg['upper'] - fvg['lower'])
                        if fill_level > 0.7:  # More than 70% filled
                            would_invalidate = True
            
            # Skip invalidated FVGs
            if would_invalidate:
                continue
            
            # If we reach here, FVG is still valid and tradeable
            if fvg['lower'] <= current_price <= fvg['upper']:
                fvg_range = fvg['upper'] - fvg['lower']
                position_in_fvg = (current_price - fvg['lower']) / fvg_range
                
                if fvg['type'] == 'bullish_fvg':
                    fill_percentage = (1 - position_in_fvg) * 100
                else:
                    fill_percentage = position_in_fvg * 100
                
                return {
                    'in_fvg': True,
                    'fvg_details': {
                        'type': fvg['type'],
                        'timestamp': fvg['timestamp'],
                        'upper': fvg['upper'],
                        'lower': fvg['lower'],
                        'size': fvg['size'],
                        'size_percentage': fvg['size_percentage'],
                        'current_price': current_price,
                        'position_in_fvg': position_in_fvg,
                        'fill_percentage': round(fill_percentage, 2),
                        'volume_confirmation': fvg['volume_confirmation'],
                        'age_candles': len(df) - fvg['candle_index'],
                        'fvg_status': fvg['status'],  # NEW: Show FVG status
                        'trade_signal': self._generate_fvg_trade_signal(fvg, current_price, position_in_fvg)
                    }
                }
        
        return {'in_fvg': False, 'fvg_details': None}
    
    def _generate_fvg_trade_signal(self, fvg, current_price, position_in_fvg):
        """
        Generate trade signal based on FVG position
        """
        signal = {
            'direction': None,
            'entry_zone': None,
            'stop_loss': None,
            'target': None,
            'risk_reward': None,
            'confidence': 'medium'
        }
        
        if fvg['type'] == 'bullish_fvg':
            signal['direction'] = 'LONG'
            signal['entry_zone'] = f"{fvg['lower']:.2f} - {fvg['upper']:.2f}"
            signal['stop_loss'] = fvg['lower'] * 0.995
            signal['target'] = fvg['upper'] + (fvg['size'] * 1.5)
            
            if position_in_fvg <= 0.3:
                signal['confidence'] = 'high'
            elif position_in_fvg <= 0.6:
                signal['confidence'] = 'medium'
            else:
                signal['confidence'] = 'low'
                
        elif fvg['type'] == 'bearish_fvg':
            signal['direction'] = 'SHORT'
            signal['entry_zone'] = f"{fvg['lower']:.2f} - {fvg['upper']:.2f}"
            signal['stop_loss'] = fvg['upper'] * 1.005
            signal['target'] = fvg['lower'] - (fvg['size'] * 1.5)
            
            if position_in_fvg >= 0.7:
                signal['confidence'] = 'high'
            elif position_in_fvg >= 0.4:
                signal['confidence'] = 'medium'
            else:
                signal['confidence'] = 'low'
        
        if signal['stop_loss'] and signal['target']:
            risk = abs(current_price - signal['stop_loss'])
            reward = abs(signal['target'] - current_price)
            signal['risk_reward'] = round(reward / risk, 2) if risk > 0 else 0
        
        return signal
    
    def scan_fvg_opportunities(self, coin_list, timeframe='15m', min_gap_size=0.3):
        """
        IMPROVED: Scan for coins with proper FVG invalidation logic
        """
        fvg_opportunities = []
        
        print(f"\n🔍 Scanning {len(coin_list)} coins on {self.market_type.upper()} market...")
        
        for symbol in coin_list:
            try:
                print(f"Scanning FVG opportunities for {symbol} ({self.market_type})...")
                
                # Get historical data
                df = self.get_historical_data(symbol, timeframe)
                if df is None or len(df) < 100:
                    continue
                
                # IMPROVED: Identify Fair Value Gaps with invalidation tracking
                fvgs = self.identify_fair_value_gaps(df)
                if not fvgs:
                    continue
                
                # Filter FVGs by minimum size AND only active status
                significant_fvgs = [fvg for fvg in fvgs if 
                                   fvg['size_percentage'] >= min_gap_size and
                                   fvg['status'] == 'active']  # NEW: Only active FVGs
                
                if not significant_fvgs:
                    continue
                
                # IMPROVED: Check if current price is in any ACTIVE FVG
                fvg_analysis = self.check_current_price_in_fvg(df, significant_fvgs)
                
                if fvg_analysis['in_fvg']:
                    fvg_details = fvg_analysis['fvg_details']
                    trade_signal = fvg_details['trade_signal']
                    
                    # Get market info (funding rate for perpetual)
                    market_info = self.get_market_info(symbol)
                    
                    # Calculate volume confirmation
                    current_volume = df['volume'].iloc[-1]
                    avg_volume = df['volume'].rolling(20).mean().iloc[-1]
                    volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1
                    
                    opportunity = {
                        'symbol': symbol,
                        'market_type': self.market_type,
                        'current_price': fvg_details['current_price'],
                        'fvg_type': fvg_details['type'],
                        'trade_direction': trade_signal['direction'],
                        'confidence': trade_signal['confidence'],
                        'entry_zone': trade_signal['entry_zone'],
                        'stop_loss': trade_signal['stop_loss'],
                        'target': trade_signal['target'],
                        'risk_reward': trade_signal['risk_reward'],
                        'gap_size_pct': fvg_details['size_percentage'],
                        'fill_percentage': fvg_details['fill_percentage'],
                        'position_in_gap': round(fvg_details['position_in_fvg'] * 100, 1),
                        'gap_age_candles': fvg_details['age_candles'],
                        'volume_confirmation': fvg_details['volume_confirmation'],
                        'current_volume_ratio': round(volume_ratio, 2),
                        'funding_rate': market_info.get('funding_rate', 'N/A'),
                        'fvg_status': fvg_details['fvg_status'],
                        'fvg_timestamp': fvg_details['timestamp'],
                        'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    }
                    
                    fvg_opportunities.append(opportunity)
                    
            except Exception as e:
                print(f"Error scanning FVG for {symbol}: {e}")
                continue
        
        # Create DataFrame and sort by confidence and risk-reward
        if fvg_opportunities:
            fvg_df = pd.DataFrame(fvg_opportunities)
            confidence_score = fvg_df['confidence'].map({'high': 3, 'medium': 2, 'low': 1})
            fvg_df['composite_score'] = confidence_score + (fvg_df['risk_reward'] * 0.5)
            fvg_df = fvg_df.sort_values('composite_score', ascending=False)
            return fvg_df
        else:
            return pd.DataFrame()
    
    def get_fvg_long_signals(self, fvg_df, min_confidence='medium', min_risk_reward=1.5):
        """Filter FVG opportunities for long trades"""
        if fvg_df.empty:
            return fvg_df
        
        confidence_hierarchy = {'high': 3, 'medium': 2, 'low': 1}
        min_conf_value = confidence_hierarchy.get(min_confidence, 2)
        
        long_signals = fvg_df[
            (fvg_df['trade_direction'] == 'LONG') &
            (fvg_df['fvg_type'] == 'bullish_fvg') &
            (fvg_df['confidence'].map(confidence_hierarchy) >= min_conf_value) &
            (fvg_df['risk_reward'] >= min_risk_reward)
        ].copy()
        
        return long_signals.sort_values('composite_score', ascending=False)
    
    def get_fvg_short_signals(self, fvg_df, min_confidence='medium', min_risk_reward=1.5):
        """Filter FVG opportunities for short trades"""
        if fvg_df.empty:
            return fvg_df
        
        confidence_hierarchy = {'high': 3, 'medium': 2, 'low': 1}
        min_conf_value = confidence_hierarchy.get(min_confidence, 2)
        
        short_signals = fvg_df[
            (fvg_df['trade_direction'] == 'SHORT') &
            (fvg_df['fvg_type'] == 'bearish_fvg') &
            (fvg_df['confidence'].map(confidence_hierarchy) >= min_conf_value) &
            (fvg_df['risk_reward'] >= min_risk_reward)
        ].copy()
        
        return short_signals.sort_values('composite_score', ascending=False)

# ================================================
# ESSENTIAL FUNCTIONS ONLY - LONG, SHORT, SPOT
# ================================================

def get_long_signals(coins, timeframe='15m', market_type='spot'):
    """
    Get long trading signals
    
    Args:
        coins: List of coins ['BTCUSDT', 'ETHUSDT']
        timeframe: '1m', '5m', '15m', '1h', '4h', '1d'
        market_type: 'spot' or 'future'
    
    Returns:
        DataFrame with long signals
    """
    scanner = SmartMoneyScanner('binance', market_type=market_type)
    fvg_df = scanner.scan_fvg_opportunities(coins, timeframe)
    return scanner.get_fvg_long_signals(fvg_df, min_confidence='medium', min_risk_reward=1.5)

def get_short_signals(coins, timeframe='15m', market_type='future'):
    """
    Get short trading signals (works best with perpetual contracts)
    
    Args:
        coins: List of coins ['BTCUSDT', 'ETHUSDT']
        timeframe: '1m', '5m', '15m', '1h', '4h', '1d'
        market_type: 'spot' or 'future' (recommend 'future' for shorts)
    
    Returns:
        DataFrame with short signals
    """
    scanner = SmartMoneyScanner('binance', market_type=market_type)
    fvg_df = scanner.scan_fvg_opportunities(coins, timeframe)
    return scanner.get_fvg_short_signals(fvg_df, min_confidence='medium', min_risk_reward=1.5)

def get_spot_signals(coins, timeframe='15m'):
    """
    Get spot trading signals (long only)
    
    Args:
        coins: List of coins ['BTCUSDT', 'ETHUSDT']
        timeframe: '1m', '5m', '15m', '1h', '4h', '1d'
    
    Returns:
        DataFrame with spot long signals
    """
    scanner = SmartMoneyScanner('binance', market_type='spot')
    fvg_df = scanner.scan_fvg_opportunities(coins, timeframe)
    return scanner.get_fvg_long_signals(fvg_df, min_confidence='medium', min_risk_reward=1.5)

def quick_scan(coins=None, timeframe='15m'):
    """
    Quick scan for all trading opportunities
    
    Args:
        coins: List of coins (default: top 5 coins)
        timeframe: Timeframe to scan (default: 15m)
    
    Returns:
        dict with all signal types
    """
    
    # Default coins if none provided
    if coins is None:
        coins = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'ADAUSDT', 'SOLUSDT']
    
    print(f"⚡ QUICK FVG SCAN")
    print(f"🪙 Coins: {', '.join(coins)}")
    print(f"⏰ Timeframe: {timeframe}")
    print("=" * 40)
    
    # Get all signals
    spot_longs = get_spot_signals(coins, timeframe)
    perp_longs = get_long_signals(coins, timeframe, market_type='future')
    perp_shorts = get_short_signals(coins, timeframe, market_type='future')
    
    total_signals = len(spot_longs) + len(perp_longs) + len(perp_shorts)
    
    print(f"✅ Total signals found: {total_signals}")
    print(f"   📈 Spot longs: {len(spot_longs)}")
    print(f"   📈 Perpetual longs: {len(perp_longs)}")
    print(f"   📉 Perpetual shorts: {len(perp_shorts)}")
    
    # Show best opportunities
    all_signals = []
    
    # Add spot longs
    for _, signal in spot_longs.iterrows():
        all_signals.append({
            'symbol': signal['symbol'],
            'type': 'SPOT LONG',
            'price': signal['current_price'],
            'risk_reward': signal['risk_reward'],
            'confidence': signal['confidence'],
            'entry': signal['entry_zone'],
            'target': signal['target'],
            'stop': signal['stop_loss']
        })
    
    # Add perp longs
    for _, signal in perp_longs.iterrows():
        all_signals.append({
            'symbol': signal['symbol'],
            'type': 'PERP LONG',
            'price': signal['current_price'],
            'risk_reward': signal['risk_reward'],
            'confidence': signal['confidence'],
            'entry': signal['entry_zone'],
            'target': signal['target'],
            'stop': signal['stop_loss']
        })
    
    # Add perp shorts
    for _, signal in perp_shorts.iterrows():
        all_signals.append({
            'symbol': signal['symbol'],
            'type': 'PERP SHORT',
            'price': signal['current_price'],
            'risk_reward': signal['risk_reward'],
            'confidence': signal['confidence'],
            'entry': signal['entry_zone'],
            'target': signal['target'],
            'stop': signal['stop_loss']
        })
    
    # Sort by risk/reward ratio
    all_signals.sort(key=lambda x: x['risk_reward'], reverse=True)
    
    if all_signals:
        print(f"\n🏆 TOP OPPORTUNITIES (sorted by R/R):")
        print("-" * 50)
        
        for i, signal in enumerate(all_signals[:10], 1):  # Show top 10
            print(f"{i}. {signal['type']} - {signal['symbol']}")
            print(f"   💰 Price: ${signal['price']:.4f}")
            print(f"   🎯 Entry: {signal['entry']}")
            print(f"   🚀 Target: ${signal['target']:.4f}")
            print(f"   ⛔ Stop: ${signal['stop']:.4f}")
            print(f"   ⚖️ R/R: {signal['risk_reward']}")
            print(f"   🔥 Confidence: {signal['confidence']}")
            print()
    else:
        print("❌ No opportunities found")
        print("💡 Try different timeframe or coins")
    
    return {
        'spot_longs': spot_longs,
        'perp_longs': perp_longs,
        'perp_shorts': perp_shorts,
        'total_count': total_signals
    }
    

#spot_longs = get_spot_signals(my_coins, timeframe='15m')

#perp_longs = get_long_signals(my_coins, timeframe='15m', market_type='future')

#perp_shorts = get_short_signals(my_coins, timeframe='15m', market_type='future')