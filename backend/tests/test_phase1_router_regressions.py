import asyncio
from dataclasses import dataclass
from datetime import datetime, time as dt_time
import json
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import src.api.account_router as account_router
import src.api.admin_controls_router as admin_controls_router
import src.agents.base as base_agent_module
import src.agents.option_chain_scanner as option_chain_scanner_module
import src.api.ai_public_router as ai_public_router
import src.api.backtest_config_router as backtest_config_router
import src.api.backtest_interpret_router as backtest_interpret_router
import src.api.backtest_results_router as backtest_results_router
import src.api.backtest_runtime_router as backtest_runtime_router
import src.api.broker_management_router as broker_management_router
import src.api.chart_ohlcv_router as chart_ohlcv_router
import src.api.chart_support_router as chart_support_router
import src.api.config_filters_router as config_filters_router
import src.api.execution_broker_router as execution_broker_router
import src.api.market_data_router as market_data_router
import src.api.options_data_router as options_data_router
import src.api.operator_runtime_router as operator_runtime_router
import src.api.options_public_router as options_public_router
import src.api.portfolio_router as portfolio_router
import src.api.project_ops_router as project_ops_router
import src.api.public_status_router as public_status_router
import src.api.strategy_builder_router as strategy_builder_router
import src.api.strategy_grades_router as strategy_grades_router
import src.api.strategy_filter_router as strategy_filter_router
import src.api.trading_approvals_router as trading_approvals_router
import src.api.trading_mode_router as trading_mode_router
import src.api.tradingview_webhook_router as tradingview_webhook_router
import src.api.universe_router as universe_router
import src.api.system_observability_router as system_observability_router
import src.core.event_bus_redis as event_bus_redis_module
import src.core.event_bus as event_bus_module
from src.core.agent_manager import AgentManager
import src.intelligence.system_diagnostics as system_diagnostics_module
import src.services.manual_controls as manual_controls
import src.services.position_monitor as position_monitor_module
from src.database.postgres import db as postgres_db
from src.strategies.v1_live_registry import V1_LIVE_STRATEGY_IDS


pytestmark = [pytest.mark.integration]


class FakeCache:
    def __init__(self):
        self.store = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ttl=None):
        self.store[key] = value
        return True

    async def delete(self, key):
        self.store.pop(key, None)
        return True


class FakePortfolioAgent:
    def __init__(self):
        self.simulated_positions = {
            "pos-1": {"status": "OPEN", "symbol": "NIFTY", "quantity": 50},
            "pos-2": {"status": "CLOSED", "symbol": "BANKNIFTY", "quantity": 25},
        }
        self.total_realized_pnl = 1200.0
        self.total_unrealized_pnl = -150.0
        self.positions = {"legacy": {"status": "OPEN"}}
        self.balance = 500000
        self.persist_calls = 0

    async def _persist_paper_trades(self):
        self.persist_calls += 1


class FakeBrokerClient:
    def __init__(self, positions):
        self._positions = positions

    async def get_positions(self):
        return self._positions

    def broker_name(self):
        return "FAKE_BROKER"


def _build_router_app(router_module):
    app = FastAPI()
    app.include_router(router_module.router)
    require_api_key = getattr(router_module, "require_api_key", None)
    if require_api_key is not None:
        app.dependency_overrides[require_api_key] = lambda: {"authorized": True}
    return app


def test_record_command_appends_and_filters_command_journal(monkeypatch):
    fake_cache = FakeCache()
    monkeypatch.setattr(postgres_db, "pool", None)

    async def _exercise():
        await manual_controls.record_command(
            fake_cache,
            "portfolio_reset",
            {
                "scope": "portfolio_admin",
                "operator": "admin_api",
                "status": "applied",
                "strategy_id": "ALPHA_SCALP_001",
                "reason": "operator reset",
            },
        )

        return await manual_controls.get_command_journal(
            fake_cache,
            action="portfolio_reset",
            strategy_id="ALPHA_SCALP_001",
        )

    journal = asyncio.run(_exercise())

    assert journal["source"] == "command_journal"
    assert journal["total"] == 1
    entry = journal["entries"][0]
    assert entry["action"] == "portfolio_reset"
    assert entry["scope"] == "portfolio_admin"
    assert entry["operator"] == "admin_api"
    assert entry["strategy_id"] == "ALPHA_SCALP_001"
    assert entry["status"] == "applied"
    assert entry["command_id"].startswith("mc_")


def test_submit_morning_brief_truncates_and_calls_record_command(monkeypatch):
    fake_cache = FakeCache()
    record_command = AsyncMock()
    monkeypatch.setattr(project_ops_router, "cache", fake_cache)
    monkeypatch.setattr(project_ops_router, "record_command", record_command)

    client = TestClient(_build_router_app(project_ops_router))
    note = "hawkish-open " * 30

    response = client.post("/api/project-lead/morning-brief", json={"operator_note": note})

    assert response.status_code == 200
    body = response.json()
    stored_note = body["stored"]["operator_note"]
    assert len(stored_note) == 200
    assert json.loads(fake_cache.store["pre_market_context"])["operator_note"] == stored_note

    record_command.assert_awaited_once()
    assert record_command.await_args.args[1] == "project_lead_morning_brief"
    assert record_command.await_args.args[2]["scope"] == "project_ops"
    assert record_command.await_args.args[2]["note"] == stored_note


def test_get_morning_brief_returns_cached_context(monkeypatch):
    fake_cache = FakeCache()
    fake_cache.store["pre_market_context"] = json.dumps({
        "date": "2026-04-23",
        "operator_note": "Wait for breadth confirmation.",
        "gift_nifty": 24500,
    })
    monkeypatch.setattr(project_ops_router, "cache", fake_cache)

    client = TestClient(_build_router_app(project_ops_router))
    response = client.get("/api/project-lead/morning-brief")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "found"
    assert body["context"]["operator_note"] == "Wait for breadth confirmation."
    assert body["context"]["gift_nifty"] == 24500


def test_force_pre_market_fetch_uses_runtime_callback_and_calls_record_command(monkeypatch):
    fake_cache = FakeCache()
    record_command = AsyncMock()

    async def fake_pre_market_fetch():
        await fake_cache.set(
            "pre_market_context",
            json.dumps({"date": "2026-04-23", "gift_nifty": 24500, "asia": "mixed"}),
            ttl=86400,
        )

    monkeypatch.setattr(project_ops_router, "cache", fake_cache)
    monkeypatch.setattr(project_ops_router, "record_command", record_command)
    monkeypatch.setattr(project_ops_router, "get_runtime_context", lambda: {"pre_market_fetch": fake_pre_market_fetch})

    client = TestClient(_build_router_app(project_ops_router))
    response = client.post("/api/system/force-pre-market-fetch")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["context"]["gift_nifty"] == 24500

    record_command.assert_awaited_once()
    assert record_command.await_args.args[1] == "system_force_pre_market_fetch"
    assert record_command.await_args.args[2]["fetched_date"] == "2026-04-23"
    assert record_command.await_args.args[2]["context_keys"] == ["asia", "date", "gift_nifty"]


def test_alpha_decay_refresh_invalidates_cache_and_calls_record_command(monkeypatch):
    fake_cache = FakeCache()
    record_command = AsyncMock()

    class FakeMonitor:
        def __init__(self):
            self.invalidated = False

        async def invalidate_cache(self):
            self.invalidated = True

    fake_monitor = FakeMonitor()

    monkeypatch.setattr(project_ops_router, "cache", fake_cache)
    monkeypatch.setattr(project_ops_router, "record_command", record_command)
    monkeypatch.setattr("src.services.alpha_decay_monitor.get_alpha_decay_monitor", lambda: fake_monitor)

    client = TestClient(_build_router_app(project_ops_router))
    response = client.post("/api/alpha-decay/refresh")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "cache_invalidated"
    assert fake_monitor.invalidated is True

    record_command.assert_awaited_once()
    assert record_command.await_args.args[1] == "alpha_decay_refresh"
    assert record_command.await_args.args[2]["scope"] == "project_ops"


def test_portfolio_reset_clears_state_and_calls_record_command(monkeypatch):
    fake_agent = FakePortfolioAgent()
    fake_agent_manager = SimpleNamespace(agents={"portfolio": fake_agent})
    record_command = AsyncMock()

    monkeypatch.setattr(portfolio_router, "record_command", record_command)
    monkeypatch.setattr(portfolio_router, "get_runtime_context", lambda: {"agent_manager": fake_agent_manager})
    monkeypatch.setattr(portfolio_router, "settings", SimpleNamespace(PAPER_TRADING=True))
    monkeypatch.setattr(portfolio_router.pathlib.Path, "write_text", lambda self, text: len(text), raising=False)

    client = TestClient(_build_router_app(portfolio_router))
    response = client.post("/api/portfolio/reset")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "reset"
    assert body["wiped_open_positions"] == 1
    assert body["wiped_total"] == 2
    assert fake_agent.simulated_positions == {}
    assert fake_agent.positions == {}
    assert fake_agent.total_realized_pnl == 0.0
    assert fake_agent.total_unrealized_pnl == 0.0
    assert fake_agent.persist_calls == 1

    record_command.assert_awaited_once()
    assert record_command.await_args.args[1] == "portfolio_reset"
    assert record_command.await_args.args[2]["scope"] == "portfolio_admin"
    assert record_command.await_args.args[2]["wiped_open_positions"] == 1
    assert record_command.await_args.args[2]["wiped_total"] == 2


def test_command_journal_route_returns_filtered_entries(monkeypatch):
    fake_cache = FakeCache()
    fake_cache.store[manual_controls._k("command_journal")] = json.dumps([
        {
            "command_id": "mc_001",
            "action": "portfolio_reset",
            "scope": "portfolio_admin",
            "strategy_id": "ALPHA_SCALP_001",
            "status": "applied",
        },
        {
            "command_id": "mc_002",
            "action": "diagnostics_run",
            "scope": "system_observability",
            "status": "applied",
        },
    ])
    monkeypatch.setattr(admin_controls_router, "cache", fake_cache)

    client = TestClient(_build_router_app(admin_controls_router))
    response = client.get("/api/controls/command-journal?action=portfolio_reset&strategy_id=ALPHA_SCALP_001&limit=5")

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "command_journal"
    assert body["total"] == 1
    assert body["entries"][0]["command_id"] == "mc_001"
    assert body["entries"][0]["action"] == "portfolio_reset"


def test_equity_scanner_toggle_route_delegates_to_manual_controls(monkeypatch):
    fake_cache = FakeCache()
    toggle_equity_scanner = AsyncMock(return_value={"enabled": False, "reason": "maintenance"})

    monkeypatch.setattr(admin_controls_router, "cache", fake_cache)
    monkeypatch.setattr(admin_controls_router.mc, "toggle_equity_scanner", toggle_equity_scanner)

    client = TestClient(_build_router_app(admin_controls_router))
    response = client.post(
        "/api/controls/scanners/equity/toggle",
        json={"enabled": False, "reason": "maintenance"},
    )

    assert response.status_code == 200
    assert response.json() == {"enabled": False, "reason": "maintenance"}
    toggle_equity_scanner.assert_awaited_once_with(fake_cache, False, "maintenance")


def test_diagnostics_latest_route_returns_cached_payload(monkeypatch):
    fake_cache = FakeCache()
    fake_cache.store["diagnostics_latest"] = json.dumps({
        "cycle_id": "diag-2026-04-23T09:15",
        "critical_count": 1,
        "warning_count": 2,
        "info_count": 3,
        "findings": [{"id": "latency_spike", "severity": "warning"}],
    })
    monkeypatch.setattr(system_observability_router, "cache", fake_cache)

    client = TestClient(_build_router_app(system_observability_router))
    response = client.get("/api/system/diagnostics")

    assert response.status_code == 200
    body = response.json()
    assert body["cycle_id"] == "diag-2026-04-23T09:15"
    assert body["critical_count"] == 1
    assert body["findings"][0]["id"] == "latency_spike"


def test_run_diagnostics_route_uses_runtime_context_and_records_command(monkeypatch):
    @dataclass
    class FakeFinding:
        id: str
        severity: str
        title: str

    @dataclass
    class FakeReport:
        cycle_id: str
        timestamp: str
        findings: list[FakeFinding]
        auto_fixes_applied: int
        critical_count: int
        warning_count: int
        info_count: int
        run_duration_ms: float

    fake_agent_manager = SimpleNamespace(agents={})
    fake_cache = FakeCache()
    record_command = AsyncMock()
    fake_report = FakeReport(
        cycle_id="diag-2026-04-23T10:15",
        timestamp="2026-04-23T10:15:12",
        findings=[FakeFinding(id="latency_spike", severity="warning", title="Latency spike")],
        auto_fixes_applied=1,
        critical_count=0,
        warning_count=1,
        info_count=0,
        run_duration_ms=42.6,
    )
    fake_system_diagnostics = SimpleNamespace(run_diagnostics=AsyncMock(return_value=fake_report))

    monkeypatch.setattr(system_observability_router, "cache", fake_cache)
    monkeypatch.setattr(system_observability_router, "record_command", record_command)
    monkeypatch.setattr(system_observability_router, "get_runtime_context", lambda: {"agent_manager": fake_agent_manager})
    monkeypatch.setattr("src.intelligence.system_diagnostics.system_diagnostics", fake_system_diagnostics)

    client = TestClient(_build_router_app(system_observability_router))
    response = client.post("/api/system/diagnostics/run")

    assert response.status_code == 200
    body = response.json()
    assert body["cycle_id"] == "diag-2026-04-23T10:15"
    assert body["run_duration_ms"] == 42.6
    assert body["findings"][0]["title"] == "Latency spike"
    fake_system_diagnostics.run_diagnostics.assert_awaited_once_with(fake_agent_manager)

    record_command.assert_awaited_once()
    assert record_command.await_args.args[1] == "diagnostics_run"
    assert record_command.await_args.args[2]["scope"] == "system_observability"
    assert record_command.await_args.args[2]["warning_count"] == 1


def test_system_state_route_uses_canonical_v1_live_strategy_total(monkeypatch):
    fake_cache = FakeCache()
    fake_agent_manager = SimpleNamespace(agents={})

    monkeypatch.setattr(system_observability_router, "cache", fake_cache)
    monkeypatch.setattr(
        system_observability_router,
        "get_runtime_context",
        lambda: {"agent_manager": fake_agent_manager},
    )

    client = TestClient(_build_router_app(system_observability_router))
    response = client.get("/api/system/state")

    assert response.status_code == 200
    assert response.json()["backtest_total"] == len(V1_LIVE_STRATEGY_IDS)


def test_system_telemetry_route_exposes_cycle_intelligence_health(monkeypatch):
    fake_cache = FakeCache()
    fake_agent_manager = AgentManager(event_bus=object())
    fake_agent_manager.is_running = True
    fake_agent_manager._cycle_intelligence.update(
        {
            "scanner_directive": "BULL_STOCKS",
            "generated_by": "gemini",
            "generated_at": (datetime.now() - timedelta(minutes=31)).isoformat(),
            "_last_trigger_at": datetime.now() - timedelta(minutes=31),
        }
    )
    fake_agent_manager._cycle_intelligence_refreshing = True

    monkeypatch.setattr(system_observability_router, "cache", fake_cache)
    monkeypatch.setattr(
        system_observability_router,
        "get_runtime_context",
        lambda: {"agent_manager": fake_agent_manager},
    )

    client = TestClient(_build_router_app(system_observability_router))
    response = client.get("/api/system/telemetry")

    assert response.status_code == 200
    body = response.json()
    cycle_intelligence = body["cycle_intelligence"]
    assert cycle_intelligence["refresh_in_progress"] is True
    assert cycle_intelligence["is_stale"] is True
    assert cycle_intelligence["generated_at_raw"] is not None
    assert cycle_intelligence["generated_at_active"] is None
    assert cycle_intelligence["scanner_directive_raw"] == "BULL_STOCKS"
    assert cycle_intelligence["scanner_directive_active"] == "ALL"
    assert body["agent_manager_running"] is True


def test_system_telemetry_route_preserves_scanner_prefilter_metrics(monkeypatch):
    fake_cache = FakeCache()
    fake_agent_manager = SimpleNamespace(agents={}, is_running=False, _session_stats={})
    fixed_now = datetime(2026, 4, 27, 12, 35, 0)
    fake_cache.store["scanner_telemetry"] = json.dumps(
        {
            "cycles": 3,
            "last_cycle_requested_universe": 30,
            "last_cycle_universe": 12,
            "last_cycle_symbols_saved": 18,
            "last_cycle_scan_reduction_pct": 60.0,
            "total_requested_universe": 90,
            "total_universe_scanned": 54,
            "total_symbols_saved": 36,
            "prefilter_cycles": 2,
            "prefilter_requested_cycles": 3,
            "prefilter_blocked_cycles": 1,
            "prefilter_hit_rate_pct": 66.67,
            "prefilter_requested_hit_rate_pct": 66.67,
            "prefilter_blocked_rate_pct": 33.33,
            "avg_symbols_saved_per_prefilter_cycle": 18.0,
            "overall_scan_reduction_pct": 40.0,
            "dominant_prefilter_block_reason": "cache_stale",
            "dominant_prefilter_block_reason_count": 1,
            "dominant_prefilter_block_recommended_action": "Wait for a fresh scanner cache cycle before relying on directive narrowing.",
            "last_cycle_at": "2026-04-27T12:34:55",
        }
    )
    fake_cache.store["cycle_timing_latest"] = json.dumps(
        {
            "sensing": 63210.0,
            "decision": 12100.0,
            "monitoring": 1000.0,
            "total": 76310.0,
            "cycle_id": "cycle-123",
            "timestamp": "2026-04-27T12:34:56",
        }
    )

    monkeypatch.setattr(system_observability_router, "cache", fake_cache)
    monkeypatch.setattr(system_observability_router, "_get_telemetry_now", lambda _reference_ts=None: fixed_now)
    monkeypatch.setattr(
        system_observability_router,
        "get_runtime_context",
        lambda: {"agent_manager": fake_agent_manager},
    )

    client = TestClient(_build_router_app(system_observability_router))
    response = client.get("/api/system/telemetry")

    assert response.status_code == 200
    body = response.json()
    scanner = body["scanner"]
    scanner_status = body["scanner_status"]
    cycle_timing = body["cycle_timing"]
    cycle_timing_health = body["cycle_timing_health"]
    cycle_timing_bottleneck = body["cycle_timing_bottleneck"]
    assert scanner["last_cycle_symbols_saved"] == 18
    assert scanner["total_symbols_saved"] == 36
    assert scanner["prefilter_hit_rate_pct"] == 66.67
    assert scanner["prefilter_blocked_rate_pct"] == 33.33
    assert scanner["dominant_prefilter_block_reason"] == "cache_stale"
    assert scanner["dominant_prefilter_block_recommended_action"] == "Wait for a fresh scanner cache cycle before relying on directive narrowing."
    assert scanner["overall_scan_reduction_pct"] == 40.0
    assert scanner_status["status"] == "available"
    assert scanner_status["last_cycle_at"] == "2026-04-27T12:34:55"
    assert scanner_status["recommended_action"] is None
    assert scanner_status["age_s"] == 5.0
    assert scanner_status["stale_after_s"] == 600.0
    assert scanner_status["is_stale"] is False
    assert cycle_timing["sensing"] == 63210.0
    assert cycle_timing["total"] == 76310.0
    assert cycle_timing["cycle_id"] == "cycle-123"
    assert cycle_timing_health["status"] == "warning"
    assert cycle_timing_health["total_ms"] == 76310.0
    assert cycle_timing_health["warn_threshold_ms"] == 60000.0
    assert cycle_timing_health["crit_threshold_ms"] == 180000.0
    assert cycle_timing_health["recommended_action"] == "Monitor trend. May indicate degrading API performance."
    assert cycle_timing_health["freshness_status"] == "fresh"
    assert cycle_timing_health["freshness_recommended_action"] is None
    assert cycle_timing_health["age_s"] == 4.0
    assert cycle_timing_health["stale_after_s"] == 600.0
    assert cycle_timing_health["is_stale"] is False
    assert cycle_timing_bottleneck["phase"] == "sensing"
    assert cycle_timing_bottleneck["phase_ms"] == 63210.0
    assert cycle_timing_bottleneck["share_pct"] == 82.83
    assert cycle_timing_bottleneck["recommended_action"] == "Scanner or market-data collection dominates cycle time. Review prefilter hit rate, universe size, and upstream data latency."


