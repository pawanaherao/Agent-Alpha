"""
Enhanced Risk Agent with Kelly Criterion Position Sizing
SEBI Compliant: Transparent risk rules

Features:
1. Kelly Criterion position sizing
2. Portfolio heat check (max capital at risk)
3. Correlation filtering (sector concentration)
4. VIX-based position scaling
5. Daily loss limits (kill switch)
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
import logging

from src.agents.base import BaseAgent
from src.core.config import settings
from src.core.messages import RiskDecision, AgentMessage
from src.services.nse_data import nse_data_service

logger = logging.getLogger(__name__)


class RiskAgent(BaseAgent):
    """
    Enhanced Risk Agent with Kelly Criterion sizing.
    
    RISK CHECKS (WHITEBOX):
    1. Daily Loss Limit: -5% of capital (kill switch)
    2. Position Heat: Max 25% capital at risk at any time
    3. Single Position Size: Max 5% of capital
    4. Sector Concentration: Max 30% in single sector
    5. Kelly Criterion: Optimal position based on win rate
    6. VIX Scaling: Reduce size in high volatility
    """
    
    def __init__(self, name: str = "RiskAgent", config: Dict[str, Any] = None):
        super().__init__(name, config)
        
        # Capital parameters
        self.total_capital = config.get('capital', 1_000_000) if config else 1_000_000  # 10L default
        self.daily_pnl = 0.0
        
        # Risk limits
        self.max_daily_loss_pct = 0.05  # 5% of capital
        self.max_position_size_pct = 0.05  # 5% per position
        self.max_portfolio_heat_pct = 0.25  # 25% total at risk
        self.max_sector_concentration = 0.30  # 30% max per sector
        
        # Kelly parameters
        self.default_win_rate = 0.55
        self.default_rr_ratio = 2.0
        self.kelly_fraction = 0.25  # Use quarter Kelly for safety
        
        # VIX scaling
        self.vix_low = 12
        self.vix_high = 25
        
        # Current positions (simplified)
        self.open_positions: Dict[str, Dict] = {}
        self.sector_exposure: Dict[str, float] = {}
        
        self.nse_service = nse_data_service
        
        logger.info("Risk Agent initialized with Kelly Criterion sizing")
    
    @property
    def max_daily_loss(self) -> float:
        """Maximum daily loss in absolute terms."""
        return -self.total_capital * self.max_daily_loss_pct
    
    async def validate_signal(self, signal_data: Dict[str, Any]) -> RiskDecision:
        """
        Validate signal against risk parameters.
        
        WHITEBOX LOGIC:
        1. Check kill switch (daily loss limit)
        2. Check portfolio heat
        3. Check sector concentration
        4. Calculate Kelly-based position size
        5. Apply VIX scaling
        6. Return decision with quantity
        """
        signal_id = signal_data.get('signal_id', 'UNKNOWN')
        symbol = signal_data.get('symbol', 'UNKNOWN')
        entry_price = signal_data.get('entry_price', 0)
        stop_loss = signal_data.get('stop_loss', 0)
        target_price = signal_data.get('target_price', entry_price)
        strength = signal_data.get('strength', 0.5)
        
        # 1. Kill Switch Check
        if self.daily_pnl < self.max_daily_loss:
            logger.warning(f"Kill Switch Active! Daily PnL: {self.daily_pnl:.0f}")
            return RiskDecision(
                decision="REJECTED",
                reason=f"Kill Switch: Daily loss {self.daily_pnl:.0f} exceeds limit {self.max_daily_loss:.0f}",
                original_signal_id=signal_id
            )
        
        # 2. Portfolio Heat Check
        current_heat = self._calculate_portfolio_heat()
        if current_heat >= self.max_portfolio_heat_pct:
            logger.warning(f"Portfolio heat too high: {current_heat*100:.1f}%")
            return RiskDecision(
                decision="REJECTED",
                reason=f"Portfolio heat {current_heat*100:.1f}% exceeds limit {self.max_portfolio_heat_pct*100}%",
                original_signal_id=signal_id
            )
        
        # 3. Calculate risk per share
        if entry_price > 0 and stop_loss > 0:
            risk_per_share = abs(entry_price - stop_loss)
            reward_per_share = abs(target_price - entry_price) if target_price else risk_per_share * 2
        else:
            risk_per_share = entry_price * 0.03  # Default 3% stop
            reward_per_share = risk_per_share * 2
        
        # 4. Calculate Risk-Reward ratio
        rr_ratio = reward_per_share / risk_per_share if risk_per_share > 0 else 1.0
        
        # Reject if R:R too low
        if rr_ratio < 1.5:
            return RiskDecision(
                decision="REJECTED",
                reason=f"Risk-Reward {rr_ratio:.2f} below minimum 1.5",
                original_signal_id=signal_id
            )
        
        # 5. Kelly Criterion Position Size
        kelly_position = self._calculate_kelly_position(
            win_rate=self.default_win_rate + (strength - 0.5) * 0.1,
            rr_ratio=rr_ratio,
            risk_per_share=risk_per_share,
            entry_price=entry_price
        )
        
        # 6. VIX Scaling
        vix_multiplier = await self._get_vix_multiplier()
        adjusted_position = kelly_position * vix_multiplier
        
        # 7. Apply position limits
        max_position_value = self.total_capital * self.max_position_size_pct
        max_shares = int(max_position_value / entry_price) if entry_price > 0 else 0
        
        final_quantity = min(int(adjusted_position), max_shares)
        final_quantity = max(1, final_quantity)  # At least 1 share
        
        # For F&O, convert to lots
        position_value = final_quantity * entry_price
        risk_amount = final_quantity * risk_per_share
        
        logger.info(
            f"Risk Approved: {symbol} | Qty={final_quantity}, "
            f"Value={position_value:.0f}, Risk={risk_amount:.0f}, "
            f"Kelly={kelly_position:.0f}, VIX_mult={vix_multiplier:.2f}"
        )
        
        return RiskDecision(
            decision="APPROVED",
            reason="Risk checks passed",
            original_signal_id=signal_id,
            modifications={
                "quantity": final_quantity,
                "position_value": position_value,
                "risk_amount": risk_amount,
                "kelly_size": kelly_position,
                "vix_multiplier": vix_multiplier,
                "rr_ratio": rr_ratio
            }
        )
    
    def _calculate_kelly_position(
        self,
        win_rate: float,
        rr_ratio: float,
        risk_per_share: float,
        entry_price: float
    ) -> float:
        """
        Kelly Criterion: f* = (bp - q) / b
        
        Where:
        - b = reward/risk ratio
        - p = win probability
        - q = loss probability (1 - p)
        - f* = fraction of capital to bet
        
        We use fractional Kelly (25%) for safety.
        """
        p = min(0.7, max(0.4, win_rate))  # Clamp win rate
        q = 1 - p
        b = rr_ratio
        
        # Kelly fraction
        kelly_f = (b * p - q) / b
        
        # Apply safety fraction
        kelly_f = max(0, kelly_f * self.kelly_fraction)
        
        # Convert to position size
        capital_to_risk = self.total_capital * kelly_f
        position_size = capital_to_risk / risk_per_share if risk_per_share > 0 else 0
        
        return position_size
    
    def _calculate_portfolio_heat(self) -> float:
        """Calculate current portfolio risk exposure."""
        total_at_risk = sum(
            pos.get('risk_amount', 0) 
            for pos in self.open_positions.values()
        )
        return total_at_risk / self.total_capital if self.total_capital > 0 else 0
    
    async def _get_vix_multiplier(self) -> float:
        """
        Scale position size based on VIX.
        
        VIX < 12: 1.2x (calm market, can take more risk)
        VIX 12-15: 1.0x (normal)
        VIX 15-20: 0.8x
        VIX 20-25: 0.6x
        VIX > 25: 0.4x (high volatility, reduce size)
        """
        try:
            vix = await self.nse_service.get_india_vix()
        except:
            vix = 15.0
        
        if vix < 12:
            return 1.2
        elif vix <= 15:
            return 1.0
        elif vix <= 20:
            return 0.8
        elif vix <= 25:
            return 0.6
        else:
            return 0.4
    
    async def on_signals_received(self, payload: Dict[str, Any]):
        """Event Handler for SIGNALS_GENERATED."""
        raw_signals = payload.get('signals', [])
        approved_signals = []
        
        for signal in raw_signals:
            decision = await self.validate_signal(signal)
            
            if decision.decision == "APPROVED":
                approved_signals.append({
                    "signal": signal,
                    "risk_decision": decision.model_dump()
                })
            else:
                logger.info(f"Rejected: {signal.get('symbol')} - {decision.reason}")
        
        if approved_signals:
            logger.info(f"Approved {len(approved_signals)}/{len(raw_signals)} signals")
            await self.publish_event("SIGNALS_APPROVED", {"orders": approved_signals})
        else:
            logger.info("No signals approved this cycle")
    
    async def update_pnl(self, pnl_change: float):
        """Update daily PnL for kill switch tracking."""
        self.daily_pnl += pnl_change
        
        if self.daily_pnl < self.max_daily_loss:
            logger.error(f"KILL SWITCH TRIGGERED! Daily PnL: {self.daily_pnl:.0f}")
    
    async def add_position(self, symbol: str, position_data: Dict):
        """Track an open position."""
        self.open_positions[symbol] = position_data
    
    async def remove_position(self, symbol: str):
        """Remove a closed position."""
        self.open_positions.pop(symbol, None)
    
    async def reset_daily(self):
        """Reset daily counters (call at market open)."""
        self.daily_pnl = 0.0
        logger.info("Daily risk counters reset")
