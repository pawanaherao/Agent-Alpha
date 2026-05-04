import logging

from fastapi import APIRouter

from src.database.redis import cache
from src.services.execution_router import execution_router


logger = logging.getLogger(__name__)
router = APIRouter()


def _execution_broker_fallback(vix: float, error: str | None = None) -> dict:
    payload = {
        "execution_broker": "auto",
        "effective_broker": "dhan",
        "data_broker": "dhan",
        "data_broker_name": "DhanHQ",
        "vix": vix,
        "options": [
            {
                "id": "auto",
                "label": "Auto (Smart Routing)",
                "description": "Strategy-aware: speed-critical orders -> DhanHQ, others -> Kotak",
                "cost": "Mixed",
                "icon": "🔄",
            },
            {
                "id": "dhan",
                "label": "DhanHQ",
                "description": "Fastest API. Use for high-volatility or intraday scalping.",
                "cost": "₹499/month subscription + per-order charges",
                "icon": "⚡",
            },
            {
                "id": "kotak",
                "label": "Kotak Neo",
                "description": "Free execution API. Best for swing, positional, and most options.",
                "cost": "FREE",
                "icon": "🆓",
            },
        ],
        "routing_note": "Execution broker configuration temporarily unavailable; falling back to Auto routing with DhanHQ data feeds.",
        "audit_note": (
            "Each order carries execution_broker in its SEBI audit log. "
            "Switching broker does NOT affect open positions (exits route to their entry broker)."
        ),
    }
    if error:
        payload["error"] = error
    return payload


@router.get("/api/broker/execution-broker")
async def get_execution_broker():
    """Get current execution broker configuration for the frontend selector."""
    try:
        vix = 15.0
        try:
            vix_raw = await cache.get("current_vix")
            if vix_raw:
                vix = float(vix_raw)
        except Exception:
            pass
        return await execution_router.get_current_config(vix=vix)
    except Exception as exc:
        logger.error(f"get_execution_broker failed: {exc}")
        return _execution_broker_fallback(vix=vix, error=str(exc))


@router.post("/api/broker/execution-broker")
async def set_execution_broker(broker: str):
    """Set execution broker override for order routing."""
    valid = ("auto", "dhan", "kotak")
    if broker not in valid:
        return {"error": f"broker must be one of {valid}"}, 400

    try:
        await execution_router.set_override(broker)
        broker_name = {"auto": "Auto Routing", "dhan": "DhanHQ", "kotak": "Kotak Neo"}[broker]
        logger.info("Execution broker override set to: %s", broker)
        return {
            "success": True,
            "execution_broker": broker,
            "broker_name": broker_name,
            "data_broker": "dhan",
            "message": (
                f"Execution broker set to {broker_name}. "
                "Data feeds remain on DhanHQ. "
                "Open positions route exits to their entry broker."
            ),
        }
    except Exception as exc:
        logger.error(f"set_execution_broker failed: {exc}")
        return {"error": str(exc)}, 500