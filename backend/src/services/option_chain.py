"""
Option Chain Data Pipeline
==========================
Enhanced option-chain service that returns strikes, premiums, IV, OI, and Greeks.

Data sources (3-tier, same pattern as NSEDataService):
  Tier 1 — DhanHQ real-time API (optionchain endpoint / market quotes)
  Tier 2 — nselib (NSE website scrape)
  Tier 3 — yfinance (Yahoo Finance, nearest expiry only)

Returns OptionChain / OptionChainItem pydantic models that downstream
strategies and the GreeksEngine can consume directly.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, date, timedelta
from typing import Any, Dict, List, Optional

from src.models.options import OptionChain, OptionChainItem, OptionType, Greeks
from src.services.greeks import greeks_engine

logger = logging.getLogger(__name__)

# Lot sizes for major indices / stocks (SEBI-defined, updated periodically)
LOT_SIZES: Dict[str, int] = {
    # ── Indices ──
    "NIFTY": 25,
    "NIFTY 50": 25,
    "BANKNIFTY": 15,
    "FINNIFTY": 25,
    "MIDCPNIFTY": 50,
    # ── Banking & Finance ──
    "HDFCBANK": 550,
    "ICICIBANK": 700,
    "AXISBANK": 1200,
    "KOTAKBANK": 400,
    "SBIN": 1500,
    "INDUSINDBK": 500,
    "FEDERALBNK": 10000,
    "IDFCFIRSTB": 14000,
    "PNB": 8000,
    "CANBK": 4700,
    "BANKBARODA": 3850,
    "UNIONBANK": 8400,
    "BAJFINANCE": 125,
    "BAJAJFINSV": 50,
    "MUTHOOTFIN": 750,
    "CHOLAFIN": 1250,
    "M&MFIN": 3000,
    "HDFCLIFE": 1100,
    "SBILIFE": 750,
    "ICICIGI": 200,
    "ICICIPRULI": 1500,
    "LICI": 700,
    # ── IT & Technology ──
    "TCS": 150,
    "INFY": 300,
    "WIPRO": 1600,
    "HCLTECH": 700,
    "TECHM": 600,
    "LTIM": 150,
    "MPHASIS": 175,
    "COFORGE": 100,
    "PERSISTENT": 125,
    "OFSS": 200,
    # ── Energy & Power ──
    "RELIANCE": 250,
    "ONGC": 3850,
    "NTPC": 3000,
    "POWERGRID": 3850,
    "TATAPOWER": 3375,
    "ADANIGREEN": 250,
    "ADANIENT": 250,
    "ADANIPORTS": 1250,
    "ADANIPOWER": 2500,
    "CESC": 4000,
    "TORNTPOWER": 750,
    # ── FMCG ──
    "HINDUNILVR": 300,
    "ITC": 1600,
    "NESTLEIND": 40,
    "BRITANNIA": 200,
    "DABUR": 2750,
    "MARICO": 1200,
    "COLPAL": 700,
    "TATACONSUM": 1400,
    "GODREJCP": 1000,
    # ── Automobile ──
    "MARUTI": 100,
    "TATAMOTORS": 1400,
    "M&M": 700,
    "BAJAJ-AUTO": 125,
    "HEROMOTOCO": 300,
    "EICHERMOT": 150,
    "ASHOKLEY": 5000,
    "BALKRISIND": 250,
    "MRF": 10,
    # ── Pharma & Healthcare ──
    "SUNPHARMA": 700,
    "DRREDDY": 125,
    "CIPLA": 650,
    "DIVISLAB": 200,
    "LUPIN": 850,
    "AUROPHARMA": 1000,
    "BIOCON": 2400,
    "ALKEM": 100,
    "GLENMARK": 1150,
    "IPCALAB": 250,
    "APOLLOHOSP": 125,
    "FORTIS": 3200,
    "MAXHEALTH": 800,
    # ── Metals & Mining ──
    "TATASTEEL": 5500,
    "HINDALCO": 2150,
    "JSWSTEEL": 1350,
    "SAIL": 9500,
    "VEDL": 2000,
    "NATIONALUM": 7500,
    "NMDC": 6250,
    "COALINDIA": 4200,
    # ── Capital Goods / Industrials ──
    "LT": 375,
    "SIEMENS": 275,
    "ABB": 125,
    "BEL": 5500,
    "HAL": 150,
    "BHEL": 6500,
    "RVNL": 5000,
    "IRFC": 8000,
    "IRCTC": 875,
    # ── Telecom ──
    "BHARTIARTL": 950,
    # ── Cement ──
    "ULTRACEMCO": 100,
    "SHREECEM": 25,
    "AMBUJACEM": 2500,
    "ACC": 500,
    # ── Real Estate ──
    "DLF": 1650,
    "GODREJPROP": 650,
    "OBEROIRLTY": 1050,
    "PRESTIGE": 2000,
    "PHOENIXLTD": 900,
    "SOBHA": 600,
    "BRIGADE": 1200,
    # ── Consumer Durables / Retail ──
    "TITAN": 375,
    "TRENT": 275,
    "DMART": 150,
    "NYKAA": 9375,
    "ZOMATO": 4800,
    "PAYTM": 2000,
    # ── Others ──
    "ASIANPAINT": 250,
    "PIDILITIND": 700,
    "SRF": 125,
    "POLYCAB": 150,
    "HAVELLS": 1000,
    "DIXON": 75,
    "INDIGO": 300,
    "MANAPPURAM": 5000,
    "ANGELONE": 250,
    "BSE": 400,
}

# Strike step per underlying (smallest step between strikes at nearest ATM)
STRIKE_STEPS: Dict[str, float] = {
    # ── Indices ──
    "NIFTY": 50,
    "NIFTY 50": 50,
    "BANKNIFTY": 100,
    "FINNIFTY": 50,
    "MIDCPNIFTY": 25,
    # ── High-price stocks — 50 or 100 rs steps ──
    "RELIANCE": 50,
    "TCS": 50,
    "HDFCBANK": 50,
    "INFY": 50,
    "ICICIBANK": 50,
    "BAJFINANCE": 100,
    "MRF": 500,
    "MARUTI": 100,
    "NESTLEIND": 100,
    "SHREECEM": 500,
    # ── Mid/low-price stocks — 5 or 10 rs steps ──
    "SBIN": 5,
    "TATAMOTORS": 5,
    "ITC": 5,
    "AXISBANK": 10,
    "KOTAKBANK": 50,
    "WIPRO": 5,
    "BHARTIARTL": 10,
    "TATASTEEL": 5,
    "INDUSINDBK": 10,
    "PNB": 2,
    "CANBK": 2,
    "BANKBARODA": 2,
}
DEFAULT_STRIKE_STEP = 50


def _time_to_expiry_years(expiry_str: str) -> float:
    """Convert expiry ISO date string to years remaining."""
    try:
        exp_date = datetime.strptime(expiry_str[:10], "%Y-%m-%d").date()
        days = (exp_date - date.today()).days
        return max(days, 1) / 365.0
    except Exception:
        return 7 / 365.0  # fallback 1 week


class OptionChainService:
    """
    Unified option chain fetcher.
    Returns an OptionChain model enriched with Greeks from GreeksEngine.
    """

    def __init__(self):
        self._cache: Dict[str, OptionChain] = {}
        self._cache_ts: Dict[str, datetime] = {}
        self._cache_ttl_seconds = int(os.getenv("OPTION_CHAIN_CACHE_TTL", "60"))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def get_chain(
        self,
        symbol: str,
        expiry: Optional[str] = None,
        num_strikes: int = 10,
        enrich_greeks: bool = True,
    ) -> OptionChain:
        """
        Fetch option chain for *symbol*.

        Parameters
        ----------
        symbol : underlying symbol (e.g. "NIFTY", "BANKNIFTY", "RELIANCE")
        expiry : ISO date "YYYY-MM-DD" or None for nearest
        num_strikes : number of strikes above/below ATM to fetch
        enrich_greeks : compute Greeks via BS model if True

        Returns
        -------
        OptionChain with items populated (may be empty if all tiers fail).
        """
        cache_key = f"{symbol}:{expiry or 'nearest'}:{num_strikes}"
        if cache_key in self._cache:
            ts = self._cache_ts.get(cache_key, datetime.min)
            if (datetime.now() - ts).total_seconds() < self._cache_ttl_seconds:
                return self._cache[cache_key]

        chain = await self._fetch_chain(symbol, expiry, num_strikes)

        if enrich_greeks and chain.items and chain.spot_price > 0:
            chain = self._enrich_with_greeks(chain)

        self._cache[cache_key] = chain
        self._cache_ts[cache_key] = datetime.now()
        return chain

    async def get_multi_expiry_chain(
        self,
        symbol: str,
        num_expiries: int = 3,
        num_strikes: int = 10,
    ) -> OptionChain:
        """Fetch chains for multiple expiries and merge into one OptionChain."""
        # First get expiry list from base chain
        base = await self.get_chain(symbol, expiry=None, num_strikes=num_strikes, enrich_greeks=False)
        if not base.expiry_dates:
            return base

        expiries = base.expiry_dates[:num_expiries]
        all_items: List[OptionChainItem] = []
        for exp in expiries:
            c = await self.get_chain(symbol, expiry=exp, num_strikes=num_strikes, enrich_greeks=False)
            all_items.extend(c.items)

        merged = OptionChain(
            symbol=symbol,
            spot_price=base.spot_price,
            expiry_dates=expiries,
            items=all_items,
        )
        if merged.items and merged.spot_price > 0:
            merged = self._enrich_with_greeks(merged)
        return merged

    # ------------------------------------------------------------------
    # Tier cascade
    # ------------------------------------------------------------------
    async def _fetch_chain(self, symbol: str, expiry: Optional[str], num_strikes: int) -> OptionChain:
        """Try Tier 1 → 2 → 3."""
        chain = await self._fetch_tier1_dhan(symbol, expiry, num_strikes)
        if chain and chain.items:
            logger.info(f"Option chain for {symbol}: Tier 1 (DhanHQ) — {len(chain.items)} items")
            return chain

        chain = await self._fetch_tier2_nselib(symbol, expiry, num_strikes)
        if chain and chain.items:
            logger.info(f"Option chain for {symbol}: Tier 2 (nselib) — {len(chain.items)} items")
            return chain

        chain = await self._fetch_tier3_yfinance(symbol, expiry, num_strikes)
        if chain and chain.items:
            logger.info(f"Option chain for {symbol}: Tier 3 (yfinance) — {len(chain.items)} items")
            return chain

        logger.warning(f"All tiers failed for {symbol} option chain")
        return OptionChain(symbol=symbol, spot_price=0.0)

    # ------------------------------------------------------------------
    # Tier 1 — DhanHQ
    # ------------------------------------------------------------------
    async def _fetch_tier1_dhan(self, symbol: str, expiry: Optional[str], num_strikes: int) -> Optional[OptionChain]:
        """
        Use DhanHQ option chain endpoint.
        Requires DHAN_ACCESS_TOKEN and security master for underlying.
        """
        try:
            from src.services.dhan_client import get_dhan_client
            dhan = get_dhan_client()
            if not dhan.dhan:
                return None

            # Resolve underlying security for the option chain request
            if not dhan._load_security_master():
                return None
            df = dhan.security_master
            sym_upper = symbol.upper().strip()

            # Get spot price from equity / index
            # For indices use "NIFTY 50" → search FUTIDX for spot proxy
            # For now, use yfinance for spot (DhanHQ doesn't have a direct spot endpoint for indices)
            spot = 0.0
            try:
                from src.services.nse_data import nse_data_service
                ohlc = await nse_data_service.get_stock_ohlc(symbol, period="1D")
                if not ohlc.empty and "close" in ohlc.columns:
                    spot = float(ohlc["close"].iloc[-1])
            except Exception:
                pass

            if spot <= 0:
                return None

            # Get option instruments from security master
            opt_df = df[
                (df["SEM_INSTRUMENT_NAME"].astype(str).str.upper().isin(["OPTIDX", "OPTSTK"]))
                & (df["SEM_TRADING_SYMBOL"].astype(str).str.upper().str.startswith(sym_upper))
            ].copy()

            if opt_df.empty:
                return None

            opt_df["_expiry"] = pd.to_datetime(opt_df["SEM_EXPIRY_DATE"], errors="coerce")
            opt_df = opt_df[opt_df["_expiry"] >= datetime.now()].sort_values("_expiry")

            if opt_df.empty:
                return None

            # Filter to requested expiry or nearest
            expiry_dates = sorted(opt_df["_expiry"].dropna().unique())
            expiry_dates_str = [d.strftime("%Y-%m-%d") for d in expiry_dates[:5]]

            if expiry:
                target_exp = pd.to_datetime(expiry)
                opt_df = opt_df[opt_df["_expiry"] == target_exp]
            else:
                opt_df = opt_df[opt_df["_expiry"] == expiry_dates[0]]

            if opt_df.empty:
                return None

            # Filter to strikes around ATM
            step = STRIKE_STEPS.get(sym_upper, DEFAULT_STRIKE_STEP)
            atm = round(spot / step) * step
            strikes_wanted = [atm + i * step for i in range(-num_strikes, num_strikes + 1)]

            opt_df["_strike"] = pd.to_numeric(opt_df["SEM_STRIKE_PRICE"], errors="coerce")
            opt_df = opt_df[opt_df["_strike"].isin(strikes_wanted)]

            lot_size = LOT_SIZES.get(sym_upper, int(float(opt_df["SEM_LOT_UNITS"].iloc[0])) if "SEM_LOT_UNITS" in opt_df.columns and not opt_df.empty else 1)

            items: List[OptionChainItem] = []
            exp_str = expiry or expiry_dates_str[0] if expiry_dates_str else ""
            for _, row in opt_df.iterrows():
                otype_raw = str(row.get("SEM_OPTION_TYPE", "")).upper()
                if otype_raw not in ("CE", "PE"):
                    continue
                strike = float(row["_strike"])
                items.append(OptionChainItem(
                    symbol=symbol,
                    strike=strike,
                    option_type=OptionType(otype_raw),
                    expiry=exp_str,
                    lot_size=lot_size,
                    in_the_money=(strike < spot if otype_raw == "CE" else strike > spot),
                ))

            return OptionChain(
                symbol=symbol,
                spot_price=spot,
                expiry_dates=expiry_dates_str,
                items=items,
            )
        except Exception as e:
            logger.debug(f"Tier 1 (DhanHQ) option chain failed: {e}")
            return None

    # ------------------------------------------------------------------
    # Tier 2 — nselib
    # ------------------------------------------------------------------
    async def _fetch_tier2_nselib(self, symbol: str, expiry: Optional[str], num_strikes: int) -> Optional[OptionChain]:
        """Use nselib to scrape NSE option chain page."""
        try:
            import nselib
            loop = asyncio.get_event_loop()
            raw = await loop.run_in_executor(
                None, nselib.derivatives.nse_live_option_chain, symbol
            )
            if raw is None or (hasattr(raw, 'empty') and raw.empty):
                return None

            import pandas as pd
            if isinstance(raw, pd.DataFrame):
                return self._parse_nselib_df(raw, symbol, expiry, num_strikes)
            return None
        except Exception as e:
            logger.debug(f"Tier 2 (nselib) option chain failed: {e}")
            return None

    def _parse_nselib_df(self, df, symbol: str, expiry: Optional[str], num_strikes: int) -> Optional[OptionChain]:
        """Parse nselib DataFrame into OptionChain model."""
        try:
            import pandas as pd
            # nselib returns columns like: strikePrice, expiryDate, CE_lastPrice, PE_lastPrice, etc.
            spot = 0.0
            if "underlyingValue" in df.columns:
                spot = float(df["underlyingValue"].iloc[0])

            items: List[OptionChainItem] = []
            lot_size = LOT_SIZES.get(symbol.upper(), 1)
            step = STRIKE_STEPS.get(symbol.upper(), DEFAULT_STRIKE_STEP)
            atm = round(spot / step) * step if spot > 0 else 0

            for _, row in df.iterrows():
                strike = float(row.get("strikePrice", 0))
                if num_strikes and spot > 0:
                    if abs(strike - atm) > num_strikes * step:
                        continue
                exp_val = str(row.get("expiryDate", ""))
                if expiry and exp_val != expiry:
                    continue

                # CE side
                ce_price = float(row.get("CE_lastPrice", 0) or 0)
                ce_oi = int(row.get("CE_openInterest", 0) or 0)
                ce_vol = int(row.get("CE_totalTradedVolume", 0) or 0)
                ce_iv = float(row.get("CE_impliedVolatility", 0) or 0) / 100.0  # nselib gives %
                if ce_price > 0 or ce_oi > 0:
                    items.append(OptionChainItem(
                        symbol=symbol, strike=strike, option_type=OptionType.CE,
                        expiry=exp_val, last_price=ce_price, volume=ce_vol,
                        open_interest=ce_oi, iv=ce_iv, lot_size=lot_size,
                        in_the_money=strike < spot,
                    ))

                # PE side
                pe_price = float(row.get("PE_lastPrice", 0) or 0)
                pe_oi = int(row.get("PE_openInterest", 0) or 0)
                pe_vol = int(row.get("PE_totalTradedVolume", 0) or 0)
                pe_iv = float(row.get("PE_impliedVolatility", 0) or 0) / 100.0
                if pe_price > 0 or pe_oi > 0:
                    items.append(OptionChainItem(
                        symbol=symbol, strike=strike, option_type=OptionType.PE,
                        expiry=exp_val, last_price=pe_price, volume=pe_vol,
                        open_interest=pe_oi, iv=pe_iv, lot_size=lot_size,
                        in_the_money=strike > spot,
                    ))

            expiry_dates = sorted(set(i.expiry for i in items))
            return OptionChain(symbol=symbol, spot_price=spot, expiry_dates=expiry_dates, items=items)
        except Exception as e:
            logger.debug(f"nselib parse error: {e}")
            return None

    # ------------------------------------------------------------------
    # Tier 3 — yfinance
    # ------------------------------------------------------------------
    async def _fetch_tier3_yfinance(self, symbol: str, expiry: Optional[str], num_strikes: int) -> Optional[OptionChain]:
        """
        Fallback: yfinance option chain (nearest expiry only unless expiry specified).
        """
        try:
            import yfinance as yf
            loop = asyncio.get_event_loop()
            sym_map = {"NIFTY": "^NSEI", "NIFTY 50": "^NSEI", "BANKNIFTY": "^NSEBANK"}
            yf_sym = sym_map.get(symbol.upper(), f"{symbol.upper()}.NS")
            ticker = yf.Ticker(yf_sym)

            # Get expiry dates
            exp_dates = await loop.run_in_executor(None, lambda: ticker.options)
            if not exp_dates:
                return None
            expiry_dates_str = list(exp_dates[:5])

            target_exp = expiry or expiry_dates_str[0]
            chain_data = await loop.run_in_executor(None, lambda: ticker.option_chain(target_exp))
            if chain_data is None:
                return None

            calls_df, puts_df = chain_data.calls, chain_data.puts
            info = await loop.run_in_executor(None, lambda: ticker.info)
            spot = float(info.get("regularMarketPrice", 0) or info.get("previousClose", 0))

            lot_size = LOT_SIZES.get(symbol.upper(), 1)
            step = STRIKE_STEPS.get(symbol.upper(), DEFAULT_STRIKE_STEP)
            atm = round(spot / step) * step if spot > 0 else 0

            items: List[OptionChainItem] = []

            for _, row in calls_df.iterrows():
                strike = float(row.get("strike", 0))
                if num_strikes and spot > 0 and abs(strike - atm) > num_strikes * step:
                    continue
                items.append(OptionChainItem(
                    symbol=symbol, strike=strike, option_type=OptionType.CE,
                    expiry=target_exp,
                    last_price=float(row.get("lastPrice", 0) or 0),
                    bid=float(row.get("bid", 0) or 0),
                    ask=float(row.get("ask", 0) or 0),
                    volume=int(row.get("volume", 0) or 0),
                    open_interest=int(row.get("openInterest", 0) or 0),
                    iv=float(row.get("impliedVolatility", 0) or 0),
                    lot_size=lot_size,
                    in_the_money=bool(row.get("inTheMoney", False)),
                ))

            for _, row in puts_df.iterrows():
                strike = float(row.get("strike", 0))
                if num_strikes and spot > 0 and abs(strike - atm) > num_strikes * step:
                    continue
                items.append(OptionChainItem(
                    symbol=symbol, strike=strike, option_type=OptionType.PE,
                    expiry=target_exp,
                    last_price=float(row.get("lastPrice", 0) or 0),
                    bid=float(row.get("bid", 0) or 0),
                    ask=float(row.get("ask", 0) or 0),
                    volume=int(row.get("volume", 0) or 0),
                    open_interest=int(row.get("openInterest", 0) or 0),
                    iv=float(row.get("impliedVolatility", 0) or 0),
                    lot_size=lot_size,
                    in_the_money=bool(row.get("inTheMoney", False)),
                ))

            return OptionChain(symbol=symbol, spot_price=spot, expiry_dates=expiry_dates_str, items=items)
        except Exception as e:
            logger.debug(f"Tier 3 (yfinance) option chain failed: {e}")
            return None

    # ------------------------------------------------------------------
    # Greeks enrichment
    # ------------------------------------------------------------------
    def _enrich_with_greeks(self, chain: OptionChain) -> OptionChain:
        """Compute Greeks for every item in the chain."""
        for item in chain.items:
            T = _time_to_expiry_years(item.expiry)
            greeks_engine.enrich_chain_item(item, chain.spot_price, T)
        return chain


# ---------------------------------------------------------------------------
# Need pandas for Tier 1 parsing
# ---------------------------------------------------------------------------
try:
    import pandas as pd
except ImportError:
    pd = None  # type: ignore


# Module-level singleton
option_chain_service = OptionChainService()
