from fastapi import APIRouter


router = APIRouter()


@router.get("/api/account/fund-limits")
async def account_fund_limits():
    """DhanHQ account margin and cash limits."""
    from src.services.dhan_client import get_dhan_client

    dhan_client = get_dhan_client()
    if not dhan_client.is_connected():
        return {"error": "DhanHQ not connected", "data": {}}
    try:
        data = await dhan_client.get_fund_limits_data()
        return {"source": "dhan", "data": data}
    except Exception as exc:
        return {"source": "dhan", "error": str(exc), "data": {}}


@router.get("/api/account/holdings")
async def account_holdings():
    """Portfolio holdings from the active broker."""
    from src.services.broker_factory import get_broker_client

    client = get_broker_client()
    if not client.is_connected():
        return {"error": f"{client.broker_name()} not connected", "holdings": []}
    try:
        if hasattr(client, "get_holdings"):
            holdings = await client.get_holdings()  # type: ignore[attr-defined]
        else:
            holdings = await client.get_positions()
        return {"broker": client.broker_name(), "holdings": holdings}
    except Exception as exc:
        return {"error": str(exc), "holdings": []}