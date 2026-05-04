import asyncio
import datetime as dt
import logging

from fastapi import APIRouter, Request


logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/api/options/expiries")
async def get_option_expiries(symbol: str = "NIFTY"):
    """
    Return list of active option expiry dates from DhanHQ.

    Falls back to generated weekly Thursdays when DhanHQ is unavailable.
    """
    import datetime as _dt

    try:
        from src.services.dhan_client import get_dhan_client

        dhan_client = get_dhan_client()
        if dhan_client.is_connected():
            expiries = await dhan_client.get_expiry_list(symbol.upper())
            if expiries:
                return {"symbol": symbol.upper(), "expiries": expiries, "source": "dhan"}
    except Exception as exc:
        logger.debug(f"DhanHQ expiry list for {symbol}: {exc}")

    today = _dt.date.today()
    days_ahead = (3 - today.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    thursdays = []
    base = today + _dt.timedelta(days=days_ahead)
    for index in range(8):
        thursdays.append(str(base + _dt.timedelta(weeks=index)))
    return {"symbol": symbol.upper(), "expiries": thursdays, "source": "generated"}


@router.get("/api/options/dhan-chain")
async def get_dhan_option_chain(symbol: str = "NIFTY", expiry: str = "", atm_range: int = 10):
    """DhanHQ native option chain with greeks, OI, and IV."""
    import datetime as _dt

    sym = symbol.upper()
    exp = expiry.strip()
    try:
        from src.services.dhan_client import get_dhan_client

        dhan_client = get_dhan_client()
        if not exp:
            expiries = await dhan_client.get_expiry_list(sym)
            exp = expiries[0] if expiries else str(
                _dt.date.today() + _dt.timedelta(days=((3 - _dt.date.today().weekday()) % 7) or 7)
            )

        raw = await dhan_client.get_option_chain_native(sym, exp)
    except Exception as exc:
        logger.error(f"DhanHQ option chain error for {sym}/{exp}: {exc}")
        raw = {}

    if not raw:
        return {
            "symbol": sym,
            "expiry": exp,
            "spot_price": 0,
            "atm_strike": 0,
            "strikes": [],
            "count": 0,
            "source": "unavailable",
        }

    try:
        spot = float(raw.get("last_price", 0))
        option_chain = raw.get("oc", {})
        all_strikes_raw = sorted(option_chain.keys(), key=lambda strike: float(strike))

        if spot > 0 and all_strikes_raw:
            atm = min(all_strikes_raw, key=lambda strike: abs(float(strike) - spot))
            atm_idx = all_strikes_raw.index(atm)
            low = max(0, atm_idx - atm_range)
            high = min(len(all_strikes_raw), atm_idx + atm_range + 1)
            selected = all_strikes_raw[low:high]
        else:
            selected = all_strikes_raw[:40]
            atm = selected[len(selected) // 2] if selected else "0"

        def _parse_leg(leg: dict) -> dict:
            greeks = leg.get("greeks", {})
            return {
                "ltp": round(float(leg.get("last_price", 0)), 2),
                "iv": round(float(leg.get("implied_volatility", 0)), 4),
                "oi": int(leg.get("oi", 0)),
                "volume": int(leg.get("volume", 0)),
                "delta": round(float(greeks.get("delta", 0)), 4),
                "gamma": round(float(greeks.get("gamma", 0)), 6),
                "theta": round(float(greeks.get("theta", 0)), 4),
                "vega": round(float(greeks.get("vega", 0)), 4),
                "bid": round(float(leg.get("top_bid_price", 0)), 2),
                "ask": round(float(leg.get("top_ask_price", 0)), 2),
                "prev_oi": round(float(leg.get("previous_oi", 0)), 0),
            }

        strikes_out = []
        for strike in selected:
            entry = option_chain.get(strike, {})
            ce = _parse_leg(entry.get("ce", {}))
            pe = _parse_leg(entry.get("pe", {}))
            strikes_out.append({"strike": float(strike), "ce": ce, "pe": pe})

        return {
            "symbol": sym,
            "expiry": exp,
            "spot_price": spot,
            "atm_strike": float(atm),
            "strikes": strikes_out,
            "count": len(strikes_out),
            "source": "dhan",
        }
    except Exception as exc:
        logger.error(f"DhanHQ option chain parse error for {sym}/{exp}: {exc}")
        return {
            "symbol": sym,
            "expiry": exp,
            "spot_price": 0,
            "atm_strike": 0,
            "strikes": [],
            "count": 0,
            "source": "unavailable",
            "error": str(exc),
        }


@router.get("/api/options/vp-context")
async def get_vp_options_context_endpoint(
    symbol: str = "NIFTY",
    expiry_type: str = "auto",
    tf_override: str = "",
    expiry: str = "",
):
    """Return VP+OI precision context for options strategy strike selection."""
    from src.services.vp_options_bridge import get_vp_options_context

    try:
        ctx = await get_vp_options_context(
            symbol=symbol,
            expiry_type=expiry_type,
            tf_override=tf_override or None,
            expiry=expiry or None,
        )
        return {
            "symbol": ctx.symbol,
            "expiry_type": ctx.expiry_type,
            "expiry": ctx.expiry,
            "dte": ctx.dte,
            "spot": ctx.spot,
            "vp_timeframe": ctx.vp_timeframe,
            "vp_timeframe_override": ctx.vp_timeframe_override,
            "poc": ctx.poc,
            "vah": ctx.vah,
            "val": ctx.val,
            "profile_shape": ctx.profile_shape,
            "vp_range": ctx.vp_range,
            "spot_in_vp_pct": ctx.spot_in_vp_pct,
            "vp_zone": ctx.vp_zone,
            "precision_ceiling": ctx.precision_ceiling,
            "precision_floor": ctx.precision_floor,
            "max_pain": ctx.max_pain,
            "pcr": ctx.pcr,
            "iv_skew": ctx.iv_skew,
            "atm_iv": ctx.atm_iv,
            "sell_ce": ctx.sell_ce,
            "buy_ce": ctx.buy_ce,
            "sell_pe": ctx.sell_pe,
            "buy_pe": ctx.buy_pe,
            "strike_step": ctx.strike_step,
            "suggested_structure": ctx.suggested_structure,
            "structure_rationale": ctx.structure_rationale,
            "confluence_score": ctx.confluence_score,
            "ce_wall_oi": ctx.ce_wall_oi,
            "pe_wall_oi": ctx.pe_wall_oi,
            "data_source": ctx.data_source,
            "ce_walls": ctx.ce_walls,
            "pe_walls": ctx.pe_walls,
        }
    except Exception as exc:
        logger.error(f"/api/options/vp-context error for {symbol}: {exc}")
        return {"error": str(exc), "symbol": symbol}


@router.post("/api/options-scan")
async def options_scan_route(request: Request):
    """Execute the 2-layer F&O options scanner and return strategy decisions."""
    from src.strategies.options_setup_scanner import FnOSetupScanner, run_two_layer_scan

    try:
        body = await request.json()
    except Exception:
        body = {}

    fno_universe = body.get("universe") or None

    try:
        from src.services.nse_data import NSEDataService

        data_service = NSEDataService()
        universe = fno_universe or FnOSetupScanner()._default_fno_universe()
        market_data_map = {}
        for symbol in universe[:40]:
            try:
                history = await data_service.get_historical_data(symbol, period="1y", interval="1d")
                if history is not None and len(history) >= 20:
                    market_data_map[symbol] = history
            except Exception:
                pass
    except Exception:
        market_data_map = {}

    try:
        decisions = await asyncio.wait_for(
            run_two_layer_scan(market_data_map, fno_universe=fno_universe),
            timeout=45.0,
        )
    except asyncio.TimeoutError:
        logger.warning("/api/options-scan timed out after 45s — returning empty")
        return []
    except Exception as exc:
        logger.error(f"/api/options-scan error: {exc}")
        return []

    out = []
    for decision in decisions:
        atm_strike = decision.legs[0]["strike"] if decision.legs else 0
        out.append(
            {
                "symbol": decision.symbol,
                "structure": decision.structure,
                "score": int(round(decision.confidence * 100)),
                "ivRank": round(decision.iv_rank, 1),
                "atmIv": round(decision.iv_rank * 0.38, 1),
                "pcr": 1.0,
                "atmStrike": atm_strike,
                "spot": 0.0,
                "expiry": decision.legs[0].get("expiry", str(dt.date.today() + dt.timedelta(days=7))) if decision.legs else "",
                "geminiAdvisory": decision.rationale[:120] if decision.rationale else None,
                "riskProfile": decision.risk_profile,
                "legs": decision.legs,
            }
        )

    return out