import logging
import os
from pathlib import Path
import time

from fastapi import APIRouter, Body
from pydantic import BaseModel
from fastapi.responses import JSONResponse

from src.core.config import settings
from src.database.redis import cache


logger = logging.getLogger(__name__)
router = APIRouter()

BROKER_NAMES = {
    "dhan": "DhanHQ",
    "kotak": "Kotak Neo",
}

AVAILABLE_BROKERS = [
    {"id": "dhan", "name": "DhanHQ", "cost": "Rs.499/month", "apiDocs": "https://dhanhq.co"},
    {"id": "kotak", "name": "Kotak Neo", "cost": "FREE", "apiDocs": "https://kotakneo.kotaksecurities.com"},
]


class BrokerSwitchBody(BaseModel):
    broker: str = ""


def _broker_status_payload(
    broker: str | None = None,
    *,
    connected: bool = False,
    broker_name: str | None = None,
    error: str | None = None,
) -> dict:
    current_broker = (broker or os.getenv("BROKER", "dhan")).lower()
    fallback_broker = os.getenv("BROKER_FALLBACK", "").lower()
    payload = {
        "broker": current_broker,
        "brokerName": broker_name or BROKER_NAMES.get(current_broker, current_broker),
        "connected": connected,
        "paperTrading": settings.PAPER_TRADING,
        "fallbackBroker": fallback_broker or None,
        "failoverEnabled": bool(fallback_broker) and settings.PAPER_TRADING,
        "availableBrokers": AVAILABLE_BROKERS,
    }
    if error:
        payload["error"] = error
        payload["lastError"] = error
    return payload


def _broker_switch_payload(broker: str, error: str | None = None, hint: str | None = None) -> dict:
    normalized_broker = broker.lower().strip()
    broker_name = BROKER_NAMES.get(normalized_broker, normalized_broker or "selected broker")
    payload = {
        "success": error is None,
        "broker": normalized_broker,
        "message": (
            f"Switched to {normalized_broker}. Reconnect to apply."
            if error is None
            else f"Broker switch to {broker_name} failed."
        ),
    }
    if error:
        payload["brokerName"] = broker_name
        payload["error"] = error
        payload["detail"] = error
    if hint:
        payload["hint"] = hint
    return payload


def _get_backend_env_path() -> Path:
    return Path(__file__).resolve().parents[2] / ".env"


@router.get("/api/broker/status")
async def get_broker_status():
    """Get active broker connection status."""
    try:
        from src.services.broker_factory import get_broker_client

        client = get_broker_client()
        current_broker = os.getenv("BROKER", "dhan").lower()
        return _broker_status_payload(
            broker=current_broker,
            connected=client.is_connected(),
            broker_name=client.broker_name(),
        )
    except Exception as exc:
        logger.error(f"Failed to get broker status: {exc}")
        return _broker_status_payload(error=str(exc))


@router.post("/api/broker/switch")
async def switch_broker(
    broker: str = "",
    body: BrokerSwitchBody = Body(default_factory=BrokerSwitchBody),
):
    """Switch the active broker, accepting either a query param or JSON body."""
    effective_broker = (broker or body.broker or "").lower().strip()
    valid = ["dhan", "kotak"]
    if effective_broker not in valid:
        error = f"Invalid broker. Must be one of: {valid}"
        return JSONResponse(status_code=400, content=_broker_switch_payload(effective_broker, error=error))

    if not settings.PAPER_TRADING:
        error = "Cannot switch broker during LIVE trading. Switch to PAPER mode first."
        return JSONResponse(
            status_code=400,
            content=_broker_switch_payload(
                effective_broker,
                error=error,
                hint="POST /api/trading/mode with mode=PAPER, then retry.",
            ),
        )

    previous_broker = os.environ.get("BROKER")
    try:
        from src.services.broker_factory import reset_broker_client

        os.environ["BROKER"] = effective_broker
        reset_broker_client()
        await cache.set("active_broker", effective_broker, ttl=86400 * 30)
        logger.info(f"Broker switched to: {effective_broker}")
        return _broker_switch_payload(effective_broker)
    except Exception as exc:
        if previous_broker is None:
            os.environ.pop("BROKER", None)
        else:
            os.environ["BROKER"] = previous_broker
        logger.error(f"Broker switch failed: {exc}")
        return JSONResponse(
            status_code=500,
            content=_broker_switch_payload(effective_broker, error=str(exc)),
        )


