from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta, time
import asyncio
import json
from uuid import uuid4

# Vertex AI is optional — falls back to rule-based justification if not installed
try:
    import vertexai
    from vertexai.generative_models import GenerativeModel
    VERTEXAI_AVAILABLE = True
except ImportError:
    VERTEXAI_AVAILABLE = False
    vertexai = None
    GenerativeModel = None

from src.agents.base import BaseAgent
from src.core.config import settings
from src.core.messages import AgentMessage
from src.services.dhan_client import get_dhan_client
from src.services.ai_cost_tracker import ai_cost_tracker
from src.services.broker_factory import get_execution_client, report_broker_error, clear_broker_errors
from src.services.instrument_translator import instrument_translator
from src.database.postgres import db
from src.database.redis import cache

# Options imports (lazy — only used when OPTIONS_ENABLED)
_options_loaded = False
def _ensure_options_imports():
    global _options_loaded, sebi_validator, multi_leg_executor, options_position_manager, OptionsSignal, LegSignal
    if _options_loaded:
        return
    try:
        from src.middleware.sebi_options import sebi_validator as _sv
        from src.services.multi_leg_executor import multi_leg_executor as _mle
        from src.services.options_position_manager import options_position_manager as _opm
        from src.models.options import OptionsSignal as _os, LegSignal as _ls
        sebi_validator = _sv
        multi_leg_executor = _mle
        options_position_manager = _opm
        OptionsSignal = _os
        LegSignal = _ls
        _options_loaded = True
    except Exception as e:
        logging.getLogger(__name__).warning(f"Options imports failed: {e}")
        _options_loaded = False

def _resolve_paper_product_type(signal: Dict) -> str:
    """
    Determine the correct product_type for a paper position.

    Uses the same explicit strategy maps as order_type_router (single source of
    truth).  Falls back to fast keyword matching so new unregistered strategies
    always get a safe default (CNC rather than INTRA).

    Product matrix:
      Options + SWING    → NRML  (overnight F&O carry)
      Options + INTRADAY → INTRA (same-day options scalper)
      Equity  + SWING    → CNC   (delivery)
      Equity  + INTRADAY → INTRA (same-day equity)
      FNO     + SWING    → NRML  (overnight futures carry)
    """
    from src.services.order_type_router import (
        get_strategy_trading_style, get_strategy_module,
    )
    metadata = signal.get("metadata") or {}

    # 1. Explicit override in metadata always wins
    if metadata.get("product_type"):
        return str(metadata["product_type"]).upper()

    # 2. Instrument-type hint in metadata (e.g. option chain signals)
    instrument_type = str(metadata.get("instrument_type", "")).upper()
    if instrument_type in {"CE", "PE", "CALL", "PUT", "OPT"}:
        # Options — check style to determine NRML vs INTRA
        style = get_strategy_trading_style(signal.get("strategy_name", ""))
        return "INTRA" if style == "INTRADAY" else "NRML"

    # 3. Use the explicit strategy maps (deterministic)
    strategy_name = str(signal.get("strategy_name", ""))
    module = get_strategy_module(strategy_name)   # Equity / Options / FNO
    style  = get_strategy_trading_style(strategy_name)  # INTRADAY / SWING

    if module == "Options":
        return "INTRA" if style == "INTRADAY" else "NRML"
    if module == "FNO":
        return "INTRA" if style == "INTRADAY" else "NRML"
    # Equity
    return "INTRA" if style == "INTRADAY" else "CNC"


def _is_entry_allowed(signal: Dict) -> tuple:
    """
    Entry time gate — blocks new entries when insufficient session time remains.

    Medallion CEO Fix #1 (Mar 2026):
    - INTRA / MIS : entries blocked after 15:20 IST (position monitor forces TIME_EXIT
      at 15:10 — any entry after 15:20 creates instant ghost trades with zero P&L)
    - CNC / NRML  : swing entries blocked after 15:00 IST (order may not settle
      within the T+1 window; also protects against late deep-OTM options fills)

    Returns (allowed: bool, reason: str).
    """
    now = datetime.now().time()
    product_type = _resolve_paper_product_type(signal)
    if product_type in ("INTRA", "MIS") and now >= time(15, 20):
        return False, f"ENTRY_BLOCKED_INTRA_POST_1520 at {now.strftime('%H:%M:%S')}"
    if product_type in ("CNC", "NRML") and now >= time(15, 0):
        return False, f"ENTRY_BLOCKED_SWING_POST_1500 at {now.strftime('%H:%M:%S')}"
    return True, "ENTRY_ALLOWED"


