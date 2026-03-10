"""
Greeks Calculator
=================
Full Black-Scholes Greeks engine for Indian equity/index options.
Produces per-leg and portfolio-level delta, gamma, theta, vega, rho.

Wires into the VolSurfaceBuilder BS math and adds analytic Greek formulas.
"""
from __future__ import annotations

import math
import logging
from typing import List, Optional

import numpy as np
from scipy.stats import norm

from src.models.options import (
    Greeks,
    LegSignal,
    LegPosition,
    MultiLegPosition,
    OptionType,
    LegAction,
    OptionChainItem,
)

logger = logging.getLogger(__name__)

# India 10-yr government bond yield (approximate)
DEFAULT_RISK_FREE_RATE = 0.07
# Dividend yield for NIFTY (approximate)
DEFAULT_DIVIDEND_YIELD = 0.012


class GreeksEngine:
    """
    Analytic Black-Scholes Greeks calculator for European options.
    Supports call (CE) and put (PE).
    All annualised; theta returned as daily decay (÷365).
    """

    def __init__(
        self,
        risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
        dividend_yield: float = DEFAULT_DIVIDEND_YIELD,
    ):
        self.r = risk_free_rate
        self.q = dividend_yield

    # ------------------------------------------------------------------
    # Core BS helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _d1(S: float, K: float, T: float, r: float, q: float, sigma: float) -> float:
        if T <= 0 or sigma <= 0:
            return 0.0
        return (math.log(S / K) + (r - q + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))

    @staticmethod
    def _d2(d1: float, sigma: float, T: float) -> float:
        if T <= 0 or sigma <= 0:
            return 0.0
        return d1 - sigma * math.sqrt(T)

    # ------------------------------------------------------------------
    # Price
    # ------------------------------------------------------------------
    def bs_price(
        self, S: float, K: float, T: float, sigma: float,
        option_type: str = "CE",
    ) -> float:
        """Black-Scholes option price (European)."""
        if T <= 0:
            if option_type == "CE":
                return max(S - K, 0.0)
            return max(K - S, 0.0)
        d1 = self._d1(S, K, T, self.r, self.q, sigma)
        d2 = self._d2(d1, sigma, T)
        if option_type == "CE":
            return (S * math.exp(-self.q * T) * norm.cdf(d1)
                    - K * math.exp(-self.r * T) * norm.cdf(d2))
        else:
            return (K * math.exp(-self.r * T) * norm.cdf(-d2)
                    - S * math.exp(-self.q * T) * norm.cdf(-d1))

    # ------------------------------------------------------------------
    # Individual Greeks
    # ------------------------------------------------------------------
    def delta(self, S: float, K: float, T: float, sigma: float, option_type: str = "CE") -> float:
        if T <= 0 or sigma <= 0:
            if option_type == "CE":
                return 1.0 if S > K else 0.0
            return -1.0 if S < K else 0.0
        d1 = self._d1(S, K, T, self.r, self.q, sigma)
        if option_type == "CE":
            return math.exp(-self.q * T) * norm.cdf(d1)
        return -math.exp(-self.q * T) * norm.cdf(-d1)

    def gamma(self, S: float, K: float, T: float, sigma: float) -> float:
        if T <= 0 or sigma <= 0 or S <= 0:
            return 0.0
        d1 = self._d1(S, K, T, self.r, self.q, sigma)
        return (math.exp(-self.q * T) * norm.pdf(d1)) / (S * sigma * math.sqrt(T))

    def theta(self, S: float, K: float, T: float, sigma: float, option_type: str = "CE") -> float:
        """Daily theta (negative = time decay costs money for long positions)."""
        if T <= 0 or sigma <= 0:
            return 0.0
        d1 = self._d1(S, K, T, self.r, self.q, sigma)
        d2 = self._d2(d1, sigma, T)
        sqrt_T = math.sqrt(T)
        common = -(S * math.exp(-self.q * T) * norm.pdf(d1) * sigma) / (2 * sqrt_T)
        if option_type == "CE":
            annual = (common
                      + self.q * S * math.exp(-self.q * T) * norm.cdf(d1)
                      - self.r * K * math.exp(-self.r * T) * norm.cdf(d2))
        else:
            annual = (common
                      - self.q * S * math.exp(-self.q * T) * norm.cdf(-d1)
                      + self.r * K * math.exp(-self.r * T) * norm.cdf(-d2))
        return annual / 365.0  # daily

    def vega(self, S: float, K: float, T: float, sigma: float) -> float:
        """Vega per 1% move in IV (i.e. / 100)."""
        if T <= 0 or sigma <= 0:
            return 0.0
        d1 = self._d1(S, K, T, self.r, self.q, sigma)
        return S * math.exp(-self.q * T) * norm.pdf(d1) * math.sqrt(T) / 100.0

    def rho(self, S: float, K: float, T: float, sigma: float, option_type: str = "CE") -> float:
        """Rho per 1% rate change."""
        if T <= 0 or sigma <= 0:
            return 0.0
        d1 = self._d1(S, K, T, self.r, self.q, sigma)
        d2 = self._d2(d1, sigma, T)
        if option_type == "CE":
            return K * T * math.exp(-self.r * T) * norm.cdf(d2) / 100.0
        return -K * T * math.exp(-self.r * T) * norm.cdf(-d2) / 100.0

    # ------------------------------------------------------------------
    # Implied Volatility
    # ------------------------------------------------------------------
    def implied_volatility(
        self, price: float, S: float, K: float, T: float,
        option_type: str = "CE", tol: float = 1e-6, max_iter: int = 100,
    ) -> float:
        """Newton-Raphson IV solver."""
        if price <= 0 or T <= 0:
            return 0.0
        sigma = 0.20  # initial guess
        for _ in range(max_iter):
            bs_p = self.bs_price(S, K, T, sigma, option_type)
            v = self.vega(S, K, T, sigma) * 100  # un-scale vega
            if abs(v) < 1e-12:
                break
            sigma -= (bs_p - price) / v
            sigma = max(0.001, min(sigma, 5.0))
            if abs(bs_p - price) < tol:
                break
        return sigma

    # ------------------------------------------------------------------
    # Bulk: compute all Greeks for a single option
    # ------------------------------------------------------------------
    def compute_all(
        self, S: float, K: float, T: float, sigma: float,
        option_type: str = "CE",
    ) -> Greeks:
        """Compute all Greeks at once and return a Greeks model."""
        return Greeks(
            delta=self.delta(S, K, T, sigma, option_type),
            gamma=self.gamma(S, K, T, sigma),
            theta=self.theta(S, K, T, sigma, option_type),
            vega=self.vega(S, K, T, sigma),
            rho=self.rho(S, K, T, sigma, option_type),
            iv=sigma,
        )

    # ------------------------------------------------------------------
    # Enrich chain items with Greeks
    # ------------------------------------------------------------------
    def enrich_chain_item(
        self, item: OptionChainItem, spot: float, T: float,
    ) -> OptionChainItem:
        """Compute / refresh Greeks for an OptionChainItem."""
        sigma = item.iv if item.iv > 0.01 else self.implied_volatility(
            item.last_price, spot, item.strike, T, item.option_type.value
        )
        item.greeks = self.compute_all(spot, item.strike, T, sigma, item.option_type.value)
        item.iv = sigma
        return item

    # ------------------------------------------------------------------
    # Portfolio-level Greeks aggregation
    # ------------------------------------------------------------------
    def portfolio_greeks(self, legs: List[LegPosition], spot: float) -> Greeks:
        """
        Aggregate Greeks across all open legs of a multi-leg position.
        Each leg's Greeks are multiplied by its signed contract count.
        """
        total = Greeks()
        for leg in legs:
            if leg.status != "OPEN":
                continue
            sign = 1 if leg.action == LegAction.BUY else -1
            contracts = leg.quantity * leg.lot_size
            g = leg.greeks
            total.delta += g.delta * contracts * sign
            total.gamma += g.gamma * contracts * sign
            total.theta += g.theta * contracts * sign
            total.vega += g.vega * contracts * sign
            total.rho += g.rho * contracts * sign
        return total

    def refresh_leg_greeks(
        self, leg: LegPosition, spot: float, T: float,
    ) -> LegPosition:
        """Re-compute Greeks for a single LegPosition using current market."""
        sigma = leg.greeks.iv if leg.greeks.iv > 0.01 else 0.2
        # If we have a current premium, re-solve IV
        if leg.current_premium > 0:
            sigma = self.implied_volatility(
                leg.current_premium, spot, leg.strike, T, leg.option_type.value
            )
        leg.greeks = self.compute_all(spot, leg.strike, T, sigma, leg.option_type.value)
        return leg


# Module-level singleton
greeks_engine = GreeksEngine()
