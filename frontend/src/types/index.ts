// Global Types
export type MarketStatus = 'OPEN' | 'CLOSED' | 'PRE_OPEN';
export type TradingMode = 'LIVE' | 'PAPER';
export type ExecutionMode = 'MANUAL' | 'HYBRID' | 'AUTO';
export type MarketRegime = 'BULL' | 'BEAR' | 'SIDEWAYS' | 'VOLATILE';
export type SignalType = 'BUY' | 'SELL' | 'HOLD';
export type OptionType = 'CE' | 'PE';
export type LegAction = 'BUY' | 'SELL';
export type BrokerType = 'dhan' | 'kotak';
export type BrokerConnectionStatus = 'connected' | 'disconnected' | 'error' | 'switching';

/**
 * Execution broker user setting:
 *   'auto'  — smart routing (strategy table + VIX/time rules)
 *   'dhan'  — force ALL orders to DhanHQ (fastest, ~₹499/month)
 *   'kotak' — force ALL orders to Kotak Neo (FREE)
 * Data plane is always DhanHQ regardless of this setting.
 */
export type ExecutionBrokerSetting = 'auto' | 'dhan' | 'kotak';

export interface ExecutionBrokerOption {
  id: ExecutionBrokerSetting;
  label: string;
  description: string;
  cost: string;
  icon: string;
}

export interface ExecutionBrokerConfig {
  execution_broker: ExecutionBrokerSetting;   // user's setting
  effective_broker: BrokerType;               // resolved right now
  data_broker: 'dhan';                        // always
  data_broker_name: 'DhanHQ';                 // always
  vix: number;
  options: ExecutionBrokerOption[];
  routing_note: string;
  audit_note: string;
}

// Universe & Strategy selection
export type UniverseType =
  | 'AUTO' | 'NIFTY_50' | 'NIFTY_100' | 'NIFTY_200' | 'FNO_50' | 'FNO_200'
  | 'BSE_SENSEX' | 'BSE_100' | 'BSE_FNO' | 'BANKEX' | 'BANK_NIFTY'
  | 'BANKING' | 'INDICES' | 'FNO';  // legacy aliases
export type StrategyCategory =
  | 'AUTO'
  // ── New catalog CAT codes (Mar 2026 — matches strategy_catalog.py) ────────
  | 'TREND'   // Trend Following: Donchian, EMA Cross, Swing Breakout, Pullback
  | 'MR'      // Mean Reversion: VWAP, BB Squeeze, RSI Div, MR Scalper
  | 'MOM'     // Momentum: ORB, Rotation, ORB+VWAP, PFTH, Sector
  | 'EVENT'   // Event-Driven: Earnings Momentum, Gap Fill
  | 'VOL'     // Long Volatility: Straddle, Strangle, Butterfly, VIX, Vol Crush
  | 'THETA'   // Theta Collection: Iron Condor, Short Straddle/Strangle, Iron Butterfly
  | 'QUANT'   // Quant/Stat: Stat Arb, Vol Arb, Cross-Sectional Momentum, RS Pair
  | 'ML'      // Machine Learning: IsolationForest + Z-Score Structural Break
  | 'HEDGE'   // Hedging: Delta Hedge, Portfolio Hedge
  | 'MICRO'   // Deep Microstructure: VP+OFI Confluence (20L DhanHQ depth)
  // ── Legacy values (kept for Redis backward-compat; deprecated) ────────────
  | 'MOMENTUM' | 'MEAN_REVERSION' | 'OPTIONS' | 'INTRADAY' | 'VOLATILITY' | 'SECTOR';

/** Strategy module: Equity (cash) vs Options (derivatives). */
export type StrategyModule = 'ALL' | 'EQUITY' | 'OPTIONS';

/** Trading style: Intraday (same-day) | Swing (multi-day) | Multi (both timeframes). */
export type TradingStyle = 'ALL' | 'INTRADAY' | 'SWING' | 'MULTI';

export interface StrategyModuleOption {
  id: StrategyModule;
  label: string;
  description: string;
  default: boolean;
}

export interface TradingStyleOption {
  id: TradingStyle;
  label: string;
  description: string;
  default: boolean;
}

export interface UniverseOption {
  id: UniverseType;
  label: string;
  description: string;
  size: string;
  default: boolean;
}

export interface StrategyCategoryOption {
  id: StrategyCategory;
  label: string;
  description: string;
  default: boolean;
}

