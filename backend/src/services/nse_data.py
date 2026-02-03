"""
NSE Market Data Service using nselib
SEBI Compliant: All data timestamped and logged

Provides:
- Historical index data (NIFTY 50, BANK NIFTY)
- Historical stock OHLC data (5-year backtest support)  
- Live option chain data
- India VIX (from index data)
- F&O stock universe
"""

from typing import Dict, Any, Optional, List
import pandas as pd
import redis
import json
import logging
from datetime import datetime, timedelta
from functools import lru_cache

# nselib imports
from nselib import capital_market, derivatives

logger = logging.getLogger(__name__)


class NSEDataService:
    """
    Real NSE market data service using nselib.
    Tested and verified with actual NSE data.
    
    SEBI Compliant: All data requests logged with timestamps.
    """
    
    def __init__(self, redis_client: Optional[redis.Redis] = None):
        """
        Initialize NSE Data Service.
        
        Args:
            redis_client: Optional Redis client for caching.
                         If None, caching is disabled.
        """
        self.cache = redis_client
        self.cache_enabled = redis_client is not None
        
        # Cache TTL settings (seconds)
        self.cache_ttl = {
            "quote": 5,           # 5 seconds for real-time quotes
            "ohlc": 300,          # 5 minutes for historical OHLC
            "option_chain": 60,   # 1 minute for option chain
            "vix": 60,            # 1 minute for VIX
            "fno_stocks": 3600,   # 1 hour for F&O stock list
        }
        
        logger.info("NSE Data Service initialized")
    
    # ==================== INDEX DATA ====================
    
    async def get_index_ohlc(
        self, 
        index: str = "NIFTY 50",
        period: str = "1M"  # 1M, 3M, 6M, 1Y, 3Y, 5Y
    ) -> pd.DataFrame:
        """
        Get historical OHLC data for index.
        
        Args:
            index: Index name (e.g., "NIFTY 50", "NIFTY BANK")
            period: Time period - 1M, 3M, 6M, 1Y, 3Y, 5Y
        
        Returns:
            DataFrame with date, open, high, low, close, volume
        """
        cache_key = f"idx_ohlc:{index}:{period}"
        
        if self.cache_enabled:
            cached = self.cache.get(cache_key)
            if cached:
                logger.debug(f"Cache hit for {cache_key}")
                return pd.read_json(cached)
        
        try:
            # Calculate date range
            end_date = datetime.now()
            period_days = {
                "1M": 30, "3M": 90, "6M": 180, 
                "1Y": 365, "3Y": 1095, "5Y": 1825
            }
            days = period_days.get(period, 30)
            start_date = end_date - timedelta(days=days)
            
            from_date = start_date.strftime("%d-%m-%Y")
            to_date = end_date.strftime("%d-%m-%Y")
            
            logger.info(f"Fetching index OHLC for {index} from {from_date} to {to_date}")
            
            # Fetch from NSE
            df = capital_market.index_data(
                index=index,
                from_date=from_date,
                to_date=to_date
            )
            
            if df is None or df.empty:
                logger.warning(f"No data returned for index {index}")
                return pd.DataFrame()
            
            # Standardize column names
            df = self._standardize_index_columns(df)
            
            # Sort by date
            if 'date' in df.columns:
                df = df.sort_values('date').reset_index(drop=True)
            
            # Cache the result
            if self.cache_enabled:
                self.cache.setex(
                    cache_key,
                    self.cache_ttl["ohlc"],
                    df.to_json()
                )
            
            logger.info(f"Fetched {len(df)} rows of index OHLC data for {index}")
            return df
            
        except Exception as e:
            logger.error(f"NSE index OHLC fetch failed for {index}: {e}")
            return pd.DataFrame()
    
    def _standardize_index_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """Standardize index data column names."""
        column_mapping = {
            'TIMESTAMP': 'date',
            'INDEX_NAME': 'symbol',
            'OPEN_INDEX_VAL': 'open',
            'HIGH_INDEX_VAL': 'high',
            'LOW_INDEX_VAL': 'low',
            'CLOSE_INDEX_VAL': 'close',
            'TURN_OVER': 'turnover',
            'TRADED_QTY': 'volume',
        }
        df = df.rename(columns=column_mapping)
        
        # Convert numeric columns
        for col in ['open', 'high', 'low', 'close', 'volume']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        return df
    
    async def get_latest_index_value(self, index: str = "NIFTY 50") -> Dict[str, Any]:
        """
        Get latest index value from recent data.
        
        Args:
            index: Index name
            
        Returns:
            Dict with ltp, open, high, low, change
        """
        try:
            df = await self.get_index_ohlc(index, period="1M")
            
            if df.empty:
                raise ValueError(f"No data for {index}")
            
            latest = df.iloc[-1]
            prev = df.iloc[-2] if len(df) > 1 else latest
            
            ltp = float(latest.get('close', 0))
            prev_close = float(prev.get('close', ltp))
            change = ((ltp - prev_close) / prev_close * 100) if prev_close else 0
            
            return {
                "symbol": index,
                "ltp": ltp,
                "open": float(latest.get('open', 0)),
                "high": float(latest.get('high', 0)),
                "low": float(latest.get('low', 0)),
                "prev_close": prev_close,
                "change": round(change, 2),
                "date": str(latest.get('date', '')),
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Latest index value failed for {index}: {e}")
            raise
    
    async def get_india_vix(self) -> float:
        """
        Get India VIX value for volatility assessment.
        
        Returns:
            Current VIX value as float
        """
        cache_key = "vix:india"
        
        if self.cache_enabled:
            cached = self.cache.get(cache_key)
            if cached:
                return float(cached)
        
        try:
            df = await self.get_index_ohlc("NIFTY VIX", period="1M")
            
            if df.empty:
                # Try alternative name
                df = await self.get_index_ohlc("India VIX", period="1M")
            
            if not df.empty:
                vix = float(df.iloc[-1].get('close', 15.0))
                
                if self.cache_enabled:
                    self.cache.setex(cache_key, self.cache_ttl["vix"], str(vix))
                
                logger.info(f"India VIX: {vix}")
                return vix
            
            logger.warning("VIX not found, returning default 15.0")
            return 15.0
            
        except Exception as e:
            logger.error(f"VIX fetch failed: {e}")
            return 15.0
    
    # ==================== STOCK DATA ====================
    
    async def get_stock_ohlc(
        self, 
        symbol: str,
        period: str = "1Y"  # 1M, 3M, 6M, 1Y, 3Y, 5Y
    ) -> pd.DataFrame:
        """
        Get historical OHLC data for a stock.
        
        Args:
            symbol: Stock symbol (e.g., "RELIANCE", "TCS")
            period: Time period
        
        Returns:
            DataFrame with date, open, high, low, close, volume
        """
        cache_key = f"stock_ohlc:{symbol}:{period}"
        
        if self.cache_enabled:
            cached = self.cache.get(cache_key)
            if cached:
                logger.debug(f"Cache hit for {cache_key}")
                return pd.read_json(cached)
        
        try:
            # Calculate date range
            end_date = datetime.now()
            period_days = {
                "1M": 30, "3M": 90, "6M": 180, 
                "1Y": 365, "3Y": 1095, "5Y": 1825
            }
            days = period_days.get(period, 365)
            start_date = end_date - timedelta(days=days)
            
            from_date = start_date.strftime("%d-%m-%Y")
            to_date = end_date.strftime("%d-%m-%Y")
            
            logger.info(f"Fetching stock OHLC for {symbol} from {from_date} to {to_date}")
            
            # Fetch from NSE
            df = capital_market.price_volume_and_deliverable_position_data(
                symbol=symbol,
                from_date=from_date,
                to_date=to_date
            )
            
            if df is None or df.empty:
                logger.warning(f"No data returned for {symbol}")
                return pd.DataFrame()
            
            # Standardize column names
            df = self._standardize_stock_columns(df)
            
            # Sort by date
            if 'date' in df.columns:
                df['date'] = pd.to_datetime(df['date'], format='%d-%b-%Y', errors='coerce')
                df = df.sort_values('date').reset_index(drop=True)
            
            # Cache the result
            if self.cache_enabled:
                self.cache.setex(
                    cache_key,
                    self.cache_ttl["ohlc"],
                    df.to_json()
                )
            
            logger.info(f"Fetched {len(df)} rows of stock OHLC data for {symbol}")
            return df
            
        except Exception as e:
            logger.error(f"NSE stock OHLC fetch failed for {symbol}: {e}")
            return pd.DataFrame()
    
    def _standardize_stock_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """Standardize stock data column names."""
        column_mapping = {
            'Date': 'date',
            'Symbol': 'symbol',
            'Series': 'series',
            'OpenPrice': 'open',
            'HighPrice': 'high',
            'LowPrice': 'low',
            'ClosePrice': 'close',
            'LastPrice': 'ltp',
            'PrevClose': 'prev_close',
            'TotalTradedQuantity': 'volume',
            'TurnoverInRs': 'turnover',
            'No.ofTrades': 'trades',
            'DeliverableQty': 'delivery_qty',
            '%DlyQttoTradedQty': 'delivery_pct',
            'AveragePrice': 'vwap',
        }
        df = df.rename(columns=column_mapping)
        
        # Convert numeric columns
        for col in ['open', 'high', 'low', 'close', 'ltp', 'volume', 'vwap']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        return df
    
    # ==================== OPTION CHAIN ====================
    
    async def get_option_chain(
        self, 
        symbol: str = "NIFTY"
    ) -> Dict[str, Any]:
        """
        Get live option chain for strike selection.
        
        Args:
            symbol: Underlying symbol (NIFTY, BANKNIFTY, etc.)
        
        Returns:
            Dict with spot_price, expiry_dates, and chain data
        """
        cache_key = f"oc:{symbol}"
        
        if self.cache_enabled:
            cached = self.cache.get(cache_key)
            if cached:
                logger.debug(f"Cache hit for option chain {symbol}")
                return json.loads(cached)
        
        try:
            # Fetch from NSE
            chain = derivatives.nse_live_option_chain(symbol)
            
            if chain is None:
                raise ValueError(f"No option chain data for {symbol}")
            
            # Handle different response formats
            if isinstance(chain, dict):
                records = chain.get('records', chain)
                result = {
                    "symbol": symbol,
                    "spot_price": records.get('underlyingValue', 0),
                    "expiry_dates": records.get('expiryDates', []),
                    "strikePrices": records.get('strikePrices', []),
                    "data": records.get('data', []),
                    "timestamp": datetime.now().isoformat()
                }
            elif isinstance(chain, pd.DataFrame):
                result = {
                    "symbol": symbol,
                    "data": chain.to_dict('records'),
                    "timestamp": datetime.now().isoformat()
                }
            else:
                result = {
                    "symbol": symbol,
                    "raw": str(chain),
                    "timestamp": datetime.now().isoformat()
                }
            
            # Cache the result
            if self.cache_enabled:
                self.cache.setex(
                    cache_key,
                    self.cache_ttl["option_chain"],
                    json.dumps(result, default=str)
                )
            
            logger.info(f"Fetched option chain for {symbol}")
            return result
            
        except Exception as e:
            logger.error(f"Option chain fetch failed for {symbol}: {e}")
            raise
    
    # ==================== UNIVERSES ====================
    
    def get_nifty_100_stocks(self) -> List[str]:
        """
        Get NIFTY 100 constituents for universe.
        
        Returns:
            List of NIFTY 100 stock symbols
        """
        # Hardcoded NIFTY 100 (combination of NIFTY 50 + Next 50)
        return [
            # NIFTY 50 (Top 50 by market cap)
            "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
            "HINDUNILVR", "SBIN", "BHARTIARTL", "KOTAKBANK", "ITC",
            "AXISBANK", "LT", "BAJFINANCE", "ASIANPAINT", "MARUTI",
            "HCLTECH", "SUNPHARMA", "TITAN", "WIPRO", "ULTRACEMCO",
            "TATAMOTORS", "TATASTEEL", "JSWSTEEL", "POWERGRID", "NTPC",
            "ONGC", "COALINDIA", "TECHM", "BAJAJFINSV", "NESTLEIND",
            "M&M", "INDUSINDBK", "ADANIENT", "ADANIPORTS", "GRASIM",
            "DIVISLAB", "DRREDDY", "CIPLA", "APOLLOHOSP", "BRITANNIA",
            "EICHERMOT", "HDFCLIFE", "SBILIFE", "HEROMOTOCO", "BAJAJ-AUTO",
            "TATAPOWER", "TATACONSUM", "BPCL", "HINDALCO", "VEDL",
            # NIFTY Next 50
            "PIDILITIND", "BERGEPAINT", "HAVELLS", "SIEMENS", "ABB",
            "GODREJCP", "DABUR", "MARICO", "PAGEIND", "MUTHOOTFIN",
            "CHOLAFIN", "TVSMOTOR", "TORNTPOWER", "JINDALSTEL", "SAIL",
            "GAIL", "IOC", "PFC", "RECLTD", "BANKBARODA",
            "CANBK", "PNB", "AMBUJACEM", "ACC", "DLF",
            "GODREJPROP", "OBEROIRLTY", "PRESTIGE", "PHOENIXLTD", "ZOMATO",
            "PAYTM", "NYKAA", "POLICYBZR", "DELHIVERY", "CARTRADE",
            "IRCTC", "HAL", "BEL", "RVNL", "IRFC",
            "TRENT", "ZYDUSLIFE", "LUPIN", "BIOCON", "AUROPHARMA"
        ]
    
    def get_fno_stocks(self) -> List[str]:
        """
        Get list of F&O eligible stocks.
        
        Returns:
            List of stock symbols eligible for F&O trading
        """
        # Popular F&O stocks (high liquidity)
        return [
            "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
            "HINDUNILVR", "SBIN", "BHARTIARTL", "KOTAKBANK", "ITC",
            "AXISBANK", "LT", "BAJFINANCE", "ASIANPAINT", "MARUTI",
            "HCLTECH", "SUNPHARMA", "TITAN", "WIPRO", "ULTRACEMCO",
            "TATAMOTORS", "TATASTEEL", "JSWSTEEL", "POWERGRID", "NTPC",
            "ONGC", "COALINDIA", "TECHM", "BAJAJFINSV", "NESTLEIND",
            "M&M", "INDUSINDBK", "ADANIENT", "ADANIPORTS", "GRASIM",
            "DIVISLAB", "DRREDDY", "CIPLA", "APOLLOHOSP", "BRITANNIA",
            "EICHERMOT", "HDFCLIFE", "SBILIFE", "HEROMOTOCO", "BAJAJ-AUTO",
            "TATAPOWER", "TATACONSUM", "BPCL", "HINDALCO", "VEDL",
            "BANKBARODA", "CANBK", "PNB", "DLF", "ZOMATO",
            "IRCTC", "HAL", "BEL", "TRENT", "LUPIN"
        ]
    
    # ==================== TECHNICAL INDICATORS ====================
    
    async def get_stock_with_indicators(
        self,
        symbol: str,
        period: str = "1Y"
    ) -> pd.DataFrame:
        """
        Get stock OHLC data with common technical indicators calculated.
        
        Args:
            symbol: Stock symbol
            period: Time period
            
        Returns:
            DataFrame with OHLC + indicators (EMA, RSI, MACD, etc.)
        """
        import ta
        
        df = await self.get_stock_ohlc(symbol, period)
        
        if df.empty:
            return df
        
        # Ensure we have the required columns
        if not all(col in df.columns for col in ['close', 'high', 'low', 'volume']):
            logger.warning(f"Missing required columns for indicators in {symbol}")
            return df
        
        try:
            # Moving Averages
            df['ema_9'] = ta.trend.ema_indicator(df['close'], window=9)
            df['ema_21'] = ta.trend.ema_indicator(df['close'], window=21)
            df['ema_50'] = ta.trend.ema_indicator(df['close'], window=50)
            df['ema_200'] = ta.trend.ema_indicator(df['close'], window=200)
            df['sma_20'] = ta.trend.sma_indicator(df['close'], window=20)
            
            # RSI
            df['rsi'] = ta.momentum.rsi(df['close'], window=14)
            
            # MACD
            macd = ta.trend.MACD(df['close'])
            df['macd'] = macd.macd()
            df['macd_signal'] = macd.macd_signal()
            df['macd_hist'] = macd.macd_diff()
            
            # Bollinger Bands
            bb = ta.volatility.BollingerBands(df['close'])
            df['bb_upper'] = bb.bollinger_hband()
            df['bb_middle'] = bb.bollinger_mavg()
            df['bb_lower'] = bb.bollinger_lband()
            
            # ATR (for stop-loss calculation)
            df['atr'] = ta.volatility.average_true_range(df['high'], df['low'], df['close'])
            
            # VWAP (requires volume)
            if 'volume' in df.columns and df['volume'].sum() > 0:
                df['vwap_calc'] = (df['close'] * df['volume']).cumsum() / df['volume'].cumsum()
            
            # ADX (trend strength)
            df['adx'] = ta.trend.adx(df['high'], df['low'], df['close'])
            
            logger.info(f"Calculated indicators for {symbol}")
            
        except Exception as e:
            logger.error(f"Indicator calculation failed for {symbol}: {e}")
        
        return df
    
    # ==================== UTILITY METHODS ====================
    
    async def is_market_open(self) -> bool:
        """Check if NSE is currently open for trading."""
        now = datetime.now()
        
        # Check if weekend
        if now.weekday() >= 5:  # Saturday = 5, Sunday = 6
            return False
        
        # Check market hours (9:15 AM - 3:30 PM IST)
        from datetime import time
        market_open = time(9, 15)
        market_close = time(15, 30)
        
        current_time = now.time()
        return market_open <= current_time <= market_close
    
    async def health_check(self) -> Dict[str, Any]:
        """
        Verify NSE data connectivity.
        
        Returns:
            Dict with status and details
        """
        try:
            # Try to fetch index data
            df = await self.get_index_ohlc("NIFTY 50", period="1M")
            
            if df.empty:
                raise ValueError("No index data returned")
            
            latest = df.iloc[-1]
            
            return {
                "status": "healthy",
                "nse_connected": True,
                "nifty_close": float(latest.get('close', 0)),
                "data_date": str(latest.get('date', '')),
                "market_open": await self.is_market_open(),
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            return {
                "status": "unhealthy",
                "nse_connected": False,
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }


# Singleton instance (without Redis for now)
nse_data_service = NSEDataService()
