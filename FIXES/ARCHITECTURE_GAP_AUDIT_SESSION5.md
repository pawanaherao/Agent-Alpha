# Architecture Gap Audit - Session 5
**Date:** Feb 24, 2026  
**Focus:** Universe Scope, Option Chain Scanning, Module Communication  
**Status:** CRITICAL GAPS IDENTIFIED - Action Required

---

## Executive Summary

Your system is designed to trade:
- **NSE 100 stocks** (equity + F&O stocks)
- **NSE F&O stocks** (full eligible universe, 150+)
- **Index Options:** NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY

**However, the actual implementation has 3 critical gaps:**

1. ❌ **Universe Mismatch:** Scanner only scans 30 hardcoded stocks (NOT 100+/150+)
2. ❌ **Option Chain Blind Spot:** Zero option chain scanning / surveillance for F&O underlyings
3. ❌ **Module Isolation:** UniversalStrategy (options) exists but is NOT wired into orchestration loop

---

## GAP 1: Universe Definition Mismatch

### Declared Architecture (AGENT_ORCHESTRATION_DIAGRAM.md)

```
Scanner Agent Role
├─ Input: SCAN_UNIVERSE = 30 highly liquid NSE stocks ← DOCUMENTED
├─ Output: Top 10 opportunities (score > 50)
└─ Scope: NSE 100 + F&O eligible
```

### Actual Implementation

#### `backend/src/agents/scanner.py` (Lines 60-85)

```python
SCAN_UNIVERSE = [
    # Banking (6)
    "HDFCBANK", "ICICIBANK", "AXISBANK", "KOTAKBANK", "SBIN", "INDUSINDBK",
    # IT (5)
    "TCS", "INFY", "WIPRO", "HCLTECH", "TECHM",
    # Energy (4)
    "RELIANCE", "ONGC", "NTPC", "POWERGRID",
    # FMCG (4)
    "HINDUNILVR", "ITC", "NESTLEIND", "BRITANNIA",
    # Auto (4)
    "MARUTI", "TATAMOTORS", "M&M", "BAJAJ-AUTO",
    # Pharma (3)
    "SUNPHARMA", "DRREDDY", "CIPLA",
    # Finance (2)
    "BAJFINANCE", "BAJAJFINSV",
    # Metals (3)
    "TATASTEEL", "HINDALCO", "JSWSTEEL"
]
# TOTAL = exactly 30 stocks
```

**Impact:**
- ✅ Covers 30 high-liquidity stocks well
- ❌ Misses 70+ other NSE 100 stocks (BAJERLIBERTY, GAIL, BHARTIARTL, ADANIPORTS, ADANIENT, etc.)
- ❌ No NSE F&O stocks beyond these 30 (e.g., KOTAKBANKTT, JIOPHARMACY level liquidity)

---

#### `backend/src/services/nse_data.py` (Line 395-420)

```python
def get_nifty_100_stocks(self) -> List[str]:
    return [
        "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",  # 105+ entries total
        ... (100+ stocks) ...
    ]

def get_fno_stocks(self) -> List[str]:
    return [
        "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "SBIN", "BHARTIARTL", "KOTAKBANK"
    ]  # ONLY 8 stocks!
```

**Critical Issue:**  
NSEDataService has BOTH universes defined, but:
- ✅ `get_nifty_100_stocks()` = ~105 stocks (good)
- ❌ `get_fno_stocks()` = **only 8 stocks** (should be 150+)

**Why This Matters:**

| Parameter | Claimed | Actual |
|-----------|---------|--------|
| NSE 100 Stocks | 100 | ✅ 105 (via `get_nifty_100_stocks()`) |
| F&O Eligible Stocks | 150+ | ❌ 8 (via `get_fno_stocks()`) |
| Scanner Universe | NSE 100 | ❌ 30 hardcoded |
| Index Options | NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY | ⚠️ Only NIFTY/BANKNIFTY scanned |

