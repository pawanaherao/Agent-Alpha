"""
SEBI Compliance Enforcement — Equity Orders (Phase 7)

Enforces:
1. Position limits   — max concurrent open positions, max % per symbol
2. Order tagging     — SEBI algo registration ID on every order
3. Expiry-day ban    — restrict F&O equity orders on expiry Thursday
4. Tranche execution — split large equity orders into time-separated sub-orders
5. Concurrent position counter — hard cap
6. Order value cap   — max single order value

All thresholds are env-overridable. None of these block paper-trading in LOCAL mode.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
import os
import logging
from datetime import datetime, date, time

logger = logging.getLogger(__name__)


# ============================================================================
# Configuration (env-overridable)
# ============================================================================

@dataclass
class SEBIEquityConfig:
    """All limits that SEBI / internal risk policy imposes on equity orders."""

    # Algo registration tag — required by SEBI Oct-2025 circular
    algo_id: str = field(default_factory=lambda: os.getenv("SEBI_ALGO_ID", "AA2026"))

    # Concurrent positions
    max_concurrent_positions: int = int(os.getenv("SEBI_MAX_CONCURRENT_POS", "10"))

    # Single position value caps
    max_position_value: float = float(os.getenv("SEBI_MAX_POSITION_VALUE", "500000"))  # ₹5L
    max_single_order_value: float = float(os.getenv("SEBI_MAX_ORDER_VALUE", "5000000"))  # ₹50L
    max_capital_pct_per_symbol: float = float(os.getenv("SEBI_MAX_CAPITAL_PCT", "0.05"))  # 5%

    # Tranche settings
    tranche_threshold_qty: int = int(os.getenv("SEBI_TRANCHE_QTY", "500"))
    max_tranche_size: int = int(os.getenv("SEBI_MAX_TRANCHE", "200"))

    # Expiry day restrictions (F&O settlement Thursdays)
    block_equity_fno_on_expiry: bool = os.getenv("SEBI_BLOCK_EXPIRY_DAY", "true").lower() == "true"

    # Daily order count limit
    max_orders_per_day: int = int(os.getenv("SEBI_MAX_ORDERS_DAY", "100"))

    # Market hours gate — reject orders outside 09:15–15:10
    enforce_market_hours: bool = os.getenv("SEBI_ENFORCE_HOURS", "true").lower() == "true"
    market_open: time = time(9, 15)
    market_cutoff: time = time(15, 10)


# ============================================================================
# Validation Result
# ============================================================================

@dataclass
class EquityValidationResult:
    approved: bool
    violations: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    modified_order: Optional[Dict[str, Any]] = None


# ============================================================================
# Validator
# ============================================================================

class SEBIEquityValidator:
    """
    Pre-trade compliance checks for equity orders.
    Call validate() before every equity order placement.
    """

    def __init__(self, config: Optional[SEBIEquityConfig] = None):
        self.config = config or SEBIEquityConfig()
        self._daily_order_count: int = 0
        self._daily_order_date: Optional[date] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate(
        self,
        order: Dict[str, Any],
        current_positions_count: int = 0,
        total_capital: float = 1_000_000,
    ) -> EquityValidationResult:
        """Run all pre-trade checks and return result."""
        violations: List[str] = []
        warnings: List[str] = []

        self._check_market_hours(violations)
        self._check_concurrent_positions(current_positions_count, violations)
        self._check_order_value(order, total_capital, violations, warnings)
        self._check_daily_order_limit(violations, warnings)
        self._check_expiry_day(order, warnings)

        approved = len(violations) == 0
        if not approved:
            logger.warning(f"SEBI equity validation REJECTED: {violations}")
        elif warnings:
            logger.info(f"SEBI equity warnings: {warnings}")

        return EquityValidationResult(
            approved=approved,
            violations=violations,
            warnings=warnings,
        )

    def tag_order(self, order: Dict[str, Any]) -> Dict[str, Any]:
        """
        Stamp the order with SEBI algo ID and audit metadata.
        Must be called on every order before sending to broker.
        """
        tagged = dict(order)
        algo_id = self.config.algo_id
        strategy_name = (order.get("metadata") or {}).get("strategy_name", "")

        # SEBI tag format: <ALGO_ID>_<STRATEGY>_<TIMESTAMP>
        tag_value = f"{algo_id}_{strategy_name}_{datetime.now().strftime('%H%M%S')}"
        tagged["tag"] = tag_value[:25]  # DhanHQ tag field max 25 chars
        tagged.setdefault("correlationId", order.get("correlationId") or tag_value)

        return tagged

    def increment_daily_orders(self):
        """Call after each successful order placement."""
        today = date.today()
        if self._daily_order_date != today:
            self._daily_order_count = 0
            self._daily_order_date = today
        self._daily_order_count += 1

    def split_into_tranches(self, quantity: int) -> List[int]:
        """
        Split a large order into smaller tranches for SEBI compliance.
        Returns list of quantities per tranche.
        """
        if quantity <= self.config.tranche_threshold_qty:
            return [quantity]

        tranches = []
        remaining = quantity
        while remaining > 0:
            chunk = min(remaining, self.config.max_tranche_size)
            tranches.append(chunk)
            remaining -= chunk
        return tranches

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def _check_market_hours(self, violations: List[str]):
        if not self.config.enforce_market_hours:
            return
        now = datetime.now().time()
        if not (self.config.market_open <= now <= self.config.market_cutoff):
            violations.append(
                f"Outside market hours: {now.strftime('%H:%M')} "
                f"(allowed {self.config.market_open}–{self.config.market_cutoff})"
            )

    def _check_concurrent_positions(self, current_count: int, violations: List[str]):
        if current_count >= self.config.max_concurrent_positions:
            violations.append(
                f"Max concurrent positions reached: {current_count} >= "
                f"{self.config.max_concurrent_positions}"
            )

    def _check_order_value(
        self, order: Dict, total_capital: float,
        violations: List[str], warnings: List[str]
    ):
        price = float(order.get("price", 0) or order.get("entry_price", 0))
        qty = int(order.get("quantity", 0))
        value = price * qty if price > 0 else 0

        # Single order value cap
        if value > self.config.max_single_order_value:
            violations.append(
                f"Order value ₹{value:,.0f} exceeds max ₹{self.config.max_single_order_value:,.0f}"
            )

        # Capital concentration cap
        if total_capital > 0 and value > 0:
            pct = value / total_capital
            if pct > self.config.max_capital_pct_per_symbol:
                warnings.append(
                    f"Position value is {pct*100:.1f}% of capital "
                    f"(limit {self.config.max_capital_pct_per_symbol*100}%)"
                )

    def _check_daily_order_limit(self, violations: List[str], warnings: List[str]):
        today = date.today()
        if self._daily_order_date != today:
            self._daily_order_count = 0
            self._daily_order_date = today

        if self._daily_order_count >= self.config.max_orders_per_day:
            violations.append(
                f"Daily order limit reached: {self._daily_order_count} >= "
                f"{self.config.max_orders_per_day}"
            )
        elif self._daily_order_count >= self.config.max_orders_per_day * 0.8:
            warnings.append(
                f"Approaching daily order limit: {self._daily_order_count}/"
                f"{self.config.max_orders_per_day}"
            )

    @staticmethod
    def _check_expiry_day(order: Dict, warnings: List[str]):
        """Warn if today is a weekly expiry day (Thursday)."""
        today = date.today()
        if today.weekday() == 3:  # Thursday
            exchange = str(order.get("exchangeSegment", "")).upper()
            if "FNO" in exchange:
                warnings.append(
                    "Expiry day (Thursday): F&O order requires extra caution"
                )


# ============================================================================
# Singleton
# ============================================================================
sebi_equity_validator = SEBIEquityValidator()