def test_system_telemetry_route_marks_cycle_timing_unavailable_when_cache_missing(monkeypatch):
    fake_cache = FakeCache()
    fake_agent_manager = SimpleNamespace(agents={}, is_running=False, _session_stats={})

    monkeypatch.setattr(system_observability_router, "cache", fake_cache)
    monkeypatch.setattr(
        system_observability_router,
        "get_runtime_context",
        lambda: {"agent_manager": fake_agent_manager},
    )

    client = TestClient(_build_router_app(system_observability_router))
    response = client.get("/api/system/telemetry")

    assert response.status_code == 200
    body = response.json()
    assert body["scanner"] == {}
    assert body["scanner_status"]["status"] == "unavailable"
    assert body["scanner_status"]["last_cycle_at"] is None
    assert body["scanner_status"]["recommended_action"] == "Wait for a completed scanner cycle to populate telemetry."
    assert body["scanner_status"]["age_s"] is None
    assert body["scanner_status"]["stale_after_s"] == 600.0
    assert body["scanner_status"]["is_stale"] is None
    assert body["cycle_timing"] == {}
    assert body["cycle_timing_bottleneck"] == {}
    assert body["cycle_timing_health"]["status"] == "unavailable"
    assert body["cycle_timing_health"]["total_ms"] == 0.0
    assert body["cycle_timing_health"]["recommended_action"] == "Wait for a completed cycle to populate timing telemetry."
    assert body["cycle_timing_health"]["freshness_status"] == "unavailable"
    assert body["cycle_timing_health"]["freshness_recommended_action"] == "Wait for a completed cycle to populate timing telemetry."
    assert body["cycle_timing_health"]["age_s"] is None
    assert body["cycle_timing_health"]["stale_after_s"] == 600.0
    assert body["cycle_timing_health"]["is_stale"] is None


def test_system_telemetry_route_marks_scanner_and_timing_stale_when_timestamps_are_old(monkeypatch):
    fake_cache = FakeCache()
    fake_agent_manager = SimpleNamespace(agents={}, is_running=False, _session_stats={})
    fixed_now = datetime(2026, 4, 27, 12, 35, 0)
    fake_cache.store["scanner_telemetry"] = json.dumps(
        {
            "last_cycle_at": "2026-04-27T12:20:00",
            "last_cycle_symbols_saved": 10,
        }
    )
    fake_cache.store["cycle_timing_latest"] = json.dumps(
        {
            "sensing": 63210.0,
            "decision": 12100.0,
            "monitoring": 1000.0,
            "total": 76310.0,
            "cycle_id": "cycle-stale",
            "timestamp": "2026-04-27T12:19:00",
        }
    )

    monkeypatch.setattr(system_observability_router, "cache", fake_cache)
    monkeypatch.setattr(system_observability_router, "_get_telemetry_now", lambda _reference_ts=None: fixed_now)
    monkeypatch.setattr(
        system_observability_router,
        "get_runtime_context",
        lambda: {"agent_manager": fake_agent_manager},
    )

    client = TestClient(_build_router_app(system_observability_router))
    response = client.get("/api/system/telemetry")

    assert response.status_code == 200
    body = response.json()
    assert body["scanner_status"]["status"] == "stale"
    assert body["scanner_status"]["age_s"] == 900.0
    assert body["scanner_status"]["is_stale"] is True
    assert body["scanner_status"]["recommended_action"] == "Wait for a fresh scanner cycle before relying on current telemetry."
    assert body["cycle_timing_health"]["status"] == "warning"
    assert body["cycle_timing_health"]["freshness_status"] == "stale"
    assert body["cycle_timing_health"]["age_s"] == 960.0
    assert body["cycle_timing_health"]["is_stale"] is True
    assert body["cycle_timing_health"]["freshness_recommended_action"] == "Latest cycle timing is stale. Wait for a new completed cycle before relying on current timing telemetry."


def test_system_telemetry_route_marks_cycle_timing_in_progress_when_snapshot_is_active(monkeypatch):
    fake_cache = FakeCache()
    fake_agent_manager = SimpleNamespace(agents={}, is_running=True, _session_stats={})
    fixed_now = datetime(2026, 4, 27, 12, 35, 0)
    fake_cache.store["cycle_timing_latest"] = json.dumps(
        {
            "cycle_id": "cycle-live",
            "timestamp": "2026-04-27T12:33:30",
            "started_at": "2026-04-27T12:33:00",
            "current_phase": "sensing",
            "cycle_status": "in_progress",
            "total": 0.0,
        }
    )

    monkeypatch.setattr(system_observability_router, "cache", fake_cache)
    monkeypatch.setattr(system_observability_router, "_get_telemetry_now", lambda _reference_ts=None: fixed_now)
    monkeypatch.setattr(
        system_observability_router,
        "get_runtime_context",
        lambda: {"agent_manager": fake_agent_manager},
    )

    client = TestClient(_build_router_app(system_observability_router))
    response = client.get("/api/system/telemetry")

    assert response.status_code == 200
    body = response.json()
    assert body["cycle_timing"]["cycle_status"] == "in_progress"
    assert body["cycle_timing"]["current_phase"] == "sensing"
    assert body["cycle_timing_health"]["status"] == "in_progress"
    assert body["cycle_timing_health"]["cycle_status"] == "in_progress"
    assert body["cycle_timing_health"]["current_phase"] == "sensing"
    assert body["cycle_timing_health"]["total_ms"] == 120000.0
    assert body["cycle_timing_health"]["recommended_action"] == "Cycle timing is still in progress. Wait for completion for the final timing total."
    assert body["cycle_timing_health"]["freshness_status"] == "fresh"


def test_update_diagnostic_threshold_persists_and_records_command(monkeypatch):
    fake_cache = FakeCache()
    record_command = AsyncMock()
    fake_system_diagnostics = SimpleNamespace(
        thresholds={"portfolio_heat_max": 0.30},
        update_threshold=lambda key, value: key == "portfolio_heat_max",
        save_thresholds=AsyncMock(),
    )

    monkeypatch.setattr(system_observability_router, "cache", fake_cache)
    monkeypatch.setattr(system_observability_router, "record_command", record_command)
    monkeypatch.setattr("src.intelligence.system_diagnostics.system_diagnostics", fake_system_diagnostics)

    client = TestClient(_build_router_app(system_observability_router))
    response = client.post("/api/system/diagnostics/threshold?key=portfolio_heat_max&value=0.2")

    assert response.status_code == 200
    assert response.json() == {"updated": "portfolio_heat_max", "value": 0.2}
    fake_system_diagnostics.save_thresholds.assert_awaited_once()
    record_command.assert_awaited_once()
    assert record_command.await_args.args[1] == "diagnostics_threshold_update"
    assert record_command.await_args.args[2]["key"] == "portfolio_heat_max"
    assert record_command.await_args.args[2]["value"] == 0.2


def test_positions_route_falls_back_to_paper_positions(monkeypatch):
    fake_agent_manager = SimpleNamespace(
        agents={
            "portfolio": SimpleNamespace(
                simulated_positions={
                    "paper-open": {
                        "status": "OPEN",
                        "symbol": "NIFTY",
                        "quantity": 50,
                        "position_type": "OPTIONS",
                        "structure_type": "IRON_CONDOR",
                        "delta": 0.08,
                        "gamma": 0.031,
                        "metadata": {
                            "delta_policy": {"short_call_delta": 0.16, "short_put_delta": 0.16},
                            "greek_regime": "GAMMA_DANGEROUS",
                            "dte_days": 5,
                        },
                    },
                    "paper-closed": {"status": "CLOSED", "symbol": "BANKNIFTY", "quantity": 25},
                }
            )
        }
    )

    monkeypatch.setattr(operator_runtime_router, "settings", SimpleNamespace(PAPER_TRADING=True))
    monkeypatch.setattr(operator_runtime_router, "get_runtime_context", lambda: {"agent_manager": fake_agent_manager})
    monkeypatch.setattr("src.services.broker_factory.get_broker_client", lambda: FakeBrokerClient([]))

    client = TestClient(_build_router_app(operator_runtime_router))
    response = client.get("/positions")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["broker"] == "FAKE_BROKER"
    assert body["paper_trading"] is True
    assert body["positions"][0]["symbol"] == "NIFTY"
    assert body["positions"][0]["policy_snapshot"]["delta_upper_bound"] == 0.05
    assert body["positions"][0]["policy_snapshot"]["gamma_threshold"] == 0.03


def test_positions_route_falls_back_to_paper_positions_when_broker_client_creation_fails(monkeypatch):
    fake_agent_manager = SimpleNamespace(
        agents={
            "portfolio": SimpleNamespace(
                simulated_positions={
                    "paper-open": {
                        "status": "OPEN",
                        "symbol": "BANKNIFTY",
                        "quantity": 15,
                        "position_type": "EQUITY",
                    }
                }
            )
        }
    )

    def _raise_broker_client_error():
        raise RuntimeError("broker factory unavailable")

    monkeypatch.setattr(operator_runtime_router, "settings", SimpleNamespace(PAPER_TRADING=True))
    monkeypatch.setattr(operator_runtime_router, "get_runtime_context", lambda: {"agent_manager": fake_agent_manager})
    monkeypatch.setattr("src.services.broker_factory.get_broker_client", _raise_broker_client_error)

    client = TestClient(_build_router_app(operator_runtime_router))
    response = client.get("/positions")

    assert response.status_code == 200
    assert response.json() == {
        "positions": [
            {
                "status": "OPEN",
                "symbol": "BANKNIFTY",
                "quantity": 15,
                "position_type": "EQUITY",
                "policy_snapshot": None,
            }
        ],
        "count": 1,
        "broker": "unknown",
        "paper_trading": True,
    }


def test_positions_route_keeps_response_when_policy_snapshot_fails(monkeypatch):
    fake_agent_manager = SimpleNamespace(agents={})

    monkeypatch.setattr(operator_runtime_router, "settings", SimpleNamespace(PAPER_TRADING=False))
    monkeypatch.setattr(operator_runtime_router, "get_runtime_context", lambda: {"agent_manager": fake_agent_manager})
    monkeypatch.setattr(
        "src.services.broker_factory.get_broker_client",
        lambda: FakeBrokerClient([
            {
                "status": "OPEN",
                "symbol": "NIFTY",
                "quantity": 50,
                "position_type": "OPTIONS",
            }
        ]),
    )
    monkeypatch.setattr(
        operator_runtime_router,
        "build_policy_snapshot",
        lambda _position: (_ for _ in ()).throw(RuntimeError("policy snapshot unavailable")),
    )

    client = TestClient(_build_router_app(operator_runtime_router))
    response = client.get("/positions")

    assert response.status_code == 200
    assert response.json() == {
        "positions": [
            {
                "status": "OPEN",
                "symbol": "NIFTY",
                "quantity": 50,
                "position_type": "OPTIONS",
                "policy_snapshot": None,
            }
        ],
        "count": 1,
        "broker": "FAKE_BROKER",
        "paper_trading": False,
    }


def test_closed_positions_route_returns_empty_when_runtime_context_is_missing(monkeypatch):
    monkeypatch.setattr(operator_runtime_router, "get_runtime_context", lambda: {})

    client = TestClient(_build_router_app(operator_runtime_router))
    response = client.get("/closed_positions")

    assert response.status_code == 200
    assert response.json() == {"closed_positions": [], "count": 0}


def test_trades_route_gracefully_handles_broker_errors(monkeypatch):
    class _FailingBrokerClient:
        async def get_trades(self):
            raise RuntimeError("broker trades unavailable")

        def broker_name(self):
            return "FAKE_BROKER"

    monkeypatch.setattr("src.services.broker_factory.get_broker_client", lambda: _FailingBrokerClient())

    client = TestClient(_build_router_app(operator_runtime_router))
    response = client.get("/trades")

    assert response.status_code == 200
    assert response.json() == {"trades": [], "count": 0, "broker": "FAKE_BROKER"}


def test_trades_route_gracefully_handles_broker_client_creation_errors(monkeypatch):
    def _raise_broker_client_error():
        raise RuntimeError("broker factory unavailable")

    monkeypatch.setattr("src.services.broker_factory.get_broker_client", _raise_broker_client_error)

    client = TestClient(_build_router_app(operator_runtime_router))
    response = client.get("/trades")

    assert response.status_code == 200
    assert response.json() == {"trades": [], "count": 0, "broker": "unknown"}


def test_ai_status_route_returns_router_vertex_and_cost_sections(monkeypatch):
    class FakeAIRouter:
        def __init__(self):
            self.initialized = False

        async def initialize(self):
            self.initialized = True

        def get_status(self):
            return {"provider": "vertex", "fallback": "local"}

    fake_ai_router = FakeAIRouter()
    fake_cost_tracker = SimpleNamespace(get_status=lambda: {"daily_cost": 0.42})
    fake_vertex_client = SimpleNamespace(status=lambda: {"healthy": True, "region": "asia-south1"})

    monkeypatch.setattr("src.services.ai_router.ai_router", fake_ai_router)
    monkeypatch.setattr("src.services.ai_cost_tracker.ai_cost_tracker", fake_cost_tracker)
    monkeypatch.setattr("src.services.vertex_ai_client.vertex_ai_client", fake_vertex_client)

    client = TestClient(_build_router_app(operator_runtime_router))
    response = client.get("/ai/status")

    assert response.status_code == 200
    body = response.json()
    assert body["ai_router"] == {"provider": "vertex", "fallback": "local"}
    assert body["vertex_ai"] == {"healthy": True, "region": "asia-south1"}
    assert body["cost_tracker"] == {"daily_cost": 0.42}
    assert body["architecture"]["design"]
    assert fake_ai_router.initialized is True


def test_ai_status_route_gracefully_handles_vertex_and_cost_status_errors(monkeypatch):
    class FakeAIRouter:
        def __init__(self):
            self.initialized = False

        async def initialize(self):
            self.initialized = True

        def get_status(self):
            return {"provider": "local", "fallback": "none"}

    def _raise_vertex_status():
        raise RuntimeError("vertex status unavailable")

    class _FailingCostTracker:
        @staticmethod
        def get_status():
            raise RuntimeError("cost status unavailable")

    fake_ai_router = FakeAIRouter()
    fake_vertex_client = SimpleNamespace(status=_raise_vertex_status)

    monkeypatch.setattr("src.services.ai_router.ai_router", fake_ai_router)
    monkeypatch.setattr("src.services.ai_cost_tracker.ai_cost_tracker", _FailingCostTracker())
    monkeypatch.setattr("src.services.vertex_ai_client.vertex_ai_client", fake_vertex_client)

    client = TestClient(_build_router_app(operator_runtime_router))
    response = client.get("/ai/status")

    assert response.status_code == 200
    body = response.json()
    assert body["ai_router"] == {"provider": "local", "fallback": "none"}
    assert body["vertex_ai"]["available"] is False
    assert "error" in body["vertex_ai"]
    assert "error" in body["cost_tracker"]
    assert fake_ai_router.initialized is True


def test_ai_status_route_gracefully_handles_ai_router_initialize_and_status_errors(monkeypatch):
    class _FailingAIRouter:
        async def initialize(self):
            raise RuntimeError("ai_router init unavailable")

        def get_status(self):
            raise RuntimeError("ai_router status unavailable")

    fake_cost_tracker = SimpleNamespace(get_status=lambda: {"daily_cost": 0.0})
    fake_vertex_client = SimpleNamespace(status=lambda: {"available": False})

    monkeypatch.setattr("src.services.ai_router.ai_router", _FailingAIRouter())
    monkeypatch.setattr("src.services.ai_cost_tracker.ai_cost_tracker", fake_cost_tracker)
    monkeypatch.setattr("src.services.vertex_ai_client.vertex_ai_client", fake_vertex_client)

    client = TestClient(_build_router_app(operator_runtime_router))
    response = client.get("/ai/status")

    assert response.status_code == 200
    body = response.json()
    assert body["ai_router"]["initialized"] is False
    assert "initialize_error" in body["ai_router"]
    assert "error" in body["ai_router"]
    assert body["cost_tracker"] == {"daily_cost": 0.0}
    assert body["vertex_ai"] == {"available": False}


