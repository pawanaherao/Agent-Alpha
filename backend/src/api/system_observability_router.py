import asyncio
import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends

from src.core.config import settings
from src.core.runtime_context import get_runtime_context
from src.database.postgres import db
from src.database.redis import cache
from src.middleware.auth import require_api_key
from src.services.manual_controls import record_command
from src.strategies.v1_live_registry import V1_LIVE_STRATEGY_IDS, get_v1_live_strategy_total


logger = logging.getLogger(__name__)
router = APIRouter(tags=["system-observability"])

_TELEMETRY_STALE_AFTER_S = 600.0


def _parse_telemetry_timestamp(value):
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        raw = value.strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return None
    return None


def _get_telemetry_now(reference_ts=None):
    if reference_ts is not None and getattr(reference_ts, "tzinfo", None):
        return datetime.now(reference_ts.tzinfo)
    return datetime.now()


def _decode_cached_json(raw_value):
    if isinstance(raw_value, Exception) or raw_value is None:
        return {}
    try:
        return json.loads(raw_value)
    except Exception:
        return {}


def _build_telemetry_freshness(timestamp_value, stale_after_s=_TELEMETRY_STALE_AFTER_S):
    parsed = _parse_telemetry_timestamp(timestamp_value)
    if parsed is None:
        return {
            "age_s": None,
            "stale_after_s": float(stale_after_s),
            "is_stale": None,
        }

    now = _get_telemetry_now(parsed)
    age_s = round(max(0.0, (now - parsed).total_seconds()), 1)
    return {
        "age_s": age_s,
        "stale_after_s": float(stale_after_s),
        "is_stale": age_s > float(stale_after_s),
    }


def _resolve_cycle_timing_total_ms(cycle_timing):
    total_ms = float((cycle_timing or {}).get("total", 0) or 0)
    if (cycle_timing or {}).get("cycle_status") != "in_progress":
        return total_ms

    started_at = _parse_telemetry_timestamp((cycle_timing or {}).get("started_at"))
    if started_at is None:
        return total_ms

    now = _get_telemetry_now(started_at)
    elapsed_ms = max(0.0, (now - started_at).total_seconds() * 1000.0)
    return max(total_ms, elapsed_ms)


