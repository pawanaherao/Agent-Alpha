'use client';

import { useEffect, useRef, useState } from 'react';

interface ChartProps {
    symbol: string;
    data?: any[];
}

export function TradingChart({ symbol, data = [] }: ChartProps) {
    const chartContainerRef = useRef<HTMLDivElement>(null);
    const [chartLoaded, setChartLoaded] = useState(false);

    useEffect(() => {
        if (!chartContainerRef.current) return;

        let chart: any = null;
        let candlestickSeries: any = null;

        // Dynamic import to avoid SSR issues
        import('lightweight-charts').then(({ createChart, ColorType }) => {
            if (!chartContainerRef.current) return;

            chart = createChart(chartContainerRef.current, {
                layout: {
                    background: { type: ColorType.Solid, color: '#0a0a0a' },
                    textColor: '#d1d4dc',
                },
                grid: {
                    vertLines: { color: '#1e222d' },
                    horzLines: { color: '#1e222d' },
                },
                width: chartContainerRef.current.clientWidth,
                height: 400,
            });

            candlestickSeries = chart.addCandlestickSeries({
                upColor: '#26a69a',
                downColor: '#ef5350',
                borderUpColor: '#26a69a',
                borderDownColor: '#ef5350',
                wickUpColor: '#26a69a',
                wickDownColor: '#ef5350',
            });

            // Mock data for demonstration
            const mockData = [
                { time: '2024-01-01', open: 24000, high: 24200, low: 23900, close: 24100 },
                { time: '2024-01-02', open: 24100, high: 24300, low: 24050, close: 24250 },
                { time: '2024-01-03', open: 24250, high: 24400, low: 24200, close: 24350 },
                { time: '2024-01-04', open: 24350, high: 24500, low: 24300, close: 24450 },
                { time: '2024-01-05', open: 24450, high: 24600, low: 24400, close: 24550 },
            ];

            candlestickSeries.setData(data.length > 0 ? data : mockData);
            chart.timeScale().fitContent();
            setChartLoaded(true);
        });

        const handleResize = () => {
            if (chartContainerRef.current && chart) {
                chart.applyOptions({ width: chartContainerRef.current.clientWidth });
            }
        };

        window.addEventListener('resize', handleResize);

        return () => {
            window.removeEventListener('resize', handleResize);
            if (chart) chart.remove();
        };
    }, [symbol, data]);

    return (
        <div className="bg-zinc-900 rounded-lg p-4">
            <div className="flex items-center justify-between mb-2">
                <h3 className="text-white font-semibold">{symbol}</h3>
                <span className="text-green-500 text-sm">+1.2%</span>
            </div>
            <div ref={chartContainerRef} className="h-[400px]">
                {!chartLoaded && (
                    <div className="h-full flex items-center justify-center text-gray-400">
                        Loading chart...
                    </div>
                )}
            </div>
        </div>
    );
}