def test_public_health_route_reports_runtime_and_dependency_state(monkeypatch):
    fake_agent_manager = SimpleNamespace(is_running=True)
    fake_vertex_client = SimpleNamespace(
        is_available=lambda: True,
        _project="agent-alpha",
        _location="asia-south1",
        _default_model_name="gemini",
    )

    monkeypatch.setattr(
        public_status_router,
        "get_runtime_value",
        lambda key, default=None: fake_agent_manager if key == "agent_manager" else default,
    )
    monkeypatch.setattr(public_status_router, "is_market_open", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(public_status_router.db, "pool", object(), raising=False)
    monkeypatch.setattr(public_status_router.cache, "client", object(), raising=False)
    monkeypatch.setattr("src.services.vertex_ai_client.vertex_ai_client", fake_vertex_client)

    client = TestClient(_build_router_app(public_status_router))
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    assert body["market_open"] is True
    assert body["agents_running"] is True
    assert body["database"] == "connected"
    assert body["redis"] == "connected"
    assert body["vertex_ai"] == {
        "active": True,
        "project": "agent-alpha",
        "location": "asia-south1",
        "model": "gemini",
    }


def test_public_health_route_uses_vertex_status_contract_when_available(monkeypatch):
    fake_agent_manager = SimpleNamespace(is_running=False)
    fake_vertex_client = SimpleNamespace(
        is_available=lambda: False,
        _project="legacy-project",
        _location="legacy-location",
        _default_model_name="legacy-model",
        status=lambda: {
            "available": True,
            "project": "status-project",
            "location": "status-location",
            "default_model": "status-model",
        },
    )

    monkeypatch.setattr(
        public_status_router,
        "get_runtime_value",
        lambda key, default=None: fake_agent_manager if key == "agent_manager" else default,
    )
    monkeypatch.setattr(public_status_router, "is_market_open", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(public_status_router.db, "pool", None, raising=False)
    monkeypatch.setattr(public_status_router.cache, "client", None, raising=False)
    monkeypatch.setattr("src.services.vertex_ai_client.vertex_ai_client", fake_vertex_client)

    client = TestClient(_build_router_app(public_status_router))
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["vertex_ai"] == {
        "active": True,
        "project": "status-project",
        "location": "status-location",
        "model": "status-model",
    }


def test_public_health_route_does_not_eagerly_call_legacy_vertex_availability(monkeypatch):
    fake_agent_manager = SimpleNamespace(is_running=False)

    def _raise_is_available():
        raise RuntimeError("legacy availability unavailable")

    fake_vertex_client = SimpleNamespace(
        is_available=_raise_is_available,
        _project="legacy-project",
        _location="legacy-location",
        _default_model_name="legacy-model",
        status=lambda: {
            "available": True,
            "project": "status-project",
            "location": "status-location",
            "default_model": "status-model",
        },
    )

    monkeypatch.setattr(
        public_status_router,
        "get_runtime_value",
        lambda key, default=None: fake_agent_manager if key == "agent_manager" else default,
    )
    monkeypatch.setattr(public_status_router, "is_market_open", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(public_status_router.db, "pool", None, raising=False)
    monkeypatch.setattr(public_status_router.cache, "client", None, raising=False)
    monkeypatch.setattr("src.services.vertex_ai_client.vertex_ai_client", fake_vertex_client)

    client = TestClient(_build_router_app(public_status_router))
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["vertex_ai"] == {
        "active": True,
        "project": "status-project",
        "location": "status-location",
        "model": "status-model",
    }


def test_public_health_route_falls_back_when_vertex_status_raises(monkeypatch):
    fake_agent_manager = SimpleNamespace(is_running=True)

    def _raise_status():
        raise RuntimeError("status unavailable")

    fake_vertex_client = SimpleNamespace(
        is_available=lambda: False,
        _project="fallback-project",
        _location="fallback-location",
        _default_model_name="fallback-model",
        status=_raise_status,
    )

    monkeypatch.setattr(
        public_status_router,
        "get_runtime_value",
        lambda key, default=None: fake_agent_manager if key == "agent_manager" else default,
    )
    monkeypatch.setattr(public_status_router, "is_market_open", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(public_status_router.db, "pool", object(), raising=False)
    monkeypatch.setattr(public_status_router.cache, "client", object(), raising=False)
    monkeypatch.setattr("src.services.vertex_ai_client.vertex_ai_client", fake_vertex_client)

    client = TestClient(_build_router_app(public_status_router))
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["vertex_ai"] == {
        "active": False,
        "project": "fallback-project",
        "location": "fallback-location",
        "model": "fallback-model",
    }


def test_public_metrics_route_returns_exported_text(monkeypatch):
    monkeypatch.setattr(public_status_router.metrics, "export", lambda: "http_requests_total 3")

    client = TestClient(_build_router_app(public_status_router))
    response = client.get("/metrics")

    assert response.status_code == 200
    assert response.text == "http_requests_total 3"


def test_public_metrics_route_falls_back_when_export_fails(monkeypatch):
    def _raise_export_error():
        raise RuntimeError("collector unavailable")

    monkeypatch.setattr(public_status_router.metrics, "export", _raise_export_error)

    client = TestClient(_build_router_app(public_status_router))
    response = client.get("/metrics")

    assert response.status_code == 200
    assert response.text == "# metrics export unavailable: collector unavailable"


def test_public_win_rate_by_regime_route_uses_runtime_context(monkeypatch):
    fake_risk_agent = SimpleNamespace(
        _strategy_regime_win_rates={
            ("ALPHA_A", "BULL"): 0.61,
            ("ALPHA_B", "BEAR"): 0.55,
        },
        _strategy_regime_trade_counts={
            ("ALPHA_A", "BULL"): 12,
            ("ALPHA_B", "BEAR"): 4,
        },
        _day_type_win_rates={"TREND_DAY": 0.72},
        _day_type_trade_counts={"TREND_DAY": 9},
    )
    fake_agent_manager = SimpleNamespace(agents={"risk": fake_risk_agent})

    monkeypatch.setattr(
        public_status_router,
        "get_runtime_value",
        lambda key, default=None: fake_agent_manager if key == "agent_manager" else default,
    )

    client = TestClient(_build_router_app(public_status_router))
    response = client.get("/api/risk/win-rate-by-regime")

    assert response.status_code == 200
    body = response.json()
    assert body["strategy_regime"][0] == {
        "strategy": "ALPHA_A",
        "regime": "BULL",
        "win_rate": 61.0,
        "trades": 12,
    }
    assert body["day_type"] == [{
        "day_type": "TREND_DAY",
        "win_rate": 72.0,
        "trades": 9,
    }]


def test_public_market_status_route_returns_schedule_snapshot(monkeypatch):
    fixed_now = datetime(2026, 4, 23, 9, 20, 0)

    class FakeDateTime:
        @staticmethod
        def now():
            return fixed_now

    monkeypatch.setattr(public_status_router, "datetime", FakeDateTime)
    monkeypatch.setattr(public_status_router, "is_market_open", lambda now=None: True)
    monkeypatch.setattr(public_status_router, "is_market_day", lambda _date: True)
    monkeypatch.setattr(public_status_router, "NSE_MARKET_OPEN", dt_time(9, 15))
    monkeypatch.setattr(public_status_router, "NSE_MARKET_CLOSE", dt_time(15, 30))

    client = TestClient(_build_router_app(public_status_router))
    response = client.get("/market-status")

    assert response.status_code == 200
    assert response.json() == {
        "market_open": True,
        "is_trading_day": True,
        "server_time": "2026-04-23T09:20:00",
        "trading_start": "09:15:00",
        "trading_end": "15:30:00",
    }


def test_option_chain_scanner_defers_cache_seed_without_running_loop(monkeypatch):
    fake_cache = FakeCache()
    fake_nse_data = SimpleNamespace(get_fno_stocks=lambda: ["RELIANCE", "SBIN"])
    fake_ai_router = SimpleNamespace(
        initialize=AsyncMock(),
        get_status=lambda: {
            "vertex_available": False,
            "local_available": False,
            "provider_config": "none",
        },
    )

    def _raise_no_loop():
        raise RuntimeError("no running event loop")

    monkeypatch.setattr(option_chain_scanner_module.asyncio, "get_running_loop", _raise_no_loop)
    monkeypatch.setattr("src.services.nse_data.nse_data_service", fake_nse_data)
    monkeypatch.setattr("src.database.redis.cache", fake_cache)
    monkeypatch.setattr("src.services.ai_router.ai_router", fake_ai_router)

    agent = option_chain_scanner_module.OptionChainScannerAgent()

    assert agent._equity_fno == ["RELIANCE", "SBIN"]
    assert agent._equity_fno_cache_seed == ["RELIANCE", "SBIN"]

    asyncio.run(agent.start())

    assert fake_cache.store["oc_last_fno_stocks"] == json.dumps(["RELIANCE", "SBIN"])
    assert agent._equity_fno_cache_seed is None


def test_options_positions_route_uses_runtime_portfolio_state(monkeypatch):
    fake_agent_manager = SimpleNamespace(
        agents={
            "portfolio": SimpleNamespace(
                simulated_positions={
                    "opt-open": {
                        "position_type": "OPTIONS",
                        "status": "OPEN",
                        "symbol": "NIFTY",
                        "structure_type": "IRON_CONDOR",
                        "strategy_name": "ALPHA_OPTIONS",
                        "legs": [{"leg": 1}],
                        "entry_price": 100.0,
                        "unrealized_pnl": 25.5,
                        "realized_pnl": 10.0,
                        "delta": 0.12,
                        "gamma": 0.0015,
                        "theta": -5.2,
                        "vega": 1.4,
                        "metadata": {
                            "delta_policy": {
                                "short_call_delta": 0.16,
                                "short_put_delta": 0.16,
                                "long_call_delta": 0.05,
                                "long_put_delta": 0.05,
                            },
                            "greek_regime": "GAMMA_DANGEROUS",
                            "dte_days": 5,
                            "strike_selection": "delta_policy",
                        },
                    },
                    "opt-closed": {
                        "position_type": "OPTIONS",
                        "status": "CLOSED",
                        "symbol": "BANKNIFTY",
                    },
                }
            )
        }
    )

    monkeypatch.setattr(
        options_public_router,
        "get_runtime_value",
        lambda key, default=None: fake_agent_manager if key == "agent_manager" else default,
    )

    client = TestClient(_build_router_app(options_public_router))
    response = client.get("/options/positions")

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "simulated_positions"
    assert body["open_positions"] == 1
    assert body["total_positions"] == 2
    assert body["positions"][0]["position_id"] == "opt-open"
    assert body["positions"][0]["policy_snapshot"]["delta_upper_bound"] == 0.05
    assert body["positions"][0]["policy_snapshot"]["strike_selection"] == "delta_policy"
    assert body["portfolio_greeks"] == {
        "delta": 0.12,
        "gamma": 0.0015,
        "theta": -5.2,
        "vega": 1.4,
    }


def test_options_positions_route_returns_safe_fallback_when_summary_fails(monkeypatch):
    monkeypatch.setattr(
        options_public_router,
        "get_runtime_value",
        lambda key, default=None: None,
    )
    monkeypatch.setattr(
        "src.services.options_position_manager.options_position_manager",
        SimpleNamespace(portfolio_summary=lambda: (_ for _ in ()).throw(RuntimeError("summary unavailable"))),
    )

    client = TestClient(_build_router_app(options_public_router))
    response = client.get("/options/positions")

    assert response.status_code == 200
    assert response.json() == {
        "open_positions": 0,
        "total_positions": 0,
        "unrealized_pnl": 0.0,
        "realized_pnl": 0.0,
        "portfolio_greeks": {
            "delta": 0.0,
            "gamma": 0.0,
            "theta": 0.0,
            "vega": 0.0,
        },
        "positions": [],
        "source": "options_position_manager",
        "error": "summary unavailable",
    }


def test_options_chain_route_returns_capped_items(monkeypatch):
    class FakeItem:
        def __init__(self, idx):
            self.idx = idx

        def dict(self):
            return {"strike": self.idx}

    fake_chain = SimpleNamespace(
        symbol="NIFTY",
        spot_price=22345.0,
        expiry_dates=["2026-04-30"],
        atm_strike=22350,
        items=[FakeItem(index) for index in range(60)],
    )
    fake_service = SimpleNamespace(get_chain=AsyncMock(return_value=fake_chain))

    monkeypatch.setattr("src.services.option_chain.option_chain_service", fake_service)

    client = TestClient(_build_router_app(options_public_router))
    response = client.get("/options/chain/NIFTY?num_strikes=12&greeks=false")

    assert response.status_code == 200
    body = response.json()
    assert body["symbol"] == "NIFTY"
    assert body["items_count"] == 60
    assert len(body["items"]) == 50
    fake_service.get_chain.assert_awaited_once_with("NIFTY", num_strikes=12, enrich_greeks=False)


def test_options_chain_route_returns_safe_fallback_when_fetch_fails(monkeypatch):
    fake_service = SimpleNamespace(get_chain=AsyncMock(side_effect=RuntimeError("chain unavailable")))

    monkeypatch.setattr("src.services.option_chain.option_chain_service", fake_service)

    client = TestClient(_build_router_app(options_public_router))
    response = client.get("/options/chain/NIFTY")

    assert response.status_code == 200
    assert response.json() == {
        "symbol": "NIFTY",
        "spot_price": None,
        "expiry_dates": [],
        "atm_strike": None,
        "items_count": 0,
        "items": [],
        "error": "chain unavailable",
    }
    fake_service.get_chain.assert_awaited_once_with("NIFTY", num_strikes=10, enrich_greeks=True)


def test_options_greeks_route_returns_position_snapshot(monkeypatch):
    fake_position = SimpleNamespace(
        legs=[{"symbol": "NIFTY24000CE"}, {"symbol": "NIFTY22000PE"}],
        status=SimpleNamespace(value="OPEN"),
    )
    fake_position_manager = SimpleNamespace(get_position=lambda _position_id: fake_position)
    fake_greeks_engine = SimpleNamespace(
        portfolio_greeks=lambda _legs: SimpleNamespace(dict=lambda: {"delta": 0.08, "theta": -4.1})
    )

    monkeypatch.setattr("src.services.options_position_manager.options_position_manager", fake_position_manager)
    monkeypatch.setattr("src.services.greeks.greeks_engine", fake_greeks_engine)

    client = TestClient(_build_router_app(options_public_router))
    response = client.get("/options/greeks/pos-1")

    assert response.status_code == 200
    assert response.json() == {
        "position_id": "pos-1",
        "greeks": {"delta": 0.08, "theta": -4.1},
        "legs": 2,
        "status": "OPEN",
    }


def test_options_greeks_route_returns_safe_fallback_when_greeks_engine_fails(monkeypatch):
    fake_position = SimpleNamespace(
        legs=[{"symbol": "NIFTY24000CE"}],
        status=SimpleNamespace(value="OPEN"),
    )
    fake_position_manager = SimpleNamespace(get_position=lambda _position_id: fake_position)
    fake_greeks_engine = SimpleNamespace(
        portfolio_greeks=lambda _legs: (_ for _ in ()).throw(RuntimeError("greeks unavailable"))
    )

    monkeypatch.setattr("src.services.options_position_manager.options_position_manager", fake_position_manager)
    monkeypatch.setattr("src.services.greeks.greeks_engine", fake_greeks_engine)

    client = TestClient(_build_router_app(options_public_router))
    response = client.get("/options/greeks/pos-1")

    assert response.status_code == 200
    assert response.json() == {
        "position_id": "pos-1",
        "greeks": {},
        "legs": 1,
        "status": "OPEN",
        "error": "greeks unavailable",
    }


def test_options_validate_route_reports_validator_config(monkeypatch):
    monkeypatch.setattr(options_public_router.settings, "OPTIONS_ENABLED", True, raising=False)
    monkeypatch.setattr(
        "src.middleware.sebi_options.sebi_validator",
        SimpleNamespace(
            config=SimpleNamespace(
                max_lots_per_underlying=4,
                max_open_structures=8,
                margin_buffer_pct=0.15,
            )
        ),
    )

    client = TestClient(_build_router_app(options_public_router))
    response = client.get("/options/validate")

    assert response.status_code == 200
    assert response.json() == {
        "validator": "SEBIOptionsValidator",
        "enabled": True,
        "max_lots_per_ul": 4,
        "max_open_structures": 8,
        "margin_buffer_pct": 0.15,
    }


def test_options_validate_route_returns_safe_fallback_when_config_missing(monkeypatch):
    monkeypatch.setattr(options_public_router.settings, "OPTIONS_ENABLED", True, raising=False)
    monkeypatch.setattr(
        "src.middleware.sebi_options.sebi_validator",
        SimpleNamespace(config=None),
    )

    client = TestClient(_build_router_app(options_public_router))
    response = client.get("/options/validate")

    assert response.status_code == 200
    assert response.json() == {
        "validator": "SEBIOptionsValidator",
        "enabled": True,
        "max_lots_per_ul": 0,
        "max_open_structures": 0,
        "margin_buffer_pct": 0.0,
        "error": "'NoneType' object has no attribute 'max_lots_per_underlying'",
    }


def test_option_expiries_route_prefers_dhan_response(monkeypatch):
    fake_dhan_client = SimpleNamespace(
        is_connected=lambda: True,
        get_expiry_list=AsyncMock(return_value=["2026-04-30", "2026-05-07"]),
    )

    monkeypatch.setattr("src.services.dhan_client.get_dhan_client", lambda: fake_dhan_client)

    client = TestClient(_build_router_app(options_data_router))
    response = client.get("/api/options/expiries?symbol=banknifty")

    assert response.status_code == 200
    assert response.json() == {
        "symbol": "BANKNIFTY",
        "expiries": ["2026-04-30", "2026-05-07"],
        "source": "dhan",
    }


def test_option_dhan_chain_route_shapes_strikes(monkeypatch):
    fake_dhan_client = SimpleNamespace(
        get_expiry_list=AsyncMock(return_value=["2026-04-30"]),
        get_option_chain_native=AsyncMock(
            return_value={
                "last_price": 22345,
                "oc": {
                    "22300": {
                        "ce": {"last_price": 100, "greeks": {"delta": 0.4}},
                        "pe": {"last_price": 90, "greeks": {"delta": -0.5}},
                    },
                    "22350": {
                        "ce": {"last_price": 80, "greeks": {"delta": 0.3}},
                        "pe": {"last_price": 110, "greeks": {"delta": -0.6}},
                    },
                },
            }
        ),
    )

    monkeypatch.setattr("src.services.dhan_client.get_dhan_client", lambda: fake_dhan_client)

    client = TestClient(_build_router_app(options_data_router))
    response = client.get("/api/options/dhan-chain?symbol=NIFTY&atm_range=1")

    assert response.status_code == 200
    body = response.json()
    assert body["symbol"] == "NIFTY"
    assert body["expiry"] == "2026-04-30"
    assert body["count"] == 2
    assert body["source"] == "dhan"
    assert body["strikes"][0]["strike"] == 22300.0
    assert body["strikes"][1]["ce"]["delta"] == 0.3


def test_option_dhan_chain_route_returns_safe_fallback_when_payload_malformed(monkeypatch):
    fake_dhan_client = SimpleNamespace(
        get_expiry_list=AsyncMock(return_value=["2026-04-30"]),
        get_option_chain_native=AsyncMock(
            return_value={
                "last_price": 22345,
                "oc": {
                    "bad-strike": {
                        "ce": {"last_price": 100},
                        "pe": {"last_price": 90},
                    }
                },
            }
        ),
    )

    monkeypatch.setattr("src.services.dhan_client.get_dhan_client", lambda: fake_dhan_client)

    client = TestClient(_build_router_app(options_data_router))
    response = client.get("/api/options/dhan-chain?symbol=NIFTY&atm_range=1")

    assert response.status_code == 200
    assert response.json() == {
        "symbol": "NIFTY",
        "expiry": "2026-04-30",
        "spot_price": 0,
        "atm_strike": 0,
        "strikes": [],
        "count": 0,
        "source": "unavailable",
        "error": "could not convert string to float: 'bad-strike'",
    }


def test_option_vp_context_route_maps_bridge_payload(monkeypatch):
    fake_context = SimpleNamespace(
        symbol="NIFTY",
        expiry_type="weekly",
        expiry="2026-04-30",
        dte=7,
        spot=22345.0,
        vp_timeframe="30m",
        vp_timeframe_override="1h",
        poc=22300.0,
        vah=22400.0,
        val=22240.0,
        profile_shape="P",
        vp_range=160.0,
        spot_in_vp_pct=0.66,
        vp_zone="upper",
        precision_ceiling=22450.0,
        precision_floor=22200.0,
        max_pain=22350.0,
        pcr=0.92,
        iv_skew=-0.04,
        atm_iv=0.18,
        sell_ce=22400,
        buy_ce=22500,
        sell_pe=22200,
        buy_pe=22100,
        strike_step=50,
        suggested_structure="iron_condor",
        structure_rationale="Balanced around value area",
        confluence_score=7.8,
        ce_wall_oi=120000,
        pe_wall_oi=118000,
        data_source="dhan+vp",
        ce_walls=[22400],
        pe_walls=[22200],
    )

    monkeypatch.setattr(
        "src.services.vp_options_bridge.get_vp_options_context",
        AsyncMock(return_value=fake_context),
    )

    client = TestClient(_build_router_app(options_data_router))
    response = client.get("/api/options/vp-context?symbol=NIFTY&expiry_type=weekly&tf_override=1h&expiry=2026-04-30")

    assert response.status_code == 200
    body = response.json()
    assert body["symbol"] == "NIFTY"
    assert body["suggested_structure"] == "iron_condor"
    assert body["vp_timeframe_override"] == "1h"
    assert body["ce_walls"] == [22400]
    assert body["pe_walls"] == [22200]


def test_option_vp_context_route_returns_shape_safe_fallback_when_bridge_fails(monkeypatch):
    monkeypatch.setattr(
        "src.services.vp_options_bridge.get_vp_options_context",
        AsyncMock(side_effect=RuntimeError("vp bridge unavailable")),
    )

    client = TestClient(_build_router_app(options_data_router))
    response = client.get("/api/options/vp-context?symbol=NIFTY&expiry_type=weekly&tf_override=1h&expiry=2026-04-30")

    assert response.status_code == 200
    assert response.json() == {
        "symbol": "NIFTY",
        "expiry_type": "weekly",
        "expiry": "2026-04-30",
        "dte": 0,
        "spot": 0.0,
        "vp_timeframe": "",
        "vp_timeframe_override": "1h",
        "poc": 0.0,
        "vah": 0.0,
        "val": 0.0,
        "profile_shape": "",
        "vp_range": 0.0,
        "spot_in_vp_pct": 0.0,
        "vp_zone": "",
        "precision_ceiling": 0.0,
        "precision_floor": 0.0,
        "max_pain": 0.0,
        "pcr": 0.0,
        "iv_skew": 0.0,
        "atm_iv": 0.0,
        "sell_ce": 0,
        "buy_ce": 0,
        "sell_pe": 0,
        "buy_pe": 0,
        "strike_step": 0,
        "suggested_structure": "",
        "structure_rationale": "",
        "confluence_score": 0.0,
        "ce_wall_oi": 0,
        "pe_wall_oi": 0,
        "data_source": "unavailable",
        "ce_walls": [],
        "pe_walls": [],
        "error": "vp bridge unavailable",
    }


def test_options_scan_route_shapes_decisions_for_frontend(monkeypatch):
    class FakeScanner:
        def _default_fno_universe(self):
            return ["NIFTY", "BANKNIFTY"]

    class FakeDataService:
        async def get_historical_data(self, symbol, period="1y", interval="1d"):
            return list(range(25))

    fake_decisions = [
        SimpleNamespace(
            symbol="NIFTY",
            structure="IRON_CONDOR",
            confidence=0.83,
            iv_rank=47.6,
            rationale="Balanced volatility setup with stable premiums",
            risk_profile="defined-risk",
            legs=[{"strike": 22500, "expiry": "2026-04-30"}],
        )
    ]

    monkeypatch.setattr("src.services.nse_data.NSEDataService", lambda *args, **kwargs: FakeDataService())
    monkeypatch.setattr("src.strategies.options_setup_scanner.FnOSetupScanner", lambda *args, **kwargs: FakeScanner())
    monkeypatch.setattr(
        "src.strategies.options_setup_scanner.run_two_layer_scan",
        AsyncMock(return_value=fake_decisions),
    )

    client = TestClient(_build_router_app(options_data_router))
    response = client.post("/api/options-scan", json={})

    assert response.status_code == 200
    assert response.json() == [
        {
            "symbol": "NIFTY",
            "structure": "IRON_CONDOR",
            "score": 83,
            "ivRank": 47.6,
            "atmIv": 18.1,
            "pcr": 1.0,
            "atmStrike": 22500,
            "spot": 0.0,
            "expiry": "2026-04-30",
            "geminiAdvisory": "Balanced volatility setup with stable premiums",
            "riskProfile": "defined-risk",
            "legs": [{"strike": 22500, "expiry": "2026-04-30"}],
        }
    ]


def test_options_scan_route_returns_shape_safe_defaults_for_malformed_decision(monkeypatch):
    class FakeScanner:
        def _default_fno_universe(self):
            return ["NIFTY"]

    class FakeDataService:
        async def get_historical_data(self, symbol, period="1y", interval="1d"):
            return list(range(25))

    fake_decisions = [
        SimpleNamespace(
            symbol="NIFTY",
            structure="IRON_CONDOR",
            confidence=None,
            iv_rank=None,
            rationale=None,
            legs=[{"strike": 22500}],
        )
    ]

    monkeypatch.setattr("src.services.nse_data.NSEDataService", lambda *args, **kwargs: FakeDataService())
    monkeypatch.setattr("src.strategies.options_setup_scanner.FnOSetupScanner", lambda *args, **kwargs: FakeScanner())
    monkeypatch.setattr(
        "src.strategies.options_setup_scanner.run_two_layer_scan",
        AsyncMock(return_value=fake_decisions),
    )

    client = TestClient(_build_router_app(options_data_router))
    response = client.post("/api/options-scan", json={})
    expected_expiry = str((datetime.now() + timedelta(days=7)).date())

    assert response.status_code == 200
    assert response.json() == [
        {
            "symbol": "NIFTY",
            "structure": "IRON_CONDOR",
            "score": 0,
            "ivRank": 0.0,
            "atmIv": 0.0,
            "pcr": 1.0,
            "atmStrike": 22500,
            "spot": 0.0,
            "expiry": expected_expiry,
            "geminiAdvisory": None,
            "riskProfile": "",
            "legs": [{"strike": 22500}],
        }
    ]


def test_tradingview_webhook_route_executes_trade_with_stripped_symbol(monkeypatch):
    execute_trade = AsyncMock()
    fake_exec_agent = SimpleNamespace(mode="HYBRID", execute_trade=execute_trade)
    fake_risk_agent = SimpleNamespace(kill_switch_triggered=False)
    fake_agent_manager = SimpleNamespace(agents={"execution": fake_exec_agent, "risk": fake_risk_agent})
    monkeypatch.setattr(
        tradingview_webhook_router,
        "get_runtime_value",
        lambda key, default=None: fake_agent_manager if key == "agent_manager" else default,
    )
    monkeypatch.setattr(tradingview_webhook_router.settings, "TRADINGVIEW_WEBHOOK_SECRET", "", raising=False)

    client = TestClient(_build_router_app(tradingview_webhook_router))
    response = client.post(
        "/api/webhook/tradingview",
        json={"symbol": "NSE:RELIANCE", "action": "buy", "price": 2500, "strength": 0.9, "strategy": "TV_Alert"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "accepted", "symbol": "RELIANCE", "action": "BUY", "mode": "HYBRID"}
    execute_trade.assert_awaited_once()
    payload = execute_trade.await_args.args[0]
    assert payload["signal"]["symbol"] == "RELIANCE"
    assert payload["signal"]["signal_type"] == "BUY"
    assert payload["signal"]["source"] == "tradingview_webhook"


def test_tradingview_webhook_route_rejects_unknown_action_with_400(monkeypatch):
    monkeypatch.setattr(
        tradingview_webhook_router,
        "get_runtime_value",
        lambda key, default=None: None,
    )
    monkeypatch.setattr(tradingview_webhook_router.settings, "TRADINGVIEW_WEBHOOK_SECRET", "", raising=False)

    client = TestClient(_build_router_app(tradingview_webhook_router))
    response = client.post(
        "/api/webhook/tradingview",
        json={"symbol": "NSE:RELIANCE", "action": "hold", "price": 2500},
    )

    assert response.status_code == 400
    assert response.json() == {"error": "Unknown action 'HOLD'. Expected buy/sell/close."}


def test_ai_public_router_status_route_returns_router_status(monkeypatch):
    fake_ai_router = SimpleNamespace(get_status=lambda: {"provider": "vertex", "vertex_available": True})
    monkeypatch.setattr("src.services.ai_router.ai_router", fake_ai_router)

    client = TestClient(_build_router_app(ai_public_router))
    response = client.get("/api/ai/router")

    assert response.status_code == 200
    assert response.json() == {"provider": "vertex", "vertex_available": True}


def test_ai_public_router_cost_route_returns_cost_status(monkeypatch):
    fake_cost_tracker = SimpleNamespace(get_status=lambda: {"daily_cost": 0.42, "budget": 500.0})
    monkeypatch.setattr("src.services.ai_cost_tracker.ai_cost_tracker", fake_cost_tracker)

    client = TestClient(_build_router_app(ai_public_router))
    response = client.get("/api/ai/cost")

    assert response.status_code == 200
    assert response.json() == {"daily_cost": 0.42, "budget": 500.0}


def test_ai_public_router_status_route_falls_back_when_router_status_fails(monkeypatch):
    def _raise_status_error():
        raise RuntimeError("router status unavailable")

    fake_ai_router = SimpleNamespace(get_status=_raise_status_error)
    monkeypatch.setattr("src.services.ai_router.ai_router", fake_ai_router)

    client = TestClient(_build_router_app(ai_public_router))
    response = client.get("/api/ai/router")

    assert response.status_code == 200
    assert response.json() == {"error": "router status unavailable"}


def test_ai_public_router_cost_route_falls_back_when_cost_status_fails(monkeypatch):
    def _raise_cost_error():
        raise RuntimeError("cost status unavailable")

    fake_cost_tracker = SimpleNamespace(get_status=_raise_cost_error)
    monkeypatch.setattr("src.services.ai_cost_tracker.ai_cost_tracker", fake_cost_tracker)

    client = TestClient(_build_router_app(ai_public_router))
    response = client.get("/api/ai/cost")

    assert response.status_code == 200
    assert response.json() == {"error": "cost status unavailable"}


def test_ai_public_router_budget_route_updates_tracker_and_persists_budgets(monkeypatch):
    fake_cache = FakeCache()

    class FakeCostTracker:
        def __init__(self):
            self._daily_budget_inr = 100.0
            self._monthly_budget_inr = 2000.0

        def set_budgets(self, daily_inr=None, monthly_inr=None):
            if daily_inr is not None:
                self._daily_budget_inr = daily_inr
            if monthly_inr is not None:
                self._monthly_budget_inr = monthly_inr

    fake_cost_tracker = FakeCostTracker()
    monkeypatch.setattr(ai_public_router, "cache", fake_cache)
    monkeypatch.setattr("src.services.ai_cost_tracker.ai_cost_tracker", fake_cost_tracker)

    client = TestClient(_build_router_app(ai_public_router))
    response = client.post("/api/ai/budget?daily_inr=250&monthly_inr=4000")

    assert response.status_code == 200
    assert response.json() == {
        "daily_budget_inr": 250.0,
        "monthly_budget_inr": 4000.0,
        "status": "updated",
    }
    assert json.loads(fake_cache.store["ai_cost_budgets"]) == {
        "daily_inr": 250.0,
        "monthly_inr": 4000.0,
    }


def test_ai_public_router_budget_route_falls_back_when_budget_update_fails(monkeypatch):
    fake_cache = FakeCache()

    class FakeCostTracker:
        def __init__(self):
            self._daily_budget_inr = 100.0
            self._monthly_budget_inr = 2000.0

        def set_budgets(self, daily_inr=None, monthly_inr=None):
            raise RuntimeError("budget update unavailable")

    fake_cost_tracker = FakeCostTracker()
    monkeypatch.setattr(ai_public_router, "cache", fake_cache)
    monkeypatch.setattr("src.services.ai_cost_tracker.ai_cost_tracker", fake_cost_tracker)

    client = TestClient(_build_router_app(ai_public_router))
    response = client.post("/api/ai/budget?daily_inr=250&monthly_inr=4000")

    assert response.status_code == 200
    assert response.json() == {
        "daily_budget_inr": 100.0,
        "monthly_budget_inr": 2000.0,
        "status": "unchanged",
        "error": "budget update unavailable",
    }
    assert "ai_cost_budgets" not in fake_cache.store


def test_market_data_recent_signals_route_prefers_redis(monkeypatch):
    fake_cache = FakeCache()
    fake_cache.store["latest_signals"] = json.dumps(
        {
            "signals": [{"symbol": "NIFTY"}, {"symbol": "BANKNIFTY"}, {"symbol": "RELIANCE"}],
            "generated_at": "2026-04-23T10:00:00",
        }
    )
    monkeypatch.setattr(market_data_router, "cache", fake_cache)

    client = TestClient(_build_router_app(market_data_router))
    response = client.get("/api/signals/recent?limit=2")

    assert response.status_code == 200
    assert response.json() == {
        "signals": [{"symbol": "NIFTY"}, {"symbol": "BANKNIFTY"}],
        "count": 2,
        "generated_at": "2026-04-23T10:00:00",
        "source": "redis",
    }


def test_market_watchlist_route_prefers_dhan_quotes(monkeypatch):
    fake_dhan_client = SimpleNamespace(
        is_connected=lambda: True,
        get_batch_quotes=AsyncMock(
            return_value={
                "NIFTY": {"ltp": 22350.0, "close": 22300.0},
                "RELIANCE": {"ltp": 2901.5, "close": 2890.0},
            }
        ),
    )

    monkeypatch.setattr("src.services.dhan_client.get_dhan_client", lambda: fake_dhan_client)

    client = TestClient(_build_router_app(market_data_router))
    response = client.get("/api/market/watchlist?symbols=NIFTY,RELIANCE")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 2
    assert body["watchlist"][0]["source"] == "dhan"
    assert body["watchlist"][0]["price"] == 22350.0
    assert body["watchlist"][1]["symbol"] == "RELIANCE"


def test_market_watchlist_route_uses_yfinance_proxy_for_midcpnifty(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "src.services.dhan_client",
        SimpleNamespace(get_dhan_client=lambda: SimpleNamespace(is_connected=lambda: False)),
    )
    monkeypatch.setattr(market_data_router, "_get_kotak_ltp_map", AsyncMock(return_value={}))

    captured = {}

    class FakeTicker:
        def __init__(self, ticker_symbol):
            captured["ticker_symbol"] = ticker_symbol
            self.fast_info = SimpleNamespace(last_price=123.4, previous_close=120.0)

        def history(self, *args, **kwargs):
            raise AssertionError("history should not be called when fast_info succeeds")

    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(Ticker=FakeTicker))

    client = TestClient(_build_router_app(market_data_router))
    response = client.get("/api/market/watchlist?symbols=MIDCPNIFTY&backtest=true")

    assert response.status_code == 200
    body = response.json()
    assert body["watchlist"][0]["source"] == "yfinance"
    assert body["watchlist"][0]["price"] == 123.4
    assert captured["ticker_symbol"] == "^NSEMDCP50"


def test_market_watchlist_route_returns_safe_item_when_dhan_quote_row_is_malformed(monkeypatch):
    fake_dhan_client = SimpleNamespace(
        is_connected=lambda: True,
        get_batch_quotes=AsyncMock(return_value={"NIFTY": "bad-row"}),
    )

    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(Ticker=object))
    monkeypatch.setattr(market_data_router, "settings", SimpleNamespace(PAPER_TRADING=False, MODE="LIVE"))
    monkeypatch.setattr("src.services.dhan_client.get_dhan_client", lambda: fake_dhan_client)
    monkeypatch.setattr(market_data_router, "_get_kotak_ltp_map", AsyncMock(return_value={}))

    client = TestClient(_build_router_app(market_data_router))
    response = client.get("/api/market/watchlist?symbols=NIFTY")

    assert response.status_code == 200
    assert response.json() == {
        "watchlist": [
            {
                "symbol": "NIFTY",
                "price": 0,
                "change": 0,
                "change_pct": 0,
                "up": False,
                "source": "none",
                "error": "No live feed from Dhan/Kotak (yfinance disabled outside backtest)",
            }
        ],
        "count": 1,
    }


def test_get_user_watchlist_route_returns_cached_symbols(monkeypatch):
    fake_cache = FakeCache()
    fake_cache.store["user_watchlist"] = json.dumps(["NIFTY 50", "INFY"])
    monkeypatch.setattr(market_data_router, "cache", fake_cache)

    client = TestClient(_build_router_app(market_data_router))
    response = client.get("/api/user/watchlist")

    assert response.status_code == 200
    assert response.json() == {"symbols": ["NIFTY 50", "INFY"]}


def test_set_user_watchlist_route_sanitizes_and_persists_symbols(monkeypatch):
    fake_cache = FakeCache()
    monkeypatch.setattr(market_data_router, "cache", fake_cache)

    client = TestClient(_build_router_app(market_data_router))
    response = client.put(
        "/api/user/watchlist",
        json={"symbols": [" nifty 50 ", "RELIANCE", "reliance", 123, "", "infy"]},
    )

    assert response.status_code == 200
    assert response.json() == {"symbols": ["NIFTY 50", "RELIANCE", "INFY"]}
    assert json.loads(fake_cache.store["user_watchlist"]) == ["NIFTY 50", "RELIANCE", "INFY"]


def test_market_depth_route_returns_broker_depth(monkeypatch):
    fake_broker = SimpleNamespace(
        get_market_depth=AsyncMock(return_value={"buy": [{"price": 100}], "sell": [{"price": 101}]}),
        is_connected=lambda: True,
    )
    monkeypatch.setattr("src.services.broker_factory.get_broker_client", lambda: fake_broker)

    client = TestClient(_build_router_app(market_data_router))
    response = client.get("/api/market/depth/NIFTY")

    assert response.status_code == 200
    assert response.json() == {
        "symbol": "NIFTY",
        "bids": [{"price": 100}],
        "asks": [{"price": 101}],
        "connected": True,
    }


def test_get_execution_mode_route_returns_execution_agent_mode(monkeypatch):
    fake_agent_manager = SimpleNamespace(agents={"execution": SimpleNamespace(mode="HYBRID")})
    monkeypatch.setattr(
        trading_mode_router,
        "get_runtime_value",
        lambda key, default=None: fake_agent_manager if key == "agent_manager" else default,
    )

    client = TestClient(_build_router_app(trading_mode_router))
    response = client.get("/api/trading/execution-mode")

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "HYBRID"
    assert body["options"] == ["MANUAL", "HYBRID", "AUTO"]


def test_set_execution_mode_route_persists_to_cache(monkeypatch):
    fake_cache = FakeCache()
    fake_exec_agent = SimpleNamespace(mode="AUTO")
    fake_agent_manager = SimpleNamespace(agents={"execution": fake_exec_agent})
    monkeypatch.setattr(trading_mode_router, "cache", fake_cache)
    monkeypatch.setattr(
        trading_mode_router,
        "get_runtime_value",
        lambda key, default=None: fake_agent_manager if key == "agent_manager" else default,
    )

    client = TestClient(_build_router_app(trading_mode_router))
    response = client.post("/api/trading/execution-mode?mode=MANUAL")

    assert response.status_code == 200
    assert response.json()["mode"] == "MANUAL"
    assert fake_exec_agent.mode == "MANUAL"
    assert fake_cache.store["execution_mode"] == "MANUAL"


def test_set_trading_mode_route_updates_settings_and_cache(monkeypatch):
    fake_cache = FakeCache()
    monkeypatch.setattr(trading_mode_router, "cache", fake_cache)
    monkeypatch.setattr(trading_mode_router.settings, "PAPER_TRADING", False, raising=False)

    client = TestClient(_build_router_app(trading_mode_router))
    response = client.post("/api/trading/mode", json={"mode": "paper"})

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "mode": "PAPER",
        "paperTrading": True,
        "message": "Trading mode changed to PAPER",
    }
    assert fake_cache.store["trading_mode"] == "PAPER"


def test_get_trading_mode_route_reflects_settings(monkeypatch):
    monkeypatch.setattr(trading_mode_router.settings, "PAPER_TRADING", True, raising=False)

    client = TestClient(_build_router_app(trading_mode_router))
    response = client.get("/api/trading/mode")

    assert response.status_code == 200
    assert response.json() == {"mode": "PAPER", "paperTrading": True}


def test_get_execution_broker_route_returns_current_config(monkeypatch):
    fake_cache = FakeCache()
    fake_cache.store["current_vix"] = "18.5"
    fake_execution_router = SimpleNamespace(
        get_current_config=AsyncMock(
            return_value={
                "execution_broker": "auto",
                "effective_broker": "dhan",
                "data_broker": "dhan",
                "vix": 18.5,
            }
        )
    )
    monkeypatch.setattr(execution_broker_router, "cache", fake_cache)
    monkeypatch.setattr(execution_broker_router, "execution_router", fake_execution_router)

    client = TestClient(_build_router_app(execution_broker_router))
    response = client.get("/api/broker/execution-broker")

    assert response.status_code == 200
    assert response.json()["effective_broker"] == "dhan"
    fake_execution_router.get_current_config.assert_awaited_once_with(vix=18.5)


def test_set_execution_broker_route_updates_override(monkeypatch):
    fake_execution_router = SimpleNamespace(set_override=AsyncMock())
    monkeypatch.setattr(execution_broker_router, "execution_router", fake_execution_router)

    client = TestClient(_build_router_app(execution_broker_router))
    response = client.post("/api/broker/execution-broker?broker=kotak")

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "execution_broker": "kotak",
        "broker_name": "Kotak Neo",
        "data_broker": "dhan",
        "message": "Execution broker set to Kotak Neo. Data feeds remain on DhanHQ. Open positions route exits to their entry broker.",
    }
    fake_execution_router.set_override.assert_awaited_once_with("kotak")


def test_get_broker_status_route_returns_connection_snapshot(monkeypatch):
    class FakeBrokerClient:
        def is_connected(self):
            return True

        def broker_name(self):
            return "DhanHQ"

    monkeypatch.setattr("src.services.broker_factory.get_broker_client", lambda: FakeBrokerClient())
    monkeypatch.setattr(broker_management_router.settings, "PAPER_TRADING", True, raising=False)
    monkeypatch.setenv("BROKER", "dhan")
    monkeypatch.setenv("BROKER_FALLBACK", "kotak")

    client = TestClient(_build_router_app(broker_management_router))
    response = client.get("/api/broker/status")

    assert response.status_code == 200
    assert response.json() == {
        "broker": "dhan",
        "brokerName": "DhanHQ",
        "connected": True,
        "paperTrading": True,
        "fallbackBroker": "kotak",
        "failoverEnabled": True,
        "availableBrokers": [
            {"id": "dhan", "name": "DhanHQ", "cost": "Rs.499/month", "apiDocs": "https://dhanhq.co"},
            {"id": "kotak", "name": "Kotak Neo", "cost": "FREE", "apiDocs": "https://kotakneo.kotaksecurities.com"},
        ],
    }


def test_switch_broker_route_accepts_json_body_and_updates_cache(monkeypatch):
    fake_cache = FakeCache()
    reset_client = Mock()

    monkeypatch.setattr(broker_management_router, "cache", fake_cache)
    monkeypatch.setattr(broker_management_router.settings, "PAPER_TRADING", True, raising=False)
    monkeypatch.setattr("src.services.broker_factory.reset_broker_client", reset_client)

    client = TestClient(_build_router_app(broker_management_router))
    response = client.post("/api/broker/switch", json={"broker": "kotak"})

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "broker": "kotak",
        "message": "Switched to kotak. Reconnect to apply.",
    }
    assert fake_cache.store["active_broker"] == "kotak"
    reset_client.assert_called_once_with()


