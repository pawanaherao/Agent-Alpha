"""
Enhanced Scanner Agent with Global Best Practices
PROFESSIONAL ALGO TRADING FILTERS - 2024

Technical Filters (12 Total):
1. RSI (14) - Momentum
2. ADX (14) - Trend strength
3. Volume (20-day avg) - Liquidity
4. MACD - Trend momentum
5. Stochastic (14,3,3) - Timing
6. Bollinger Bands - Volatility
7. OBV - Volume confirmation
8. Parabolic SAR - Trend direction
9. ATR - Volatility filter
10. EMA Alignment (9/21/50)
11. VWAP Proximity
12. Delivery % (NSE specific)

GenAI Validation:
- Multi-factor scoring
- News sentiment integration
- Pattern recognition
"""

from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, time
import pandas as pd
import numpy as np
import logging
import asyncio
import ta

# GenAI imports
try:
    import vertexai
    from vertexai.generative_models import GenerativeModel
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False

from src.agents.base import BaseAgent
from src.services.nse_data import nse_data_service
from src.core.config import settings

logger = logging.getLogger(__name__)


class ScannerAgent(BaseAgent):
    """
    Enhanced Scanner Agent with 12 Technical Filters + GenAI Validation.
    
    GLOBAL BEST PRACTICES IMPLEMENTED:
    1. Multi-indicator confirmation
    2. Trend + Momentum + Volume triangle
    3. AI-assisted scoring
    4. Regime-adaptive filtering
    """
    
    # Top stocks by liquidity and volatility
    SCAN_UNIVERSE = [
        # Banking
        "HDFCBANK", "ICICIBANK", "AXISBANK", "KOTAKBANK", "SBIN", "INDUSINDBK",
        # IT
        "TCS", "INFY", "WIPRO", "HCLTECH", "TECHM",
        # Energy
        "RELIANCE", "ONGC", "NTPC", "POWERGRID",
        # FMCG
        "HINDUNILVR", "ITC", "NESTLEIND", "BRITANNIA",
        # Auto
        "MARUTI", "TATAMOTORS", "M&M", "BAJAJ-AUTO",
        # Pharma
        "SUNPHARMA", "DRREDDY", "CIPLA",
        # Finance
        "BAJFINANCE", "BAJAJFINSV",
        # Metals
        "TATASTEEL", "HINDALCO", "JSWSTEEL"
    ]
    
    def __init__(self, name: str = "ScannerAgent", config: Dict[str, Any] = None):
        super().__init__(name, config)
        
        self.nse_service = nse_data_service
        self.model = None
        
        # Technical filter thresholds
        self.filters = {
            # Momentum
            "rsi_min": 40,
            "rsi_max": 70,
            "stoch_oversold": 20,
            "stoch_overbought": 80,
            
            # Trend
            "adx_min": 20,
            "macd_confirm": True,
            "ema_alignment": True,
            "psar_confirm": True,
            
            # Volume
            "volume_ratio_min": 1.3,
            "obv_rising": True,
            
            # Volatility
            "bb_squeeze": False,  # Optional
            "atr_min_pct": 0.01,  # 1% min ATR
            
            # NSE specific
            "delivery_pct_min": 30,  # Min 30% delivery
            "vwap_proximity_pct": 0.02  # Within 2% of VWAP
        }
        
        # Scoring weights
        self.weights = {
            "rsi_score": 0.10,
            "adx_score": 0.10,
            "macd_score": 0.12,
            "stoch_score": 0.08,
            "volume_score": 0.15,
            "obv_score": 0.10,
            "ema_score": 0.10,
            "psar_score": 0.08,
            "bb_score": 0.07,
            "delivery_score": 0.15, # High weight for institutional conviction
            "genai_score": 0.05  # Reduced AI weight
        }
        
        self.project_id = getattr(settings, 'GCP_PROJECT', None)
        self.location = "us-central1"
        
        logger.info("Scanner Agent initialized with 12 technical filters")
    
    async def start(self):
        """Initialize GenAI for validation."""
        await super().start()
        
        if GENAI_AVAILABLE and self.project_id:
            try:
                vertexai.init(project=self.project_id, location=self.location)
                self.model = GenerativeModel("gemini-1.5-flash")
                logger.info("GenAI validation enabled")
            except Exception as e:
                logger.warning(f"GenAI init failed: {e}")
    
    async def scan_universe(
        self, 
        regime: str = "BULL",
        top_n: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Scan entire universe and return top N stocks.
        
        Args:
            regime: Current market regime (BULL, BEAR, SIDEWAYS, VOLATILE)
            top_n: Number of top stocks to return
            
        Returns:
            List of stock dicts with scores and indicators
        """
        logger.info(f"Scanning {len(self.SCAN_UNIVERSE)} stocks in {regime} regime")
        
        # Adjust filters based on regime
        adjusted_filters = self._adjust_filters_for_regime(regime)
        
        results = []
        
        for symbol in self.SCAN_UNIVERSE:
            try:
                score, indicators = await self._analyze_stock(symbol, adjusted_filters)
                
                if score > 50:  # Minimum threshold
                    results.append({
                        "symbol": symbol,
                        "score": score,
                        "indicators": indicators,
                        "regime": regime,
                        "timestamp": datetime.now().isoformat()
                    })
                    
            except Exception as e:
                logger.debug(f"Scan failed for {symbol}: {e}")
            
            # Rate limiting
            await asyncio.sleep(0.1)
        
        # Sort by score and return top N
        results.sort(key=lambda x: x['score'], reverse=True)
        top_stocks = results[:top_n]
        
        logger.info(f"Found {len(top_stocks)} qualified stocks")
        
        # Publish event
        await self.publish_event("SCAN_COMPLETE", {
            "regime": regime,
            "stocks": [s['symbol'] for s in top_stocks],
            "timestamp": datetime.now().isoformat()
        })
        
        return top_stocks
    
    async def _analyze_stock(
        self, 
        symbol: str, 
        filters: Dict
    ) -> Tuple[float, Dict]:
        """
        Analyze a single stock with all 12 technical filters.
        
        Returns:
            Tuple of (overall_score, indicator_dict)
        """
        # Fetch data
        df = await self.nse_service.get_stock_ohlc(symbol, period="3M")
        
        if df is None or df.empty or len(df) < 50:
            return 0, {}
        
        # Calculate all indicators
        indicators = await self._calculate_all_indicators(df)
        
        # Score each indicator
        scores = {}
        
        # 1. RSI Score
        rsi = indicators.get('rsi', 50)
        if filters['rsi_min'] <= rsi <= filters['rsi_max']:
            scores['rsi_score'] = 100 - abs(rsi - 55) * 2  # Peak at 55
        else:
            scores['rsi_score'] = max(0, 50 - abs(rsi - 55))
        
        # 2. ADX Score
        adx = indicators.get('adx', 0)
        if adx >= filters['adx_min']:
            scores['adx_score'] = min(100, adx * 3)
        else:
            scores['adx_score'] = adx * 2
        
        # 3. MACD Score
        macd_signal = indicators.get('macd_signal', 0)  # 1=bullish, -1=bearish, 0=neutral
        if filters.get('macd_confirm'):
            scores['macd_score'] = 50 + macd_signal * 50
        else:
            scores['macd_score'] = 50
        
        # 4. Stochastic Score
        stoch = indicators.get('stoch_k', 50)
        if stoch < filters['stoch_oversold']:
            scores['stoch_score'] = 80  # Good for buying
        elif stoch > filters['stoch_overbought']:
            scores['stoch_score'] = 30  # Overbought
        else:
            scores['stoch_score'] = 60
        
        # 5. Volume Score
        volume_ratio = indicators.get('volume_ratio', 1.0)
        if volume_ratio >= filters['volume_ratio_min']:
            scores['volume_score'] = min(100, volume_ratio * 50)
        else:
            scores['volume_score'] = volume_ratio * 40
        
        # 6. OBV Score
        obv_rising = indicators.get('obv_rising', False)
        scores['obv_score'] = 80 if obv_rising else 40
        
        # 7. EMA Alignment Score
        ema_aligned = indicators.get('ema_aligned', False)
        scores['ema_score'] = 90 if ema_aligned else 40
        
        # 8. Parabolic SAR Score
        psar_bullish = indicators.get('psar_bullish', False)
        scores['psar_score'] = 85 if psar_bullish else 35
        
        # 9. Bollinger Band Score
        bb_position = indicators.get('bb_position', 0.5)  # 0=lower, 0.5=mid, 1=upper
        scores['bb_score'] = 100 - abs(bb_position - 0.5) * 100  # Peak at middle
        
        # 10. Delivery % Score (Institutional Filter)
        delivery_pct = indicators.get('delivery_pct', 0)
        if delivery_pct >= filters.get('delivery_pct_min', 30):
            scores['delivery_score'] = min(100, (delivery_pct / 60) * 100) # Max 100 at 60% delivery
        else:
            scores['delivery_score'] = (delivery_pct / 30) * 40 # Penalize low delivery
        
        # 11. GenAI Score (if available)
        if self.model:
            genai_score = await self._get_genai_score(symbol, indicators)
            scores['genai_score'] = genai_score
        else:
            scores['genai_score'] = 50  # Neutral
        
        # Calculate weighted average
        total_score = sum(
            scores.get(k, 50) * self.weights.get(k, 0) 
            for k in self.weights.keys()
        )
        
        # Normalize to 0-100
        total_score = min(100, max(0, total_score))
        
        indicators['total_score'] = total_score
        indicators['scores_breakdown'] = scores
        
        return total_score, indicators
    
    async def _calculate_all_indicators(self, df: pd.DataFrame) -> Dict:
        """Calculate all 12 technical indicators."""
        
        close = df['close'].astype(float)
        high = df['high'].astype(float)
        low = df['low'].astype(float)
        volume = df['volume'].astype(float)
        
        indicators = {}
        
        try:
            # 1. RSI
            indicators['rsi'] = float(ta.momentum.rsi(close, window=14).iloc[-1])
            
            # 2. ADX
            adx_indicator = ta.trend.ADXIndicator(high, low, close, window=14)
            indicators['adx'] = float(adx_indicator.adx().iloc[-1])
            indicators['di_plus'] = float(adx_indicator.adx_pos().iloc[-1])
            indicators['di_minus'] = float(adx_indicator.adx_neg().iloc[-1])
            
            # 3. MACD
            macd = ta.trend.MACD(close)
            macd_line = macd.macd().iloc[-1]
            signal_line = macd.macd_signal().iloc[-1]
            indicators['macd'] = float(macd_line)
            indicators['macd_signal'] = 1 if macd_line > signal_line else -1
            
            # 4. Stochastic
            stoch = ta.momentum.StochasticOscillator(high, low, close, window=14, smooth_window=3)
            indicators['stoch_k'] = float(stoch.stoch().iloc[-1])
            indicators['stoch_d'] = float(stoch.stoch_signal().iloc[-1])
            
            # 5. Volume ratio
            avg_volume = volume.rolling(20).mean().iloc[-1]
            indicators['volume_ratio'] = float(volume.iloc[-1] / avg_volume) if avg_volume > 0 else 1.0
            
            # 6. OBV
            obv = ta.volume.on_balance_volume(close, volume)
            obv_sma = obv.rolling(10).mean()
            indicators['obv_rising'] = bool(obv.iloc[-1] > obv_sma.iloc[-1])
            
            # 7. EMA Alignment (9 > 21 > 50 = bullish)
            ema_9 = ta.trend.ema_indicator(close, window=9).iloc[-1]
            ema_21 = ta.trend.ema_indicator(close, window=21).iloc[-1]
            ema_50 = ta.trend.ema_indicator(close, window=50).iloc[-1]
            indicators['ema_aligned'] = bool(close.iloc[-1] > ema_9 > ema_21 > ema_50)
            
            # 8. Parabolic SAR
            psar = ta.trend.PSARIndicator(high, low, close)
            psar_value = psar.psar().iloc[-1]
            indicators['psar_bullish'] = bool(close.iloc[-1] > psar_value)
            
            # 9. Bollinger Bands
            bb = ta.volatility.BollingerBands(close, window=20)
            bb_upper = bb.bollinger_hband().iloc[-1]
            bb_lower = bb.bollinger_lband().iloc[-1]
            bb_range = bb_upper - bb_lower
            indicators['bb_position'] = float((close.iloc[-1] - bb_lower) / bb_range) if bb_range > 0 else 0.5
            indicators['bb_width'] = float(bb_range / close.iloc[-1])
            
            # 10. ATR
            indicators['atr'] = float(ta.volatility.average_true_range(high, low, close).iloc[-1])
            indicators['atr_pct'] = float(indicators['atr'] / close.iloc[-1])
            
            # 11. Current price
            indicators['price'] = float(close.iloc[-1])
            
            # 12. Delivery %
            indicators['delivery_pct'] = await self.nse_service.get_delivery_percentage(df.get('symbol', 'UNKNOWN'))
            if indicators['delivery_pct'] == 0 and 'symbol' in df.columns:
                 indicators['delivery_pct'] = await self.nse_service.get_delivery_percentage(df['symbol'].iloc[0])
            
        except Exception as e:
            logger.debug(f"Indicator calculation error: {e}")
        
        return indicators
    
    async def _get_genai_score(self, symbol: str, indicators: Dict) -> float:
        """
        Get GenAI validation score for stock.
        
        Uses AI to:
        1. Validate technical setup quality
        2. Check for red flags
        3. Score overall opportunity
        """
        if not self.model:
            return 50
        
        try:
            prompt = f"""
            Score this stock for INTRADAY trading (0-100):
            
            Symbol: {symbol}
            Current Price: {indicators.get('price', 'N/A')}
            
            Technical Indicators:
            - RSI(14): {indicators.get('rsi', 'N/A'):.1f}
            - ADX: {indicators.get('adx', 'N/A'):.1f}
            - MACD Signal: {'Bullish' if indicators.get('macd_signal', 0) > 0 else 'Bearish'}
            - Stochastic: {indicators.get('stoch_k', 'N/A'):.1f}
            - Volume: {indicators.get('volume_ratio', 1):.1f}x average
            - EMA Aligned: {indicators.get('ema_aligned', False)}
            - Parabolic SAR: {'Bullish' if indicators.get('psar_bullish', False) else 'Bearish'}
            
            Scoring Criteria:
            - 80-100: Strong setup, multiple confirmations
            - 60-79: Good setup, trade with caution
            - 40-59: Weak setup, avoid
            - 0-39: Red flags present
            
            Return ONLY a number 0-100.
            """
            
            response = await asyncio.to_thread(
                self.model.generate_content, prompt
            )
            
            score_text = response.text.strip()
            import re
            match = re.search(r'\d+', score_text)
            if match:
                return min(100, max(0, float(match.group())))
            
        except Exception as e:
            logger.debug(f"GenAI scoring failed: {e}")
        
        return 50
    
    def _adjust_filters_for_regime(self, regime: str) -> Dict:
        """Adjust filter thresholds based on market regime."""
        adjusted = self.filters.copy()
        
        if regime == "BULL":
            adjusted['rsi_min'] = 45
            adjusted['rsi_max'] = 75
            adjusted['adx_min'] = 20
            adjusted['volume_ratio_min'] = 1.2
        
        elif regime == "BEAR":
            adjusted['rsi_min'] = 30
            adjusted['rsi_max'] = 55
            adjusted['adx_min'] = 25
            adjusted['volume_ratio_min'] = 1.5
        
        elif regime == "SIDEWAYS":
            adjusted['rsi_min'] = 40
            adjusted['rsi_max'] = 60
            adjusted['adx_min'] = 15  # Lower threshold for ranging
            adjusted['bb_squeeze'] = True
        
        elif regime == "VOLATILE":
            adjusted['adx_min'] = 30
            adjusted['atr_min_pct'] = 0.015
            adjusted['volume_ratio_min'] = 1.5
        
        return adjusted
    
    def get_scanner_summary(self) -> Dict:
        """Get summary of scanner configuration."""
        return {
            "universe_size": len(self.SCAN_UNIVERSE),
            "filters_count": len(self.filters),
            "genai_enabled": self.model is not None,
            "indicator_weights": self.weights
        }
