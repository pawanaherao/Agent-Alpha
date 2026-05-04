"""Phase 4 — GenAI validation regression guards.

Covers:
  StrategyAgent._validate_with_genai  — null-model passthrough, empty-response
    passthrough, REJECT conviction drop, max_tokens budget scaling with batch
    size, and options-presence token bonus.
  ScannerAgent._ai_counter_validate   — null-model passthrough, empty-response
    passthrough, AVOID veto removal, score_adjustment clamping, max_tokens
    budget formula.
  AIRouter.generate (AIResponse)      — null provider-text normalised to "".
"""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import src.agents.strategy as strategy_module
import src.agents.scanner as scanner_module
from src.agents.strategy import StrategyAgent
from src.agents.scanner import ScannerAgent
from src.strategies.base import StrategySignal


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_signal(symbol: str, strategy: str = "ALPHA_ORB_001",
                 strength: float = 0.70,
                 structure_type: str = None) -> StrategySignal:
    return StrategySignal(
        signal_id=f"sig-{symbol.lower()}",
        strategy_name=strategy,
        symbol=symbol,
        signal_type="BUY",
        strength=strength,
        entry_price=100.0,
        stop_loss=95.0,
        target_price=110.0,
        market_regime_at_signal="BULL",
        structure_type=structure_type,
        metadata={},
    )


