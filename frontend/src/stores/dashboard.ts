import { create } from 'zustand';
import { DashboardState, TradingMode, MarketRegime, Position, TradingSignal } from '@/types';

interface DashboardStore extends DashboardState {
    // Actions
    setMode: (mode: TradingMode) => void;
    setRegime: (regime: MarketRegime) => void;
    setVix: (vix: number) => void;
    addSignal: (signal: TradingSignal) => void;
    updatePosition: (symbol: string, position: Partial<Position>) => void;
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

    killSwitch: () => set((state) => ({
        positions: [],
        signals: [],
        availableCapital: state.capital
    }))
}));
