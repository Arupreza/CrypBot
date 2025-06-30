import ccxt
import time
import pandas as pd
from datetime import datetime, timedelta

class BinanceEMAScanner:
    def __init__(self, api_key=None, api_secret=None):
        """Initialize Binance connection"""
        self.exchange = ccxt.binance({
            'apiKey': api_key,
            'secret': api_secret,
            'sandbox': False,
            'rateLimit': 1200,
            'enableRateLimit': True,
        })
        
    def get_symbol_listing_date(self, symbol):
        """Get the listing date of a symbol by checking historical data availability"""
        try:
            # Convert to CCXT format
            ccxt_symbol = symbol.replace('USDT', '/USDT')
            
            # Fetch the earliest available data (1 day timeframe for efficiency)
            # Start from a very early date and work forward
            earliest_data = self.exchange.fetch_ohlcv(
                ccxt_symbol, 
                '1d', 
                limit=1000,  # Get maximum available history
                since=None   # Get from the earliest available
            )
            
            if earliest_data:
                # Convert timestamp to datetime
                earliest_timestamp = earliest_data[0][0]  # First candle timestamp
                listing_date = datetime.fromtimestamp(earliest_timestamp / 1000)
                return listing_date
            else:
                return None
                
        except Exception as e:
            print(f"Error getting listing date for {symbol}: {e}")
            return None
    
    def has_sufficient_data(self, symbol, min_days=365):
        """Check if symbol has at least min_days of historical data"""
        try:
            # Convert to CCXT format
            ccxt_symbol = symbol.replace('USDT', '/USDT')
            
            # Calculate timestamp for min_days ago
            cutoff_date = datetime.now() - timedelta(days=min_days)
            cutoff_timestamp = int(cutoff_date.timestamp() * 1000)
            
            # Try to fetch data from the cutoff date
            historical_data = self.exchange.fetch_ohlcv(
                ccxt_symbol,
                '1d',
                since=cutoff_timestamp,
                limit=min_days
            )
            
            # Check if we have sufficient data points
            return len(historical_data) >= min_days * 0.9  # Allow 10% tolerance for missing days
            
        except Exception as e:
            print(f"Error checking data availability for {symbol}: {e}")
            return False
    
    def filter_by_listing_age_and_data(self, symbols, min_age_days=365, min_data_days=365):
        """Filter symbols based on listing age and data availability"""
        filtered_symbols = []
        current_date = datetime.now()
        
        print(f"Filtering {len(symbols)} symbols for listing age > {min_age_days} days and data availability...")
        
        for i, symbol in enumerate(symbols):
            try:
                print(f"Processing {i+1}/{len(symbols)}: {symbol}")
                
                # Get listing date
                listing_date = self.get_symbol_listing_date(symbol)
                
                if listing_date is None:
                    print(f"  - Skipped: Could not determine listing date")
                    continue
                
                # Calculate age in days
                age_days = (current_date - listing_date).days
                
                if age_days <= min_age_days:
                    print(f"  - Skipped: Listed {age_days} days ago (< {min_age_days} days)")
                    continue
                
                # Check data availability
                if not self.has_sufficient_data(symbol, min_data_days):
                    print(f"  - Skipped: Insufficient historical data")
                    continue
                
                print(f"  - Included: Listed {age_days} days ago, sufficient data available")
                filtered_symbols.append(symbol)
                
                # Add small delay to avoid rate limits
                time.sleep(0.1)
                
            except Exception as e:
                print(f"  - Error processing {symbol}: {e}")
                continue
        
        return filtered_symbols
    
    def get_usdt_pairs_under_30(self):
        """Get all active USDT trading pairs under $30, excluding stablecoins"""
        stablecoins = [
            'GUSDUSDT', 'FRAXUSDT', 'USDDUSDT', 'MIMUSDT', 'LUSDUSDT', 'FEIUSDT', 'HUSDUSDT', 
            'SUSDUSDT', 'OUSDUSDT', 'USTCUSDT', 'VAIUSDT', 'DOLAUSDT', 'ALUSDUSDT', 'MUSDUSDT', 
            'DUSDUSDT', 'CUSDUSDT', 'NUSDUSDT', 'ZUSDUSDT', 'EURUSDT', "USDPUSDT", 'TUSDUSDT', 
            'PAXUSDT', 'BUSDUSDT', 'DAIUSDT', 'USDNUSDT', 'USDKUSDT', 'BTTCUSDT', 'XUSDUSDT'
        ]
        
        try:
            # Get all markets
            markets = self.exchange.load_markets()
            usdt_pairs = []
            
            # Filter USDT pairs and exclude stablecoins
            for symbol in markets.keys():
                if (symbol.endswith('/USDT') and 
                    markets[symbol]['active'] and 
                    markets[symbol]['spot']):
                    # Convert to Binance format: BTC/USDT -> BTCUSDT
                    binance_symbol = symbol.replace('/', '')
                    if binance_symbol not in stablecoins:
                        usdt_pairs.append(binance_symbol)
            
            # Filter out leveraged tokens
            filtered_pairs = [pair for pair in usdt_pairs 
                            if not any(x in pair for x in ['UP', 'DOWN', 'BEAR', 'BULL'])]
            
            # Get current prices and filter pairs under $30
            pairs_under_30 = []
            
            # Get ticker prices for all symbols at once (more efficient)
            tickers = self.exchange.fetch_tickers()
            
            for pair in filtered_pairs:
                try:
                    # Convert back to CCXT format for ticker lookup
                    ccxt_symbol = pair.replace('USDT', '/USDT')
                    
                    if ccxt_symbol in tickers:
                        current_price = tickers[ccxt_symbol]['last']
                        if current_price and current_price <= 30:
                            pairs_under_30.append({
                                'symbol': pair,
                                'price': current_price
                            })
                except Exception as e:
                    print(f"Error processing {pair}: {e}")
                    continue
            
            # Sort by price (lowest to highest)
            pairs_under_30.sort(key=lambda x: x['price'])
            
            return pairs_under_30
            
        except Exception as e:
            print(f"Error fetching USDT pairs: {e}")
            return []
    
    def get_usdt_pairs_symbols_only(self):
        """Get only the symbol names (without prices) for pairs under $30"""
        pairs_data = self.get_usdt_pairs_under_30()
        return [pair['symbol'] for pair in pairs_data]
    
    def get_filtered_symbols_with_age_and_data(self, max_price=30, min_age_days=365, min_data_days=365):
        """Get symbols under max_price that are older than min_age_days and have sufficient data"""
        # First get all pairs under the price threshold
        pairs_under_price = self.get_usdt_pairs_under_30() if max_price == 30 else self.get_usdt_pairs_under_price(max_price)
        symbols = [pair['symbol'] for pair in pairs_under_price]
        
        print(f"Found {len(symbols)} symbols under ${max_price}")
        
        # Filter by listing age and data availability
        filtered_symbols = self.filter_by_listing_age_and_data(symbols, min_age_days, min_data_days)
        
        print(f"Final result: {len(filtered_symbols)} symbols meet all criteria")
        return filtered_symbols
    
    def get_usdt_pairs_under_price(self, max_price):
        """Get all active USDT trading pairs under specified price, excluding stablecoins"""
        stablecoins = [
            'GUSDUSDT', 'FRAXUSDT', 'USDDUSDT', 'MIMUSDT', 'LUSDUSDT', 'FEIUSDT', 'HUSDUSDT', 
            'SUSDUSDT', 'OUSDUSDT', 'USTCUSDT', 'VAIUSDT', 'DOLAUSDT', 'ALUSDUSDT', 'MUSDUSDT', 
            'DUSDUSDT', 'CUSDUSDT', 'NUSDUSDT', 'ZUSDUSDT', 'EURUSDT', "USDPUSDT", 'TUSDUSDT', 
            'PAXUSDT', 'BUSDUSDT', 'DAIUSDT', 'USDNUSDT', 'USDKUSDT', 'BTTCUSDT', 'XUSDUSDT'
        ]
        
        try:
            # Get all markets
            markets = self.exchange.load_markets()
            usdt_pairs = []
            
            # Filter USDT pairs and exclude stablecoins
            for symbol in markets.keys():
                if (symbol.endswith('/USDT') and 
                    markets[symbol]['active'] and 
                    markets[symbol]['spot']):
                    # Convert to Binance format: BTC/USDT -> BTCUSDT
                    binance_symbol = symbol.replace('/', '')
                    if binance_symbol not in stablecoins:
                        usdt_pairs.append(binance_symbol)
            
            # Filter out leveraged tokens
            filtered_pairs = [pair for pair in usdt_pairs 
                            if not any(x in pair for x in ['UP', 'DOWN', 'BEAR', 'BULL'])]
            
            # Get current prices and filter pairs under max_price
            pairs_under_price = []
            
            # Get ticker prices for all symbols at once (more efficient)
            tickers = self.exchange.fetch_tickers()
            
            for pair in filtered_pairs:
                try:
                    # Convert back to CCXT format for ticker lookup
                    ccxt_symbol = pair.replace('USDT', '/USDT')
                    
                    if ccxt_symbol in tickers:
                        current_price = tickers[ccxt_symbol]['last']
                        if current_price and current_price <= max_price:
                            pairs_under_price.append({
                                'symbol': pair,
                                'price': current_price
                            })
                except Exception as e:
                    print(f"Error processing {pair}: {e}")
                    continue
            
            # Sort by price (lowest to highest)
            pairs_under_price.sort(key=lambda x: x['price'])
            
            return pairs_under_price
            
        except Exception as e:
            print(f"Error fetching USDT pairs: {e}")
            return []

def get_symbol(max_price=30, min_age_days=365, min_data_days=365):
    """
    Get symbols that meet all criteria:
    - Price under max_price (default $30)
    - Listed more than min_age_days ago (default 365 days)
    - Have at least min_data_days of historical data (default 365 days)
    """
    scanner = BinanceEMAScanner()
    
    # Get filtered symbols
    filtered_symbols = scanner.get_filtered_symbols_with_age_and_data(
        max_price=max_price,
        min_age_days=min_age_days,
        min_data_days=min_data_days
    )
    
    return filtered_symbols