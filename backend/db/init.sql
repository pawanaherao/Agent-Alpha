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

-- Grant permissions
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO "user";
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO "user";
GRANT USAGE ON SCHEMA public TO "user";