---

## GAP 2: Option Chain Scanning - Zero Coverage

### Declared Architecture

```
Multi-Asset Universe
├─ Equity: NSE 100 stocks
├─ Options: NIFTY Index Options (50 lot)
├─ Options: BANKNIFTY Index Options (15 lot)
├─ Options: FINNIFTY Index Options (40 lot)
├─ Options: MIDCPNIFTY Index Options
└─ Options: All NSE F&O stocks (individual stock options)
```

### Actual Implementation: No Options Scanning Loop

**Problem:** There is NO agent or scheduler that scans option chains.

#### What EXISTS (but unused):

1. **OptionChainService** (`backend/src/services/option_chain.py`)
   ```python
   async def get_chain(
       self, 
       symbol: str = "NIFTY",
       num_strikes: int = 10,
       enrich_greeks: bool = True
   ) -> OptionChain:
       """Get live option chain with Greeks"""
   ```
   - ✅ Can fetch chains for ANY symbol
   - ❌ Only called on-demand (not in scanning loop)

2. **GreeksEngine** (`backend/src/services/greeks.py`)
   ```python
   def enrich_chain_item(self, item, spot_price, T):
       """Calculate Greeks: delta, gamma, theta, vega, rho"""
   
   def portfolio_greeks(self, legs, spot):
       """Multi-leg portfolio Greeks"""
   ```
   - ✅ Can compute Greeks for structures
   - ❌ Not integrated into Scanner

3. **UniversalStrategy with Options Mode** (`backend/src/strategies/universal_strategy.py`)
   ```python
   async def _generate_options_signal(self, market_data: pd.DataFrame, regime: str):
       """Config-driven options signal generator"""
       structure = self.config.get("structure", "IRON_CONDOR")
       opts_cfg = self.config.get("options_config", {})
       
       # Fetch option chain
       chain = await option_chain_service.get_chain(symbol, ...)
       
       # Build legs based on structure
       legs = self._build_structure_legs(structure, chain, ...)
   ```
   - ✅ Can generate options signals
   - ❌ Only called if registered in StrategyAgent (which it is)
   - ❌ But receives NO option chain data (only equity OHLCV)

#### Missing: Option Chain Scanner Agent

**Flow That Should Exist But Doesn't:**

```
AgentManager.run_cycle()
  ├─ Phase 1: Sensing (PARALLEL)
  │   ├─ SentimentAgent → SENTIMENT_UPDATED
  │   ├─ RegimeAgent → REGIME_UPDATED
  │   ├─ ScannerAgent (Equity) → SCAN_COMPLETE
  │   └─ ❌ OptionChainScannerAgent → ???  (MISSING!)
  │
  ├─ Phase 2: Decision (SEQUENTIAL)
  │   ├─ StrategyAgent
  │   │   ├─ Uses equity signals from Scanner
  │   │   ├─ Calls UniversalStrategy (config mode)
  │   │   └─ UniversalStrategy fetches option chains on-demand
  │   │       (No universe scanning, just per-symbol)
  │   └─ ❌ No options universe scan
  │
  └─ Phase 3: Execution
      └─ All signals routed to RiskAgent
```

**What's Currently Missing:**

| Component | Status | Issue |
|-----------|--------|-------|
| Option Chain Fetching | ✅ Exists | `get_option_chain()` works |
| Greeks Calculation | ✅ Exists | `greeks_engine` works |
| Options Signal Generation | ✅ Exists | UniversalStrategy.\_generate_options_signal() |
| **Options Universe Scanning** | ❌ **MISSING** | **No scanner for F&O stocks/indices** |
| **Options Event Publishing** | ❌ **MISSING** | **No OPTIONS_SCAN_COMPLETE event** |
| **Options Data to Strategy** | ❌ **MISSING** | **UniversalStrategy not given chains** |
| Options in Orchestration Loop | ❌ **MISSING** | **No parallel options sensing** |