def test_update_broker_credentials_route_writes_backend_env_file(monkeypatch, tmp_path):
    fake_env = tmp_path / ".env"
    fake_env.write_text("KOTAK_UCC=old-value\n", encoding="utf-8")

    monkeypatch.setattr(broker_management_router.settings, "PAPER_TRADING", True, raising=False)
    monkeypatch.setattr(broker_management_router, "_get_backend_env_path", lambda: fake_env)
    monkeypatch.setattr("src.services.dhan_client.reset_dhan_client", lambda: None)
    monkeypatch.setattr("src.services.kotak_neo_client.reset_kotak_client", lambda: None)
    monkeypatch.setattr("src.services.broker_factory.reset_broker_client", lambda: None)
    monkeypatch.setattr("src.services.broker_factory.reset_execution_clients", lambda: None)
    monkeypatch.setattr("src.services.broker_factory.reset_data_client", lambda: None)
    monkeypatch.setattr("src.services.nse_data.nse_data_service._init_dhan_client", lambda: None)

    client = TestClient(_build_router_app(broker_management_router))
    response = client.post("/api/broker/credentials", json={"kotak_ucc": "ABC123"})

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["updated_fields"] == ["KOTAK_UCC"]
    assert "KOTAK_UCC=ABC123" in fake_env.read_text(encoding="utf-8")
    assert os.environ["KOTAK_UCC"] == "ABC123"


