import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from src.database.redis import cache
from src.middleware.auth import require_api_key
from src.services import manual_controls as mc


router = APIRouter(dependencies=[Depends(require_api_key)], tags=["admin-controls"])


class StrategyToggleRequest(BaseModel):
    enabled: bool
    reason: str = ""


class StrategyLimitRequest(BaseModel):
    max_loss: float = 0.0
    max_loss_pct: float = 0.0


class ActiveSetRequest(BaseModel):
    strategy_ids: List[str]
    reason: str = ""


class RegimeOverrideRequest(BaseModel):
    regime: str
    duration_minutes: int = 60
    reason: str = ""


class PositionSizingRequest(BaseModel):
    multiplier: float
    duration_hours: int = 4
    reason: str = ""


class RateLimitRequest(BaseModel):
    max_orders_per_cycle: int
    reason: str = ""


class BlacklistRequest(BaseModel):
    symbols: List[str]
    reason: str = ""


class AlertThresholdsRequest(BaseModel):
    min_signal_strength: Optional[float] = None
    min_strategy_score: Optional[float] = None
    vix_warning_level: Optional[float] = None
    daily_loss_warning: Optional[float] = None
    approval_sound: Optional[bool] = None


class ApprovalTimeoutRequest(BaseModel):
    timeout_seconds: int
    reason: str = ""


class TextCommandRequest(BaseModel):
    command: str
    dry_run: bool = True
    operator: str = "admin_text"
    reason: str = ""


class TextCommandApprovalDecisionRequest(BaseModel):
    operator: str = "admin_text"
    reason: str = ""


class BacktestConfigRequest(BaseModel):
    capital: Optional[float] = None
    slippage_bps: Optional[int] = None
    commission_per_order: Optional[float] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    strategy_ids: Optional[List[str]] = None
    universe: Optional[str] = None
    period: Optional[str] = None


class BulkToggleRequest(BaseModel):
    strategy_ids: List[str]
    enabled: bool
    reason: str = ""


class MaxDailyTradesRequest(BaseModel):
    max_daily_trades: int
    reason: str = ""


class OrdersPerSecondRequest(BaseModel):
    orders_per_second: int
    reason: str = ""


class ConfluenceMinRequest(BaseModel):
    min_confluence_score: int
    reason: str = ""


class QualityGradeRequest(BaseModel):
    min_quality_grade: str
    reason: str = ""


class IVRegimePrefRequest(BaseModel):
    tiers: Dict[str, bool]
    reason: str = ""


@router.get("/api/controls/snapshot")
async def get_controls_snapshot():
    return await mc.get_all_controls(cache)


@router.get("/api/controls/strategies")
async def list_strategies():
    return {"strategies": await mc.get_strategy_states(cache)}


@router.post("/api/controls/strategies/{strategy_id}/toggle")
async def toggle_strategy(strategy_id: str, body: StrategyToggleRequest):
    return await mc.toggle_strategy(cache, strategy_id, body.enabled, body.reason)


@router.post("/api/controls/strategies/{strategy_id}/limits")
async def set_strategy_limit(strategy_id: str, body: StrategyLimitRequest):
    return await mc.set_strategy_limit(cache, strategy_id, body.max_loss, body.max_loss_pct)


@router.post("/api/controls/strategies/{strategy_id}/reset-circuit-breaker")
async def reset_circuit_breaker(strategy_id: str):
    return await mc.reset_circuit_breaker(cache, strategy_id)


@router.post("/api/controls/strategies/bulk-toggle")
async def bulk_toggle_strategies(body: BulkToggleRequest):
    return await mc.bulk_toggle_strategies(cache, body.strategy_ids, body.enabled, body.reason)


@router.get("/api/controls/active-set")
async def get_active_set():
    return await mc.get_active_set(cache)


@router.post("/api/controls/active-set")
async def set_active_set(body: ActiveSetRequest):
    return await mc.set_active_set(cache, body.strategy_ids, body.reason)


@router.get("/api/controls/regime-override")
async def get_regime_override():
    return await mc.get_regime_override(cache)


@router.post("/api/controls/regime-override")
async def set_regime_override(body: RegimeOverrideRequest):
    return await mc.set_regime_override(cache, body.regime, body.duration_minutes, body.reason)


@router.delete("/api/controls/regime-override")
async def clear_regime_override():
    return await mc.clear_regime_override(cache)


@router.get("/api/controls/scanners")
async def get_scanner_controls():
    return await mc.get_scanner_controls(cache)