---

## GAP 3: Module Communication Gaps

### UniversalStrategy Registration ✅ EXISTS

**`backend/src/agents/init_agents.py` (Line 130)**

```python
if UniversalStrategy is not None:
    await agent.register_strategy(UniversalStrategy())
```

- ✅ UniversalStrategy IS registered in StrategyAgent
- ❌ It's registered with **empty config** (no equity/options config passed)
- ❌ Never receives option chain data as input

### Flow: How UniversalStrategy Gets Data Today

**EQUITY MODE (Working):**
```
ScannerAgent.scan_universe() → SCAN_COMPLETE event
  ├─ Payload: {scanned: [{symbol, score, indicators}]}
  │
StrategyAgent.on_scan_complete()
  ├─ Populates _scan_cache
  │
StrategyAgent.select_and_execute()
  ├─ For each symbol in cache:
  │   ├─ Fetch OHLCV (with injected indicators from cache)
  │   ├─ For each strategy (including UniversalStrategy):
  │   │   └─ Call strategy.generate_signal(market_data, regime)
  │   │       └─ UniversalStrategy._generate_equity_signal() ✅
  │   └─ Return signals
  │
RiskAgent → ExecutionAgent
```

**OPTIONS MODE (Broken):**
```
❌ NO OPTIONS UNIVERSE SCANNER
   There's no agent to scan NIFTY, BANKNIFTY, F&O stocks for options

❌ NO OPTIONS EVENT CHAIN
   Even if options were scanned, there's no event to pass chain data

UniversalStrategy (if in options mode)
  ├─ _generate_options_signal() is never called
  │   (because StrategyAgent doesn't route options data to it)
  │
  ├─ If called, it FETCHES its own chains on-demand:
  │   chain = await option_chain_service.get_chain(symbol, ...)
  │   └─ ⚠️ Not scalable for 150+ stocks per cycle
  │
  └─ Result: Options signals never generated
```

### Key Missing Link: Data Flow

**Equity Chain (Working):**
```
Scanner Indicators → StrategyAgent Cache → UniversalStrategy Input ✅
(12 indicators)        (_scan_cache)       (equity mode)
```

**Options Chain (Broken):**
```
Option Chain Data → ??? → UniversalStrategy.options_mode ❌
(APIs exist)       (No event/cache)        (Never called)
```

---

## Evidence: UniversalStrategy Not Receiving Options Config

**UniversalStrategy Constructor:**
```python
def __init__(self, config: Dict[str, Any] = None):
    default_config = {
        "mode": "equity",  # HARDCODED DEFAULT
        "entry_conditions": [],
        "exit_conditions": [],
        "stop_loss_pct": 0.0,
        "take_profit_pct": 0.0,
        "options_config": {},  # EMPTY!
        "greeks_limits": {},   # EMPTY!
        "structure": None,
    }
    final_config = {**default_config, **(config or {})}
```

**How It Gets Registered:**
```python
# init_agents.py, Line 130
await agent.register_strategy(UniversalStrategy())  # ← NO CONFIG PASSED
```

**Result:** UniversalStrategy always runs in equity mode with empty configs.

---

## Impact Analysis

### Scope Mismatch

| Claim | Implementation | Gap | Impact |
|-------|-----------------|-----|--------|
| Trade NSE 100 | Scan only 30 | -70 stocks | 70% of NSE 100 universe ignored |
| Trade F&O Stocks | Only 8 F&O eligible | -142+ stocks | ~95% of F&O universe ignored |
| Scan Index Options | No scanning loop | -4 indices | NIFTY options only if manually requested |
| Risk >= 2:1 RR | Applied per signal | ✅ Works | Good (works at signal-level) |
| SEBI Compliance | Phase 7 implemented | ✅ Works | Good (tagging, audit trail, tranches) |

### Throughput Impact (10 trades/second target)

