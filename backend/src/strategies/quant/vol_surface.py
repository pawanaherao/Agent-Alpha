import numpy as np
import pandas as pd
from scipy.interpolate import griddata, CubicSpline
from scipy.stats import norm
from scipy.optimize import brentq
import logging
import asyncio
from typing import Dict, List, Tuple, Any

from src.services.nse_data import nse_data_service

logger = logging.getLogger(__name__)

class VolSurfaceBuilder:
    """
    Volatility Surface Builder for Volatility Arbitrage.
    
    Logic:
    1. Fetch Option Chain
    2. Calculate Implied Volatility (IV) for each strike using Black-Scholes inverse
    3. Fit Volatility Smile (Curve) for each expiry
    4. Detect Anomalies (IV > Model + 2*Sigma) -> Short Candidates
    """
    def __init__(self, symbol: str = "NIFTY"):
        self.symbol = symbol
        self.risk_free_rate = 0.07  # India 10Y Bond Yield approx
        self.chain_data = {}
    
    async def build_surface(self):
        """
        Fetch option chain and build volatility surface model.
        B10 fix: Uses real parsed option chain data from get_option_chain().
        Returns a list of anomaly dicts (strike, expiry, market_iv, model_iv, type).
        """
        try:
            # 1. Fetch Option Chain (now returns real calls/puts with IVs)
            self.chain = await nse_data_service.get_option_chain(self.symbol)
            if not self.chain or 'data' not in self.chain:
                logger.warning(f"No option chain data for {self.symbol}")
                return []

            spot = self.chain.get('spot_price', 0)
            chain_data = self.chain.get('data', [])
            if spot == 0 or not chain_data:
                logger.warning(f"Empty chain or zero spot for {self.symbol}")
                return []

            anomalies = []

            # 2. Group data by expiry, then by option type (CE/PE)
            from collections import defaultdict
            expiry_groups: Dict[str, Dict[str, list]] = defaultdict(lambda: {"CE": [], "PE": []})
            for item in chain_data:
                exp = item.get("expiry", "unknown")
                otype = item.get("option_type", "CE")
                expiry_groups[exp][otype].append(item)

            # 3. Process each expiry
            for expiry, sides in expiry_groups.items():
                for option_type_label, items in sides.items():
                    if len(items) < 5:
                        continue  # need enough strikes to fit a curve

                    strikes = []
                    ivs = []
                    for item in items:
                        strike = item.get("strike", 0)
                        iv = item.get("implied_volatility", 0)
                        price = item.get("last_price", 0)

                        # If broker-provided IV is available, use it directly
                        if iv > 0.01:
                            strikes.append(strike)
                            ivs.append(iv)
                        elif price > 0 and strike > 0:
                            # Calculate IV from market price via Black-Scholes inverse
                            # Estimate T (time to expiry) — rough 7-day default for nearest
                            T = 7 / 365.0
                            calc_type = 'call' if option_type_label == 'CE' else 'put'
                            computed_iv = self.implied_volatility(price, spot, strike, T, self.risk_free_rate, calc_type)
                            if 0.01 < computed_iv < 2.0:
                                strikes.append(strike)
                                ivs.append(computed_iv)

                    if len(strikes) < 5:
                        continue

                    strikes_arr = np.array(strikes)
                    ivs_arr = np.array(ivs)

                    # 4. Fit Volatility Smile via Cubic Spline
                    sort_idx = np.argsort(strikes_arr)
                    strikes_sorted = strikes_arr[sort_idx]
                    ivs_sorted = ivs_arr[sort_idx]

                    try:
                        model = CubicSpline(strikes_sorted, ivs_sorted)
                    except Exception:
                        continue

                    # 5. Detect Anomalies — market IV > model IV + 2σ
                    residuals = ivs_sorted - model(strikes_sorted)
                    residual_std = np.std(residuals) if len(residuals) > 1 else 0.01
                    threshold = 2.0 * residual_std

                    for i, strike in enumerate(strikes_sorted):
                        model_iv = float(model(strike))
                        market_iv = float(ivs_sorted[i])
                        if market_iv > model_iv + threshold:
                            anomalies.append({
                                "symbol": self.symbol,
                                "expiry": expiry,
                                "strike": float(strike),
                                "option_type": option_type_label,
                                "market_iv": round(market_iv, 4),
                                "model_iv": round(model_iv, 4),
                                "deviation_sigma": round((market_iv - model_iv) / residual_std, 2),
                                "action": "SHORT",  # Overpriced — sell candidate
                                "spot_price": spot,
                            })

            logger.info(f"Vol surface built for {self.symbol}: {len(anomalies)} anomalies detected")
            return anomalies
            
        except Exception as e:
            logger.error(f"Surface build failed: {e}")
            return []

    def black_scholes_call(self, S, K, T, r, sigma):
        """Standard BS Call Price."""
        if T <= 0: return max(S - K, 0)
        d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
        d2 = d1 - sigma * np.sqrt(T)
        return S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)

    def implied_volatility(self, price, S, K, T, r, option_type='call'):
        """Calculate IV using Newton-Raphson or Brent's method."""
        if price <= 0: return 0.0
        
        def objective(sigma):
            if option_type == 'call':
                return self.black_scholes_call(S, K, T, r, sigma) - price
            else:
                # Put-Call Parity: P = C - S + K*e^(-rT)
                call_price = self.black_scholes_call(S, K, T, r, sigma)
                put_price = call_price - S + K * np.exp(-r * T)
                return put_price - price
        
        try:
            return brentq(objective, 0.01, 2.0) # Search IV between 1% and 200%
        except:
            return 0.0

if __name__ == "__main__":
    # Test Runner
    logging.basicConfig(level=logging.INFO)
    async def main():
        builder = VolSurfaceBuilder("NIFTY")
        # Test IV calc
        iv = builder.implied_volatility(150, 24000, 24200, 7/365, 0.07, 'call')
        print(f"Test IV: {iv:.2%}")
        
    asyncio.run(main())