@router.post("/api/controls/scanners")
async def set_scanner_controls(body: Dict[str, Any]):
    reason = str(body.pop("reason", ""))
    return await mc.set_scanner_controls(cache, body, reason)


@router.post("/api/controls/scanners/equity/toggle")
async def toggle_equity_scanner(body: Dict[str, Any]):
    enabled = bool(body.get("enabled", True))
    reason = str(body.get("reason", ""))
    return await mc.toggle_equity_scanner(cache, enabled, reason)


@router.post("/api/controls/scanners/options/toggle")
async def toggle_option_scanner(body: Dict[str, Any]):
    enabled = bool(body.get("enabled", True))
    reason = str(body.get("reason", ""))
    return await mc.toggle_option_scanner(cache, enabled, reason)


@router.post("/api/controls/scanners/legmonitor/toggle")
async def toggle_legmonitor(body: Dict[str, Any]):
    enabled = bool(body.get("enabled", True))
    reason = str(body.get("reason", ""))
    return await mc.toggle_legmonitor(cache, enabled, reason)


@router.get("/api/manual-controls/parameter-overrides")
async def get_parameter_overrides(strategy_id: Optional[str] = None):
    return await mc.get_parameter_overrides(cache, strategy_id)


@router.get("/api/manual-controls/parameter-schema/{strategy_id}")
async def get_parameter_schema(strategy_id: str):
    return await mc.get_parameter_schema(cache, strategy_id)


@router.get("/api/manual-controls/dropdown-options")
async def get_dropdown_options():
    strategies = [
        {"id": s["id"], "name": s["name"], "category": s["category"], "module": s["module"]}
        for s in mc.STRATEGY_REGISTRY
    ]
    strategy_params = {}
    for strategy_id, param_names in mc._STRATEGY_PARAMS.items():
        if strategy_id not in mc.STRATEGY_IDS:
            continue
        params = {}
        for param_name in param_names:
            rule = mc._PARAM_VALIDATION_RULES.get(param_name)
            if not rule:
                continue
            min_value, max_value, step, default = rule
            params[param_name] = {
                "min": min_value,
                "max": max_value,
                "step": step,
                "default": default,
            }
        strategy_params[strategy_id] = params
    return {"strategies": strategies, "strategy_params": strategy_params}


@router.post("/api/manual-controls/parameter-override")
async def set_parameter_override(body: Dict[str, Any]):
    return await mc.set_parameter_override(
        cache,
        str(body.get("strategy_id", "")),
        str(body.get("parameter_name", "")),
        body.get("override_value", 0),
        int(body.get("ttl_minutes", 60)),
        str(body.get("reason", "")),
    )


@router.delete("/api/manual-controls/parameter-override/{override_id}")
async def clear_parameter_override(override_id: str):
    return await mc.clear_parameter_override(cache, override_id)


@router.get("/api/manual-controls/risk-state")
async def get_risk_overrides():
    return await mc.get_risk_overrides(cache)


@router.post("/api/manual-controls/risk-override")
async def set_risk_override(body: Dict[str, Any]):
    return await mc.set_risk_override(
        cache,
        str(body.get("override_type", "")),
        body.get("override_value", 0),
        int(body.get("ttl_minutes", 0)),
        str(body.get("reason", "")),
    )


@router.delete("/api/manual-controls/risk-override")
async def clear_risk_overrides():
    return await mc.clear_risk_overrides(cache)


@router.get("/api/controls/position-sizing")
async def get_position_sizing():
    return await mc.get_position_sizing(cache)


@router.post("/api/controls/position-sizing")
async def set_position_sizing(body: PositionSizingRequest):
    return await mc.set_position_sizing(cache, body.multiplier, body.duration_hours, body.reason)


@router.delete("/api/controls/position-sizing")
async def clear_position_sizing():
    return await mc.clear_position_sizing(cache)


@router.get("/api/controls/rate-limit")
async def get_rate_limit():
    return await mc.get_rate_limit(cache)


@router.post("/api/controls/rate-limit")
async def set_rate_limit(body: RateLimitRequest):
    return await mc.set_rate_limit(cache, body.max_orders_per_cycle, body.reason)


@router.get("/api/controls/instrument-filter")
async def get_instrument_filter():
    return await mc.get_instrument_filter(cache)


@router.post("/api/controls/instrument-filter/add")
async def add_to_blacklist(body: BlacklistRequest):
    return await mc.add_to_blacklist(cache, body.symbols, body.reason)


