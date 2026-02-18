import { useRef, useEffect, useCallback } from 'react';
import { useMarketStore, MarketTick } from '../stores/marketStore';

/**
 * Custom hook to buffer incoming WebSocket ticks and update global state
 * at a throttled frame rate (e.g., 10Hz) to prevent main-thread blocking.
 */
export const useThrottledTick = (fps: number = 10) => {
    const bufferRef = useRef<MarketTick[]>([]);
    const updateMarketData = useMarketStore(state => state.bulkUpdateMarketData);

    // Push incoming tick to buffer
    const pushTick = useCallback((tick: MarketTick) => {
        bufferRef.current.push(tick);
    }, []);

    useEffect(() => {
        const interval = 1000 / fps;
        const timer = setInterval(() => {
            if (bufferRef.current.length > 0) {
                // flush buffer to store
                updateMarketData(bufferRef.current);
                bufferRef.current = [];
            }
        }, interval);

        return () => clearInterval(timer);
    }, [fps, updateMarketData]);

    return { pushTick };
};
