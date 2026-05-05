"""
Manual Controls Service
========================
Central service for all user-driven overrides and manual choices.
Every override is:
  - Stored in Redis with an expiry (default 24h, or 30-day for persistent settings)
  - Logged to SEBI audit trail
  - Checked by the relevant agent/executor before acting

Controls managed here:
  1. Strategy Enable/Disable (per individual strategy)
  2. Strategy Active Set (subset to run in live/paper)
  3. Max Loss per Strategy (circuit breaker)
  4. Market Regime Override (1-hour default TTL)
  5. Position Sizing Multiplier (0.25x – 3.0x)
  6. Max Orders per Cycle (rate limiter)
  7. Instrument Blacklist / Whitelist
  8. Alert Thresholds (signal strength, min score)
  9. Approval Timeout (MANUAL mode)
 10. Backtest Config (capital, slippage, commission)
 11. Max Daily Trades (cap total executions per day)
 12. Orders Per Second (SEBI rate cap, default 10)
 13. Min Confluence Score (quality gate, 1-5 scale)
 14. Min Quality Grade (AI quality threshold, A-F)
 15. IV Regime Preferences (allow/block per IV tier)
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from src.strategies.v1_live_registry import filter_v1_live_entries

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# FIX-V1-REBUILD: canonical live V1 strategy universe
# Source of truth for live ALPHA IDs comes from strategy_catalog.py.
# This registry keeps the richer UI/control metadata, then filters out
# framework and unregistered placeholders via v1_live_registry.
# ---------------------------------------------------------------------------

STRATEGY_REGISTRY: List[Dict[str, Any]] = [
    # ── Wave 1: Core Intraday / Options (18) ──────────────────────────────
    {"id": "ALPHA_ORB_001",        "name": "Opening Range Breakout",     "category": "MOMENTUM",       "module": "EQUITY",   "default_broker": "dhan",  "intraday": True},
    {"id": "ALPHA_VWAP_002",       "name": "VWAP Mean Reversion",        "category": "MEAN_REVERSION", "module": "EQUITY",   "default_broker": "dhan",  "intraday": True},
    {"id": "ALPHA_TREND_003",      "name": "Trend Following (Donchian)", "category": "TREND",          "module": "EQUITY",   "default_broker": "kotak", "intraday": False},
    {"id": "ALPHA_OFI_004",        "name": "Order Flow Imbalance",       "category": "QUANT",          "module": "EQUITY",   "default_broker": "dhan",  "intraday": True},
    {"id": "ALPHA_SENTIMENT_005",  "name": "Sentiment Divergence",       "category": "MOMENTUM",       "module": "EQUITY",   "default_broker": "kotak", "intraday": False},
    {"id": "ALPHA_ML_006",         "name": "ML Structural Break",        "category": "ML",             "module": "EQUITY",   "default_broker": "kotak", "intraday": True},
    {"id": "ALPHA_BCS_007",        "name": "Bull Call Spread",           "category": "OPTIONS",        "module": "OPTIONS",  "default_broker": "dhan",  "intraday": False},
    {"id": "ALPHA_BEARPUT_008",    "name": "Bear Put Spread",            "category": "OPTIONS",        "module": "OPTIONS",  "default_broker": "dhan",  "intraday": False},
    {"id": "ALPHA_RATIO_009",      "name": "Ratio Spread",               "category": "OPTIONS",        "module": "OPTIONS",  "default_broker": "dhan",  "intraday": False},
    {"id": "ALPHA_CALENDAR_010",   "name": "Calendar Spread",            "category": "OPTIONS",        "module": "OPTIONS",  "default_broker": "dhan",  "intraday": False},
    {"id": "ALPHA_IRON_011",       "name": "Iron Condor",                "category": "OPTIONS",        "module": "OPTIONS",  "default_broker": "dhan",  "intraday": False},
    {"id": "ALPHA_BUTTERFLY_012",  "name": "Butterfly Spread",           "category": "OPTIONS",        "module": "OPTIONS",  "default_broker": "kotak", "intraday": False},
    {"id": "ALPHA_STRANGLE_013",   "name": "Long Strangle",              "category": "OPTIONS",        "module": "OPTIONS",  "default_broker": "kotak", "intraday": False},
    {"id": "ALPHA_STRADDLE_014",   "name": "Long Straddle",              "category": "VOLATILITY",     "module": "OPTIONS",  "default_broker": "kotak", "intraday": False},
    {"id": "ALPHA_VIX_015",        "name": "VIX Trading",                "category": "VOLATILITY",     "module": "OPTIONS",  "default_broker": "kotak", "intraday": False},
    {"id": "ALPHA_DELTA_016",      "name": "Delta Hedging",              "category": "HEDGING",        "module": "OPTIONS",  "default_broker": "kotak", "intraday": True},
    {"id": "ALPHA_PORT_017",       "name": "Portfolio Hedge",             "category": "HEDGING",        "module": "OPTIONS",  "default_broker": "kotak", "intraday": False},
    {"id": "ALPHA_PAIR_018",       "name": "Pair Trading",                "category": "MEAN_REVERSION", "module": "EQUITY",   "default_broker": "kotak", "intraday": False},
    # ── Wave 1.5: Swing Strategies (3) ────────────────────────────────────
    {"id": "ALPHA_BREAKOUT_101",   "name": "Swing Breakout",             "category": "SWING",          "module": "EQUITY",   "default_broker": "kotak", "intraday": False},
    {"id": "ALPHA_PULLBACK_102",   "name": "Trend Pullback",             "category": "SWING",          "module": "EQUITY",   "default_broker": "kotak", "intraday": False},
    {"id": "ALPHA_EMA_CROSS_104",  "name": "EMA Crossover",              "category": "MOMENTUM",       "module": "EQUITY",   "default_broker": "kotak", "intraday": False},
    # ── Wave 2: Rotation / Mean-Rev / Event / Vol (8) ─────────────────────
    {"id": "ALPHA_MOMENTUM_201",   "name": "Momentum Rotation",          "category": "MOMENTUM",       "module": "EQUITY",   "default_broker": "kotak", "intraday": False},
    {"id": "ALPHA_SECTOR_202",     "name": "Sector Rotation",            "category": "MOMENTUM",       "module": "EQUITY",   "default_broker": "kotak", "intraday": False},
    {"id": "ALPHA_BB_203",         "name": "BB Squeeze",                  "category": "MEAN_REVERSION", "module": "EQUITY",   "default_broker": "kotak", "intraday": False},
    {"id": "ALPHA_RSI_DIV_204",    "name": "RSI Divergence",             "category": "MEAN_REVERSION", "module": "EQUITY",   "default_broker": "kotak", "intraday": False},
    {"id": "ALPHA_EARN_205",       "name": "Earnings Momentum",          "category": "MOMENTUM",       "module": "EQUITY",   "default_broker": "kotak", "intraday": False},
    {"id": "ALPHA_GAP_206",        "name": "Gap Fill",                    "category": "MEAN_REVERSION", "module": "EQUITY",   "default_broker": "kotak", "intraday": True},
    {"id": "ALPHA_ATR_207",        "name": "ATR Breakout",               "category": "MOMENTUM",       "module": "OPTIONS",  "default_broker": "kotak", "intraday": False},
    {"id": "ALPHA_VOL_CRUSH_208",  "name": "Volatility Crush",           "category": "VOLATILITY",     "module": "OPTIONS",  "default_broker": "kotak", "intraday": True},
    # ── Quant / Statistical (3) ───────────────────────────────────────────
    {"id": "ALPHA_STAT_ARB_301",   "name": "Statistical Arbitrage",      "category": "QUANT",          "module": "EQUITY",   "default_broker": "kotak", "intraday": False},
    {"id": "ALPHA_VOL_ARB_401",    "name": "Volatility Arbitrage",       "category": "QUANT",          "module": "OPTIONS",  "default_broker": "dhan",  "intraday": False},
    {"id": "ALPHA_CROSS_MOM_402",  "name": "Cross-Sectional Momentum",   "category": "QUANT",          "module": "EQUITY",   "default_broker": "kotak", "intraday": False},
    # ── Wave 4: Options Premium (3) ───────────────────────────────────────
    {"id": "ALPHA_SHORT_STRADDLE_501",  "name": "Short Straddle",        "category": "THETA",          "module": "OPTIONS",  "default_broker": "dhan",  "intraday": True},
    {"id": "ALPHA_SHORT_STRANGLE_502",  "name": "Short Strangle",        "category": "THETA",          "module": "OPTIONS",  "default_broker": "dhan",  "intraday": True},
    {"id": "ALPHA_IRON_BUTTERFLY_503",  "name": "Iron Butterfly",        "category": "THETA",          "module": "OPTIONS",  "default_broker": "dhan",  "intraday": True},
    # ── Wave 3: Alpha Boost (6) ───────────────────────────────────────────
    {"id": "ALPHA_ORB_VWAP_307",   "name": "ORB+VWAP Fusion",            "category": "MOMENTUM",       "module": "EQUITY",   "default_broker": "dhan",  "intraday": True},
    {"id": "ALPHA_MR_SCALP_302",   "name": "Mean Reversion Scalper",     "category": "MEAN_REVERSION", "module": "EQUITY",   "default_broker": "dhan",  "intraday": True},
    {"id": "ALPHA_IDX_SCALP_303",  "name": "Index Options Scalper",      "category": "OPTIONS",        "module": "OPTIONS",  "default_broker": "dhan",  "intraday": True},
    {"id": "ALPHA_PFTH_304",       "name": "Power of First Hour",        "category": "MOMENTUM",       "module": "EQUITY",   "default_broker": "dhan",  "intraday": True},
    {"id": "ALPHA_RS_PAIR_305",    "name": "RS Pair Trade",              "category": "QUANT",          "module": "EQUITY",   "default_broker": "kotak", "intraday": False},
    {"id": "ALPHA_THETA_306",      "name": "Theta Capture",              "category": "THETA",          "module": "OPTIONS",  "default_broker": "dhan",  "intraday": False},
    # ── Wave 4: Deep Microstructure (1) ───────────────────────────────────
    {"id": "ALPHA_VP_OFI_403",     "name": "Volume Profile + OFI (20L)", "category": "MICRO",          "module": "EQUITY",   "default_broker": "dhan",  "intraday": True},    # ── Wave 5: Institutional Microstructure (1) ──────────────────────
    {"id": "ALPHA_VP_MICRO_405",   "name": "VP Micro + Tick Delta",      "category": "MICRO",          "module": "EQUITY",   "default_broker": "dhan",  "intraday": True},    # ── Wave 5.1: Nano Microstructure (1) ─────────────────────
    {"id": "ALPHA_VP_NANO_406",    "name": "VP Nano 200L Depth",         "category": "MICRO",          "module": "EQUITY",   "default_broker": "dhan",  "intraday": True},    # ── Phase 3: Dynamic Options (3) ──────────────────────────────
    {"id": "ALPHA_DIAG_041",       "name": "Diagonal Spread",            "category": "THETA",          "module": "OPTIONS",  "default_broker": "kotak", "intraday": False},
    {"id": "ALPHA_RREV_042",       "name": "Risk Reversal",              "category": "TREND",          "module": "OPTIONS",  "default_broker": "kotak", "intraday": True},
    {"id": "ALPHA_CREDIT_043",     "name": "Credit Spread",              "category": "THETA",          "module": "OPTIONS",  "default_broker": "kotak", "intraday": True},
    # ── Phase 3: Income Strategies (2) — Day 16 addition ──────────────────
    {"id": "ALPHA_CCALL_044",      "name": "Covered Call",               "category": "THETA",          "module": "OPTIONS",  "default_broker": "kotak", "intraday": False},
    {"id": "ALPHA_CSP_045",        "name": "Cash-Secured Put",           "category": "THETA",          "module": "OPTIONS",  "default_broker": "kotak", "intraday": False},
    # ── Phase 3: Protective + Volatility Strategies (2) — A+ Intelligence Layer ──
    {"id": "ALPHA_COLLAR_046",     "name": "Protective Collar",           "category": "HEDGE",          "module": "OPTIONS",  "default_broker": "kotak", "intraday": False},
    {"id": "ALPHA_RATIO_CW_047",   "name": "Ratio Call Write",            "category": "THETA",          "module": "OPTIONS",  "default_broker": "kotak", "intraday": False},
    # ── FIX-AUDIT-D20-H8: Universal AI Builder Strategies ─────────────────
    {"id": "AIBLD_001_EQUITY_MULTI",  "name": "AI Builder Equity Multi",  "category": "UNIVERSAL",      "module": "EQUITY",   "default_broker": "kotak", "intraday": False},
    {"id": "AIBLD_003_EQUITY_BEAR_TA", "name": "AI Builder Equity Bear TA", "category": "UNIVERSAL",      "module": "EQUITY",   "default_broker": "kotak", "intraday": False},
    {"id": "AIBLD_004_EQUITY_BULL_REV", "name": "AI Builder Equity Bull Reversal", "category": "UNIVERSAL",      "module": "EQUITY",   "default_broker": "kotak", "intraday": False},
    {"id": "AIBLD_002_OPTIONS_IC",    "name": "AI Builder Options IC",    "category": "UNIVERSAL",      "module": "OPTIONS",  "default_broker": "dhan",  "intraday": False},
]

STRATEGY_REGISTRY = filter_v1_live_entries(STRATEGY_REGISTRY)

STRATEGY_IDS = {s["id"] for s in STRATEGY_REGISTRY}

# ---------------------------------------------------------------------------
# Redis key helpers (all prefixed mc_ = manual_controls)
# ---------------------------------------------------------------------------

def _k(suffix: str) -> str:
    return f"mc_{suffix}"


async def _append_capped_log(cache, key: str, entry: Dict[str, Any], limit: int = 5000) -> None:
    raw = await cache.get(key)
    log: List[Dict[str, Any]] = json.loads(raw) if raw else []
    log.append(entry)
    if len(log) > limit:
        log = log[-limit:]
    await cache.set(key, json.dumps(log), ttl=86400 * 90)


def _build_command_entry(action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    strategy_id = payload.get("strategy_id", payload.get("id", None))
    operator = payload.get("operator", payload.get("user", "system"))
    return {
        "command_id": payload.get("command_id", f"mc_{uuid4().hex}"),
        "ts": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "operator": operator,
        "strategy_id": strategy_id,
        "status": payload.get("status", "applied"),
        "reason": payload.get("reason", ""),
        "scope": payload.get("scope", "manual_controls"),
        **payload,
    }

# ---------------------------------------------------------------------------
# SEBI audit helper
# ---------------------------------------------------------------------------

async def _audit(cache, action: str, payload: Dict[str, Any]) -> None:
    """Append an entry to the SEBI audit ring-buffer in Redis (last 5000 events)
    AND persist to the sebi_audit_log Postgres table for permanent compliance."""
    try:
        entry = _build_command_entry(action, payload)
        # ── Redis (fast, ephemeral — 90 day TTL) ──
        await _append_capped_log(cache, _k("audit_log"), entry)
        await _append_capped_log(cache, _k("command_journal"), entry)

        # ── Postgres (permanent SEBI compliance trail — B7 fix) ──
        try:
            from src.database.postgres import db
            if db.pool:
                async with db.pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO sebi_audit_log (ts, action, operator, strategy_id, payload)
                        VALUES (NOW(), $1, $2, $3, $4::jsonb)
                        """,
                        action,
                        entry.get("operator", "system"),
                        entry.get("strategy_id", None),
                        json.dumps(entry),
                    )
        except Exception as pg_exc:
            logger.warning("SEBI audit Postgres write failed (Redis succeeded): %s", pg_exc)

    except Exception as exc:
        logger.warning("SEBI audit write failed: %s", exc)


