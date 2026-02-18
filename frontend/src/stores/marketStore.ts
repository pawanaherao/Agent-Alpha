import { create } from 'zustand';

// Type definitions for Market Data
export interface MarketTick {
    symbol: string;
    ltp: number;
    change: number;
    volume: number;
    timestamp: string;
}

export interface OrderUpdate {
    orderId: string;
    status: 'PENDING' | 'EXECUTED' | 'REJECTED';
    price?: number;
    timestamp: string;
}

interface MarketState {
    isConnected: boolean;
    marketData: Map<string, MarketTick>; // Map for O(1) access
    latestTicks: MarketTick[]; // Array for history/charts

    // Actions
    setConnected: (status: boolean) => void;
    updateMarketData: (tick: MarketTick) => void;
    bulkUpdateMarketData: (ticks: MarketTick[]) => void;
}

export const useMarketStore = create<MarketState>((set) => ({
    isConnected: false,
    marketData: new Map(),
    latestTicks: [],

    setConnected: (status) => set({ isConnected: status }),

    updateMarketData: (tick) => set((state) => {
        const newMap = new Map(state.marketData);
        newMap.set(tick.symbol, tick);

        // Keep last 100 ticks for quick debugging/charts
        const newHistory = [tick, ...state.latestTicks].slice(0, 100);

        return {
            marketData: newMap,
            latestTicks: newHistory
        };
    }),

    // Optimization: Handle batch updates to reduce re-renders
    bulkUpdateMarketData: (ticks) => set((state) => {
        const newMap = new Map(state.marketData);
        ticks.forEach(tick => newMap.set(tick.symbol, tick));
        return { marketData: newMap };
    })
}));
