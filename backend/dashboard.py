"""
AGENT ALPHA - Trading Dashboard
Streamlit-based browser dashboard for paper trading simulation
"""

import streamlit as st
import pandas as pd
import numpy as np
import asyncio
from datetime import datetime, timedelta
import json
import os
import sys

# Add parent dir to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Page config
st.set_page_config(
    page_title="Agent Alpha - Trading Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for premium look
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: 700;
        background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0;
    }
    .sub-header {
        font-size: 1rem;
        color: #6c757d;
        margin-top: 0;
    }
    .metric-card {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
        border-radius: 12px;
        padding: 20px;
        color: white;
        box-shadow: 0 4px 15px rgba(0,0,0,0.2);
    }
    .signal-buy {
        background: linear-gradient(135deg, #00b894 0%, #00cec9 100%);
        padding: 10px 20px;
        border-radius: 8px;
        color: white;
        font-weight: bold;
    }
    .signal-sell {
        background: linear-gradient(135deg, #e74c3c 0%, #c0392b 100%);
        padding: 10px 20px;
        border-radius: 8px;
        color: white;
        font-weight: bold;
    }
    .regime-bull { color: #00b894; font-weight: bold; }
    .regime-bear { color: #e74c3c; font-weight: bold; }
    .regime-sideways { color: #f39c12; font-weight: bold; }
    .regime-volatile { color: #9b59b6; font-weight: bold; }
</style>
""", unsafe_allow_html=True)


# Initialize session state
if 'capital' not in st.session_state:
    st.session_state.capital = 1000000
if 'positions' not in st.session_state:
    st.session_state.positions = {}
if 'trades' not in st.session_state:
    st.session_state.trades = []
if 'signals' not in st.session_state:
    st.session_state.signals = []


def get_regime_color(regime):
    colors = {
        "BULL": "#00b894",
        "BEAR": "#e74c3c",
        "SIDEWAYS": "#f39c12",
        "VOLATILE": "#9b59b6"
    }
    return colors.get(regime, "#6c757d")


def get_mock_regime():
    """Get mock regime for demo."""
    import random
    regimes = ["BULL", "BEAR", "SIDEWAYS", "VOLATILE"]
    weights = [0.4, 0.2, 0.3, 0.1]
    return random.choices(regimes, weights=weights)[0]


def get_mock_vix():
    """Get mock VIX for demo."""
    import random
    return round(random.uniform(12, 25), 2)


def get_mock_signals():
    """Generate mock signals for demo."""
    import random
    
    stocks = ["RELIANCE", "TCS", "HDFCBANK", "TATAMOTORS", "INFY", "SBIN", "NTPC", "TATASTEEL"]
    strategies = ["VWAP Reversion", "Momentum Rotation", "Swing Breakout", "ATR Breakout"]
    
    signals = []
    for _ in range(random.randint(1, 4)):
        stock = random.choice(stocks)
        strategy = random.choice(strategies)
        score = random.randint(55, 95)
        price = random.uniform(500, 3000)
        
        signals.append({
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "symbol": stock,
            "strategy": strategy,
            "signal": "BUY" if score > 70 else "WATCH",
            "score": score,
            "price": round(price, 2),
            "stop_loss": round(price * 0.97, 2),
            "target": round(price * 1.05, 2)
        })
    
    return signals


def load_backtest_results():
    """Load backtest results from CSV."""
    try:
        df = pd.read_csv("full_strategy_backtest.csv")
        return df
    except:
        return None


# Header
st.markdown('<h1 class="main-header">🚀 Agent Alpha</h1>', unsafe_allow_html=True)
st.markdown('<p class="sub-header">AI-Powered Trading System | Paper Trading Dashboard</p>', unsafe_allow_html=True)

# Sidebar
with st.sidebar:
    st.image("https://img.icons8.com/fluency/96/trading.png", width=80)
    st.markdown("### ⚙️ Settings")
    
    capital = st.number_input("Starting Capital (₹)", value=st.session_state.capital, step=100000)
    st.session_state.capital = capital
    
    risk_per_trade = st.slider("Risk per Trade (%)", 1, 5, 2)
    max_positions = st.slider("Max Open Positions", 1, 10, 5)
    
    st.markdown("---")
    st.markdown("### 📊 Quick Stats")
    
    # Load backtest
    df = load_backtest_results()
    if df is not None:
        st.metric("Strategies Tested", len(df['strategy_name'].unique()))
        st.metric("Avg Sharpe", f"{df['sharpe'].mean():.2f}")
        st.metric("Top Sharpe", f"{df['sharpe'].max():.2f}")
    
    st.markdown("---")
    st.markdown("### 🎯 Top Performers")
    if df is not None:
        top3 = df.nlargest(3, 'sharpe')[['strategy_name', 'symbol', 'sharpe']]
        for _, row in top3.iterrows():
            st.markdown(f"**{row['strategy_name']}**")
            st.markdown(f"_{row['symbol']}_ | Sharpe: {row['sharpe']:.2f}")


# Main content
col1, col2, col3, col4 = st.columns(4)

# Get current data
regime = get_mock_regime()
vix = get_mock_vix()

with col1:
    st.markdown("### 📈 Market Regime")
    regime_color = get_regime_color(regime)
    st.markdown(f"""
    <div style="background: {regime_color}; padding: 20px; border-radius: 12px; text-align: center;">
        <h2 style="color: white; margin: 0;">{regime}</h2>
    </div>
    """, unsafe_allow_html=True)

with col2:
    st.markdown("### 📊 India VIX")
    vix_color = "#00b894" if vix < 15 else ("#f39c12" if vix < 20 else "#e74c3c")
    st.markdown(f"""
    <div style="background: {vix_color}; padding: 20px; border-radius: 12px; text-align: center;">
        <h2 style="color: white; margin: 0;">{vix}</h2>
    </div>
    """, unsafe_allow_html=True)

with col3:
    st.markdown("### 💰 Capital")
    st.markdown(f"""
    <div style="background: #2d3436; padding: 20px; border-radius: 12px; text-align: center;">
        <h2 style="color: #00b894; margin: 0;">₹{capital:,.0f}</h2>
    </div>
    """, unsafe_allow_html=True)

with col4:
    st.markdown("### 📋 Positions")
    positions_count = len(st.session_state.positions)
    st.markdown(f"""
    <div style="background: #2d3436; padding: 20px; border-radius: 12px; text-align: center;">
        <h2 style="color: #74b9ff; margin: 0;">{positions_count} / {max_positions}</h2>
    </div>
    """, unsafe_allow_html=True)


st.markdown("---")

# Tabs
tab1, tab2, tab3, tab4 = st.tabs(["📡 Live Signals", "📊 Backtest Results", "💼 Portfolio", "🤖 Agent Status"])

with tab1:
    st.markdown("### 📡 Live Trading Signals")
    
    col_refresh, col_auto = st.columns([1, 3])
    with col_refresh:
        if st.button("🔄 Refresh Signals", type="primary"):
            st.session_state.signals = get_mock_signals()
    with col_auto:
        auto_refresh = st.checkbox("Auto-refresh (5s)", value=False)
    
    if auto_refresh:
        st.session_state.signals = get_mock_signals()
    
    if st.session_state.signals:
        for signal in st.session_state.signals:
            with st.container():
                cols = st.columns([2, 2, 1, 1, 1, 1, 1])
                
                with cols[0]:
                    signal_class = "signal-buy" if signal['signal'] == "BUY" else ""
                    st.markdown(f"**{signal['symbol']}** | {signal['strategy']}")
                
                with cols[1]:
                    if signal['signal'] == "BUY":
                        st.success(f"🟢 BUY @ ₹{signal['price']:,.2f}")
                    else:
                        st.warning(f"🟡 WATCH @ ₹{signal['price']:,.2f}")
                
                with cols[2]:
                    st.metric("Score", f"{signal['score']}/100")
                
                with cols[3]:
                    st.metric("SL", f"₹{signal['stop_loss']:,.0f}")
                
                with cols[4]:
                    st.metric("Target", f"₹{signal['target']:,.0f}")
                
                with cols[5]:
                    if signal['signal'] == "BUY":
                        if st.button("Execute", key=f"exec_{signal['symbol']}_{signal['timestamp']}"):
                            st.session_state.positions[signal['symbol']] = signal
                            st.success(f"Paper trade executed: {signal['symbol']}")
                
                st.markdown("---")
    else:
        st.info("Click 'Refresh Signals' to scan for opportunities")


with tab2:
    st.markdown("### 📊 Backtest Performance")
    
    df = load_backtest_results()
    if df is not None:
        # Summary metrics
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Tests", len(df))
        col2.metric("Avg Sharpe", f"{df['sharpe'].mean():.2f}")
        col3.metric("Sharpe > 3.0", len(df[df['sharpe'] > 3]))
        col4.metric("Avg Win Rate", f"{df['win_rate'].mean()*100:.1f}%")
        
        st.markdown("---")
        
        # Strategy performance
        st.markdown("#### Strategy Performance Ranking")
        strat_perf = df.groupby('strategy_name').agg({
            'sharpe': ['mean', 'max'],
            'win_rate': 'mean'
        }).round(3)
        strat_perf.columns = ['Avg Sharpe', 'Max Sharpe', 'Win Rate']
        strat_perf = strat_perf.sort_values('Avg Sharpe', ascending=False)
        strat_perf['Win Rate'] = (strat_perf['Win Rate'] * 100).round(1).astype(str) + '%'
        st.dataframe(strat_perf, use_container_width=True)
        
        st.markdown("---")
        
        # Top combinations
        st.markdown("#### Top 10 Strategy-Stock Combinations")
        top10 = df.nlargest(10, 'sharpe')[['strategy_name', 'symbol', 'sharpe', 'win_rate', 'total_trades']]
        top10['win_rate'] = (top10['win_rate'] * 100).round(1).astype(str) + '%'
        top10.columns = ['Strategy', 'Symbol', 'Sharpe', 'Win Rate', 'Trades']
        st.dataframe(top10, use_container_width=True)
    else:
        st.warning("No backtest results found. Run `python run_full_backtest.py` first.")


with tab3:
    st.markdown("### 💼 Portfolio Overview")
    
    if st.session_state.positions:
        st.markdown("#### Open Positions")
        positions_df = pd.DataFrame(st.session_state.positions.values())
        st.dataframe(positions_df, use_container_width=True)
        
        # Close position button
        position_to_close = st.selectbox("Select position to close:", 
                                          list(st.session_state.positions.keys()))
        if st.button("Close Position"):
            if position_to_close in st.session_state.positions:
                del st.session_state.positions[position_to_close]
                st.success(f"Closed position: {position_to_close}")
                st.rerun()
    else:
        st.info("No open positions. Execute signals from the Live Signals tab.")
    
    st.markdown("---")
    st.markdown("#### Trade History")
    if st.session_state.trades:
        trades_df = pd.DataFrame(st.session_state.trades)
        st.dataframe(trades_df, use_container_width=True)
    else:
        st.info("No trades executed yet.")


with tab4:
    st.markdown("### 🤖 Agent Status")
    
    agents = [
        {"name": "Regime Agent", "status": "🟢 Active", "genai": "No (SEBI Whitebox)", "desc": "BULL/BEAR/SIDEWAYS/VOLATILE classification"},
        {"name": "Sentiment Agent", "status": "🟢 Active", "genai": "✓ News Analysis", "desc": "Headlines sentiment scoring"},
        {"name": "Scanner Agent", "status": "🟢 Active", "genai": "✓ Stock Validation", "desc": "12 technical filters + GenAI"},
        {"name": "Strategy Agent", "status": "🟢 Active", "genai": "✓ Signal Validation", "desc": "15 strategies enabled"},
        {"name": "Risk Agent", "status": "🟢 Active", "genai": "No (SEBI Whitebox)", "desc": "Kelly Criterion, VIX scaling"},
        {"name": "Execution Agent", "status": "🟡 Paper Mode", "genai": "✓ Justification", "desc": "DhanHQ paper trading"},
        {"name": "Portfolio Agent", "status": "🟢 Active", "genai": "No", "desc": "P&L tracking"},
    ]
    
    for agent in agents:
        with st.expander(f"{agent['status']} {agent['name']}"):
            st.markdown(f"**Description:** {agent['desc']}")
            st.markdown(f"**GenAI:** {agent['genai']}")


# Footer
st.markdown("---")
st.markdown("""
<div style="text-align: center; color: #6c757d; padding: 20px;">
    <p>Agent Alpha v1.0 | Paper Trading Mode | Market Hours: 9:15 AM - 3:30 PM IST</p>
    <p>⚠️ This is a simulation. No real trades are executed.</p>
</div>
""", unsafe_allow_html=True)