async def record_command(cache, action: str, payload: Dict[str, Any]) -> None:
    """Public wrapper for journaling privileged control-plane actions."""
    await _audit(cache, action, payload)


async def _read_log_entries(cache, suffix: str) -> tuple[List[Dict[str, Any]], Optional[str], bool]:
    label = suffix
    try:
        raw = await cache.get(_k(suffix))
    except Exception as exc:
        logger.warning("Failed to read %s cache: %s", label, exc)
        return [], f"{label} unavailable", False

    if not raw:
        return [], None, False

    try:
        entries = json.loads(raw)
    except Exception:
        logger.warning("Failed to decode %s cache payload", label)
        return [], f"{label} payload invalid", True

    if not isinstance(entries, list):
        logger.warning("Unexpected %s cache payload type: %s", label, type(entries).__name__)
        return [], f"{label} payload invalid", True

    return [entry for entry in entries if isinstance(entry, dict)], None, True


async def get_audit_log(cache, limit: int = 100) -> Dict[str, Any]:
    entries, error, _ = await _read_log_entries(cache, "audit_log")
    payload = {"entries": entries[-limit:], "total": len(entries)}
    if error:
        payload["error"] = error
    return payload


async def get_command_journal(
    cache,
    limit: int = 100,
    action: Optional[str] = None,
    strategy_id: Optional[str] = None,
) -> Dict[str, Any]:
    entries, error, found = await _read_log_entries(cache, "command_journal")
    source = "command_journal"

    if error or not found:
        fallback_entries, fallback_error, _ = await _read_log_entries(cache, "audit_log")
        entries = fallback_entries
        source = "audit_log_fallback"
        if error is None:
            error = fallback_error

    if action:
        entries = [entry for entry in entries if entry.get("action") == action]
    if strategy_id:
        entries = [entry for entry in entries if entry.get("strategy_id") == strategy_id]

    payload = {
        "entries": entries[-limit:],
        "total": len(entries),
        "source": source,
    }
    if error:
        payload["error"] = error
    return payload


TEXT_COMMAND_EXAMPLES: List[str] = [
    "disable equity scanner",
    "enable option scanner",
    "disable leg monitor",
    "set approval timeout to 45 seconds",
    "set regime override to bear for 30 minutes",
    "clear regime override",
    "set position sizing to 0.5x for 4 hours",
    "set rate limit to 6 orders per cycle",
]


def _normalize_text_command(command: str) -> str:
    return " ".join(command.strip().lower().split())