def test_update_kotak_totp_route_sets_env_and_resets_client(monkeypatch):
    reset_client = Mock()
    monkeypatch.setattr("src.services.kotak_neo_client.reset_kotak_client", reset_client)

    client = TestClient(_build_router_app(broker_management_router))
    response = client.post("/api/broker/kotak-totp", json={"totp": "123456"})

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert os.environ["KOTAK_TOTP"] == "123456"
    reset_client.assert_called_once_with()


def test_broker_diagnostics_route_reports_skipped_dhan_and_live_yfinance(monkeypatch):
    monkeypatch.delenv("DHAN_CLIENT_ID", raising=False)
    monkeypatch.delenv("DHAN_ACCESS_TOKEN", raising=False)

    class FakeKotakClient:
        def is_connected(self):
            return False

    class FakeFastInfo:
        last_price = 2450.5

    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol
            self.fast_info = FakeFastInfo()

    monkeypatch.setattr("src.services.kotak_neo_client.get_kotak_client", lambda: FakeKotakClient())
    monkeypatch.setattr("yfinance.Ticker", FakeTicker)

    client = TestClient(_build_router_app(broker_management_router))
    response = client.get("/api/broker/diagnostics")

    assert response.status_code == 200
    body = response.json()
    assert body["overall"] == "ok"
    assert body["tiers"]["dhan"]["status"] == "skipped"
    assert body["tiers"]["kotak"]["status"] == "error"
    assert body["tiers"]["yfinance"]["status"] == "ok"


def test_broker_connect_route_rejects_unknown_broker(monkeypatch):
    client = TestClient(_build_router_app(broker_management_router))
    response = client.post("/api/broker/connect?broker=zerodha")

    assert response.status_code == 200
    assert response.json() == {
        "connected": False,
        "broker": "zerodha",
        "message": "Unknown broker: zerodha. Supported: dhan, kotak",
    }


def test_get_module_filter_route_returns_cached_active_value(monkeypatch):
    fake_cache = FakeCache()
    fake_cache.store["strategy_module_filter"] = "OPTIONS"
    monkeypatch.setattr(config_filters_router, "cache", fake_cache)

    client = TestClient(_build_router_app(config_filters_router))
    response = client.get("/api/config/module-filter")

    assert response.status_code == 200
    body = response.json()
    assert body["active"] == "OPTIONS"
    assert body["options"][0]["id"] == "ALL"


def test_set_module_filter_route_persists_selection(monkeypatch):
    fake_cache = FakeCache()
    monkeypatch.setattr(config_filters_router, "cache", fake_cache)

    client = TestClient(_build_router_app(config_filters_router))
    response = client.post("/api/config/module-filter?module=EQUITY")

    assert response.status_code == 200
    assert response.json() == {"success": True, "active": "EQUITY", "label": "Equity Only"}
    assert fake_cache.store["strategy_module_filter"] == "EQUITY"


def test_get_trading_style_filter_route_returns_cached_active_value(monkeypatch):
    fake_cache = FakeCache()
    fake_cache.store["trading_style_filter"] = "SWING"
    monkeypatch.setattr(config_filters_router, "cache", fake_cache)

    client = TestClient(_build_router_app(config_filters_router))
    response = client.get("/api/config/trading-style")

    assert response.status_code == 200
    body = response.json()
    assert body["active"] == "SWING"
    assert body["options"][1]["id"] == "INTRADAY"


def test_set_trading_style_filter_route_persists_selection(monkeypatch):
    fake_cache = FakeCache()
    monkeypatch.setattr(config_filters_router, "cache", fake_cache)

    client = TestClient(_build_router_app(config_filters_router))
    response = client.post("/api/config/trading-style?style=INTRADAY")

    assert response.status_code == 200
    assert response.json() == {"success": True, "active": "INTRADAY", "label": "Intraday Only"}
    assert fake_cache.store["trading_style_filter"] == "INTRADAY"


def test_get_strategy_filter_route_returns_cached_active_value(monkeypatch):
    fake_cache = FakeCache()
    fake_cache.store["strategy_category_filter"] = "QUANT"
    monkeypatch.setattr(strategy_filter_router, "cache", fake_cache)

    client = TestClient(_build_router_app(strategy_filter_router))
    response = client.get("/api/config/strategy-filter")

    assert response.status_code == 200
    body = response.json()
    assert body["active"] == "QUANT"
    assert body["options"][0]["id"] == "AUTO"


def test_set_strategy_filter_route_persists_selection(monkeypatch):
    fake_cache = FakeCache()
    monkeypatch.setattr(strategy_filter_router, "cache", fake_cache)

    client = TestClient(_build_router_app(strategy_filter_router))
    response = client.post("/api/config/strategy-filter?category=SECTOR")

    assert response.status_code == 200
    assert response.json() == {"success": True, "active": "SECTOR", "label": "Sector Rotation"}
    assert fake_cache.store["strategy_category_filter"] == "SECTOR"


def test_get_universe_config_route_returns_cached_active_value(monkeypatch):
    fake_cache = FakeCache()
    fake_cache.store["scan_universe_type"] = "BANK_NIFTY"
    monkeypatch.setattr(universe_router, "cache", fake_cache)

    client = TestClient(_build_router_app(universe_router))
    response = client.get("/api/config/universe")

    assert response.status_code == 200
    body = response.json()
    assert body["active"] == "BANK_NIFTY"
    assert body["options"][0]["id"] == "AUTO"


def test_set_universe_config_route_persists_selection(monkeypatch):
    fake_cache = FakeCache()
    monkeypatch.setattr(universe_router, "cache", fake_cache)
    monkeypatch.setattr(
        universe_router,
        "UNIVERSE_OPTIONS",
        [
            {"id": "AUTO", "label": "Auto"},
            {"id": "FNO_50", "label": "F&O Top 50"},
        ],
    )

    client = TestClient(_build_router_app(universe_router))
    response = client.post("/api/config/universe?universe=FNO_50")

    assert response.status_code == 200
    assert response.json() == {"success": True, "active": "FNO_50", "label": "F&O Top 50"}
    assert fake_cache.store["scan_universe_type"] == "FNO_50"


def test_get_universe_symbols_route_returns_classified_sorted_entries(monkeypatch):
    monkeypatch.setattr(universe_router, "_UNIVERSE_STOCKS", {"AUTO": ["RELIANCE", "BANKNIFTY", "INFY"]})
    monkeypatch.setattr(universe_router, "UNIVERSE_OPTIONS", [{"id": "AUTO", "label": "Auto"}])
    monkeypatch.setattr(
        "src.services.option_chain.LOT_SIZES",
        {"BANKNIFTY": 15, "INFY": 300},
        raising=False,
    )

    client = TestClient(_build_router_app(universe_router))
    response = client.get("/api/universe/symbols?universe=AUTO")

    assert response.status_code == 200
    assert response.json() == {
        "universe": "AUTO",
        "universes": ["AUTO"],
        "indices": [{"symbol": "BANKNIFTY", "lot_size": 15, "has_options": True, "type": "INDEX"}],
        "equities": [
            {"symbol": "INFY", "lot_size": 300, "has_options": True, "type": "EQUITY"},
            {"symbol": "RELIANCE", "lot_size": 0, "has_options": False, "type": "EQUITY"},
        ],
        "total": 3,
    }


def test_backtest_universes_route_uses_static_auto_when_live_nse_empty(monkeypatch):
    monkeypatch.setattr(backtest_config_router, "AUTO_UNIVERSE", ["INFY", "RELIANCE"])
    monkeypatch.setattr(backtest_config_router, "NIFTY_200_FNO", ["INFY"])
    monkeypatch.setattr(backtest_config_router, "NIFTY_200", ["INFY"])
    monkeypatch.setattr(backtest_config_router, "NIFTY_100", ["INFY"])
    monkeypatch.setattr(backtest_config_router, "NIFTY_50", ["INFY"])
    monkeypatch.setattr(backtest_config_router, "FNO_200", ["RELIANCE"])
    monkeypatch.setattr(backtest_config_router, "FNO_UNIVERSE_50", ["RELIANCE"])
    monkeypatch.setattr(backtest_config_router, "FNO_UNIVERSE_20", ["RELIANCE"])
    monkeypatch.setattr(backtest_config_router, "BSE_SENSEX", ["SBIN"])
    monkeypatch.setattr(backtest_config_router, "BSE_100", ["SBIN"])
    monkeypatch.setattr(backtest_config_router, "BSE_FNO", ["SBIN"])
    monkeypatch.setattr(backtest_config_router, "BANKEX", ["HDFCBANK"])
    monkeypatch.setattr(backtest_config_router, "BANK_NIFTY", ["BANKNIFTY"])
    monkeypatch.setattr(backtest_config_router, "INDEX_UNIVERSE", ["NIFTY"])
    monkeypatch.setattr(
        "src.services.nse_data.nse_data_service",
        SimpleNamespace(get_nifty_100_stocks=lambda: [], get_fno_stocks=lambda: []),
        raising=False,
    )

    client = TestClient(_build_router_app(backtest_config_router))
    response = client.get("/api/backtest/universes")

    assert response.status_code == 200
    body = response.json()
    assert body["defaultUniverse"] == "auto"
    assert body["defaultCapital"] == 10_00_000
    assert body["universes"][0]["id"] == "auto"
    assert body["universes"][0]["stocks"] == ["INFY", "RELIANCE"]
    assert body["universes"][0]["count"] == 2


