import logging

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from src.core.config import settings
from src.core.runtime_context import get_runtime_value
from src.database.redis import cache


logger = logging.getLogger(__name__)
router = APIRouter()

EXECUTION_MODE_OPTIONS = ["MANUAL", "HYBRID", "AUTO"]


def _execution_mode_config_payload(mode: str = "AUTO", error: str | None = None) -> dict:
    payload = {
        "mode": mode,
        "options": EXECUTION_MODE_OPTIONS,
        "hybrid_threshold": 0.8,
        "description": {
            "MANUAL": "All trades require user approval",
            "HYBRID": "Auto-execute if signal strength > 80%, else user approval",
            "AUTO": "All trades execute automatically without user approval",
        },
    }
    if error:
        payload["error"] = error
    return payload


def _execution_mode_update_payload(mode: str, error: str | None = None) -> dict:
    payload = {
        "success": error is None,
        "mode": mode,
        "message": (
            f"Execution mode set to {mode}"
            if error is None
            else f"Execution mode update to {mode} failed"
        ),
    }
    if error:
        payload["error"] = error
        payload["detail"] = error
    return payload


class ExecutionModeBody(BaseModel):
    mode: str = ""


@router.get("/api/trading/execution-mode")
async def get_execution_mode():
    """Get current execution mode (MANUAL, HYBRID, AUTO)."""
    try:
        agent_manager = get_runtime_value("agent_manager")
        exec_agent = agent_manager.agents.get("execution") if agent_manager else None
        mode = exec_agent.mode if exec_agent else "AUTO"
        return _execution_mode_config_payload(mode=mode)
    except Exception as exc:
        logger.error(f"Failed to get execution mode: {exc}")
        return _execution_mode_config_payload(error=str(exc))


@router.post("/api/trading/execution-mode")
async def set_execution_mode(mode: str = "", body: ExecutionModeBody = Body(default_factory=ExecutionModeBody)):
    """Set execution mode (MANUAL, HYBRID, AUTO)."""
    effective_mode = (mode or body.mode or "").upper()
    if effective_mode not in EXECUTION_MODE_OPTIONS:
        error = f"Invalid mode. Must be one of: {EXECUTION_MODE_OPTIONS}"
        return JSONResponse(status_code=400, content={"error": error, "detail": error})

    try:
        agent_manager = get_runtime_value("agent_manager")
        exec_agent = agent_manager.agents.get("execution") if agent_manager else None
        if exec_agent:
            exec_agent.mode = effective_mode
            await cache.set("execution_mode", effective_mode, ttl=86400 * 30)
            logger.info(f"Execution mode changed to: {effective_mode}")
            return _execution_mode_update_payload(effective_mode)
        error = "ExecutionAgent not initialized"
        return JSONResponse(
            status_code=500,
            content=_execution_mode_update_payload(effective_mode, error=error),
        )
    except Exception as exc:
        logger.error(f"Failed to set execution mode: {exc}")
        return JSONResponse(
            status_code=500,
            content=_execution_mode_update_payload(effective_mode or "AUTO", error=str(exc)),
        )


class TradingModeBody(BaseModel):
    mode: str = ""


@router.post("/api/trading/mode")
async def set_trading_mode(mode: str = "", body: TradingModeBody = Body(default_factory=TradingModeBody)):
    """Set PAPER or LIVE trading mode. Accepts mode as query param OR JSON body."""
    effective_mode = (mode or body.mode or "").upper()
    if effective_mode not in ["PAPER", "LIVE"]:
        return {"error": "Mode must be PAPER or LIVE"}, 400

    try:
        settings.PAPER_TRADING = effective_mode == "PAPER"
        await cache.set("trading_mode", effective_mode)
        logger.info(f"Trading mode set to: {effective_mode}")
        return {
            "success": True,
            "mode": effective_mode,
            "paperTrading": settings.PAPER_TRADING,
            "message": f"Trading mode changed to {effective_mode}",
        }
    except Exception as exc:
        logger.error(f"Failed to set trading mode: {exc}")
        return {"error": str(exc)}, 500


@router.get("/api/trading/mode")
async def get_trading_mode():
    """Get current PAPER/LIVE mode."""
    return {"mode": "PAPER" if settings.PAPER_TRADING else "LIVE", "paperTrading": settings.PAPER_TRADING}