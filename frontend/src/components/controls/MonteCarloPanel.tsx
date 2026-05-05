'use client';

import React, { useState } from 'react';
import { api } from '@/lib/api';

interface MCResult {
  n_simulations: number;
  n_trades_per_sim: number;
  method: string;
  initial_capital: number;
  terminal_wealth_mean: number;
  terminal_wealth_median: number;
  terminal_wealth_p5: number;
  terminal_wealth_p25: number;
  terminal_wealth_p75: number;
  terminal_wealth_p95: number;
  cagr_mean: number;
  cagr_median: number;
  cagr_p5: number;
  cagr_p95: number;
  max_drawdown_mean: number;
  max_drawdown_median: number;
  max_drawdown_p95: number;
  probability_of_ruin: number;
  ruin_threshold: number;
  sharpe_mean: number;
  sharpe_median: number;
  sharpe_p5: number;
  sharpe_p95: number;
  win_rate: number;
  profit_factor: number;
}

export function MonteCarloPanel() {
  const [nSims, setNSims] = useState(5000);
  const [nTrades, setNTrades] = useState(252);
  const [capital, setCapital] = useState(1000000);
  const [method, setMethod] = useState<'trade' | 'block' | 'parametric'>('block');
  const [blockSize, setBlockSize] = useState(5);
  const [ruinThreshold, setRuinThreshold] = useState(0.30);
  const [returnsInput, setReturnsInput] = useState('');
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<MCResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const runSimulation = async () => {
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      // Parse returns: comma-separated or one per line
      const returns = returnsInput
        .split(/[,\n]+/)
        .map(s => s.trim())
        .filter(s => s.length > 0)
        .map(Number)
        .filter(n => !isNaN(n));

      if (returns.length < 10) {
        setError('Need at least 10 trade returns. Enter comma-separated values or one per line.');
        return;
      }

      const res = await api.fetch('/api/backtest/monte-carlo/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          trade_returns: returns,
          n_simulations: nSims,
          n_trades_per_sim: nTrades,
          initial_capital: capital,
          method,
          block_size: blockSize,
          ruin_threshold: ruinThreshold,
        }),
      });
      const data = await res.json();
      if (!res.ok || !data.success) throw new Error(data.error || 'Simulation failed');
      setResult(data.result);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Simulation failed');
    } finally {
      setRunning(false);
    }
  };

  const pct = (v: number) => `${(v * 100).toFixed(2)}%`;
  const fmt = (v: number) => `₹${v.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`;

  return (
    <div className="space-y-5">
      <h3 className="text-sm font-bold text-cyan-400 uppercase tracking-wide">🎲 Monte Carlo Simulator</h3>

      {/* ── Configuration ─────────────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div>
          <label className="text-xs text-gray-400 block mb-1">Simulations</label>
          <input type="number" value={nSims} onChange={e => setNSims(Number(e.target.value))}
            className="w-full bg-gray-900 text-white text-sm px-2 py-1.5 rounded border border-gray-700" />
        </div>
        <div>
          <label className="text-xs text-gray-400 block mb-1">Trades/Sim</label>
          <input type="number" value={nTrades} onChange={e => setNTrades(Number(e.target.value))}
            className="w-full bg-gray-900 text-white text-sm px-2 py-1.5 rounded border border-gray-700" />
        </div>
        <div>
          <label className="text-xs text-gray-400 block mb-1">Initial Capital (₹)</label>
          <input type="number" value={capital} onChange={e => setCapital(Number(e.target.value))}
            className="w-full bg-gray-900 text-white text-sm px-2 py-1.5 rounded border border-gray-700" />
        </div>
        <div>
          <label className="text-xs text-gray-400 block mb-1">Method</label>
          <select value={method} onChange={e => setMethod(e.target.value as 'trade' | 'block' | 'parametric')}
            className="w-full bg-gray-900 text-white text-sm px-2 py-1.5 rounded border border-gray-700">
            <option value="block">Block Bootstrap</option>
            <option value="trade">Trade Bootstrap (IID)</option>
            <option value="parametric">Parametric (Student-t)</option>
          </select>
        </div>
        <div>
          <label className="text-xs text-gray-400 block mb-1">Block Size</label>
          <input type="number" value={blockSize} onChange={e => setBlockSize(Number(e.target.value))}
            className="w-full bg-gray-900 text-white text-sm px-2 py-1.5 rounded border border-gray-700"
            disabled={method !== 'block'} />
        </div>
        <div>
          <label className="text-xs text-gray-400 block mb-1">Ruin Threshold</label>
          <input type="number" step="0.05" value={ruinThreshold} onChange={e => setRuinThreshold(Number(e.target.value))}
            className="w-full bg-gray-900 text-white text-sm px-2 py-1.5 rounded border border-gray-700" />
        </div>
      </div>

      {/* ── Trade Returns Input ────────────────────────────────────────────── */}
      <div>
        <label className="text-xs text-gray-400 block mb-1">
          Trade Returns (comma-separated or one per line, e.g. 0.02, -0.01, 0.015…)
        </label>
        <textarea value={returnsInput} onChange={e => setReturnsInput(e.target.value)}
          rows={4}
          placeholder="0.02, -0.01, 0.015, 0.008, -0.005, 0.012, -0.003, 0.025, -0.008, 0.019..."
          className="w-full bg-gray-900 text-white text-xs px-3 py-2 rounded border border-gray-700 font-mono resize-y" />
      </div>

      <button onClick={runSimulation} disabled={running}
        className="bg-cyan-700 hover:bg-cyan-600 text-white px-5 py-2 rounded-lg font-medium text-sm transition-all disabled:opacity-50">
        {running ? '⏳ Running Simulation…' : '🎲 Run Monte Carlo'}
      </button>

      {error && (
        <div className="bg-red-900/40 border border-red-800 rounded-lg px-4 py-2 text-sm text-red-300">{error}</div>
      )}

      {/* ── Results ───────────────────────────────────────────────────────────── */}
      {result && (
        <div className="space-y-4">
          <div className="text-xs text-gray-500">
            {result.n_simulations.toLocaleString()} simulations × {result.n_trades_per_sim} trades | Method: {result.method}
          </div>

          {/* Terminal Wealth Distribution */}
          <div className="bg-gray-800/50 rounded-lg p-4 border border-gray-700/50">
            <h4 className="text-xs font-bold text-white uppercase mb-3">Terminal Wealth Distribution</h4>
            <div className="grid grid-cols-3 md:grid-cols-6 gap-2 text-center text-xs">
              <div className="bg-red-900/30 rounded p-2"><div className="text-red-400">P5</div><div className="text-white font-mono">{fmt(result.terminal_wealth_p5)}</div></div>
              <div className="bg-orange-900/30 rounded p-2"><div className="text-orange-400">P25</div><div className="text-white font-mono">{fmt(result.terminal_wealth_p25)}</div></div>
              <div className="bg-blue-900/30 rounded p-2"><div className="text-blue-400">Median</div><div className="text-white font-mono">{fmt(result.terminal_wealth_median)}</div></div>
              <div className="bg-blue-900/30 rounded p-2"><div className="text-blue-400">Mean</div><div className="text-white font-mono">{fmt(result.terminal_wealth_mean)}</div></div>
              <div className="bg-green-900/30 rounded p-2"><div className="text-green-400">P75</div><div className="text-white font-mono">{fmt(result.terminal_wealth_p75)}</div></div>
              <div className="bg-green-900/30 rounded p-2"><div className="text-green-400">P95</div><div className="text-white font-mono">{fmt(result.terminal_wealth_p95)}</div></div>
            </div>
          </div>

          {/* Key Metrics */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <div className="bg-gray-800/50 rounded-lg p-3 border border-gray-700/50 text-center">
              <div className="text-xs text-gray-400">CAGR (Median)</div>
              <div className={`text-lg font-bold ${result.cagr_median >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                {pct(result.cagr_median)}
              </div>
              <div className="text-[10px] text-gray-600">{pct(result.cagr_p5)} – {pct(result.cagr_p95)}</div>
            </div>
            <div className="bg-gray-800/50 rounded-lg p-3 border border-gray-700/50 text-center">
              <div className="text-xs text-gray-400">Sharpe (Median)</div>
              <div className={`text-lg font-bold ${result.sharpe_median >= 1 ? 'text-green-400' : result.sharpe_median >= 0 ? 'text-yellow-400' : 'text-red-400'}`}>
                {result.sharpe_median.toFixed(2)}
              </div>
              <div className="text-[10px] text-gray-600">{result.sharpe_p5.toFixed(2)} – {result.sharpe_p95.toFixed(2)}</div>
            </div>
            <div className="bg-gray-800/50 rounded-lg p-3 border border-gray-700/50 text-center">
              <div className="text-xs text-gray-400">Max DD (Median)</div>
              <div className="text-lg font-bold text-red-400">{pct(result.max_drawdown_median)}</div>
              <div className="text-[10px] text-gray-600">P95: {pct(result.max_drawdown_p95)}</div>
            </div>
            <div className="bg-gray-800/50 rounded-lg p-3 border border-gray-700/50 text-center">
              <div className="text-xs text-gray-400">P(Ruin &gt; {pct(result.ruin_threshold)})</div>
              <div className={`text-lg font-bold ${result.probability_of_ruin < 0.05 ? 'text-green-400' : result.probability_of_ruin < 0.20 ? 'text-yellow-400' : 'text-red-400'}`}>
                {pct(result.probability_of_ruin)}
              </div>
              <div className="text-[10px] text-gray-600">WR: {pct(result.win_rate)} | PF: {result.profit_factor.toFixed(2)}</div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