def _build_cycle_timing_health(cycle_timing):
    try:
        from src.intelligence.system_diagnostics import system_diagnostics

        warn_ms = float(system_diagnostics.thresholds.get("cycle_duration_warn_ms", 60_000) or 60_000)
        crit_ms = float(system_diagnostics.thresholds.get("cycle_duration_crit_ms", 180_000) or 180_000)
    except Exception:
        warn_ms = 60_000.0
        crit_ms = 180_000.0

    freshness = _build_telemetry_freshness((cycle_timing or {}).get("timestamp"))
    total_ms = _resolve_cycle_timing_total_ms(cycle_timing)
    cycle_status = (cycle_timing or {}).get("cycle_status")
    current_phase = (cycle_timing or {}).get("current_phase")
    if cycle_status == "in_progress":
        return {
            "status": "in_progress",
            "cycle_status": cycle_status,
            "current_phase": current_phase,
            "total_ms": round(total_ms, 2),
            "warn_threshold_ms": warn_ms,
            "crit_threshold_ms": crit_ms,
            "recommended_action": "Cycle timing is still in progress. Wait for completion for the final timing total.",
            "freshness_status": "fresh" if freshness["is_stale"] is False else "stale" if freshness["is_stale"] is True else "unknown",
            "freshness_recommended_action": None if freshness["is_stale"] is False else "Timing snapshot has not refreshed recently while the cycle is still running. Check for a stalled phase if this persists." if freshness["is_stale"] is True else "Inspect cycle timing timestamp generation before relying on freshness.",
            **freshness,
        }

    if total_ms <= 0:
        return {
            "status": "unavailable",
            "cycle_status": cycle_status,
            "current_phase": current_phase,
            "total_ms": 0.0,
            "warn_threshold_ms": warn_ms,
            "crit_threshold_ms": crit_ms,
            "recommended_action": "Wait for a completed cycle to populate timing telemetry.",
            "freshness_status": "unavailable",
            "freshness_recommended_action": "Wait for a completed cycle to populate timing telemetry.",
            **freshness,
        }

    if freshness["is_stale"] is True:
        freshness_status = "stale"
        freshness_recommended_action = "Latest cycle timing is stale. Wait for a new completed cycle before relying on current timing telemetry."
    elif freshness["is_stale"] is False:
        freshness_status = "fresh"
        freshness_recommended_action = None
    else:
        freshness_status = "unknown"
        freshness_recommended_action = "Inspect cycle timing timestamp generation before relying on freshness."

    if total_ms > crit_ms:
        return {
            "status": "critical",
            "cycle_status": cycle_status,
            "current_phase": current_phase,
            "total_ms": total_ms,
            "warn_threshold_ms": warn_ms,
            "crit_threshold_ms": crit_ms,
            "recommended_action": "Check broker API latency and database connection pool.",
            "freshness_status": freshness_status,
            "freshness_recommended_action": freshness_recommended_action,
            **freshness,
        }
    if total_ms > warn_ms:
        return {
            "status": "warning",
            "cycle_status": cycle_status,
            "current_phase": current_phase,
            "total_ms": total_ms,
            "warn_threshold_ms": warn_ms,
            "crit_threshold_ms": crit_ms,
            "recommended_action": "Monitor trend. May indicate degrading API performance.",
            "freshness_status": freshness_status,
            "freshness_recommended_action": freshness_recommended_action,
            **freshness,
        }
    return {
        "status": "healthy",
        "cycle_status": cycle_status,
        "current_phase": current_phase,
        "total_ms": total_ms,
        "warn_threshold_ms": warn_ms,
        "crit_threshold_ms": crit_ms,
        "recommended_action": None,
        "freshness_status": freshness_status,
        "freshness_recommended_action": freshness_recommended_action,
        **freshness,
    }


def _build_cycle_timing_bottleneck(cycle_timing):
    total_ms = _resolve_cycle_timing_total_ms(cycle_timing)
    if total_ms <= 0:
        return {}

    candidate_phases = {}
    for phase, value in (cycle_timing or {}).items():
        if phase in {"total", "cycle_id", "timestamp", "started_at", "current_phase", "cycle_status"}:
            continue
        try:
            numeric_value = float(value or 0)
        except (TypeError, ValueError):
            continue
        if numeric_value > 0:
            candidate_phases[phase] = numeric_value

    if not candidate_phases:
        return {}

    dominant_phase, dominant_phase_ms = sorted(
        candidate_phases.items(),
        key=lambda item: (-float(item[1]), str(item[0])),
    )[0]

    if dominant_phase == "sensing":
        recommended_action = "Scanner or market-data collection dominates cycle time. Review prefilter hit rate, universe size, and upstream data latency."
    elif dominant_phase == "decision":
        recommended_action = "Strategy decision time dominates. Review strategy selection, signal generation, and any AI fallback latency."
    elif dominant_phase == "monitoring":
        recommended_action = "Monitoring dominates cycle time. Review portfolio updates, diagnostics, and broker synchronization paths."
    else:
        recommended_action = "Review the detailed cycle timing breakdown to confirm which runtime phase is slowing the cycle."

    return {
        "phase": dominant_phase,
        "phase_ms": dominant_phase_ms,
        "share_pct": round((dominant_phase_ms / total_ms) * 100, 2),
        "recommended_action": recommended_action,
    }