@router.post("/api/controls/instrument-filter/remove")
async def remove_from_blacklist(body: BlacklistRequest):
    return await mc.remove_from_blacklist(cache, body.symbols)


@router.get("/api/controls/alert-thresholds")
async def get_alert_thresholds():
    return await mc.get_alert_thresholds(cache)


@router.post("/api/controls/alert-thresholds")
async def set_alert_thresholds(body: AlertThresholdsRequest):
    payload = {key: value for key, value in body.model_dump().items() if value is not None}
    return await mc.set_alert_thresholds(cache, payload)


@router.get("/api/controls/approval-timeout")
async def get_approval_timeout():
    return await mc.get_approval_timeout(cache)


@router.post("/api/controls/approval-timeout")
async def set_approval_timeout(body: ApprovalTimeoutRequest):
    return await mc.set_approval_timeout(cache, body.timeout_seconds, body.reason)


@router.get("/api/controls/backtest-config")
async def get_backtest_config():
    return await mc.get_backtest_config(cache)


@router.post("/api/controls/backtest-config")
async def set_backtest_config(body: BacktestConfigRequest):
    payload = {key: value for key, value in body.model_dump().items() if value is not None}
    return await mc.set_backtest_config(cache, payload)


@router.get("/api/controls/audit-log")
async def get_audit_log(limit: int = Query(default=100, le=1000)):
    return await mc.get_audit_log(cache, limit=limit)


@router.get("/api/controls/command-journal")
async def get_command_journal(
    limit: int = Query(default=100, le=1000),
    action: Optional[str] = None,
    strategy_id: Optional[str] = None,
):
    return await mc.get_command_journal(
        cache,
        limit=limit,
        action=action,
        strategy_id=strategy_id,
    )


@router.post("/api/controls/text-command")
async def process_text_command(body: TextCommandRequest):
    return await mc.process_text_command(
        cache,
        body.command,
        dry_run=body.dry_run,
        operator=body.operator,
        reason=body.reason,
    )


@router.get("/api/controls/text-command/approvals")
async def get_text_command_approvals():
    return await mc.get_pending_text_command_approvals(cache)


@router.post("/api/controls/text-command/approvals/{request_id}/approve")
async def approve_text_command(request_id: str, body: TextCommandApprovalDecisionRequest):
    return await mc.approve_text_command(cache, request_id, operator=body.operator, reason=body.reason)


@router.post("/api/controls/text-command/approvals/{request_id}/reject")
async def reject_text_command(request_id: str, body: TextCommandApprovalDecisionRequest):
    return await mc.reject_text_command(cache, request_id, operator=body.operator, reason=body.reason)


@router.get("/api/controls/max-daily-trades")
async def get_max_daily_trades():
    return await mc.get_max_daily_trades(cache)


@router.post("/api/controls/max-daily-trades")
async def set_max_daily_trades(body: MaxDailyTradesRequest):
    return await mc.set_max_daily_trades(cache, body.max_daily_trades, body.reason)


@router.get("/api/controls/daily-trade-count")
async def get_daily_trade_count():
    count = await mc.get_daily_trade_count(cache)
    check = await mc.check_daily_trade_limit(cache)
    return {"count": count, **check}


@router.get("/api/controls/orders-per-second")
async def get_orders_per_second():
    return await mc.get_orders_per_second(cache)


@router.post("/api/controls/orders-per-second")
async def set_orders_per_second(body: OrdersPerSecondRequest):
    return await mc.set_orders_per_second(cache, body.orders_per_second, body.reason)


@router.get("/api/controls/min-confluence-score")
async def get_min_confluence_score():
    return await mc.get_min_confluence_score(cache)


@router.post("/api/controls/min-confluence-score")
async def set_min_confluence_score(body: ConfluenceMinRequest):
    return await mc.set_min_confluence_score(cache, body.min_confluence_score, body.reason)


@router.get("/api/controls/min-quality-grade")
async def get_min_quality_grade():
    return await mc.get_min_quality_grade(cache)


@router.post("/api/controls/min-quality-grade")
async def set_min_quality_grade(body: QualityGradeRequest):
    return await mc.set_min_quality_grade(cache, body.min_quality_grade, body.reason)


@router.get("/api/controls/iv-regime-preferences")
async def get_iv_regime_preferences():
    return await mc.get_iv_regime_preferences(cache)


@router.post("/api/controls/iv-regime-preferences")
async def set_iv_regime_preferences(body: IVRegimePrefRequest):
    return await mc.set_iv_regime_preferences(cache, body.tiers, body.reason)