**Best Case (30 stock × 1 strategy = 30 signals/cycle):**
```
30 stocks × 5 indicators/stock × 100ms fetch = 1500ms per cycle
→ Only 0.67 trades/cycle × 1 cycle/3min = ~0.22 trades/min = 227 trades/day
→ FAR SHORT of 10 trades/second = 86,400 trades/day
```

**With Full NSE 100 (100+ stocks):**
```
100 stocks × 5 indicators = 500ms × 100 = 5000ms per cycle
→ 0.2 trades/cycle
→ Even worse!
```

**With Options (150+ F&O stocks):**
```
150 stocks × option chains (20 strikes each)
→ 3000+ option contracts to scan
→ Greeks calculation for each
→ 15000ms+ per cycle
→ SYSTEM OVERLOAD
```

---

## Root Cause Analysis

### Why This Happened

1. **Initial Design (Sessions 1-3):** 
   - Built for 30-stock MVP
   - Scanner architecture fixed to 30 hardcoded list
   - Option chain services added later (Phase 6)
   - No integration between them

2. **Phase 7 Completion (Session 4):**
   - Focused on equity SEBI compliance
   - Options module completed but not wired to orchestration
   - UniversalStrategy created but not configured
   - No option chain scanning agent created

3. **Documentation:**
   - Reference docs show 30 stocks explicitly
   - Orchestration diagrams don't show option chain flow
   - Universe definitions scattered across files (get_nifty_100 vs get_fno_stocks vs SCAN_UNIVERSE)

---

## Comparison: Declared vs Actual Architecture

### Declared (from your documents)

```
Universe Scope
├─ Equity: NSE 100 stocks (Declared in IMPLEMENTATION_GUIDE.md)
├─ F&O: NSE F&O eligible list (Mentioned in SEBI-Compliant Strategy.md)
└─ Options: NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY index options

Pipeline
├─ ScannerAgent → SCAN_COMPLETE event → StrategyAgent cache
├─ StrategyAgent → register all 15+ strategies
├─ UniversalStrategy → Equity + Options modes
└─ Risk/Execution → SEBI compliant gates
```

### Actual Implementation

```
Universe Scope
├─ Equity Scanning: 30 hardcoded stocks
├─ F&O Available: 8 stocks (but get_fno_stocks() exists to extend)
└─ Options Scanning: NONE (only on-demand per symbol)

Pipeline
├─ ScannerAgent → Scans 30 stocks only → SCAN_COMPLETE event ✅
├─ StrategyAgent → Receives 30 opportunities max
├─ UniversalStrategy → Registered but in equity mode only
│                      (options config never passed)
└─ Risk/Execution → SEBI compliant gates ✅
```

### Gap Summary

| Layer | Declared | Actual | Status |
|-------|----------|--------|--------|
| Universe Definition | 100+ stocks | 30 scanned, 105 available | ⚠️ Mismatch |
| F&O Universe | 150+ stocks | 8 defined, none scanned | ❌ Critical |
| Index Options | 4 indices | NIFTY only (if manually) | ❌ Critical |
| Options Scanning | Enabled | Disabled | ❌ **BROKEN** |
| Options Event | OPTIONS_SCAN_COMPLETE | Not published | ❌ **MISSING** |
| Module Integration | Unified agent loop | Isolated services | ⚠️ Fragmented |
| UniversalStrategy | Equity + Options | Equity only | ⚠️ Unused |
| Greeks Engine | Integrated validation | Call-site only | ⚠️ Unused |

---

## Files Confirming This Gap

### Universe Definition Inconsistency

1. **`backend/src/agents/scanner.py` (Line 60-85)**
   - SCAN_UNIVERSE = 30 stocks

2. **`backend/src/services/nse_data.py` (Lines 395-420)**
   - get_nifty_100_stocks() = 105+ stocks
   - get_fno_stocks() = 8 stocks (hardcoded)