def _build_scanner_telemetry_status(scanner_telemetry):
    if not scanner_telemetry:
        return {
            "status": "unavailable",
            "last_cycle_at": None,
            "recommended_action": "Wait for a completed scanner cycle to populate telemetry.",
            "age_s": None,
            "stale_after_s": _TELEMETRY_STALE_AFTER_S,
            "is_stale": None,
        }
    freshness = _build_telemetry_freshness(scanner_telemetry.get("last_cycle_at"))
    if freshness["is_stale"] is True:
        status = "stale"
        recommended_action = "Wait for a fresh scanner cycle before relying on current telemetry."
    elif freshness["is_stale"] is False:
        status = "available"
        recommended_action = None
    else:
        status = "timestamp_unknown"
        recommended_action = "Inspect scanner telemetry timestamp generation before relying on freshness."
    return {
        "status": status,
        "last_cycle_at": scanner_telemetry.get("last_cycle_at"),
        "recommended_action": recommended_action,
        **freshness,
    }


@router.post("/api/system/db-reconnect", dependencies=[Depends(require_api_key)])
async def db_reconnect():
    """Re-attempt PostgreSQL connection (use when DB was unavailable at startup)."""
    if db.pool is not None:
        return {"status": "already_connected"}
    try:
        await db.connect()
        from src.services.options_position_manager import options_position_manager as options_position_manager

        await options_position_manager.load_from_db()
        result = {"status": "connected", "message": "DB connected and options positions hydrated"}
        await record_command(cache, "system_db_reconnect", {
            "scope": "system_observability",
            "operator": "admin_api",
            "status": "applied",
            "connection_status": "connected",
        })
        return result
    except Exception as exc:
        return {"status": "failed", "error": str(exc)}