@router.post("/api/broker/credentials")
async def update_broker_credentials(data: dict = Body(...)):
    """Update broker credentials in backend/.env at runtime."""
    import re

    if not settings.PAPER_TRADING:
        return JSONResponse(status_code=400, content={"error": "Cannot update credentials during LIVE trading. Switch to PAPER first."})

    field_map = {
        "dhan_client_id": "DHAN_CLIENT_ID",
        "dhan_access_token": "DHAN_ACCESS_TOKEN",
        "kotak_consumer_key": "KOTAK_CONSUMER_KEY",
        "kotak_mobile_number": "KOTAK_MOBILE_NUMBER",
        "kotak_ucc": "KOTAK_UCC",
        "kotak_mpin": "KOTAK_MPIN",
    }

    updates = {}
    for field, env_key in field_map.items():
        if field in data and data[field] is not None and str(data[field]).strip():
            updates[env_key] = str(data[field]).strip()

    totp_val = str(data.get("kotak_totp_secret") or "").strip()
    if totp_val:
        is_base32 = len(totp_val) > 6 and not totp_val.isdigit()
        if is_base32:
            updates["KOTAK_TOTP_SECRET"] = totp_val
            updates.pop("KOTAK_TOTP", None)
            logger.info("[Kotak] Saving base32 TOTP secret — will auto-generate codes")
        else:
            updates["KOTAK_TOTP"] = totp_val

    if not updates:
        return JSONResponse(status_code=400, content={"error": "No valid credential fields provided."})

    env_path = _get_backend_env_path()
    if env_path.exists():
        content = env_path.read_text(encoding="utf-8")
        for env_key, value in updates.items():
            pattern = rf"^{env_key}=.*$"
            replacement = f"{env_key}={value}"
            if re.search(pattern, content, flags=re.MULTILINE):
                content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
            else:
                content += f"\n{replacement}"
        env_path.write_text(content, encoding="utf-8")

    for env_key, value in updates.items():
        os.environ[env_key] = value

    try:
        from src.services.broker_factory import reset_broker_client, reset_execution_clients, reset_data_client
        from src.services.dhan_client import reset_dhan_client
        from src.services.kotak_neo_client import reset_kotak_client

        reset_dhan_client()
        reset_kotak_client()
        reset_broker_client()
        reset_execution_clients()
        reset_data_client()
    except Exception as reinit_err:
        logger.warning(f"Broker client re-init after credential update: {reinit_err}")

    try:
        from src.services.nse_data import nse_data_service

        nse_data_service._init_dhan_client()
        logger.info("NSE data service DhanHQ client refreshed with new credentials")
    except Exception as nse_err:
        logger.warning(f"NSE data service reinit skipped: {nse_err}")

    dhan_status = {"connected": False, "message": "pending"}
    if any(key in updates for key in ("DHAN_CLIENT_ID", "DHAN_ACCESS_TOKEN")):
        try:
            from src.services.dhan_client import get_dhan_client
            import asyncio as _asyncio

            dhan_client = get_dhan_client()
            dhan_client.client_id = os.getenv("DHAN_CLIENT_ID", "") or dhan_client.client_id
            dhan_client.access_token = os.getenv("DHAN_ACCESS_TOKEN", "") or dhan_client.access_token
            if dhan_client.is_connected():
                resp = await _asyncio.get_event_loop().run_in_executor(None, dhan_client.dhan.get_fund_limits)
                if isinstance(resp, dict) and resp.get("status") == "success":
                    data = resp.get("data", {})
                    avail = data.get("availabelBalance", data.get("availableBalance"))
                    bal = f" · Available ₹{float(avail):,.0f}" if avail is not None else ""
                    dhan_status = {"connected": True, "message": f"DhanHQ verified{bal}"}
                else:
                    hint = str(resp)[:150] if resp else "empty response"
                    dhan_status = {"connected": False, "message": f"Token rejected: {hint}"}
            else:
                dhan_status = {"connected": False, "message": "Client init failed — check credentials"}
        except Exception as conn_err:
            err = str(conn_err)
            if "401" in err or "nauthorized" in err:
                dhan_status = {"connected": False, "message": "401 Unauthorized — token expired, re-generate from dhanhq.co"}
            elif "404" in err:
                dhan_status = {"connected": False, "message": "404 — token expired or client ID wrong"}
            else:
                dhan_status = {"connected": False, "message": err[:200]}
            logger.warning(f"DhanHQ verify after credential save: {conn_err}")

    return {
        "success": True,
        "updated_fields": list(updates.keys()),
        "message": "Credentials saved to .env and applied to running services.",
        "dhan_connection": dhan_status,
    }