3. **`AGENT_ORCHESTRATION_DIAGRAM.md` (Line 104)**
   - "SCAN_UNIVERSE = 30 highly liquid NSE stocks"

4. **`AGENT_COMMUNICATION_REFERENCE.md` (Line 65)**
   - "Universe scanner computes 12 indicators per stock"
   - Shows only 30 stocks in example

### Options Scanning Not Implemented

1. **`backend/src/core/agent_manager.py` (Lines 160-180)**
   - Phase 1 Sensing: sentiment, regime, scanner
   - ❌ NO options scanning task

2. **`backend/src/services/option_chain.py` (Line 438)**
   - OptionChainService defined but never called from agents

3. **`backend/src/strategies/universal_strategy.py` (Line 159)**
   - `chain = await option_chain_service.get_chain()`
   - This is the ONLY place chains are fetched
   - Only called if UniversalStrategy.generate_signal() is called
   - Which requires options mode config (never provided)

4. **`backend/src/agents/init_agents.py` (Line 130)**
   - `await agent.register_strategy(UniversalStrategy())` ← Empty config

---

## Required Fixes (Recommendations)

### Fix 1: Expand Scanner Universe (Priority: HIGH)

**Option A - Quick (5 min):**
```python
# backend/src/agents/scanner.py, line 60

# Replace hardcoded 30 stocks with:
async def __init__(self, ...):
    # Use the full NSE 100 universe
    self.SCAN_UNIVERSE = self.nse_service.get_nifty_100_stocks()
    # Result: 105 stocks instead of 30
```

**Option B - Complete (2 hours):**
```python
# Separate equity and options scanning
# scanner.py:

class ScannerAgent:
    EQUITY_UNIVERSE = get_nifty_100_stocks()  # 105 stocks
    OPTIONS_UNIVERSE = get_fno_stocks()  # 8 stocks (or expand to 150+)
    INDEX_OPTIONS = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"]
    
    async def scan_equity_universe(self, regime: str):
        """Scan all NSE 100 stocks"""
        
    async def scan_options_universe(self, regime: str):
        """Scan option chains for F&O stocks + indices"""
```

### Fix 2: Implement Option Chain Scanning (Priority: CRITICAL)

**Option ChainScanner Agent** (new file, 200 lines):
```python
# backend/src/agents/option_chain_scanner.py

class OptionChainScannerAgent(BaseAgent):
    """Scan option chains for F&O stocks and indices"""
    
    async def scan_universe(self, regime: str) -> List[Dict]:
        """
        For each F&O stock + index:
        1. Fetch option chain
        2. Calculate Greeks
        3. Score setups (IV rank, structure quality, etc.)
        4. Return: {symbol, expiry, chain_data, structures: [{structure, legs, p/l}]}
        """
```

**Wire into orchestration** (`agent_manager.py`):
```python
# Phase 1: Sensing (parallel)
options_chain_task = asyncio.create_task(
    self.breakers["options_chain"].call(
        self.agents["option_chain_scanner"].scan_universe
    )
)
```

### Fix 3: Configure UniversalStrategy for Options (Priority: HIGH)

**In init_agents.py**:
```python
# Create TWO instances: equity + options

# Equity mode (current)
await agent.register_strategy(UniversalStrategy({
    "mode": "equity",
    ...
}))

# Options mode (new)
await agent.register_strategy(UniversalStrategy({
    "mode": "options",
    "symbol": "NIFTY",
    "structure": "BULL_CALL_SPREAD",
    "options_config": {
        "wing_width": 200,
        "short_delta": 0.20,
        ...
    },
    ...
}))
```

### Fix 4: Publish OPTIONS_SCAN_COMPLETE Event

**In option_chain_scanner.py**:
```python
await self.publish_event("OPTIONS_SCAN_COMPLETE", {
    "chains": [
        {
            "symbol": "NIFTY",
            "spot_price": 23500.0,
            "structures": [
                {
                    "type": "BULL_CALL_SPREAD",
                    "legs": [...],
                    "max_profit": 500,
                    "max_loss": -200
                }
            ]
        }
    ]
})
```

