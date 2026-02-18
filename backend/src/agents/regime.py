"""
Regime Agent - Market Regime Classification
SEBI Compliant: Whitebox logic with transparent rules

Classifies market into: BULL, BEAR, SIDEWAYS, VOLATILE
Based on: ADX (trend strength), EMA alignment, RSI, VIX
"""

from typing import Dict, Any, Optional
import pandas as pd
import ta
import numpy as np
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from datetime import datetime

from src.agents.base import BaseAgent
from src.core.config import settings
from src.services.nse_data import nse_data_service


class RegimeAgent(BaseAgent):
    """
    Agent responsible for classifying Market Regime.
    
    WHITEBOX LOGIC (SEBI Compliant):
    - Uses ADX for trend strength
    - Uses EMA(20,50) alignment for trend direction
    - Uses RSI for momentum
    - Uses VIX for volatility context
    
    OUTPUTS:
    - BULL: Strong uptrend (ADX>25, Price>EMA20>EMA50)
    - BEAR: Strong downtrend (ADX>25, Price<EMA20<EMA50)
    - SIDEWAYS: No clear trend (ADX<25, RSI between 40-60)
    - VOLATILE: High uncertainty (VIX>20 or mixed signals)
    """
    
    def __init__(self, name: str = "RegimeAgent", config: Dict[str, Any] = None):
        super().__init__(name, config)
        self.current_regime = "SIDEWAYS"
        self.current_vix = 15.0
        self.nse_service = nse_data_service
    
    async def analyze_with_real_data(self, index: str = "NIFTY 50") -> str:
        """
        Classify regime using REAL NSE data.
        
        Args:
            index: Index to analyze (default NIFTY 50)
            
        Returns:
            Regime string: BULL, BEAR, SIDEWAYS, VOLATILE
        """
        try:
            # 1. Fetch real data from NSE
            self.logger.info(f"Fetching real data for {index}...")
            df = await self.nse_service.get_index_ohlc(index, period="3M")
            
            if df.empty:
                self.logger.warning("No data received from NSE, using fallback")
                return self.current_regime
            
            # 2. Get VIX for volatility context
            try:
                self.current_vix = await self.nse_service.get_india_vix()
            except:
                self.current_vix = 15.0  # Default
            
            # 3. Classify regime
            regime = await self.classify_regime(df)
            
            self.logger.info(f"Regime: {regime}, VIX: {self.current_vix:.2f}")
            return regime
            
        except Exception as e:
            self.logger.error(f"Real data analysis failed: {e}")
            return self.current_regime
    
    async def classify_regime(self, market_data: pd.DataFrame) -> str:
        """
        Classify the current market regime based on technical indicators.
        
        WHITEBOX RULES:
        1. ADX > 25 = Trending market
        2. Price > EMA20 > EMA50 = BULL
        3. Price < EMA20 < EMA50 = BEAR
        4. VIX > 25 = VOLATILE override
        5. Otherwise = SIDEWAYS
        
        Args:
            market_data: DataFrame with OHLC columns
            
        Returns:
            Regime string
        """
        try:
            # Ensure we have required columns
            if 'close' not in market_data.columns:
                self.logger.error("Missing 'close' column in market data")
                return "SIDEWAYS"
            
            if len(market_data) < 50:
                self.logger.warning(f"Insufficient data: {len(market_data)} rows")
                return "SIDEWAYS"
            
            close = market_data['close'].astype(float)
            high = market_data.get('high', close).astype(float)
            low = market_data.get('low', close).astype(float)
            
            # 1. Calculate Indicators using 'ta' library
            # ADX for trend strength
            adx_indicator = ta.trend.ADXIndicator(high, low, close, window=14)
            adx_values = adx_indicator.adx()
            
            # RSI for momentum
            rsi_values = ta.momentum.rsi(close, window=14)
            
            # EMAs for trend direction
            ema_20 = ta.trend.ema_indicator(close, window=20)
            ema_50 = ta.trend.ema_indicator(close, window=50)
            
            # Get latest values
            current_adx = adx_values.iloc[-1] if not adx_values.empty else 20
            current_rsi = rsi_values.iloc[-1] if not rsi_values.empty else 50
            current_price = close.iloc[-1]
            current_ema_20 = ema_20.iloc[-1] if not ema_20.empty else current_price
            current_ema_50 = ema_50.iloc[-1] if not ema_50.empty else current_price
            
            # 2. Statistical Regime Detection (Phase 4)
            statistical_regime = await self._detect_regime_kmeans(market_data)
            
            # 3. Apply WHITEBOX Logic Rules + Statistical Fusion
            
            # VIX Override: High volatility = VOLATILE
            if self.current_vix > 25:
                regime = "VOLATILE"
                self.logger.info(f"VIX Override: {self.current_vix:.2f} > 25")
            
            # If statistical regime is confident, use it to augment rules
            elif statistical_regime and statistical_regime != "SIDEWAYS":
                regime = statistical_regime
                self.logger.info(f"Statistical Regime detected: {regime}")
            
            # Rule-based fallback/refinement
            elif current_adx > 25:  # Strong trend
                if current_price > current_ema_20 > current_ema_50:
                    regime = "BULL"
                elif current_price < current_ema_20 < current_ema_50:
                    regime = "BEAR"
                else:
                    regime = "VOLATILE"
            
            else:
                if current_rsi > 60 and current_price > current_ema_20:
                    regime = "BULL"
                elif current_rsi < 40 and current_price < current_ema_20:
                    regime = "BEAR"
                else:
                    regime = "SIDEWAYS"
            
            # Update state
            self.current_regime = regime
            
            # Log decision rationale
            self.logger.info(
                f"Regime Decision: {regime} (Stat: {statistical_regime}) | "
                f"ADX={current_adx:.1f}, RSI={current_rsi:.1f}, VIX={self.current_vix:.1f}"
            )
            
            # 4. Publish Event
            await self.publish_event("REGIME_UPDATED", {
                "regime": regime,
                "statistical_regime": statistical_regime,
                "vix": float(self.current_vix),
                "timestamp": datetime.now().isoformat()
            })
            
            return regime

        except Exception as e:
            self.logger.error(f"Regime Classification Failed: {e}", exc_info=True)
            return "SIDEWAYS"  # Safe fallback

    async def _detect_regime_kmeans(self, df: pd.DataFrame) -> str:
        """
        Unsupervised Regime Detection using K-Means.
        Clusters are mapped to: BULL, BEAR, SIDEWAYS, VOLATILE.
        """
        try:
            if len(df) < 30: return "SIDEWAYS"
            
            # 1. Feature Engineering
            df_feat = pd.DataFrame()
            df_feat['returns'] = df['close'].pct_change()
            df_feat['volatility'] = df_feat['returns'].rolling(10).std()
            df_feat['momentum'] = ta.momentum.rsi(df['close'], window=14) / 100
            
            X = df_feat.dropna()
            if len(X) < 20: return "SIDEWAYS"
            
            # 2. Normalization
            scaler = StandardScaler()
            X_scaled = scaler.fit_transform(X)
            
            # 3. K-Means Clustering (4 regimes)
            kmeans = KMeans(n_clusters=4, random_state=42, n_init=10)
            clusters = kmeans.fit_predict(X_scaled)
            
            # Get latest cluster
            latest_cluster = clusters[-1]
            
            # 4. Map Clusters to Human-Readable Regimes
            # Strategy: Analyze cluster centers
            centers = kmeans.cluster_centers_
            # Centers columns: 0=Returns, 1=Volatility, 2=Momentum (scaled)
            
            # Bull: High returns, Low volatility, High Momentum
            # Bear: Low returns, High Volatility, Low Momentum
            # Sideways: Low returns, Low Volatility, Mid Momentum
            # Volatile: Mixed returns, Very High Volatility
            
            # Find Bull: Highest returns * momentum
            cluster_ranks = {}
            for i in range(4):
                score = centers[i, 0] + centers[i, 2] - centers[i, 1]
                cluster_ranks[i] = score
                
            sorted_clusters = sorted(cluster_ranks.items(), key=lambda x: x[1])
            
            mapping = {
                sorted_clusters[3][0]: "BULL",
                sorted_clusters[0][0]: "BEAR",
                sorted_clusters[1][0]: "SIDEWAYS",
                sorted_clusters[2][0]: "VOLATILE"
            }
            
            return mapping.get(latest_cluster, "SIDEWAYS")
            
        except Exception as e:
             self.logger.debug(f"K-Means Regime detection failed: {e}")
             return "SIDEWAYS"
    
    def get_regime_strategy_weights(self) -> Dict[str, float]:
        """
        Get strategy type weights based on current regime.
        Used by Risk Agent for dynamic allocation.
        
        Returns:
            Dict with weights for each strategy type
        """
        weights = {
            "BULL": {
                "momentum": 0.4,
                "trend": 0.3,
                "mean_reversion": 0.1,
                "theta": 0.1,
                "hedge": 0.1
            },
            "BEAR": {
                "momentum": 0.1,
                "trend": 0.1,
                "mean_reversion": 0.1,
                "theta": 0.2,
                "hedge": 0.5
            },
            "SIDEWAYS": {
                "momentum": 0.1,
                "trend": 0.1,
                "mean_reversion": 0.3,
                "theta": 0.4,
                "hedge": 0.1
            },
            "VOLATILE": {
                "momentum": 0.2,
                "trend": 0.1,
                "mean_reversion": 0.1,
                "theta": 0.1,
                "hedge": 0.5
            }
        }
        
        return weights.get(self.current_regime, weights["SIDEWAYS"])
