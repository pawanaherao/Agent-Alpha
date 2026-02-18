'use client';

import React, { useEffect } from 'react';
import { useDashboard } from '@/stores/dashboard';
import { useMarketStore } from '@/stores/marketStore';
import { socket } from '@/lib/socket';
import { useThrottledTick } from '@/hooks/useThrottledTick';

// Components
import { HighPerformanceChart } from '@/components/dashboard/HighPerformanceChart';
import { OrderBook } from '@/components/dashboard/OrderBook';
import { StrategyPnL } from '@/components/dashboard/StrategyPnL';
import { PositionsGrid } from '@/components/PositionsGrid';
import { KillSwitch } from '@/components/KillSwitch';
import { TradingTerminal } from '@/components/TradingTerminal';

export default function Dashboard() {
  const {
    mode,
    capital,
    availableCapital,
    positions,
    setMode
  } = useDashboard();

  const { isConnected, setConnected } = useMarketStore();
  const { pushTick } = useThrottledTick(10); // 10Hz throttle

  // WebSocket Connection Logic
  useEffect(() => {
    socket.connect();

    function onConnect() {
      setConnected(true);
    }

    function onDisconnect() {
      setConnected(false);
    }

    function onMarketTick(data: any) {
      pushTick(data);
    }

    socket.on('connect', onConnect);
    socket.on('disconnect', onDisconnect);
    socket.on('market_tick', onMarketTick);

    return () => {
      socket.off('connect', onConnect);
      socket.off('disconnect', onDisconnect);
      socket.off('market_tick', onMarketTick);
      socket.disconnect();
    };
  }, [pushTick, setConnected]);

  const deployed = capital - availableCapital;

  // Mock Order Book Data (for visualization)
  const mockBids = Array.from({ length: 15 }, (_, i) => ({ price: 24350 - i * 0.5, quantity: Math.floor(Math.random() * 100) + 10 }));
  const mockAsks = Array.from({ length: 15 }, (_, i) => ({ price: 24350 + i * 0.5, quantity: Math.floor(Math.random() * 100) + 10 }));

  return (
    <div className="min-h-screen bg-black text-gray-300 font-sans p-4">
      {/* Header */}
      <header className="bg-gray-900 border border-gray-800 rounded-lg p-4 mb-4 flex items-center justify-between shadow-lg shadow-purple-900/10">
        <div className="flex items-center gap-4">
          <div className="w-10 h-10 bg-gradient-to-br from-indigo-600 to-purple-600 rounded-lg flex items-center justify-center text-white font-bold text-xl">
            A
          </div>
          <div>
            <h1 className="text-xl font-bold text-white tracking-wide">
              AGENT ALPHA <span className="text-purple-500 text-xs align-top">PRO</span>
            </h1>
            <div className="flex items-center gap-2">
              <div className={`w-2 h-2 rounded-full ${isConnected ? 'bg-green-500 animate-pulse' : 'bg-red-500'}`} />
              <span className="text-xs text-gray-400 font-mono">
                {isConnected ? 'SYSTEM ONLINE' : 'DISCONNECTED'}
              </span>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-4">
          <Link href="/strategy-builder" className="px-3 py-1.5 bg-blue-900/40 text-blue-400 border border-blue-800 rounded text-xs font-bold hover:bg-blue-800/50 transition-colors flex items-center gap-2">
            <span className="text-lg">🧠</span> STRATEGY AI
          </Link>
          {/* Connection Quality Indicator */}
          <div className="flex flex-col items-end mr-4">
            <span className="text-xs text-gray-500">LATENCY</span>
            <span className="text-green-400 font-mono text-sm">12ms</span>
          </div>

          <button
            onClick={() => setMode(mode === 'LIVE' ? 'PAPER' : 'LIVE')}
            className={`px-4 py-2 rounded-md font-bold text-sm transition-all border ${mode === 'LIVE'
              ? 'bg-red-900/30 border-red-600 text-red-500 hover:bg-red-900/50'
              : 'bg-yellow-900/30 border-yellow-600 text-yellow-500 hover:bg-yellow-900/50'
              }`}
          >
            {mode === 'LIVE' ? '🔴 LIVE EXECUTION' : '🟡 PAPER TRADING'}
          </button>

          <KillSwitch />
        </div>
      </header>

      {/* Main Command Center Grid */}
      <div className="grid grid-cols-12 gap-4 h-[calc(100vh-140px)]">

        {/* Left Col: Order Book & Watchlist (25%) */}
        <div className="col-span-3 flex flex-col gap-4">
          <div className="bg-gray-900 border border-gray-800 rounded-lg p-1 flex-1">
            <OrderBook bids={mockBids} asks={mockAsks} />
          </div>

          <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 h-1/3">
            <h3 className="text-xs font-bold text-gray-500 mb-2 uppercase">Watchlist</h3>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between items-center text-white">
                <span>NIFTY 50</span>
                <span className="text-green-400">24,350.55 (+0.4%)</span>
              </div>
              <div className="flex justify-between items-center text-white">
                <span>BANKNIFTY</span>
                <span className="text-green-400">52,100.20 (+0.6%)</span>
              </div>
              <div className="flex justify-between items-center text-white">
                <span>RELIANCE</span>
                <span className="text-red-400">2,890.00 (-0.2%)</span>
              </div>
            </div>
          </div>
        </div>

        {/* Center: Charts & Monitor (50%) */}
        <div className="col-span-12 lg:col-span-6 flex flex-col gap-4">
          {/* Chart Area */}
          <div className="bg-gray-900 border border-gray-800 rounded-lg flex-1 min-h-[400px] relative p-1">
            <HighPerformanceChart symbol="NIFTY 50" />
          </div>

          {/* Quick Stats Row */}
          <div className="grid grid-cols-3 gap-4 h-32">
            <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 flex flex-col justify-center text-center">
              <span className="text-gray-500 text-xs uppercase">Daily P&L</span>
              <span className="text-green-400 text-2xl font-mono font-bold">+₹14,205</span>
            </div>
            <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 flex flex-col justify-center text-center">
              <span className="text-gray-500 text-xs uppercase">Available Margin</span>
              <span className="text-white text-xl font-mono font-bold">₹{(availableCapital / 100000).toFixed(2)}L</span>
            </div>
            <div className="bg-gray-900 border border-gray-800 rounded-lg p-4 flex flex-col justify-center text-center">
              <span className="text-gray-500 text-xs uppercase">Active Positions</span>
              <span className="text-purple-400 text-2xl font-mono font-bold">{positions.length}</span>
            </div>
          </div>
        </div>

        {/* Right Col: Strategy & Control (25%) */}
        <div className="col-span-3 flex flex-col gap-4">
          {/* Strategy Performance */}
          <div className="flex-1">
            <StrategyPnL />
          </div>

          {/* Manual Terminal */}
          <div className="bg-gray-900 border border-gray-800 rounded-lg p-1">
            <div className="p-2 border-b border-gray-800">
              <h3 className="text-xs font-bold text-gray-400">MANUAL OVERRIDE</h3>
            </div>
            <div className="p-2">
              <TradingTerminal />
            </div>
          </div>
        </div>

      </div>
    </div>
  );
}