def test_backtest_universes_route_prefers_live_nse_combined_auto(monkeypatch):
    monkeypatch.setattr(backtest_config_router, "AUTO_UNIVERSE", ["SBIN", "INFY"])
    monkeypatch.setattr(backtest_config_router, "NIFTY_200_FNO", ["INFY"])
    monkeypatch.setattr(backtest_config_router, "NIFTY_200", ["INFY"])
    monkeypatch.setattr(backtest_config_router, "NIFTY_100", ["INFY"])
    monkeypatch.setattr(backtest_config_router, "NIFTY_50", ["INFY"])
    monkeypatch.setattr(backtest_config_router, "FNO_200", ["RELIANCE"])
    monkeypatch.setattr(backtest_config_router, "FNO_UNIVERSE_50", ["RELIANCE"])
    monkeypatch.setattr(backtest_config_router, "FNO_UNIVERSE_20", ["RELIANCE"])
    monkeypatch.setattr(backtest_config_router, "BSE_SENSEX", ["SBIN"])
    monkeypatch.setattr(backtest_config_router, "BSE_100", ["SBIN"])
    monkeypatch.setattr(backtest_config_router, "BSE_FNO", ["SBIN"])
    monkeypatch.setattr(backtest_config_router, "BANKEX", ["HDFCBANK"])
    monkeypatch.setattr(backtest_config_router, "BANK_NIFTY", ["BANKNIFTY"])
    monkeypatch.setattr(backtest_config_router, "INDEX_UNIVERSE", ["NIFTY"])
    monkeypatch.setattr(
        "src.services.nse_data.nse_data_service",
        SimpleNamespace(
            get_nifty_100_stocks=lambda: ["INFY", "TCS"],
            get_fno_stocks=lambda: ["TCS", "RELIANCE"],
        ),
        raising=False,
    )

    client = TestClient(_build_router_app(backtest_config_router))
    response = client.get("/api/backtest/universes")

    assert response.status_code == 200
    auto_entry = response.json()["universes"][0]
    assert auto_entry["id"] == "auto"
    assert auto_entry["stocks"] == ["INFY", "TCS", "RELIANCE", "SBIN"]
    assert auto_entry["count"] == 4


def test_backtest_run_route_starts_background_backtest(monkeypatch):
    created = {}
    scheduled = []

    class FakeBacktester:
        def __init__(self, capital, universe, period, custom_stocks=None):
            created["capital"] = capital
            created["universe"] = universe
            created["period"] = period
            created["custom_stocks"] = custom_stocks
            self.stocks = ["INFY", "RELIANCE"]
            self.indices = ["NIFTY"]
            self.status = {"status": "queued"}

        async def run(self):
            return None

    monkeypatch.setattr(backtest_runtime_router, "get_active_backtester", lambda: None)
    monkeypatch.setattr(backtest_runtime_router, "FullSystemBacktester", FakeBacktester)
    monkeypatch.setattr(backtest_runtime_router, "set_active_backtester", lambda bt: created.setdefault("active", bt))
    monkeypatch.setattr(backtest_runtime_router.asyncio, "create_task", lambda coro: scheduled.append(coro) or "task")

    client = TestClient(_build_router_app(backtest_runtime_router))
    response = client.post(
        "/api/backtest/run",
        json={"universe": "fno_50", "period": "3Y", "capital": 2500000, "stocks": ["INFY", "RELIANCE"]},
    )

    assert response.status_code == 200
    assert response.json() == {
        "message": "Backtest started",
        "universe": "custom",
        "period": "3Y",
        "capital": 2500000,
        "stocks": ["INFY", "RELIANCE"],
        "stockCount": 2,
        "indexCount": 1,
    }
    assert created["capital"] == 2500000
    assert created["universe"] == "custom"
    assert created["period"] == "3Y"
    assert created["custom_stocks"] == ["INFY", "RELIANCE"]
    assert len(scheduled) == 1
    scheduled[0].close()


def test_backtest_status_route_returns_idle_when_no_active_backtester(monkeypatch):
    monkeypatch.setattr(backtest_runtime_router, "get_active_backtester", lambda: None)

    client = TestClient(_build_router_app(backtest_runtime_router))
    response = client.get("/api/backtest/status")

    assert response.status_code == 200
    assert response.json() == {"status": "idle", "progress": 0, "currentTask": "No backtest run yet"}


def test_backtest_status_route_returns_active_backtester_status(monkeypatch):
    monkeypatch.setattr(
        backtest_runtime_router,
        "get_active_backtester",
        lambda: SimpleNamespace(status={"status": "running", "progress": 42, "currentTask": "Scanning universe"}),
    )

    client = TestClient(_build_router_app(backtest_runtime_router))
    response = client.get("/api/backtest/status")

    assert response.status_code == 200
    assert response.json() == {"status": "running", "progress": 42, "currentTask": "Scanning universe"}


def test_chart_ohlcv_route_uses_nse_index_service_for_daily_index_requests(monkeypatch):
    import pandas as pd

    fake_nse_data_module = SimpleNamespace(
        nse_data_service=SimpleNamespace(
            get_index_ohlc=AsyncMock(
                return_value=pd.DataFrame(
                    [
                        {
                            "date": pd.Timestamp("2026-04-22"),
                            "open": 24123.4,
                            "high": 24210.8,
                            "low": 24098.2,
                            "close": 24188.6,
                            "volume": 123456,
                        }
                    ]
                )
            )
        )
    )
    monkeypatch.setitem(sys.modules, "src.services.nse_data", fake_nse_data_module)

    client = TestClient(_build_router_app(chart_ohlcv_router))
    response = client.get("/api/charts/ohlcv/NIFTY?period=3mo&interval=1d")

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "nse_data_service"
    assert body["count"] == 1
    assert body["candles"][0] == {
        "time": int(pd.Timestamp("2026-04-22").timestamp()),
        "open": 24123.4,
        "high": 24210.8,
        "low": 24098.2,
        "close": 24188.6,
        "volume": 123456,
    }
    fake_nse_data_module.nse_data_service.get_index_ohlc.assert_awaited_once_with("NIFTY 50", period="3mo")


def test_chart_ohlcv_route_returns_yfinance_fallback_candles_in_backtest_mode(monkeypatch):
    import pandas as pd

    class FakeTicker:
        def __init__(self, ticker_symbol):
            self.ticker_symbol = ticker_symbol

        def history(self, period, interval, auto_adjust=True):
            assert period == "1d"
            assert interval == "1m"
            assert auto_adjust is True
            return pd.DataFrame(
                {
                    "Open": [100.25, 101.0],
                    "High": [101.5, 102.25],
                    "Low": [99.8, 100.75],
                    "Close": [101.2, 101.9],
                    "Volume": [1000, 1200],
                },
                index=pd.to_datetime(["2026-04-23 09:15:00", "2026-04-23 09:16:00"]),
            )

    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(Ticker=FakeTicker))

    client = TestClient(_build_router_app(chart_ohlcv_router))
    response = client.get("/api/charts/ohlcv/RELIANCE?period=1d&interval=1m&backtest=true")

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "yfinance"
    assert body["ticker"] == "RELIANCE.NS"
    assert body["count"] == 2
    assert body["candles"] == [
        {
            "time": int(pd.Timestamp("2026-04-23 09:15:00").timestamp()),
            "open": 100.25,
            "high": 101.5,
            "low": 99.8,
            "close": 101.2,
            "volume": 1000,
        },
        {
            "time": int(pd.Timestamp("2026-04-23 09:16:00").timestamp()),
            "open": 101.0,
            "high": 102.25,
            "low": 100.75,
            "close": 101.9,
            "volume": 1200,
        },
    ]


def test_chart_intraday_route_returns_yfinance_fallback_latest_session(monkeypatch):
    import pandas as pd

    disconnected_client = SimpleNamespace(is_connected=lambda: False)
    monkeypatch.setitem(sys.modules, "src.services.dhan_market_feed", SimpleNamespace(_DHAN_SECURITY_MAP={"RELIANCE": ("123", "NSE_EQ")}))
    monkeypatch.setitem(sys.modules, "src.services.dhan_client", SimpleNamespace(get_dhan_client=lambda: disconnected_client))

    class FakeTicker:
        def __init__(self, ticker_symbol):
            self.ticker_symbol = ticker_symbol

        def history(self, period, interval, auto_adjust=True):
            assert period == "5d"
            return pd.DataFrame(
                {
                    "Open": [99.0, 100.25, 101.0],
                    "High": [100.0, 101.5, 102.25],
                    "Low": [98.75, 99.8, 100.75],
                    "Close": [99.75, 101.2, 101.9],
                    "Volume": [900, 1000, 1200],
                },
                index=pd.to_datetime([
                    "2026-04-22 15:29:00",
                    "2026-04-23 09:15:00",
                    "2026-04-23 09:16:00",
                ]),
            )

    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(Ticker=FakeTicker))

    client = TestClient(_build_router_app(chart_support_router))
    response = client.get("/api/charts/intraday/RELIANCE?interval=1m&backtest=true")

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "yfinance"
    assert body["count"] == 2
    assert body["prev_close"] == 99.75
    assert body["candles"][0]["time"] == int(pd.Timestamp("2026-04-23 09:15:00").timestamp())
    assert body["candles"][1]["close"] == 101.9


def test_chart_indicators_route_uses_ohlcv_data_for_requested_outputs(monkeypatch):
    candles = [
        {
            "time": 1700000000 + index * 60,
            "open": 100 + index,
            "high": 101 + index,
            "low": 99 + index,
            "close": 100.5 + index,
            "volume": 1000 + index * 10,
        }
        for index in range(25)
    ]
    monkeypatch.setattr(chart_support_router, "get_ohlcv", AsyncMock(return_value={"source": "yfinance", "candles": candles}))

    client = TestClient(_build_router_app(chart_support_router))
    response = client.get("/api/charts/indicators/RELIANCE?period=3mo&interval=1d&indicators=ema,vwap")

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "yfinance"
    assert "ema" in body["indicators"]
    assert "ema9" in body["indicators"]["ema"]
    assert body["indicators"]["ema"]["ema9"]
    assert body["indicators"]["vwap"]


def test_chart_signals_route_returns_cached_markers_for_symbol(monkeypatch, tmp_path):
    fake_cache = FakeCache()
    fake_cache.store["latest_signals"] = json.dumps(
        {
            "signals": [
                {
                    "symbol": "RELIANCE",
                    "timestamp": datetime.now().isoformat(),
                    "signal_type": "BUY",
                    "strategy_name": "Momentum",
                    "entry_price": 2500,
                    "strength": 0.9,
                }
            ]
        }
    )
    monkeypatch.setattr(chart_support_router, "cache", fake_cache)
    monkeypatch.setattr(chart_support_router, "_get_backend_paper_trades_path", lambda: tmp_path / "paper_trades.json")

    client = TestClient(_build_router_app(chart_support_router))
    response = client.get("/api/charts/signals/RELIANCE?days=90")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["markers"][0]["type"] == "BUY"
    assert body["markers"][0]["strategy"] == "Momentum"


def test_volume_profile_route_returns_profile_from_intraday_data(monkeypatch):
    candles = [
        {
            "time": 1700000000 + index * 300,
            "open": 100 + index * 0.1,
            "high": 100.5 + index * 0.1,
            "low": 99.5 + index * 0.1,
            "close": 100.2 + index * 0.1,
            "volume": 1000 + index,
        }
        for index in range(20)
    ]
    fake_profile = SimpleNamespace(
        buckets={100.0: SimpleNamespace(total_volume=1200, buy_volume=700, sell_volume=500, delta=200, is_hvn=True, is_lvn=False)},
        footprints=[],
        as_dict=lambda: {"poc_price": 100.0, "vah_price": 101.0, "val_price": 99.0},
    )
    fake_session_profiles = SimpleNamespace(
        current_profile=lambda: fake_profile,
        full_day=fake_profile,
        as_dict=lambda: {"full_day": {"poc_price": 100.0}},
    )
    monkeypatch.setattr(chart_support_router, "get_intraday", AsyncMock(return_value={"candles": candles}))
    monkeypatch.setitem(
        sys.modules,
        "src.strategies.candle_volume_profile",
        SimpleNamespace(
            build_candle_volume_profile=lambda df, lookback_candles=None: fake_profile,
            build_session_volume_profiles=lambda df: fake_session_profiles,
            detect_microstructure_patterns=lambda mvp, current_price, current_ofi=0.0: [{"pattern": "balance"}],
        ),
    )
    monkeypatch.setitem(sys.modules, "src.services.dhan_depth_feed", SimpleNamespace(get_dhan_depth_feed=lambda: None))

    client = TestClient(_build_router_app(chart_support_router))
    response = client.get("/api/charts/volume-profile/RELIANCE?session=auto&interval=5m")

    assert response.status_code == 200
    body = response.json()
    assert body["profile"] == {"poc_price": 100.0, "vah_price": 101.0, "val_price": 99.0}
    assert body["patterns"] == [{"pattern": "balance"}]
    assert body["histogram"][0]["price"] == 100.0


def test_volume_profile_route_uses_recent_cached_depth_for_ofi_when_feed_reconnecting(monkeypatch):
    candles = [
        {
            "time": 1700000000 + index * 300,
            "open": 100 + index * 0.1,
            "high": 100.5 + index * 0.1,
            "low": 99.5 + index * 0.1,
            "close": 100.2 + index * 0.1,
            "volume": 1000 + index,
        }
        for index in range(20)
    ]
    fake_profile = SimpleNamespace(
        buckets={100.0: SimpleNamespace(total_volume=1200, buy_volume=700, sell_volume=500, delta=200, is_hvn=True, is_lvn=False)},
        footprints=[],
        as_dict=lambda: {"poc_price": 100.0, "vah_price": 101.0, "val_price": 99.0, "profile_shape": "D"},
    )
    fake_session_profiles = SimpleNamespace(
        current_profile=lambda: fake_profile,
        full_day=fake_profile,
        as_dict=lambda: {"full_day": {"poc_price": 100.0}},
    )
    fake_ofi = SimpleNamespace(
        weighted_ofi=0.42,
        raw_bid_pressure=3200.0,
        raw_ask_pressure=1800.0,
        iceberg_detected=True,
        iceberg_side="BID",
        top_3_bid_qty=900,
        top_3_ask_qty=450,
        deep_bid_qty=2400,
        deep_ask_qty=700,
        levels_with_data=18,
    )
    fake_depth_feed = SimpleNamespace(
        _running=False,
        get_depth=lambda _symbol: SimpleNamespace(timestamp=datetime.now().timestamp()),
        compute_ofi=lambda _symbol: fake_ofi,
    )
    monkeypatch.setattr(chart_support_router, "get_intraday", AsyncMock(return_value={"candles": candles}))
    monkeypatch.setitem(
        sys.modules,
        "src.strategies.candle_volume_profile",
        SimpleNamespace(
            build_candle_volume_profile=lambda df, lookback_candles=None: fake_profile,
            build_session_volume_profiles=lambda df: fake_session_profiles,
            detect_microstructure_patterns=lambda mvp, current_price, current_ofi=0.0: [{"pattern": "trend", "ofi": current_ofi}],
        ),
    )
    monkeypatch.setitem(sys.modules, "src.services.dhan_depth_feed", SimpleNamespace(get_dhan_depth_feed=lambda: fake_depth_feed))

    client = TestClient(_build_router_app(chart_support_router))
    response = client.get("/api/charts/volume-profile/RELIANCE?session=auto&interval=5m")

    assert response.status_code == 200
    body = response.json()
    assert body["ofi"] == {
        "weighted_ofi": 0.42,
        "raw_bid_pressure": 3200.0,
        "raw_ask_pressure": 1800.0,
        "iceberg_detected": True,
        "iceberg_side": "BID",
        "top_3_bid_qty": 900,
        "top_3_ask_qty": 450,
        "deep_bid_qty": 2400,
        "deep_ask_qty": 700,
        "levels_with_data": 18,
    }
    assert body["patterns"] == [{"pattern": "trend", "ofi": 0.42}]


def test_volume_profile_route_skips_stale_cached_depth_when_feed_not_running(monkeypatch):
    candles = [
        {
            "time": 1700000000 + index * 300,
            "open": 100 + index * 0.1,
            "high": 100.5 + index * 0.1,
            "low": 99.5 + index * 0.1,
            "close": 100.2 + index * 0.1,
            "volume": 1000 + index,
        }
        for index in range(20)
    ]
    fake_profile = SimpleNamespace(
        buckets={100.0: SimpleNamespace(total_volume=1200, buy_volume=700, sell_volume=500, delta=200, is_hvn=True, is_lvn=False)},
        footprints=[],
        as_dict=lambda: {"poc_price": 100.0, "vah_price": 101.0, "val_price": 99.0, "profile_shape": "D"},
    )
    fake_session_profiles = SimpleNamespace(
        current_profile=lambda: fake_profile,
        full_day=fake_profile,
        as_dict=lambda: {"full_day": {"poc_price": 100.0}},
    )
    fake_depth_feed = SimpleNamespace(
        _running=False,
        get_depth=lambda _symbol: SimpleNamespace(timestamp=datetime.now().timestamp() - 300),
        compute_ofi=lambda _symbol: (_ for _ in ()).throw(AssertionError("stale depth should not be used")),
    )
    monkeypatch.setattr(chart_support_router, "get_intraday", AsyncMock(return_value={"candles": candles}))
    monkeypatch.setitem(
        sys.modules,
        "src.strategies.candle_volume_profile",
        SimpleNamespace(
            build_candle_volume_profile=lambda df, lookback_candles=None: fake_profile,
            build_session_volume_profiles=lambda df: fake_session_profiles,
            detect_microstructure_patterns=lambda mvp, current_price, current_ofi=0.0: [{"pattern": "balance", "ofi": current_ofi}],
        ),
    )
    monkeypatch.setitem(sys.modules, "src.services.dhan_depth_feed", SimpleNamespace(get_dhan_depth_feed=lambda: fake_depth_feed))

    client = TestClient(_build_router_app(chart_support_router))
    response = client.get("/api/charts/volume-profile/RELIANCE?session=auto&interval=5m")

    assert response.status_code == 200
    body = response.json()
    assert body["ofi"] is None
    assert body["patterns"] == [{"pattern": "balance", "ofi": 0.0}]


