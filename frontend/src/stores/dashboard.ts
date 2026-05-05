import { create } from 'zustand';
import { DashboardState, TradingMode, ExecutionMode, MarketRegime, Position, TradingSignal, TradingApprovalRequest, StrategyPerformance, BrokerType, BrokerConnectionStatus, BrokerStatusInfo, UniverseType, StrategyCategory, StrategyModule, TradingStyle, ExecutionBrokerSetting, ExecutionBrokerConfig, ControlsSnapshot, StrategyControlEntry, RegimeOverrideState, PositionSizingState, RateLimitState, InstrumentFilterState, AlertThresholdState, ApprovalTimeoutState, BacktestConfigState, ActiveSetState, MaxDailyTradesState, OrdersPerSecondState, ConfluenceMinState, QualityGradeState, IVRegimePrefState } from '@/types';

interface DashboardStore extends DashboardState {
    // Actions
    setMode: (mode: TradingMode) => void;
    setExecutionMode: (executionMode: ExecutionMode) => void;
    setRegime: (regime: MarketRegime) => void;
    setSwingRegime: (regime: MarketRegime) => void;
    setVix: (vix: number) => void;
    addSignal: (signal: TradingSignal) => void;
    updatePosition: (symbol: string, position: Partial<Position>) => void;
    updateStrategyPerformance: (strategies: StrategyPerformance[]) => void;
    setPendingApprovals: (approvals: TradingApprovalRequest[]) => void;
    removePendingApproval: (requestId: string) => void;
    killSwitch: () => void;
    // Broker
    broker: BrokerType;
    brokerName: string;
    brokerStatus: BrokerConnectionStatus;
    brokerError: string | null;
    brokerInfo: BrokerStatusInfo | null;
    setBrokerInfo: (info: BrokerStatusInfo) => void;
    setBrokerStatus: (status: BrokerConnectionStatus, error?: string) => void;
    // Execution broker (manual override: 'auto' | 'dhan' | 'kotak')
    executionBroker: ExecutionBrokerSetting;
    executionBrokerConfig: ExecutionBrokerConfig | null;
    setExecutionBroker: (setting: ExecutionBrokerSetting) => void;
    setExecutionBrokerConfig: (config: ExecutionBrokerConfig) => void;
    // Universe + strategy selection
    setUniverse: (universe: UniverseType) => void;
    setStrategyFilter: (category: StrategyCategory) => void;
    setModuleFilter: (module: StrategyModule) => void;
    setTradingStyleFilter: (style: TradingStyle) => void;
    // ---- Manual Controls ----
    strategyControls: StrategyControlEntry[];
    activeSet: ActiveSetState;
    regimeOverride: RegimeOverrideState;
    positionSizing: PositionSizingState;
    rateLimitConfig: RateLimitState;
    instrumentFilter: InstrumentFilterState;
    alertThresholds: AlertThresholdState;
    approvalTimeout: ApprovalTimeoutState;
    backtestConfig: BacktestConfigState;
    maxDailyTrades: MaxDailyTradesState;
    ordersPerSecond: OrdersPerSecondState;
    confluenceMin: ConfluenceMinState;
    qualityGradeMin: QualityGradeState;
    ivRegimePrefs: IVRegimePrefState;
    controlsLoaded: boolean;
    setControlsSnapshot: (snapshot: ControlsSnapshot) => void;
    setStrategyControls: (strategies: StrategyControlEntry[]) => void;
    setRegimeOverride: (state: RegimeOverrideState) => void;
    setPositionSizing: (state: PositionSizingState) => void;
    setRateLimit: (state: RateLimitState) => void;
    setInstrumentFilter: (state: InstrumentFilterState) => void;
    setAlertThresholds: (state: AlertThresholdState) => void;
    setApprovalTimeout: (state: ApprovalTimeoutState) => void;
    setBacktestConfig: (state: BacktestConfigState) => void;
    setActiveSet: (state: ActiveSetState) => void;
    setMaxDailyTrades: (state: MaxDailyTradesState) => void;
    setOrdersPerSecond: (state: OrdersPerSecondState) => void;
    setConfluenceMin: (state: ConfluenceMinState) => void;
    setQualityGradeMin: (state: QualityGradeState) => void;
    setIVRegimePrefs: (state: IVRegimePrefState) => void;
}

