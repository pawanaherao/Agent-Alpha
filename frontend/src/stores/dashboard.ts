import { create } from 'zustand';
import { DashboardState, TradingMode, MarketRegime, Position, TradingSignal, StrategyPerformance } from '@/types';

interface DashboardStore extends DashboardState {
    // Actions
    setMode: (mode: TradingMode) => void;
    setRegime: (regime: MarketRegime) => void;
    setVix: (vix: number) => void;
    addSignal: (signal: TradingSignal) => void;
    updatePosition: (symbol: string, position: Partial<Position>) => void;
    updateStrategyPerformance: (strategies: StrategyPerformance[]) => void;
    killSwitch: () => void;
}

export const useDashboard = create<DashboardStore>((set) => ({
    // Initial State
    mode: 'PAPER',
    regime: 'SIDEWAYS',
    vix: 15.5,
    capital: 1000000,
    availableCapital: 1000000,
    positions: [],
    signals: [],
    marketStatus: 'CLOSED',
    strategyPerformance: [
        { strategyId: "ALPHA_ORB_001", name: "ORB Momentum", pnl: 14500, roi: 2.8, winRate: 65, trades: 14, active: true },
        { strategyId: "ALPHA_VWAP_002", name: "Mean Reversion", pnl: -2300, roi: -1.2, winRate: 45, trades: 9, active: true },
        { strategyId: "ALPHA_IRON_011", name: "Iron Condor", pnl: 8100, roi: 1.5, winRate: 88, trades: 42, active: false },
        { strategyId: "ALPHA_BREAKOUT_101", name: "Swing Breakout", pnl: 5200, roi: 3.4, winRate: 55, trades: 6, active: true },
    ],

    // Actions
    setMode: (mode) => set({ mode }),
    setRegime: (regime) => set({ regime }),
    setVix: (vix) => set({ vix }),

    addSignal: (signal) => set((state) => ({
        signals: [signal, ...state.signals].slice(0, 50) // Keep last 50
    })),

    updatePosition: (symbol, updates) => set((state) => ({
        positions: state.positions.map(p =>
            p.symbol === symbol ? { ...p, ...updates } : p
        )
    })),

    updateStrategyPerformance: (strategies) => set({ strategyPerformance: strategies }),

    killSwitch: () => set((state) => ({
        positions: [],
        signals: [],
        availableCapital: state.capital
    }))
}));
