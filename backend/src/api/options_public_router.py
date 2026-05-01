from fastapi import APIRouter

from src.core.config import settings
from src.core.runtime_context import get_runtime_value
from src.services.options_policy_snapshot import build_policy_snapshot


router = APIRouter()


@router.get("/options/positions")
async def options_positions():
    """All open options multi-leg positions with aggregated Greeks & P&L."""
    agent_manager = get_runtime_value("agent_manager")
    portfolio_agent = agent_manager.agents.get("portfolio") if agent_manager else None
    if portfolio_agent and getattr(portfolio_agent, "simulated_positions", None):
        open_positions = [
            position for position in portfolio_agent.simulated_positions.values()
            if position.get("position_type") == "OPTIONS" and position.get("status") == "OPEN"
        ]
        if open_positions:
            total_upnl = sum(float(position.get("unrealized_pnl", 0) or 0) for position in open_positions)
            total_rpnl = sum(float(position.get("realized_pnl", 0) or 0) for position in open_positions)
            agg_delta = sum(float(position.get("delta", 0) or 0) for position in open_positions)
            agg_gamma = sum(float(position.get("gamma", 0) or 0) for position in open_positions)
            agg_theta = sum(float(position.get("theta", 0) or 0) for position in open_positions)
            agg_vega = sum(float(position.get("vega", 0) or 0) for position in open_positions)
            return {
                "open_positions": len(open_positions),
                "total_positions": len(portfolio_agent.simulated_positions),
                "unrealized_pnl": round(total_upnl, 2),
                "realized_pnl": round(total_rpnl, 2),
                "portfolio_greeks": {
                    "delta": round(agg_delta, 4),
                    "gamma": round(agg_gamma, 6),
                    "theta": round(agg_theta, 4),
                    "vega": round(agg_vega, 4),
                },
                "positions": [
                    {
                        "position_id": position_id,
                        "symbol": position.get("symbol"),
                        "structure_type": position.get("structure_type"),
                        "strategy_name": position.get("strategy_name"),
                        "legs": position.get("legs", []),
                        "legs_count": position.get("legs_count", len(position.get("legs", []))),
                        "net_premium": position.get("net_premium"),
                        "entry_premium": position.get("entry_premium"),
                        "current_premium": position.get("current_premium"),
                        "entry_price": position.get("entry_price"),
                        "unrealized_pnl": position.get("unrealized_pnl"),
                        "greeks": {
                            "delta": position.get("delta"),
                            "gamma": position.get("gamma"),
                            "theta": position.get("theta"),
                            "vega": position.get("vega"),
                        },
                        "entry_time": position.get("entry_time"),
                        "status": position.get("status"),
                        "simulated": position.get("simulated", True),
                        "policy_snapshot": build_policy_snapshot(position),
                    }
                    for position_id, position in portfolio_agent.simulated_positions.items()
                    if position.get("position_type") == "OPTIONS" and position.get("status") == "OPEN"
                ],
                "source": "simulated_positions",
            }

    from src.services.options_position_manager import options_position_manager

    summary = options_position_manager.portfolio_summary()
    summary["source"] = "options_position_manager"
    return summary


@router.get("/options/chain/{symbol}")
async def options_chain(symbol: str, num_strikes: int = 10, greeks: bool = True):
    """Live option chain with Greeks for a symbol."""
    from src.services.option_chain import option_chain_service

    chain = None
    try:
        chain = await option_chain_service.get_chain(
            symbol,
            num_strikes=num_strikes,
            enrich_greeks=greeks,
        )
        raw_items = list(getattr(chain, "items", []) or [])
        return {
            "symbol": getattr(chain, "symbol", symbol),
            "spot_price": getattr(chain, "spot_price", None),
            "expiry_dates": list(getattr(chain, "expiry_dates", []) or []),
            "atm_strike": getattr(chain, "atm_strike", None),
            "items_count": len(raw_items),
            "items": [item.dict() for item in raw_items[:50]],
        }
    except Exception as exc:
        raw_items = list(getattr(chain, "items", []) or []) if chain else []
        return {
            "symbol": getattr(chain, "symbol", symbol),
            "spot_price": getattr(chain, "spot_price", None),
            "expiry_dates": list(getattr(chain, "expiry_dates", []) or []),
            "atm_strike": getattr(chain, "atm_strike", None),
            "items_count": len(raw_items),
            "items": [],
            "error": str(exc),
        }


@router.get("/options/greeks/{position_id}")
async def options_greeks(position_id: str):
    """Greeks snapshot for a specific options position."""
    from src.services.greeks import greeks_engine
    from src.services.options_position_manager import options_position_manager

    position = options_position_manager.get_position(position_id)
    if not position:
        return {"error": f"Position {position_id} not found"}

    try:
        portfolio_greeks = greeks_engine.portfolio_greeks(position.legs)
        greeks_payload = portfolio_greeks.dict() if portfolio_greeks else {}
    except Exception as exc:
        greeks_payload = {}
        error = str(exc)

    return {
        "position_id": position_id,
        "greeks": greeks_payload,
        "legs": len(position.legs),
        "status": position.status.value if hasattr(position.status, "value") else str(position.status),
        **({"error": error} if 'error' in locals() else {}),
    }


@router.get("/options/validate")
async def options_validate_sebi():
    """Health check for SEBI options validator."""
    from src.middleware.sebi_options import sebi_validator

    cfg = sebi_validator.config
    return {
        "validator": "SEBIOptionsValidator",
        "enabled": settings.OPTIONS_ENABLED,
        "max_lots_per_ul": cfg.max_lots_per_underlying,
        "max_open_structures": cfg.max_open_structures,
        "margin_buffer_pct": cfg.margin_buffer_pct,
    }