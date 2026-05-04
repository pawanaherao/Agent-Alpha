import asyncio
import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from src.api.chart_symbol_maps import SYMBOL_MAP
from src.core.config import settings
from src.database.redis import cache
from src.services.yfinance_symbols import get_yfinance_price_symbol


logger = logging.getLogger(__name__)
router = APIRouter()
DEFAULT_WATCHLIST = ["NIFTY 50", "BANKNIFTY", "RELIANCE", "HDFCBANK", "FINNIFTY"]


@router.get("/api/signals/recent")
async def get_recent_signals(limit: int = 20):
    """Return most-recently generated trading signals."""
    import json as _json

    try:
        raw = await cache.get("latest_signals")
        if raw:
            data = _json.loads(raw)
            signals = data.get("signals", [])[:limit]
            if signals:
                return {
                    "signals": signals,
                    "count": len(signals),
                    "generated_at": data.get("generated_at"),
                    "source": "redis",
                }
    except Exception:
        pass

    try:
        from src.agents.strategy import _SIGNAL_STORE

        if _SIGNAL_STORE.get("signals"):
            signals = _SIGNAL_STORE["signals"][:limit]
            return {
                "signals": signals,
                "count": len(signals),
                "generated_at": _SIGNAL_STORE.get("generated_at"),
                "source": "in_process",
            }
    except Exception as exc:
        logger.warning(f"In-process signal store read failed: {exc}")

    return {"signals": [], "count": 0, "generated_at": None, "source": "none"}


async def _get_kotak_ltp_map(symbols: list[str]) -> dict[str, float]:
    """Best-effort Kotak LTP lookup by symbol for fallback routing."""
    try:
        from src.services.kotak_neo_client import get_kotak_client

        kotak_client = get_kotak_client()
        if not kotak_client.is_connected():
            await asyncio.to_thread(kotak_client.connect)
        if not kotak_client.is_connected() or not getattr(kotak_client, "_client", None):
            return {}

        tokens = []
        token_to_symbol: dict[str, str] = {}

        for symbol in symbols:
            scrip_resp = None
            for segment in ("nse_cm", "bse_cm"):
                try:
                    scrip_resp = await asyncio.to_thread(
                        kotak_client._client.search_scrip,
                        exchange_segment=segment,
                        symbol=symbol,
                    )
                except TypeError:
                    try:
                        scrip_resp = await asyncio.to_thread(kotak_client._client.search_scrip, segment, symbol)
                    except Exception:
                        scrip_resp = None
                except Exception:
                    scrip_resp = None

                rows = (scrip_resp or {}).get("data", []) if isinstance(scrip_resp, dict) else []
                if rows:
                    token = str(rows[0].get("pSymbol") or rows[0].get("token") or "")
                    if token:
                        tokens.append({"instrument_token": token, "exchange_segment": segment})
                        token_to_symbol[token] = symbol
                    break

        if not tokens:
            return {}

        ltp_map = await kotak_client.get_ltp(tokens)
        out: dict[str, float] = {}
        for token, ltp in ltp_map.items():
            symbol = token_to_symbol.get(str(token))
            if symbol:
                out[symbol] = float(ltp or 0)
        return out
    except Exception as exc:
        logger.debug(f"Kotak fallback LTP map failed: {exc}")
        return {}