class ExecutionAgent(BaseAgent):
    """
    Agent responsible for Order Execution.
    Phase 4 of Orchestration Loop.
    Modes: MANUAL, AUTO, HYBRID.
    """
    def __init__(self, name: str = "ExecutionAgent", config: Dict[str, Any] = None):
        super().__init__(name, config)
        self.mode = "AUTO" # Default Mode for Testing (was HYBRID)
        self.model = None
        self.project_id = settings.GCP_PROJECT
        self.location = "us-central1"

    async def start(self):
        """
        Initialize Vertex AI (optional).
        Load execution mode from cache if available.
        """
        await super().start()

        # 1. Load execution mode from cache (user preference from UI).
        _cached_mode: str = ""
        try:
            cached_mode = await cache.get("execution_mode")
            if isinstance(cached_mode, bytes):
                cached_mode = cached_mode.decode()
            if cached_mode in ["MANUAL", "HYBRID", "AUTO"]:
                self.mode = cached_mode
                _cached_mode = cached_mode
                self.logger.info(f"Loaded execution mode from cache: {self.mode}")
        except Exception as e:
            self.logger.warning(f"Failed to load execution mode from cache: {e}")

        # 2. PAPER / LOCAL mode: force AUTO *after* cache load so it always wins.
        #    Paper trading must auto-execute — MANUAL/HYBRID would stall every
        #    signal waiting for a UI click that may never come.
        try:
            _paper = getattr(settings, "PAPER_TRADING", False) or getattr(settings, "MODE", "LIVE") in ("PAPER", "LOCAL")
            if _paper and self.mode != "AUTO":
                self.mode = "AUTO"
                self.logger.info(
                    f"PAPER mode — execution mode forced to AUTO"
                    + (f" (cache had '{_cached_mode}')" if _cached_mode else "")
                )
        except Exception:
            pass
        
        if not VERTEXAI_AVAILABLE:
            self.logger.warning("Vertex AI not installed — using rule-based justification")
            return
        try:
            model_name = getattr(settings, 'VERTEXAI_MODEL', 'gemini-2.0-flash-001')
            location   = getattr(settings, 'VERTEXAI_LOCATION', 'us-central1')
            vertexai.init(project=self.project_id, location=location)
            # B19 FIX: replaced deprecated gemini-1.5-pro-preview-0409 with
            # settings.VERTEXAI_MODEL (defaults to gemini-2.0-flash-001).
            # In HYBRID paper-trade mode this generates the plain-English
            # justification card shown to the investor before approval.
            self.model = GenerativeModel(model_name)
            self.logger.info(f"Connected to Vertex AI for Trade Justification: {model_name}")
        except Exception as e:
            self.logger.warning(f"Vertex AI init failed (non-critical): {e}")

    async def execute_trade(self, order_package: Dict[str, Any]):
        """
        Execute approved trade based on mode.
        """
        signal = order_package['signal']
        decision = order_package['risk_decision']

        # ── Live + Paper entry time gate (Panel Fix R1) ───────────────────────
        # Applied here so the gate covers ALL execution modes (AUTO, HYBRID,
        # MANUAL) in BOTH paper and live.  Previously only paper paths had
        # this guard, leaving live INTRA orders after 15:20 reaching DhanHQ
        # and being auto-squared at 15:30 with 20–50 bps slippage.
        _entry_ok, _entry_reason = _is_entry_allowed(signal)
        if not _entry_ok:
            self.logger.warning(
                f"ENTRY BLOCKED ({_entry_reason}): "
                f"{signal.get('signal_type', 'BUY')} {signal.get('symbol', '')} "
                f"| strategy={signal.get('strategy_name', '')}"
            )
            return
        # ── End entry time gate ───────────────────────────────────────────────

        strength = signal.get('strength', 0.0)
        
        # Mode Logic
        should_auto_execute = False
        
        if self.mode == "AUTO":
            should_auto_execute = True
        elif self.mode == "HYBRID":
            # MFT Mar 2026: lowered from 0.8 to 0.65 for more auto-executions
            if strength > 0.65:
                should_auto_execute = True
            else:
                should_auto_execute = False
        else: # MANUAL
            should_auto_execute = False
            
        if should_auto_execute:
            await self._place_market_order(signal, decision)
        else:
            await self._request_user_approval(signal, decision)

    async def _place_market_order(self, signal: Dict, decision: Dict):
        """Send order via routed execution broker with full SEBI compliance (Phase 7)."""
        try:
            # ── Paper mode: simulate fill without broker call ──────────
            _is_paper = bool(getattr(settings, "PAPER_TRADING", False)) or \
                        getattr(settings, "MODE", "LIVE") in ("PAPER", "LOCAL")
            if _is_paper:
                # ── Market hours guard (paper mode) ──────────────────
                # Intraday signals entered after 15:10 are immediately
                # TIME_EXIT'd with ltp == entry_price → zero PnL and
                # contaminate paper-trading stats.  Block the fill so
                # ghost trades never reach position_monitor.
                from src.core.agent_manager import is_market_open as _is_mkt_open
                if not _is_mkt_open():
                    self.logger.warning(
                        f"PAPER FILL BLOCKED (outside market hours 09:15–15:30): "
                        f"{signal.get('signal_type', 'BUY')} {signal.get('symbol', '')} "
                        f"@ {signal.get('entry_price', 0)} "
                        f"| strategy={signal.get('strategy_name', '')}"
                    )
                    return
                # ── End market hours guard ────────────────────────────
                # ── Entry time gate (paper mode) ──────────────────────────
                # No new INTRA entries after 15:20 IST; swing blocked after 15:00.
                _entry_ok, _entry_reason = _is_entry_allowed(signal)
                if not _entry_ok:
                    self.logger.info(
                        f"PAPER ENTRY BLOCKED ({_entry_reason}): "
                        f"{signal.get('signal_type', 'BUY')} {signal.get('symbol', '')} "
                        f"| strategy={signal.get('strategy_name', '')}"
                    )
                    return
                # ── End entry time gate ───────────────────────────────────
                quantity = int(
                    (decision.get('modifications') or {}).get(
                        'quantity', signal.get('quantity', 1)
                    ) or 1
                )
                sim_order_id = f"SIM_{uuid4().hex[:12]}"
                # Resolve product_type so portfolio.py & position_monitor
                # assign the right exit logic (CNC → trailing SL + partial
                # profit booking; NRML → options partial exit; INTRA → TIME_EXIT)
                _paper_product_type = _resolve_paper_product_type(signal)
                _signal_with_pt = dict(signal)
                _signal_with_pt["metadata"] = dict(signal.get("metadata") or {})
                _signal_with_pt["metadata"]["product_type"] = _paper_product_type
                # ── Friction-aware P&L simulation (Medallion CEO Fix #5) ──────────
                # Add round-trip transaction cost estimate so paper P&L reflects
                # real-world drag. PortfolioAgent reads this to report net_pnl.
                # INTRA: ₹70 (₹20 brokerage + ₹30 STT approx + ₹20 exchange charges)
                # CNC/NRML: ₹40 (delivery settlement — lower STT, no intraday premium)
                _friction_rt = 70.0 if _paper_product_type in ("INTRA", "MIS") else 40.0
                _signal_with_pt["metadata"]["estimated_friction_cost"] = _friction_rt
                _signal_with_pt["metadata"]["friction_per_share"] = round(
                    _friction_rt / max(quantity, 1), 4
                )
                # ── End friction tracking ─────────────────────────────────────────
                self.logger.info(
                    f"PAPER FILL: {signal.get('signal_type','BUY')} {quantity} "
                    f"{signal.get('symbol','')} @ {signal.get('entry_price', 0)} "
                    f"| strategy={signal.get('strategy_name','')} "
                    f"| product_type={_paper_product_type} | ID={sim_order_id}"
                )
                await self.publish_event("ORDER_FILLED", {
                    "order_id": sim_order_id,
                    "symbol": signal.get('symbol', ''),
                    "status": "FILLED",
                    "signal": _signal_with_pt,
                    "quantity": quantity,
                })
                # Audit trail for paper trades
                try:
                    await db.execute(
                        """INSERT INTO execution_logs
                           (strategy_name, symbol, action, price, quantity,
                            execution_time, status, reason)
                           VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
                        signal.get('strategy_name', ''),
                        signal.get('symbol', ''),
                        signal.get('signal_type', 'BUY'),
                        float(signal.get('entry_price', 0) or 0),
                        quantity,
                        datetime.now(),
                        "PAPER_FILLED",
                        f"Paper trading simulated fill | strength={signal.get('strength', 0):.2f}",
                    )
                except Exception:
                    pass
                return
            # ── End paper mode ─────────────────────────────────────────

            # Data plane: always DhanHQ for symbol resolution / market data
            dhan_client = get_dhan_client()
            metadata = signal.get('metadata', {}) or {}

            # Execution plane: routed by ExecutionRouter (strategy matrix + VIX rules)
            strategy_id = signal.get('strategy_name', '')
            vix = float(metadata.get('vix', 15.0))
            exec_client = await get_execution_client(strategy_id=strategy_id, vix=vix)
            quantity = (decision.get('modifications') or {}).get('quantity', signal.get('quantity', 1))

            # ----------------------------------------------------------
            # Phase 7.1: SEBI equity pre-trade validation
            # ----------------------------------------------------------
            from src.middleware.sebi_equity import sebi_equity_validator

            # Count current open positions from DB (best-effort)
            current_pos_count = 0
            try:
                if db.pool is not None:
                    async with db.pool.acquire() as conn:
                        row = await conn.fetchrow(
                            "SELECT COUNT(*) AS cnt FROM open_positions WHERE status='OPEN'"
                        )
                    current_pos_count = int(row['cnt']) if row else 0
            except Exception:
                pass

            _is_paper = bool(getattr(settings, "PAPER_TRADING", False))
            equity_check = sebi_equity_validator.validate(
                order={
                    "price": signal.get("entry_price", 0),
                    "quantity": quantity,
                    "exchangeSegment": metadata.get("exchange_segment", "NSE"),
                    "metadata": metadata,
                },
                current_positions_count=current_pos_count,
                is_paper=_is_paper,
            )
            if not equity_check.approved:
                self.logger.warning(f"SEBI equity REJECTED: {equity_check.violations}")
                return
            if equity_check.warnings:
                self.logger.info(f"SEBI equity warnings: {equity_check.warnings}")

            # Resolve security details
            resolved = dhan_client.resolve_security_details(
                symbol=signal.get('symbol', ''),
                signal_type=signal.get('signal_type', 'BUY'),
                metadata=metadata
            )

            exchange_segment = (
                (resolved or {}).get("exchange_segment")
                or metadata.get("exchange_segment")
                or metadata.get("exchangeSegment")
                or ("NSE" if str(metadata.get("instrument", "")).upper() == "EQUITY_CASH" else "NSE_FNO")
            )

            product_type = (
                (resolved or {}).get("product_type")
                or metadata.get("product_type")
                or metadata.get("productType")
                or ("CNC" if exchange_segment == "NSE" else "INTRA")
            )

            order_payload = {
                "transactionType": str(signal.get('signal_type', 'BUY')).upper(),
                "exchangeSegment": str(exchange_segment).upper(),
                "productType": str(product_type).upper(),
                "orderType": "MARKET",
                "validity": "DAY",
                "price": 0.0,
                "triggerPrice": 0.0,
                "tradingSymbol": (resolved or {}).get("trading_symbol") or signal.get('symbol'),
                "securityId": (resolved or {}).get("security_id") or metadata.get('security_id') or metadata.get('securityId'),
                "quantity": int(quantity or 1),
                "correlationId": signal.get('signal_id'),
                "metadata": {
                    **metadata,
                    "strategy_name": signal.get("strategy_name", ""),
                },
            }

            if not order_payload.get("securityId"):
                # Retry once via security master refresh
                try:
                    from src.services.dhan_client import get_dhan_client as _retry_dc
                    _rdc = _retry_dc()
                    _rdc.refresh_security_master()
                    _resolved2 = _rdc.resolve_security_details(signal.get('symbol', ''), 'BUY', metadata)
                    if _resolved2 and _resolved2.get('security_id'):
                        order_payload['securityId'] = _resolved2['security_id']
                        order_payload['tradingSymbol'] = _resolved2.get('trading_symbol', order_payload['tradingSymbol'])
                        self.logger.info(f"securityId resolved on retry: {order_payload['securityId']}")
                    else:
                        self.logger.error(
                            f"securityId unresolved after retry for {signal.get('symbol')} — order rejected"
                        )
                        return
                except Exception as _sec_err:
                    self.logger.error(f"securityId retry failed ({_sec_err}) — order rejected")
                    return

            # ----------------------------------------------------------
            # Phase 7.2: SEBI order tagging (algo ID on every order)
            # ----------------------------------------------------------
            order_payload = sebi_equity_validator.tag_order(order_payload)

            # ----------------------------------------------------------
            # Broker translation — convert DhanHQ payload to Kotak format
            # when the execution router has directed this order to Kotak Neo.
            # Kotak requires pTrdSymbol (e.g. RELIANCE-EQ) not the bare
            # DhanHQ symbol; also strips securityId (DhanHQ-only field).
            # Data plane (symbol resolution) always stays on DhanHQ above.
            # ----------------------------------------------------------
            from src.services.kotak_neo_client import KotakNeoClient
            if isinstance(exec_client, KotakNeoClient):
                order_payload = await instrument_translator.translate_for_kotak(
                    order_payload, exec_client
                )
                self.logger.info(
                    f"Payload translated for Kotak Neo: "
                    f"symbol={order_payload.get('tradingSymbol')}  "
                    f"seg={order_payload.get('exchangeSegment')}"
                )

            # ----------------------------------------------------------
            # Phase 7.4: High-throughput tranche execution
            # Uses DhanHQ place_slice_order for auto-slicing, or
            # concurrent tranche placement for 10+ trades/sec.
            # ----------------------------------------------------------
            total_qty = int(order_payload["quantity"])
            tranches = sebi_equity_validator.split_into_tranches(total_qty)

            all_order_ids = []

            if len(tranches) == 1:
                # Single order — place directly
                try:
                    oid = await exec_client.place_order(order_payload)
                    if oid:
                        clear_broker_errors()
                    all_order_ids.append(oid)
                except Exception as _order_err:
                    report_broker_error()
                    raise _order_err
                sebi_equity_validator.increment_daily_orders()
            elif len(tranches) <= 3:
                # Small number of tranches — use DhanHQ slice order (broker handles splitting)
                try:
                    dhan_client = get_dhan_client()
                    result = await dhan_client.place_slice_order_async(
                        security_id=order_payload.get("securityId", ""),
                        exchange_segment=order_payload["exchangeSegment"],
                        transaction_type=order_payload["transactionType"],
                        quantity=total_qty,
                        order_type=order_payload.get("orderType", "MARKET"),
                        product_type=order_payload.get("productType", "CNC"),
                        price=order_payload.get("price", 0),
                        validity="IOC",
                        tag=order_payload.get("correlationId"),
                    )
                    oid = (result.get("data", {}) or {}).get("orderId", "SLICE-UNKNOWN")
                    all_order_ids.append(oid)
                    clear_broker_errors()
                    for _ in tranches:
                        sebi_equity_validator.increment_daily_orders()
                except Exception as _order_err:
                    report_broker_error()
                    raise _order_err
            else:
                # Many tranches — concurrent execution with asyncio.gather
                async def _place_tranche(tranche_qty: int, idx: int):
                    tranche_payload = {**order_payload, "quantity": tranche_qty}
                    try:
                        oid = await exec_client.place_order(tranche_payload)
                        if oid:
                            clear_broker_errors()
                        sebi_equity_validator.increment_daily_orders()
                        return oid
                    except Exception as _te:
                        report_broker_error()
                        self.logger.warning(f"Tranche {idx} failed: {_te}")
                        return None

                results = await asyncio.gather(
                    *[_place_tranche(tq, i) for i, tq in enumerate(tranches)],
                    return_exceptions=True
                )
                all_order_ids = [r for r in results if r and not isinstance(r, Exception)]

            order_id = all_order_ids[0] if all_order_ids else "UNKNOWN"
            filled_qty = total_qty
            self.logger.info(f"Order Placed. ID: {order_id} (tranches={len(tranches)})")

            # ── Alert: trade executed notification ──
            try:
                from src.services.alerting import alerting_service
                await alerting_service.send_trade_notification(
                    symbol=signal['symbol'],
                    action=signal.get('signal_type', 'BUY'),
                    quantity=filled_qty,
                    price=float(signal.get('entry_price', 0) or 0),
                    strategy=signal.get('strategy_name', 'unknown'),
                    order_id=str(order_id),
                )
            except Exception as _alert_err:
                self.logger.debug(f"Trade alert failed: {_alert_err}")

            # Publish Event — include full signal so PortfolioAgent can record position
            await self.publish_event("ORDER_FILLED", {
                "order_id": order_id,
                "symbol": signal['symbol'],
                "status": "FILLED",
                "signal": signal,
                "quantity": filled_qty,
            })

            # ----------------------------------------------------------
            # Phase 7.3: Audit trail — full trade lifecycle logging
            # B3.5/B5 FIX: persist genai_reason so AI decision is in DB,
            # not just in memory (survives restarts, satisfies SEBI audit).
            # ----------------------------------------------------------
            try:
                sig_meta   = signal.get('metadata') or {}
                genai_info = (
                    f"genai_reason={sig_meta.get('genai_reason', 'N/A')[:120]}, "
                    f"genai_conf={sig_meta.get('genai_confidence', 'N/A')}, "
                    f"genai_validated={sig_meta.get('genai_validated', 'N/A')}"
                )
                await db.execute(
                    """INSERT INTO execution_logs
                       (strategy_name, symbol, action, price, quantity,
                        execution_time, status, reason)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
                    signal.get('strategy_name', ''),
                    signal['symbol'],
                    signal.get('signal_type', 'BUY'),
                    float(signal.get('entry_price', 0) or 0),
                    filled_qty,
                    datetime.now(),
                    "FILLED",
                    (
                        f"SEBI_TAG={order_payload.get('tag','')}, "
                        f"tranches={len(tranches)}, "
                        f"risk_decision={decision.get('reason','')}, "
                        f"{genai_info}"
                    )
                )
            except Exception as log_err:
                self.logger.debug(f"Audit log insert failed: {log_err}")

            await db.execute(
                "INSERT INTO trades (order_id, symbol, signal_type, quantity, status) VALUES ($1, $2, $3, $4, $5)",
                str(order_id),
                signal['symbol'],
                signal['signal_type'],
                filled_qty,
                "FILLED"
            )

        except Exception as e:
            self.logger.error(f"Execution Failed: {e}")

    async def _request_user_approval(self, signal: Dict, decision: Dict):
        """
        Notify User for Manual Approval with AI-Generated Justification.
        Stores approval request in Redis cache with 30-second TTL.
        """
        self.logger.info(f"Requesting User Validation for {signal['symbol']}")
        
        # 1. Generate "The Why"
        justification = await self._generate_justification(signal, decision)
        
        # 2. Create Approval Request with Unique ID
        request_id = str(uuid4())
        now = datetime.now()
        expires_at = now + timedelta(seconds=30)
        
        approval_request = {
            "id": request_id,
            "signal": signal,
            "justification": justification,
            "decision": decision,
            "timestamp": now.isoformat(),
            "expiresAt": expires_at.isoformat(),
            "status": "PENDING"
        }
        
        # 3. Store in Redis cache with 30-second TTL
        try:
            await cache.set(
                f"approval_request:{request_id}",
                json.dumps(approval_request, default=str),
                ttl=30
            )
            
            # Also add to approvals list for easy retrieval
            pending_approvals = await cache.get("pending_approvals") or []
            if isinstance(pending_approvals, str):
                pending_approvals = json.loads(pending_approvals)
            
            pending_approvals.append({
                "id": request_id,
                "symbol": signal['symbol'],
                "timestamp": now.isoformat(),
                "expiresAt": expires_at.isoformat()
            })
            
            await cache.set(
                "pending_approvals",
                json.dumps(pending_approvals, default=str),
                ttl=30
            )
            
            self.logger.info(f"APPROVAL REQUEST STORED: {request_id} | {signal['symbol']} | Expires in 30s")
            self.logger.info(f"Justification: {justification}")
            
        except Exception as e:
            self.logger.error(f"Failed to store approval request in cache: {e}")

    async def _generate_justification(self, signal: Dict, decision: Dict) -> str:
        """
        Ask Gemini to explain the trade in plain English.
        Falls back to a structured template if Vertex AI is unavailable
        (common in paper-trade / local dev mode without GCP credentials).
        SEBI HYBRID mode: shown to investor before order approval.
        """
        # B19 FIX: structured fallback — never returns bare "Justification unavailable."
        def _template_justification() -> str:
            symbol       = signal.get('symbol', 'N/A')
            sig_type     = signal.get('signal_type', 'N/A')
            strategy     = signal.get('strategy_name', 'N/A')
            strength     = signal.get('strength', 0.0)
            regime       = signal.get('market_regime_at_signal', 'N/A')
            qty          = (decision.get('modifications') or {}).get('quantity', signal.get('quantity', 0))
            return (
                f"{sig_type} signal on {symbol} ({strategy}). "
                f"Signal strength {strength:.0%} in a {regime} regime. "
                f"Proposed quantity: {qty} units."
            )

        if not self.model or not ai_cost_tracker.should_use_ai("execution"):
            return _template_justification()

        try:
            prompt = f"""You are an expert Senior Trader. Explain why this trade should be taken \
to a junior trader. Be concise, persuasive, and data-driven.

Strategy: {signal.get('strategy_name')}
Symbol: {signal.get('symbol')}
Type: {signal.get('signal_type')}
Strength: {signal.get('strength', 0):.0%}
Regime: {signal.get('market_regime_at_signal')}

Output a 2-sentence plain-language justification."""

            response = await asyncio.to_thread(self.model.generate_content, prompt)

            # Track token usage
            _in_tok = getattr(getattr(response, 'usage_metadata', None), 'prompt_token_count', 0) or 200
            _out_tok = getattr(getattr(response, 'usage_metadata', None), 'candidates_token_count', 0) or 40
            await ai_cost_tracker.record_usage("execution", input_tokens=_in_tok, output_tokens=_out_tok)

            text = (response.text or "").strip()
            return text if text else _template_justification()

        except Exception as e:
            self.logger.warning(f"Justification generation failed (using template): {e}")
            return _template_justification()
        
    # ------------------------------------------------------------------
    # Options multi-leg execution
    # ------------------------------------------------------------------
    async def _execute_options_trade(self, signal: Dict, decision: Dict):
        """Route a multi-leg options signal through SEBI validation -> multi-leg executor."""
        try:
            # Normalize: legs/structure may be inside metadata for some strategies
            _meta = signal.get("metadata", {}) or {}
            if not signal.get("legs") and _meta.get("legs"):
                signal["legs"] = _meta["legs"]
            if not signal.get("structure_type"):
                signal["structure_type"] = _meta.get("structure") or signal.get("signal_type", "CUSTOM")
            if not signal.get("quantity") and decision.get("modifications", {}).get("quantity"):
                signal["quantity"] = decision["modifications"]["quantity"]

            # ── Paper mode: simulate options fill ──────────────────────
            _is_paper = bool(getattr(settings, "PAPER_TRADING", False)) or \
                        getattr(settings, "MODE", "LIVE") in ("PAPER", "LOCAL")
            if _is_paper:
                from src.core.agent_manager import is_market_open as _is_mkt_open
                if not _is_mkt_open():
                    self.logger.warning(
                        f"PAPER OPTIONS FILL BLOCKED (outside market hours): "
                        f"{signal.get('structure_type', 'CUSTOM')} {signal.get('symbol', '')} "
                        f"| strategy={signal.get('strategy_name', '')}"
                    )
                    return
                # ── Entry time gate for options (paper mode) ────────────────
                _entry_ok, _entry_reason = _is_entry_allowed(signal)
                if not _entry_ok:
                    self.logger.info(
                        f"PAPER OPTIONS ENTRY BLOCKED ({_entry_reason}): "
                        f"{signal.get('structure_type', 'CUSTOM')} {signal.get('symbol', '')} "
                        f"| strategy={signal.get('strategy_name', '')}"
                    )
                    return
                # ── End options entry gate ────────────────────────────────────
                sim_pos_id = f"SIM_OPT_{uuid4().hex[:10]}"
                legs_count = len(signal.get("legs", []))
                self.logger.info(
                    f"PAPER OPTIONS FILL: {signal.get('structure_type','CUSTOM')} "
                    f"{signal.get('symbol','')} | legs={legs_count} | ID={sim_pos_id}"
                )
                await self.publish_event("OPTIONS_ORDER_FILLED", {
                    "position_id": sim_pos_id,
                    "symbol": signal.get("symbol", ""),
                    "structure_type": signal.get("structure_type", "CUSTOM"),
                    "legs": legs_count,
                    "simulated": True,
                })
                # Also publish as ORDER_FILLED so PortfolioAgent tracks it
                await self.publish_event("ORDER_FILLED", {
                    "order_id": sim_pos_id,
                    "symbol": signal.get("symbol", ""),
                    "status": "FILLED",
                    "signal": signal,
                    "entry_price": float(signal.get("entry_price", 0) or 0),
                    "quantity": int(signal.get("quantity", 1) or 1),
                })
                return
            # ── End paper mode ─────────────────────────────────────────

            _ensure_options_imports()
            if not _options_loaded:
                self.logger.error("Options modules not available")
                return

            # Rebuild OptionsSignal from dict legs
            legs_raw = signal.get("legs", [])
            leg_signals = []
            for idx, l in enumerate(legs_raw):
                leg_signals.append(LegSignal(
                    leg_id=f"{signal.get('signal_id','')}_L{idx}",
                    symbol=signal.get("symbol", ""),
                    option_type=l.get("option_type", "CE"),
                    strike=float(l.get("strike", 0)),
                    expiry=signal.get("expiry", ""),
                    action=l.get("action", "BUY"),
                    quantity=int(l.get("quantity", 1)),
                    lot_size=int(l.get("lot_size", 1)),
                    premium=float(l.get("premium", 0)),
                ))

            opts_signal = OptionsSignal(
                signal_id=signal.get("signal_id", ""),
                strategy_name=signal.get("strategy_name", ""),
                symbol=signal.get("symbol", ""),
                legs=leg_signals,
                structure_type=signal.get("structure_type", "CUSTOM"),
                net_premium=float(signal.get("net_premium", 0)),
                max_profit=signal.get("max_profit"),
                max_loss=signal.get("max_loss"),
            )

            # 1. SEBI pre-trade validation — query real position counts from DB
            try:
                from src.database.postgres import db as _db
                # Per-underlying lots: sum all open options legs for this symbol
                _row_ul = await _db.fetchrow(
                    """
                    SELECT COALESCE(SUM(quantity), 0) AS lots
                    FROM options_positions
                    WHERE symbol = $1 AND status = 'OPEN'
                    """,
                    opts_signal.symbol,
                ) if _db.pool else None
                current_lots_ul = int((_row_ul["lots"] if _row_ul else 0) or 0)

                # Market-wide lots: all open options across every underlying
                _row_mw = await _db.fetchrow(
                    "SELECT COALESCE(SUM(quantity), 0) AS lots FROM options_positions WHERE status = 'OPEN'"
                ) if _db.pool else None
                market_wide_lots = int((_row_mw["lots"] if _row_mw else 0) or 0)

                # Open structure count for max-structures gate
                _row_sc = await _db.fetchrow(
                    "SELECT COUNT(*) AS cnt FROM options_positions WHERE status = 'OPEN'"
                ) if _db.pool else None
                open_structure_count = int((_row_sc["cnt"] if _row_sc else 0) or 0)

                available_margin = float(getattr(settings, "TRADING_CAPITAL", 1_000_000))
            except Exception as _e:
                if not settings.PAPER_TRADING:
                    # LIVE mode: cannot verify position limits — block the trade
                    self.logger.error(
                        f"LIVE TRADING — SEBI position DB query failed. BLOCKING options trade "
                        f"to prevent exchange position-limit breach: {_e}"
                    )
                    return
                else:
                    # PAPER mode: safe to continue with zero baseline
                    self.logger.warning(
                        f"PAPER TRADING — SEBI options DB query failed, using zero baseline: {_e}"
                    )
                    current_lots_ul = 0
                    market_wide_lots = 0
                    open_structure_count = 0
                    available_margin = None

            validation = sebi_validator.validate(
                opts_signal,
                current_positions_lots=current_lots_ul,
                market_wide_lots=market_wide_lots,
                available_margin=available_margin,
                open_structure_count=open_structure_count,
            )
            if not validation.approved:
                self.logger.warning(f"SEBI rejected options trade: {validation.violations}")
                return
            if validation.warnings:
                self.logger.info(f"SEBI warnings: {validation.warnings}")

            # 2. Execute multi-leg
            position = await multi_leg_executor.execute_signal(opts_signal)
            if not position:
                self.logger.error("Multi-leg execution returned None")
                return

            # 3. Track in position manager
            options_position_manager.add_position(position)

            self.logger.info(
                f"Options position opened: {position.position_id} | "
                f"{opts_signal.structure_type} | legs={len(position.legs)}"
            )

            await self.publish_event("OPTIONS_ORDER_FILLED", {
                "position_id": position.position_id,
                "symbol": opts_signal.symbol,
                "structure_type": opts_signal.structure_type,
                "legs": len(position.legs),
            })

        except Exception as e:
            self.logger.error(f"Options execution failed: {e}", exc_info=True)

    # ------------------------------------------------------------------
    # StatArb atomic pair execution
    # ------------------------------------------------------------------
    async def _execute_statarb_pair(self, signal: Dict, decision: Dict):
        """
        Execute a statistical arbitrage equity pair atomically.

        The BUY leg symbol is in signal['symbol'].
        The SELL leg details are in signal['metadata']['sell_leg']: {"symbol": str, "ratio": float}.

        Both legs are placed back-to-back with immediate rollback on partial fill.
        SEBI note: both legs must settle same-day (INTRA/MIS product type).
        """
        import logging
        metadata = signal.get("metadata", {}) or {}
        sell_leg_meta = metadata.get("sell_leg") or {}

        buy_symbol = signal.get("symbol", "")
        sell_symbol = sell_leg_meta.get("symbol", "")
        hedge_ratio = float(sell_leg_meta.get("ratio", 1.0))
        quantity = int((decision.get("modifications") or {}).get("quantity", signal.get("quantity", 1)))
        sell_qty = max(1, round(quantity * hedge_ratio))

        if not buy_symbol or not sell_symbol:
            self.logger.error(f"StatArb pair missing symbols: buy={buy_symbol} sell={sell_symbol}")
            return

        # ── Paper mode: simulate both legs ─────────────────────────────
        _is_paper = bool(getattr(settings, "PAPER_TRADING", False)) or \
                    getattr(settings, "MODE", "LIVE") in ("PAPER", "LOCAL")
        if _is_paper:
            # ── Entry time gate for StatArb (always INTRA) ────────────────
            _now_t = datetime.now().time()
            if _now_t >= time(15, 20):
                self.logger.info(
                    f"PAPER STATARB ENTRY BLOCKED (INTRA_POST_1520 at {_now_t.strftime('%H:%M:%S')}): "
                    f"{buy_symbol}/{sell_symbol}"
                )
                return
            # ── End StatArb entry gate ────────────────────────────────────
            sim_buy_id = f"SIM_{uuid4().hex[:12]}"
            sim_sell_id = f"SIM_{uuid4().hex[:12]}"
            self.logger.info(
                f"PAPER STATARB FILL: BUY {buy_symbol} x{quantity} | "
                f"SELL {sell_symbol} x{sell_qty} | pair={metadata.get('pair')}"
            )
            await self.publish_event("ORDER_FILLED", {
                "order_id": sim_buy_id,
                "symbol": buy_symbol,
                "status": "FILLED",
                "signal": signal,
                "quantity": quantity,
                "statarb_pair": {
                    "buy": {"symbol": buy_symbol, "order_id": sim_buy_id, "qty": quantity},
                    "sell": {"symbol": sell_symbol, "order_id": sim_sell_id, "qty": sell_qty},
                    "pair": metadata.get("pair", ""),
                },
            })
            return
        # ── End paper mode ─────────────────────────────────────────────

        dhan_client = get_dhan_client()
        self.logger.info(
            f"StatArb pair: BUY {buy_symbol} x{quantity} | SELL {sell_symbol} x{sell_qty} "
            f"(ratio={hedge_ratio:.3f}) | pair={metadata.get('pair')}"
        )

        # ── Leg 1: BUY the buy-leg symbol ──────────────────────────────────────
        buy_resolved = dhan_client.resolve_security_details(
            symbol=buy_symbol, signal_type="BUY", metadata={"instrument": "EQUITY_CASH"}
        ) or {}
        buy_payload = {
            "transactionType": "BUY",
            "exchangeSegment": buy_resolved.get("exchange_segment", "NSE"),
            "productType": "INTRA",  # MIS — both legs same session
            "orderType": "MARKET",
            "validity": "DAY",
            "price": 0.0,
            "triggerPrice": 0.0,
            "tradingSymbol": buy_resolved.get("trading_symbol") or buy_symbol,
            "securityId": buy_resolved.get("security_id"),
            "quantity": quantity,
            "correlationId": signal.get("signal_id", "") + "_BUY",
            "metadata": {
                "strategy_name": signal.get("strategy_name", ""),
                "strategy_type": "STATISTICAL_ARBITRAGE",
                "statarb_leg": "BUY",
                "pair": metadata.get("pair", ""),
            },
        }

        buy_order_id = None
        try:
            buy_order_id = await dhan_client.place_order(buy_payload)
            self.logger.info(f"StatArb BUY leg placed: {buy_symbol} → order_id={buy_order_id}")
        except Exception as e:
            self.logger.error(f"StatArb BUY leg FAILED for {buy_symbol}: {e} — no sell placed")
            return  # Do NOT proceed to sell if buy failed (prevents naked short)

        # ── Leg 2: SELL the sell-leg symbol ────────────────────────────────────
        sell_resolved = dhan_client.resolve_security_details(
            symbol=sell_symbol, signal_type="SELL", metadata={"instrument": "EQUITY_CASH"}
        ) or {}
        sell_payload = {
            "transactionType": "SELL",
            "exchangeSegment": sell_resolved.get("exchange_segment", "NSE"),
            "productType": "INTRA",
            "orderType": "MARKET",
            "validity": "DAY",
            "price": 0.0,
            "triggerPrice": 0.0,
            "tradingSymbol": sell_resolved.get("trading_symbol") or sell_symbol,
            "securityId": sell_resolved.get("security_id"),
            "quantity": sell_qty,
            "correlationId": signal.get("signal_id", "") + "_SELL",
            "metadata": {
                "strategy_name": signal.get("strategy_name", ""),
                "strategy_type": "STATISTICAL_ARBITRAGE",
                "statarb_leg": "SELL",
                "pair": metadata.get("pair", ""),
            },
        }

        sell_order_id = None
        try:
            sell_order_id = await dhan_client.place_order(sell_payload)
            self.logger.info(f"StatArb SELL leg placed: {sell_symbol} → order_id={sell_order_id}")
        except Exception as e:
            # SELL leg failed after BUY leg was placed → rollback by reversing the BUY
            self.logger.error(
                f"StatArb SELL leg FAILED for {sell_symbol}: {e}. "
                f"Rolling back BUY leg {buy_symbol} (order_id={buy_order_id})"
            )
            try:
                rollback_payload = {**buy_payload, "transactionType": "SELL",
                                    "correlationId": signal.get("signal_id", "") + "_ROLLBACK"}
                rollback_id = await dhan_client.place_order(rollback_payload)
                self.logger.info(f"StatArb rollback order placed: {rollback_id}")
            except Exception as rb_err:
                self.logger.critical(
                    f"StatArb rollback FAILED — directional exposure on {buy_symbol}! "
                    f"Manual intervention required. Roll-back error: {rb_err}"
                )
            return

        # ── Both legs filled — publish and log ─────────────────────────────────
        await self.publish_event("ORDER_FILLED", {
            "order_id": buy_order_id,
            "symbol": buy_symbol,
            "status": "FILLED",
            "signal": signal,
            "quantity": quantity,
            "statarb_pair": {
                "buy": {"symbol": buy_symbol, "order_id": buy_order_id, "qty": quantity},
                "sell": {"symbol": sell_symbol, "order_id": sell_order_id, "qty": sell_qty},
                "pair": metadata.get("pair", ""),
            },
        })

    async def on_orders_approved(self, payload: Dict[str, Any]):
        """
        Event Handler for SIGNALS_APPROVED.
        Routes to options, StatArb pairs, or equity execution based on signal content.
        v2: Concurrent processing of independent orders for 10+ trades/sec throughput.
        """
        orders = payload.get('orders', [])

        async def _route_order(order):
            signal = order.get("signal", {})
            metadata = signal.get("metadata", {}) or {}

            # ── Module guard (Medallion CEO Fix #2) ──────────────────────────────
            # Options-module strategies (BearPutSpread, IronCondor, etc.) must ONLY
            # execute on FNO instruments. Block equity-routed signals from these
            # strategies — prevents mis-classification causing equity fills on options
            # logic flow (e.g. ALPHA_BEARPUT_008 generating a plain equity signal).
            from src.services.order_type_router import get_strategy_module as _get_mod
            _strat_name = signal.get("strategy_name", "")
            _strat_module = _get_mod(_strat_name)
            if _strat_module == "Options":
                _has_legs = bool(
                    signal.get("legs") or signal.get("structure_type") or
                    metadata.get("legs") or metadata.get("structure")
                )
                _has_fno = str(metadata.get("instrument_type", "")).upper() in {
                    "CE", "PE", "CALL", "PUT", "OPT"
                } or "FNO" in str(metadata.get("exchange_segment", "")).upper()
                if not _has_legs and not _has_fno:
                    self.logger.warning(
                        f"MODULE_GUARD_BLOCKED: '{_strat_name}' is Options module but signal "
                        f"for '{signal.get('symbol','')}' has no options legs or FNO instrument. "
                        f"Signal rejected — options strategies must only execute on FNO instruments."
                    )
                    return
            # ── End module guard ──────────────────────────────────────────────────

            # ── Options multi-leg: explicit legs list or structure_type ────────
            _meta = metadata  # already extracted above
            if signal.get("legs") or signal.get("structure_type") or _meta.get("legs") or _meta.get("structure"):
                await self._execute_options_trade(signal, order.get("risk_decision", {}))

            # ── StatArb equity pairs: both legs must execute atomically ─────────
            elif metadata.get("strategy_type") == "STATISTICAL_ARBITRAGE" and metadata.get("sell_leg"):
                await self._execute_statarb_pair(signal, order.get("risk_decision", {}))

            else:
                await self.execute_trade(order)

        # Execute all independent orders concurrently
        if len(orders) > 1:
            await asyncio.gather(*[_route_order(o) for o in orders], return_exceptions=True)
        elif orders:
            await _route_order(orders[0])

        if orders:
            self.total_orders_sent = getattr(self, 'total_orders_sent', 0) + len(orders)
            logger.info(
                f"📊 EXECUTION TELEMETRY | orders_this_batch={len(orders)} "
                f"session_total_orders={self.total_orders_sent}"
            )