def preview_text_command(command: str, operator: str = "system", reason: str = "") -> Dict[str, Any]:
    normalized = _normalize_text_command(command)
    if not normalized:
        return {
            "success": False,
            "recognized": False,
            "command": command,
            "error": "Text command cannot be empty",
            "supported_examples": TEXT_COMMAND_EXAMPLES,
        }

    toggle_match = re.fullmatch(r"(enable|disable)\s+(equity|option|options)\s+scanner", normalized)
    if toggle_match:
        verb, target = toggle_match.groups()
        enabled = verb == "enable"
        target_name = "equity" if target == "equity" else "option"
        return {
            "success": True,
            "recognized": True,
            "command": command,
            "normalized_command": normalized,
            "intent": f"toggle_{target_name}_scanner",
            "scope": "text_admin",
            "mutates_state": True,
            "requires_confirmation": True,
            "operator": operator or "system",
            "reason": reason or f"text_command:{normalized}",
            "summary": f"{verb.title()} {target_name} scanner",
            "parameters": {"enabled": enabled},
        }

    legmonitor_match = re.fullmatch(r"(enable|disable)\s+leg\s*monitor", normalized)
    if legmonitor_match:
        verb = legmonitor_match.group(1)
        enabled = verb == "enable"
        return {
            "success": True,
            "recognized": True,
            "command": command,
            "normalized_command": normalized,
            "intent": "toggle_legmonitor",
            "scope": "text_admin",
            "mutates_state": True,
            "requires_confirmation": True,
            "operator": operator or "system",
            "reason": reason or f"text_command:{normalized}",
            "summary": f"{verb.title()} leg monitor",
            "parameters": {"enabled": enabled},
        }

    approval_match = re.fullmatch(r"set\s+approval\s+timeout\s+to\s+(\d+)\s+seconds?", normalized)
    if approval_match:
        timeout_seconds = int(approval_match.group(1))
        return {
            "success": True,
            "recognized": True,
            "command": command,
            "normalized_command": normalized,
            "intent": "set_approval_timeout",
            "scope": "text_admin",
            "mutates_state": True,
            "requires_confirmation": True,
            "operator": operator or "system",
            "reason": reason or f"text_command:{normalized}",
            "summary": f"Set approval timeout to {timeout_seconds} seconds",
            "parameters": {"timeout_seconds": timeout_seconds},
        }

    regime_match = re.fullmatch(
        r"set\s+regime\s+override\s+to\s+(bull|bear|sideways|volatile)(?:\s+for\s+(\d+)\s+minutes?)?",
        normalized,
    )
    if regime_match:
        regime, duration_raw = regime_match.groups()
        duration_minutes = int(duration_raw) if duration_raw else 60
        return {
            "success": True,
            "recognized": True,
            "command": command,
            "normalized_command": normalized,
            "intent": "set_regime_override",
            "scope": "text_admin",
            "mutates_state": True,
            "requires_confirmation": True,
            "operator": operator or "system",
            "reason": reason or f"text_command:{normalized}",
            "summary": f"Set regime override to {regime.upper()} for {duration_minutes} minutes",
            "parameters": {"regime": regime.upper(), "duration_minutes": duration_minutes},
        }

    if normalized == "clear regime override":
        return {
            "success": True,
            "recognized": True,
            "command": command,
            "normalized_command": normalized,
            "intent": "clear_regime_override",
            "scope": "text_admin",
            "mutates_state": True,
            "requires_confirmation": True,
            "operator": operator or "system",
            "reason": reason or f"text_command:{normalized}",
            "summary": "Clear active regime override",
            "parameters": {},
        }

    sizing_match = re.fullmatch(
        r"set\s+position\s+sizing\s+to\s+(\d+(?:\.\d+)?)x(?:\s+for\s+(\d+)\s+hours?)?",
        normalized,
    )
    if sizing_match:
        multiplier_raw, duration_raw = sizing_match.groups()
        multiplier = float(multiplier_raw)
        duration_hours = int(duration_raw) if duration_raw else 4
        return {
            "success": True,
            "recognized": True,
            "command": command,
            "normalized_command": normalized,
            "intent": "set_position_sizing",
            "scope": "text_admin",
            "mutates_state": True,
            "requires_confirmation": True,
            "operator": operator or "system",
            "reason": reason or f"text_command:{normalized}",
            "summary": f"Set position sizing to {multiplier}x for {duration_hours} hours",
            "parameters": {"multiplier": multiplier, "duration_hours": duration_hours},
        }

    rate_limit_match = re.fullmatch(
        r"set\s+rate\s+limit\s+to\s+(\d+)\s+orders?\s+per\s+cycle",
        normalized,
    )
    if rate_limit_match:
        max_orders_per_cycle = int(rate_limit_match.group(1))
        return {
            "success": True,
            "recognized": True,
            "command": command,
            "normalized_command": normalized,
            "intent": "set_rate_limit",
            "scope": "text_admin",
            "mutates_state": True,
            "requires_confirmation": True,
            "operator": operator or "system",
            "reason": reason or f"text_command:{normalized}",
            "summary": f"Set rate limit to {max_orders_per_cycle} orders per cycle",
            "parameters": {"max_orders_per_cycle": max_orders_per_cycle},
        }

    return {
        "success": False,
        "recognized": False,
        "command": command,
        "normalized_command": normalized,
        "error": "Unsupported text command",
        "supported_examples": TEXT_COMMAND_EXAMPLES,
    }


async def process_text_command(
    cache,
    command: str,
    dry_run: bool = True,
    operator: str = "system",
    reason: str = "",
) -> Dict[str, Any]:
    plan = preview_text_command(command, operator=operator, reason=reason)

    if not plan.get("recognized"):
        await record_command(
            cache,
            "text_command_rejected",
            {
                "scope": "text_admin",
                "operator": operator or "system",
                "status": "rejected",
                "reason": reason or "unsupported_text_command",
                "text_command": command,
                "error": plan.get("error", "Unsupported text command"),
            },
        )
        return {**plan, "dry_run": dry_run}

    if dry_run:
        await record_command(
            cache,
            "text_command_preview",
            {
                "scope": "text_admin",
                "operator": plan["operator"],
                "status": "preview",
                "reason": plan["reason"],
                "text_command": command,
                "intent": plan["intent"],
                "parameters": plan["parameters"],
            },
        )
        return {"success": True, "recognized": True, "dry_run": True, "plan": plan}

    await record_command(
        cache,
        "text_command_execute",
        {
            "scope": "text_admin",
            "operator": plan["operator"],
            "status": "requested",
            "reason": plan["reason"],
            "text_command": command,
            "intent": plan["intent"],
            "parameters": plan["parameters"],
        },
    )

    intent = plan["intent"]
    parameters = plan["parameters"]
    plan_reason = plan["reason"]

    if intent == "toggle_equity_scanner":
        result = await toggle_equity_scanner(cache, parameters["enabled"], plan_reason)
    elif intent == "toggle_option_scanner":
        result = await toggle_option_scanner(cache, parameters["enabled"], plan_reason)
    elif intent == "toggle_legmonitor":
        result = await toggle_legmonitor(cache, parameters["enabled"], plan_reason)
    elif intent == "set_approval_timeout":
        result = await set_approval_timeout(cache, parameters["timeout_seconds"], plan_reason)
    elif intent == "set_regime_override":
        result = await set_regime_override(
            cache,
            parameters["regime"],
            parameters["duration_minutes"],
            plan_reason,
        )
    elif intent == "clear_regime_override":
        result = await clear_regime_override(cache)
    elif intent == "set_position_sizing":
        result = await set_position_sizing(
            cache,
            parameters["multiplier"],
            parameters["duration_hours"],
            plan_reason,
        )
    elif intent == "set_rate_limit":
        result = await set_rate_limit(cache, parameters["max_orders_per_cycle"], plan_reason)
    else:
        result = {"success": False, "error": f"Unsupported text intent: {intent}"}

    return {
        "success": bool(result.get("success", True)),
        "recognized": True,
        "dry_run": False,
        "plan": plan,
        "result": result,
    }

# ===========================================================================
# 1. STRATEGY ENABLE / DISABLE
# ===========================================================================

async def get_strategy_states(cache) -> List[Dict[str, Any]]:
    """Return all strategies with their enabled flag, circuit-breaker state, and today's P&L."""
    disabled_raw = await cache.get(_k("disabled_strategies"))
    disabled: set = set(json.loads(disabled_raw)) if disabled_raw else set()

    cb_raw = await cache.get(_k("circuit_breakers"))
    circuit_breakers: Dict = json.loads(cb_raw) if cb_raw else {}

    pnl_raw = await cache.get(_k("strategy_daily_pnl"))
    daily_pnl: Dict = json.loads(pnl_raw) if pnl_raw else {}

    result = []
    for s in STRATEGY_REGISTRY:
        sid = s["id"]
        cb = circuit_breakers.get(sid, {})
        result.append({
            **s,
            "enabled":           sid not in disabled,
            "circuit_breaker_triggered": cb.get("triggered", False),
            "circuit_breaker_reason":    cb.get("reason", ""),
            "today_pnl":                 round(daily_pnl.get(sid, 0.0), 2),
            "max_loss":                  cb.get("max_loss", None),
            "max_loss_pct":              cb.get("max_loss_pct", None),
        })
    return result


async def toggle_strategy(cache, strategy_id: str, enabled: bool, reason: str = "") -> Dict[str, Any]:
    """Enable or disable a strategy. Logged to SEBI audit trail."""
    if strategy_id not in STRATEGY_IDS:
        return {"success": False, "error": f"Unknown strategy: {strategy_id}"}

    raw = await cache.get(_k("disabled_strategies"))
    disabled: set = set(json.loads(raw)) if raw else set()

    prev = strategy_id not in disabled
    if enabled:
        disabled.discard(strategy_id)
    else:
        disabled.add(strategy_id)

    await cache.set(_k("disabled_strategies"), json.dumps(list(disabled)), ttl=86400 * 30)
    await _audit(cache, "strategy_toggle", {
        "strategy_id": strategy_id,
        "previous": prev,
        "new": enabled,
        "reason": reason or "user_manual",
    })
    logger.info("Strategy %s: %s → %s (reason: %s)", strategy_id, "ON" if prev else "OFF", "ON" if enabled else "OFF", reason)
    return {"success": True, "strategy_id": strategy_id, "enabled": enabled}


async def bulk_toggle_strategies(cache, strategy_ids: List[str], enabled: bool, reason: str = "") -> Dict[str, Any]:
    """Enable/disable multiple strategies atomically."""
    results = []
    for sid in strategy_ids:
        r = await toggle_strategy(cache, sid, enabled, reason)
        results.append(r)
    return {"success": True, "results": results, "count": len(results)}


def is_strategy_enabled(disabled_ids: set, strategy_id: str) -> bool:
    """Synchronous check (used in hot path by agents)."""
    return strategy_id not in disabled_ids

# ===========================================================================
# 2. STRATEGY ACTIVE SET  (subset for live/paper execution)
# ===========================================================================

async def get_active_set(cache) -> Dict[str, Any]:
    """Return the active strategy subset. Empty list means 'all enabled strategies'."""
    raw = await cache.get(_k("active_strategy_set"))
    subset: List[str] = json.loads(raw) if raw else []
    return {
        "active_set":   subset,
        "mode":         "subset" if subset else "all_enabled",
        "count":        len(subset) if subset else len(STRATEGY_REGISTRY),
    }


async def set_active_set(cache, strategy_ids: List[str], reason: str = "") -> Dict[str, Any]:
    """Set the live-execution subset. Pass empty list to restore 'all enabled'."""
    invalid = [s for s in strategy_ids if s not in STRATEGY_IDS]
    if invalid:
        return {"success": False, "error": f"Unknown strategy IDs: {invalid}"}

    await cache.set(_k("active_strategy_set"), json.dumps(strategy_ids), ttl=86400 * 30)
    await _audit(cache, "active_set_change", {
        "strategy_ids": strategy_ids,
        "mode": "subset" if strategy_ids else "all_enabled",
        "reason": reason or "user_manual",
    })
    return {
        "success": True,
        "active_set": strategy_ids,
        "mode": "subset" if strategy_ids else "all_enabled",
        "count": len(strategy_ids) if strategy_ids else len(STRATEGY_REGISTRY),
    }