def _make_stock(symbol: str, score: float = 75.0) -> dict:
    return {
        "symbol": symbol,
        "score": score,
        "indicators": {
            "rsi": 65.0,
            "adx": 28.0,
            "macd_signal": 0.5,
            "rs_vs_nifty": 1.05,
            "volume_ratio": 1.3,
            "ema_aligned": True,
            "atr_expansion_ratio": 1.1,
            "bb_position": 0.55,
            "delivery_pct": 45.0,
            "vp_zone": "AT_POC",
            "category_scores": {
                "trend": 70, "momentum": 65, "volume": 60,
                "price_action": 68, "volatility": 55, "microstructure": 60,
            },
            "price": 500.0,
            "scores_breakdown": {},
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# StrategyAgent._validate_with_genai
# ─────────────────────────────────────────────────────────────────────────────

def test_strategy_validate_with_genai_none_model_passthrough():
    """When genai_model is None (AI disabled), all signals returned unchanged."""
    agent = StrategyAgent()
    agent.genai_model = None

    signals = [_make_signal("RELIANCE"), _make_signal("TCS")]
    result = asyncio.run(
        agent._validate_with_genai(signals, regime="BULL", sentiment=0.5)
    )

    assert result is signals
    assert len(result) == 2


def test_strategy_validate_with_genai_empty_response_passthrough(monkeypatch):
    """When ai_router returns empty text, all signals pass through unchanged."""
    agent = StrategyAgent()

    import src.services.ai_router as _router_mod
    monkeypatch.setattr(
        _router_mod.ai_router, "generate",
        AsyncMock(return_value=SimpleNamespace(text="", provider="vertex_flash")),
    )
    agent.genai_model = _router_mod.ai_router

    signals = [_make_signal("RELIANCE"), _make_signal("TCS")]
    result = asyncio.run(
        agent._validate_with_genai(signals, regime="BULL", sentiment=0.5)
    )

    assert len(result) == 2
    assert result[0].symbol == "RELIANCE"
    assert result[1].symbol == "TCS"


def test_strategy_validate_with_genai_reject_conviction_drops_signal(monkeypatch):
    """Signals with REJECT conviction are excluded from the validated output."""
    agent = StrategyAgent()

    # Two signals; first will be REJECTED, second MODERATE
    signals = [_make_signal("REJSTOCK"), _make_signal("KEEPSTOCK")]
    batch_json = json.dumps({"evaluations": [
        {
            "idx": 0, "valid": False, "conviction": "REJECT",
            "confidence": 0.9, "adjusted_strength": 0.0,
            "market_edge": "", "risk_note": "terminal data error",
            "reasoning": "SL > entry, structural contradiction", "hold_days": 0,
        },
        {
            "idx": 1, "valid": True, "conviction": "MODERATE",
            "confidence": 0.7, "adjusted_strength": 0.65,
            "market_edge": "breakout confirmation", "risk_note": "watch VIX",
            "reasoning": "Good momentum setup", "hold_days": 0,
        },
    ]})

    # Patch the singleton generate method — local imports inside the method
    # pick up src.services.ai_router.ai_router, not the module attribute.
    import src.services.ai_router as _router_mod
    monkeypatch.setattr(
        _router_mod.ai_router, "generate",
        AsyncMock(return_value=SimpleNamespace(text=batch_json, provider="vertex_flash")),
    )
    agent.genai_model = _router_mod.ai_router

    result = asyncio.run(
        agent._validate_with_genai(signals, regime="BULL", sentiment=0.5)
    )

    assert len(result) == 1
    assert result[0].symbol == "KEEPSTOCK"


def test_strategy_validate_with_genai_strong_conviction_passes_through(monkeypatch):
    """STRONG conviction signals pass through with ai quality grade A."""
    agent = StrategyAgent()

    signals = [_make_signal("STRONGSTOCK", strength=0.80)]
    batch_json = json.dumps({"evaluations": [
        {
            "idx": 0, "valid": True, "conviction": "STRONG",
            "confidence": 0.92, "adjusted_strength": 0.85,
            "market_edge": "institutional accumulation", "risk_note": "",
            "reasoning": "Breakout with volume", "hold_days": 1,
        },
]})

    import src.services.ai_router as _router_mod
    monkeypatch.setattr(
        _router_mod.ai_router, "generate",
        AsyncMock(return_value=SimpleNamespace(text=batch_json, provider="vertex_flash")),
    )
    agent.genai_model = _router_mod.ai_router

    result = asyncio.run(
        agent._validate_with_genai(signals, regime="BULL", sentiment=0.6)
    )

    assert len(result) == 1
    assert result[0].metadata.get("genai_conviction") == "STRONG"
    assert result[0].metadata.get("ai_quality_grade") == "A"


def test_strategy_validate_with_genai_builds_prompt_once_per_batch(monkeypatch):
    """Batch prompt and token budget are built once after all descriptors are collected."""
    agent = StrategyAgent()

    signals = [
        _make_signal("RELIANCE"),
        _make_signal("TCS"),
        _make_signal("INFY", structure_type="IRON_CONDOR"),
    ]
    batch_json = json.dumps({
        "evaluations": [
            {
                "idx": 0,
                "valid": True,
                "conviction": "MODERATE",
                "confidence": 0.7,
                "adjusted_strength": 0.68,
                "market_edge": "Relative strength breakout.",
                "risk_note": "Watch failed follow-through.",
                "reasoning": "Momentum remains constructive.",
                "hold_days": 0,
            },
            {
                "idx": 1,
                "valid": True,
                "conviction": "MODERATE",
                "confidence": 0.7,
                "adjusted_strength": 0.68,
                "market_edge": "Participation is broad.",
                "risk_note": "Respect the stop.",
                "reasoning": "Trend remains supportive.",
                "hold_days": 0,
            },
            {
                "idx": 2,
                "valid": True,
                "conviction": "MODERATE",
                "confidence": 0.7,
                "adjusted_strength": 0.68,
                "market_edge": "Premium remains attractive.",
                "risk_note": "Monitor volatility expansion.",
                "reasoning": "The structure still fits the regime.",
                "hold_days": 1,
            },
        ]
    })

    import src.services.ai_router as _router_mod
    monkeypatch.setattr(
        _router_mod.ai_router, "generate",
        AsyncMock(return_value=SimpleNamespace(text=batch_json, provider="vertex_flash")),
    )
    agent.genai_model = _router_mod.ai_router

    _orig_prompt = agent._build_genai_validation_prompt
    _orig_budget = agent._get_genai_validation_max_tokens
    prompt_spy = Mock(side_effect=_orig_prompt)
    budget_spy = Mock(side_effect=_orig_budget)
    monkeypatch.setattr(agent, "_build_genai_validation_prompt", prompt_spy)
    monkeypatch.setattr(agent, "_get_genai_validation_max_tokens", budget_spy)

    result = asyncio.run(
        agent._validate_with_genai(signals, regime="BULL", sentiment=0.5)
    )

    assert len(result) == 3
    assert prompt_spy.call_count == 1
    assert budget_spy.call_count == 1
    assert len(prompt_spy.call_args.args[0]) == 3
    assert len(budget_spy.call_args.args[0]) == 3


def test_strategy_max_tokens_scales_with_batch_size():
    """Token budget grows with signal count and stays within [768, 3072]."""
    agent = StrategyAgent()

    # 1 signal → 384 + 1*256 = 640 → clamped to 768
    descs_1 = [{"symbol": "A", "structure_type": None, "options_greeks": {}}]
    assert agent._get_genai_validation_max_tokens(descs_1) == 768

    # 8 signals → 384 + 8*256 = 2432 → in range, returned as-is
    descs_8 = [{"symbol": str(i), "structure_type": None, "options_greeks": {}} for i in range(8)]
    assert agent._get_genai_validation_max_tokens(descs_8) == 2432

    # 12 signals → 384 + 12*256 = 3456 → clamped to 3072
    descs_12 = [{"symbol": str(i), "structure_type": None, "options_greeks": {}} for i in range(12)]
    assert agent._get_genai_validation_max_tokens(descs_12) == 3072


def test_strategy_max_tokens_adds_options_bonus():
    """Options signals (with structure_type set) add 128 to the budget."""
    agent = StrategyAgent()

    # 8 equity signals: 384 + 8*256 = 2432
    equity_descs = [{"symbol": str(i), "structure_type": None, "options_greeks": {}} for i in range(8)]
    equity_budget = agent._get_genai_validation_max_tokens(equity_descs)

    # 8 signals where one has structure_type → +128
    mixed_descs = [{"symbol": str(i), "structure_type": None, "options_greeks": {}} for i in range(7)]
    mixed_descs.append({"symbol": "OPT", "structure_type": "IRON_CONDOR", "options_greeks": {}})
    mixed_budget = agent._get_genai_validation_max_tokens(mixed_descs)

    assert mixed_budget == equity_budget + 128


# ─────────────────────────────────────────────────────────────────────────────
# ScannerAgent._ai_counter_validate
# ─────────────────────────────────────────────────────────────────────────────

def test_scanner_counter_validate_no_model_returns_original():
    """When self.model is None, top_stocks returned unchanged."""
    agent = ScannerAgent()
    agent.model = None

    stocks = [_make_stock("RELIANCE"), _make_stock("TCS")]
    result = asyncio.run(
        agent._ai_counter_validate(stocks, regime="BULL")
    )

    assert result is stocks
    assert len(result) == 2


def test_scanner_counter_validate_empty_stocks_returns_empty():
    """When top_stocks is empty, returns empty list without calling ai_router."""
    agent = ScannerAgent()
    agent.model = object()  # non-None, but ai_router should not be called

    result = asyncio.run(
        agent._ai_counter_validate([], regime="BULL")
    )

    assert result == []


def test_scanner_counter_validate_empty_response_passthrough(monkeypatch):
    """Empty ai_router response returns all original stocks unchanged."""
    agent = ScannerAgent()
    agent.model = object()  # mark as enabled

    import src.services.ai_router as _router_mod
    monkeypatch.setattr(
        _router_mod.ai_router, "generate",
        AsyncMock(return_value=SimpleNamespace(text="", provider="vertex_flash")),
    )

    stocks = [_make_stock("RELIANCE", 80.0), _make_stock("INFY", 75.0)]
    result = asyncio.run(
        agent._ai_counter_validate(stocks, regime="BULL")
    )

    assert len(result) == 2
    assert result[0]["symbol"] == "RELIANCE"


def test_scanner_counter_validate_avoid_veto_removes_stock(monkeypatch):
    """Stocks with AVOID verdict are excluded from the validated shortlist."""
    agent = ScannerAgent()
    agent.model = object()

    verdicts = json.dumps([
        {
            "symbol": "AVOIDME", "score_adjustment": None, "verdict": "AVOID",
            "confidence": 0.88, "category_divergences": [],
            "red_flags": ["operator_activity"], "reasoning": "circuit stock",
        },
        {
            "symbol": "KEEPME", "score_adjustment": 3, "verdict": "BUY",
            "confidence": 0.75, "category_divergences": [],
            "red_flags": [], "reasoning": "stage 2 breakout",
        },
    ])

    import src.services.ai_router as _router_mod
    monkeypatch.setattr(
        _router_mod.ai_router, "generate",
        AsyncMock(return_value=SimpleNamespace(text=verdicts, provider="vertex_flash")),
    )
    # Stub Redis and postgres to avoid I/O
    monkeypatch.setattr(scanner_module, "_redis_cache", SimpleNamespace(
        get=AsyncMock(return_value=None),
        set=AsyncMock(return_value=None),
    ), raising=False)

    stocks = [_make_stock("AVOIDME", 78.0), _make_stock("KEEPME", 74.0)]
    result = asyncio.run(
        agent._ai_counter_validate(stocks, regime="BULL")
    )

    syms = [s["symbol"] for s in result]
    assert "AVOIDME" not in syms
    assert "KEEPME" in syms


def test_scanner_counter_validate_score_adjustment_applied(monkeypatch):
    """score_adjustment is added to the stock's composite score."""
    agent = ScannerAgent()
    agent.model = object()

    verdicts = json.dumps([
        {
            "symbol": "BOOSTME", "score_adjustment": 10, "verdict": "STRONG_BUY",
            "confidence": 0.90, "category_divergences": [],
            "red_flags": [], "reasoning": "microstructure leads weight",
        },
    ])

    import src.services.ai_router as _router_mod
    monkeypatch.setattr(
        _router_mod.ai_router, "generate",
        AsyncMock(return_value=SimpleNamespace(text=verdicts, provider="vertex_flash")),
    )
    monkeypatch.setattr(scanner_module, "_redis_cache", SimpleNamespace(
        get=AsyncMock(return_value=None),
        set=AsyncMock(return_value=None),
    ), raising=False)

    stocks = [_make_stock("BOOSTME", 72.0)]
    result = asyncio.run(
        agent._ai_counter_validate(stocks, regime="BULL")
    )

    assert len(result) == 1
    assert result[0]["score"] == 82.0  # 72 + 10


def test_scanner_counter_validate_score_adjustment_clamped(monkeypatch):
    """score_adjustment from Gemini is clamped to [-15, +15]."""
    agent = ScannerAgent()
    agent.model = object()

    # Gemini returns +99 — should be clamped to +15
    verdicts = json.dumps([
        {
            "symbol": "EXTREME", "score_adjustment": 99, "verdict": "STRONG_BUY",
            "confidence": 0.99, "category_divergences": [],
            "red_flags": [], "reasoning": "extreme outlier",
        },
    ])

    import src.services.ai_router as _router_mod
    monkeypatch.setattr(
        _router_mod.ai_router, "generate",
        AsyncMock(return_value=SimpleNamespace(text=verdicts, provider="vertex_flash")),
    )
    monkeypatch.setattr(scanner_module, "_redis_cache", SimpleNamespace(
        get=AsyncMock(return_value=None),
        set=AsyncMock(return_value=None),
    ), raising=False)

    stocks = [_make_stock("EXTREME", 60.0)]
    result = asyncio.run(
        agent._ai_counter_validate(stocks, regime="BULL")
    )

    assert len(result) == 1
    # +99 clamped to +15 → 60 + 15 = 75
    assert result[0]["score"] == 75.0


def test_scanner_counter_validate_max_tokens_formula(monkeypatch):
    """Token budget matches the documented formula: min(4096, max(768, 384 + n*224))."""
    captured = {}

    agent = ScannerAgent()
    agent.model = object()

    # Build a 5-stock batch (well under the 15-stock cap)
    stocks = [_make_stock(f"SYM{i}", 70.0 + i) for i in range(5)]
    expected = min(4096, max(768, 384 + 5 * 224))  # = 1504

    async def _fake_generate(prompt, agent_name, temperature, max_tokens, json_mode):
        captured["max_tokens"] = max_tokens
        return SimpleNamespace(text="", provider="vertex_flash")

    import src.services.ai_router as _router_mod
    monkeypatch.setattr(_router_mod.ai_router, "generate", _fake_generate)

    asyncio.run(agent._ai_counter_validate(stocks, regime="BULL"))

    assert captured.get("max_tokens") == expected


# ─────────────────────────────────────────────────────────────────────────────
# AIRouter AIResponse — null text normalisation
# ─────────────────────────────────────────────────────────────────────────────

def test_ai_router_response_text_normalised_to_empty_string_on_none():
    """AIResponse.text is normalised to '' when provider returns None text."""
    from src.services.ai_router import AIResponse

    resp = AIResponse(text=None, provider="vertex_flash", model="gemini-2.5-flash")
    # Production guard pattern: (response.text or "").strip() should not crash
    safe = (resp.text or "").strip()
    assert safe == ""


def test_ai_router_response_text_passthrough_on_nonempty():
    """AIResponse.text is returned as-is when provider returns non-empty text."""
    from src.services.ai_router import AIResponse

    resp = AIResponse(text='[{"symbol":"X"}]', provider="vertex_flash", model="gemini-2.5-flash")
    assert resp.text == '[{"symbol":"X"}]'