@router.get("/api/market/watchlist")
async def market_watchlist(
    symbols: str = "NIFTY 50,BANKNIFTY,RELIANCE,HDFCBANK,FINNIFTY",
    backtest: bool = False,
):
    """Real-time LTP for watchlist symbols."""
    from src.services.dhan_client import get_dhan_client
    import yfinance as yf

    sym_list = [symbol.strip().upper() for symbol in symbols.split(",") if symbol.strip()]
    result = []

    def _safe_float(value) -> float:
        try:
            return float(value or 0)
        except Exception:
            return 0.0

    def _safe_quote_row(symbol: str) -> dict:
        row = dhan_quotes.get(symbol) or {}
        return row if isinstance(row, dict) else {}

    dhan_quotes: dict = {}
    try:
        dhan_client = get_dhan_client()
        if dhan_client.is_connected():
            dhan_quotes = await dhan_client.get_batch_quotes(sym_list, mode="ticker")
    except Exception as exc:
        logger.debug(f"Watchlist DhanHQ quote failed: {exc}")

    missing_after_dhan = [
        symbol for symbol in sym_list if _safe_float(_safe_quote_row(symbol).get("ltp")) <= 0
    ]
    kotak_ltp = await _get_kotak_ltp_map(missing_after_dhan) if missing_after_dhan else {}

    for symbol in sym_list:
        dhan_quote = _safe_quote_row(symbol)
        dhan_ltp = _safe_float(dhan_quote.get("ltp"))
        dhan_prev = _safe_float(dhan_quote.get("close"))
        if dhan_ltp > 0:
            change = round(dhan_ltp - (dhan_prev or dhan_ltp), 2)
            change_pct = round((change / dhan_prev * 100) if dhan_prev else 0, 2)
            result.append(
                {
                    "symbol": symbol,
                    "price": round(dhan_ltp, 2),
                    "change": change,
                    "change_pct": change_pct,
                    "up": change >= 0,
                    "source": "dhan",
                }
            )
            continue

        kotak_price = _safe_float(kotak_ltp.get(symbol))
        if kotak_price > 0:
            result.append(
                {
                    "symbol": symbol,
                    "price": round(kotak_price, 2),
                    "change": 0,
                    "change_pct": 0,
                    "up": True,
                    "source": "kotak",
                }
            )
            continue

        is_paper = getattr(settings, "PAPER_TRADING", False) or getattr(settings, "MODE", "") in ("PAPER", "LOCAL")
        if not backtest and not is_paper:
            result.append(
                {
                    "symbol": symbol,
                    "price": 0,
                    "change": 0,
                    "change_pct": 0,
                    "up": False,
                    "source": "none",
                    "error": "No live feed from Dhan/Kotak (yfinance disabled outside backtest)",
                }
            )
            continue

        ticker_symbol = get_yfinance_price_symbol(symbol)
        try:
            ticker = yf.Ticker(ticker_symbol)
            last: float | None = None
            prev: float | None = None

            try:
                fast_info = ticker.fast_info
                last = float(fast_info.last_price or 0) or None
                prev = float(fast_info.previous_close or 0) or None
            except Exception:
                pass

            if not last:
                try:
                    hist1m = ticker.history(period="1d", interval="1m")
                    if not hist1m.empty:
                        last = float(hist1m["Close"].iloc[-1])
                        if prev is None:
                            prev = float(hist1m["Open"].iloc[0])
                except Exception:
                    pass

            if not last:
                hist2d = ticker.history(period="2d")
                if hist2d.empty:
                    result.append(
                        {
                            "symbol": symbol,
                            "price": 0,
                            "change": 0,
                            "change_pct": 0,
                            "up": False,
                            "source": "yfinance",
                            "error": "no_data",
                        }
                    )
                    continue
                last = float(hist2d["Close"].iloc[-1])
                prev = float(hist2d["Close"].iloc[-2]) if len(hist2d) > 1 else last

            prev = prev or last
            change = round(last - prev, 2)
            change_pct = round((change / prev * 100) if prev else 0, 2)
            result.append(
                {
                    "symbol": symbol,
                    "price": round(last, 2),
                    "change": change,
                    "change_pct": change_pct,
                    "up": change >= 0,
                    "source": "yfinance",
                }
            )
        except Exception as exc:
            result.append(
                {
                    "symbol": symbol,
                    "price": 0,
                    "change": 0,
                    "change_pct": 0,
                    "up": False,
                    "source": "yfinance",
                    "error": str(exc),
                }
            )

    return {"watchlist": result, "count": len(result)}