# ===========================================================================
# 3. MAX LOSS PER STRATEGY  (circuit breaker)
# ===========================================================================

async def set_strategy_limit(cache, strategy_id: str, max_loss: float, max_loss_pct: float) -> Dict[str, Any]:
    """Set max daily loss for a strategy. When breached, strategy auto-disables."""
    if strategy_id not in STRATEGY_IDS:
        return {"success": False, "error": f"Unknown strategy: {strategy_id}"}
    if max_loss <= 0 and max_loss_pct <= 0:
        return {"success": False, "error": "max_loss or max_loss_pct must be positive"}

    raw = await cache.get(_k("circuit_breakers"))
    cbs: Dict = json.loads(raw) if raw else {}
    cbs[strategy_id] = {
        **cbs.get(strategy_id, {}),
        "max_loss":     abs(max_loss),
        "max_loss_pct": abs(max_loss_pct),
        "set_at":       datetime.now(timezone.utc).isoformat(),
        "triggered":    False,
    }
    await cache.set(_k("circuit_breakers"), json.dumps(cbs), ttl=86400 * 30)
    await _audit(cache, "circuit_breaker_set", {
        "strategy_id": strategy_id,
        "max_loss": max_loss,
        "max_loss_pct": max_loss_pct,
    })
    return {"success": True, "strategy_id": strategy_id, "max_loss": max_loss, "max_loss_pct": max_loss_pct}


async def update_strategy_pnl(cache, strategy_id: str, pnl_delta: float) -> None:
    """Called by execution agent after each trade to update daily P&L and check circuit breakers."""
    if strategy_id not in STRATEGY_IDS:
        return

    # Update daily P&L
    raw = await cache.get(_k("strategy_daily_pnl"))
    pnl_map: Dict = json.loads(raw) if raw else {}
    pnl_map[strategy_id] = pnl_map.get(strategy_id, 0.0) + pnl_delta
    today_pnl = pnl_map[strategy_id]
    await cache.set(_k("strategy_daily_pnl"), json.dumps(pnl_map), ttl=86400)  # reset daily

    # Check circuit breaker
    cb_raw = await cache.get(_k("circuit_breakers"))
    cbs: Dict = json.loads(cb_raw) if cb_raw else {}
    cb = cbs.get(strategy_id, {})

    if cb and not cb.get("triggered", False):
        breach_abs = cb.get("max_loss") and today_pnl < -(cb["max_loss"])
        breach_pct = False  # pct needs capital context — checked separately
        if breach_abs or breach_pct:
            cbs[strategy_id]["triggered"] = True
            cbs[strategy_id]["reason"] = f"Daily P&L {today_pnl:.0f} breached limit -{cb.get('max_loss', 0):.0f}"
            cbs[strategy_id]["triggered_at"] = datetime.now(timezone.utc).isoformat()
            await cache.set(_k("circuit_breakers"), json.dumps(cbs), ttl=86400 * 30)
            # Auto-disable the strategy
            await toggle_strategy(cache, strategy_id, False, reason=f"circuit_breaker:{today_pnl:.0f}")
            logger.warning("CIRCUIT BREAKER fired for %s: today_pnl=%.2f", strategy_id, today_pnl)


async def reset_circuit_breaker(cache, strategy_id: str) -> Dict[str, Any]:
    """Manually reset a triggered circuit breaker (re-enables the strategy)."""
    if strategy_id not in STRATEGY_IDS:
        return {"success": False, "error": f"Unknown strategy: {strategy_id}"}

    raw = await cache.get(_k("circuit_breakers"))
    cbs: Dict = json.loads(raw) if raw else {}
    if strategy_id in cbs:
        cbs[strategy_id]["triggered"] = False
        cbs[strategy_id]["reason"] = ""
        await cache.set(_k("circuit_breakers"), json.dumps(cbs), ttl=86400 * 30)

    # Also re-enable the strategy
    await toggle_strategy(cache, strategy_id, True, reason="circuit_breaker_manual_reset")
    return {"success": True, "strategy_id": strategy_id, "message": "Circuit breaker reset + strategy re-enabled"}

# ===========================================================================
# 4. MARKET REGIME OVERRIDE (1-hour TTL by default)
# ===========================================================================

VALID_REGIMES = ("BULL", "BEAR", "SIDEWAYS", "VOLATILE")

async def get_regime_override(cache) -> Dict[str, Any]:
    raw = await cache.get(_k("regime_override"))
    if not raw:
        return {"active": False, "regime": None, "expires_at": None}
    data = json.loads(raw)
    return {"active": True, **data}


async def set_regime_override(cache, regime: str, duration_minutes: int = 60, reason: str = "") -> Dict[str, Any]:
    if regime.upper() not in VALID_REGIMES:
        return {"success": False, "error": f"Invalid regime. Must be one of: {VALID_REGIMES}"}

    expires_at = datetime.fromtimestamp(time.time() + duration_minutes * 60, tz=timezone.utc).isoformat()
    data = {
        "regime":       regime.upper(),
        "set_at":       datetime.now(timezone.utc).isoformat(),
        "expires_at":   expires_at,
        "duration_min": duration_minutes,
        "reason":       reason or "user_manual",
    }
    await cache.set(_k("regime_override"), json.dumps(data), ttl=duration_minutes * 60)
    await _audit(cache, "regime_override", data)
    return {"success": True, **data}


async def clear_regime_override(cache) -> Dict[str, Any]:
    await cache.delete(_k("regime_override"))
    await _audit(cache, "regime_override_cleared", {})
    return {"success": True, "message": "Regime override cleared — auto-detection resumed"}

# ===========================================================================
# 5. POSITION SIZING MULTIPLIER  (0.25x – 3.0x)
# ===========================================================================

async def get_position_sizing(cache) -> Dict[str, Any]:
    raw = await cache.get(_k("position_sizing_multiplier"))
    if not raw:
        return {"multiplier": 1.0, "is_overridden": False, "expires_at": None}
    data = json.loads(raw)
    return {"is_overridden": True, **data}


async def set_position_sizing(cache, multiplier: float, duration_hours: int = 4, reason: str = "") -> Dict[str, Any]:
    if not (0.1 <= multiplier <= 3.0):
        return {"success": False, "error": "Multiplier must be between 0.1 and 3.0"}

    expires_at = datetime.fromtimestamp(time.time() + duration_hours * 3600, tz=timezone.utc).isoformat()
    data = {
        "multiplier":   round(multiplier, 2),
        "set_at":       datetime.now(timezone.utc).isoformat(),
        "expires_at":   expires_at,
        "duration_hrs": duration_hours,
        "reason":       reason or "user_manual",
    }
    await cache.set(_k("position_sizing_multiplier"), json.dumps(data), ttl=duration_hours * 3600)
    await _audit(cache, "position_sizing_override", data)
    return {"success": True, **data}


async def clear_position_sizing(cache) -> Dict[str, Any]:
    await cache.delete(_k("position_sizing_multiplier"))
    await _audit(cache, "position_sizing_cleared", {})
    return {"success": True, "message": "Position sizing restored to 100%", "multiplier": 1.0}

# ===========================================================================
# 6. RATE LIMITER  (max orders per cycle)
# ===========================================================================

async def get_rate_limit(cache) -> Dict[str, Any]:
    raw = await cache.get(_k("rate_limit"))
    if not raw:
        return {"max_orders_per_cycle": 10, "is_overridden": False}
    return {"is_overridden": True, **json.loads(raw)}


async def set_rate_limit(cache, max_orders_per_cycle: int, reason: str = "") -> Dict[str, Any]:
    if not (1 <= max_orders_per_cycle <= 50):
        return {"success": False, "error": "max_orders_per_cycle must be between 1 and 50"}
    data = {
        "max_orders_per_cycle": max_orders_per_cycle,
        "set_at": datetime.now(timezone.utc).isoformat(),
        "reason": reason or "user_manual",
    }
    await cache.set(_k("rate_limit"), json.dumps(data), ttl=86400 * 30)
    await _audit(cache, "rate_limit_set", data)
    return {"success": True, **data}

# ===========================================================================
# 7. INSTRUMENT BLACKLIST
# ===========================================================================

async def get_instrument_filter(cache) -> Dict[str, Any]:
    raw = await cache.get(_k("instrument_blacklist"))
    blacklist: List[str] = json.loads(raw) if raw else []
    return {"blacklist": blacklist, "count": len(blacklist)}


async def add_to_blacklist(cache, symbols: List[str], reason: str = "") -> Dict[str, Any]:
    raw = await cache.get(_k("instrument_blacklist"))
    existing: List[str] = json.loads(raw) if raw else []
    added = []
    for sym in symbols:
        sym_upper = sym.strip().upper()
        if sym_upper and sym_upper not in existing:
            existing.append(sym_upper)
            added.append(sym_upper)
    await cache.set(_k("instrument_blacklist"), json.dumps(existing), ttl=86400 * 30)
    await _audit(cache, "blacklist_add", {"symbols": added, "reason": reason or "user_manual"})
    return {"success": True, "added": added, "blacklist": existing}


async def remove_from_blacklist(cache, symbols: List[str]) -> Dict[str, Any]:
    raw = await cache.get(_k("instrument_blacklist"))
    existing: List[str] = json.loads(raw) if raw else []
    removed = [s.upper() for s in symbols if s.upper() in existing]
    existing = [s for s in existing if s not in {x.upper() for x in symbols}]
    await cache.set(_k("instrument_blacklist"), json.dumps(existing), ttl=86400 * 30)
    await _audit(cache, "blacklist_remove", {"symbols": removed})
    return {"success": True, "removed": removed, "blacklist": existing}


def is_instrument_allowed(blacklist: List[str], symbol: str) -> bool:
    return symbol.upper() not in blacklist

# ===========================================================================
# 8. ALERT THRESHOLDS
# ===========================================================================