export interface BrokerStatusInfo {
  broker: BrokerType;
  brokerName: string;         // 'DhanHQ' | 'Kotak Neo'
  connected: boolean;
  paperTrading: boolean;
  fallbackBroker: BrokerType | null;
  failoverEnabled: boolean;
  lastError?: string;
  availableBrokers: Array<{
    id: BrokerType;
    name: string;
    cost: string;
    apiDocs: string;
  }>;
}
export type StructureType =
  | 'IRON_CONDOR' | 'IRON_BUTTERFLY' | 'BUTTERFLY'
  | 'LONG_CALL_SPREAD' | 'LONG_PUT_SPREAD'
  | 'SHORT_CALL_SPREAD' | 'SHORT_PUT_SPREAD'
  | 'LONG_STRADDLE' | 'SHORT_STRADDLE'
  | 'LONG_STRANGLE' | 'SHORT_STRANGLE'
  | 'SHORT_STRANGLE_WITH_WINGS'   // ML7: ThetaCapture 4-leg credit spread
  | 'DIRECTIONAL_BUY'             // ML6: IndexOptionsScalper ATM CE/PE
  | 'PROTECTIVE_PUT'              // ML11: PortfolioHedge PE hedge
  | 'CALENDAR_SPREAD' | 'DIAGONAL_SPREAD' | 'CUSTOM';

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
    geminiAdvisory?: string;
    geminiEnabled?: boolean;
}

// Trading Approval Request (MANUAL/HYBRID mode)
export interface TradingApprovalRequest {
    id: string;
    symbol: string;
    signal: TradingSignal;
    justification: string;
    timestamp: string;
    expiresAt: string;
    status: 'PENDING' | 'APPROVED' | 'REJECTED';
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
    /** INTRA (intraday MIS), CNC (equity delivery), NRML (F&O overnight) */
    product_type?: string;
    /** INTRADAY | SWING */
    trading_style?: string;
    /** Equity | Options | FNO */
    module?: string;
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
    displayName: string;
    status: 'ACTIVE' | 'INACTIVE' | 'ERROR' | 'RUNNING';
    genAI: boolean;
    genAIMode: 'DISABLED' | 'ADVISORY' | 'VALIDATION' | 'ANALYSIS';
    sebiCompliant: boolean;
    lastAction?: string;
    lastRunAt?: string;
    cycleTimeMs?: number;
    signalsToday?: number;
    description: string;
}

