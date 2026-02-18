'use client';

import React, { useEffect, useRef, memo } from 'react';
import { createChart, ColorType, IChartApi, ISeriesApi, Time } from 'lightweight-charts';
import { useMarketStore } from '../../stores/marketStore';

export const HighPerformanceChart = memo(({ symbol }: { symbol: string }) => {
    const chartContainerRef = useRef<HTMLDivElement>(null);
    const chartRef = useRef<IChartApi | null>(null);
    const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);

    // Connect to store to get latest ticks
    const latestTicks = useMarketStore(state => state.latestTicks);

    useEffect(() => {
        if (!chartContainerRef.current) return;

        // Initialize Chart
        const handleResize = () => {
            chartRef.current?.applyOptions({ width: chartContainerRef.current?.clientWidth });
        };

        const chart = createChart(chartContainerRef.current, {
            layout: {
                background: { type: ColorType.Solid, color: '#111827' }, // Gray-900
                textColor: '#9CA3AF',
            },
            grid: {
                vertLines: { color: '#1F2937' },
                horzLines: { color: '#1F2937' },
            },
            width: chartContainerRef.current.clientWidth,
            height: 300,
            timeScale: {
                timeVisible: true,
                secondsVisible: true,
            },
        });

        // Add Series
        const series = chart.addCandlestickSeries({
            upColor: '#10B981',
            downColor: '#EF4444',
            borderVisible: false,
            wickUpColor: '#10B981',
            wickDownColor: '#EF4444',
        });

        // Set initial data (mock for now, real history in production)
        const initialData = generateInitialData();
        series.setData(initialData);

        chartRef.current = chart;
        seriesRef.current = series;

        window.addEventListener('resize', handleResize);

        return () => {
            window.removeEventListener('resize', handleResize);
            chart.remove();
        };
    }, []);

    // Update chart with real-time ticks
    useEffect(() => {
        if (!seriesRef.current || latestTicks.length === 0) return;

        // In a real app, you would aggregate ticks into candles
        // For this demo, we just verify the component receives updates
        // Implementation of Tick -> Candle aggregation would go here

    }, [latestTicks]);

    return (
        <div className="w-full h-full relative">
            <div
                ref={chartContainerRef}
                className="w-full h-[300px] border border-gray-800 rounded-lg overflow-hidden"
            />
            <div className="absolute top-2 left-2 bg-gray-900/80 px-2 py-1 rounded text-xs">
                {symbol} • 1M
            </div>
        </div>
    );
});

HighPerformanceChart.displayName = 'HighPerformanceChart';

// Helper to generate dummy history
function generateInitialData() {
    const data = [];
    let time = Math.floor(Date.now() / 1000) - 100 * 60;
    let value = 25000;

    for (let i = 0; i < 100; i++) {
        const open = value;
        const close = value + (Math.random() - 0.5) * 50;
        const high = Math.max(open, close) + Math.random() * 10;
        const low = Math.min(open, close) - Math.random() * 10;

        data.push({ time, open, high, low, close });
        time += 60;
        value = close;
    }
    return data;
}
