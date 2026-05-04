from datetime import datetime
import time

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from src.core.agent_manager import (
    NSE_MARKET_CLOSE,
    NSE_MARKET_OPEN,
    is_market_day,
    is_market_open,
)
from src.core.config import settings
from src.core.metrics import metrics
from src.core.runtime_context import get_runtime_value
from src.database.postgres import db
from src.database.redis import cache


router = APIRouter()

_HEALTH_SNAPSHOT_TTL_S = 1.0
_health_snapshot_expires_at = 0.0
_health_snapshot_payload = None


def _get_health_snapshot_now() -> float:
    return time.monotonic()


def _build_health_payload():
    from src.services.vertex_ai_client import vertex_ai_client as vertex_ai_client

    vtx_status = {}
    try:
        status_fn = getattr(vertex_ai_client, "status", None)
        if callable(status_fn):
            vtx_status = status_fn() or {}
    except Exception:
        vtx_status = {}

    active = vtx_status.get("available")
    if active is None:
        try:
            active = vertex_ai_client.is_available()
        except Exception:
            active = False

    agent_manager = get_runtime_value("agent_manager")
    return {
        "status": "healthy",
        "mode": settings.MODE,
        "market_open": is_market_open(),
        "agents_running": bool(getattr(agent_manager, "is_running", False)),
        "database": "connected" if getattr(db, "pool", None) else "disconnected",
        "redis": "connected" if getattr(cache, "client", None) else "disconnected",
        "vertex_ai": {
            "active": bool(active),
            "project": vtx_status.get("project", getattr(vertex_ai_client, "_project", None)),
            "location": vtx_status.get("location", getattr(vertex_ai_client, "_location", None)),
            "model": vtx_status.get("default_model", getattr(vertex_ai_client, "_default_model_name", None)),
        },
    }


@router.get("/health")
async def health_check():
    global _health_snapshot_expires_at, _health_snapshot_payload

    now = _get_health_snapshot_now()
    if _health_snapshot_payload is not None and now < _health_snapshot_expires_at:
        return _health_snapshot_payload

    payload = _build_health_payload()
    _health_snapshot_payload = payload
    _health_snapshot_expires_at = now + _HEALTH_SNAPSHOT_TTL_S
    return payload


@router.get("/metrics", response_class=PlainTextResponse)
async def prometheus_metrics():
    """Prometheus scrape endpoint — returns all metrics in text exposition format."""
    try:
        return metrics.export()
    except Exception as exc:
        return f"# metrics export unavailable: {exc}"


@router.get("/api/risk/win-rate-by-regime")
async def win_rate_by_regime():
    """
    Return per-strategy-regime and day-type win rates tracked by RiskAgent.

    Used by the dashboard analytics tile to show how each strategy performs
    in different market regimes (BULL/BEAR/SIDEWAYS/VOLATILE) and VIX day-types.
    """
    agent_manager = get_runtime_value("agent_manager")
    risk_agent = agent_manager.agents.get("risk") if agent_manager else None
    if not risk_agent:
        return {"strategy_regime": {}, "day_type": {}}

    strategy_regime_win_rates = getattr(risk_agent, "_strategy_regime_win_rates", {})
    strategy_regime_trade_counts = getattr(risk_agent, "_strategy_regime_trade_counts", {})
    strategy_regime = [
        {
            "strategy": key[0],
            "regime": key[1],
            "win_rate": round(float(value) * 100, 1),
            "trades": strategy_regime_trade_counts.get(key, 0),
        }
        for key, value in strategy_regime_win_rates.items()
    ]
    strategy_regime.sort(key=lambda item: (-item["trades"], item["strategy"]))

    day_type_win_rates = getattr(risk_agent, "_day_type_win_rates", {})
    day_type_trade_counts = getattr(risk_agent, "_day_type_trade_counts", {})
    day_type = [
        {
            "day_type": key,
            "win_rate": round(float(value) * 100, 1),
            "trades": day_type_trade_counts.get(key, 0),
        }
        for key, value in day_type_win_rates.items()
    ]
    day_type.sort(key=lambda item: -item["trades"])

    return {"strategy_regime": strategy_regime, "day_type": day_type}


@router.get("/market-status")
async def market_status():
    """NSE market open/closed status."""
    now = datetime.now()
    return {
        "market_open": is_market_open(now),
        "is_trading_day": is_market_day(now.date()),
        "server_time": now.isoformat(),
        "trading_start": str(NSE_MARKET_OPEN),
        "trading_end": str(NSE_MARKET_CLOSE),
    }