@router.post("/api/broker/kotak-totp")
async def update_kotak_totp(totp: str = Body(..., embed=True)):
    """Quick-update the Kotak NEO TOTP (6-digit OTP) without restarting."""
    totp_clean = str(totp).strip()
    if not totp_clean.isdigit() or len(totp_clean) != 6:
        return JSONResponse(status_code=400, content={
            "error": "TOTP must be a 6-digit numeric code from your authenticator app (e.g. 123456)"
        })

    os.environ["KOTAK_TOTP"] = totp_clean

    try:
        from src.services.kotak_neo_client import reset_kotak_client

        reset_kotak_client()
    except Exception as exc:
        logger.warning(f"Kotak client reset after TOTP update: {exc}")

    return {
        "success": True,
        "message": f"TOTP updated to {totp_clean[:2]}**** — valid for ~30 seconds. Click Connect now.",
        "hint": "This update is temporary (not saved to .env). Re-enter on next restart.",
    }


@router.get("/api/broker/diagnostics")
async def broker_diagnostics():
    """Run a quick connectivity test on every data tier and return results."""
    results: dict = {}

    t0 = time.time()
    try:
        client_id = os.getenv("DHAN_CLIENT_ID", "")
        access_token = os.getenv("DHAN_ACCESS_TOKEN", "")
        if not client_id or not access_token:
            results["dhan"] = {"status": "skipped", "message": "Credentials not configured"}
        else:
            from dhanhq import dhanhq

            client = dhanhq(client_id, access_token)
            resp = client.get_fund_limits()
            if isinstance(resp, dict) and resp.get("status") == "success":
                results["dhan"] = {"status": "ok", "latency_ms": round((time.time() - t0) * 1000), "message": "Connected"}
            else:
                results["dhan"] = {"status": "error", "latency_ms": round((time.time() - t0) * 1000), "message": str(resp)[:200]}
    except Exception as exc:
        results["dhan"] = {"status": "error", "latency_ms": round((time.time() - t0) * 1000), "message": str(exc)[:200]}

    t0 = time.time()
    try:
        from src.services.kotak_neo_client import get_kotak_client

        kotak_client = get_kotak_client()
        if kotak_client.is_connected():
            results["kotak"] = {"status": "ok", "latency_ms": round((time.time() - t0) * 1000), "message": "Connected"}
        else:
            results["kotak"] = {"status": "error", "latency_ms": round((time.time() - t0) * 1000), "message": "Not connected — check MPIN/TOTP"}
    except Exception as exc:
        results["kotak"] = {"status": "error", "latency_ms": round((time.time() - t0) * 1000), "message": str(exc)[:200]}

    t0 = time.time()
    try:
        import yfinance as yf

        tick = yf.Ticker("RELIANCE.NS")
        info = tick.fast_info
        price = getattr(info, "last_price", None)
        if price:
            results["yfinance"] = {"status": "ok", "latency_ms": round((time.time() - t0) * 1000), "message": f"Price ₹{price:.2f} (15-min delay)"}
        else:
            results["yfinance"] = {"status": "error", "latency_ms": round((time.time() - t0) * 1000), "message": "No price returned"}
    except Exception as exc:
        results["yfinance"] = {"status": "error", "latency_ms": round((time.time() - t0) * 1000), "message": str(exc)[:200]}

    overall = "ok" if any(value.get("status") == "ok" for value in results.values()) else "all_failed"
    return {"overall": overall, "tiers": results}


