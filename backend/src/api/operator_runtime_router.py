from datetime import date

from fastapi import APIRouter, Depends

from src.core.config import settings
from src.core.runtime_context import get_runtime_context
from src.database.postgres import db
from src.middleware.auth import require_api_key
from src.services.options_policy_snapshot import build_policy_snapshot


router = APIRouter(tags=["operator-runtime"])


def _get_agent_manager():
    try:
        return get_runtime_context().get("agent_manager")
    except Exception:
        return None


@router.get("/ai/status", dependencies=[Depends(require_api_key)])
async def ai_status():
    """Unified AI layer status - ai_router, Vertex availability, budgets, and architecture."""
    from src.services.ai_cost_tracker import ai_cost_tracker as ai_cost_tracker
    from src.services.ai_router import ai_router
    from src.services.vertex_ai_client import vertex_ai_client

    ai_router_status = {}
    try:
        await ai_router.initialize()
    except Exception as exc:
        ai_router_status = {
            "initialized": False,
            "initialize_error": str(exc),
        }

    try:
        _status = ai_router.get_status() or {}
        if isinstance(_status, dict):
            ai_router_status = {**_status, **ai_router_status}
        elif not ai_router_status:
            ai_router_status = {"status": str(_status)}
    except Exception as exc:
        ai_router_status = {**ai_router_status, "error": str(exc)}

    if not ai_router_status:
        ai_router_status = {"error": "ai_router status unavailable"}

    try:
        vertex_status = vertex_ai_client.status()
    except Exception as exc:
        vertex_status = {
            "available": False,
            "error": str(exc),
        }

    try:
        cost_status = ai_cost_tracker.get_status()
    except Exception as exc:
        cost_status = {
            "error": str(exc),
        }

    return {
        "ai_router": ai_router_status,
        "vertex_ai": vertex_status,
        "cost_tracker": cost_status,
        "architecture": {
            "design": "Unified ai_router boundary with Vertex primary and local fallback",
            "project": "agent-alpha1",
            "region": "asia-south1 (Mumbai - min latency to DhanHQ/Kotak Neo)",
            "agents_using_ai": [
                {"agent": "SentimentAgent", "role": "VADER + Gemini sentiment scoring (news headlines)"},
                {"agent": "ScannerAgent", "role": "Gemini counter-validation on filtered shortlist"},
                {"agent": "StrategyAgent", "role": "Gemini AVOID/PASS signal gate after confluence filter"},
                {"agent": "ExecutionAgent", "role": "Gemini plain-English HYBRID approval card generation"},
                {"agent": "OptionChainScanner", "role": "Gemini options structure rationale (advisory only)"},
            ],
            "fallback_when_unavailable": "VADER rules / deterministic scoring - all agents work without AI",
        },
    }


@router.get("/positions", dependencies=[Depends(require_api_key)])
async def get_positions():
    """Live broker positions (broker-agnostic via factory). In paper mode, merges simulated positions."""
    from src.services.broker_factory import get_broker_client

    def _attach_policy_snapshot(position):
        if not isinstance(position, dict):
            return position
        try:
            policy_snapshot = build_policy_snapshot(position)
        except Exception:
            policy_snapshot = None
        return {
            **position,
            "policy_snapshot": policy_snapshot,
        }

    agent_manager = _get_agent_manager()
    broker_name = "unknown"
    try:
        client = get_broker_client()
        try:
            broker_name = client.broker_name()
        except Exception:
            broker_name = "unknown"

        try:
            positions = await client.get_positions()
        except Exception:
            positions = []
    except Exception:
        positions = []

    if not positions and settings.PAPER_TRADING:
        try:
            portfolio_agent = agent_manager.agents.get("portfolio")
            if portfolio_agent and portfolio_agent.simulated_positions:
                positions = [
                    _attach_policy_snapshot(position)
                    for position in portfolio_agent.simulated_positions.values()
                    if position.get("status") == "OPEN"
                    and not (
                        position.get("position_type") == "OPTIONS"
                        and int(position.get("net_qty") or position.get("quantity") or 0) == 0
                        and str(position.get("order_id", "")).startswith("SIM_OPT_")
                    )
                ]
        except Exception:
            pass

    positions = [_attach_policy_snapshot(position) for position in positions]

    return {
        "positions": positions,
        "count": len(positions),
        "broker": broker_name,
        "paper_trading": settings.PAPER_TRADING,
    }


@router.get("/closed_positions", dependencies=[Depends(require_api_key)])
async def get_closed_positions():
    """Closed or exited simulated positions with exit metadata."""
    agent_manager = _get_agent_manager()
    agents = getattr(agent_manager, "agents", {}) if agent_manager else {}
    portfolio_agent = agents.get("portfolio") if isinstance(agents, dict) else None
    if not portfolio_agent or not getattr(portfolio_agent, "simulated_positions", None):
        return {"closed_positions": [], "count": 0}

    closed = [
        {
            "position_id": position_id,
            "symbol": position.get("symbol"),
            "side": position.get("side"),
            "quantity": position.get("quantity"),
            "entry_price": position.get("entry_price"),
            "exit_price": position.get("exit_price"),
            "entry_time": position.get("entry_time"),
            "exit_time": position.get("exit_time"),
            "exit_reason": position.get("exit_reason", "UNKNOWN"),
            "trailing_sl": position.get("trailing_sl", False),
            "realized_pnl": position.get("realized_pnl"),
            "product_type": position.get("product_type"),
            "position_type": position.get("position_type"),
            "strategy_name": position.get("strategy_name"),
        }
        for position_id, position in portfolio_agent.simulated_positions.items()
        if position.get("status") == "CLOSED"
    ]
    return {"closed_positions": closed, "count": len(closed)}


@router.get("/trades", dependencies=[Depends(require_api_key)])
async def get_trades():
    """Today's filled trades (broker-agnostic via factory)."""
    from src.services.broker_factory import get_broker_client

    broker_name = "unknown"
    try:
        client = get_broker_client()
        try:
            broker_name = client.broker_name()
        except Exception:
            broker_name = "unknown"

        try:
            trades = await client.get_trades()
        except Exception:
            trades = []
    except Exception:
        trades = []
    return {"trades": trades, "count": len(trades), "broker": broker_name}


@router.get("/pnl", dependencies=[Depends(require_api_key)])
async def get_pnl():
    """Today's PnL summary from the daily_pnl table."""
    try:
        if db.pool is None:
            return {"error": "database not connected"}
        today = date.today()
        async with db.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM daily_pnl WHERE trade_date = $1", today)
        if row:
            return dict(row)
        return {"trade_date": str(today), "realized_pnl": 0, "unrealized_pnl": 0}
    except Exception as exc:
        return {"error": str(exc)}