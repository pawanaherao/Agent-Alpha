# Agentic Alpha — Comprehensive Codebase & Architecture Audit

> **Audit Period:** February 18–23, 2026  
> **Auditors:** AI-assisted code review  
> **Status:** NOT READY FOR PAPER TRADING  
> **Codebase Version:** main branch as of Feb 23, 2026

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Architecture Overview](#2-architecture-overview)
3. [Startup Blockers (Severity 1)](#3-startup-blockers-severity-1)
4. [Missing Dependencies (Severity 2)](#4-missing-dependencies-severity-2)
5. [Agent Orchestration Deep Dive](#5-agent-orchestration-deep-dive)
6. [Agent-by-Agent Audit](#6-agent-by-agent-audit)
7. [Equity Strategy Audit — Intraday](#7-equity-strategy-audit--intraday)
8. [Equity Strategy Audit — Swing](#8-equity-strategy-audit--swing)
9. [Equity Strategy Audit — Wave 2](#9-equity-strategy-audit--wave-2)
10. [Options Strategy Audit — Multi-Leg](#10-options-strategy-audit--multi-leg)
11. [Universal AI Strategy Audit](#11-universal-ai-strategy-audit)
12. [Data Pipeline Audit](#12-data-pipeline-audit)
13. [Broker Integration Audit (Dhan)](#13-broker-integration-audit-dhan)
14. [Risk Management Audit](#14-risk-management-audit)
15. [SEBI Compliance Audit](#15-sebi-compliance-audit)
16. [Backtester Reliability Audit](#16-backtester-reliability-audit)
17. [Test Coverage Audit](#17-test-coverage-audit)
18. [Infrastructure & DevOps Audit](#18-infrastructure--devops-audit)
19. [Bugs & Inconsistencies Registry](#19-bugs--inconsistencies-registry)
20. [Paper Trading Readiness Scorecard](#20-paper-trading-readiness-scorecard)
21. [Recommended Implementation Plan](#21-recommended-implementation-plan)

---

## 1. Executive Summary

Agentic Alpha is a multi-agent AI trading system targeting the Indian equity and options market (NSE/BSE via DhanHQ). It features 35+ strategies, 7 specialized agents, a 3-tier data pipeline, and event-driven orchestration.

**Strengths:**
- Sound multi-agent architecture with clear separation of concerns
- 11 production-quality equity strategies with real technical signal generation
- Proper regime detection (K-Means + rule-based) using live NIFTY data
- Kelly Criterion + VaR risk framework
- 3-tier data redundancy design (DhanHQ → nselib → yfinance)

**Critical Gaps:**
- 5 startup-blocking import errors prevent the app from running
- 6+ missing pip dependencies in requirements.txt
- Options multi-leg execution is not implemented (single-order only)
- No real-time data (DhanHQ Tier 1 is placeholder; yfinance EOD only)
- Empty API layer (no REST endpoints for frontend)
- PortfolioAgent is a stub (no position tracking)
- Paper trading runs once and exits (no continuous loop)
- Test coverage is effectively 0% (no assertions)
- SEBI compliance is documented but not enforced in code

**Verdict:** The system needs 9 categories of fixes before paper trading is viable.

---

## 2. Architecture Overview

### System Components

```
┌─────────────────────────────────────────────────────┐
│                    Frontend (Next.js)                 │
│              localhost:3000 — No API to consume       │
└──────────────────────┬──────────────────────────────┘
                       │ (empty API layer)
┌──────────────────────▼──────────────────────────────┐
│              Backend (FastAPI on port 8000)           │
│  ┌─────────────────────────────────────────────────┐ │
│  │         AgentManager (3-min heartbeat)           │ │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────────┐    │ │
│  │  │Sentiment │ │ Regime   │ │   Scanner    │    │ │
│  │  │  Agent   │ │  Agent   │ │    Agent     │    │ │
│  │  └────┬─────┘ └────┬─────┘ └──────┬───────┘    │ │
│  │       └─────────────┼──────────────┘            │ │
│  │              ┌──────▼───────┐                   │ │
│  │              │  Strategy    │ 35+ Strategies     │ │
│  │              │   Agent      │                   │ │
│  │              └──────┬───────┘                   │ │
│  │              ┌──────▼───────┐                   │ │
│  │              │    Risk      │ Kelly+VaR+VIX     │ │
│  │              │   Agent      │                   │ │
│  │              └──────┬───────┘                   │ │
│  │              ┌──────▼───────┐                   │ │
│  │              │  Execution   │ → DhanHQ           │ │
│  │              │   Agent      │                   │ │
│  │              └──────┬───────┘                   │ │
│  │              ┌──────▼───────┐                   │ │
│  │              │  Portfolio   │ (STUB)             │ │
│  │              │   Agent      │                   │ │
│  │              └──────────────┘                   │ │
│  └─────────────────────────────────────────────────┘ │
│  ┌───────────┐ ┌───────────┐ ┌──────────────────┐   │
│  │ PostgreSQL │ │   Redis   │ │ Firestore (opt)  │   │
│  └───────────┘ └───────────┘ └──────────────────┘   │
└─────────────────────────────────────────────────────┘
```

### Key Files

| Component | Primary File | Status |
|-----------|-------------|--------|
| Main entrypoint | `backend/src/main.py` | Blocked by import errors |
| Dev entrypoint | `backend/main.py` | Socket.IO dev server (port 5000) |
| Orchestration | `backend/src/core/agent_manager.py` | Working logic, blocked by downstream errors |
| Event Bus | `backend/src/core/event_bus.py` | In-memory, sync/async mismatch with Redis variant |
| Strategy Registry | `backend/src/strategies/__init__.py` | Silent import failures possible |
| Strategy Factory | `backend/src/agents/init_agents.py` | 4 missing imports → NameError |
| Config | `backend/src/core/config.py` | Uses pydantic-settings (not in requirements) |
| Data Service | `backend/src/services/nse_data.py` | Tier 3 yfinance only (Tiers 1-2 stub/limited) |
| Broker | `backend/src/services/dhan_client.py` | Simulated mode only |
| DB Schema | `backend/db/init.sql` | Schema mismatches with code |

---

## 3. Startup Blockers (Severity 1)

These errors prevent the application from starting at all.

| # | Error | File | Line | Impact |
|---|-------|------|------|--------|
| S1-1 | `import vertexai` — package not installed | `backend/src/agents/execution.py` | L4-5 | **ImportError** crashes agent system |
| S1-2 | `from google.cloud import firestore` — not installed | `backend/src/database/firestore.py` | L1 | **ImportError** via `src/main.py` L7 |
| S1-3 | `from apscheduler.schedulers.asyncio import AsyncIOScheduler` — not in requirements | `backend/src/main.py` | L3 | **ImportError** on entrypoint |
| S1-4 | `StatisticalArbitrageStrategy`, `VolatilityArbitrageStrategy`, `CrossSectionalMomentumStrategy`, `UniversalStrategy` used without import | `backend/src/agents/init_agents.py` | L108-118 | **NameError** during strategy init |
| S1-5 | `db_firestore` is `None` at import; `lifespan()` calls `.connect()` on it | `backend/src/main.py` → `firestore.py` | L7, L39 | **AttributeError: NoneType** |

---

## 4. Missing Dependencies (Severity 2)

Packages used in code but absent from `backend/requirements.txt`:

| Package | Used In | Purpose |
|---------|---------|---------|
| `apscheduler` | `src/main.py` | 3-minute orchestration scheduler |
| `asyncpg` | `database/postgres.py` | Async PostgreSQL driver |
| `pydantic-settings` | `core/config.py` | Settings management with env vars |
| `google-cloud-firestore` | `database/firestore.py` | GCP Firestore client |
| `google-cloud-aiplatform` | `agents/execution.py`, `sentiment.py`, `scanner.py` | Vertex AI / Gemini |
| `python-socketio` | `backend/main.py` | WebSocket dev server |

---

## 5. Agent Orchestration Deep Dive

### 5.1 Trigger Mechanism

Two triggers fire the orchestration cycle:
1. **Timer:** APScheduler fires `orchestration_loop()` every 3 minutes (`backend/src/main.py` L29-33)
2. **Manual:** `POST /trigger-cycle` endpoint (`backend/src/main.py` L60-63)

### 5.2 The 3-Minute Cycle — Exact Sequence

Defined in `AgentManager.run_cycle()` (`backend/src/core/agent_manager.py` L77-119):

**Phase 1 — SENSING (parallel via asyncio.gather):**
- `SentimentAgent.analyze()` → `float` sentiment_score (-1.0 to +1.0)
- `RegimeAgent.analyze_with_real_data("NIFTY 50")` → `str` regime (BULL/BEAR/SIDEWAYS/VOLATILE)
- `ScannerAgent.scan_universe()` → `List[Dict]` opportunities (top 10 stocks with score > 50)

**Phase 2 — DECISION (sequential):**
- `StrategyAgent.select_and_execute(regime, sentiment, opportunities)`
  - Filters strategies by regime suitability (> 50)
  - Fetches real NSE data per opportunity
  - Runs top 3 strategies × top 10 stocks
  - Optional GenAI validation (Gemini 1.5 Flash)
  - Publishes `SIGNALS_GENERATED` event

**Phase 3 — RISK (event-driven, triggered by SIGNALS_GENERATED):**
- `RiskAgent.on_signals_received(payload)`
  - 7 validation checks per signal (kill switch, heat, correlation, VaR, R:R, Kelly, VIX scaling)
  - Publishes `SIGNALS_APPROVED` for passing signals

**Phase 4 — EXECUTION (event-driven, triggered by SIGNALS_APPROVED):**
- `ExecutionAgent.on_orders_approved(payload)`
  - Routes by mode: AUTO → place order, HYBRID → auto if strength > 0.8, MANUAL → user approval
  - Calls `dhan_client.place_order()` (currently returns simulated IDs)
  - Publishes `ORDER_FILLED` event

**Phase 5 — MONITORING (sequential, back in run_cycle):**
- `PortfolioAgent.update_portfolio()` → stub (hardcoded balance, no tracking)

### 5.3 Event Wiring

| Event | Publisher | Subscriber | Status |
|-------|----------|------------|--------|
| `SIGNALS_GENERATED` | StrategyAgent | RiskAgent.on_signals_received | Wired |
| `SIGNALS_APPROVED` | RiskAgent | ExecutionAgent.on_orders_approved | Wired |
| `ORDER_FILLED` | ExecutionAgent | PortfolioAgent.on_order_filled | Wired |
| `SCAN_COMPLETE` | ScannerAgent | **Nobody** | Orphan |
| `REGIME_UPDATED` | RegimeAgent | **Nobody** | Orphan |
| `SENTIMENT_UPDATED` | SentimentAgent | **Nobody** | Orphan |
| `PORTFOLIO_UPDATED` | PortfolioAgent | **Nobody** | Orphan |

### 5.4 Dynamic Decision Making Assessment

| What | Dynamic? | Detail |
|------|----------|--------|
| Market regime classification | **Yes** | Real NIFTY data + K-Means + ADX/EMA/RSI rules |
| Strategy selection per regime | **Yes** | Suitability scoring + regime weights |
| Stock selection | **Partial** | Real indicators, but universe is 30 hardcoded stocks |
| Position sizing | **Yes** | Kelly + VaR + VIX scaling |
| GenAI validation of signals | **Yes** | Gemini validates signals (optional) |
| Sentiment-based adjustment | **Yes** | Live news fetching + VADER/GenAI scoring |
| Kelly win rate learning | **No** | Static 0.55 forever |
| Strategy parameter tuning | **No** | All thresholds hardcoded |
| Feedback loop from results | **No** | Signal history stored but never read back |
| Social media sentiment | **No** | 2 hardcoded fake headlines |

### 5.5 Error Handling at Orchestration Level

- Entire cycle: `try/except` catches all, logs error, skips cycle. No retry.
- EventBus: Each subscriber callback wrapped in `_safe_execute` — individual failures logged but don't crash the bus.
- **No circuit breaker integration** (module exists in `core/resilience.py` but unused).
- **No dead letter queue** for failed signals.
- **No partial recovery** — if regime detection fails, entire cycle skips.

---

## 6. Agent-by-Agent Audit

### 6.1 SentimentAgent (`backend/src/agents/sentiment.py`, 466 lines)

**Purpose:** Global market sentiment score (-1.0 to +1.0).

**Data Sources:**
1. Google News India RSS (real)
2. NSE corporate announcements API (real)
3. ET Markets + Livemint RSS (real)
4. Social media → **HARDCODED** (2 fake headlines)
5. NIFTY change + VIX → Market indicator fallback

**Analysis Pipeline:** GenAI (Gemini 1.5 Flash) → VADER (fallback) → keyword rules (fallback).

**Issues:**
- Social media source returns 2 hardcoded headlines always
- 3 hardcoded fallback headlines always included in market indicator path
- GenAI initialization can fail silently
- Returns cached `self.global_sentiment` on any error

### 6.2 RegimeAgent (`backend/src/agents/regime.py`, 284 lines)

**Purpose:** Classify market as BULL/BEAR/SIDEWAYS/VOLATILE.

**Classification Logic (ordered priority):**
1. VIX > 25 → VOLATILE (hard override)
2. K-Means cluster analysis (4 clusters by returns + volatility + RSI)
3. ADX > 25 + Price > EMA20 > EMA50 → BULL
4. ADX > 25 + Price < EMA20 < EMA50 → BEAR
5. ADX > 25 but mixed signals → VOLATILE
6. ADX ≤ 25 + RSI > 60 + Price > EMA20 → BULL
7. ADX ≤ 25 + RSI < 40 + Price < EMA20 → BEAR
8. Default → SIDEWAYS

**Regime Strategy Weights:**

| Regime | Momentum | Trend | Mean Reversion | Theta | Hedge |
|--------|----------|-------|----------------|-------|-------|
| BULL | 1.5 | 1.3 | 0.7 | 0.5 | 0.3 |
| BEAR | 0.5 | 0.7 | 1.0 | 0.8 | 1.5 |
| SIDEWAYS | 0.5 | 0.5 | 1.5 | 1.5 | 0.8 |
| VOLATILE | 1.2 | 0.8 | 0.5 | 0.3 | 1.2 |

**Issues:** Falls back to SIDEWAYS on any error. K-Means needs 30+ rows.

### 6.3 ScannerAgent (`backend/src/agents/scanner.py`, 470 lines)

**Purpose:** Screen 30 stocks using 12 technical filters.

**Universe:** 30 hardcoded NSE stocks (banking, IT, energy, FMCG, auto, pharma, finance, metals).

**12 Indicators & Weights:**

| Indicator | Weight | Scoring |
|-----------|--------|---------|
| Volume ratio (20d avg) | 0.15 | min(100, ratio×50) |
| Delivery % (NSE specific) | 0.15 | Institutional conviction proxy |
| MACD | 0.12 | +50 bullish crossover, -50 bearish |
| RSI(14) | 0.10 | Peak at 55 |
| ADX(14) | 0.10 | min(100, ADX×3) |
| OBV | 0.10 | 80 rising above 10-SMA, else 40 |
| EMA alignment (9>21>50) | 0.10 | 90 aligned, 40 otherwise |
| Stochastic(14,3,3) | 0.08 | 80 oversold, 30 overbought, 60 otherwise |
| Parabolic SAR | 0.08 | 85 bullish, 35 bearish |
| Bollinger Bands | 0.07 | Peak at mid-band |
| GenAI score | 0.05 | Gemini 0-100 rating |

**Issues:**
- Returns `List[Dict]` but StrategyAgent iterates it as `List[str]` → **type mismatch bug**
- Rate limited at 0.1s between stock analyses

### 6.4 StrategyAgent (`backend/src/agents/strategy.py`, 372 lines)

**Purpose:** Strategy selection, data fetching, signal generation, GenAI validation.

**select_and_execute Flow:**
1. Filter strategies: `calculate_suitability() × regime_weight > 50`
2. For top 10 opportunities: fetch `get_stock_with_indicators(symbol, "3M")`
3. Calculate Hurst exponent (optional, fails silently)
4. Top 3 strategies × each stock → `generate_signal(market_data, regime)`
5. Enhance metadata (suitability, sentiment, regime, position_weight)
6. Optional GenAI validation
7. Publish `SIGNALS_GENERATED`

**Position Weight Formula:** `(suitability/100 × 0.4) + (sentiment_adj × 0.3) + (strength × 0.3)`, clamped [0.1, 1.0]

**Issues:**
- Fetches `period="3M"` (~63 bars) — insufficient for Pullback strategy (needs 205)
- Polars conversion attempted but result is unused
- Hurst calculation from fast_math may fail in numba nopython mode

### 6.5 RiskAgent (`backend/src/agents/risk.py`, 359 lines)

**Purpose:** 7-check risk validation + Kelly position sizing.

**Checks (in order):**
1. Kill Switch: daily_pnl < -5% capital → REJECT
2. Portfolio Heat: open risk / capital ≥ 25% → REJECT
3. Correlation: max correlation with open > 0.7 → REJECT
4. VaR (95%): VaR > 2% capital → REJECT
5. Risk-Reward: R:R < 1.5 → REJECT
6. Kelly Criterion: `f* = (bp - q) / b × 0.25` quarter-Kelly
7. VIX Scaling: 0.4× (VIX>25) to 1.2× (VIX<12)

**Issues:**
- **Missing imports:** `Dict`, `Any` from typing and `pd` (pandas) → **NameError at runtime**
- `open_positions` is **never populated** — heat/correlation checks always pass
- Kelly win_rate is static 0.55 with no learning
- No per-signal error isolation in batch processing

### 6.6 ExecutionAgent (`backend/src/agents/execution.py`, 154 lines)

**Purpose:** Order placement via DhanHQ.

**Mode Routing:**
- AUTO → always `_place_market_order()`
- HYBRID → auto if `strength > 0.8`, else `_request_user_approval()`
- MANUAL → always `_request_user_approval()`

**Issues:**
- `import vertexai` at module level → **ImportError** (not installed)
- `from src.services.dhan_client import dhan_client` → imports `None`
- `securityId: "1333"` hardcoded for ALL orders
- No symbol-to-security-ID lookup
- User approval path logs but never sends notification (TODO)
- DB insert schema doesn't match `init.sql` table columns

### 6.7 PortfolioAgent (`backend/src/agents/portfolio.py`)

**Purpose:** Portfolio monitoring.

**Status: STUB.** Balance hardcoded to ₹100,000. `positions = {}` never populated. `update_portfolio()` just publishes a static event. `on_order_filled()` logs and calls `update_portfolio()`.

---

## 7. Equity Strategy Audit — Intraday

### 7.1 ORB — Opening Range Breakout

| Attribute | Value |
|-----------|-------|
| **File** | `backend/src/strategies/momentum/orb.py` (451 lines) |
| **ID** | ALPHA_ORB_001 |
| **Type** | Intraday Momentum — NIFTY Index Options |
| **Status** | Signal generation works; execution is single-leg only |

**Entry Conditions (ALL required):**
1. Market open (9:15-15:30, weekdays)
2. Not already traded today
3. Past ORB end time (9:30 AM)
4. Within entry window (10:00 AM - 11:00 AM)
5. Opening range width: 50-200 points
6. Bullish: `current_price > range_high` → BUY
7. Bearish: `current_price < range_low` → SELL
8. VIX ≤ 25

**Opening Range Calculation:** Uses **daily OHLC × 0.3** as proxy for 15-min range (no real intraday data). `range_high = open + estimated_orb/2`, `range_low = open - estimated_orb/2`.

**Exit Logic:**
- SL: opposite range boundary ± 10% of range width
- Target: 2× range width from entry
- Time exit: 3:15 PM (metadata only — NOT enforced)

**Signal Strength:** 0.7 base + 0.1 (trending regime) + 0.1 (VIX 12-20) + 0.1 (>60% breakout beyond center)

**Critical Gaps:**
- No real 15-minute candle data — range is approximated from daily data
- Time exit is not monitored by any agent
- Options strike selection uses NIFTY 50-point increments but execution agent ignores this metadata

### 7.2 VWAP Mean Reversion

| Attribute | Value |
|-----------|-------|
| **File** | `backend/src/strategies/mean_reversion/vwap.py` (243 lines) |
| **ID** | ALPHA_VWAP_002 |
| **Type** | Intraday Mean Reversion — Index Options |
| **Status** | Signal generation works; VWAP calculation is wrong for intraday |

**Entry Conditions (ALL required):**
1. Regime NOT BULL or BEAR
2. Time: 09:45-14:30
3. BUY: deviation < -1.5% from VWAP AND |deviation| < 3% AND RSI < 35
4. SELL: deviation > +1.5% from VWAP AND |deviation| < 3% AND RSI > 65

**VWAP Calculation:** `cumulative(TP × volume) / cumulative(volume)` over the **entire DataFrame** (not reset daily). With daily data, this produces a multi-day weighted average, NOT an intraday VWAP.

**Exit Logic:**
- Target: VWAP level (reversion target)
- SL: 2× deviation distance
- Time exit: 3:15 PM (metadata only — NOT enforced)

**Critical Gaps:**
- VWAP is calculated across 3 months of daily data — not a true intraday VWAP
- No intraday data feed to support this strategy
- Backtest shows Sharpe 10.74+ (suspicious — see Backtester section)

---

## 8. Equity Strategy Audit — Swing

### 8.1 Swing Breakout

| Attribute | Value |
|-----------|-------|
| **File** | `backend/src/strategies/swing/breakout.py` (389 lines) |
| **ID** | ALPHA_BREAKOUT_101 |
| **Type** | Swing Momentum — Equity Cash — 3-7 day hold |
| **Status** | Production-ready signal generation |

**Entry Conditions:**
1. Regime NOT BEAR
2. ≥ 25 rows of data
3. `close > 20-day high` (true breakout)
4. RSI between 50-70
5. Volume and ADX are calculated for strength but **NOT required for entry** (docstring mismatch)

**Exit Logic:** SL = max(20-day low, entry × 0.97), Target = entry × 1.08. Max hold 7 days (not enforced).

**Backtest:** Realistic — Sharpe 1.21 (SBIN), 1.69 (TATASTEEL). Some stocks show 0 trades.

### 8.2 EMA Crossover

| Attribute | Value |
|-----------|-------|
| **File** | `backend/src/strategies/swing/ema_crossover.py` (217 lines) |
| **ID** | ALPHA_EMA_CROSS_104 |
| **Type** | Swing Trend — Equity Cash — 5-15 day hold |
| **Status** | Production-ready signal generation |

**Entry Conditions (ALL required):**
1. ≥ 55 rows
2. EMA(9) crosses above EMA(21) (bullish crossover)
3. Price > EMA(50) (uptrend filter)
4. ADX > 25 (mandatory, fine-tuned from 20)
5. BUY signals only (no SELL on bearish crossover)

**Exit Logic:** SL = entry × 0.95 (5%). Target is **missing** from signal construction. Trail at 21 EMA after +5% (metadata only).

**Backtest:** Realistic — Sharpe 1.46 (SBIN).

### 8.3 Trend Pullback

| Attribute | Value |
|-----------|-------|
| **File** | `backend/src/strategies/swing/pullback.py` (209 lines) |
| **ID** | ALPHA_PULLBACK_102 |
| **Type** | Swing Trend — Equity Cash — 5-10 day hold |
| **Status** | Logic sound but data requirement too high |

**Entry Conditions (ALL required):**
1. Regime NOT BEAR/VOLATILE
2. ≥ 205 rows (needs 200-day EMA) — **strategy agent only fetches 3M (~63 bars)**
3. `price > EMA(50) > EMA(200)` (uptrend)
4. `|price - EMA(20)| / EMA(20) ≤ 1%` (pullback to moving average)
5. RSI between 40-55 (cooled momentum)

**Exit Logic:** SL = max(EMA50 × 0.99, entry × 0.96), Target = entry × 1.10.

**Critical Issue:** Requires 205 bars but StrategyAgent fetches "3M" (~63 bars). The 200-EMA will be mostly NaN, so the uptrend filter will never pass. **This strategy will effectively never fire.**

---

## 9. Equity Strategy Audit — Wave 2

### 9.1 Momentum Rotation (ALPHA_MOMENTUM_201)

**Entry:** Regime NOT BEAR, ≥ 63 rows, RS score > 80 (where RS = 50 + 3M_return × 200).  
**Bug:** RS is absolute, not relative to a benchmark (misleading name).  
**Exit:** SL = price - 2×ATR, Target = price × 1.15.

### 9.2 Sector Rotation (ALPHA_SECTOR_202)

**Entry:** BULL regime only, stock in one of 4 hardcoded sector lists (20 stocks total), 1M return > 5%.  
**Very restrictive** — only fires in BULL for 20 specific stocks.  
**Exit:** SL × 0.95, Target × 1.10.

### 9.3 BB Squeeze (ALPHA_BB_203)

**Entry:** ≥ 25 rows, BB width < 4% for 2 consecutive bars (squeeze), then breakout: |price_change| > 0.5% AND price outside bands.  
**Sound logic.** Exit at opposite band (SL) / ±8% (target).

### 9.4 RSI Divergence (ALPHA_RSI_DIV_204)

**Entry:** ≥ 34 rows, price near 15-day low but RSI > prior RSI + 5 (bullish divergence), volume ≥ 1.5× 20d avg.  
**Fine-tuned:** Lookback 10→15 days, volume 1.3→1.5x.  
**Exit:** SL ±3%, Target ±8%.

### 9.5 Earnings Momentum (ALPHA_EARN_205)

**Entry:** Gap up > 3% + volume > 1.5× average.  
**No actual earnings calendar** — triggers on any large gap-up with volume.  
**Exit:** SL 5%, Target 12%, 7-day hold (not enforced).

### 9.6 Gap Fill (ALPHA_GAP_206)

**Entry:** Gap between 1-2%, bet on gap fill. Gap up → SELL, gap down → BUY.  
**Fine-tuned:** Max gap 3%→2%.  
**Bug:** Volume confirmation documented but not implemented.

### 9.7 ATR Breakout (ALPHA_ATR_207)

**Entry:** Price > prev_close + 1.5×ATR(14) → BUY, or < prev_close - 1.5×ATR → SELL.  
**Exit:** SL 2×ATR, Target 3×ATR.  
**Sound logic**, well-parameterized.

### 9.8 Volatility Crush (ALPHA_VOL_CRUSH_208)

**Entry:** Regime VOLATILE/BEAR, VIX ≥ 20.  
**Bug:** No check that VIX is actually declining — only checks VIX > 20 threshold. The "crush" thesis requires VIX to have peaked.  
**Possibly incomplete** — file appears truncated at ~200 lines.

### Wave 2 Strategy Summary

| Strategy | Fires Reliably? | Logic Sound? | Key Issue |
|----------|----------------|-------------|-----------|
| Momentum Rotation | Yes (BULL/SIDEWAYS) | RS calc is misleading | Not relative to benchmark |
| Sector Rotation | Rarely (BULL only, 20 stocks) | Sound | Very restrictive |
| BB Squeeze | Yes | Good | None critical |
| RSI Divergence | Yes | Good (fine-tuned) | None critical |
| Earnings Momentum | Yes (any gap > 3%) | Flawed | No earnings calendar |
| Gap Fill | Yes | Sound | Volume check missing |
| ATR Breakout | Yes | Good | None critical |
| Vol Crush | Yes | Flawed | No VIX decline check |

---

## 10. Options Strategy Audit — Multi-Leg

### 10.1 Architecture Problem

**The system has NO actual multi-leg execution capability.**

The `StrategySignal` model (`backend/src/strategies/base.py`) has no `legs[]` field. All multi-leg information is stuffed into the generic `metadata: Dict` field. The `ExecutionAgent` places **one single market order** — it does not parse metadata for legs, cannot place atomic multi-leg orders, and has no bracket/OCO support.

### 10.2 Options Strategies Inventory

**Tier 1 — Detailed implementations (SEBI-labeled, individual files):**

| Strategy | File | Signal Gen | Premiums | Greeks | SEBI ID |
|----------|------|-----------|---------|--------|---------|
| Iron Condor | `multileg/iron_condor.py` | 4-leg metadata | Hardcoded estimates | None | ALPHA_IRON_011 |
| Bull Call Spread | `spreads/bull_call_spread.py` | 2-leg metadata | Hardcoded (120/60) | None | ALPHA_BCS_007 |
| Portfolio Hedge | `hedging/portfolio_hedge.py` | 1-leg (put buy) | Estimated | None | ALPHA_PORT_017 |

**Tier 2 — Basic implementations (strategies.py files):**

| Strategy | File | Issues |
|----------|------|--------|
| IronCondor | multileg/strategies.py | Uses non-existent `entry_type` field on StrategySignal |
| ButterflySpread | multileg/strategies.py | Same field issue |
| LongStrangle | multileg/strategies.py | Same field issue |
| BearPutSpread | spreads/strategies.py | Same field issue |
| RatioSpread | spreads/strategies.py | Same field issue |
| CalendarSpread | spreads/strategies.py | Same field issue |
| LongStraddle | volatility/strategies.py | Same field issue |
| VIXTrading | volatility/strategies.py | Same field issue |
| DeltaHedging | hedging/strategies.py | Uses price momentum as delta proxy (not actual Greeks) |

**Tier 3 — Simple/broken:**

| Strategy | File | Issue |
|----------|------|-------|
| IronCondorStrategy (simple) | options/iron_condor.py | `market_data.get('vix')` on DataFrame → runtime error |

### 10.3 What's NOT Implemented for Options

| Capability | Status |
|------------|--------|
| Atomic multi-leg order execution | **Missing** |
| Individual leg P&L monitoring | **Missing** |
| Leg adjustment/rolling | **Missing** |
| Leg surrender (close one, keep others) | **Missing** |
| Dynamic strategy creation from UniversalStrategy | **Missing** (equity only) |
| Real option chain data flow | **Missing** (fetched then discarded) |
| Greeks (delta/gamma/theta/vega) | **Missing** (BS math exists but stubbed) |
| Premium pricing from market | **Missing** (all hardcoded) |
| Expiry management / DTE tracking | **Missing** |
| Position monitoring for multi-leg | **Missing** |

### 10.4 Black-Scholes Implementation

`backend/src/strategies/quant/vol_surface.py` contains:
- **Correct** `black_scholes_call(S, K, T, r, sigma)` using `scipy.stats.norm`
- **Correct** `implied_volatility()` using Brent's method root-finding
- Risk-free rate: 7% (India 10Y proxy)
- **BUT** `build_surface()` is stubbed — always returns `[]`

The math exists but is **disconnected from all strategies**.

---

## 11. Universal AI Strategy Audit

**File:** `backend/src/strategies/universal_strategy.py`

**Purpose:** JSON-configurable meta-strategy for SEBI "whitebox" compliance.

**Supported Conditions:**
- Indicators: RSI, SMA, EMA, MACD
- Operators: GT, LT, CROSS_ABOVE, CROSS_BELOW
- Logic: Implicit AND across all conditions

**What It Can Do:**
- Express various RSI/SMA/EMA/MACD strategies without code changes
- Dynamic indicator calculation via `pandas_ta`
- Configurable stop-loss and take-profit percentages

**What It Cannot Do:**
- No options-specific conditions (IV, Greeks, strike, expiry)
- No multi-leg signal generation
- No option chain integration
- No regime-aware parameter adjustment
- MACD evaluation logic is incomplete
- CROSS_ABOVE/BELOW detection is convoluted and may not work correctly
- Cannot create or modify strategies at runtime (config must be set at instantiation)

---

## 12. Data Pipeline Audit

### 12.1 Three-Tier Architecture

| Tier | Source | Status | Data Quality |
|------|--------|--------|-------------|
| 1 | DhanHQ API | **PLACEHOLDER** — all methods commented out | Would be real-time if implemented |
| 2 | nselib | **Limited** — single-day snapshots only, no historical | Current day indices + bhavcopy |
| 3 | yfinance | **Working** — actual data source for everything | Delayed EOD, no intraday |

### 12.2 Data Methods Available

| Method | Source | Cache TTL | Status |
|--------|--------|-----------|--------|
| `get_index_ohlc(index, period)` | yfinance | 300s | Working |
| `get_stock_ohlc(symbol, period)` | yfinance | 300s | Working |
| `get_stock_with_indicators(symbol, period)` | yfinance + ta | 300s | Working (15+ indicators) |
| `get_india_vix()` | yfinance `^INDIAVIX` | 60s | Working (fallback 15.0) |
| `get_option_chain(symbol)` | yfinance | 60s | **Broken** — fetches data but returns `data: []` |
| `get_latest_index_value(index)` | nselib | 5s | Partially working |
| `get_delivery_percentage(symbol)` | nselib bhavcopy | None | Working (current day only) |
| `get_nifty_100_stocks()` | Hardcoded | N/A | 95 stocks |

### 12.3 Critical Data Gaps

1. **No intraday data** — ORB and VWAP strategies approximate from daily candles
2. **No streaming/WebSocket** — required for real-time intraday
3. **Option chain data discarded** — `get_option_chain()` fetches but doesn't process
4. **No NSE holiday calendar** — weekday check only
5. **Redis cache created without connection** — `nse_data_service = NSEDataService()` at module level with no Redis
6. **Period mapping bug** — default fallback "1mo" for unmapped periods
7. **DhanHQ Tier 1 entirely placeholder** — no actual API calls

---

## 13. Broker Integration Audit (Dhan)

### 13.1 Current State

**File:** `backend/src/services/dhan_client.py`

| Method | Implementation | Status |
|--------|---------------|--------|
| `connect()` | Initializes `dhanhq` SDK from env vars | Ready if creds provided |
| `place_order(order_details)` | Calls `self.dhan.place_order()` or returns `SIM_...` | Works for single orders |
| `fetch_market_data(security_id, exchange)` | Returns `{"ltp": 0.0}` | **PLACEHOLDER** |
| `get_order_status(order_id)` | Delegates to DhanHQ | Works if connected |

### 13.2 Integration Issues

1. **Global `dhan_client = None`** — lazy-init via `get_dhan_client()` but `execution.py` imports the `None` directly
2. **No symbol-to-security-ID mapping** — `securityId: "1333"` hardcoded
3. **No multi-leg order support** — DhanHQ supports bracket orders but client doesn't use them
4. **No market data via Dhan** — `fetch_market_data()` is a stub returning LTP=0
5. **No WebSocket data feed** — DhanHQ supports WebSocket but not implemented
6. **No order modification/cancellation** — critical for position management
7. **No position fetch** — DhanHQ can report positions, not implemented

### 13.3 What DhanHQ API Provides (Available but Not Used)

With the Dhan API credentials now available, these capabilities can be unlocked:

| DhanHQ Feature | Use Case | Current Status |
|----------------|----------|---------------|
| Market data API | Real-time LTP, OHLC | Placeholder |
| WebSocket feed | Streaming quotes for intraday | Not implemented |
| Order placement | Single + bracket orders | Single only (simulated) |
| Order modification | Leg adjustment, SL updates | Not implemented |
| Position book | Portfolio tracking | Not implemented |
| Holdings | Long-term position tracking | Not implemented |
| Trade book | Executed trade history | Not implemented |
| Option chain | Real-time strikes, premiums, OI | Not implemented |
| Security master | Symbol-to-ID mapping | Not implemented (hardcoded 1333) |

---

## 14. Risk Management Audit

### 14.1 Framework

| Check | Rule | Status |
|-------|------|--------|
| Kill Switch | Daily PnL < -5% capital | Logic exists, PnL never updated |
| Portfolio Heat | Open risk / capital ≥ 25% | Logic exists, positions never tracked |
| Correlation | Max correlation > 0.7 | Logic exists, always returns 0.0 |
| VaR (95%) | VaR > 2% capital | Implemented |
| Risk-Reward | R:R < 1.5 | Implemented |
| Kelly Criterion | Quarter-Kelly formula | Implemented (static win_rate) |
| VIX Scaling | 0.4× to 1.2× multiplier | Implemented |

### 14.2 Gaps

- **Missing imports** — `Dict`, `Any`, `pd` not imported → runtime NameError
- **open_positions never populated** — heat and correlation checks are cosmetic
- **Daily PnL never updated** — kill switch can never fire
- **No multi-leg risk** — no aggregate Greeks, no per-leg assessment
- **No sector concentration enforcement** — 30% limit defined but not checked
- **Kelly win_rate static** (0.55) — no learning from actual results
- **No drawdown tracking** across multiple cycles

---

## 15. SEBI Compliance Audit

### 15.1 What Exists

| Requirement | Implementation |
|-------------|---------------|
| Unique algo ID per strategy | Present in metadata for 3 strategies (Iron Condor, Bull Call Spread, Portfolio Hedge) |
| Whitebox labeling | Docstrings mention "SEBI Whitebox" for 3 strategies |
| Iron Condor disabled | Correctly removed from `init_agents.py` per Jane Street manipulation risk |
| Kill switch | -5% daily loss limit in RiskAgent |
| Position limits | Documented in docstrings (2% per trade, 5 concurrent max) |

### 15.2 What's NOT Enforced in Code

| SEBI Requirement | Status |
|------------------|--------|
| Expiry day trading restrictions | **Docstring only** — no datetime check |
| Position size limits | **Not enforced** — Kelly sizing has no hard cap per trade |
| Maximum concurrent positions | **Not counted** — no position tracking |
| Tranche execution (2-3 split orders) | **Not implemented** |
| Real-time position reporting to exchange | **Not implemented** |
| Algo registration with SEBI/exchange | **Not implemented** |
| Two-factor approval for large orders | HYBRID mode exists but approval path is TODO |
| Audit trail logging | DB insert exists but schema mismatches |
| Order-level algo tagging | Not implemented (Dhan API supports `tag` field) |
| Pre-trade risk validation | Logic exists but bypassed by empty position tracking |

---

## 16. Backtester Reliability Audit

### 16.1 Suspicious Results

| Strategy | Period | Sharpe | Issue |
|----------|--------|--------|-------|
| VWAP Reversion | 1Y NIFTY | +10.74 | 89% win rate, unrealistic |
| VWAP Reversion | 3Y NIFTY | +13.10 | 1.99 billion % return — **compounding bug** |
| VWAP Reversion | 5Y NIFTY | +16.69 | Same class of bug |
| Iron Condor | Stock level | +19 to +36 | Simplified premium model (always collects) |

### 16.2 Methodology Issues

1. **Iron Condor backtest is not an options backtest** — uses flat 0.5%/1.0% credit/loss based on weekly range (no options pricing, no theta, no IV)
2. **Wave 2 strategies share same backtest method** — BB Squeeze, RSI Div, Momentum, ATR all fall back to `backtest_breakout_strategy`; results are identical per stock
3. **No slippage or commission modeling**
4. **No fill simulation** — assumes instant fill at exact signal price
5. **Multi-period backtest CSV is empty** — no data
6. **VWAP uses 3-month cumulative VWAP (not intraday)** — backtest results are meaningless for intraday strategy

### 16.3 Realistic Results

| Strategy | Stock | Sharpe | Realistic? |
|----------|-------|--------|-----------|
| Swing Breakout | SBIN | 1.21 | Yes |
| Swing Breakout | TATASTEEL | 1.69 | Yes |
| EMA Crossover | SBIN | 1.46 | Yes |
| ORB | NIFTY (3Y) | 0.25 | Yes |

---

## 17. Test Coverage Audit

| File | Type | Assertions | Status |
|------|------|-----------|--------|
| `backend/test_strategies.py` | Integration demo | None (print only) | Not a real test |
| `backend/test_all_agents.py` | Integration demo | None (print only) | Not a real test |
| `backend/test_integration.py` | Smoke test | None (print only) | Not a real test |
| `backend/test_sentiment.py` | Sentiment demo | None | Not a real test |
| `backend/test_nse.py` | Data demo | None | Not a real test |
| `backend/tests/test_strategy_registry.py` | Unit test | Has `assert` | **Will fail** — expected keys don't match actual registry |

**Effective test coverage: ~0%** — No unit tests with assertions for any strategy, agent, or service.

---

## 18. Infrastructure & DevOps Audit

### 18.1 Docker

| Issue | Detail |
|-------|--------|
| Port mismatch | Dockerfile CMD → port 5000, compose → port 8000, `src/main.py` → port 8000 |
| Dual entrypoints | `backend/main.py` (Socket.IO/5000) vs `backend/src/main.py` (FastAPI/8000) |
| Heavy dependencies | `nautilus_trader>=1.218.0` may cause Docker build failures |
| TA-Lib | Commented out (requires manual Windows .whl) |

### 18.2 Configuration

| Issue | Detail |
|-------|--------|
| No `.env.example` | Template for required env vars missing |
| CORS wildcard | `allow_origins=["*"]` in production |
| No environment separation | Same config for dev/staging/prod |
| Firestore required at startup | Hard requirement even for local dev |

### 18.3 API Layer

`backend/src/api/` contains only an empty `__init__.py`. No routes, no endpoints. The only HTTP endpoints are:
- `GET /health` → health check
- `POST /trigger-cycle` → manual orchestration trigger

No API for: strategy listing, portfolio view, signal history, market data, backtest results, agent status, trade management, WebSocket streaming.

---

## 19. Bugs & Inconsistencies Registry

| # | Severity | File | Issue |
|---|----------|------|-------|
| B01 | Critical | `agents/execution.py` L4-5 | `import vertexai` — not installed |
| B02 | Critical | `database/firestore.py` L1 | `from google.cloud import firestore` — not installed |
| B03 | Critical | `src/main.py` L3 | `apscheduler` not in requirements |
| B04 | Critical | `agents/init_agents.py` L108-118 | 4 classes used without import → NameError |
| B05 | Critical | `src/main.py` L7 | `db_firestore` is None at import time |
| B06 | Critical | `agents/risk.py` | Missing `Dict`, `Any`, `pd` imports → NameError |
| B07 | High | `agents/execution.py` L73 | `securityId: "1333"` hardcoded for all orders |
| B08 | High | `services/nse_data.py` get_option_chain() | Fetches data then returns `data: []` |
| B09 | High | `agents/scanner.py` → `agents/strategy.py` | Scanner returns `List[Dict]`, strategy iterates as `List[str]` |
| B10 | High | `strategies/quant/vol_surface.py` build_surface() | Stubbed with `pass`, always returns `[]` |
| B11 | High | `agents/portfolio.py` | Entire agent is a stub — no position tracking |
| B12 | High | `agents/risk.py` | `open_positions` never populated — heat/correlation checks no-op |
| B13 | Medium | `strategies/swing/pullback.py` | Needs 205 bars, but strategy agent fetches 63 bars (3M) |
| B14 | Medium | `strategies/swing/breakout.py` | ADX/volume documented as required but not enforced |
| B15 | Medium | `strategies/swing/ema_crossover.py` | `target_price` missing from signal construction |
| B16 | Medium | `strategies/wave2/event_driven.py` (Gap Fill) | Volume confirmation documented but not implemented |
| B17 | Medium | `strategies/wave2/volatility.py` (Vol Crush) | No VIX decline check (only threshold) |
| B18 | Medium | `strategies/wave2/momentum.py` | RS score is absolute, not relative to benchmark |
| B19 | Medium | All `spreads/strategies.py`, `multileg/strategies.py` | Use non-existent `StrategySignal` fields (`entry_type`, `confidence`) |
| B20 | Medium | `strategies/mean_reversion/vwap.py` | Cumulative VWAP over 3M (not intraday reset) |
| B21 | Medium | `options/iron_condor.py` | `market_data.get('vix')` on DataFrame fails |
| B22 | Low | `core/event_bus.py` vs `core/event_bus_redis.py` | `subscribe()` sync vs async mismatch |
| B23 | Low | `core/resilience.py` | CircuitBreaker exists but never used |
| B24 | Low | `agents/sentiment.py` | Social media returns 2 fake headlines |
| B25 | Low | `core/agent_manager.py` vs `agents/base.py` | EventBus dual-initialization (module vs instance) |
| B26 | Low | `services/nse_data.py` | Period mapping "3M" fallback produces wrong yfinance period |
| B27 | Low | Dockerfile | Port 5000 vs compose port 8000 |
| B28 | Low | `utils/fast_math.py` | Hurst exponent has dead code (unused `A` matrix) |

---

## 20. Paper Trading Readiness Scorecard

| Component | Score | Status | Blocking? |
|-----------|-------|--------|-----------|
| **Startup (app can launch)** | 0% | 5 blocking import errors | **YES** |
| **Requirements.txt** | 50% | 6+ missing packages | **YES** |
| **Core architecture** | 70% | Sound design, event-driven | No |
| **Agent orchestration** | 65% | Works conceptually; import errors block | **YES** |
| **Equity strategy signal gen** | 75% | 11 strategies produce valid signals | No |
| **Options strategy execution** | 0% | No multi-leg capability | **YES** (for options) |
| **Real-time data feed** | 0% | DhanHQ placeholder, yfinance EOD only | **YES** |
| **Broker order placement** | 10% | Simulated only; security ID hardcoded | **YES** |
| **Position tracking** | 0% | PortfolioAgent is a stub | **YES** |
| **Stop-loss/target monitoring** | 0% | Time exits and SL not enforced | **YES** |
| **Continuous execution loop** | 0% | Paper trading runs once and exits | **YES** |
| **Risk management** | 40% | Logic present but state never updated | **YES** |
| **API layer** | 5% | Empty — only /health and /trigger-cycle | No (for paper trading) |
| **SEBI compliance** | 20% | Labels exist, enforcement does not | **YES** (for live) |
| **Test coverage** | 0% | No unit tests with assertions | No (for paper trading) |
| **Database schema** | 60% | Tables exist; column mismatches | Medium |

**Overall: NOT READY. 9 blocking categories must be resolved.**

---

## 21. Recommended Implementation Plan

### Prerequisites

- Dhan API credentials available (confirmed by user)
- Local Docker environment (PostgreSQL + Redis)
- Python 3.12 environment

---

### Phase 0: Fix Startup Blockers (Day 1)

**Goal:** App can start without errors.

| Step | Task | Files | Detail |
|------|------|-------|--------|
| 0.1 | Wrap vertexai import in try/except | `agents/execution.py` | Fall back to rule-based justification |
| 0.2 | Wrap google.cloud.firestore in try/except | `database/firestore.py` | Make Firestore fully optional |
| 0.3 | Add missing imports in init_agents.py | `agents/init_agents.py` | Add imports for StatisticalArbitrageStrategy, VolatilityArbitrageStrategy, CrossSectionalMomentumStrategy, UniversalStrategy |
| 0.4 | Fix db_firestore initialization | `src/main.py` | Use `get_firestore_client()` or make connection conditional |
| 0.5 | Fix RiskAgent imports | `agents/risk.py` | Add `from typing import Dict, Any` and `import pandas as pd` |
| 0.6 | Update requirements.txt | `requirements.txt` | Add: apscheduler, asyncpg, pydantic-settings, google-cloud-firestore (optional), google-cloud-aiplatform (optional), python-socketio |
| 0.7 | Standardize port to 8000 | `Dockerfile`, `backend/main.py` | Align all entrypoints |

**Verification:** `python -c "from src.main import app"` succeeds.

---

### Phase 1: Dhan API Integration — Data Feed (Days 2-4)

**Goal:** Real market data flowing to all strategies via DhanHQ Tier 1.

| Step | Task | Files | Detail |
|------|------|-------|--------|
| 1.1 | Implement DhanHQ security master | `services/dhan_client.py` | Download and cache CSV from DhanHQ, build symbol→security_id mapping |
| 1.2 | Implement `fetch_market_data()` | `services/dhan_client.py` | Real LTP, OHLC via DhanHQ market data API |
| 1.3 | Implement Dhan historical OHLC | `services/nse_data.py` Tier 1 | Replace placeholder in `get_stock_ohlc()` and `get_index_ohlc()` |
| 1.4 | Implement Dhan option chain | `services/nse_data.py` | Real strikes, premiums, OI, volume via DhanHQ |
| 1.5 | Fix `get_option_chain()` return | `services/nse_data.py` | Process and return actual calls/puts data instead of `[]` |
| 1.6 | Implement WebSocket data feed | New: `services/dhan_websocket.py` | Streaming quotes for intraday strategies (ORB, VWAP) |
| 1.7 | Fix Redis cache initialization | `services/nse_data.py` | Pass Redis connection at startup, not at module import |

**Verification:** `nse_data_service.get_stock_ohlc("SBIN", "3mo")` returns DhanHQ data with < 1s latency.

---

### Phase 2: Broker Order Execution (Days 5-7)

**Goal:** Real paper orders through DhanHQ.

| Step | Task | Files | Detail |
|------|------|-------|--------|
| 2.1 | Implement security ID lookup | `agents/execution.py`, `services/dhan_client.py` | Remove hardcoded "1333", lookup from security master |
| 2.2 | Fix `dhan_client` import pattern | `agents/execution.py` | Use `get_dhan_client()` instead of importing module-level `None` |
| 2.3 | Implement proper order params | `agents/execution.py` | Map StrategySignal fields to DhanHQ order params (exchange, segment, product type) |
| 2.4 | Add order modification/cancel | `services/dhan_client.py` | Required for stop-loss updates and position management |
| 2.5 | Implement position book fetch | `services/dhan_client.py` | `get_positions()` → current open positions from DhanHQ |
| 2.6 | Implement trade book fetch | `services/dhan_client.py` | `get_trades()` → executed trade history |
| 2.7 | Add Dhan `tag` field for algo ID | `agents/execution.py` | SEBI audit trail via order tags |

**Verification:** Place and verify a paper order through DhanHQ sandbox.

---

### Phase 3: Position Management & Monitoring (Days 8-11)

**Goal:** Persistent position tracking with stop-loss/target enforcement.

| Step | Task | Files | Detail |
|------|------|-------|--------|
| 3.1 | Rebuild PortfolioAgent | `agents/portfolio.py` | Fetch positions from DhanHQ, calculate real PnL, persist to PostgreSQL |
| 3.2 | Implement position state in DB | `db/init.sql`, new migration | Add `open_positions` table with per-position SL, target, regime, entry_time |
| 3.3 | Wire RiskAgent to real positions | `agents/risk.py` | Populate `open_positions` from DB; make heat/correlation checks real |
| 3.4 | Build SL/TP monitoring loop | New: `services/position_monitor.py` | Continuous check of open positions against SL/target; trigger exit orders |
| 3.5 | Implement time-based exits | `services/position_monitor.py` | Intraday: exit at 15:15. Swing: exit at max hold days |
| 3.6 | Update daily PnL tracking | `agents/risk.py` | Feed real PnL to kill switch |
| 3.7 | Fix schema mismatches | `db/init.sql`, `agents/execution.py` | Align trade table columns with insert statements |

**Verification:** Open a test position, verify it persists across restarts, verify SL triggers an exit.

---

### Phase 4: Fix Scanner→Strategy Data Flow (Day 12)

**Goal:** Clean data handoff between agents.

| Step | Task | Files | Detail |
|------|------|-------|--------|
| 4.1 | Fix scanner return type handling | `agents/strategy.py` | Extract `symbol` from scanner's `List[Dict]` instead of treating as string |
| 4.2 | Increase data fetch period for Pullback | `agents/strategy.py` | Fetch "1Y" for strategies needing 200+ bars |
| 4.3 | Fix StrategySignal field usage | 12 files in `strategies/` | Replace `entry_type`, `confidence` with actual model fields |
| 4.4 | Enforce documented entry conditions | `swing/breakout.py`, `wave2/event_driven.py` | Add volume/ADX to required checks (not just strength scoring) |

**Verification:** Run full cycle; all 11 Tier 1 strategies can generate valid signals.

---

### Phase 5: Continuous Paper Trading Loop (Days 13-15)

**Goal:** System runs persistently, not one-shot.

| Step | Task | Files | Detail |
|------|------|-------|--------|
| 5.1 | Refactor paper trading as persistent service | `run_paper_trading.py` → integrate into `src/main.py` | Use APScheduler 3-min loop with position state persistence |
| 5.2 | Add market hours awareness | New: `services/market_calendar.py` | NSE holiday calendar, pre-market/post-market detection |
| 5.3 | Implement graceful shutdown | `src/main.py` | Save state, close DhanHQ connection, cancel pending orders |
| 5.4 | Add health dashboard data | `src/api/` | Basic endpoints: `/positions`, `/signals`, `/trades`, `/agents/health` |
| 5.5 | Wire Kelly win-rate update | `agents/risk.py` | After each trade closes, update empirical win rate from DB |

**Verification:** Start system, let run for 1 full trading day, verify signals → orders → position tracking → SL/TP exits.

---

### Phase 6 (Optional): Options Multi-Leg Execution

**Goal:** Support actual multi-leg option strategies.

| Step | Task | Detail |
|------|------|--------|
| 6.1 | Add `legs[]` to StrategySignal | `LegSignal` model: action, option_type, strike, expiry, quantity, premium |
| 6.2 | Multi-leg execution in ExecutionAgent | Parse legs, place atomically (DhanHQ basket order or sequential with rollback) |
| 6.3 | Per-leg position tracking | Track each leg's P&L, Greeks, premium |
| 6.4 | Wire VolSurfaceBuilder to real data | Complete `build_surface()` with real option chain |
| 6.5 | Implement leg adjustment engine | Roll, surrender, re-leg with configurable rules |
| 6.6 | Greeks-based risk monitoring | Portfolio delta/gamma/theta/vega limits |

---

### Phase 7 (Optional): SEBI Compliance Enforcement

| Step | Task | Detail |
|------|------|--------|
| 7.1 | Pre-trade validation middleware | Enforce position limits, expiry-day restrictions before execution |
| 7.2 | Order tagging | Add SEBI algo ID to every DhanHQ order via `tag` field |
| 7.3 | Audit trail logging | Complete trade lifecycle logging to PostgreSQL |
| 7.4 | Tranche execution | Split large orders into 2-3 time-separated sub-orders |
| 7.5 | Concurrent position counter | Hard limit enforcement (e.g., max 10 concurrent) |

---

### Implementation Priority Matrix

```
                    IMPACT
                    High ─────────────────────────── Low
         │
    Easy │  Phase 0 (Startup)     Phase 4 (Data Flow)
         │  Phase 1.1-1.3 (Dhan   
         │    historical data)     
EFFORT   │                        
         │  Phase 2 (Orders)      Phase 5.4 (API)
         │  Phase 3 (Positions)   Phase 7 (SEBI)
         │  Phase 5 (Loop)        
    Hard │  Phase 1.6 (WebSocket) Phase 6 (Options Multi-Leg)
         │
```

**Recommended order:** Phase 0 → Phase 1 (1.1-1.5) → Phase 2 → Phase 3 → Phase 4 → Phase 5 → then Phase 6/7 as needed.

**Estimated time to minimum viable paper trading (equities):** ~15 working days with focused effort.

---

*End of Audit — February 23, 2026*