@router.post("/api/broker/connect")
async def broker_connect(broker: str = "dhan"):
    """Trigger an active broker session connection."""
    broker = broker.lower().strip()

    if broker == "dhan":
        try:
            import asyncio as _asyncio
            import time as _time
            from src.services.dhan_client import get_dhan_client

            dhan_client = get_dhan_client()
            dhan_client.client_id = os.getenv("DHAN_CLIENT_ID", "") or dhan_client.client_id
            dhan_client.access_token = os.getenv("DHAN_ACCESS_TOKEN", "") or dhan_client.access_token
            await _asyncio.get_event_loop().run_in_executor(None, dhan_client.connect)
            if not dhan_client.dhan:
                return {"connected": False, "broker": "dhan", "message": "DhanHQ credentials not configured — set DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN"}

            start = _time.time()

            def _verify_dhan():
                return dhan_client.dhan.get_fund_limits()

            resp = await _asyncio.get_event_loop().run_in_executor(None, _verify_dhan)
            latency = round((_time.time() - start) * 1000)
            if isinstance(resp, dict) and resp.get("status") == "success":
                data = resp.get("data", {})
                avail = data.get("availabelBalance", data.get("availableBalance", None))
                balance_str = f" · Available balance ₹{float(avail):,.0f}" if avail is not None else ""
                return {"connected": True, "broker": "dhan", "message": f"DhanHQ connected — token valid{balance_str} ({latency} ms)", "latency_ms": latency}
            hint = str(resp).replace('{', '').replace('}', '')[:200] if resp else "empty response"
            return {"connected": False, "broker": "dhan", "message": f"DhanHQ token rejected — {hint}. Re-paste your access token from dhanhq.co"}
        except Exception as exc:
            logger.error(f"DhanHQ connect error: {exc}")
            err = str(exc)
            if "401" in err or "Unauthorized" in err or "unauthorized" in err:
                return {"connected": False, "broker": "dhan", "message": "DhanHQ: Unauthorized (401) — token expired. Re-generate from dhanhq.co → API Dashboard and paste the new token in Settings."}
            if "404" in err or "Not Found" in err or "not found" in err:
                return {"connected": False, "broker": "dhan", "message": "DhanHQ: 404 Not Found — token is expired or client ID is invalid. Re-generate access token from dhanhq.co → Login → API Dashboard → Access Token."}
            return {"connected": False, "broker": "dhan", "message": err[:300]}

    if broker == "kotak":
        try:
            import asyncio as _asyncio
            from src.services.kotak_neo_client import get_kotak_client, reset_kotak_client

            reset_kotak_client()
            kotak_client = get_kotak_client()
            ok = await _asyncio.get_event_loop().run_in_executor(None, kotak_client.connect)
            if ok:
                return {"connected": True, "broker": "kotak", "message": "Kotak Neo session established"}
            totp_val = os.getenv("KOTAK_TOTP", "").strip()
            if not totp_val or not totp_val.isdigit() or len(totp_val) != 6:
                return {
                    "connected": False,
                    "broker": "kotak",
                    "message": "Kotak Neo: KOTAK_TOTP must be the current 6-digit OTP from your authenticator app. Enter it in Settings → Kotak Neo → TOTP field, save credentials, then connect immediately (valid ~30 s).",
                }
            return {
                "connected": False,
                "broker": "kotak",
                "message": "Kotak Neo connect failed — verify KOTAK_CONSUMER_KEY, KOTAK_MOBILE_NUMBER (10 digits, no +91), KOTAK_UCC, KOTAK_MPIN, and enter a fresh 6-digit TOTP OTP before connecting",
            }
        except Exception as exc:
            logger.error(f"Kotak connect error: {exc}")
            return {"connected": False, "broker": "kotak", "message": str(exc)[:300]}

    return {"connected": False, "broker": broker, "message": f"Unknown broker: {broker}. Supported: dhan, kotak"}