export const useDashboard = create<DashboardStore>((set) => ({
    // Initial State
    mode: 'PAPER',
    executionMode: 'AUTO',
    regime: 'SIDEWAYS',
    swingRegime: 'SIDEWAYS',
    vix: 15.5,
    capital: 1000000,
    availableCapital: 1000000,
    positions: [],
    signals: [],
    pendingApprovals: [],
    marketStatus: 'CLOSED',
    universe: 'AUTO',
    strategyFilter: 'AUTO',
    moduleFilter: 'ALL',
    tradingStyleFilter: 'ALL',
    // Starts empty — populated by polling /api/portfolio/strategies every 30 s
    strategyPerformance: [],

    // Actions
    setMode: (mode) => set({ mode }),
    setExecutionMode: (executionMode) => set({ executionMode }),
    setRegime: (regime) => set({ regime }),
    setSwingRegime: (swingRegime) => set({ swingRegime }),
    setVix: (vix) => set({ vix }),
    setUniverse: (universe) => set({ universe }),
    setStrategyFilter: (strategyFilter) => set({ strategyFilter }),
    setModuleFilter: (moduleFilter) => set({ moduleFilter }),
    setTradingStyleFilter: (tradingStyleFilter) => set({ tradingStyleFilter }),

    // Broker
    broker: 'dhan',
    brokerName: 'DhanHQ',
    brokerStatus: 'disconnected',
    brokerError: null,
    brokerInfo: null,
    setBrokerInfo: (info) => set({
        brokerInfo: info,
        broker: info.broker,
        brokerName: info.brokerName,
        brokerStatus: info.connected ? 'connected' : 'disconnected',
        brokerError: null,
    }),
    setBrokerStatus: (status, error) => set({
        brokerStatus: status,
        brokerError: error ?? null,
    }),
    // Execution broker override
    executionBroker: 'auto',
    executionBrokerConfig: null,
    setExecutionBroker: (setting) => set({ executionBroker: setting }),
    setExecutionBrokerConfig: (config) => set({
        executionBrokerConfig: config,
        executionBroker: config.execution_broker,
    }),

    // ---- Manual Controls initial state ----
    strategyControls: [],
    controlsLoaded: false,
    activeSet: { active_set: [], mode: 'all_enabled', count: 32 },
    regimeOverride: { active: false, regime: null },
    positionSizing: { multiplier: 1.0, is_overridden: false },
    rateLimitConfig: { max_orders_per_cycle: 10, is_overridden: false },
    instrumentFilter: { blacklist: [], count: 0 },
    alertThresholds: {
        min_signal_strength: 0.6,
        min_strategy_score: 0.55,
        vix_warning_level: 20,
        daily_loss_warning: -2,
        approval_sound: true,
        is_overridden: false,
    },
    approvalTimeout: { timeout_seconds: 30, is_overridden: false },
    backtestConfig: {
        capital: 1000000,
        slippage_bps: 5,
        commission_per_order: 20,
        start_date: '2022-01-01',
        end_date: '',
        strategy_ids: [],
        universe: 'fno_50',
        period: '1Y',
        is_overridden: false,
    },
    maxDailyTrades: { max_daily_trades: 0, is_overridden: false, today_count: 0 },
    ordersPerSecond: { orders_per_second: 10, is_overridden: false },
    confluenceMin: { min_confluence_score: 3, is_overridden: false },
    qualityGradeMin: { min_quality_grade: 'C', is_overridden: false },
    ivRegimePrefs: { tiers: { IV_CHEAP: true, IV_NORMAL: true, IV_RICH: true, IV_EXTREME: true }, is_overridden: false },

    // ---- Manual Controls actions ----
    setControlsSnapshot: (snap) => set((state) => ({
        strategyControls: snap.strategies,
        activeSet: snap.active_set,
        regimeOverride: snap.regime_override,
        positionSizing: snap.position_sizing,
        rateLimitConfig: snap.rate_limit,
        instrumentFilter: snap.instrument_filter,
        alertThresholds: snap.alert_thresholds,
        approvalTimeout: snap.approval_timeout,
        backtestConfig: snap.backtest_config,
        maxDailyTrades: snap.max_daily_trades ?? state.maxDailyTrades,
        ordersPerSecond: snap.orders_per_second ?? state.ordersPerSecond,
        confluenceMin: snap.min_confluence_score ?? state.confluenceMin,
        qualityGradeMin: snap.min_quality_grade ?? state.qualityGradeMin,
        ivRegimePrefs: snap.iv_regime_preferences ?? state.ivRegimePrefs,
        controlsLoaded: true,
    })),
    setStrategyControls: (strategies) => set({ strategyControls: strategies }),
    setRegimeOverride: (state) => set({ regimeOverride: state }),
    setPositionSizing: (state) => set({ positionSizing: state }),
    setRateLimit: (state) => set({ rateLimitConfig: state }),
    setInstrumentFilter: (state) => set({ instrumentFilter: state }),
    setAlertThresholds: (state) => set({ alertThresholds: state }),
    setApprovalTimeout: (state) => set({ approvalTimeout: state }),
    setBacktestConfig: (state) => set({ backtestConfig: state }),
    setActiveSet: (state) => set({ activeSet: state }),
    setMaxDailyTrades: (state) => set({ maxDailyTrades: state }),
    setOrdersPerSecond: (state) => set({ ordersPerSecond: state }),
    setConfluenceMin: (state) => set({ confluenceMin: state }),
    setQualityGradeMin: (state) => set({ qualityGradeMin: state }),
    setIVRegimePrefs: (state) => set({ ivRegimePrefs: state }),

    addSignal: (signal) => set((state) => ({
        signals: [signal, ...state.signals].slice(0, 50) // Keep last 50
    })),

    updatePosition: (symbol, updates) => set((state) => ({
        positions: state.positions.map(p =>
            p.symbol === symbol ? { ...p, ...updates } : p
        )
    })),

    updateStrategyPerformance: (strategies) => {
        // Deduplicate by strategyId — last entry wins (handles stale truncated cache entries)
        const seen = new Map<string, StrategyPerformance>();
        for (const s of strategies) seen.set(s.strategyId, s);
        set({ strategyPerformance: Array.from(seen.values()) });
    },

    setPendingApprovals: (approvals) => set({ pendingApprovals: approvals }),

    removePendingApproval: (requestId) => set((state) => ({
        pendingApprovals: state.pendingApprovals.filter(a => a.id !== requestId)
    })),

    killSwitch: () => set((state) => ({
        positions: [],
        signals: [],
        pendingApprovals: [],
        availableCapital: state.capital
    }))
}));
