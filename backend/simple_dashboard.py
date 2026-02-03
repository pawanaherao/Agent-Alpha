"""
AGENT ALPHA - Simple Web Dashboard (Flask)
No complex dependencies - just open http://localhost:5000
"""

from flask import Flask, render_template_string, jsonify
import pandas as pd
import random
from datetime import datetime
import os

app = Flask(__name__)

# HTML Template with embedded CSS
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Agent Alpha - Trading Dashboard</title>
    <meta charset="UTF-8">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { 
            font-family: 'Segoe UI', Tahoma, sans-serif; 
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: white;
            min-height: 100vh;
        }
        .container { max-width: 1400px; margin: 0 auto; padding: 20px; }
        
        header {
            text-align: center;
            padding: 30px 0;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }
        header h1 {
            font-size: 2.5rem;
            background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        header p { color: #6c757d; margin-top: 5px; }
        
        .metrics { 
            display: grid; 
            grid-template-columns: repeat(4, 1fr); 
            gap: 20px; 
            margin: 30px 0;
        }
        .metric-card {
            background: rgba(255,255,255,0.05);
            border-radius: 12px;
            padding: 25px;
            text-align: center;
            border: 1px solid rgba(255,255,255,0.1);
        }
        .metric-card h3 { color: #6c757d; font-size: 0.9rem; margin-bottom: 10px; }
        .metric-card .value { font-size: 2rem; font-weight: bold; }
        .metric-card.bull .value { color: #00b894; }
        .metric-card.bear .value { color: #e74c3c; }
        .metric-card.neutral .value { color: #74b9ff; }
        
        .section { margin: 30px 0; }
        .section h2 { 
            color: #667eea; 
            margin-bottom: 20px; 
            padding-bottom: 10px;
            border-bottom: 2px solid #667eea;
        }
        
        table {
            width: 100%;
            border-collapse: collapse;
            background: rgba(255,255,255,0.02);
            border-radius: 8px;
            overflow: hidden;
        }
        th, td { 
            padding: 15px; 
            text-align: left; 
            border-bottom: 1px solid rgba(255,255,255,0.05);
        }
        th { background: rgba(102, 126, 234, 0.2); color: #667eea; }
        tr:hover { background: rgba(255,255,255,0.05); }
        
        .signal-buy { 
            background: linear-gradient(135deg, #00b894 0%, #00cec9 100%);
            padding: 5px 15px;
            border-radius: 20px;
            font-weight: bold;
        }
        .signal-watch { 
            background: linear-gradient(135deg, #f39c12 0%, #e67e22 100%);
            padding: 5px 15px;
            border-radius: 20px;
            font-weight: bold;
        }
        
        .btn {
            background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            padding: 12px 25px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 1rem;
            margin: 10px 5px;
        }
        .btn:hover { opacity: 0.9; }
        
        .agents-grid { 
            display: grid; 
            grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); 
            gap: 15px; 
        }
        .agent-card {
            background: rgba(255,255,255,0.05);
            border-radius: 10px;
            padding: 20px;
            border-left: 4px solid #00b894;
        }
        .agent-card h4 { color: #667eea; margin-bottom: 10px; }
        .agent-card .status { color: #00b894; }
        
        footer {
            text-align: center;
            padding: 30px;
            color: #6c757d;
            border-top: 1px solid rgba(255,255,255,0.1);
            margin-top: 50px;
        }
        
        @media (max-width: 768px) {
            .metrics { grid-template-columns: repeat(2, 1fr); }
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🚀 Agent Alpha</h1>
            <p>AI-Powered Trading System | Paper Trading Dashboard</p>
        </header>
        
        <div class="metrics">
            <div class="metric-card bull">
                <h3>📈 Market Regime</h3>
                <div class="value">{{ regime }}</div>
            </div>
            <div class="metric-card neutral">
                <h3>📊 India VIX</h3>
                <div class="value">{{ vix }}</div>
            </div>
            <div class="metric-card neutral">
                <h3>💰 Capital</h3>
                <div class="value">₹{{ capital }}</div>
            </div>
            <div class="metric-card neutral">
                <h3>📋 Active Strategies</h3>
                <div class="value">15</div>
            </div>
        </div>
        
        <div class="section">
            <h2>📡 Live Trading Signals</h2>
            <button class="btn" onclick="location.reload()">🔄 Refresh Signals</button>
            <table>
                <thead>
                    <tr>
                        <th>Time</th>
                        <th>Symbol</th>
                        <th>Strategy</th>
                        <th>Signal</th>
                        <th>Price</th>
                        <th>Score</th>
                        <th>Stop Loss</th>
                        <th>Target</th>
                    </tr>
                </thead>
                <tbody>
                    {% for signal in signals %}
                    <tr>
                        <td>{{ signal.time }}</td>
                        <td><strong>{{ signal.symbol }}</strong></td>
                        <td>{{ signal.strategy }}</td>
                        <td><span class="signal-{{ signal.signal_class }}">{{ signal.signal }}</span></td>
                        <td>₹{{ signal.price }}</td>
                        <td>{{ signal.score }}/100</td>
                        <td>₹{{ signal.stop_loss }}</td>
                        <td>₹{{ signal.target }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        
        <div class="section">
            <h2>📊 Backtest Performance (Top 10)</h2>
            <table>
                <thead>
                    <tr>
                        <th>#</th>
                        <th>Strategy</th>
                        <th>Symbol</th>
                        <th>Sharpe</th>
                        <th>Win Rate</th>
                        <th>Trades</th>
                    </tr>
                </thead>
                <tbody>
                    {% for row in backtest %}
                    <tr>
                        <td>{{ loop.index }}</td>
                        <td>{{ row.strategy_name }}</td>
                        <td><strong>{{ row.symbol }}</strong></td>
                        <td style="color: {% if row.sharpe > 3 %}#00b894{% else %}#74b9ff{% endif %}">
                            {{ "%.2f"|format(row.sharpe) }}
                        </td>
                        <td>{{ "%.1f"|format(row.win_rate * 100) }}%</td>
                        <td>{{ row.total_trades|int }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        
        <div class="section">
            <h2>🤖 Agent Status</h2>
            <div class="agents-grid">
                <div class="agent-card">
                    <h4>Regime Agent</h4>
                    <p class="status">🟢 Active</p>
                    <p>Market classification: BULL/BEAR/SIDEWAYS/VOLATILE</p>
                    <p><em>GenAI: No (SEBI Whitebox)</em></p>
                </div>
                <div class="agent-card">
                    <h4>Sentiment Agent</h4>
                    <p class="status">🟢 Active</p>
                    <p>News sentiment analysis</p>
                    <p><em>GenAI: ✓ Headlines Analysis</em></p>
                </div>
                <div class="agent-card">
                    <h4>Scanner Agent</h4>
                    <p class="status">🟢 Active</p>
                    <p>12 technical filters + validation</p>
                    <p><em>GenAI: ✓ Stock Validation (10%)</em></p>
                </div>
                <div class="agent-card">
                    <h4>Strategy Agent</h4>
                    <p class="status">🟢 Active</p>
                    <p>15 strategies enabled</p>
                    <p><em>GenAI: ✓ Signal Validation</em></p>
                </div>
                <div class="agent-card">
                    <h4>Risk Agent</h4>
                    <p class="status">🟢 Active</p>
                    <p>Kelly Criterion, VIX scaling</p>
                    <p><em>GenAI: No (SEBI Whitebox)</em></p>
                </div>
                <div class="agent-card">
                    <h4>Execution Agent</h4>
                    <p class="status">🟡 Paper Mode</p>
                    <p>DhanHQ integration ready</p>
                    <p><em>GenAI: ✓ Trade Justification</em></p>
                </div>
            </div>
        </div>
        
        <footer>
            <p>Agent Alpha v1.0 | Paper Trading Mode | Market Hours: 9:15 AM - 3:30 PM IST</p>
            <p>⚠️ This is a simulation. No real trades are executed.</p>
        </footer>
    </div>
</body>
</html>
'''


def get_mock_signals():
    """Generate mock trading signals."""
    stocks = ["RELIANCE", "TCS", "HDFCBANK", "TATAMOTORS", "INFY", "SBIN", "NTPC", "TATASTEEL"]
    strategies = ["VWAP Reversion", "Momentum Rotation", "Swing Breakout", "ATR Breakout", "Sector Rotation"]
    
    signals = []
    for _ in range(random.randint(2, 5)):
        score = random.randint(55, 95)
        price = round(random.uniform(500, 3000), 2)
        signals.append({
            "time": datetime.now().strftime("%H:%M:%S"),
            "symbol": random.choice(stocks),
            "strategy": random.choice(strategies),
            "signal": "BUY" if score > 70 else "WATCH",
            "signal_class": "buy" if score > 70 else "watch",
            "price": f"{price:,.2f}",
            "score": score,
            "stop_loss": f"{price * 0.97:,.2f}",
            "target": f"{price * 1.05:,.2f}"
        })
    return signals


def load_backtest():
    """Load backtest results."""
    try:
        df = pd.read_csv("full_strategy_backtest.csv")
        return df.nlargest(10, 'sharpe').to_dict('records')
    except:
        return []


@app.route('/')
def dashboard():
    regime = random.choice(["BULL", "BEAR", "SIDEWAYS", "VOLATILE"])
    vix = round(random.uniform(12, 25), 2)
    
    return render_template_string(
        HTML_TEMPLATE,
        regime=regime,
        vix=vix,
        capital="10,00,000",
        signals=get_mock_signals(),
        backtest=load_backtest()
    )


@app.route('/api/signals')
def api_signals():
    return jsonify(get_mock_signals())


if __name__ == '__main__':
    print("\n" + "=" * 60)
    print("  AGENT ALPHA - Trading Dashboard")
    print("=" * 60)
    print("\n  Open your browser and go to:")
    print("\n  👉  http://localhost:5000")
    print("\n  Press Ctrl+C to stop the server")
    print("=" * 60 + "\n")
    
    app.run(host='0.0.0.0', port=5000, debug=False)
