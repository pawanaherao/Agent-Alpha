import json

from fastapi import APIRouter

from src.database.redis import cache


router = APIRouter()


def _read_budget_value(tracker, attr_name: str, fallback=None):
    value = getattr(tracker, attr_name, fallback)
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return fallback


@router.get("/api/ai/router")
async def get_ai_router_status():
    """AI Router status — provider config, availability, call stats."""
    from src.services.ai_router import ai_router

    try:
        status = ai_router.get_status()
        if isinstance(status, dict):
            return status
        return {"status": str(status)}
    except Exception as exc:
        return {"error": str(exc)}


@router.get("/api/ai/cost")
async def get_ai_cost_status():
    """Return current AI token usage, cost, and budget status."""
    from src.services.ai_cost_tracker import ai_cost_tracker

    try:
        status = ai_cost_tracker.get_status()
        if isinstance(status, dict):
            return status
        return {"status": str(status)}
    except Exception as exc:
        return {"error": str(exc)}


@router.post("/api/ai/budget")
async def set_ai_budget(daily_inr: float = None, monthly_inr: float = None):
    """Update AI cost budgets and persist them to Redis for the dashboard."""
    from src.services.ai_cost_tracker import ai_cost_tracker

    daily_budget_inr = _read_budget_value(ai_cost_tracker, "_daily_budget_inr", daily_inr)
    monthly_budget_inr = _read_budget_value(ai_cost_tracker, "_monthly_budget_inr", monthly_inr)
    status = "updated"
    error = None

    if daily_inr is not None or monthly_inr is not None:
        try:
            ai_cost_tracker.set_budgets(daily_inr=daily_inr, monthly_inr=monthly_inr)
            daily_budget_inr = _read_budget_value(
                ai_cost_tracker,
                "_daily_budget_inr",
                daily_budget_inr,
            )
            monthly_budget_inr = _read_budget_value(
                ai_cost_tracker,
                "_monthly_budget_inr",
                monthly_budget_inr,
            )
            try:
                await cache.set(
                    "ai_cost_budgets",
                    json.dumps(
                        {
                            "daily_inr": daily_budget_inr,
                            "monthly_inr": monthly_budget_inr,
                        }
                    ),
                )
            except Exception:
                pass
        except Exception as exc:
            status = "unchanged"
            error = str(exc)

    response = {
        "daily_budget_inr": daily_budget_inr,
        "monthly_budget_inr": monthly_budget_inr,
        "status": status,
    }
    if error is not None:
        response["error"] = error

    return response