@router.get("/api/system/state")
async def get_system_state():
    """Aggregate live system state for the dashboard AI intelligence cards."""
    context = get_runtime_context()
    agent_manager = context["agent_manager"]

    try:
        strategy_total = get_v1_live_strategy_total(agent_manager.agents.get("strategy"))
    except Exception:
        strategy_total = len(V1_LIVE_STRATEGY_IDS)

    defaults = {
        "regime": "SIDEWAYS",
        "swing_regime": "SIDEWAYS",
        "vix": 21.0,
        "sentiment": 0.0,
        "iv_rank": 50,
        "active_agents": 0,
        "total_agents": len(agent_manager.agents) if agent_manager.agents else 8,
        "last_cycle_at": None,
        "backtest_pass": 0,
        "backtest_total": strategy_total,
        "execution_mode": "AUTO",
        "selected_strategies": [],
        "selected_strategies_regime": "",
        "selected_strategies_at": None,
    }

    try:
        raw_regime = await cache.get("current_regime")
        if raw_regime:
            if isinstance(raw_regime, (bytes, str)):
                try:
                    obj = json.loads(raw_regime)
                    defaults["regime"] = obj.get("regime", defaults["regime"])
                    defaults["swing_regime"] = obj.get("swing_regime", defaults["swing_regime"])
                    defaults["vix"] = float(obj.get("vix", defaults["vix"]))
                except Exception:
                    defaults["regime"] = str(raw_regime)
        if defaults["swing_regime"] == "SIDEWAYS":
            try:
                regime_agent = agent_manager.agents.get("regime") if agent_manager else None
                if regime_agent:
                    defaults["swing_regime"] = getattr(regime_agent, "swing_regime", "SIDEWAYS")
            except Exception:
                pass

        raw_sent = await cache.get("current_sentiment")
        if raw_sent:
            try:
                obj = json.loads(raw_sent) if isinstance(raw_sent, str) else raw_sent
                if isinstance(obj, dict):
                    defaults["sentiment"] = float(obj.get("score", obj.get("sentiment", 0)))
                else:
                    defaults["sentiment"] = float(obj)
            except Exception:
                pass

        raw_vix = await cache.get("current_vix")
        if raw_vix:
            try:
                defaults["vix"] = float(raw_vix)
            except Exception:
                pass

        vix_value = defaults["vix"]
        defaults["iv_rank"] = max(0, min(100, int(round((vix_value - 10) / (35 - 10) * 100))))

        raw_last_cycle = await cache.get("last_cycle_at")
        if raw_last_cycle:
            defaults["last_cycle_at"] = str(raw_last_cycle)

        active = 0
        for agent in (agent_manager.agents or {}).values():
            if hasattr(agent, "last_run") and agent.last_run:
                from datetime import datetime as dt

                delta = (dt.now() - agent.last_run).total_seconds()
                if delta < 300:
                    active += 1
            elif hasattr(agent, "is_enabled") and agent.is_enabled:
                active += 1
        if active == 0 and agent_manager.is_running:
            active = defaults["total_agents"]
        defaults["active_agents"] = active

        raw_backtest = await cache.get("backtest_summary")
        if raw_backtest:
            try:
                backtest = json.loads(raw_backtest) if isinstance(raw_backtest, str) else raw_backtest
                defaults["backtest_pass"] = int(backtest.get("pass", defaults["backtest_pass"]))
                defaults["backtest_total"] = int(backtest.get("total", defaults["backtest_total"]))
            except Exception:
                pass

        raw_execution_mode = await cache.get("execution_mode")
        if raw_execution_mode:
            execution_mode = raw_execution_mode.decode() if isinstance(raw_execution_mode, bytes) else str(raw_execution_mode)
            if execution_mode in ("MANUAL", "HYBRID", "AUTO"):
                defaults["execution_mode"] = execution_mode
        else:
            exec_agent = agent_manager.agents.get("execution")
            if exec_agent and hasattr(exec_agent, "mode"):
                defaults["execution_mode"] = exec_agent.mode

        raw_selected = await cache.get("selected_strategies_this_cycle")
        if raw_selected:
            try:
                selected = json.loads(raw_selected) if isinstance(raw_selected, str) else raw_selected
                defaults["selected_strategies"] = selected.get("strategies", [])
                defaults["selected_strategies_regime"] = selected.get("regime", "")
                defaults["selected_strategies_at"] = selected.get("updated_at")
            except Exception:
                pass

        raw_probabilities = await cache.get("current_regime")
        if raw_probabilities:
            try:
                regime_obj = json.loads(raw_probabilities) if isinstance(raw_probabilities, (str, bytes)) else raw_probabilities
                defaults["regime_probabilities"] = regime_obj.get("regime_probabilities", None)
                defaults["vix_spike_signal"] = regime_obj.get("vix_spike_signal", None)
            except Exception:
                pass
        if "regime_probabilities" not in defaults:
            defaults["regime_probabilities"] = None
            defaults["vix_spike_signal"] = None

        raw_kelly = await cache.get("kelly_feedback:PORTFOLIO:ALL")
        if raw_kelly:
            try:
                kelly_obj = json.loads(raw_kelly) if isinstance(raw_kelly, (str, bytes)) else raw_kelly
                defaults["kelly_win_rate"] = float(kelly_obj.get("win_rate", 0))
                defaults["kelly_trades"] = int(kelly_obj.get("trade_count", kelly_obj.get("total_trades", 0)))
                defaults["kelly_avg_win"] = float(kelly_obj.get("avg_win", 0))
                defaults["kelly_avg_loss"] = float(kelly_obj.get("avg_loss", 0))
            except Exception:
                pass
        if "kelly_win_rate" not in defaults:
            defaults["kelly_win_rate"] = None
            defaults["kelly_trades"] = 0
            defaults["kelly_avg_win"] = 0
            defaults["kelly_avg_loss"] = 0

        kelly_win_rate = defaults.get("kelly_win_rate")
        kelly_avg_win = defaults.get("kelly_avg_win", 0)
        kelly_avg_loss = defaults.get("kelly_avg_loss", 0)
        if kelly_win_rate and kelly_win_rate > 0 and (kelly_avg_win + kelly_avg_loss) > 0:
            expected_return = kelly_win_rate * kelly_avg_win - (1 - kelly_win_rate) * abs(kelly_avg_loss)
            defaults["expected_return_per_trade"] = round(expected_return, 2)
            defaults["edge_bps"] = round(expected_return / max(kelly_avg_win, 1) * 10000, 1)
        else:
            defaults["expected_return_per_trade"] = None
            defaults["edge_bps"] = None

        try:
            strategy_agent = agent_manager.agents.get("strategy")
            if strategy_agent and hasattr(strategy_agent, "strategies"):
                defaults["total_strategies_registered"] = len(strategy_agent.strategies)
        except Exception:
            pass
    except Exception as exc:
        logger.debug("system state partial error: %s", exc)

    return defaults


