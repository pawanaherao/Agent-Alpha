// Global Types
export type MarketStatus = 'OPEN' | 'CLOSED' | 'PRE_OPEN';
export type TradingMode = 'LIVE' | 'PAPER';
export type MarketRegime = 'BULL' | 'BEAR' | 'SIDEWAYS' | 'VOLATILE';
export type SignalType = 'BUY' | 'SELL' | 'HOLD';

// Trading Signal
export interface TradingSignal {
    id: string;
    timestamp: string;
    symbol: string;
    strategy: string;
    signal: SignalType;
    price: number;
    score: number;
    stopLoss: number;
    target: number;
    reason?: string;
}

// Position
export interface Position {
    symbol: string;
    quantity: number;
    entryPrice: number;
    currentPrice: number;
    pnl: number;
    pnlPercent: number;
    strategyName: string;
}

// Market Data
export interface TickData {
    symbol: string;
    ltp: number;
    change: number;
    changePercent: number;
    volume: number;
    timestamp: string;
}

// Agent Status
export interface AgentStatus {
    name: string;
    status: 'ACTIVE' | 'INACTIVE' | 'ERROR';
    genAI: boolean;
    lastAction?: string;
    uptime?: string;
}

// Dashboard State
export interface DashboardState {
    mode: TradingMode;
    regime: MarketRegime;
    vix: number;
    capital: number;
    availableCapital: number;
    positions: Position[];
    signals: TradingSignal[];
    marketStatus: MarketStatus;
    strategyPerformance: StrategyPerformance[];
}

// Strategy Performance
export interface StrategyPerformance {
    strategyId: string;
    name: string;
    pnl: number;
    roi: number;
    winRate: number;
    trades: number;
    active: boolean;
}
