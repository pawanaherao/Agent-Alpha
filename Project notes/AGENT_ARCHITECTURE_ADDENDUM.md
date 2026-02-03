# AGENTIC ALPHA 2026 - Agent Architecture Addendum

**Version:** 4.0  
**Date:** January 30, 2026  
**Document Type:** Technical Specification Addendum  
**Parent Document:** AGENTIC_ALPHA_2026_ENHANCED_ARCHITECTURE.md  

---

## 📋 TABLE OF CONTENTS

1. [Executive Summary](#1-executive-summary)
2. [Agent Overview](#2-agent-overview)
3. [Agent Detailed Specifications](#3-agent-detailed-specifications)
4. [Agent Orchestration Framework](#4-agent-orchestration-framework)
5. [Communication Protocols](#5-communication-protocols)
6. [Data Flow Architecture](#6-data-flow-architecture)
7. [Error Handling & Resilience](#7-error-handling--resilience)
8. [Performance Optimization](#8-performance-optimization)
9. [Monitoring & Observability](#9-monitoring--observability)
10. [Implementation Examples](#10-implementation-examples)

---

## 1. EXECUTIVE SUMMARY

The Agentic Alpha 2026 system employs **8 specialized AI agents** that work collaboratively to execute algorithmic trading strategies. This document provides a comprehensive specification of each agent's roles, responsibilities, decision-making processes, and inter-agent orchestration patterns.

### Agent Hierarchy

```
┌─────────────────────────────────────────────────────────────┐
│                     ORCHESTRATOR HUB                        │
│                    (FastAPI Main Loop)                      │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │         MARKET HOURS: 9:15 AM - 3:30 PM IST         │   │
│  │         Execution Cycle: Every 3 minutes (180s)     │   │
│  └─────────────────────────────────────────────────────┘   │
└──────────────────────────┬──────────────────────────────────┘
                           │
        ┌──────────────────┴──────────────────┐
        │                                     │
   ┌────▼────┐                          ┌────▼────┐
   │ SENSING │                          │ ACTING  │
   │ AGENTS  │                          │ AGENTS  │
   └────┬────┘                          └────┬────┘
        │                                     │
  ┌─────┴─────────────┐           ┌──────────┴──────────┐
  │                   │           │                     │
  ▼                   ▼           ▼                     ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│  SENTIMENT   │ │   REGIME     │ │   SCANNER    │ │   STRATEGY   │
│    AGENT     │ │    AGENT     │ │    AGENT     │ │    AGENT     │
│              │ │              │ │              │ │              │
│ Market Mood  │ │ Market State │ │ Opportunity  │ │ Signal Gen   │
│ (-1 to +1)   │ │ 4 Regimes    │ │ Finder       │ │ 18 Strategies│
└──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘
                                                           │
                                    ┌──────────────────────┤
                                    │                      │
                                    ▼                      ▼
                           ┌──────────────┐      ┌──────────────┐
                           │     RISK     │      │  EXECUTION   │
                           │    AGENT     │      │    AGENT     │
                           │              │      │              │
                           │ Position Size│      │ Order Mgmt   │
                           │ Kill Switch  │      │ Smart Entry  │
                           └──────┬───────┘      └──────┬───────┘
                                  │                     │
                                  └──────────┬──────────┘
                                             │
                              ┌──────────────┴──────────────┐
                              │                             │
                              ▼                             ▼
                     ┌──────────────┐            ┌──────────────┐
                     │    PAPER     │            │  PORTFOLIO   │
                     │    AGENT     │            │    AGENT     │
                     │              │            │              │
                     │ Simulation   │            │ Portfolio    │
                     │ Backtesting  │            │ Greeks Mgmt  │
                     └──────────────┘            └──────────────┘
```

### Agent Classification

| **Agent** | **Type** | **Priority** | **Execution Frequency** |
|-----------|----------|--------------|------------------------|
| Sentiment Agent | Sensing | P1 | Every 3 min |
| Regime Agent | Sensing | P0 | Every 3 min |
| Scanner Agent | Sensing | P1 | Every 3 min |
| Strategy Agent | Decision | P0 | Every 3 min (on signal) |
| Risk Agent | Control | P0 | Continuous (every signal) |
| Execution Agent | Action | P0 | On-demand (per signal) |
| Paper Agent | Simulation | P2 | MODE=PAPER only |
| Portfolio Agent | Monitoring | P1 | Every 15 min + on-trade |

**Priority Levels:**
- **P0 (Critical):** Must complete; failure blocks system
- **P1 (High):** Should complete; degraded mode if fails
- **P2 (Medium):** Can skip; non-blocking

---

## 2. AGENT OVERVIEW

### 2.1 Quick Reference Matrix

| Agent | Primary Input | Primary Output | Dependencies | Downstream Consumers |
|-------|--------------|----------------|--------------|---------------------|
| **Sentiment** | News, Twitter, GIFT Nifty | Sentiment Score (-1 to +1) | External APIs | Regime, Strategy |
| **Regime** | OHLC, Indicators, Sentiment | Regime (BULL/BEAR/SIDEWAYS/VOLATILE) | Sentiment | Scanner, Strategy |
| **Scanner** | Universe List, Quotes, Regime | Top 10 Opportunities | Regime, Market Data | Strategy |
| **Strategy** | Regime, Opportunities, Signals | Trade Signals (18 strategies) | Regime, Scanner, Risk | Risk, Execution |
| **Risk** | Signals, Portfolio State | Position Size, Approval/Reject | Strategy, Portfolio | Execution, Portfolio |
| **Execution** | Approved Signals | Order IDs, Fills | Risk | Paper/Live Broker |
| **Paper** | Signals (in PAPER mode) | Simulated Fills, P&L | Execution | Portfolio |
| **Portfolio** | All Trades, Market Data | Portfolio Metrics, Greeks | All agents | Risk, Strategy |

### 2.2 Agent Lifecycle States

Each agent maintains the following states:

```python
class AgentState(Enum):
    INITIALIZING = "initializing"    # Starting up, loading config
    READY = "ready"                  # Idle, waiting for trigger
    RUNNING = "running"              # Actively processing
    WAITING = "waiting"              # Waiting for dependencies
    ERROR = "error"                  # Error state, needs intervention
    DISABLED = "disabled"            # Manually disabled by admin
```

---

## 3. AGENT DETAILED SPECIFICATIONS

### 3.1 SENTIMENT AGENT

**Role:** Market sentiment analyzer - gauges overall market mood and directional bias.

#### Responsibilities

1. **News Aggregation**
   - Fetch top 20 news headlines from:
     - Economic Times
     - MoneyControl
     - Business Standard
     - Reuters India
   - Filter for market-relevant keywords (Nifty, markets, RBI, inflation, etc.)

2. **Social Media Analysis**
   - Monitor Twitter hashtags: #Nifty, #BankNifty, #NSE, #IndianMarkets
   - Analyze sentiment of top 100 tweets in last 30 minutes
   - Weight by user influence score

3. **Global Market Correlation**
   - Fetch overnight performance:
     - US markets (S&P 500, Nasdaq, Dow)
     - Asian markets (Nikkei, Hang Seng, SGX Nifty)
   - GIFT Nifty pre-market indication

4. **Sentiment Score Calculation**
   - Combine inputs with weighted formula:
     ```
     Sentiment = (0.4 * News_Sentiment) + 
                 (0.3 * Social_Sentiment) + 
                 (0.2 * Global_Markets) + 
                 (0.1 * GIFT_Nifty)
     ```
   - Output: Float between -1.0 (extremely bearish) to +1.0 (extremely bullish)

#### Input Specifications

```python
class SentimentInput(BaseModel):
    timestamp: datetime
    news_headlines: List[str]           # Top 20 headlines
    tweets: List[Dict]                  # Tweet text + metadata
    global_markets: Dict[str, float]    # Symbol: change_pct
    gift_nifty: Dict                    # Price, change, volume
```

#### Output Specifications

```python
class SentimentOutput(BaseModel):
    timestamp: datetime
    sentiment_score: float              # -1.0 to +1.0
    confidence: float                   # 0.0 to 1.0
    contributing_factors: Dict[str, float]  # Breakdown by source
    key_drivers: List[str]              # Top 3 sentiment drivers
    
    # Example:
    # {
    #   "sentiment_score": 0.35,
    #   "confidence": 0.78,
    #   "contributing_factors": {
    #     "news": 0.45,
    #     "social": 0.25,
    #     "global": 0.30,
    #     "gift_nifty": 0.40
    #   },
    #   "key_drivers": [
    #     "RBI maintains repo rate at 6.5%",
    #     "FII inflows continue for 5th day",
    #     "US markets closed higher"
    #   ]
    # }
```

#### Processing Logic

```python
class SentimentAgent(BaseAgent):
    async def analyze(self, market_data: Dict) -> SentimentOutput:
        """
        Main analysis pipeline
        """
        # Step 1: Fetch news
        news = await self._fetch_news()
        news_sentiment = await self._analyze_news_sentiment(news)
        
        # Step 2: Analyze social media
        tweets = await self._fetch_tweets()
        social_sentiment = await self._analyze_social_sentiment(tweets)
        
        # Step 3: Global markets
        global_data = await self._fetch_global_markets()
        global_sentiment = self._calculate_global_sentiment(global_data)
        
        # Step 4: GIFT Nifty
        gift_nifty = await self._fetch_gift_nifty()
        gift_sentiment = self._calculate_gift_sentiment(gift_nifty)
        
        # Step 5: Weighted combination
        sentiment_score = (
            0.4 * news_sentiment +
            0.3 * social_sentiment +
            0.2 * global_sentiment +
            0.1 * gift_sentiment
        )
        
        # Step 6: Calculate confidence
        confidence = self._calculate_confidence([
            news_sentiment, social_sentiment, 
            global_sentiment, gift_sentiment
        ])
        
        return SentimentOutput(
            timestamp=datetime.now(),
            sentiment_score=sentiment_score,
            confidence=confidence,
            contributing_factors={...},
            key_drivers=self._extract_key_drivers(news)
        )
```

#### Performance Metrics

- **Execution Time:** < 5 seconds
- **Caching:** 180 seconds (matches orchestration cycle)
- **Fallback:** If external APIs fail, use last known sentiment with degraded confidence

#### Integration Points

**Upstream Dependencies:**
- News APIs (Economic Times, MoneyControl)
- Twitter API
- Yahoo Finance (global markets)
- NSE GIFT Nifty feed

**Downstream Consumers:**
- Regime Agent (uses sentiment for regime confirmation)
- Strategy Agent (sentiment-based strategy filtering)
- Risk Agent (sentiment extremes trigger risk adjustments)

---

### 3.2 REGIME AGENT

**Role:** Market regime classifier - determines current market state (Bull/Bear/Sideways/Volatile).

#### Responsibilities

1. **Technical Indicator Calculation**
   - EMA (9, 21, 50, 200)
   - ADX (14-period)
   - RSI (14-period)
   - MACD (12, 26, 9)
   - Bollinger Bands (20, 2σ)
   - ATR (14-period)

2. **Regime Classification**
   - **BULL:** Uptrend with momentum
   - **BEAR:** Downtrend with momentum
   - **SIDEWAYS:** Range-bound, low momentum
   - **VOLATILE:** High volatility, direction unclear

3. **Confidence Scoring**
   - How certain is the regime classification?
   - Based on indicator agreement

4. **Regime Change Detection**
   - Alert when regime changes (e.g., BULL → SIDEWAYS)
   - Critical for strategy adjustment

#### Classification Logic

```python
class RegimeClassification(Enum):
    BULL = "BULL"
    BEAR = "BEAR"
    SIDEWAYS = "SIDEWAYS"
    VOLATILE = "VOLATILE"

class RegimeAgent(BaseAgent):
    async def classify_regime(
        self, 
        ohlc_data: pd.DataFrame,
        sentiment: SentimentOutput
    ) -> RegimeOutput:
        """
        Regime classification algorithm
        """
        # Calculate all indicators
        indicators = self._calculate_indicators(ohlc_data)
        
        # Apply decision tree
        regime = self._apply_decision_tree(indicators, sentiment)
        
        return regime
    
    def _apply_decision_tree(
        self, 
        indicators: Dict, 
        sentiment: SentimentOutput
    ) -> str:
        """
        Decision Tree for Regime Classification
        
        Rules (in priority order):
        """
        price = indicators['close']
        ema_9 = indicators['ema_9']
        ema_21 = indicators['ema_21']
        ema_50 = indicators['ema_50']
        ema_200 = indicators['ema_200']
        adx = indicators['adx']
        rsi = indicators['rsi']
        vix = indicators['vix']
        bb_width = indicators['bb_width']
        
        # VOLATILE Regime (highest priority)
        if vix > 25 or adx < 15:
            if bb_width > indicators['bb_width_avg'] * 1.5:
                return RegimeClassification.VOLATILE
        
        # BULL Regime
        if (price > ema_9 > ema_21 > ema_50 > ema_200 and
            adx > 25 and
            rsi > 50 and
            sentiment.sentiment_score > 0):
            return RegimeClassification.BULL
        
        # BEAR Regime
        if (price < ema_9 < ema_21 < ema_50 < ema_200 and
            adx > 25 and
            rsi < 50 and
            sentiment.sentiment_score < 0):
            return RegimeClassification.BEAR
        
        # SIDEWAYS Regime (default)
        if adx < 25 and 15 < vix < 20:
            return RegimeClassification.SIDEWAYS
        
        # Fallback: Use last known regime
        return self.last_regime
```

#### Output Specifications

```python
class RegimeOutput(BaseModel):
    timestamp: datetime
    regime: RegimeClassification
    confidence: float                   # 0.0 to 1.0
    indicators: Dict[str, float]        # All indicator values
    regime_duration: int                # Minutes in current regime
    previous_regime: str | None
    regime_changed: bool                # True if regime just changed
    
    # Sector-specific regimes (NEW in v4.0)
    sector_regimes: Dict[str, str] = {
        "banking": "BULL",
        "it": "SIDEWAYS",
        "auto": "BEAR",
        "pharma": "BULL",
        "metals": "VOLATILE",
        # ... all sectors
    }
```

#### Performance Metrics

- **Execution Time:** < 3 seconds
- **Accuracy Target:** >75% (regime should hold for >15 minutes)
- **Caching:** 180 seconds

#### Integration Points

**Upstream Dependencies:**
- Market Data Service (OHLC data)
- Sentiment Agent (sentiment score)

**Downstream Consumers:**
- Scanner Agent (filters opportunities by regime)
- Strategy Agent (selects strategies based on regime)
- Risk Agent (adjusts risk limits by regime)
- Portfolio Agent (regime-aware rebalancing)

---

### 3.3 SCANNER AGENT (NEW)

**Role:** Multi-asset opportunity scanner - scans Nifty 500 universe for trading setups.

#### Responsibilities

1. **Universe Management**
   - Maintain list of 200+ F&O eligible stocks
   - Filter by liquidity (> 0.6 score)
   - Filter by volatility (< 80th percentile)

2. **Technical Setup Detection**
   - Breakout patterns
   - Support/resistance levels
   - RSI divergence
   - VWAP mean reversion
   - Volume surges

3. **Opportunity Scoring**
   - Score each setup (0.0 to 1.0)
   - Rank by probability of success
   - Return top 10 opportunities

4. **Sector Rotation Analysis**
   - Identify hot sectors (outperforming)
   - Flag cold sectors (underperforming)
   - Suggest sector-specific strategies

#### Scanning Algorithm

```python
class ScannerAgent(BaseAgent):
    async def scan_universe(
        self,
        asset_class: str,
        regime: RegimeOutput
    ) -> ScannerOutput:
        """
        Scan trading universe for opportunities
        """
        # Step 1: Get active universe
        instruments = self.universe_manager.get_active_universe(
            asset_class=asset_class,
            min_liquidity=0.6,
            max_volatility=80.0
        )
        
        opportunities = []
        
        # Step 2: Scan each instrument
        for instrument in instruments:
            # Fetch OHLC + indicators
            data = await self._fetch_instrument_data(instrument)
            
            # Detect technical setups
            setups = self._detect_setups(data, regime)
            
            if setups:
                # Score opportunity
                score = self._calculate_score(
                    instrument, 
                    data, 
                    setups, 
                    regime
                )
                
                if score > 0.6:  # Threshold
                    opportunities.append({
                        "symbol": instrument.symbol,
                        "security_id": instrument.security_id,
                        "sector": instrument.sector,
                        "setup_type": setups[0],  # Primary setup
                        "score": score,
                        "entry_price": data['close'].iloc[-1],
                        "stop_loss": self._calculate_stop(data, setups[0]),
                        "target": self._calculate_target(data, setups[0]),
                        "risk_reward": self._calculate_rr(data, setups[0])
                    })
        
        # Step 3: Rank opportunities
        opportunities.sort(key=lambda x: x['score'], reverse=True)
        
        # Step 4: Return top 10
        return ScannerOutput(
            timestamp=datetime.now(),
            regime=regime.regime,
            total_scanned=len(instruments),
            opportunities=opportunities[:10],
            sector_summary=self._analyze_sectors(opportunities)
        )
    
    def _detect_setups(
        self, 
        data: pd.DataFrame, 
        regime: RegimeOutput
    ) -> List[str]:
        """
        Detect technical setups
        
        Setup Types:
        - BREAKOUT: Price breaks resistance with volume
        - BREAKDOWN: Price breaks support with volume
        - PULLBACK: Trend pullback to support/resistance
        - REVERSAL: RSI divergence + price action
        - SQUEEZE: Bollinger Band squeeze (volatility contraction)
        """
        setups = []
        
        # Breakout detection
        if self._is_breakout(data, regime):
            setups.append("BREAKOUT")
        
        # Pullback detection
        if self._is_pullback(data, regime):
            setups.append("PULLBACK")
        
        # Squeeze detection
        if self._is_squeeze(data):
            setups.append("SQUEEZE")
        
        return setups
```

#### Output Specifications

```python
class OpportunitySignal(BaseModel):
    symbol: str
    security_id: str
    sector: str
    setup_type: str                     # BREAKOUT, PULLBACK, etc.
    score: float                        # 0.0 to 1.0
    entry_price: float
    stop_loss: float
    target: float
    risk_reward: float
    
    # Additional metadata
    liquidity_score: float
    volatility_percentile: float
    volume_ratio: float                 # Current vol / Avg vol

class ScannerOutput(BaseModel):
    timestamp: datetime
    regime: RegimeClassification
    total_scanned: int
    opportunities: List[OpportunitySignal]  # Top 10
    
    # Sector analysis
    sector_summary: Dict[str, Dict] = {
        "banking": {
            "regime": "BULL",
            "opportunities": 3,
            "avg_score": 0.75
        },
        # ... other sectors
    }
```

#### Performance Metrics

- **Execution Time:** < 10 seconds (scanning 200+ stocks)
- **Concurrency:** Parallel processing (10 threads)
- **Cache:** Individual stock data cached for 60 seconds
- **Success Rate:** >60% of flagged opportunities should be profitable

#### Integration Points

**Upstream Dependencies:**
- Regime Agent (current regime)
- Market Data Service (real-time quotes + OHLC)

**Downstream Consumers:**
- Strategy Agent (uses top opportunities for trade generation)

---

### 3.4 STRATEGY AGENT

**Role:** Trade signal generator - selects and executes 18 different strategies based on market conditions.

#### Responsibilities

1. **Strategy Selection**
   - Match regime to appropriate strategies
   - Filter strategies by asset class
   - Consider capital allocation limits

2. **Signal Generation**
   - Execute strategy logic
   - Calculate entry/exit points
   - Determine position size (preliminary)
   - Compute Greeks (for options)

3. **Multi-Leg Trade Construction**
   - Build complex strategies (Iron Condor, Butterfly, etc.)
   - Ensure leg prices are feasible
   - Calculate net credit/debit

4. **Signal Validation**
   - Verify minimum risk-reward ratio (>2:1)
   - Check win probability (>55%)
   - Ensure sufficient liquidity

#### Strategy Selection Matrix

```python
class StrategyAgent(BaseAgent):
    """
    Strategy Selection Logic
    """
    STRATEGY_MATRIX = {
        # Regime: (VIX Range, Strategies)
        "BULL": {
            (0, 15): ["ALPHA_ORB_001", "ALPHA_VWAP_002"],
            (15, 25): ["ALPHA_BCS_004", "ALPHA_TREND_003"],
            (25, 100): ["ALPHA_STRADDLE_011"]
        },
        "BEAR": {
            (0, 25): ["ALPHA_BPS_005", "ALPHA_TREND_003"],
            (25, 100): ["ALPHA_BPS_005", "ALPHA_PORT_014"]
        },
        "SIDEWAYS": {
            (0, 15): ["ALPHA_IRON_008", "ALPHA_CALENDAR_007"],
            (15, 25): ["ALPHA_IRON_008", "ALPHA_BUTTERFLY_009"],
            (25, 100): ["ALPHA_STRANGLE_010"]
        },
        "VOLATILE": {
            (0, 100): ["ALPHA_DELTA_013", "ALPHA_PORT_014"]
        }
    }
    
    async def select_strategies(
        self,
        regime: RegimeOutput,
        vix: float,
        opportunities: ScannerOutput,
        portfolio: PortfolioSnapshot
    ) -> List[str]:
        """
        Select appropriate strategies for current conditions
        """
        # Get strategies for regime + VIX
        strategies = self._lookup_strategies(regime.regime, vix)
        
        # Filter by capital availability
        strategies = self._filter_by_capital(
            strategies, 
            portfolio.available_capital
        )
        
        # Filter by existing exposure
        strategies = self._filter_by_exposure(
            strategies,
            portfolio.open_positions
        )
        
        return strategies
    
    async def generate_signals(
        self,
        strategies: List[str],
        opportunities: ScannerOutput,
        market_data: Dict
    ) -> List[Signal]:
        """
        Generate trade signals for selected strategies
        """
        signals = []
        
        for strategy_id in strategies:
            # Load strategy implementation
            strategy = self.strategies[strategy_id]
            
            # Generate signal
            signal = await strategy.generate_signal(
                regime=market_data['regime'],
                opportunities=opportunities.opportunities,
                vix=market_data['vix'],
                option_chain=market_data.get('option_chain')
            )
            
            if signal:
                # Validate signal
                if self._validate_signal(signal):
                    signals.append(signal)
        
        return signals
```

#### Signal Output Specifications

```python
class LegSignal(BaseModel):
    """Single leg of a trade (for multi-leg strategies)"""
    symbol: str                         # NIFTY26FEB2522500CE
    security_id: str                    # DhanHQ security ID
    side: str                           # BUY or SELL
    quantity: int
    strike_price: float | None          # For options
    option_type: str | None             # CE or PE
    expiry_date: str | None
    limit_price: float                  # Entry price
    stop_loss: float
    take_profit: float

class Signal(BaseModel):
    signal_id: str                      # UUID
    timestamp: datetime
    strategy_id: str                    # ALPHA_ORB_001, etc.
    strategy_name: str
    
    # Asset details
    underlying: str                     # NIFTY, BANKNIFTY, RELIANCE
    asset_class: str                    # INDEX_OPTIONS, STOCK_FUTURES
    
    # Trade structure
    legs: List[LegSignal]               # 1-4 legs
    trade_type: str                     # DIRECTIONAL, SPREAD, HEDGE
    
    # Entry/Exit
    entry_reason: str                   # "ORB breakout at 22,500"
    stop_loss_reason: str
    take_profit_reason: str
    
    # Risk metrics
    risk_reward_ratio: float
    max_loss: float
    max_profit: float
    win_probability: float              # Backtested probability
    
    # Options-specific
    net_credit_debit: float | None      # For spreads
    portfolio_greeks: Dict | None = {
        "delta": 0.55,
        "gamma": 0.0012,
        "theta": -8.5,
        "vega": 15.2
    }
    
    # Metadata
    regime: RegimeClassification
    confidence: float                   # 0.0 to 1.0
    holding_period_estimate: int        # Minutes
```

#### Performance Metrics

- **Execution Time:** < 2 seconds per strategy
- **Signal Quality Target:**
  - Win Rate: >55%
  - Risk-Reward: >2:1
  - Sharpe Ratio: >1.5 (backtested)

#### Integration Points

**Upstream Dependencies:**
- Regime Agent (market regime)
- Scanner Agent (opportunities)
- Market Data Service (option chain, quotes)

**Downstream Consumers:**
- Risk Agent (for approval/rejection)
- Execution Agent (for order placement)

---

### 3.5 RISK AGENT

**Role:** Risk management and kill switch - the guardian that prevents catastrophic losses.

#### Responsibilities

1. **Position Sizing**
   - Calculate optimal quantity based on:
     - Account size
     - Risk per trade (default: 2%)
     - Strategy win rate
     - Current portfolio exposure

2. **Pre-Trade Risk Checks**
   - Verify signal meets risk criteria
   - Check portfolio-level limits
   - Validate Greeks exposure
   - Ensure sufficient margin

3. **Kill Switch Monitoring**
   - Daily loss limit: -5% of capital
   - Consecutive losses: 5 trades
   - Portfolio drawdown: -10% from peak
   - Greek limits exceeded

4. **Dynamic Risk Adjustment**
   - Reduce position sizes in volatile regimes
   - Increase sizes after winning streaks
   - Hedge portfolio when risk accumulates

#### Risk Calculation Logic

```python
class RiskAgent(BaseAgent):
    """
    Risk management with multiple layers of protection
    """
    
    async def validate_signal(
        self,
        signal: Signal,
        portfolio: PortfolioSnapshot
    ) -> RiskDecision:
        """
        Multi-stage risk validation
        
        Returns: APPROVED, REJECTED, or MODIFIED
        """
        # Stage 1: Pre-trade checks
        checks = {
            "capital_available": self._check_capital(signal, portfolio),
            "position_limits": self._check_position_limits(signal, portfolio),
            "correlation": self._check_correlation(signal, portfolio),
            "greeks_limits": self._check_greeks(signal, portfolio),
            "risk_reward": signal.risk_reward_ratio >= 2.0,
            "win_probability": signal.win_probability >= 0.55
        }
        
        if not all(checks.values()):
            return RiskDecision(
                decision="REJECTED",
                reason=f"Failed checks: {[k for k,v in checks.items() if not v]}",
                signal_id=signal.signal_id
            )
        
        # Stage 2: Calculate position size
        position_size = self._calculate_position_size(signal, portfolio)
        
        if position_size == 0:
            return RiskDecision(
                decision="REJECTED",
                reason="Position size calculated as 0 (insufficient capital)",
                signal_id=signal.signal_id
            )
        
        # Stage 3: Check kill switch conditions
        if self._is_kill_switch_active(portfolio):
            return RiskDecision(
                decision="REJECTED",
                reason="Kill switch ACTIVE - trading suspended",
                signal_id=signal.signal_id,
                kill_switch_active=True
            )
        
        # Stage 4: Approve with modifications
        modified_signal = self._apply_modifications(signal, position_size)
        
        return RiskDecision(
            decision="APPROVED",
            signal_id=signal.signal_id,
            modified_signal=modified_signal,
            approved_quantity=position_size,
            risk_metrics=self._calculate_risk_metrics(modified_signal)
        )
    
    def _calculate_position_size(
        self,
        signal: Signal,
        portfolio: PortfolioSnapshot
    ) -> int:
        """
        Kelly Criterion-adjusted position sizing
        
        Formula:
        Position Size = (Capital * Risk_Per_Trade) / Stop_Loss_Distance
        
        Adjustments:
        - Reduce by 50% if VIX > 25
        - Reduce by 30% if portfolio drawdown > 5%
        - Max 3 positions per strategy
        - Max 10 total positions
        """
        # Base calculation
        capital = portfolio.total_capital
        risk_per_trade = 0.02  # 2%
        
        # Calculate risk amount
        risk_amount = capital * risk_per_trade
        
        # Calculate stop loss distance per lot
        if len(signal.legs) == 1:
            # Single leg trade
            stop_distance = abs(
                signal.legs[0].limit_price - signal.legs[0].stop_loss
            )
        else:
            # Multi-leg trade
            stop_distance = signal.max_loss / signal.legs[0].quantity
        
        # Base position size
        position_size = int(risk_amount / (stop_distance * signal.legs[0].quantity))
        
        # Apply adjustments
        if portfolio.vix > 25:
            position_size = int(position_size * 0.5)
        
        if portfolio.drawdown_pct > 5:
            position_size = int(position_size * 0.7)
        
        # Enforce limits
        position_size = min(position_size, 3)  # Max 3 lots
        
        return position_size
    
    def _is_kill_switch_active(
        self,
        portfolio: PortfolioSnapshot
    ) -> bool:
        """
        Kill switch conditions
        """
        # Daily loss limit: -5%
        if portfolio.daily_pnl_pct < -5.0:
            self.logger.critical("KILL SWITCH: Daily loss > 5%")
            return True
        
        # Portfolio drawdown: -10%
        if portfolio.drawdown_pct > 10.0:
            self.logger.critical("KILL SWITCH: Drawdown > 10%")
            return True
        
        # Consecutive losses: 5
        if portfolio.consecutive_losses >= 5:
            self.logger.critical("KILL SWITCH: 5 consecutive losses")
            return True
        
        # Portfolio delta exceeds limits
        if abs(portfolio.portfolio_delta) > 100:
            self.logger.critical("KILL SWITCH: Portfolio delta > 100")
            return True
        
        return False
```

#### Output Specifications

```python
class RiskDecision(BaseModel):
    timestamp: datetime
    decision: str                       # APPROVED, REJECTED, MODIFIED
    signal_id: str
    reason: str | None
    
    # If approved
    approved_quantity: int | None
    modified_signal: Signal | None
    
    # Risk metrics
    risk_metrics: Dict | None = {
        "position_risk_amount": 2000,   # ₹2,000 at risk
        "position_risk_pct": 0.2,       # 0.2% of capital
        "portfolio_risk_pct": 3.5,      # Total portfolio risk
        "expected_value": 1500,         # Expected profit
        "required_margin": 50000        # Margin required
    }
    
    # Kill switch
    kill_switch_active: bool = False
    kill_switch_reason: str | None
```

#### Performance Metrics

- **Execution Time:** < 1 second
- **False Positive Rate:** < 10% (valid signals rejected)
- **Kill Switch Activations:** < 2 per month (target)

#### Integration Points

**Upstream Dependencies:**
- Strategy Agent (signals to validate)
- Portfolio Agent (portfolio state)

**Downstream Consumers:**
- Execution Agent (approved signals)
- Portfolio Agent (risk metrics for monitoring)

---

### 3.6 EXECUTION AGENT (NEW)

**Role:** Smart order execution - places orders efficiently with slippage minimization.

#### Responsibilities

1. **Order Placement**
   - Convert approved signals to broker orders
   - Handle single-leg and multi-leg trades
   - Support MARKET, LIMIT, SL, SL-M order types

2. **Slippage Management**
   - Use LIMIT orders with intelligent pricing
   - Retry logic if order not filled
   - Cancel and retry with adjusted price

3. **Order Status Tracking**
   - Poll DhanHQ for order status
   - Handle partial fills
   - Report fills to Portfolio Agent

4. **Error Handling**
   - Retry on transient errors
   - Alert on critical errors (insufficient margin, symbol not found)
   - Rollback multi-leg trades if any leg fails

#### Execution Logic

```python
class ExecutionAgent(BaseAgent):
    """
    Intelligent order execution with retry logic
    """
    
    async def execute_signal(
        self,
        signal: Signal,
        risk_decision: RiskDecision
    ) -> ExecutionResult:
        """
        Execute approved trade signal
        """
        if risk_decision.decision != "APPROVED":
            return ExecutionResult(
                status="SKIPPED",
                reason=risk_decision.reason
            )
        
        # Use modified signal if Risk Agent modified it
        signal = risk_decision.modified_signal or signal
        
        # Execute based on number of legs
        if len(signal.legs) == 1:
            result = await self._execute_single_leg(signal)
        else:
            result = await self._execute_multi_leg(signal)
        
        return result
    
    async def _execute_single_leg(
        self,
        signal: Signal
    ) -> ExecutionResult:
        """
        Execute single-leg trade
        """
        leg = signal.legs[0]
        
        # Place order with DhanHQ
        order_id = await self.dhan_client.place_order(
            security_id=leg.security_id,
            exchange=ExchangeSegment.NSE_FNO,
            transaction_type=TransactionType.BUY if leg.side == "BUY" else TransactionType.SELL,
            quantity=leg.quantity,
            order_type=OrderType.LIMIT,
            price=leg.limit_price,
            product_type=ProductType.INTRADAY,
            validity=Validity.DAY
        )
        
        # Wait for order to fill (with timeout)
        fill_status = await self._wait_for_fill(order_id, timeout=60)
        
        if fill_status.status == "FILLED":
            return ExecutionResult(
                status="SUCCESS",
                order_ids=[order_id],
                fill_price=fill_status.fill_price,
                fill_time=fill_status.fill_time
            )
        
        elif fill_status.status == "PENDING":
            # Cancel and retry with market price
            await self.dhan_client.cancel_order(order_id)
            
            # Retry with market order
            market_order_id = await self.dhan_client.place_order(
                security_id=leg.security_id,
                exchange=ExchangeSegment.NSE_FNO,
                transaction_type=TransactionType.BUY if leg.side == "BUY" else TransactionType.SELL,
                quantity=leg.quantity,
                order_type=OrderType.MARKET,
                product_type=ProductType.INTRADAY
            )
            
            # Wait for market order fill
            market_fill = await self._wait_for_fill(market_order_id, timeout=30)
            
            return ExecutionResult(
                status="SUCCESS",
                order_ids=[market_order_id],
                fill_price=market_fill.fill_price,
                fill_time=market_fill.fill_time,
                slippage=abs(market_fill.fill_price - leg.limit_price)
            )
        
        else:
            return ExecutionResult(
                status="FAILED",
                reason=fill_status.reason
            )
    
    async def _execute_multi_leg(
        self,
        signal: Signal
    ) -> ExecutionResult:
        """
        Execute multi-leg trade (Iron Condor, Spread, etc.)
        
        Strategy:
        - Place all legs simultaneously
        - Monitor all order statuses
        - If any leg fails, cancel all and retry
        - Max 3 retry attempts
        """
        order_ids = []
        fill_results = []
        
        # Place all legs
        for leg in signal.legs:
            order_id = await self.dhan_client.place_order(
                security_id=leg.security_id,
                exchange=ExchangeSegment.NSE_FNO,
                transaction_type=TransactionType.BUY if leg.side == "BUY" else TransactionType.SELL,
                quantity=leg.quantity,
                order_type=OrderType.LIMIT,
                price=leg.limit_price,
                product_type=ProductType.INTRADAY
            )
            order_ids.append(order_id)
        
        # Wait for all legs to fill (60 seconds)
        for order_id in order_ids:
            fill_status = await self._wait_for_fill(order_id, timeout=60)
            fill_results.append(fill_status)
        
        # Check if all legs filled
        all_filled = all(f.status == "FILLED" for f in fill_results)
        
        if all_filled:
            return ExecutionResult(
                status="SUCCESS",
                order_ids=order_ids,
                fill_results=fill_results
            )
        
        else:
            # Cancel all unfilled orders
            for order_id, fill in zip(order_ids, fill_results):
                if fill.status == "PENDING":
                    await self.dhan_client.cancel_order(order_id)
            
            return ExecutionResult(
                status="FAILED",
                reason="Multi-leg trade partially filled - all legs cancelled"
            )
```

#### Output Specifications

```python
class ExecutionResult(BaseModel):
    timestamp: datetime
    status: str                         # SUCCESS, FAILED, SKIPPED
    signal_id: str
    
    # Order details
    order_ids: List[str]                # Broker order IDs
    fill_results: List[Dict] | None     # Fill price, time for each leg
    
    # Execution quality
    slippage: float = 0.0               # Actual - Expected price
    execution_time: int                 # Milliseconds
    
    # Error handling
    reason: str | None                  # If failed
    retry_count: int = 0
```

#### Performance Metrics

- **Execution Time:** < 3 seconds for single-leg, < 10 seconds for multi-leg
- **Success Rate:** >95% (orders filled)
- **Slippage:** < 0.5% of entry price (target)

#### Integration Points

**Upstream Dependencies:**
- Risk Agent (approved signals)
- DhanHQ API (order placement)

**Downstream Consumers:**
- Paper Agent (if MODE=PAPER)
- Portfolio Agent (trade logging)

---

### 3.7 PAPER AGENT

**Role:** Simulation and backtesting - test strategies without real money.

#### Responsibilities

1. **Paper Trading Simulation**
   - Simulate order fills (no real broker interaction)
   - Apply realistic slippage model
   - Track simulated P&L

2. **Backtesting Engine**
   - Run strategies on historical data
   - Calculate performance metrics
   - Generate backtest reports

3. **Strategy Validation**
   - Validate new strategies before live deployment
   - Compare live vs paper performance
   - Detect strategy degradation

#### Simulation Logic

```python
class PaperAgent(BaseAgent):
    """
    Paper trading simulator
    """
    
    async def simulate_execution(
        self,
        signal: Signal,
        risk_decision: RiskDecision
    ) -> PaperExecutionResult:
        """
        Simulate trade execution (no real orders)
        """
        if risk_decision.decision != "APPROVED":
            return PaperExecutionResult(status="SKIPPED")
        
        # Get current market price
        current_prices = await self._fetch_current_prices(signal)
        
        # Simulate fills with slippage
        fills = []
        for leg in signal.legs:
            # Apply slippage model
            slippage_pct = self._calculate_slippage(leg, current_prices)
            
            if leg.side == "BUY":
                fill_price = leg.limit_price * (1 + slippage_pct)
            else:
                fill_price = leg.limit_price * (1 - slippage_pct)
            
            fills.append({
                "leg": leg,
                "fill_price": fill_price,
                "slippage": abs(fill_price - leg.limit_price)
            })
        
        # Log to SQLite database
        trade_id = await self._log_paper_trade(signal, fills)
        
        return PaperExecutionResult(
            status="SUCCESS",
            trade_id=trade_id,
            fills=fills,
            simulated=True
        )
    
    def _calculate_slippage(
        self,
        leg: LegSignal,
        current_prices: Dict
    ) -> float:
        """
        Realistic slippage model
        
        Factors:
        - Market order: 0.1-0.3% slippage
        - Limit order: 0-0.1% slippage (may not fill)
        - Volatility: Higher VIX = higher slippage
        - Liquidity: Lower liquidity = higher slippage
        """
        base_slippage = 0.001  # 0.1%
        
        # Adjust for volatility
        if self.current_vix > 20:
            base_slippage *= 1.5
        
        # Adjust for liquidity
        if leg.liquidity_score < 0.7:
            base_slippage *= 1.3
        
        return base_slippage
```

#### Performance Metrics

- **Accuracy:** Simulated P&L should be within 10% of live P&L
- **Execution Time:** < 1 second

#### Integration Points

**Upstream Dependencies:**
- Execution Agent (signals to simulate)
- Market Data Service (current prices)

**Downstream Consumers:**
- Portfolio Agent (simulated trades logged)

---

### 3.8 PORTFOLIO AGENT (NEW)

**Role:** Portfolio-level monitoring and risk management.

#### Responsibilities

1. **Portfolio Aggregation**
   - Aggregate all open positions
   - Calculate net Greeks (Delta, Gamma, Theta, Vega)
   - Compute total P&L (realized + unrealized)

2. **Risk Monitoring**
   - Portfolio-level risk limits
   - Correlation analysis
   - Value at Risk (VaR 95%)

3. **Hedging Recommendations**
   - Suggest hedges when risk accumulates
   - Rebalance portfolio Greeks

4. **Performance Tracking**
   - Daily/Weekly/Monthly returns
   - Sharpe ratio, Sortino ratio
   - Maximum drawdown tracking

#### Portfolio Calculation Logic

```python
class PortfolioAgent(BaseAgent):
    """
    Portfolio-level monitoring and management
    """
    
    async def calculate_portfolio_state(
        self,
        open_positions: List[Trade],
        market_data: Dict
    ) -> PortfolioSnapshot:
        """
        Calculate real-time portfolio state
        """
        # Calculate P&L for each position
        position_pnls = []
        for position in open_positions:
            pnl = await self._calculate_position_pnl(position, market_data)
            position_pnls.append(pnl)
        
        # Aggregate Greeks
        portfolio_greeks = self._aggregate_greeks(open_positions, market_data)
        
        # Calculate risk metrics
        var_95 = self._calculate_var(open_positions, market_data)
        
        # Performance metrics
        sharpe = self._calculate_sharpe_ratio(position_pnls)
        
        return PortfolioSnapshot(
            timestamp=datetime.now(),
            total_capital=self.config['total_capital'],
            allocated_capital=sum(p.capital_used for p in open_positions),
            available_capital=self._calculate_available_capital(),
            open_positions=len(open_positions),
            total_pnl=sum(pnl['current_pnl'] for pnl in position_pnls),
            daily_pnl=self._calculate_daily_pnl(position_pnls),
            portfolio_delta=portfolio_greeks['delta'],
            portfolio_gamma=portfolio_greeks['gamma'],
            portfolio_theta=portfolio_greeks['theta'],
            portfolio_vega=portfolio_greeks['vega'],
            var_95=var_95,
            sharpe_ratio=sharpe,
            max_drawdown_pct=self._calculate_drawdown()
        )
    
    def _aggregate_greeks(
        self,
        positions: List[Trade],
        market_data: Dict
    ) -> Dict[str, float]:
        """
        Aggregate portfolio Greeks
        """
        total_delta = 0.0
        total_gamma = 0.0
        total_theta = 0.0
        total_vega = 0.0
        
        for position in positions:
            if position.instrument_type == "OPTION":
                # Fetch current Greeks
                greeks = await self._get_option_greeks(
                    position.symbol,
                    market_data
                )
                
                # Multiply by quantity and direction
                multiplier = position.quantity * (1 if position.side == "BUY" else -1)
                
                total_delta += greeks['delta'] * multiplier
                total_gamma += greeks['gamma'] * multiplier
                total_theta += greeks['theta'] * multiplier
                total_vega += greeks['vega'] * multiplier
        
        return {
            "delta": total_delta,
            "gamma": total_gamma,
            "theta": total_theta,
            "vega": total_vega
        }
```

#### Output Specifications

```python
class PortfolioSnapshot(BaseModel):
    timestamp: datetime
    
    # Capital
    total_capital: float
    allocated_capital: float
    available_capital: float
    
    # Positions
    open_positions: int
    total_pnl: float
    daily_pnl: float
    daily_pnl_pct: float
    
    # Greeks
    portfolio_delta: float
    portfolio_gamma: float
    portfolio_theta: float
    portfolio_vega: float
    
    # Risk metrics
    var_95: float                       # Value at Risk (95% confidence)
    max_drawdown_pct: float
    consecutive_losses: int
    
    # Performance
    sharpe_ratio: float
    win_rate: float
    profit_factor: float
    
    # Market context
    vix: float
    regime: RegimeClassification
```

#### Performance Metrics

- **Update Frequency:** Every 15 minutes + on every trade
- **Execution Time:** < 2 seconds
- **Accuracy:** Portfolio Greeks should match broker calculations

#### Integration Points

**Upstream Dependencies:**
- All agents (trades, positions)
- Market Data Service (current prices, Greeks)

**Downstream Consumers:**
- Risk Agent (portfolio state for risk checks)
- Strategy Agent (capital availability)
- Dashboard (real-time portfolio display)

---

## 4. AGENT ORCHESTRATION FRAMEWORK

### 4.1 Execution Flow (Every 3 Minutes)

```python
class AgenticOrchestrator:
    """
    Main orchestrator that coordinates all agents
    
    Execution cycle: Every 3 minutes (9:15 AM - 3:30 PM IST)
    """
    
    async def execute_trading_cycle(self):
        """
        One complete trading cycle
        
        Duration: ~15-20 seconds total
        """
        cycle_start = datetime.now()
        
        try:
            # ============================================
            # PHASE 1: SENSING (Parallel Execution)
            # Duration: ~5-8 seconds
            # ============================================
            sensing_tasks = [
                self.sentiment_agent.analyze(),      # ~5s
                self.regime_agent.classify_regime(), # ~3s
                self.scanner_agent.scan_universe()   # ~10s (parallel)
            ]
            
            sentiment, regime, opportunities = await asyncio.gather(
                *sensing_tasks,
                return_exceptions=True
            )
            
            # Handle failures gracefully
            if isinstance(sentiment, Exception):
                sentiment = self._get_cached_sentiment()
            if isinstance(regime, Exception):
                regime = self._get_cached_regime()
            if isinstance(opportunities, Exception):
                opportunities = []
            
            # ============================================
            # PHASE 2: DECISION MAKING (Sequential)
            # Duration: ~3-5 seconds
            # ============================================
            
            # Step 1: Select strategies based on regime
            strategies = await self.strategy_agent.select_strategies(
                regime=regime,
                vix=await self._get_vix(),
                opportunities=opportunities,
                portfolio=await self.portfolio_agent.get_snapshot()
            )
            
            # Step 2: Generate signals for selected strategies
            signals = await self.strategy_agent.generate_signals(
                strategies=strategies,
                opportunities=opportunities,
                market_data={
                    'regime': regime,
                    'sentiment': sentiment,
                    'vix': await self._get_vix()
                }
            )
            
            # ============================================
            # PHASE 3: RISK VALIDATION (Sequential)
            # Duration: ~1-2 seconds
            # ============================================
            approved_signals = []
            
            for signal in signals:
                # Get current portfolio state
                portfolio = await self.portfolio_agent.get_snapshot()
                
                # Risk validation
                risk_decision = await self.risk_agent.validate_signal(
                    signal=signal,
                    portfolio=portfolio
                )
                
                if risk_decision.decision == "APPROVED":
                    approved_signals.append(risk_decision)
                else:
                    self.logger.info(
                        f"Signal {signal.signal_id} rejected: {risk_decision.reason}"
                    )
            
            # ============================================
            # PHASE 4: EXECUTION (Parallel)
            # Duration: ~3-10 seconds
            # ============================================
            if approved_signals:
                execution_tasks = [
                    self.execution_agent.execute_signal(signal, risk_decision)
                    for signal, risk_decision in zip(signals, approved_signals)
                ]
                
                execution_results = await asyncio.gather(
                    *execution_tasks,
                    return_exceptions=True
                )
                
                # Log results
                for result in execution_results:
                    if isinstance(result, Exception):
                        self.logger.error(f"Execution failed: {result}")
                    elif result.status == "SUCCESS":
                        self.logger.info(f"Trade executed: {result.order_ids}")
                    else:
                        self.logger.warning(f"Execution failed: {result.reason}")
            
            # ============================================
            # PHASE 5: PORTFOLIO UPDATE
            # Duration: ~1-2 seconds
            # ============================================
            await self.portfolio_agent.refresh_snapshot()
            
            # ============================================
            # PHASE 6: MONITORING & ALERTS
            # Duration: ~1 second
            # ============================================
            await self._check_alerts()
            await self._log_cycle_metrics(cycle_start)
            
        except Exception as e:
            self.logger.critical(f"Trading cycle failed: {e}")
            await self._handle_critical_error(e)
    
    async def _check_alerts(self):
        """Check for alert conditions"""
        portfolio = await self.portfolio_agent.get_snapshot()
        
        # Daily loss alert
        if portfolio.daily_pnl_pct < -3.0:
            await self.notification_service.send_alert(
                type="WARNING",
                message=f"Daily loss: {portfolio.daily_pnl_pct:.2f}%"
            )
        
        # Kill switch alert
        if await self.risk_agent._is_kill_switch_active(portfolio):
            await self.notification_service.send_alert(
                type="CRITICAL",
                message="KILL SWITCH ACTIVATED - Trading suspended"
            )
```

### 4.2 Agent Communication Patterns

#### Pattern 1: Request-Response (Synchronous)

```python
# Strategy Agent requests risk validation
signal = await strategy_agent.generate_signal(...)
risk_decision = await risk_agent.validate_signal(signal)

if risk_decision.decision == "APPROVED":
    execution_result = await execution_agent.execute_signal(signal)
```

#### Pattern 2: Event Broadcasting (Asynchronous)

```python
# Regime Agent broadcasts regime change
await event_bus.publish(
    event="REGIME_CHANGED",
    data={
        "old_regime": "BULL",
        "new_regime": "SIDEWAYS",
        "timestamp": datetime.now()
    }
)

# Multiple agents subscribe to this event
@event_bus.subscribe("REGIME_CHANGED")
async def on_regime_change(data):
    # Strategy Agent adjusts active strategies
    await strategy_agent.reload_strategies(data['new_regime'])
    
    # Risk Agent adjusts risk limits
    await risk_agent.adjust_limits(data['new_regime'])
```

#### Pattern 3: Shared State (via Portfolio Agent)

```python
# All agents can query portfolio state
portfolio = await portfolio_agent.get_snapshot()

# Agents use this for decision-making
if portfolio.available_capital < 100000:
    # Don't generate new signals
    return []
```

### 4.3 Error Handling & Circuit Breakers

```python
class CircuitBreaker:
    """
    Circuit breaker pattern for agent failures
    """
    def __init__(self, failure_threshold=3, timeout=300):
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.timeout = timeout  # seconds
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
        self.last_failure_time = None
    
    async def call(self, func, *args, **kwargs):
        """Execute function with circuit breaker protection"""
        
        if self.state == "OPEN":
            # Check if timeout has passed
            if (datetime.now() - self.last_failure_time).seconds > self.timeout:
                self.state = "HALF_OPEN"
            else:
                raise Exception("Circuit breaker OPEN - agent unavailable")
        
        try:
            result = await func(*args, **kwargs)
            
            # Success - reset failure count
            if self.state == "HALF_OPEN":
                self.state = "CLOSED"
            self.failure_count = 0
            
            return result
        
        except Exception as e:
            self.failure_count += 1
            self.last_failure_time = datetime.now()
            
            if self.failure_count >= self.failure_threshold:
                self.state = "OPEN"
                self.logger.error(f"Circuit breaker OPEN for {func.__name__}")
            
            raise e

# Usage
sentiment_circuit = CircuitBreaker(failure_threshold=3)

async def get_sentiment():
    return await sentiment_circuit.call(
        sentiment_agent.analyze
    )
```

---

## 5. COMMUNICATION PROTOCOLS

### 5.1 Inter-Agent Messaging

All agents communicate via **typed messages** using Pydantic models:

```python
class AgentMessage(BaseModel):
    """Base class for all agent messages"""
    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=datetime.now)
    sender: str                         # Agent name
    recipient: str                      # Agent name or "BROADCAST"
    message_type: str
    payload: Dict

# Example: Regime Agent → Strategy Agent
regime_message = AgentMessage(
    sender="RegimeAgent",
    recipient="StrategyAgent",
    message_type="REGIME_UPDATE",
    payload={
        "regime": "SIDEWAYS",
        "confidence": 0.85,
        "indicators": {...}
    }
)
```

### 5.2 Event Bus Architecture

```python
class EventBus:
    """
    Centralized event bus for agent communication
    """
    def __init__(self):
        self.subscribers: Dict[str, List[Callable]] = {}
    
    def subscribe(self, event_type: str, callback: Callable):
        """Subscribe to event type"""
        if event_type not in self.subscribers:
            self.subscribers[event_type] = []
        self.subscribers[event_type].append(callback)
    
    async def publish(self, event_type: str, data: Dict):
        """Publish event to all subscribers"""
        if event_type in self.subscribers:
            tasks = [
                callback(data) 
                for callback in self.subscribers[event_type]
            ]
            await asyncio.gather(*tasks, return_exceptions=True)

# Global event bus
event_bus = EventBus()

# Agents subscribe to events
event_bus.subscribe("REGIME_CHANGED", strategy_agent.on_regime_change)
event_bus.subscribe("KILL_SWITCH_ACTIVATED", execution_agent.on_kill_switch)
event_bus.subscribe("TRADE_EXECUTED", portfolio_agent.on_trade_executed)
```

---

## 6. DATA FLOW ARCHITECTURE

### 6.1 Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    EXTERNAL DATA SOURCES                    │
└─────────────────┬───────────────────────────────────────────┘
                  │
        ┌─────────┴─────────┐
        │                   │
        ▼                   ▼
┌───────────────┐    ┌──────────────┐
│   DhanHQ API  │    │  News/Social │
│  (Market Data)│    │  Media APIs  │
└───────┬───────┘    └──────┬───────┘
        │                   │
        └─────────┬─────────┘
                  │
                  ▼
        ┌─────────────────┐
        │  Data Fetcher   │
        │    Service      │
        └────────┬────────┘
                 │
        ┌────────┴─────────┐
        │                  │
        ▼                  ▼
┌──────────────┐    ┌──────────────┐
│    Redis     │    │  Firestore   │
│   (Cache)    │    │  (Real-time) │
└──────┬───────┘    └──────┬───────┘
       │                   │
       └─────────┬─────────┘
                 │
        ┌────────▼─────────────────┐
        │    AGENTS (8 Agents)     │
        │  - Sentiment             │
        │  - Regime                │
        │  - Scanner               │
        │  - Strategy              │
        │  - Risk                  │
        │  - Execution             │
        │  - Paper                 │
        │  - Portfolio             │
        └──────────┬───────────────┘
                   │
        ┌──────────┴──────────┐
        │                     │
        ▼                     ▼
┌──────────────┐      ┌──────────────┐
│  Cloud SQL   │      │  BigQuery    │
│ (Trades DB)  │      │ (Analytics)  │
└──────────────┘      └──────────────┘
```

### 6.2 Data Caching Strategy

| **Data Type** | **Storage** | **TTL** | **Update Frequency** |
|---------------|-------------|---------|---------------------|
| Real-time quotes | Redis | 5 sec | Continuous (Streaming) |
| Option chain | Redis | 10 sec | Every 30 sec |
| Sentiment score | Redis | 180 sec | Every 3 min |
| Regime state | Redis | 180 sec | Every 3 min |
| Portfolio snapshot | Redis | 60 sec | Every 15 min |
| Historical OHLC | BigQuery | Permanent | End of day |
| Trade logs | Cloud SQL | Permanent | On trade |

---

## 7. ERROR HANDLING & RESILIENCE

### 7.1 Agent Failure Modes

| **Failure** | **Impact** | **Mitigation** |
|-------------|-----------|---------------|
| Sentiment Agent down | Degraded regime detection | Use last known sentiment |
| Regime Agent down | Cannot generate signals | HALT trading, use last regime |
| Scanner Agent down | No opportunities | Fall back to index-only trading |
| Strategy Agent down | No signals | HALT trading |
| Risk Agent down | Unsafe to trade | HALT trading immediately |
| Execution Agent down | Cannot place orders | HALT trading, use backup broker |
| Paper Agent down | No impact (paper mode) | Log warning |
| Portfolio Agent down | No monitoring | HALT trading, emergency alert |

### 7.2 Automatic Recovery Procedures

```python
class AgentHealthMonitor:
    """
    Monitors agent health and triggers recovery
    """
    async def monitor_agents(self):
        """Continuous health monitoring"""
        while True:
            for agent in self.agents:
                health = await agent.get_health()
                
                if health['status'] != "HEALTHY":
                    await self._trigger_recovery(agent, health)
            
            await asyncio.sleep(30)  # Check every 30 seconds
    
    async def _trigger_recovery(self, agent, health):
        """Automatic recovery procedures"""
        
        if health['status'] == "DEGRADED":
            # Try to restart agent
            await agent.restart()
        
        elif health['status'] == "FAILED":
            # Critical failure
            if agent.priority == "P0":
                # Halt trading
                await self.orchestrator.halt_trading(
                    reason=f"{agent.name} critical failure"
                )
                
                # Alert admin
                await self.notification_service.send_critical_alert(
                    message=f"CRITICAL: {agent.name} failed"
                )
            
            else:
                # Non-critical - log and continue in degraded mode
                self.logger.warning(f"{agent.name} failed - degraded mode")
```

---

## 8. PERFORMANCE OPTIMIZATION

### 8.1 Parallel Execution

Agents that don't depend on each other run in parallel:

```python
# Good: Parallel execution
sentiment, regime, scanner = await asyncio.gather(
    sentiment_agent.analyze(),
    regime_agent.classify(),
    scanner_agent.scan()
)

# Bad: Sequential execution (slow)
sentiment = await sentiment_agent.analyze()  # 5s
regime = await regime_agent.classify()      # 3s
scanner = await scanner_agent.scan()        # 10s
# Total: 18 seconds

# Good: Total time = max(5s, 3s, 10s) = 10 seconds
```

### 8.2 Caching Strategy

```python
from functools import lru_cache
from datetime import datetime, timedelta

class CachedAgent(BaseAgent):
    """Base class with caching support"""
    
    def __init__(self, config):
        super().__init__(config)
        self.cache = {}
        self.cache_ttl = config.get('cache_ttl', 180)  # seconds
    
    async def get_cached_or_compute(
        self,
        cache_key: str,
        compute_func: Callable,
        ttl: int = None
    ):
        """Get from cache or compute"""
        ttl = ttl or self.cache_ttl
        
        # Check cache
        if cache_key in self.cache:
            cached_data, cached_time = self.cache[cache_key]
            
            if (datetime.now() - cached_time).seconds < ttl:
                return cached_data
        
        # Compute fresh data
        data = await compute_func()
        
        # Store in cache
        self.cache[cache_key] = (data, datetime.now())
        
        return data
```

---

## 9. MONITORING & OBSERVABILITY

### 9.1 Agent Metrics

Each agent exposes the following metrics:

```python
class AgentMetrics(BaseModel):
    agent_name: str
    
    # Health
    status: str                         # HEALTHY, DEGRADED, FAILED
    uptime_seconds: int
    last_execution_time: datetime
    
    # Performance
    avg_execution_time_ms: float
    success_rate: float                 # 0.0 to 1.0
    error_count: int
    
    # Business metrics (agent-specific)
    custom_metrics: Dict
    
    # Example for Regime Agent:
    # {
    #   "regime_accuracy": 0.78,
    #   "regime_changes_today": 3,
    #   "avg_regime_duration_min": 45
    # }
```

### 9.2 Monitoring Dashboard

```python
@app.get("/metrics/agents")
async def get_agent_metrics():
    """
    Endpoint for Prometheus/Grafana monitoring
    """
    metrics = {}
    
    for agent in [
        sentiment_agent,
        regime_agent,
        scanner_agent,
        strategy_agent,
        risk_agent,
        execution_agent,
        paper_agent,
        portfolio_agent
    ]:
        metrics[agent.name] = await agent.get_metrics()
    
    return metrics
```

---

## 10. IMPLEMENTATION EXAMPLES

### 10.1 Complete Agent Implementation Template

```python
# src/agents/template_agent.py
from abc import ABC
from typing import Dict, Any
from datetime import datetime
from src.agents.base_agent import BaseAgent
from src.models import InputModel, OutputModel

class TemplateAgent(BaseAgent):
    """
    Template for creating new agents
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        
        # Agent-specific initialization
        self.custom_param = config.get('custom_param', 'default')
        self.cache_ttl = config.get('cache_ttl', 180)
        
        # State
        self.last_output = None
        self.execution_count = 0
    
    async def analyze(self, input_data: InputModel) -> OutputModel:
        """
        Main analysis method
        """
        try:
            # Log start
            self.logger.info(f"{self.name} starting analysis")
            start_time = datetime.now()
            
            # Step 1: Validate input
            self._validate_input(input_data)
            
            # Step 2: Fetch required data
            market_data = await self._fetch_market_data()
            
            # Step 3: Core processing logic
            result = await self._process(input_data, market_data)
            
            # Step 4: Post-processing
            output = self._format_output(result)
            
            # Step 5: Update state
            self.last_output = output
            self.execution_count += 1
            
            # Log completion
            duration = (datetime.now() - start_time).total_seconds()
            self.logger.info(
                f"{self.name} completed in {duration:.2f}s"
            )
            
            return output
        
        except Exception as e:
            self.logger.error(f"{self.name} failed: {e}")
            self.error_count += 1
            raise
    
    async def _process(
        self,
        input_data: InputModel,
        market_data: Dict
    ) -> Dict:
        """Core processing logic - implement in subclass"""
        raise NotImplementedError
    
    def get_status(self) -> Dict:
        """Return agent status"""
        return {
            "agent_name": self.name,
            "status": "HEALTHY" if self.error_count < 3 else "DEGRADED",
            "execution_count": self.execution_count,
            "last_execution": self.last_output.timestamp if self.last_output else None,
            "error_count": self.error_count
        }
    
    async def restart(self):
        """Restart agent after failure"""
        self.logger.info(f"Restarting {self.name}")
        self.error_count = 0
        self.last_output = None
        await self._initialize()
```

### 10.2 Agent Integration Example

```python
# src/main.py - FastAPI application
from fastapi import FastAPI
from src.agents import (
    SentimentAgent,
    RegimeAgent,
    ScannerAgent,
    StrategyAgent,
    RiskAgent,
    ExecutionAgent,
    PaperAgent,
    PortfolioAgent
)

app = FastAPI()

# Initialize all agents
sentiment_agent = SentimentAgent(config)
regime_agent = RegimeAgent(config)
scanner_agent = ScannerAgent(config)
strategy_agent = StrategyAgent(config)
risk_agent = RiskAgent(config)
execution_agent = ExecutionAgent(config)
paper_agent = PaperAgent(config)
portfolio_agent = PortfolioAgent(config)

@app.post("/tick")
async def trading_tick():
    """
    Main trading cycle endpoint (called every 3 minutes)
    """
    # Phase 1: Sensing
    sentiment, regime, opportunities = await asyncio.gather(
        sentiment_agent.analyze(),
        regime_agent.classify_regime(),
        scanner_agent.scan_universe()
    )
    
    # Phase 2: Decision
    signals = await strategy_agent.generate_signals(
        regime=regime,
        opportunities=opportunities
    )
    
    # Phase 3: Risk
    approved_signals = []
    for signal in signals:
        decision = await risk_agent.validate_signal(signal)
        if decision.decision == "APPROVED":
            approved_signals.append((signal, decision))
    
    # Phase 4: Execution
    results = []
    for signal, decision in approved_signals:
        result = await execution_agent.execute_signal(signal, decision)
        results.append(result)
    
    # Phase 5: Portfolio update
    await portfolio_agent.refresh_snapshot()
    
    return {
        "timestamp": datetime.now(),
        "regime": regime.regime,
        "signals_generated": len(signals),
        "signals_approved": len(approved_signals),
        "trades_executed": len([r for r in results if r.status == "SUCCESS"])
    }
```

---

## 📚 APPENDIX

### A. Agent Quick Reference

| Agent | Input | Output | Execution Time | Priority |
|-------|-------|--------|----------------|----------|
| Sentiment | News, Social, Global | Sentiment Score | 5s | P1 |
| Regime | OHLC, Indicators | Regime State | 3s | P0 |
| Scanner | Universe, Quotes | Opportunities | 10s | P1 |
| Strategy | Regime, Opportunities | Signals | 2s | P0 |
| Risk | Signals, Portfolio | Approval | 1s | P0 |
| Execution | Approved Signals | Order IDs | 3-10s | P0 |
| Paper | Signals (paper mode) | Simulated Fills | 1s | P2 |
| Portfolio | All Trades | Portfolio State | 2s | P1 |

### B. Error Codes

| Code | Description | Resolution |
|------|-------------|------------|
| E001 | Agent initialization failed | Check config, restart |
| E002 | Dependency agent unavailable | Wait for dependency to recover |
| E003 | External API timeout | Retry with exponential backoff |
| E004 | Invalid signal generated | Log and skip signal |
| E005 | Risk check failed | Log rejection reason |
| E006 | Order execution failed | Retry or manual intervention |
| E007 | Kill switch activated | Manual investigation required |

---

**Document Version:** 4.0  
**Last Updated:** January 30, 2026  
**Maintained By:** MSMEcred Engineering Team  

**Next Steps:**
1. Review agent specifications with development team
2. Implement base agent class and infrastructure
3. Develop agents in priority order (Risk → Regime → Strategy → Execution)
4. Test inter-agent communication
5. Deploy to Cloud Run with monitoring

🚀 **Ready to build the 8-agent system!**
