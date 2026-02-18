import pandas as pd
import pandas_ta as ta
import logging
from typing import Dict, Any, Optional, List

from src.strategies.base import BaseStrategy, StrategySignal

logger = logging.getLogger(__name__)

class UniversalStrategy(BaseStrategy):
    """
    The 'Super-Algo' for SEBI Compliance.
    
    Instead of writing new code for every user strategy, this class 
    contains ALL supported logic blocks (RSI, MACD, SMA, etc.).
    
    The AI (or User) simply provides a JSON Configuration ('Universal Parameter Matrix')
    to enable/disable specific blocks.
    
    Configuration Schema Example:
    {
        "entry_conditions": [
            {"type": "RSI", "period": 14, "condition": "GT", "value": 30},
            {"type": "SMA", "period": 200, "condition": "CROSS_ABOVE", "value": "CLOSE"}
        ],
        "exit_conditions": [ ... ],
        "stop_loss_pct": 0.02
    }
    """
    def __init__(self, config: Dict[str, Any] = None):
        # Default Config if none provided
        default_config = {
            "entry_conditions": [],
            "exit_conditions": [],
            "stop_loss_pct": 0.0,
            "take_profit_pct": 0.0
        }
        # Merge provided config with defaults
        final_config = {**default_config, **(config or {})}
        super().__init__("UniversalStrategy", final_config)
    
    async def calculate_suitability(self, market_data: pd.DataFrame, regime: str) -> float:
        """
        Suitability depends on the *active* logic blocks.
        For MVP, we return a neutral score as this is a meta-strategy.
        """
        return 75.0

    async def generate_signal(self, market_data: pd.DataFrame, regime: str) -> Optional[StrategySignal]:
        try:
            if market_data.empty:
                return None
                
            # 1. Calculate Indicators (Lazy Loading based on Config)
            # Optimization: Only calc what is needed by the active conditions
            df = market_data.copy()
            
            # Helper to ensure indicators exist
            self._ensure_indicators(df, self.config['entry_conditions'])
            self._ensure_indicators(df, self.config['exit_conditions'])
            
            # 2. Check Entry Conditions
            entry_signal = self._evaluate_conditions(df, self.config['entry_conditions'])
            
            # 3. Check Exit Conditions (if we were managing position state here, but StrategyAgent handles state)
            # For now, we generates cues.
            # If entry_signal is True, we signal BUY.
            
            if entry_signal:
                return StrategySignal(
                    signal_id=f"UNI_{int(pd.Timestamp.now().timestamp())}",
                    strategy_name="UniversalStrategy",
                    symbol=self.config.get('symbol', 'UNKNOWN'),
                    signal_type="BUY", # Default to Long for MVP
                    strength=1.0,
                    metadata={"reason": "Universal Logic Match"},
                    market_regime_at_signal=regime
                )
                
            return None

        except Exception as e:
            logger.error(f"Universal Strategy Error: {e}")
            return None

    def _ensure_indicators(self, df: pd.DataFrame, conditions: List[Dict]):
        """
        Dynamically calculate indicators based on config.
        """
        # Pre-calc common ones to be safe, or parse config
        # For MVP, let's just calc standard suite
        # In Phase 7 optimization, we will parse 'period' from config
        
        # RSI
        if any(c['type'] == 'RSI' for c in conditions):
             # Extract period from first RSI cond (simplified)
            rsi_cond = next(c for c in conditions if c['type'] == 'RSI')
            period = rsi_cond.get('period', 14)
            df[f'RSI_{period}'] = ta.rsi(df['close'], length=period)
            
        # SMA / EMA
        # (Handling dynamic periods requires loop)
        for c in conditions:
            if c['type'] in ['SMA', 'EMA']:
                period = c.get('period', 20)
                if c['type'] == 'SMA':
                    df[f'SMA_{period}'] = ta.sma(df['close'], length=period)
                else:
                    df[f'EMA_{period}'] = ta.ema(df['close'], length=period)
                    
        # MACD
        if any(c['type'] == 'MACD' for c in conditions):
            macd = ta.macd(df['close'])
            df = pd.concat([df, macd], axis=1) # Adds MACD_12_26_9, MACDh_12_26_9, MACDs_12_26_9

    def _evaluate_conditions(self, df: pd.DataFrame, conditions: List[Dict]) -> bool:
        """
        Evaluate list of conditions. implicit AND logic.
        """
        if not conditions: 
            return False
            
        for c in conditions:
            # Get latest values
            current_idx = -1
            prev_idx = -2
            
            # RSI Logic
            if c['type'] == 'RSI':
                period = c.get('period', 14)
                col = f'RSI_{period}'
                if col not in df.columns: continue
                
                val = df[col].iloc[current_idx]
                threshold = c.get('value', 50)
                
                if c['condition'] == 'GT' and not (val > threshold): return False
                if c['condition'] == 'LT' and not (val < threshold): return False
                if c['condition'] == 'CROSS_ABOVE':
                    prev_val = df[col].iloc[prev_idx]
                    if not (prev_val <= threshold and val > threshold): return False
                if c['condition'] == 'CROSS_BELOW':
                    prev_val = df[col].iloc[prev_idx]
                    if not (prev_val >= threshold and val < threshold): return False

            # SMA/EMA Logic
            elif c['type'] in ['SMA', 'EMA']:
                period = c.get('period', 20)
                col = f"{c['type']}_{period}"
                if col not in df.columns: continue
                
                ind_val = df[col].iloc[current_idx]
                
                # Check what we are comparing against (Price or another value)
                comp_val = c.get('value', 0)
                if comp_val == 'CLOSE':
                    comp_val = df['close'].iloc[current_idx]
                    
                    # Special Cross Logic for Price vs MA
                    if c['condition'] == 'CROSS_ABOVE': # Price crosses above MA
                        # This means Price was < MA, now Price > MA
                        prev_price = df['close'].iloc[prev_idx]
                        prev_ma = df[col].iloc[prev_idx]
                        if not (prev_price <= prev_ma and df['close'].iloc[current_idx] > ind_val): return False
                        continue # Matched
                        
                if c['condition'] == 'GT' and not (ind_val > comp_val): return False
                # ... other operators ...

        return True # All passed