DEFAULT_ALERT_THRESHOLDS = {
    "min_signal_strength":  0.60,   # Only surface signals >= 60% strength
    "min_strategy_score":   0.55,   # Backtest score threshold for paper trade
    "vix_warning_level":    20.0,   # Alert when VIX crosses this
    "daily_loss_warning":   -2.0,   # % warn before kill switch
    "approval_sound":       True,   # Browser audio on new approval
}


async def get_alert_thresholds(cache) -> Dict[str, Any]:
    raw = await cache.get(_k("alert_thresholds"))
    if not raw:
        return {**DEFAULT_ALERT_THRESHOLDS, "is_overridden": False}
    return {"is_overridden": True, **json.loads(raw)}


async def set_alert_thresholds(cache, thresholds: Dict[str, Any]) -> Dict[str, Any]:
    current_raw = await cache.get(_k("alert_thresholds"))
    current: Dict = json.loads(current_raw) if current_raw else dict(DEFAULT_ALERT_THRESHOLDS)

    # Validate individual fields
    if "min_signal_strength" in thresholds:
        v = float(thresholds["min_signal_strength"])
        if not (0.0 <= v <= 1.0):
            return {"success": False, "error": "min_signal_strength must be 0.0–1.0"}
        current["min_signal_strength"] = v

    if "vix_warning_level" in thresholds:
        v = float(thresholds["vix_warning_level"])
        if not (5.0 <= v <= 100.0):
            return {"success": False, "error": "vix_warning_level must be 5–100"}
        current["vix_warning_level"] = v

    if "min_strategy_score" in thresholds:
        current["min_strategy_score"] = float(thresholds["min_strategy_score"])

    if "daily_loss_warning" in thresholds:
        v = float(thresholds["daily_loss_warning"])
        current["daily_loss_warning"] = min(v, 0.0)  # ensure negative

    if "approval_sound" in thresholds:
        current["approval_sound"] = bool(thresholds["approval_sound"])

    await cache.set(_k("alert_thresholds"), json.dumps(current), ttl=86400 * 30)
    await _audit(cache, "alert_thresholds_set", {"thresholds": current})
    return {"success": True, **current}

# ===========================================================================
# 9. APPROVAL TIMEOUT  (MANUAL mode)
# ===========================================================================

async def get_approval_timeout(cache) -> Dict[str, Any]:
    raw = await cache.get(_k("approval_timeout"))
    if not raw:
        return {"timeout_seconds": 30, "is_overridden": False}
    return {"is_overridden": True, **json.loads(raw)}


async def set_approval_timeout(cache, timeout_seconds: int, reason: str = "") -> Dict[str, Any]:
    if not (10 <= timeout_seconds <= 300):
        return {"success": False, "error": "timeout_seconds must be between 10 and 300"}
    data = {
        "timeout_seconds": timeout_seconds,
        "set_at": datetime.now(timezone.utc).isoformat(),
        "reason": reason or "user_manual",
    }
    await cache.set(_k("approval_timeout"), json.dumps(data), ttl=86400 * 30)
    await _audit(cache, "approval_timeout_set", data)
    return {"success": True, **data}

# ===========================================================================
# 10. BACKTEST CONFIG
# ===========================================================================

DEFAULT_BACKTEST_CONFIG = {
    "capital":           1_000_000,
    "slippage_bps":      5,          # basis points per trade
    "commission_per_order": 20,      # ₹ per order
    "start_date":        "2022-01-01",
    "end_date":          "",         # "" = today
    "strategy_ids":      [],         # [] = all
}


async def get_backtest_config(cache) -> Dict[str, Any]:
    raw = await cache.get(_k("backtest_config"))
    if not raw:
        return {**DEFAULT_BACKTEST_CONFIG, "is_overridden": False}
    return {"is_overridden": True, **json.loads(raw)}


async def set_backtest_config(cache, config: Dict[str, Any]) -> Dict[str, Any]:
    current: Dict = dict(DEFAULT_BACKTEST_CONFIG)

    if "capital" in config:
        v = float(config["capital"])
        if v < 10_000:
            return {"success": False, "error": "capital must be ≥ ₹10,000"}
        current["capital"] = v

    if "slippage_bps" in config:
        current["slippage_bps"] = max(0, int(config["slippage_bps"]))

    if "commission_per_order" in config:
        current["commission_per_order"] = max(0, float(config["commission_per_order"]))

    if "start_date" in config:
        current["start_date"] = str(config["start_date"])

    if "end_date" in config:
        current["end_date"] = str(config["end_date"])

    if "strategy_ids" in config:
        ids = config["strategy_ids"]
        invalid = [s for s in ids if s not in STRATEGY_IDS]
        if invalid:
            return {"success": False, "error": f"Unknown strategy IDs: {invalid}"}
        current["strategy_ids"] = ids

    await cache.set(_k("backtest_config"), json.dumps(current), ttl=86400 * 7)  # 7-day TTL
    return {"success": True, **current}

# ===========================================================================
# 11. MAX DAILY TRADES  (cap total trade executions per day)
# ===========================================================================

async def get_max_daily_trades(cache) -> Dict[str, Any]:
    """Return max daily trades setting. 0 = unlimited."""
    raw = await cache.get(_k("max_daily_trades"))
    if not raw:
        return {"max_daily_trades": 0, "is_overridden": False}
    return {"is_overridden": True, **json.loads(raw)}


async def set_max_daily_trades(cache, max_trades: int, reason: str = "") -> Dict[str, Any]:
    """Set a daily trade execution cap. 0 = unlimited, otherwise 1-500."""
    if max_trades < 0 or max_trades > 500:
        return {"success": False, "error": "max_daily_trades must be 0 (unlimited) or 1-500"}
    data = {
        "max_daily_trades": max_trades,
        "set_at": datetime.now(timezone.utc).isoformat(),
        "reason": reason or "user_manual",
    }
    await cache.set(_k("max_daily_trades"), json.dumps(data), ttl=86400 * 30)
    await _audit(cache, "max_daily_trades_set", data)
    return {"success": True, **data}


async def get_daily_trade_count(cache) -> int:
    """Return how many trades have been executed today."""
    raw = await cache.get(_k("daily_trade_count"))
    return int(raw) if raw else 0


async def increment_daily_trade_count(cache) -> int:
    """Increment the daily trade counter. Called by execution agent after each fill."""
    raw = await cache.get(_k("daily_trade_count"))
    count = (int(raw) if raw else 0) + 1
    await cache.set(_k("daily_trade_count"), str(count), ttl=86400)  # auto-reset daily
    return count


async def check_daily_trade_limit(cache) -> Dict[str, Any]:
    """Check if daily trade cap is reached. Returns allow=True/False."""
    settings = await get_max_daily_trades(cache)
    max_trades = settings.get("max_daily_trades", 0)
    if max_trades == 0:
        return {"allowed": True, "reason": "unlimited", "count": await get_daily_trade_count(cache)}
    count = await get_daily_trade_count(cache)
    if count >= max_trades:
        return {"allowed": False, "reason": f"Daily cap reached: {count}/{max_trades}", "count": count, "limit": max_trades}
    return {"allowed": True, "remaining": max_trades - count, "count": count, "limit": max_trades}

# ===========================================================================
# 12. ORDERS PER SECOND  (SEBI compliance rate cap)
# ===========================================================================

async def get_orders_per_second(cache) -> Dict[str, Any]:
    """Return SEBI orders-per-second cap. Default 10 (NSE non-co-location limit)."""
    raw = await cache.get(_k("orders_per_second"))
    if not raw:
        return {"orders_per_second": 10, "is_overridden": False}
    return {"is_overridden": True, **json.loads(raw)}


async def set_orders_per_second(cache, ops: int, reason: str = "") -> Dict[str, Any]:
    """Set SEBI orders-per-second cap. Range: 1-25 (default 10).
    SEBI/HO/MRD/DOP/P/CIR/2021/587: NSE non-co-location default is 10/sec."""
    if not (1 <= ops <= 25):
        return {"success": False, "error": "orders_per_second must be between 1 and 25"}
    data = {
        "orders_per_second": ops,
        "set_at": datetime.now(timezone.utc).isoformat(),
        "reason": reason or "user_manual",
    }
    await cache.set(_k("orders_per_second"), json.dumps(data), ttl=86400 * 30)
    await _audit(cache, "orders_per_second_set", data)
    return {"success": True, **data}

# ===========================================================================
# 13. MIN CONFLUENCE SCORE  (quality gate threshold)
# ===========================================================================

async def get_min_confluence_score(cache) -> Dict[str, Any]:
    """Return minimum confluence score (1-5). Default 3 (require 3-of-5 factors)."""
    raw = await cache.get(_k("min_confluence_score"))
    if not raw:
        return {"min_confluence_score": 3, "is_overridden": False}
    return {"is_overridden": True, **json.loads(raw)}


async def set_min_confluence_score(cache, score: int, reason: str = "") -> Dict[str, Any]:
    """Set minimum confluence score. 1 = very loose, 5 = perfect confluence only."""
    if not (1 <= score <= 5):
        return {"success": False, "error": "min_confluence_score must be between 1 and 5"}
    data = {
        "min_confluence_score": score,
        "set_at": datetime.now(timezone.utc).isoformat(),
        "reason": reason or "user_manual",
    }
    await cache.set(_k("min_confluence_score"), json.dumps(data), ttl=86400 * 30)
    await _audit(cache, "min_confluence_score_set", data)
    return {"success": True, **data}

# ===========================================================================
# 14. MIN QUALITY GRADE  (AI quality classifier threshold)
# ===========================================================================

VALID_GRADES = ("A", "B", "C", "D", "F")

async def get_min_quality_grade(cache) -> Dict[str, Any]:
    """Return minimum AI quality grade threshold. Default 'C'."""
    raw = await cache.get(_k("min_quality_grade"))
    if not raw:
        return {"min_quality_grade": "C", "is_overridden": False}
    return {"is_overridden": True, **json.loads(raw)}