def test_candle_vp_route_returns_footprints_and_publishes_delta(monkeypatch):
    candles = [
        {
            "time": 1700000000 + index * 300,
            "open": 100 + index * 0.1,
            "high": 101 + index * 0.1,
            "low": 99 + index * 0.1,
            "close": 100.5 + index * 0.1,
            "volume": 1000 + index,
        }
        for index in range(25)
    ]
    fake_redis = SimpleNamespace(store={})

    async def fake_set(key, value, ex=None):
        fake_redis.store[key] = value
        return True

    fake_redis.set = fake_set
    fake_footprint = SimpleNamespace(
        timestamp=datetime(2026, 4, 23, 9, 15),
        open=100.0,
        high=102.0,
        low=99.0,
        close=101.0,
        poc_price=100.5,
        candle_delta=12.5,
        levels={99.5: (10, 5), 100.5: (20, 15), 101.5: (5, 25)},
    )
    monkeypatch.setattr(chart_support_router, "get_ohlcv", AsyncMock(return_value={"candles": candles}))
    monkeypatch.setattr(chart_support_router, "cache", fake_redis)
    monkeypatch.setitem(
        sys.modules,
        "src.strategies.candle_volume_profile",
        SimpleNamespace(build_candle_volume_profile=lambda df, lookback_candles=None: SimpleNamespace(footprints=[fake_footprint])),
    )

    client = TestClient(_build_router_app(chart_support_router))
    response = client.get("/api/charts/candle-vp/RELIANCE?interval=5m&bars=25")

    assert response.status_code == 200
    body = response.json()
    assert len(body["footprints"]) == 1
    assert len(body["footprints"][0]["nodes"]) == 20
    assert fake_redis.store["footprint_delta:RELIANCE"] == "12.5"


def test_market_quote_route_returns_yfinance_fallback_in_backtest_mode(monkeypatch):
    monkeypatch.setitem(sys.modules, "src.services.dhan_client", SimpleNamespace(get_dhan_client=lambda: SimpleNamespace(is_connected=lambda: False)))
    monkeypatch.setattr(market_data_router, "_get_kotak_ltp_map", AsyncMock(return_value={}))

    class FakeTicker:
        def __init__(self, ticker_symbol):
            self.fast_info = SimpleNamespace(last_price=2501.5)

    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(Ticker=FakeTicker))

    client = TestClient(_build_router_app(market_data_router))
    response = client.get("/api/market/quote/RELIANCE?backtest=true")

    assert response.status_code == 200
    assert response.json() == {
        "symbol": "RELIANCE",
        "source": "yfinance",
        "mode": "ticker",
        "data": {"ltp": 2501.5, "open": 0, "high": 0, "low": 0, "close": 0},
    }


def test_account_fund_limits_route_returns_error_when_dhan_disconnected(monkeypatch):
    monkeypatch.setitem(sys.modules, "src.services.dhan_client", SimpleNamespace(get_dhan_client=lambda: SimpleNamespace(is_connected=lambda: False)))

    client = TestClient(_build_router_app(account_router))
    response = client.get("/api/account/fund-limits")

    assert response.status_code == 200
    assert response.json() == {"error": "DhanHQ not connected", "data": {}}


def test_account_holdings_route_returns_active_broker_holdings(monkeypatch):
    fake_client = SimpleNamespace(
        is_connected=lambda: True,
        broker_name=lambda: "KOTAK",
        get_holdings=AsyncMock(return_value=[{"symbol": "RELIANCE", "qty": 10}]),
    )
    monkeypatch.setitem(sys.modules, "src.services.broker_factory", SimpleNamespace(get_broker_client=lambda: fake_client))

    client = TestClient(_build_router_app(account_router))
    response = client.get("/api/account/holdings")

    assert response.status_code == 200
    assert response.json() == {"broker": "KOTAK", "holdings": [{"symbol": "RELIANCE", "qty": 10}]}


def test_backtest_full_results_route_returns_active_portfolio_results(monkeypatch):
    monkeypatch.setattr(
        backtest_results_router,
        "get_active_backtester",
        lambda: SimpleNamespace(portfolio_results={"strategies": [{"strategyId": "STRAT1"}], "count": 1}),
    )

    client = TestClient(_build_router_app(backtest_results_router))
    response = client.get("/api/backtest/full-results")

    assert response.status_code == 200
    assert response.json() == {"strategies": [{"strategyId": "STRAT1"}], "count": 1}


def test_backtest_full_results_route_reads_backend_data_file(tmp_path, monkeypatch):
    monkeypatch.setattr(backtest_results_router, "get_active_backtester", lambda: None)
    payload_path = tmp_path / "backtest_full_results.json"
    payload_path.write_text(json.dumps({"strategies": [{"strategyId": "DISK1"}], "count": 1}), encoding="utf-8")
    monkeypatch.setattr(backtest_results_router, "_get_backend_data_path", lambda filename: payload_path)

    client = TestClient(_build_router_app(backtest_results_router))
    response = client.get("/api/backtest/full-results")

    assert response.status_code == 200
    assert response.json() == {"strategies": [{"strategyId": "DISK1"}], "count": 1}


def test_backtest_results_route_reads_backend_csv_and_grades_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(backtest_results_router, "_get_backend_root_path", lambda filename: tmp_path / filename)
    csv_path = tmp_path / "backtest_results.csv"
    csv_path.write_text(
        "strategy_name,total_return,annual_return,sharpe_ratio,sortino_ratio,max_drawdown,win_rate,profit_factor,total_trades\nMomentum,12.5,10.2,1.8,2.0,8.5,58,1.7,42\n",
        encoding="utf-8",
    )

    client = TestClient(_build_router_app(backtest_results_router))
    response = client.get("/api/backtest/results")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["source"] == "backtest_results.csv"
    assert body["strategies"][0]["name"] == "Momentum"
    assert body["strategies"][0]["grade"] == "A"
    assert body["strategies"][0]["passes"] is True


def test_backtest_per_symbol_route_filters_results(monkeypatch):
    monkeypatch.setattr(
        backtest_results_router,
        "get_active_backtester",
        lambda: SimpleNamespace(
            results=[
                {"strategyName": "Momentum", "strategyId": "MOM1", "symbol": "INFY"},
                {"strategyName": "Momentum", "strategyId": "MOM1", "symbol": "RELIANCE"},
                {"strategyName": "MeanRev", "strategyId": "MR1", "symbol": "INFY"},
            ]
        ),
    )

    client = TestClient(_build_router_app(backtest_results_router))
    response = client.get("/api/backtest/per-symbol?strategy=MOM1&symbol=RELIANCE")

    assert response.status_code == 200
    assert response.json() == {
        "results": [{"strategyName": "Momentum", "strategyId": "MOM1", "symbol": "RELIANCE"}],
        "count": 1,
    }


def test_backtest_advanced_analysis_route_runs_single_strategy_analysis(monkeypatch):
    monkeypatch.setattr(
        backtest_results_router,
        "get_active_backtester",
        lambda: SimpleNamespace(
            portfolio_results={"strategies": [{"name": "Momentum", "strategyId": "MOM1"}]},
            results=[{"strategyName": "Momentum", "symbol": "INFY"}],
            capital=1500000,
        ),
    )
    monkeypatch.setattr(
        backtest_results_router,
        "run_strategy_analysis",
        lambda strategy, per_symbol, capital: {
            "strategyName": strategy["name"],
            "rows": len(per_symbol),
            "capital": capital,
        },
    )

    client = TestClient(_build_router_app(backtest_results_router))
    response = client.get("/api/backtest/advanced-analysis?strategy=MOM1")

    assert response.status_code == 200
    assert response.json() == {
        "results": [{"strategyName": "Momentum", "rows": 1, "capital": 1500000}],
        "count": 1,
    }