### Fix 5: Expand get_fno_stocks() (Priority: MEDIUM)

**Current (8 stocks):**
```python
def get_fno_stocks(self) -> List[str]:
    return ["RELIANCE", "TCS", "HDFCBANK", ...]  # Only 8
```

**Should be (150+ stocks):**
```python
def get_fno_stocks(self) -> List[str]:
    return [
        # Banking (20+)
        "HDFCBANK", "ICICIBANK", "AXISBANK", "KOTAKBANK", "SBIN", 
        "INDUSINDBK", "CANBK", "PNB", ...
        
        # IT (15+)
        "TCS", "INFY", "WIPRO", "HCLTECH", "TECHM", ...
        
        # Full NSE F&O list (150+ total)
        ...
    ]
```

### Fix 6: Update Reference Documentation (Priority: MEDIUM)

**Update these files:**
1. `AGENT_ORCHESTRATION_DIAGRAM.md` - Show option chain scanner
2. `AGENT_COMMUNICATION_REFERENCE.md` - Add options column to event matrix
3. `ARCHITECTURE_SPEC.md` - Clarify universe scope
4. Update comments in `scanner.py` to explicitly state "30-stock MVP, use get_nifty_100_stocks() for full production"

---

## Testing Checklist

- [ ] Scanner scans 100+ stocks (verify SCAN_UNIVERSE size)
- [ ] get_fno_stocks() returns 150+ stocks (verify list completeness)
- [ ] OptionChainScanner scans NIFTY, BANKNIFTY, F&O stocks
- [ ] OPTIONS_SCAN_COMPLETE event fires with chain data
- [ ] UniversalStrategy receives options config
- [ ] UniversalStrategy.\_generate_options_signal() produces option signals
- [ ] Options signals routed through RiskAgent
- [ ] Full orchestration cycle time < 500ms with 100+ stocks
- [ ] Documentation updated (scope, universe, option chain flow)

---

## Summary of Gaps

| Gap | Type | Severity | Impact | Fix Complexity |
|-----|------|----------|--------|-----------------|
| Scanner universe = 30, not 100+ | Design | 🔴 High | 70 stocks missed | Low (1 line) |
| get_fno_stocks() = 8, not 150+ | Data | 🔴 High | Most F&O universe ignored | Medium (500 lines) |
| No option chain scanning | Architecture | 🔴 Critical | Options disabled | High (200 lines) |
| UniversalStrategy not in options mode | Config | 🟠 Medium | Options signals never generated | Low (5 lines) |
| No OPTIONS_SCAN_COMPLETE event | Integration | 🟠 Medium | No option data flow | Low (10 lines) |
| Documentation shows 30 stocks | Docs | 🟠 Medium | Misleading to stakeholders | Low (5 files) |

---

## Recommended Action Plan

### Phase 1 (1-2 hours): Quick Wins
1. ✅ Expand Scanner.SCAN_UNIVERSE to use get_nifty_100_stocks()
2. ✅ Fix get_fno_stocks() with full 150+ stock list
3. ✅ Update reference docs to clarify scope

### Phase 2 (4-6 hours): Critical Fixes
1. ✅ Create OptionChainScannerAgent
2. ✅ Wire into orchestration loop (parallel sensing)
3. ✅ Publish OPTIONS_SCAN_COMPLETE event
4. ✅ Configure UniversalStrategy for options mode

### Phase 3 (2 hours): Validation
1. ✅ End-to-end test with options data
2. ✅ Verify latency < 500ms
3. ✅ Check 10-trades/second architecture goal
4. ✅ Update all documentation

---

**Next Steps:** Implement Phase 1 quick wins immediately (easy wins), then tackle Phase 2 for full options coverage.