async def set_min_quality_grade(cache, grade: str, reason: str = "") -> Dict[str, Any]:
    """Set minimum quality grade. A = only top signals, F = accept all."""
    grade = grade.upper()
    if grade not in VALID_GRADES:
        return {"success": False, "error": f"Invalid grade. Must be one of: {VALID_GRADES}"}
    data = {
        "min_quality_grade": grade,
        "set_at": datetime.now(timezone.utc).isoformat(),
        "reason": reason or "user_manual",
    }
    await cache.set(_k("min_quality_grade"), json.dumps(data), ttl=86400 * 30)
    await _audit(cache, "min_quality_grade_set", data)
    return {"success": True, **data}

# ===========================================================================
# 15. IV REGIME PREFERENCES  (allow/block per IV tier)
# ===========================================================================

VALID_IV_TIERS = ("IV_CHEAP", "IV_NORMAL", "IV_RICH", "IV_EXTREME")
DEFAULT_IV_PREFS = {tier: True for tier in VALID_IV_TIERS}  # all allowed by default

async def get_iv_regime_preferences(cache) -> Dict[str, Any]:
    """Return per-IV-tier allow/block preferences."""
    raw = await cache.get(_k("iv_regime_preferences"))
    if not raw:
        return {"tiers": dict(DEFAULT_IV_PREFS), "is_overridden": False}
    return {"is_overridden": True, **json.loads(raw)}


async def set_iv_regime_preferences(cache, tiers: Dict[str, bool], reason: str = "") -> Dict[str, Any]:
    """Set which IV tiers are allowed for trading.
    E.g., block IV_EXTREME to avoid selling premium in extreme vol."""
    invalid = [t for t in tiers if t not in VALID_IV_TIERS]
    if invalid:
        return {"success": False, "error": f"Invalid IV tiers: {invalid}. Valid: {VALID_IV_TIERS}"}
    # Merge with defaults so all tiers always have a value
    merged = dict(DEFAULT_IV_PREFS)
    merged.update(tiers)
    data = {
        "tiers": merged,
        "set_at": datetime.now(timezone.utc).isoformat(),
        "reason": reason or "user_manual",
    }
    await cache.set(_k("iv_regime_preferences"), json.dumps(data), ttl=86400 * 30)
    await _audit(cache, "iv_regime_preferences_set", data)
    return {"success": True, **data}


def is_iv_tier_allowed(prefs: Dict[str, bool], tier: str) -> bool:
    """Synchronous check (used in hot path by strategies)."""
    return prefs.get(tier, True)

# ===========================================================================
# AGGREGATE SNAPSHOT  (single call for UI state sync)
# ===========================================================================

async def get_all_controls(cache) -> Dict[str, Any]:
    """Return all manual control states in one shot for UI initialisation."""
    from asyncio import gather
    (
        strategies,
        active_set,
        regime_override,
        position_sizing,
        rate_limit,
        instrument_filter,
        alert_thresholds,
        approval_timeout,
        backtest_config,
        max_daily_trades,
        orders_per_second,
        min_confluence_score,
        min_quality_grade,
        iv_regime_preferences,
    ) = await gather(
        get_strategy_states(cache),
        get_active_set(cache),
        get_regime_override(cache),
        get_position_sizing(cache),
        get_rate_limit(cache),
        get_instrument_filter(cache),
        get_alert_thresholds(cache),
        get_approval_timeout(cache),
        get_backtest_config(cache),
        get_max_daily_trades(cache),
        get_orders_per_second(cache),
        get_min_confluence_score(cache),
        get_min_quality_grade(cache),
        get_iv_regime_preferences(cache),
    )
    daily_count = await get_daily_trade_count(cache)
    return {
        "strategies":           strategies,
        "active_set":           active_set,
        "regime_override":      regime_override,
        "position_sizing":      position_sizing,
        "rate_limit":           rate_limit,
        "instrument_filter":    instrument_filter,
        "alert_thresholds":     alert_thresholds,
        "approval_timeout":     approval_timeout,
        "backtest_config":      backtest_config,
        "max_daily_trades":     {**max_daily_trades, "today_count": daily_count},
        "orders_per_second":    orders_per_second,
        "min_confluence_score": min_confluence_score,
        "min_quality_grade":    min_quality_grade,
        "iv_regime_preferences":iv_regime_preferences,
    }


# ===========================================================================
# FIX-SCANNER-MC1: 16. SCANNER CONTROLS (Equity + Options + LegMonitor)
# ===========================================================================

SCANNER_CONTROL_DEFAULTS: Dict[str, Any] = {
    "equity_scanner_enabled": True,
    "option_scanner_enabled": True,
    "scan_frequency_sec": 180,          # 3-minute default
    "scanner_min_score": 0,             # 0 = use regime-adaptive default
    "scanner_concurrency": 12,          # asyncio semaphore limit (was 4)
    "scanner_ai_enabled": True,         # Gemini scout counter-validation
    "option_scanner_structures": [],    # [] = all 5 structures
    "option_scanner_equity_count": 0,   # 0 = use regime-adaptive default
    "option_scanner_min_score": 40,     # minimum structure score
    "option_scanner_gemini_enabled": True,
    "legmonitor_enabled": True,
    "legmonitor_max_loss_pct": 2.0,
    "legmonitor_profit_target_pct": 50.0,
    "legmonitor_exit_time": "15:10",
    "event_penalty_high": 15,
    "event_penalty_medium": 8,
    "event_penalty_low": 3,
}


async def get_scanner_controls(cache) -> Dict[str, Any]:
    """Return current scanner controls (merged with defaults)."""
    raw = await cache.get(_k("scanner_controls"))
    if not raw:
        return {"is_overridden": False, **SCANNER_CONTROL_DEFAULTS}
    stored = json.loads(raw)
    merged = {**SCANNER_CONTROL_DEFAULTS, **stored}
    return {"is_overridden": True, **merged}


async def set_scanner_controls(cache, controls: Dict[str, Any], reason: str = "") -> Dict[str, Any]:
    """Update scanner controls (partial update — only specified keys change)."""
    raw = await cache.get(_k("scanner_controls"))
    current = json.loads(raw) if raw else dict(SCANNER_CONTROL_DEFAULTS)
    current.update(controls)
    current["updated_at"] = datetime.now(timezone.utc).isoformat()
    current["reason"] = reason or "manual_update"
    await cache.set(_k("scanner_controls"), json.dumps(current), ttl=86400 * 30)
    await _audit(cache, "scanner_controls_updated", {
        "changes": controls,
        "reason": reason,
        "operator": controls.get("operator", "system"),
    })
    return {"success": True, **current}


async def toggle_equity_scanner(cache, enabled: bool, reason: str = "") -> Dict[str, Any]:
    """Enable/disable the equity scanner agent."""
    return await set_scanner_controls(cache, {"equity_scanner_enabled": enabled}, reason or f"equity_scanner_{'enabled' if enabled else 'disabled'}")


async def toggle_option_scanner(cache, enabled: bool, reason: str = "") -> Dict[str, Any]:
    """Enable/disable the option chain scanner agent."""
    return await set_scanner_controls(cache, {"option_scanner_enabled": enabled}, reason or f"option_scanner_{'enabled' if enabled else 'disabled'}")


async def toggle_legmonitor(cache, enabled: bool, reason: str = "") -> Dict[str, Any]:
    """Enable/disable the LegMonitor service."""
    return await set_scanner_controls(cache, {"legmonitor_enabled": enabled}, reason or f"legmonitor_{'enabled' if enabled else 'disabled'}")


# ═══════════════════════════════════════════════════════════════════════════════
# FIX-AUDIT-D20-PART2: PARAMETER OVERRIDE SYSTEM
# ═══════════════════════════════════════════════════════════════════════════════