@router.get("/api/intelligence/summary")
async def intelligence_summary():
    context = get_runtime_context()
    agent_manager = context["agent_manager"]

    result = {
        "regime_probabilities": None,
        "vix_spike_signal": None,
        "kelly": {"win_rate": None, "trades": 0, "avg_win": 0, "avg_loss": 0},
        "expected_return": None,
        "edge_bps": None,
        "position_aging": [],
        "strategy_edge": [],
        "delta_hedge_status": None,
    }
    try:
        raw_regime = await cache.get("current_regime")
        if raw_regime:
            regime_obj = json.loads(raw_regime) if isinstance(raw_regime, (str, bytes)) else raw_regime
            result["regime_probabilities"] = regime_obj.get("regime_probabilities")
            result["vix_spike_signal"] = regime_obj.get("vix_spike_signal")

        per_strategy = []
        strategy_agent = agent_manager.agents.get("strategy")
        if strategy_agent and hasattr(strategy_agent, "strategies"):
            for strategy_id in strategy_agent.strategies:
                raw_kelly = await cache.get(f"kelly_feedback:{strategy_id}:__all__")
                if raw_kelly:
                    kelly_obj = json.loads(raw_kelly) if isinstance(raw_kelly, (str, bytes)) else raw_kelly
                    win_rate = float(kelly_obj.get("win_rate", 0))
                    avg_win = float(kelly_obj.get("avg_win", 0))
                    avg_loss = float(kelly_obj.get("avg_loss", 0))
                    total_trades = int(kelly_obj.get("total_trades", 0))
                    expected_return = win_rate * avg_win - (1 - win_rate) * abs(avg_loss) if total_trades > 0 else 0
                    per_strategy.append({
                        "strategy_id": strategy_id,
                        "win_rate": round(win_rate, 4),
                        "trades": total_trades,
                        "avg_win": round(avg_win, 2),
                        "avg_loss": round(avg_loss, 2),
                        "expected_return": round(expected_return, 2),
                        "should_trade": expected_return > 0 and total_trades >= 3,
                    })
        result["strategy_edge"] = per_strategy

        raw_global_kelly = await cache.get("kelly_feedback:PORTFOLIO:ALL")
        if raw_global_kelly:
            global_kelly = json.loads(raw_global_kelly) if isinstance(raw_global_kelly, (str, bytes)) else raw_global_kelly
            win_rate = float(global_kelly.get("win_rate", 0))
            avg_win = float(global_kelly.get("avg_win", 0))
            avg_loss = float(global_kelly.get("avg_loss", 0))
            total_trades = int(global_kelly.get("trade_count", global_kelly.get("total_trades", 0)))
            result["kelly"] = {"win_rate": round(win_rate, 4), "trades": total_trades, "avg_win": round(avg_win, 2), "avg_loss": round(avg_loss, 2)}
            if total_trades > 0:
                expected_return = win_rate * avg_win - (1 - win_rate) * abs(avg_loss)
                result["expected_return"] = round(expected_return, 2)
                result["edge_bps"] = round(expected_return / max(avg_win, 1) * 10000, 1) if avg_win > 0 else 0

        portfolio_agent = agent_manager.agents.get("portfolio")
        if portfolio_agent and hasattr(portfolio_agent, "simulated_positions"):
            from datetime import datetime as dt

            aging = []
            for _, position in portfolio_agent.simulated_positions.items():
                if position.get("status") != "OPEN":
                    continue
                entry_time = position.get("entry_time")
                if not entry_time:
                    continue
                try:
                    entry_dt = dt.fromisoformat(str(entry_time)) if isinstance(entry_time, str) else entry_time
                    age_days = (dt.now() - entry_dt).days
                    aging.append({
                        "symbol": position.get("symbol", "?"),
                        "strategy": position.get("strategy_id", ""),
                        "age_days": age_days,
                        "action": "FORCE_CLOSE" if age_days > 7 else "TIGHTEN_SL" if age_days > 3 else "HOLD",
                    })
                except Exception:
                    pass
            result["position_aging"] = aging

        raw_delta_hedge = await cache.get("delta_hedge_status")
        if raw_delta_hedge:
            result["delta_hedge_status"] = json.loads(raw_delta_hedge) if isinstance(raw_delta_hedge, (str, bytes)) else raw_delta_hedge
    except Exception as exc:
        logger.debug("intelligence summary error: %s", exc)

    return result


