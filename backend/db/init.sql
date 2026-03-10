-- ============================================================================
-- AGENTIC ALPHA - DATABASE SCHEMA INITIALIZATION
-- ============================================================================

-- Create trades table
CREATE TABLE IF NOT EXISTS trades (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    entry_price DECIMAL(10, 2) NOT NULL,
    current_price DECIMAL(10, 2),
    quantity INT NOT NULL,
    signal_type VARCHAR(20),
    status VARCHAR(20) DEFAULT 'OPEN',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);
CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
CREATE INDEX IF NOT EXISTS idx_trades_created_at ON trades(created_at);

-- Create execution logs table
CREATE TABLE IF NOT EXISTS execution_logs (
    id SERIAL PRIMARY KEY,
    strategy_name VARCHAR(100) NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    action VARCHAR(20),
    price DECIMAL(10, 2),
    quantity INT,
    execution_time TIMESTAMP,
    status VARCHAR(20),
    reason TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_exec_logs_strategy ON execution_logs(strategy_name);
CREATE INDEX IF NOT EXISTS idx_exec_logs_symbol ON execution_logs(symbol);
CREATE INDEX IF NOT EXISTS idx_exec_logs_created_at ON execution_logs(created_at);

-- Create risk assessment table
CREATE TABLE IF NOT EXISTS risk_assessment (
    id SERIAL PRIMARY KEY,
    portfolio_id VARCHAR(50),
    max_drawdown DECIMAL(5, 2),
    current_dd DECIMAL(5, 2),
    sharpe_ratio DECIMAL(5, 2),
    var_95 DECIMAL(5, 2),
    assessment_time TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_risk_portfolio ON risk_assessment(portfolio_id);
CREATE INDEX IF NOT EXISTS idx_risk_created_at ON risk_assessment(created_at);

-- Create portfolio state table
CREATE TABLE IF NOT EXISTS portfolio_state (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    quantity INT,
    avg_cost DECIMAL(10, 2),
    current_value DECIMAL(10, 2),
    regime VARCHAR(20),
    strategy_allocation DECIMAL(5, 2),
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_portfolio_symbol ON portfolio_state(symbol);

-- Create market data cache table
CREATE TABLE IF NOT EXISTS market_data_cache (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    timestamp TIMESTAMP NOT NULL,
    open DECIMAL(10, 2),
    high DECIMAL(10, 2),
    low DECIMAL(10, 2),
    close DECIMAL(10, 2),
    volume BIGINT,
    regime VARCHAR(20),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_market_data_symbol ON market_data_cache(symbol);
CREATE INDEX IF NOT EXISTS idx_market_data_timestamp ON market_data_cache(timestamp);
CREATE INDEX IF NOT EXISTS idx_market_data_symbol_time ON market_data_cache(symbol, timestamp);

-- ============================================================================
-- Open positions table - source of truth for SL/TP monitoring
-- ============================================================================
CREATE TABLE IF NOT EXISTS open_positions (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(50) NOT NULL,
    security_id VARCHAR(30),
    exchange_segment VARCHAR(20),
    product_type VARCHAR(20),
    strategy_id VARCHAR(100),
    signal_id VARCHAR(150),
    side VARCHAR(10) NOT NULL,           -- BUY or SELL
    quantity INT NOT NULL,
    entry_price DECIMAL(12, 4) NOT NULL,
    stop_loss DECIMAL(12, 4),
    target_price DECIMAL(12, 4),
    order_id VARCHAR(100) UNIQUE,
    entry_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ltp DECIMAL(12, 4) DEFAULT 0,
    unrealized_pnl DECIMAL(12, 4) DEFAULT 0,
    realized_pnl DECIMAL(12, 4) DEFAULT 0,
    status VARCHAR(20) DEFAULT 'OPEN',   -- OPEN, CLOSED, SL_HIT, TARGET_HIT
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_open_positions_symbol ON open_positions(symbol);
CREATE INDEX IF NOT EXISTS idx_open_positions_status ON open_positions(status);
CREATE INDEX IF NOT EXISTS idx_open_positions_strategy ON open_positions(strategy_id);
CREATE INDEX IF NOT EXISTS idx_open_positions_signal ON open_positions(signal_id);

-- Daily PnL summary
CREATE TABLE IF NOT EXISTS daily_pnl (
    id SERIAL PRIMARY KEY,
    trade_date DATE NOT NULL DEFAULT CURRENT_DATE,
    realized_pnl DECIMAL(12, 4) DEFAULT 0,
    unrealized_pnl DECIMAL(12, 4) DEFAULT 0,
    total_trades INT DEFAULT 0,
    winning_trades INT DEFAULT 0,
    losing_trades INT DEFAULT 0,
    gross_pnl DECIMAL(12, 4) DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(trade_date)
);

CREATE INDEX IF NOT EXISTS idx_daily_pnl_date ON daily_pnl(trade_date);

-- ============================================================================
-- Options multi-leg positions
-- ============================================================================
CREATE TABLE IF NOT EXISTS options_positions (
    position_id    TEXT PRIMARY KEY,
    signal_id      TEXT,
    symbol         VARCHAR(50) NOT NULL,
    structure_type VARCHAR(40),
    status         VARCHAR(20) DEFAULT 'OPEN',
    legs_json      JSONB,
    net_premium    DECIMAL(12, 4) DEFAULT 0,
    max_profit     DECIMAL(12, 4),
    max_loss       DECIMAL(12, 4),
    realized_pnl   DECIMAL(12, 4) DEFAULT 0,
    greeks_json    JSONB,
    expiry         VARCHAR(20),
    opened_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    closed_at      TIMESTAMP,
    updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_opts_pos_symbol   ON options_positions(symbol);
CREATE INDEX IF NOT EXISTS idx_opts_pos_status   ON options_positions(status);
CREATE INDEX IF NOT EXISTS idx_opts_pos_expiry   ON options_positions(expiry);

-- Grant permissions
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO "user";
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO "user";
GRANT USAGE ON SCHEMA public TO "user";
