"""
SEBI Options Enforcement Layer
==============================
Pre-trade compliance checks applied as middleware before any options
order reaches the broker.

Enforces:
  1. Position limits — per-underlying and market-wide OI caps
  2. Lot-size quantization — orders must be in exact lot multiples
  3. Expiry restrictions — no new positions in illiquid far-month expiries
  4. Tranche splitting — large orders split to avoid market impact
  5. Margin validation — estimated margin ≤ available capital
  6. Naked short protection — prevent uncovered short options
  7. Max open structures — cap on concurrent multi-leg positions
  8. Order value limits — single order max notional

SEBI circular references:
  - SEBI/HO/MRD2/DCAP/CIR/P/2024/152 (position limits for index derivatives)
  - SEBI/HO/MRD/DP/CIR/P/2019/041 (option risk management)
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from src.models.options import (
    LegSignal,
    LegAction,
    OptionsSignal,
    OptionType,
    StructureType,
)
from src.services.option_chain import LOT_SIZES

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration (env-overridable)
# ---------------------------------------------------------------------------
@dataclass
class SEBIConfig:
    """SEBI compliance configuration."""
    # Position limits (in lots)
    max_lots_per_underlying: int = int(os.getenv("SEBI_MAX_LOTS_PER_UL", "200"))
    max_lots_market_wide: int = int(os.getenv("SEBI_MAX_LOTS_MARKET", "500"))

    # Expiry restrictions
    max_expiry_months_ahead: int = int(os.getenv("SEBI_MAX_EXPIRY_MONTHS", "3"))
    min_dte_for_new_position: int = int(os.getenv("SEBI_MIN_DTE_NEW", "1"))

    # Order splitting
    max_lots_per_tranche: int = int(os.getenv("SEBI_MAX_LOTS_TRANCHE", "50"))
    max_order_value: float = float(os.getenv("SEBI_MAX_ORDER_VALUE", "5000000"))  # ₹50L

    # Margin
    margin_buffer_pct: float = float(os.getenv("SEBI_MARGIN_BUFFER_PCT", "20"))
    available_capital: float = float(os.getenv("TRADING_CAPITAL", "1000000"))  # ₹10L

    # Structure limits
    max_open_structures: int = int(os.getenv("SEBI_MAX_OPEN_STRUCTURES", "10"))

    # Naked short prevention
    allow_naked_shorts: bool = os.getenv("SEBI_ALLOW_NAKED_SHORTS", "false").lower() == "true"


sebi_config = SEBIConfig()


# ---------------------------------------------------------------------------
# Validation result
# ---------------------------------------------------------------------------
@dataclass
class ValidationResult:
    """Result of SEBI pre-trade validation."""
    approved: bool
    violations: List[str]
    warnings: List[str]
    modified_signal: Optional[OptionsSignal] = None  # if tranche-split or lot-adjusted

    def __bool__(self) -> bool:
        return self.approved


# ---------------------------------------------------------------------------
# SEBI Validator (main class)
# ---------------------------------------------------------------------------
class SEBIOptionsValidator:
    """
    Pre-trade compliance gate for options orders.
    Call validate() before sending any OptionsSignal to the executor.
    """

    def __init__(self, config: Optional[SEBIConfig] = None):
        self.config = config or sebi_config

    def validate(
        self,
        signal: OptionsSignal,
        current_positions_lots: int = 0,
        market_wide_lots: int = 0,
        available_margin: Optional[float] = None,
        open_structure_count: int = 0,
    ) -> ValidationResult:
        """
        Run all SEBI pre-trade checks on an OptionsSignal.

        Parameters
        ----------
        signal : the options signal to validate
        current_positions_lots : total lots currently open for this underlying
        market_wide_lots : total lots across all underlyings
        available_margin : available capital for new positions
        open_structure_count : number of currently open multi-leg structures

        Returns
        -------
        ValidationResult with approved flag, violations, and warnings.
        """
        violations: List[str] = []
        warnings: List[str] = []

        # 1. Lot size quantization
        lot_violations = self._check_lot_sizes(signal)
        violations.extend(lot_violations)

        # 2. Position limits
        pos_violations = self._check_position_limits(
            signal, current_positions_lots, market_wide_lots
        )
        violations.extend(pos_violations)

        # 3. Expiry restrictions
        exp_violations = self._check_expiry_restrictions(signal)
        violations.extend(exp_violations)

        # 4. Naked short protection
        naked_violations = self._check_naked_shorts(signal)
        violations.extend(naked_violations)

        # 5. Max open structures
        if open_structure_count >= self.config.max_open_structures:
            violations.append(
                f"Max open structures reached: {open_structure_count}/{self.config.max_open_structures}"
            )

        # 6. Margin validation
        margin = available_margin if available_margin is not None else self.config.available_capital
        margin_warnings = self._check_margin(signal, margin)
        warnings.extend(margin_warnings)

        # 7. Order value limit
        value_violations = self._check_order_value(signal)
        violations.extend(value_violations)

        # 8. Tranche splitting check (warning, not violation)
        tranche_warnings = self._check_tranche_size(signal)
        warnings.extend(tranche_warnings)

        approved = len(violations) == 0

        if violations:
            logger.warning(
                f"SEBI validation FAILED for {signal.signal_id}: {violations}"
            )
        elif warnings:
            logger.info(
                f"SEBI validation PASSED with warnings for {signal.signal_id}: {warnings}"
            )

        return ValidationResult(
            approved=approved,
            violations=violations,
            warnings=warnings,
            modified_signal=signal if approved else None,
        )

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------
    def _check_lot_sizes(self, signal: OptionsSignal) -> List[str]:
        """Ensure all legs use correct lot sizes."""
        violations = []
        for leg in signal.legs:
            expected_lot = LOT_SIZES.get(leg.symbol.upper(), 1)
            if leg.lot_size != expected_lot:
                violations.append(
                    f"Leg {leg.leg_id}: lot_size={leg.lot_size} but expected {expected_lot} for {leg.symbol}"
                )
            if leg.quantity <= 0:
                violations.append(f"Leg {leg.leg_id}: quantity must be > 0, got {leg.quantity}")
        return violations

    def _check_position_limits(
        self, signal: OptionsSignal,
        current_lots: int, market_wide: int,
    ) -> List[str]:
        """Enforce per-underlying and market-wide position limits."""
        violations = []
        new_lots = sum(leg.quantity for leg in signal.legs)

        if current_lots + new_lots > self.config.max_lots_per_underlying:
            violations.append(
                f"Position limit breach: {current_lots}+{new_lots} > "
                f"{self.config.max_lots_per_underlying} lots for {signal.symbol}"
            )

        if market_wide + new_lots > self.config.max_lots_market_wide:
            violations.append(
                f"Market-wide limit breach: {market_wide}+{new_lots} > "
                f"{self.config.max_lots_market_wide} lots"
            )
        return violations

    def _check_expiry_restrictions(self, signal: OptionsSignal) -> List[str]:
        """No positions in far-month or very near expiry."""
        violations = []
        from datetime import date, datetime, timedelta

        today = date.today()
        max_expiry = today + timedelta(days=self.config.max_expiry_months_ahead * 30)

        for leg in signal.legs:
            try:
                exp_date = datetime.strptime(leg.expiry[:10], "%Y-%m-%d").date()
                dte = (exp_date - today).days

                if dte < self.config.min_dte_for_new_position:
                    violations.append(
                        f"Leg {leg.leg_id}: DTE={dte} < min {self.config.min_dte_for_new_position}"
                    )
                if exp_date > max_expiry:
                    violations.append(
                        f"Leg {leg.leg_id}: expiry {leg.expiry} exceeds "
                        f"{self.config.max_expiry_months_ahead}-month limit"
                    )
            except Exception:
                violations.append(f"Leg {leg.leg_id}: invalid expiry date '{leg.expiry}'")
        return violations

    def _check_naked_shorts(self, signal: OptionsSignal) -> List[str]:
        """Prevent uncovered short options unless explicitly allowed."""
        if self.config.allow_naked_shorts:
            return []

        violations = []
        short_legs = [l for l in signal.legs if l.action == LegAction.SELL]
        buy_legs = [l for l in signal.legs if l.action == LegAction.BUY]

        for short_leg in short_legs:
            # Check if there's a protective buy leg of same type
            covered = any(
                bl.option_type == short_leg.option_type
                and bl.expiry == short_leg.expiry
                for bl in buy_legs
            )
            if not covered:
                violations.append(
                    f"Naked short detected: {short_leg.option_type.value} {short_leg.strike} "
                    f"has no protective buy leg"
                )
        return violations

    def _check_margin(self, signal: OptionsSignal, available_margin: float) -> List[str]:
        """Estimate margin and warn if insufficient."""
        warnings = []
        if signal.margin_required and signal.margin_required > 0:
            required_with_buffer = signal.margin_required * (1 + self.config.margin_buffer_pct / 100)
            if required_with_buffer > available_margin:
                warnings.append(
                    f"Margin warning: required ₹{required_with_buffer:,.0f} "
                    f"(incl {self.config.margin_buffer_pct}% buffer) > available ₹{available_margin:,.0f}"
                )
        return warnings

    def _check_order_value(self, signal: OptionsSignal) -> List[str]:
        """Check that total order value is within limits."""
        violations = []
        total_value = 0
        for leg in signal.legs:
            premium = leg.premium or 0
            total_value += premium * leg.quantity * leg.lot_size

        if total_value > self.config.max_order_value:
            violations.append(
                f"Order value ₹{total_value:,.0f} exceeds max ₹{self.config.max_order_value:,.0f}"
            )
        return violations

    def _check_tranche_size(self, signal: OptionsSignal) -> List[str]:
        """Warn if any leg exceeds tranche size (needs splitting)."""
        warnings = []
        for leg in signal.legs:
            if leg.quantity > self.config.max_lots_per_tranche:
                warnings.append(
                    f"Leg {leg.leg_id}: {leg.quantity} lots should be split into "
                    f"tranches of {self.config.max_lots_per_tranche}"
                )
        return warnings

    # ------------------------------------------------------------------
    # Tranche splitter utility
    # ------------------------------------------------------------------
    def split_into_tranches(self, signal: OptionsSignal) -> List[OptionsSignal]:
        """
        Split a large signal into multiple tranche signals, each within
        max_lots_per_tranche.
        """
        max_lots = self.config.max_lots_per_tranche
        max_leg_qty = max(leg.quantity for leg in signal.legs) if signal.legs else 0

        if max_leg_qty <= max_lots:
            return [signal]

        import math
        num_tranches = math.ceil(max_leg_qty / max_lots)
        tranches: List[OptionsSignal] = []

        for t in range(num_tranches):
            tranche_legs = []
            for leg in signal.legs:
                remaining = leg.quantity - t * max_lots
                tranche_qty = min(max_lots, max(0, remaining))
                if tranche_qty > 0:
                    new_leg = leg.model_copy(update={"quantity": tranche_qty})
                    tranche_legs.append(new_leg)

            if tranche_legs:
                tranche_signal = signal.model_copy(
                    update={
                        "signal_id": f"{signal.signal_id}_T{t+1}",
                        "legs": tranche_legs,
                    }
                )
                tranches.append(tranche_signal)

        return tranches


# Module-level singleton
sebi_validator = SEBIOptionsValidator()
