'use client';

import React, { memo, useEffect, useRef } from 'react';
import { createChart, ColorType, IChartApi, ISeriesApi } from 'lightweight-charts';
import { ArrowUpRight, ArrowDownRight, TrendingUp, Activity, AlertTriangle } from 'lucide-react';
import { useDashboard } from '../../stores/dashboard';
import { StrategyPerformance } from '@/types';

export const StrategyPnL = memo(() => {
    const chartContainerRef = useRef<HTMLDivElement>(null);
    const chartRef = useRef<IChartApi | null>(null);
    const areaSeriesRef = useRef<ISeriesApi<"Area"> | null>(null);

    // Get real strategy data from store
    const strategies = useDashboard(state => state.strategyPerformance);

    const totalPnL = strategies.reduce((acc: number, s: StrategyPerformance) => acc + s.pnl, 0);
    const totalTrades = strategies.reduce((acc: number, s: StrategyPerformance) => acc + s.trades, 0);
    const winRate = totalTrades > 0
        ? Math.round(strategies.reduce((acc: number, s: StrategyPerformance) => acc + (s.winRate * s.trades), 0) / totalTrades)
        : 0;

    // Initialize Equity Curve Chart
    useEffect(() => {
        if (!chartContainerRef.current) return;

        const chart = createChart(chartContainerRef.current, {
            layout: {
                background: { type: ColorType.Solid, color: '#111827' }, // gray-900
                textColor: '#9CA3AF',
            },
            grid: {
                vertLines: { color: '#374151' },
                horzLines: { color: '#374151' },
            },
            width: chartContainerRef.current.clientWidth,
            height: 200,
            timeScale: {
                timeVisible: true,
                secondsVisible: false,
            },
        });

        const areaSeries = chart.addAreaSeries({
            lineColor: '#10B981',
            topColor: 'rgba(16, 185, 129, 0.4)',
            bottomColor: 'rgba(16, 185, 129, 0.0)',
            lineWidth: 2,
        });

        // Generate Mock Equity Curve (TODO: Connect to backend history)
        const data = [];
        let value = 100000; // Starting capital
        const now = new Date();
        for (let i = 0; i < 100; i++) {
            const time = new Date(now.getTime() - (100 - i) * 60000); // Past 100 minutes
            // Random walk with drift
            const change = (Math.random() - 0.45) * 200;
            value += change;
            data.push({
                time: time.getTime() / 1000 as any, // Timestamp for lightweight-charts
                value: value
            });
        }

        areaSeries.setData(data);
        chart.timeScale().fitContent();

        chartRef.current = chart;
        areaSeriesRef.current = areaSeries;

        const handleResize = () => {
            if (chartContainerRef.current) {
                chart.applyOptions({ width: chartContainerRef.current.clientWidth });
            }
        };

        window.addEventListener('resize', handleResize);

        return () => {
            window.removeEventListener('resize', handleResize);
            chart.remove();
        };
    }, []);

    return (
        <div className="border border-gray-800 bg-gray-900 rounded-lg p-4 flex flex-col gap-6">
            {/* Header & Stats Grid */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div className="p-3 bg-gray-800/50 rounded-lg border border-gray-700">
                    <p className="text-xs text-gray-400 font-medium mb-1">Total P&L</p>
                    <div className={`text-xl font-mono font-bold flex items-center gap-2 ${totalPnL >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                        {totalPnL >= 0 ? <TrendingUp size={18} /> : <TrendingUp size={18} className="rotate-180" />}
                        ₹{totalPnL.toLocaleString()}
                    </div>
                </div>

                <div className="p-3 bg-gray-800/50 rounded-lg border border-gray-700">
                    <p className="text-xs text-gray-400 font-medium mb-1">Win Rate</p>
                    <div className="text-xl font-mono font-bold text-blue-400 flex items-center gap-2">
                        <Activity size={18} />
                        {winRate}%
                    </div>
                </div>

                <div className="p-3 bg-gray-800/50 rounded-lg border border-gray-700">
                    <p className="text-xs text-gray-400 font-medium mb-1">Max Drawdown</p>
                    <div className="text-xl font-mono font-bold text-orange-400 flex items-center gap-2">
                        <ArrowDownRight size={18} />
                        -2.4%
                    </div>
                </div>

                <div className="p-3 bg-gray-800/50 rounded-lg border border-gray-700">
                    <p className="text-xs text-gray-400 font-medium mb-1">Active Strategies</p>
                    <div className="text-xl font-mono font-bold text-purple-400 flex items-center gap-2">
                        <AlertTriangle size={18} />
                        {strategies.filter(s => s.active).length}/{strategies.length}
                    </div>
                </div>
            </div>

            {/* Equity Curve Chart */}
            <div className="h-[200px] w-full border border-gray-800 rounded bg-gray-900 overflow-hidden relative">
                <div className="absolute top-2 left-2 z-10 text-xs font-bold text-gray-500 uppercase tracking-wider">
                    Portfolio Equity Curve
                </div>
                <div ref={chartContainerRef} className="w-full h-full" />
            </div>

            {/* Strategy List */}
            <div>
                <h3 className="text-gray-400 text-xs font-bold uppercase tracking-wider mb-3">Live Strategies</h3>
                <div className="space-y-2">
                    {strategies.map((strat) => (
                        <div key={strat.strategyId} className="flex justify-between items-center p-2 hover:bg-gray-800 rounded transition-colors border border-transparent hover:border-gray-700">
                            <div className="flex items-center gap-3">
                                <span className={`w-2 h-2 rounded-full shadow-[0_0_8px] ${strat.active ? 'bg-green-500 shadow-green-500/50 animate-pulse' : 'bg-gray-600 shadow-none'}`} />
                                <div>
                                    <p className="text-sm font-medium text-gray-200">{strat.name}</p>
                                    <p className="text-xs text-gray-500">{strat.trades} trades • {strat.winRate}% win</p>
                                </div>
                            </div>

                            <div className="text-right">
                                <p className={`font-mono text-sm font-bold ${strat.pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                    {strat.pnl >= 0 ? '+' : ''}{strat.pnl.toLocaleString()}
                                </p>
                                <div className="flex items-center justify-end gap-1 text-xs text-gray-500">
                                    {strat.roi > 0 ? <ArrowUpRight size={12} className="text-green-500" /> : <ArrowDownRight size={12} className="text-red-500" />}
                                    {Math.abs(strat.roi)}% ROI
                                </div>
                            </div>
                        </div>
                    ))}
                </div>
            </div>
        </div>
    );
});

StrategyPnL.displayName = 'StrategyPnL';