@router.get("/api/system/signal-flow-log")
async def get_signal_flow_log(limit: int = 100):
    try:
        if cache.client:
            raw_list = await cache.client.lrange("signal_flow_log", 0, min(limit, 200) - 1)
            entries = []
            for raw in reversed(raw_list):
                try:
                    entries.append(json.loads(raw))
                except Exception:
                    pass
            return {"entries": entries, "count": len(entries)}
    except Exception as exc:
        logger.debug("signal_flow_log read error: %s", exc)
    return {"entries": [], "count": 0}


@router.get("/api/strategies/performance-dashboard")
async def strategy_performance_dashboard():
    try:
        if not db.pool:
            return {"strategies": [], "error": "Database not connected"}

        async with db.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT strategy_name,
                       COUNT(*) as trading_days,
                       SUM(day_pnl) as total_pnl,
                       SUM(trades_today) as total_trades,
                       SUM(winning_trades) as total_wins,
                       MAX(drawdown_pct) as max_drawdown,
                       AVG(day_pnl) as avg_daily_pnl,
                       MAX(day_pnl) as best_day,
                       MIN(day_pnl) as worst_day
                FROM   strategy_daily_performance
                WHERE  strategy_name IS NOT NULL AND strategy_name != ''
                GROUP BY strategy_name
                ORDER BY total_pnl DESC
                """
            )

        strategies = []
        dragging = []
        for row in rows:
            name = row["strategy_name"]
            total_trades = int(row["total_trades"] or 0)
            total_wins = int(row["total_wins"] or 0)
            total_pnl = float(row["total_pnl"] or 0)
            win_rate = round(total_wins / total_trades * 100, 1) if total_trades > 0 else 0
            avg_daily = float(row["avg_daily_pnl"] or 0)
            entry = {
                "strategy_name": name,
                "trading_days": int(row["trading_days"]),
                "total_trades": total_trades,
                "total_wins": total_wins,
                "win_rate": win_rate,
                "total_pnl": round(total_pnl, 2),
                "avg_daily_pnl": round(avg_daily, 2),
                "best_day": round(float(row["best_day"] or 0), 2),
                "worst_day": round(float(row["worst_day"] or 0), 2),
                "max_drawdown": round(float(row["max_drawdown"] or 0), 2),
                "is_dragging": win_rate < 35 or total_pnl < -500,
            }
            strategies.append(entry)
            if entry["is_dragging"] and total_trades >= 3:
                dragging.append(name)

        return {
            "strategies": strategies,
            "total_strategies": len(strategies),
            "dragging_strategies": dragging,
            "dragging_count": len(dragging),
        }
    except Exception as exc:
        logger.error("Strategy performance dashboard error: %s", exc)
        return {"strategies": [], "error": str(exc)}


@router.get("/api/system/telemetry")
async def get_system_telemetry():
    context = get_runtime_context()
    agent_manager = context["agent_manager"]

    raw_session = raw_scanner = raw_cycle_timing = raw_funnel = raw_risk = raw_execution = None
    try:
        (
            raw_session,
            raw_scanner,
            raw_cycle_timing,
            raw_funnel,
            raw_risk,
            raw_execution,
        ) = await asyncio.gather(
            cache.get("session_telemetry"),
            cache.get("scanner_telemetry"),
            cache.get("cycle_timing_latest"),
            cache.get("strategy_funnel_telemetry"),
            cache.get("risk_telemetry"),
            cache.get("execution_telemetry"),
            return_exceptions=True,
        )
    except Exception:
        pass

    session = _decode_cached_json(raw_session)
    if session:
        session.pop("last_updated", None)
    if not session:
        session = dict(getattr(agent_manager, "_session_stats", {})) if agent_manager else {}
    cycle_intelligence_telemetry = (
        agent_manager.get_cycle_intelligence_telemetry()
        if agent_manager and hasattr(agent_manager, "get_cycle_intelligence_telemetry")
        else {}
    )
    scanner_telemetry = _decode_cached_json(raw_scanner)
    cycle_timing_telemetry = _decode_cached_json(raw_cycle_timing)
    cycle_timing_health = {}
    cycle_timing_bottleneck = {}
    scanner_telemetry_status = {}
    funnel_telemetry = _decode_cached_json(raw_funnel)
    risk_telemetry = _decode_cached_json(raw_risk)
    execution_telemetry = _decode_cached_json(raw_execution)

    scanner_telemetry_status = _build_scanner_telemetry_status(scanner_telemetry)
    cycle_timing_health = _build_cycle_timing_health(cycle_timing_telemetry)
    cycle_timing_bottleneck = _build_cycle_timing_bottleneck(cycle_timing_telemetry)

    execution_agent = (agent_manager.agents or {}).get("execution")
    risk_agent = (agent_manager.agents or {}).get("risk")
    portfolio_agent = (agent_manager.agents or {}).get("portfolio")

    execution_trades = getattr(execution_agent, "total_orders_sent", 0) if execution_agent else 0
    risk_approved = getattr(risk_agent, "total_signals_approved", 0) if risk_agent else 0
    open_positions = len(getattr(portfolio_agent, "simulated_positions", {})) if portfolio_agent else 0

    if risk_approved == 0:
        risk_approved = risk_telemetry.get("total_signals_approved", 0)
    if execution_trades == 0:
        execution_trades = execution_telemetry.get("total_orders_sent", 0)

    if execution_trades == 0 and settings.PAPER_TRADING and portfolio_agent:
        simulated_positions = getattr(portfolio_agent, "simulated_positions", {})
        if simulated_positions:
            execution_trades = len([position for position in simulated_positions.values() if position.get("status") != "PURGED"])

    return {
        "session": session,
        "cycle_intelligence": cycle_intelligence_telemetry,
        "scanner": scanner_telemetry,
        "scanner_status": scanner_telemetry_status,
        "cycle_timing": cycle_timing_telemetry,
        "cycle_timing_health": cycle_timing_health,
        "cycle_timing_bottleneck": cycle_timing_bottleneck,
        "strategy_funnel": funnel_telemetry,
        "live_counters": {
            "risk_signals_approved": risk_approved,
            "execution_orders_sent": execution_trades,
            "open_positions_now": open_positions,
        },
        "agents_registered": list((agent_manager.agents or {}).keys()),
        "agent_manager_running": agent_manager.is_running if agent_manager else False,
    }


@router.get("/api/system/diagnostics")
async def get_diagnostics_latest():
    try:
        raw = await cache.get("diagnostics_latest")
        if raw:
            return json.loads(raw)
        return {"findings": [], "message": "No diagnostics run yet. Will run after next cycle."}
    except Exception as exc:
        return {"findings": [], "error": str(exc)}


@router.get("/api/system/diagnostics/history")
async def get_diagnostics_history():
    try:
        raw = await cache.get("diagnostics_history")
        if raw:
            findings = json.loads(raw)
            return {"findings": findings, "total": len(findings)}
        return {"findings": [], "total": 0}
    except Exception as exc:
        return {"findings": [], "error": str(exc)}


@router.get("/api/system/diagnostics/autofixes")
async def get_diagnostics_autofixes():
    try:
        raw = await cache.get("diagnostics_autofix_log")
        if raw:
            fixes = json.loads(raw)
            return {"fixes": fixes, "total": len(fixes)}
        return {"fixes": [], "total": 0}
    except Exception as exc:
        return {"fixes": [], "error": str(exc)}


@router.get("/api/system/diagnostics/status")
async def get_diagnostics_status():
    from src.intelligence.system_diagnostics import system_diagnostics

    return system_diagnostics.get_status()


@router.post("/api/system/diagnostics/suppress", dependencies=[Depends(require_api_key)])
async def suppress_diagnostic_finding(finding_id: str):
    from src.intelligence.system_diagnostics import system_diagnostics

    system_diagnostics.suppress_finding(finding_id)
    await system_diagnostics.save_suppressed()
    result = {"suppressed": finding_id, "total_suppressed": len(system_diagnostics._suppressed_ids)}
    await record_command(cache, "diagnostics_suppress", {
        "scope": "system_observability",
        "operator": "admin_api",
        "status": "applied",
        "finding_id": finding_id,
        "total_suppressed": len(system_diagnostics._suppressed_ids),
    })
    return result


@router.post("/api/system/diagnostics/unsuppress", dependencies=[Depends(require_api_key)])
async def unsuppress_diagnostic_finding(finding_id: str):
    from src.intelligence.system_diagnostics import system_diagnostics

    system_diagnostics.unsuppress_finding(finding_id)
    await system_diagnostics.save_suppressed()
    result = {"unsuppressed": finding_id}
    await record_command(cache, "diagnostics_unsuppress", {
        "scope": "system_observability",
        "operator": "admin_api",
        "status": "applied",
        "finding_id": finding_id,
    })
    return result


@router.post("/api/system/diagnostics/threshold", dependencies=[Depends(require_api_key)])
async def update_diagnostic_threshold(key: str, value: float):
    from src.intelligence.system_diagnostics import system_diagnostics

    ok = system_diagnostics.update_threshold(key, value)
    if not ok:
        return {"error": f"Unknown threshold key: {key}", "available": list(system_diagnostics.thresholds.keys())}
    await system_diagnostics.save_thresholds()
    result = {"updated": key, "value": value}
    await record_command(cache, "diagnostics_threshold_update", {
        "scope": "system_observability",
        "operator": "admin_api",
        "status": "applied",
        "key": key,
        "value": value,
    })
    return result


@router.post("/api/system/diagnostics/run", dependencies=[Depends(require_api_key)])
async def run_diagnostics_now():
    from dataclasses import asdict
    from src.intelligence.system_diagnostics import system_diagnostics

    context = get_runtime_context()
    agent_manager = context["agent_manager"]

    if not agent_manager:
        return {"error": "Agent manager not initialized"}
    report = await system_diagnostics.run_diagnostics(agent_manager)
    result = {
        "cycle_id": report.cycle_id,
        "timestamp": report.timestamp,
        "findings": [asdict(finding) for finding in report.findings],
        "auto_fixes_applied": report.auto_fixes_applied,
        "critical_count": report.critical_count,
        "warning_count": report.warning_count,
        "info_count": report.info_count,
        "run_duration_ms": round(report.run_duration_ms, 1),
    }
    await record_command(cache, "diagnostics_run", {
        "scope": "system_observability",
        "operator": "admin_api",
        "status": "applied",
        "cycle_id": report.cycle_id,
        "critical_count": report.critical_count,
        "warning_count": report.warning_count,
        "info_count": report.info_count,
        "auto_fixes_applied": report.auto_fixes_applied,
    })
    return result