"""
Scanner Agent Demo - GenAI Integration Test
Shows how the scanner identifies stocks using 12 technical filters + GenAI validation
"""

import asyncio
import sys
import logging
from datetime import datetime
import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')

# Configure logging - suppress debug
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

from src.agents.scanner import ScannerAgent
from src.services.nse_data import nse_data_service


async def demo_scanner():
    """Demonstrate Scanner Agent with GenAI integration."""
    
    print("\n" + "=" * 80)
    print("SCANNER AGENT DEMO - GenAI Integration")
    print("=" * 80)
    
    # Step 1: Initialize Scanner
    print("\n[STEP 1] Initializing Scanner Agent...")
    scanner = ScannerAgent("ScannerDemo")
    await scanner.start()
    
    # Check GenAI status
    genai_status = "ENABLED (Vertex AI)" if scanner.model else "DISABLED (whitebox fallback)"
    print(f"  GenAI Status: {genai_status}")
    print(f"  Universe Size: {len(scanner.SCAN_UNIVERSE)} stocks")
    print(f"  Technical Filters: 12")
    print()
    print("  Filter Details:")
    print("    Momentum: RSI(14), Stochastic(14,3,3)")
    print("    Trend: ADX(14), MACD, EMA Alignment (9/21/50), Parabolic SAR")
    print("    Volume: Volume Ratio, OBV")
    print("    Volatility: Bollinger Bands, ATR")
    print("    GenAI: Multi-factor validation score")
    
    # Step 2: Scan a few stocks manually to show the process
    print("\n[STEP 2] Scanning Sample Stocks...")
    print("-" * 70)
    
    test_stocks = ["RELIANCE", "HDFCBANK", "TCS", "TATAMOTORS", "NESTLEIND"]
    
    results = []
    
    for symbol in test_stocks:
        print(f"\n  Analyzing {symbol}...")
        try:
            score, indicators = await scanner._analyze_stock(symbol, scanner.filters)
            
            # Display indicators
            print(f"    RSI(14): {indicators.get('rsi', 0):.1f}")
            print(f"    ADX(14): {indicators.get('adx', 0):.1f}")
            print(f"    MACD: {'Bullish' if indicators.get('macd_signal', 0) > 0 else 'Bearish'}")
            print(f"    Stochastic K: {indicators.get('stoch_k', 50):.1f}")
            print(f"    Volume Ratio: {indicators.get('volume_ratio', 1):.2f}x avg")
            print(f"    OBV Rising: {indicators.get('obv_rising', False)}")
            print(f"    EMA Aligned (9>21>50): {indicators.get('ema_aligned', False)}")
            print(f"    Parabolic SAR: {'Bullish' if indicators.get('psar_bullish', False) else 'Bearish'}")
            print(f"    BB Position: {indicators.get('bb_position', 0.5):.2f} (0=lower, 0.5=middle, 1=upper)")
            print(f"    ATR %: {indicators.get('atr_pct', 0.02)*100:.2f}%")
            
            # Score breakdown
            scores = indicators.get('scores_breakdown', {})
            print(f"\n    SCORE BREAKDOWN:")
            print(f"      RSI Score: {scores.get('rsi_score', 50):.0f}/100 (10% weight)")
            print(f"      ADX Score: {scores.get('adx_score', 50):.0f}/100 (10% weight)")
            print(f"      MACD Score: {scores.get('macd_score', 50):.0f}/100 (12% weight)")
            print(f"      Volume Score: {scores.get('volume_score', 50):.0f}/100 (15% weight)")
            print(f"      EMA Score: {scores.get('ema_score', 50):.0f}/100 (10% weight)")
            print(f"      GenAI Score: {scores.get('genai_score', 50):.0f}/100 (10% weight)")
            
            print(f"\n    TOTAL SCORE: {score:.1f}/100", end="")
            if score > 70:
                print(" *** HIGH - STRATEGY TRIGGER ***")
            elif score > 50:
                print(" - Moderate")
            else:
                print(" - Skip")
            
            results.append({
                'symbol': symbol,
                'score': score,
                'rsi': indicators.get('rsi', 0),
                'adx': indicators.get('adx', 0),
                'genai': scores.get('genai_score', 50)
            })
            
        except Exception as e:
            print(f"    Error: {e}")
        
        await asyncio.sleep(0.5)
    
    # Step 3: Summary
    print("\n" + "=" * 80)
    print("[STEP 3] Stock Ranking Summary")
    print("=" * 80)
    
    results.sort(key=lambda x: x['score'], reverse=True)
    
    print(f"\n{'Rank':<6}{'Symbol':<12}{'Score':<10}{'RSI':<8}{'ADX':<8}{'GenAI':<10}{'Action'}")
    print("-" * 70)
    
    for i, r in enumerate(results, 1):
        action = "TRADE" if r['score'] > 70 else ("WATCH" if r['score'] > 50 else "SKIP")
        print(f"{i:<6}{r['symbol']:<12}{r['score']:.1f}{'':>4}{r['rsi']:.1f}{'':>3}{r['adx']:.1f}{'':>3}{r['genai']:.0f}{'':>5}{action}")
    
    # Step 4: Strategy Trigger Flow
    print("\n" + "=" * 80)
    print("[STEP 4] How Strategies Get Triggered")
    print("=" * 80)
    
    print("""
    SCANNER → STRATEGY FLOW:
    
    ┌─────────────────────────────────────────────────────────────────────┐
    │                        SCANNER AGENT                                │
    │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌────────────┐  │
    │  │ 12 Tech     │  │ Regime      │  │ GenAI       │  │ Final      │  │
    │  │ Indicators  │──│ Adjustment  │──│ Validation  │──│ Score      │  │
    │  │ (90%)       │  │             │  │ (10%)       │  │            │  │
    │  └─────────────┘  └─────────────┘  └─────────────┘  └────────────┘  │
    │                                                           │         │
    │                                                           ▼         │
    │                                                    Score > 50?      │
    │                                                         │           │
    └─────────────────────────────────────────────────────────│───────────┘
                                                              │
                              ┌────────────────────────────────┘
                              ▼
    ┌─────────────────────────────────────────────────────────────────────┐
    │                      STRATEGY AGENT                                 │
    │                                                                     │
    │  For each qualified stock:                                          │
    │    1. Calculate suitability for each of 15 strategies               │
    │    2. Select strategies with suitability > 70%                      │
    │    3. Generate signals using strategy logic                         │
    │                                                                     │
    │  Example: RELIANCE (Score 75)                                       │
    │    ├─ VWAP Reversion: Suitability 90% → GENERATE SIGNAL             │
    │    ├─ Swing Breakout: Suitability 85% → GENERATE SIGNAL             │
    │    ├─ Momentum Rotation: Suitability 80% → GENERATE SIGNAL          │
    │    └─ Gap Fill: Suitability 45% → SKIP                              │
    │                                                                     │
    └─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
    ┌─────────────────────────────────────────────────────────────────────┐
    │                        RISK AGENT                                   │
    │                                                                     │
    │  For each signal:                                                   │
    │    - Kelly Criterion position sizing                                │
    │    - VIX scaling                                                    │
    │    - Portfolio heat check (max 25%)                                 │
    │    - Approve/Reject/Modify                                          │
    │                                                                     │
    └─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
    ┌─────────────────────────────────────────────────────────────────────┐
    │                      EXECUTION AGENT                                │
    │                                                                     │
    │  Place order via DhanHQ API                                         │
    │  Generate GenAI trade justification (for manual review)             │
    │                                                                     │
    └─────────────────────────────────────────────────────────────────────┘
    """)
    
    # GenAI Details
    print("\n" + "=" * 80)
    print("[STEP 5] GenAI Scoring Details")
    print("=" * 80)
    
    print("""
    GenAI VALIDATION PROCESS:
    
    1. WHEN: After 11 technical indicators are calculated
    
    2. HOW: Sends prompt to Vertex AI Gemini:
    
       ┌─────────────────────────────────────────────────────────────┐
       │                                                             │
       │  Score this stock for INTRADAY trading (0-100):             │
       │                                                             │
       │  Symbol: RELIANCE                                           │
       │  RSI(14): 52.3                                              │
       │  ADX: 28.5                                                  │
       │  MACD Signal: Bullish                                       │
       │  Stochastic: 45.2                                           │
       │  Volume: 1.8x average                                       │
       │  EMA Aligned: True                                          │
       │  Parabolic SAR: Bullish                                     │
       │                                                             │
       │  Scoring Criteria:                                          │
       │  - 80-100: Strong setup, multiple confirmations             │
       │  - 60-79: Good setup, trade with caution                    │
       │  - 40-59: Weak setup, avoid                                 │
       │  - 0-39: Red flags present                                  │
       │                                                             │
       │  Return ONLY a number 0-100.                                │
       │                                                             │
       └─────────────────────────────────────────────────────────────┘
    
    3. WEIGHT: GenAI contributes 10% to final score
       - 90% from technical indicators
       - 10% from GenAI validation
    
    4. FALLBACK: If GenAI fails, defaults to score 50 (neutral)
    
    5. PURPOSE:
       - Catch patterns humans might miss
       - Validate technical confluences
       - Add AI "sanity check" to signals
    """)
    
    print("\n" + "=" * 80)
    print("DEMO COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(demo_scanner())