# Parameter validation bounds — (min, max, step, default)
_PARAM_VALIDATION_RULES: Dict[str, tuple] = {
    # EMA / Moving Averages
    "ema_fast":           (3, 50, 1, 9),
    "ema_slow":           (10, 200, 1, 21),
    "ema_trend":          (20, 200, 1, 50),
    "ema_short":          (10, 50, 1, 20),
    "ema_medium":         (30, 100, 1, 50),
    "ema_long":           (100, 300, 1, 200),
    # RSI
    "rsi_period":         (5, 30, 1, 14),
    "rsi_overbought":     (55, 90, 1, 65),
    "rsi_oversold":       (10, 45, 1, 35),
    "rsi_min":            (30, 60, 1, 50),
    "rsi_max":            (55, 85, 1, 70),
    # ATR
    "atr_period":         (5, 30, 1, 14),
    "atr_multiplier":     (0.5, 5.0, 0.1, 2.0),
    "atr_stop_mult":      (1.0, 4.0, 0.1, 2.0),
    "atr_target_mult":    (1.5, 6.0, 0.1, 3.0),
    # ADX
    "adx_threshold":      (15, 40, 1, 25),
    # Volume
    "volume_multiplier":  (0.5, 5.0, 0.1, 2.0),
    # VIX
    "vix_min":            (8.0, 25.0, 0.5, 13.0),
    "vix_max":            (15.0, 45.0, 0.5, 22.0),
    "vix_entry":          (12.0, 30.0, 0.5, 20.0),
    "vix_peak":           (18.0, 40.0, 0.5, 25.0),
    "vix_exit":           (8.0, 20.0, 0.5, 15.0),
    "max_vix":            (15.0, 35.0, 0.5, 20.0),
    "max_vix_entry":      (15.0, 35.0, 0.5, 25.0),
    "vix_activate":       (12.0, 25.0, 0.5, 18.0),
    "vix_increase":       (18.0, 30.0, 0.5, 22.0),
    # SL / TP
    "stoploss_pct":       (0.1, 10.0, 0.1, 3.0),
    "target_pct":         (0.5, 15.0, 0.1, 8.0),
    "stop_loss_pct":      (0.1, 10.0, 0.1, 3.0),
    "profit_target_pct":  (0.1, 1.0, 0.05, 0.50),
    "sl_pct":             (0.1, 5.0, 0.1, 1.5),
    "tp_pct":             (0.1, 10.0, 0.1, 3.0),
    # Bollinger Bands
    "bb_window":          (10, 40, 1, 20),
    "bb_std":             (1.0, 3.5, 0.1, 2.0),
    # MACD
    "macd_fast":          (5, 20, 1, 12),
    "macd_slow":          (15, 50, 1, 26),
    "macd_signal":        (5, 15, 1, 9),
    # Donchian
    "donchian_period":    (10, 40, 1, 20),
    # ORB specific
    "min_range_points":   (20, 150, 5, 50),
    "max_range_points":   (100, 400, 10, 200),
    # VWAP
    "min_deviation_pct":  (0.3, 2.0, 0.1, 0.8),
    "max_deviation_pct":  (1.0, 5.0, 0.1, 3.0),
    "stop_loss_multiplier": (1.0, 4.0, 0.1, 2.0),
    # OFI
    "ofi_buy_threshold":  (0.10, 0.50, 0.05, 0.25),
    "ofi_sell_threshold": (-0.50, -0.10, 0.05, -0.25),
    # Structural Break / ML
    "z_threshold":        (1.5, 4.0, 0.1, 2.5),
    "lookback":           (30, 120, 5, 60),
    "volume_surge_mult":  (1.0, 3.0, 0.1, 1.5),
    # Spread / Options
    "spread_width":       (50, 300, 50, 100),
    "wing_width":         (50, 400, 50, 200),
    "protection_width":   (50, 200, 50, 100),
    "strangle_width":     (100, 400, 50, 200),
    "iv_threshold":       (15, 50, 1, 30),
    "iv_contango_threshold": (0.02, 0.20, 0.01, 0.10),
    "min_dte":            (2, 15, 1, 7),
    "max_dte":            (10, 45, 1, 21),
    # Swing
    "lookback_period":    (10, 80, 5, 20),
    "max_hold_days":      (3, 30, 1, 7),
    "pullback_threshold": (0.005, 0.03, 0.005, 0.01),
    "trail_trigger":      (0.02, 0.10, 0.01, 0.05),
    # Momentum Rotation
    "rs_threshold":       (50, 90, 5, 70),
    "rebalance_days":     (5, 40, 5, 20),
    # Event Driven
    "gap_threshold":      (0.005, 0.05, 0.005, 0.015),
    "holding_days":       (1, 15, 1, 7),
    "min_gap_pct":        (0.005, 0.03, 0.005, 0.01),
    "max_gap_pct":        (0.01, 0.05, 0.005, 0.02),
    # Scalper
    "sharp_move_pct":     (0.002, 0.015, 0.001, 0.005),
    "max_signals_per_day": (5, 50, 5, 30),
    "lookback_bars":      (10, 50, 5, 20),
    # Power First Hour
    "sl_pct_base":        (0.005, 0.03, 0.005, 0.015),
    "tp_pct_pfth":        (0.01, 0.06, 0.005, 0.03),
    "fh_volume_mult":     (1.0, 2.0, 0.05, 1.20),
    # RS Pair
    "rs_period":          (20, 120, 5, 63),
    "rs_long_threshold":  (60, 90, 5, 75),
    "rs_short_threshold": (10, 40, 5, 25),
    # Theta Capture
    "sl_multiplier":      (1.0, 4.0, 0.5, 2.0),
    "sd_multiplier":      (0.5, 2.0, 0.1, 1.0),
    # Portfolio Hedge
    "otm_distance_pct":   (2.0, 10.0, 0.5, 5.0),
    "hedge_ratio_normal": (0.05, 0.50, 0.05, 0.20),
    "hedge_ratio_high":   (0.10, 0.60, 0.05, 0.30),
    "max_hedge_cost_pct": (0.5, 5.0, 0.5, 2.0),
    # Pair Trading
    "correlation_threshold": (0.5, 0.95, 0.05, 0.70),
    "zscore_threshold":   (1.0, 3.5, 0.1, 2.0),
    # Stat Arb
    "z_entry":            (1.0, 3.5, 0.1, 2.0),
    "z_exit":             (-1.0, 1.0, 0.1, 0.0),
    # Vol Arb
    "iv_deviation":       (0.01, 0.05, 0.005, 0.02),
    # Breakout multiplier
    "breakout_multiplier": (1.0, 3.0, 0.1, 1.5),
    "stop_multiplier":    (1.0, 4.0, 0.1, 2.0),
    "target_multiplier":  (1.5, 6.0, 0.1, 3.0),
    # VP + OFI
    "ofi_reversal_threshold":  (0.10, 0.60, 0.05, 0.30),
    "ofi_breakout_threshold":  (0.05, 0.50, 0.05, 0.20),
    "ofi_poc_threshold":       (0.10, 0.50, 0.05, 0.25),
    "vp_lookback_bars":        (10, 50, 5, 20),
    # Collar
    "put_delta_target":        (0.10, 0.40, 0.05, 0.20),
    "call_delta_target":       (0.10, 0.40, 0.05, 0.25),
    # Ratio Call Write
    "ratio":                   (1, 4, 1, 2),
    "min_net_credit":          (0.0, 1.0, 0.1, 0.0),
    "min_vix":                 (10.0, 25.0, 0.5, 15.0),
    # Delta Hedging
    "target_delta":            (-0.5, 0.5, 0.05, 0.0),
    "rehedge_threshold":       (0.01, 0.10, 0.01, 0.03),
    # VIX Trading
    "vol_lookback":            (10, 50, 5, 20),
    "vol_threshold":           (1.5, 4.0, 0.1, 2.5),
    # Squeeze
    "squeeze_threshold":       (0.01, 0.10, 0.01, 0.04),
    "squeeze_percentile":      (5, 40, 5, 20),
    "breakout_threshold":      (0.002, 0.015, 0.001, 0.005),
}

# ── Per-strategy parameter map: strategy_id → list of param names ────────────
_STRATEGY_PARAMS: Dict[str, List[str]] = {
    # ── Momentum ──────────────────────────────────────────────
    "ALPHA_ORB_001": [
        "min_range_points", "max_range_points", "vix_min", "vix_max",
        "volume_multiplier",
    ],
    "ALPHA_VWAP_002": [
        "min_deviation_pct", "max_deviation_pct", "rsi_oversold", "rsi_overbought",
        "stop_loss_multiplier",
    ],
    "ALPHA_TREND_003": [
        "donchian_period", "atr_period", "atr_stop_mult", "atr_target_mult",
        "adx_threshold", "volume_multiplier",
    ],
    "ALPHA_OFI_004": [
        "ofi_buy_threshold", "ofi_sell_threshold", "atr_multiplier",
    ],
    "ALPHA_SENTIMENT_005": [
        # Price/sentiment thresholds (custom); no generic indicator params
    ],
    "ALPHA_ML_006": [
        "z_threshold", "lookback", "volume_surge_mult", "atr_period",
        "atr_stop_mult", "atr_target_mult",
    ],
    # ── Options Spreads ──────────────────────────────────────
    "ALPHA_BCS_007": [
        "spread_width", "max_vix", "profit_target_pct", "stop_loss_pct",
    ],
    "ALPHA_BEARPUT_008": [
        "spread_width", "stop_loss_pct", "profit_target_pct",
    ],
    "ALPHA_RATIO_009": [
        "spread_width",
    ],
    "ALPHA_CALENDAR_010": [
        "iv_contango_threshold",
    ],
    "ALPHA_IRON_011": [
        "wing_width", "protection_width", "vix_min", "vix_max",
        "profit_target_pct", "stop_loss_pct", "min_dte", "max_dte",
    ],
    "ALPHA_BUTTERFLY_012": [
        "spread_width", "stop_loss_pct", "profit_target_pct",
    ],
    "ALPHA_STRANGLE_013": [
        "strangle_width", "stop_loss_pct", "profit_target_pct",
    ],
    "ALPHA_STRADDLE_014": [
        "iv_threshold", "atr_multiplier", "stop_loss_pct", "profit_target_pct",
    ],
    "ALPHA_VIX_015": [
        "vol_lookback", "vol_threshold", "stoploss_pct", "target_pct",
    ],
    "ALPHA_DELTA_016": [
        "target_delta", "rehedge_threshold",
    ],
    "ALPHA_PORT_017": [
        "otm_distance_pct", "hedge_ratio_normal", "hedge_ratio_high",
        "vix_activate", "vix_increase", "max_hedge_cost_pct",
    ],
    "ALPHA_PAIR_018": [
        "correlation_threshold", "zscore_threshold", "rsi_oversold", "rsi_overbought",
    ],
    # ── Swing ─────────────────────────────────────────────────
    "ALPHA_BREAKOUT_101": [
        "lookback_period", "volume_multiplier", "rsi_min", "rsi_max",
        "adx_threshold", "stop_loss_pct", "target_pct", "max_hold_days",
    ],
    "ALPHA_PULLBACK_102": [
        "ema_short", "ema_medium", "ema_long", "pullback_threshold",
        "rsi_min", "rsi_max", "stop_loss_pct", "target_pct",
        "trail_trigger", "max_hold_days",
    ],
    "ALPHA_EMA_CROSS_104": [
        "ema_fast", "ema_slow", "ema_trend", "adx_threshold",
        "stop_loss_pct", "trail_trigger", "max_hold_days",
    ],
    # ── Wave 2: Rotation / MR / Event / Vol ───────────────────
    "ALPHA_MOMENTUM_201": [
        "lookback_period", "rs_threshold", "rebalance_days",
    ],
    "ALPHA_SECTOR_202": [
        "lookback_period", "atr_stop_mult", "atr_target_mult",
    ],
    "ALPHA_BB_203": [
        "bb_window", "bb_std", "squeeze_threshold", "squeeze_percentile",
        "breakout_threshold", "volume_multiplier", "atr_target_mult",
    ],
    "ALPHA_RSI_DIV_204": [
        "rsi_period", "volume_multiplier", "ema_trend",
        "atr_stop_mult", "atr_target_mult",
    ],
    "ALPHA_EARN_205": [
        "gap_threshold", "holding_days", "volume_multiplier",
        "stoploss_pct", "target_pct",
    ],
    "ALPHA_GAP_206": [
        "min_gap_pct", "max_gap_pct", "volume_multiplier", "stoploss_pct",
    ],
    "ALPHA_ATR_207": [
        "atr_period", "breakout_multiplier", "stop_multiplier",
        "target_multiplier", "volume_multiplier",
    ],
    "ALPHA_VOL_CRUSH_208": [
        "vix_entry", "vix_peak", "vix_exit", "stoploss_pct", "target_pct",
    ],
    # ── Quant / Statistical ───────────────────────────────────
    "ALPHA_STAT_ARB_301": [
        "z_entry", "z_exit", "correlation_threshold", "stoploss_pct", "target_pct",
    ],
    "ALPHA_VOL_ARB_401": [
        "iv_deviation", "stoploss_pct", "target_pct",
    ],
    "ALPHA_CROSS_MOM_402": [
        "lookback_period",
    ],
    # ── Options Premium (Theta) ───────────────────────────────
    "ALPHA_SHORT_STRADDLE_501": [
        "iv_threshold", "stop_loss_pct", "profit_target_pct",
    ],
    "ALPHA_SHORT_STRANGLE_502": [
        "strangle_width", "stop_loss_pct", "profit_target_pct",
    ],
    "ALPHA_IRON_BUTTERFLY_503": [
        "wing_width", "stop_loss_pct", "profit_target_pct",
    ],
    # ── Wave 3: Alpha Boost ───────────────────────────────────
    "ALPHA_ORB_VWAP_307": [
        "min_range_points", "max_range_points", "min_deviation_pct",
        "vix_min", "vix_max", "volume_multiplier",
    ],
    "ALPHA_MR_SCALP_302": [
        "sharp_move_pct", "sl_pct", "tp_pct", "max_signals_per_day",
        "volume_multiplier",
    ],
    "ALPHA_IDX_SCALP_303": [
        "lookback_bars", "sl_pct", "tp_pct", "max_signals_per_day",
        "volume_multiplier",
    ],
    "ALPHA_PFTH_304": [
        "sl_pct_base", "tp_pct_pfth", "fh_volume_mult",
    ],
    "ALPHA_RS_PAIR_305": [
        "rs_period", "rs_long_threshold", "rs_short_threshold",
        "sl_pct", "tp_pct",
    ],
    "ALPHA_THETA_306": [
        "profit_target_pct", "sl_multiplier", "sd_multiplier",
        "max_vix_entry", "min_dte",
    ],
    # ── Microstructure ────────────────────────────────────────
    "ALPHA_VP_OFI_403": [
        "ofi_reversal_threshold", "ofi_breakout_threshold",
        "ofi_poc_threshold", "vp_lookback_bars",
    ],
    "ALPHA_VP_MICRO_405": [
        "vp_lookback_bars",
    ],
    "ALPHA_VP_NANO_406": [
        "vp_lookback_bars",
    ],
    # ── Phase 3 Options ───────────────────────────────────────
    "ALPHA_DIAG_041": [
        "iv_contango_threshold", "spread_width", "min_dte", "max_dte",
    ],
    "ALPHA_RREV_042": [
        "spread_width", "stop_loss_pct",
    ],
    "ALPHA_CREDIT_043": [
        "spread_width", "stop_loss_pct", "profit_target_pct",
    ],
    "ALPHA_CCALL_044": [
        "put_delta_target", "call_delta_target", "min_dte", "max_dte",
    ],
    "ALPHA_CSP_045": [
        "put_delta_target", "min_dte", "max_dte", "stop_loss_pct",
    ],
    "ALPHA_COLLAR_046": [
        "put_delta_target", "call_delta_target", "min_dte", "max_dte",
    ],
    "ALPHA_RATIO_CW_047": [
        "ratio", "min_vix", "min_dte", "max_dte", "stop_loss_pct",
    ],
    # ── Universal / AI Builder ────────────────────────────────
    "AIBLD_001_EQUITY_MULTI": [
        "ema_fast", "ema_slow", "rsi_period", "rsi_overbought", "rsi_oversold",
        "atr_period", "atr_multiplier", "adx_threshold", "volume_multiplier",
        "bb_window", "bb_std", "macd_fast", "macd_slow", "macd_signal",
        "stoploss_pct", "target_pct",
    ],
    "AIBLD_003_EQUITY_BEAR_TA": [
        "stop_loss_pct", "target_pct",
    ],
    "AIBLD_004_EQUITY_BULL_REV": [
        "stop_loss_pct", "target_pct",
    ],
    "AIBLD_002_OPTIONS_IC": [
        "wing_width", "protection_width", "vix_min", "vix_max",
        "profit_target_pct", "stop_loss_pct", "min_dte", "max_dte",
    ],
}