@router.get("/api/user/watchlist")
async def get_user_watchlist():
    """Return the user's saved watchlist symbols."""
    import json as _json

    try:
        raw = await cache.get("user_watchlist")
        if raw:
            symbols = _json.loads(raw)
        else:
            symbols = list(DEFAULT_WATCHLIST)
    except Exception:
        symbols = list(DEFAULT_WATCHLIST)
    return {"symbols": symbols}


@router.put("/api/user/watchlist")
async def set_user_watchlist(body: dict):
    """Save user watchlist. Body: {"symbols": [...]}"""
    import json as _json

    symbols = body.get("symbols")
    if not isinstance(symbols, list):
        return JSONResponse({"error": "symbols must be an array"}, status_code=400)

    clean: list[str] = []
    seen: set[str] = set()
    for symbol in symbols:
        if not isinstance(symbol, str):
            continue
        key = symbol.strip().upper()
        if key and key not in seen:
            seen.add(key)
            clean.append(key)
        if len(clean) >= 20:
            break

    try:
        await cache.set("user_watchlist", _json.dumps(clean), ttl=86400 * 365)
    except Exception as exc:
        return {"symbols": clean, "error": str(exc)}

    return {"symbols": clean}


@router.get("/api/market/depth/{symbol}")
async def market_depth(symbol: str):
    """Real 5-level order book (bid/ask) from broker API."""
    from src.services.broker_factory import get_broker_client

    client = get_broker_client()
    try:
        depth = await client.get_market_depth(symbol)
        return {
            "symbol": symbol,
            "bids": depth.get("buy", []),
            "asks": depth.get("sell", []),
            "connected": client.is_connected(),
        }
    except Exception as exc:
        return {"symbol": symbol, "bids": [], "asks": [], "connected": False, "error": str(exc)}


@router.get("/api/market/quote/{symbol}")
async def market_quote(symbol: str, mode: str = "ohlc", backtest: bool = False):
    """Return live market quote with broker-first fallbacks."""
    from src.services.dhan_client import get_dhan_client

    sym_upper = symbol.upper()
    dhan_client = get_dhan_client()

    if dhan_client.is_connected():
        try:
            data = await dhan_client.get_batch_quotes([sym_upper], mode=mode)
            row = data.get(sym_upper) or data.get(symbol) or {}
            if float(row.get("ltp") or 0) > 0:
                return {"symbol": symbol, "source": "dhan", "mode": mode, "data": row}
        except Exception as exc:
            logger.warning(f"DhanHQ quote error for {symbol}: {exc}")

    try:
        kotak = await _get_kotak_ltp_map([sym_upper])
        ltp = float(kotak.get(sym_upper) or 0)
        if ltp > 0:
            return {
                "symbol": symbol,
                "source": "kotak",
                "mode": "ticker",
                "data": {"ltp": ltp, "open": 0, "high": 0, "low": 0, "close": 0},
            }
    except Exception as exc:
        logger.debug(f"Kotak quote fallback error for {symbol}: {exc}")

    is_paper = getattr(settings, "PAPER_TRADING", False) or getattr(settings, "MODE", "") in ("PAPER", "LOCAL")
    if not backtest and not is_paper:
        return {
            "symbol": symbol,
            "source": "none",
            "mode": mode,
            "error": "No live quote from Dhan/Kotak (yfinance disabled outside backtest)",
            "data": {},
        }

    try:
        import yfinance as yf

        ticker_symbol = SYMBOL_MAP.get(sym_upper, f"{sym_upper}.NS")
        info = yf.Ticker(ticker_symbol).fast_info
        ltp = getattr(info, "last_price", None) or 0
        return {
            "symbol": symbol,
            "source": "yfinance",
            "mode": "ticker",
            "data": {"ltp": ltp, "open": 0, "high": 0, "low": 0, "close": 0},
        }
    except Exception as exc:
        return {
            "symbol": symbol,
            "source": "yfinance",
            "mode": "ticker",
            "error": str(exc),
            "data": {"ltp": 0, "open": 0, "high": 0, "low": 0, "close": 0},
        }