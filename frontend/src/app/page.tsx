'use client';

import { useDashboard } from '@/stores/dashboard';
import { TradingChart } from '@/components/TradingChart';
import { PositionsGrid } from '@/components/PositionsGrid';
import { KillSwitch } from '@/components/KillSwitch';
import { TradingTerminal } from '@/components/TradingTerminal';

export default function Dashboard() {
  const {
    mode,
    regime,
    vix,
    capital,
    availableCapital,
    positions,
    setMode
  } = useDashboard();

  const deployed = capital - availableCapital;

  return (
    <div className="min-h-screen bg-zinc-950 text-white p-4">
      {/* Header */}
      <header className="bg-zinc-900 rounded-lg p-4 mb-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <h1 className="text-2xl font-bold bg-gradient-to-r from-purple-500 to-pink-500 bg-clip-text text-transparent">
              🚀 Agent Alpha
            </h1>
            <span className="text-gray-400 text-sm">AI-Powered Trading System</span>
          </div>

          <div className="flex items-center gap-4">
            {/* Mode Toggle */}
            <button
              onClick={() => setMode(mode === 'LIVE' ? 'PAPER' : 'LIVE')}
              className={`px-4 py-2 rounded-lg font-semibold transition-all ${mode === 'LIVE'
                ? 'bg-green-600 hover:bg-green-700'
                : 'bg-yellow-600 hover:bg-yellow-700'
                }`}
            >
              {mode === 'LIVE' ? '🟢 LIVE' : '🟡 PAPER'}
            </button>

            <KillSwitch />
          </div>
        </div>
      </header>

      {/* Metrics Bar */}
      <div className="grid grid-cols-4 gap-4 mb-4">
        <div className="bg-zinc-900 rounded-lg p-4">
          <p className="text-gray-400 text-sm mb-1">Market Regime</p>
          <p className={`text-2xl font-bold ${regime === 'BULL' ? 'text-green-500' :
            regime === 'BEAR' ? 'text-red-500' :
              regime === 'SIDEWAYS' ? 'text-yellow-500' :
                'text-purple-500'
            }`}>
            {regime}
          </p>
        </div>

        <div className="bg-zinc-900 rounded-lg p-4">
          <p className="text-gray-400 text-sm mb-1">India VIX</p>
          <p className="text-2xl font-bold text-blue-400">{vix.toFixed(2)}</p>
        </div>

        <div className="bg-zinc-900 rounded-lg p-4">
          <p className="text-gray-400 text-sm mb-1">Capital</p>
          <p className="text-2xl font-bold text-emerald-400">₹{(capital / 100000).toFixed(1)}L</p>
          <p className="text-xs text-gray-500">Deployed: ₹{(deployed / 100000).toFixed(1)}L</p>
        </div>

        <div className="bg-zinc-900 rounded-lg p-4">
          <p className="text-gray-400 text-sm mb-1">Open Positions</p>
          <p className="text-2xl font-bold text-purple-400">{positions.length}</p>
        </div>
      </div>

      {/* Main Grid */}
      <div className="grid grid-cols-3 gap-4 mb-4">
        <div className="col-span-2">
          <TradingChart symbol="NIFTY 50" />
        </div>

        <div className="bg-zinc-900 rounded-lg p-4">
          <h3 className="text-white font-semibold mb-3">Agent Status</h3>
          <div className="space-y-2">
            {[
              { name: 'Regime Agent', status: 'ACTIVE', genai: false },
              { name: 'Scanner Agent', status: 'ACTIVE', genai: true },
              { name: 'Strategy Agent', status: 'ACTIVE', genai: true },
              { name: 'Risk Agent', status: 'ACTIVE', genai: false },
              { name: 'Execution Agent', status: 'ACTIVE', genai: true },
            ].map(agent => (
              <div key={agent.name} className="flex items-center justify-between text-sm">
                <span className="text-gray-300">{agent.name}</span>
                <div className="flex items-center gap-2">
                  {agent.genai && <span className="text-xs text-purple-400">AI</span>}
                  <span className="text-green-500">●</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Positions */}
      <div className="bg-zinc-900 rounded-lg p-4 mb-4">
        <h3 className="text-white font-semibold mb-3">Open Positions</h3>
        <PositionsGrid positions={positions} />
      </div>

      {/* Trading Terminal Button */}
      <div className="flex justify-center">
        <TradingTerminal />
      </div>
    </div>
  );
}