// Dashboard State
export interface DashboardState {
    mode: TradingMode;
    executionMode: ExecutionMode;
    /** Intraday regime: 3-month daily data, EMA 20/50, ADX 14 */
    regime: MarketRegime;
    /** Swing regime: 6-month daily data, EMA 14/28/50 — refreshed every 4 h */
    swingRegime: MarketRegime;
    vix: number;
    capital: number;
    availableCapital: number;
    positions: Position[];
    signals: TradingSignal[];
    pendingApprovals: TradingApprovalRequest[];
    marketStatus: MarketStatus;
    strategyPerformance: StrategyPerformance[];
    // User-selected scan universe and strategy category
    universe: UniverseType;
    strategyFilter: StrategyCategory;
    moduleFilter: StrategyModule;
    tradingStyleFilter: TradingStyle;
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

// ─── Options Types ───────────────────────────────────────────────────────────
export interface Greeks {
    delta: number;
    gamma: number;
    vega: number;
    theta: number;
    rho?: number;
    iv: number;
    ivRank: number;
}

export interface OptionLeg {
    legId: string;
    symbol: string;
    optionType: OptionType;
    strike: number;
    expiry: string;
    action: LegAction;
    quantity: number;
    premium: number;
    currentPremium: number;
    pnl: number;
    greeks?: Greeks;
}

export interface MultiLegOptionsPosition {
    positionId: string;
    symbol: string;
    strategyName: string;
    structureType: StructureType;
    legs: OptionLeg[];
    netPremium: number;
    maxProfit?: number;
    maxLoss?: number;
    breakevens?: number[];
    entryPrice: number;
    entryTime: string;
    status: 'OPEN' | 'CLOSED' | 'ADJUSTED' | 'EXPIRED';
    realizedPnl: number;
    unrealizedPnl: number;
    portfolioGreeks?: Greeks;
    geminiAdvisory?: string;
}

export interface OptionChainOpportunity {
    symbol: string;
    structure: string;
    score: number;
    ivRank: number;
    atmIv: number;
    oiPcr: number;
    atmStrike: number;
    spotPrice: number;
    expiry: string;
    geminiAdvisory?: string;
    geminiEnabled?: boolean;
}

// ─── Sentiment / Intelligence Types ──────────────────────────────────────────
export interface SentimentData {
    symbol: string;
    score: number;       // -1 to +1
    label: 'BULLISH' | 'BEARISH' | 'NEUTRAL';
    headlines: string[];
    source: 'GenAI' | 'Rules';
    analysedAt: string;
    geminiSummary?: string;
}

export interface RegimeData {
    regime: MarketRegime;
    confidence: number;
    adx: number;
    vixLevel: number;
    emaTrend: string;
    switchedAt?: string;
    description: string;
}

export interface GeminiAdvisoryLog {
    id: string;
    timestamp: string;
    agent: string;
    symbol: string;
    advisory: string;
    sebiNote: string;
}

// ─── Risk Types ───────────────────────────────────────────────────────────────
export interface RiskMetrics {
    portfolioHeat: number;      // 0-1 (fraction at risk)
    dailyLossPct: number;       // negative number
    killSwitchActive: boolean;
    killSwitchThreshold: number; // e.g. -0.05
    positionsAtRisk: number;
    marginUsedPct: number;
    autoCloseoutEnabled: boolean;
    lastCloseoutAt?: string;
    closeoutPositionsCount?: number;
}

// ─── Manual Controls Types ───────────────────────────────────────────────────

/** Expanded strategy category set — matches strategy_catalog.py FILTER_DIMENSIONS.category */
export type FullStrategyCategory =
  | 'TREND' | 'MR' | 'MOM' | 'EVENT' | 'VOL' | 'THETA'
  | 'QUANT' | 'ML' | 'HEDGE' | 'MICRO'
  // Legacy labels (from pre-Mar-2026 strategy manager)
  | 'MOMENTUM' | 'MEAN_REVERSION' | 'SWING' | 'OPTIONS' | 'HEDGING' | 'VOLATILITY' | 'META';

/** One row in the strategy manager table. */
export interface StrategyControlEntry {
  id: string;
  name: string;
  category: FullStrategyCategory;
  module: 'EQUITY' | 'OPTIONS';
  default_broker: 'dhan' | 'kotak';
  intraday: boolean;
  enabled: boolean;
  circuit_breaker_triggered: boolean;
  circuit_breaker_reason: string;
  today_pnl: number;
  max_loss: number | null;
  max_loss_pct: number | null;
  inActiveSet?: boolean;
}

/** Active strategy subset response. */
export interface ActiveSetState {
  active_set: string[];
  mode: 'subset' | 'all_enabled';
  count: number;
}

/** Market regime override state. */
export interface RegimeOverrideState {
  active: boolean;
  regime: MarketRegime | null;
  set_at?: string;
  expires_at?: string;
  duration_min?: number;
  reason?: string;
}

/** Position sizing override state. */
export interface PositionSizingState {
  multiplier: number;
  is_overridden: boolean;
  expires_at?: string;
  duration_hrs?: number;
  reason?: string;
}

/** Rate limiter state. */
export interface RateLimitState {
  max_orders_per_cycle: number;
  is_overridden: boolean;
  set_at?: string;
}

/** Instrument blacklist state. */
export interface InstrumentFilterState {
  blacklist: string[];
  count: number;
}

/** Alert threshold settings. */
export interface AlertThresholdState {
  min_signal_strength: number;
  min_strategy_score: number;
  vix_warning_level: number;
  daily_loss_warning: number;
  approval_sound: boolean;
  is_overridden: boolean;
}

/** Approval timeout state. */
export interface ApprovalTimeoutState {
  timeout_seconds: number;
  is_overridden: boolean;
  set_at?: string;
}

/** Max daily trades cap state. */
export interface MaxDailyTradesState {
  max_daily_trades: number;
  is_overridden: boolean;
  today_count?: number;
  set_at?: string;
}

/** SEBI orders-per-second cap state. */
export interface OrdersPerSecondState {
  orders_per_second: number;
  is_overridden: boolean;
  set_at?: string;
}

/** Min confluence score quality gate state. */
export interface ConfluenceMinState {
  min_confluence_score: number;
  is_overridden: boolean;
  set_at?: string;
}

/** Min quality grade threshold state. */
export interface QualityGradeState {
  min_quality_grade: string;
  is_overridden: boolean;
  set_at?: string;
}

/** IV regime preference state (per-tier allow/block). */
export interface IVRegimePrefState {
  tiers: Record<string, boolean>;
  is_overridden: boolean;
  set_at?: string;
}

/** Backtest run configuration. */
export interface BacktestConfigState {
  capital: number;
  slippage_bps: number;
  commission_per_order: number;
  start_date: string;
  end_date: string;
  strategy_ids: string[];
  universe: string;
  period: string;
  is_overridden: boolean;
}

/** Full aggregate snapshot from /api/controls/snapshot. */
export interface ControlsSnapshot {
  strategies: StrategyControlEntry[];
  active_set: ActiveSetState;
  regime_override: RegimeOverrideState;
  position_sizing: PositionSizingState;
  rate_limit: RateLimitState;
  instrument_filter: InstrumentFilterState;
  alert_thresholds: AlertThresholdState;
  approval_timeout: ApprovalTimeoutState;
  backtest_config: BacktestConfigState;
  max_daily_trades: MaxDailyTradesState;
  orders_per_second: OrdersPerSecondState;
  min_confluence_score: ConfluenceMinState;
  min_quality_grade: QualityGradeState;
  iv_regime_preferences: IVRegimePrefState;
}

/** SEBI audit log entry. */
export interface AuditLogEntry {
  ts: string;
  action: string;
  [key: string]: unknown;
}

// ─── Backtesting Types ────────────────────────────────────────────────────────
export interface BacktestMetrics {
    strategyId: string;
    strategyName: string;
    totalReturnPct: number;
    annualReturnPct: number;
    sharpeRatio: number;
    sortinoRatio: number;
    maxDrawdownPct: number;
    winRatePct: number;
    profitFactor: number;
    totalTrades: number;
    calmarRatio: number;
    recoveryFactor: number;
    passesProduction: boolean;
    failedCriteria: string[];
    equityCurve?: number[];
}

// ─── Intelligence Layer Types (Day 13 Sprint — alpha_intelligence.py) ────────

/** Probabilistic regime — replaces binary BULL/BEAR/SIDEWAYS/VOLATILE */
export interface RegimeProbabilities {
    BULL: number;
    BEAR: number;
    SIDEWAYS: number;
    VOLATILE: number;
}

/** VIX spike crash-capture signal */
export interface VixSpikeSignal {
    triggered: boolean;
    signal_type: string;       // e.g. "LONG_STRADDLE"
    strike: number;
    capital_pct: number;       // 0.02 = 2%
    vix_change_pct: number;
}

/** Kelly criterion feedback data */
export interface KellyFeedback {
    win_rate: number | null;
    trades: number;
    avg_win: number;
    avg_loss: number;
}

/** Per-strategy expected return edge */
export interface StrategyEdge {
    strategy_id: string;
    win_rate: number;
    trades: number;
    avg_win: number;
    avg_loss: number;
    expected_return: number;
    should_trade: boolean;
}

/** Position aging action */
export interface PositionAging {
    symbol: string;
    strategy: string;
    age_days: number;
    action: 'HOLD' | 'TIGHTEN_SL' | 'FORCE_CLOSE';
}

/** F2.3 Delta hedge drift entry */
export interface DeltaHedgeDrift {
    position_id: string;
    symbol: string;
    net_delta: number;
    lot_size: number;
    tier: 'URGENT' | 'NORMAL';
    action: string;
    hedge_qty?: number;
    hedge_side?: string;
}

/** F2.3 Delta hedge orchestrator status */
export interface DeltaHedgeStatus {
    checked_at: string;
    options_positions: number;
    urgent_hedges: DeltaHedgeDrift[];
    normal_drifts: DeltaHedgeDrift[];
    hedges_executed: number;
    hedges_skipped_cooldown: number;
    errors: string[];
}

/** Full intelligence summary from /api/intelligence/summary */
export interface IntelligenceSummary {
    regime_probabilities: RegimeProbabilities | null;
    vix_spike_signal: VixSpikeSignal | null;
    kelly: KellyFeedback;
    expected_return: number | null;
    edge_bps: number | null;
    position_aging: PositionAging[];
    strategy_edge: StrategyEdge[];
    delta_hedge_status: DeltaHedgeStatus | null;
}