def test_backtest_monte_carlo_route_runs_simulator_and_strips_equity_curves(monkeypatch):
    @dataclass
    class FakeMonteCarloResult:
        n_simulations: int = 500
        n_trades_per_sim: int = 25
        method: str = "block"
        initial_capital: float = 1000000.0
        terminal_wealth_mean: float = 1100000.0
        terminal_wealth_median: float = 1080000.0
        terminal_wealth_p5: float = 900000.0
        terminal_wealth_p25: float = 980000.0
        terminal_wealth_p75: float = 1150000.0
        terminal_wealth_p95: float = 1250000.0
        cagr_mean: float = 0.12
        cagr_median: float = 0.1
        cagr_p5: float = -0.03
        cagr_p95: float = 0.22
        max_drawdown_mean: float = 0.11
        max_drawdown_median: float = 0.09
        max_drawdown_p95: float = 0.22
        probability_of_ruin: float = 0.04
        ruin_threshold: float = 0.30
        sharpe_mean: float = 1.1
        sharpe_median: float = 1.0
        sharpe_p5: float = 0.2
        sharpe_p95: float = 1.8
        win_rate: float = 0.56
        profit_factor: float = 1.7
        equity_curves: list[list[float]] | None = None

    run_mock = Mock(return_value=FakeMonteCarloResult(equity_curves=[[1000000.0, 1010000.0]]))
    monkeypatch.setattr(backtest_results_router.monte_carlo_simulator, "run", run_mock)

    client = TestClient(_build_router_app(backtest_results_router))
    response = client.post(
        "/api/backtest/monte-carlo/run",
        json={
            "trade_returns": [0.02, -0.01, 0.015, 0.008, -0.005, 0.012, -0.003, 0.025, -0.008, 0.019],
            "n_simulations": 500,
            "n_trades_per_sim": 25,
            "initial_capital": 1000000,
            "method": "block",
            "block_size": 3,
            "ruin_threshold": 0.30,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "result": {
            "n_simulations": 500,
            "n_trades_per_sim": 25,
            "method": "block",
            "initial_capital": 1000000.0,
            "terminal_wealth_mean": 1100000.0,
            "terminal_wealth_median": 1080000.0,
            "terminal_wealth_p5": 900000.0,
            "terminal_wealth_p25": 980000.0,
            "terminal_wealth_p75": 1150000.0,
            "terminal_wealth_p95": 1250000.0,
            "cagr_mean": 0.12,
            "cagr_median": 0.1,
            "cagr_p5": -0.03,
            "cagr_p95": 0.22,
            "max_drawdown_mean": 0.11,
            "max_drawdown_median": 0.09,
            "max_drawdown_p95": 0.22,
            "probability_of_ruin": 0.04,
            "ruin_threshold": 0.30,
            "sharpe_mean": 1.1,
            "sharpe_median": 1.0,
            "sharpe_p5": 0.2,
            "sharpe_p95": 1.8,
            "win_rate": 0.56,
            "profit_factor": 1.7,
        },
    }
    run_mock.assert_called_once()


def test_backtest_sensitivity_1d_route_returns_current_stub_contract():
    client = TestClient(_build_router_app(backtest_results_router))
    response = client.post("/api/backtest/sensitivity-1d", json={"strategy": "Momentum"})

    assert response.status_code == 200
    assert response.json() == {
        "status": "not_implemented_yet",
        "note": "Requires strategy class registration — use after backtest engine upgrade",
    }


def test_backtest_sensitivity_2d_route_returns_current_stub_contract():
    client = TestClient(_build_router_app(backtest_results_router))
    response = client.post("/api/backtest/sensitivity-2d", json={"strategy": "Momentum"})

    assert response.status_code == 200
    assert response.json() == {
        "status": "not_implemented_yet",
        "note": "Requires strategy class registration — use after backtest engine upgrade",
    }


def test_strategy_builder_parse_route_cleans_fences_and_records_vertex_usage(monkeypatch):
    config = {
        "mode": "equity",
        "symbol": "NIFTY",
        "strategy_name": "RSI Dip",
        "entry_conditions": [{"type": "RSI", "period": 14, "condition": "LT", "value": 30}],
        "exit_conditions": [{"type": "RSI", "period": 14, "condition": "GT", "value": 70}],
        "stop_loss_pct": 0.02,
        "take_profit_pct": 0.04,
    }
    raw_config = json.dumps(config)
    fake_ai_router = SimpleNamespace(
        generate=AsyncMock(
            return_value=SimpleNamespace(
                text=f"```json\n{raw_config}\n```",
                provider="vertex-gemini",
                model="fake-model",
            )
        )
    )
    fake_cost_tracker = SimpleNamespace(record_usage=AsyncMock())
    monkeypatch.setattr("src.services.ai_router.ai_router", fake_ai_router)
    monkeypatch.setattr("src.services.ai_cost_tracker.ai_cost_tracker", fake_cost_tracker)

    client = TestClient(_build_router_app(strategy_builder_router))
    response = client.post(
        "/api/strategy-builder/parse",
        json={"description": "Buy NIFTY when RSI below 30", "mode": "equity"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "config": config,
        "raw": raw_config,
        "model": "fake-model",
    }
    fake_ai_router.generate.assert_awaited_once()
    fake_cost_tracker.record_usage.assert_awaited_once()


def test_strategy_builder_parse_route_passes_pattern_support_in_system_prompt(monkeypatch):
    fake_ai_router = SimpleNamespace(
        generate=AsyncMock(
            return_value=SimpleNamespace(
                text=json.dumps(
                    {
                        "mode": "equity",
                        "symbol": "RELIANCE",
                        "strategy_name": "Pattern Builder",
                        "entry_conditions": [
                            {
                                "type": "CANDLESTICK_PATTERN",
                                "condition": "BULLISH_CONFIRMED",
                                "value": "bullish_engulfing",
                            }
                        ],
                        "exit_conditions": [],
                        "stop_loss_pct": 0.02,
                        "take_profit_pct": 0.04,
                    }
                ),
                provider="vertex-gemini",
                model="fake-model",
            )
        )
    )
    fake_cost_tracker = SimpleNamespace(record_usage=AsyncMock())
    monkeypatch.setattr("src.services.ai_router.ai_router", fake_ai_router)
    monkeypatch.setattr("src.services.ai_cost_tracker.ai_cost_tracker", fake_cost_tracker)

    client = TestClient(_build_router_app(strategy_builder_router))
    response = client.post(
        "/api/strategy-builder/parse",
        json={"description": "Buy RELIANCE on a confirmed bullish engulfing", "mode": "equity"},
    )

    assert response.status_code == 200
    system_prompt = fake_ai_router.generate.await_args.kwargs["system"]
    assert "CANDLESTICK_PATTERN" in system_prompt
    assert "CHART_PATTERN" in system_prompt
    assert "BULLISH_CONFIRMED" in system_prompt
    assert "BEARISH_CONFIRMED" in system_prompt
    assert "confirmed head-and-shoulders reversal" in system_prompt
    assert "symmetrical or directional triangle breakout" in system_prompt
    assert "triple-top/bottom breakout" in system_prompt
    assert "bullish/bearish flag or pennant continuation" in system_prompt
    assert "wedge breakout" in system_prompt


def test_strategy_builder_validate_route_returns_expected_errors():
    client = TestClient(_build_router_app(strategy_builder_router))
    response = client.post(
        "/api/strategy-builder/validate",
        json={"config": {"mode": "crypto", "entry_conditions": []}},
    )

    assert response.status_code == 200
    assert response.json() == {
        "valid": False,
        "errors": [
            "Invalid mode 'crypto'. Must be 'equity' or 'options'.",
            "At least one entry_condition is required.",
        ],
        "config": {"mode": "crypto", "entry_conditions": []},
    }


def test_strategy_builder_validate_route_accepts_pattern_conditions():
    client = TestClient(_build_router_app(strategy_builder_router))
    config = {
        "mode": "equity",
        "symbol": "RELIANCE",
        "direction": "SELL",
        "entry_conditions": [
            {
                "type": "CANDLESTICK_PATTERN",
                "condition": "BULLISH_CONFIRMED",
                "value": "bullish_engulfing",
            },
            {
                "type": "CHART_PATTERN",
                "condition": "BEARISH_CONFIRMED",
                "value": "bearish_flag",
            },
        ],
        "exit_conditions": [],
    }

    response = client.post("/api/strategy-builder/validate", json={"config": config})

    assert response.status_code == 200
    assert response.json() == {"valid": True, "errors": [], "config": config}


def test_strategy_builder_validate_route_rejects_unknown_equity_direction():
    client = TestClient(_build_router_app(strategy_builder_router))
    config = {
        "mode": "equity",
        "symbol": "RELIANCE",
        "direction": "HOLD",
        "entry_conditions": [{"type": "RSI", "condition": "LT", "value": 30}],
    }

    response = client.post("/api/strategy-builder/validate", json={"config": config})

    assert response.status_code == 200
    assert response.json() == {
        "valid": False,
        "errors": ["Invalid direction 'HOLD'. Must be 'BUY' or 'SELL'."],
        "config": config,
    }


def test_strategy_builder_backtest_route_returns_summary_for_recent_bars(monkeypatch):
    import pandas as pd

    class FakeStrategy:
        def __init__(self, config):
            self.config = config

        async def generate_signal(self, window, _regime):
            if len(window) == 53:
                return SimpleNamespace(entry_price=100.0, stop_loss=95.0, target_price=105.0)
            return None

    df = pd.DataFrame(
        {
            "Low": [99.0] * 55,
            "High": [106.0] * 55,
            "Close": [101.0] * 55,
        }
    )
    fake_yfinance = SimpleNamespace(download=Mock(return_value=df))
    monkeypatch.setattr("src.strategies.universal_strategy.UniversalStrategy", FakeStrategy)
    monkeypatch.setitem(sys.modules, "yfinance", fake_yfinance)

    client = TestClient(_build_router_app(strategy_builder_router))
    response = client.post(
        "/api/strategy-builder/backtest",
        json={
            "config": {"mode": "equity", "entry_conditions": [{"type": "RSI", "condition": "LT", "value": 30}]},
            "symbol": "NIFTY",
            "bars": 3,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "results": {
            "total_trades": 1,
            "wins": 1,
            "losses": 0,
            "win_rate": 100.0,
            "total_pnl": 5.0,
            "bars_tested": 3,
            "symbol": "NIFTY",
        },
    }
    fake_yfinance.download.assert_called_once_with("NIFTY.NS", period="6mo", interval="1d", progress=False)


def test_strategy_builder_deploy_route_prefixes_id_and_persists_status(monkeypatch):
    fake_cache = FakeCache()
    monkeypatch.setattr(strategy_builder_router, "cache", fake_cache)

    client = TestClient(_build_router_app(strategy_builder_router))
    response = client.post(
        "/api/strategy-builder/deploy",
        json={
            "config": {"strategy_name": "Universal Equity Builder"},
            "strategy_id": "01_UNIVERSAL_EQ",
            "enabled": True,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "strategy_id": "AIBLD_01_UNIVERSAL_EQ",
        "enabled": True,
        "message": "Strategy AIBLD_01_UNIVERSAL_EQ deployed successfully.",
    }
    assert json.loads(fake_cache.store["strategy_builder:AIBLD_01_UNIVERSAL_EQ"]) == {
        "strategy_name": "Universal Equity Builder"
    }
    status_payload = json.loads(fake_cache.store["strategy_builder:status:AIBLD_01_UNIVERSAL_EQ"])
    assert status_payload["enabled"] is True
    assert status_payload["config_key"] == "strategy_builder:AIBLD_01_UNIVERSAL_EQ"
    assert status_payload["strategy_name"] == "Universal Equity Builder"
    assert status_payload["deployed_at"]


def test_strategy_grades_route_returns_reports_and_caches_results(monkeypatch):
    fake_cache = FakeCache()
    monkeypatch.setattr(strategy_grades_router, "cache", fake_cache)
    monkeypatch.setattr(strategy_grades_router.db, "pool", None)
    monkeypatch.setattr(
        strategy_grades_router,
        "_load_grade_inputs",
        lambda: ([{"name": "Momentum", "strategyId": "MOM1"}], [{"strategyName": "Momentum"}], 1500000),
    )
    monkeypatch.setattr(
        strategy_grades_router,
        "run_all_strategies_analysis",
        lambda strategies, per_symbol, capital: [{"strategyName": "Momentum", "score": 8.2}],
    )

    class FakeGrader:
        def grade_all(self, strategies, advanced_map, paper_map, live_map):
            return [{"strategyName": "Momentum", "grade": "A", "compositeScore": 82}]

    monkeypatch.setattr(strategy_grades_router, "StrategyGrader", lambda: FakeGrader())

    client = TestClient(_build_router_app(strategy_grades_router))
    response = client.get("/api/strategies/grades")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["strategies"] == [{"strategyName": "Momentum", "grade": "A", "compositeScore": 82}]
    assert "strategy_grades_cache" in fake_cache.store


def test_strategy_grades_commentary_route_uses_cached_grades_and_post_filter(monkeypatch):
    fake_cache = FakeCache()
    fake_cache.store["strategy_grades_cache"] = json.dumps(
        {
            "strategies": [
                {
                    "strategyName": "Momentum",
                    "strategyId": "MOM1",
                    "grade": "A",
                    "compositeScore": 82,
                    "phase": "paper",
                    "tiers": [{"tier": "T3", "score": 20, "maxScore": 25}],
                    "sharpe": 1.8,
                    "winRate": 58,
                    "paperTradingDays": 40,
                }
            ]
        }
    )
    monkeypatch.setattr(strategy_grades_router, "cache", fake_cache)
    monkeypatch.setattr(
        "src.services.ai_router.ai_router",
        SimpleNamespace(
            generate=AsyncMock(
                return_value=SimpleNamespace(
                    text='[{"name":"Momentum","commentary":"Solid paper performance.","weakestTier":"T3","improvementAction":"Add live trading days."}]',
                    provider="local",
                    model="fake-model",
                )
            )
        ),
    )

    client = TestClient(_build_router_app(strategy_grades_router))
    response = client.post("/api/strategies/grades/commentary", json={"strategy_id": "MOM1"})

    assert response.status_code == 200
    assert response.json() == {
        "commentary": [
            {
                "name": "Momentum",
                "commentary": "Solid paper performance.",
                "weakestTier": "T3",
                "improvementAction": "Add live trading days.",
            }
        ],
        "count": 1,
        "model": "fake-model",
    }


def test_strategy_performance_history_route_returns_db_rows(monkeypatch):
    rows = [
        {
            "trade_date": "2026-04-22",
            "day_pnl": 150.0,
            "cumulative_pnl": 1150.0,
            "equity": 100150.0,
            "trades_today": 3,
            "winning_trades": 2,
            "losing_trades": 1,
            "drawdown_pct": 1.2,
        },
        {
            "trade_date": "2026-04-23",
            "day_pnl": 175.0,
            "cumulative_pnl": 1325.0,
            "equity": 100325.0,
            "trades_today": 4,
            "winning_trades": 3,
            "losing_trades": 1,
            "drawdown_pct": 0.8,
        },
    ]

    class FakeConn:
        async def fetch(self, query, *params):
            return rows

    class FakeAcquire:
        async def __aenter__(self):
            return FakeConn()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakePool:
        def acquire(self):
            return FakeAcquire()

    monkeypatch.setattr(strategy_grades_router.db, "pool", FakePool())

    client = TestClient(_build_router_app(strategy_grades_router))
    response = client.get("/api/strategies/performance-history?strategy_id=MOM1&mode=PAPER&days=90")

    assert response.status_code == 200
    assert response.json() == {
        "history": [
            {
                "date": "2026-04-23",
                "dayPnl": 175.0,
                "cumulativePnl": 1325.0,
                "equity": 100325.0,
                "trades": 4,
                "wins": 3,
                "losses": 1,
                "drawdownPct": 0.8,
            },
            {
                "date": "2026-04-22",
                "dayPnl": 150.0,
                "cumulativePnl": 1150.0,
                "equity": 100150.0,
                "trades": 3,
                "wins": 2,
                "losses": 1,
                "drawdownPct": 1.2,
            },
        ],
        "count": 2,
        "mode": "PAPER",
    }


def test_strategy_record_daily_route_persists_snapshot(monkeypatch):
    execute_calls = []

    class FakeConn:
        async def execute(self, query, *params):
            execute_calls.append((query, params))

    class FakeAcquire:
        async def __aenter__(self):
            return FakeConn()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakePool:
        def acquire(self):
            return FakeAcquire()

    monkeypatch.setattr(strategy_grades_router.db, "pool", FakePool())

    client = TestClient(_build_router_app(strategy_grades_router))
    response = client.post(
        "/api/strategies/record-daily",
        json={
            "strategy_id": "MOM1",
            "strategy_name": "Momentum",
            "mode": "PAPER",
            "day_pnl": 125.0,
            "trades_today": 3,
            "winning_trades": 2,
            "losing_trades": 1,
            "equity": 100125.0,
        },
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "recorded": "Momentum", "mode": "PAPER"}
    assert len(execute_calls) == 2
    assert execute_calls[0][1] == ("MOM1", "Momentum", "PAPER", 125.0, 3, 2, 1, 100125.0)
    assert execute_calls[1][1] == ("MOM1", "PAPER")


def test_strategy_record_eod_route_uses_runtime_portfolio_and_refreshes_grades(monkeypatch):
    execute_calls = []

    class FakeConn:
        async def execute(self, query, *params):
            execute_calls.append((query, params))

    class FakeAcquire:
        async def __aenter__(self):
            return FakeConn()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakePool:
        def acquire(self):
            return FakeAcquire()

    fake_portfolio_agent = SimpleNamespace(
        simulated_positions={
            "pos-1": {
                "status": "OPEN",
                "strategy_name": "Momentum",
                "realized_pnl": 200.0,
                "unrealized_pnl": 50.0,
            }
        },
        balance=100000.0,
        total_realized_pnl=200.0,
        total_unrealized_pnl=50.0,
    )
    fake_agent_manager = SimpleNamespace(agents={"portfolio": fake_portfolio_agent})
    refresh_mock = AsyncMock(return_value={"strategies": [{"strategyName": "Momentum"}]})
    monkeypatch.setattr(strategy_grades_router.db, "pool", FakePool())
    monkeypatch.setattr(
        strategy_grades_router,
        "get_runtime_value",
        lambda key, default=None: fake_agent_manager if key == "agent_manager" else default,
    )
    monkeypatch.setattr(strategy_grades_router.settings, "MODE", "PAPER", raising=False)
    monkeypatch.setattr(strategy_grades_router, "strategy_grades_api", refresh_mock)

    client = TestClient(_build_router_app(strategy_grades_router))
    response = client.post("/api/strategies/record-eod?date=2026-04-23")

    assert response.status_code == 200
    assert response.json() == {"ok": True, "recorded": 1, "equity": 100250.0}
    assert len(execute_calls) == 2
    assert execute_calls[0][1][0] == "momentum"
    assert execute_calls[0][1][1] == "Momentum"
    assert execute_calls[0][1][2] == "2026-04-23"
    assert execute_calls[0][1][3] == "PAPER"
    assert execute_calls[0][1][4] == 250.0
    assert execute_calls[0][1][8] == 100250.0
    refresh_mock.assert_awaited_once_with()


def test_backtest_interpret_route_returns_error_without_backtest_results(monkeypatch, tmp_path):
    monkeypatch.setattr(backtest_interpret_router, "get_active_backtester", lambda: None)
    monkeypatch.setattr(backtest_interpret_router, "_get_backend_data_path", lambda filename: tmp_path / filename)

    client = TestClient(_build_router_app(backtest_interpret_router))
    response = client.get("/api/backtest/interpret")

    assert response.status_code == 200
    assert response.json() == {"interpretation": None, "error": "No backtest results available."}


def test_backtest_interpret_route_returns_ai_interpretations_from_backend_data(monkeypatch, tmp_path):
    monkeypatch.setattr(backtest_interpret_router, "get_active_backtester", lambda: None)
    payload_path = tmp_path / "backtest_full_results.json"
    payload_path.write_text(
        json.dumps(
            {
                "strategies": [{"name": "Momentum", "strategyId": "MOM1", "sharpe": 1.7, "win_rate": 56}],
                "capital": 1200000,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(backtest_interpret_router, "_get_backend_data_path", lambda filename: payload_path)
    monkeypatch.setattr(
        "src.services.ai_router.ai_router",
        SimpleNamespace(
            generate=AsyncMock(
                return_value=SimpleNamespace(
                    text='[{"name":"Momentum","strengths":["Consistent sharpe"],"weaknesses":["Limited sample"],"bestRegime":"BULL","riskRating":"MEDIUM","recommendation":"deploy carefully"}]',
                    provider="local",
                    model="fake-model",
                )
            )
        ),
    )

    client = TestClient(_build_router_app(backtest_interpret_router))
    response = client.get("/api/backtest/interpret?strategy=MOM1")

    assert response.status_code == 200
    assert response.json() == {
        "interpretations": [
            {
                "name": "Momentum",
                "strengths": ["Consistent sharpe"],
                "weaknesses": ["Limited sample"],
                "bestRegime": "BULL",
                "riskRating": "MEDIUM",
                "recommendation": "deploy carefully",
            }
        ],
        "count": 1,
        "model": "fake-model",
    }


def test_get_pending_approvals_route_returns_active_entries(monkeypatch):
    fake_cache = FakeCache()
    timestamp = (datetime.now() - timedelta(seconds=5)).isoformat()
    fake_cache.store["pending_approvals"] = json.dumps([{"id": "req-1"}])
    fake_cache.store["approval_request:req-1"] = json.dumps(
        {
            "timestamp": timestamp,
            "signal": {"symbol": "NIFTY", "signal_type": "BUY"},
            "justification": "Strong breakout",
            "expiresAt": "soon",
        }
    )
    monkeypatch.setattr(trading_approvals_router, "cache", fake_cache)

    client = TestClient(_build_router_app(trading_approvals_router))
    response = client.get("/api/trading/approvals")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["approvals"][0]["id"] == "req-1"
    assert body["approvals"][0]["status"] == "PENDING"


def test_approve_trade_route_places_order_and_clears_cache(monkeypatch):
    fake_cache = FakeCache()
    fake_cache.store["approval_request:req-1"] = json.dumps(
        {
            "signal": {"symbol": "NIFTY", "signal_type": "BUY"},
            "decision": {"qty": 50},
        }
    )
    fake_cache.store["pending_approvals"] = json.dumps([{"id": "req-1"}, {"id": "req-2"}])
    fake_exec_agent = SimpleNamespace(_place_market_order=AsyncMock())
    fake_agent_manager = SimpleNamespace(agents={"execution": fake_exec_agent})
    monkeypatch.setattr(trading_approvals_router, "cache", fake_cache)
    monkeypatch.setattr(
        trading_approvals_router,
        "get_runtime_value",
        lambda key, default=None: fake_agent_manager if key == "agent_manager" else default,
    )

    client = TestClient(_build_router_app(trading_approvals_router))
    response = client.post("/api/trading/approvals/req-1/approve")

    assert response.status_code == 200
    assert response.json()["approved"] is True
    fake_exec_agent._place_market_order.assert_awaited_once_with(
        {"symbol": "NIFTY", "signal_type": "BUY"},
        {"qty": 50},
    )
    assert "approval_request:req-1" not in fake_cache.store
    assert json.loads(fake_cache.store["pending_approvals"]) == [{"id": "req-2"}]


def test_system_diagnostics_initialize_loads_persisted_threshold_overrides(monkeypatch):
    fake_cache = FakeCache()
    fake_cache.store["diagnostics_thresholds"] = json.dumps({
        "portfolio_heat_max": 0.22,
        "cycle_duration_warn_ms": 45000,
        "unknown_threshold": 123,
    })
    monkeypatch.setattr(system_diagnostics_module, "cache", fake_cache, raising=False)
    monkeypatch.setattr("src.database.redis.cache", fake_cache)

    engine = system_diagnostics_module.SystemDiagnosticsEngine()
    asyncio.run(engine.initialize())

    assert engine.thresholds["portfolio_heat_max"] == 0.22
    assert engine.thresholds["cycle_duration_warn_ms"] == 45000
    assert "unknown_threshold" not in engine.thresholds


def test_redis_event_bus_subscribe_after_connect_registers_channel_once():
    class FakePubSub:
        def __init__(self):
            self.channels = []

        async def subscribe(self, event_type):
            self.channels.append(event_type)

        async def listen(self):
            if False:
                yield {}

    async def _callback(_data):
        return None

    bus = event_bus_redis_module.RedisEventBus()
    bus.is_connected = True
    bus.pubsub = FakePubSub()

    async def _exercise():
        bus.subscribe("SIGNALS_GENERATED", _callback)
        bus.subscribe("SIGNALS_GENERATED", _callback)
        if bus._subscription_tasks:
            await asyncio.gather(*list(bus._subscription_tasks))

    asyncio.run(_exercise())

    assert bus.pubsub.channels == ["SIGNALS_GENERATED"]
    assert bus._subscribed_channels == {"SIGNALS_GENERATED"}


def test_base_agent_publish_event_uses_live_event_bus_resolver(monkeypatch):
    class DummyAgent(base_agent_module.BaseAgent):
        pass

    fake_bus = SimpleNamespace(publish=AsyncMock())
    monkeypatch.setattr(base_agent_module, "get_event_bus", lambda: fake_bus)

    agent = DummyAgent("dummy-agent")

    asyncio.run(agent.publish_event("TEST_EVENT", {"status": "ok"}))

    fake_bus.publish.assert_awaited_once_with("TEST_EVENT", {"status": "ok"})


def test_system_diagnostics_persist_report_uses_live_event_bus_resolver(monkeypatch):
    fake_cache = FakeCache()
    stale_bus = SimpleNamespace(publish=AsyncMock())
    live_bus = SimpleNamespace(publish=AsyncMock())
    fake_agent_manager = SimpleNamespace(
        event_bus=stale_bus,
        _emit_realtime_update=AsyncMock(),
    )
    report = system_diagnostics_module.DiagnosticReport(
        cycle_id="cycle-1",
        timestamp="2026-04-23T12:00:00",
        findings=[
            system_diagnostics_module.DiagnosticFinding(
                id="finding-1",
                severity="CRITICAL",
                category="D1",
                title="Heat breach",
                description="Portfolio heat exceeded threshold",
            )
        ],
        critical_count=1,
    )

    monkeypatch.setattr("src.database.redis.cache", fake_cache)
    monkeypatch.setattr(system_diagnostics_module, "get_event_bus", lambda: live_bus)

    engine = system_diagnostics_module.SystemDiagnosticsEngine()

    asyncio.run(engine._persist_report(report, fake_agent_manager))

    stale_bus.publish.assert_not_called()
    live_bus.publish.assert_awaited_once_with(
        "DIAGNOSTIC_ALERT",
        {
            "severity": "CRITICAL",
            "findings_count": 1,
            "critical_count": 1,
            "warning_count": 0,
            "auto_fixes": 0,
            "top_finding": "Heat breach",
            "timestamp": "2026-04-23T12:00:00",
        },
    )
    fake_agent_manager._emit_realtime_update.assert_awaited_once()


def test_position_monitor_publish_exit_event_uses_live_event_bus_resolver(monkeypatch):
    stale_bus = SimpleNamespace(publish=AsyncMock())
    live_bus = SimpleNamespace(publish=AsyncMock())

    monkeypatch.setattr(event_bus_module.EventBus, "_instance", stale_bus, raising=False)
    monkeypatch.setattr(event_bus_module, "get_event_bus", lambda: live_bus)

    asyncio.run(
        position_monitor_module.PositionMonitor._publish_exit_event(
            symbol="NIFTY",
            reason="TARGET_HIT",
            entry_price=100.0,
            exit_price=110.0,
            quantity=50,
            order_id="order-1",
        )
    )

    stale_bus.publish.assert_not_called()
    live_bus.publish.assert_awaited_once_with(
        "POSITION_EXITED",
        {
            "symbol": "NIFTY",
            "reason": "TARGET_HIT",
            "entry_price": 100.0,
            "exit_price": 110.0,
            "quantity": 50,
            "order_id": "order-1",
        },
    )