def _validate_parameter(param_name: str, value: float) -> tuple:
    """Validate a parameter against known bounds. Returns (valid, error_msg)."""
    rule = _PARAM_VALIDATION_RULES.get(param_name)
    if not rule:
        return True, ""  # Unknown params pass through (strategy-specific)
    mn, mx, _step, _default = rule
    if value < mn or value > mx:
        return False, f"{param_name}: {value} outside bounds [{mn}, {mx}]"
    return True, ""


async def get_parameter_overrides(cache, strategy_id: str = None) -> Dict[str, Any]:
    """Get active parameter overrides, optionally filtered by strategy."""
    raw = await cache.get(_k("parameter_overrides"))
    if not raw:
        return {"overrides": [], "count": 0}
    all_overrides = json.loads(raw)
    # Prune expired
    now = datetime.now(timezone.utc).isoformat()
    active = [o for o in all_overrides if o.get("expires_at", "9999") > now]
    if strategy_id:
        active = [o for o in active if o.get("strategy_id") == strategy_id]
    return {"overrides": active, "count": len(active)}


async def set_parameter_override(
    cache, strategy_id: str, parameter_name: str, override_value: float,
    ttl_minutes: int = 60, reason: str = ""
) -> Dict[str, Any]:
    """Set a single parameter override with validation and audit."""
    valid, err = _validate_parameter(parameter_name, override_value)
    if not valid:
        return {"success": False, "error": err}

    raw = await cache.get(_k("parameter_overrides"))
    overrides = json.loads(raw) if raw else []

    # Remove existing override for same strategy+param
    overrides = [
        o for o in overrides
        if not (o.get("strategy_id") == strategy_id and o.get("parameter_name") == parameter_name)
    ]

    now = datetime.now(timezone.utc)
    entry = {
        "id": f"{strategy_id}_{parameter_name}_{int(now.timestamp())}",
        "strategy_id": strategy_id,
        "parameter_name": parameter_name,
        "override_value": override_value,
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=ttl_minutes)).isoformat() if ttl_minutes > 0 else "9999-12-31T23:59:59Z",
        "reason": reason,
    }
    overrides.append(entry)
    await cache.set(_k("parameter_overrides"), json.dumps(overrides), ttl=86400 * 30)
    await _audit(cache, "parameter_override_set", {
        "strategy_id": strategy_id, "parameter_name": parameter_name,
        "override_value": override_value, "reason": reason,
    })
    return {"success": True, "override": entry}


async def clear_parameter_override(cache, override_id: str) -> Dict[str, Any]:
    """Remove a specific parameter override by its ID."""
    raw = await cache.get(_k("parameter_overrides"))
    if not raw:
        return {"success": False, "error": "No overrides found"}
    overrides = json.loads(raw)
    before = len(overrides)
    overrides = [o for o in overrides if o.get("id") != override_id]
    if len(overrides) == before:
        return {"success": False, "error": f"Override {override_id} not found"}
    await cache.set(_k("parameter_overrides"), json.dumps(overrides), ttl=86400 * 30)
    await _audit(cache, "parameter_override_cleared", {"override_id": override_id})
    return {"success": True, "remaining": len(overrides)}


async def get_parameter_schema(cache, strategy_id: str) -> Dict[str, Any]:
    """Return parameter bounds/schema for a strategy (for frontend sliders)."""
    # Strategy-specific params if mapped, else empty
    param_names = _STRATEGY_PARAMS.get(strategy_id, [])
    schema = {}
    for name in param_names:
        rule = _PARAM_VALIDATION_RULES.get(name)
        if rule:
            mn, mx, step, default = rule
            schema[name] = {"min": mn, "max": mx, "step": step, "default": default}
    return {"strategy_id": strategy_id, "parameters": schema}


# ═══════════════════════════════════════════════════════════════════════════════
# FIX-AUDIT-D20-PART2: RISK PARAMETER OVERRIDE
# ═══════════════════════════════════════════════════════════════════════════════

RISK_OVERRIDE_DEFAULTS = {
    "kelly_fraction": 0.25,
    "max_position_pct": 5.0,
    "max_daily_loss_pct": 3.0,
    "max_sector_exposure_pct": 15.0,
    "max_open_positions": 10,
    "max_options_positions": 5,
}


async def get_risk_overrides(cache) -> Dict[str, Any]:
    """Get current risk parameter overrides."""
    raw = await cache.get(_k("risk_overrides"))
    if not raw:
        return {"is_overridden": False, **RISK_OVERRIDE_DEFAULTS}
    stored = json.loads(raw)
    merged = {**RISK_OVERRIDE_DEFAULTS, **stored}
    return {"is_overridden": True, **merged}


async def set_risk_override(
    cache, override_type: str, override_value: float,
    ttl_minutes: int = 0, reason: str = ""
) -> Dict[str, Any]:
    """Override a specific risk parameter."""
    if override_type not in RISK_OVERRIDE_DEFAULTS:
        return {"success": False, "error": f"Unknown risk parameter: {override_type}"}

    raw = await cache.get(_k("risk_overrides"))
    current = json.loads(raw) if raw else {}
    current[override_type] = override_value
    now = datetime.now(timezone.utc)
    current["updated_at"] = now.isoformat()
    current["reason"] = reason

    ttl = (ttl_minutes * 60) if ttl_minutes > 0 else 86400 * 30
    await cache.set(_k("risk_overrides"), json.dumps(current), ttl=ttl)
    await _audit(cache, "risk_override_set", {
        "override_type": override_type, "override_value": override_value,
        "ttl_minutes": ttl_minutes, "reason": reason,
    })
    return {"success": True, override_type: override_value}


async def clear_risk_overrides(cache) -> Dict[str, Any]:
    """Reset all risk overrides to defaults."""
    await cache.delete(_k("risk_overrides"))
    await _audit(cache, "risk_overrides_cleared", {})
    return {"success": True, "reset_to": RISK_OVERRIDE_DEFAULTS}
