'use client';

import React, { useState, useEffect } from 'react';
import { useDashboard } from '@/stores/dashboard';
import { api } from '@/lib/api';

interface UniverseOption {
  id: string;
  label: string;
  count: number;
  stocks: string[];
}

const PERIOD_OPTIONS = [
  { id: '6M',  label: '6 Months' },
  { id: '1Y',  label: '1 Year' },
  { id: '2Y',  label: '2 Years' },
  { id: '3Y',  label: '3 Years' },
  { id: '5Y',  label: '5 Years' },
];

export function BacktestConfig() {
  const { backtestConfig, strategyControls, setBacktestConfig } = useDashboard();

  const [capital,     setCapital]    = useState(backtestConfig.capital);
  const [slippage,    setSlippage]   = useState(backtestConfig.slippage_bps);
  const [commission,  setCommission] = useState(backtestConfig.commission_per_order);
  const [startDate,   setStartDate]  = useState(backtestConfig.start_date);
  const [endDate,     setEndDate]    = useState(backtestConfig.end_date);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(
    new Set(backtestConfig.strategy_ids)
  );
  const [universe,    setUniverse]   = useState(backtestConfig.universe || 'fno_50');
  const [period,      setPeriod]     = useState(backtestConfig.period || '1Y');
  const [universes,   setUniverses]  = useState<UniverseOption[]>([]);
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState(false);
  const [msg,    setMsg]    = useState<{ text: string; ok: boolean } | null>(null);

  /* Load available universes from backend */
  useEffect(() => {
    api.fetch('/api/backtest/universes')
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d?.universes) setUniverses(d.universes); })
      .catch(() => {});
  }, []);

  const toast = (text: string, ok = true) => {
    setMsg({ text, ok });
    setTimeout(() => setMsg(null), 3500);
  };

  const handleIdToggle = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const handleSelectAll   = () => setSelectedIds(new Set(strategyControls.map((s) => s.id)));
  const handleClearSelect = () => setSelectedIds(new Set());

  const handleSave = async () => {
    setSaving(true);
    try {
      const body = {
        capital,
        slippage_bps:         slippage,
        commission_per_order: commission,
        start_date:           startDate,
        end_date:             endDate,
        strategy_ids:         [...selectedIds],
        universe,
        period,
      };
      const res = await api.fetch(`/api/controls/backtest-config`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed');
      setBacktestConfig({ ...data, is_overridden: true });
      toast('Backtest configuration saved');
    } catch (e: unknown) {
      toast(e instanceof Error ? e.message : 'Error', false);
    } finally {
      setSaving(false);
    }
  };

  const handleRunBacktest = async () => {
    setRunning(true);
    try {
      const res = await api.fetch('/api/backtest/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ universe, period, capital }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed to start');
      toast(`Backtest started: ${data.stockCount} stocks, ${period} period`);
    } catch (e: unknown) {
      toast(e instanceof Error ? e.message : 'Error starting backtest', false);
    } finally {
      setRunning(false);
    }
  };

  const categorised = strategyControls.reduce<Record<string, typeof strategyControls>>((acc, s) => {
    (acc[s.category] = acc[s.category] || []).push(s);
    return acc;
  }, {});

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-semibold text-white">Backtest Configuration</h2>

      {msg && (
        <div className={`px-3 py-2 rounded text-sm ${msg.ok ? 'bg-green-950 border border-green-800 text-green-300' : 'bg-red-950 border border-red-800 text-red-300'}`}>
          {msg.text}
        </div>
      )}

      {/* ── Universe & Period ──────────────────────────────────────────── */}
      <section className="bg-gray-900/50 border border-gray-800 rounded-lg p-4 space-y-4">
        <h3 className="text-sm font-semibold text-white">Universe & Period</h3>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* Universe */}
          <div>
            <label className="text-xs text-gray-400 block mb-1.5">Stock Universe</label>
            <div className="space-y-1.5">
              {(universes.length ? universes : [
                { id: 'fno_20',    label: 'F&O Quick 20',  count: 20,  stocks: [] },
                { id: 'fno_50',    label: 'F&O Top 50',    count: 50,  stocks: [] },
                { id: 'nifty_100', label: 'Nifty 100',     count: 100, stocks: [] },
                { id: 'fno_200',   label: 'F&O Full 200',  count: 200, stocks: [] },
                { id: 'index',     label: 'Indices Only',  count: 2,   stocks: [] },
              ]).map(u => (
                <button
                  key={u.id}
                  onClick={() => setUniverse(u.id)}
                  className={`w-full text-left px-3 py-2 rounded text-xs transition-all border ${
                    universe === u.id
                      ? 'bg-blue-900/40 border-blue-600/50 text-blue-200'
                      : 'bg-gray-800 border-gray-700 text-gray-400 hover:border-gray-500'
                  }`}
                >
                  <span className="font-medium">{u.label}</span>
                  <span className="text-gray-500 ml-2">({u.count} stocks)</span>
                </button>
              ))}
            </div>
          </div>

          {/* Period + Stock Preview */}
          <div className="space-y-4">
            <div>
              <label className="text-xs text-gray-400 block mb-1.5">Backtest Period</label>
              <div className="flex flex-wrap gap-1.5">
                {PERIOD_OPTIONS.map(p => (
                  <button
                    key={p.id}
                    onClick={() => setPeriod(p.id)}
                    className={`px-3 py-1.5 rounded text-xs border transition-all ${
                      period === p.id
                        ? 'bg-blue-900/40 border-blue-600/50 text-blue-200'
                        : 'bg-gray-800 border-gray-700 text-gray-400 hover:border-gray-500'
                    }`}
                  >
                    {p.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Stock Preview */}
            <div>
              <label className="text-xs text-gray-400 block mb-1.5">Stocks in Universe</label>
              <div className="bg-gray-800 border border-gray-700 rounded p-2 h-28 overflow-y-auto">
                {(universes.find(u => u.id === universe)?.stocks ?? []).length > 0 ? (
                  <div className="flex flex-wrap gap-1">
                    {universes.find(u => u.id === universe)!.stocks.map(s => (
                      <span key={s} className="text-[10px] bg-gray-900 border border-gray-700 px-1.5 py-0.5 rounded text-gray-400">{s}</span>
                    ))}
                  </div>
                ) : (
                  <p className="text-[10px] text-gray-600 text-center mt-6">Loading stock list...</p>
                )}
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── Parameters ─────────────────────────────────────────────────────── */}
      <section className="bg-gray-900/50 border border-gray-800 rounded-lg p-4 space-y-4">
        <h3 className="text-sm font-semibold text-white">Simulation Parameters</h3>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* Capital */}
          <div>
            <label className="text-xs text-gray-400 block mb-1">Starting Capital (₹)</label>
            <input
              type="number" min={10000} step={10000}
              value={capital}
              onChange={(e) => setCapital(Number(e.target.value))}
              className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500"
            />
          </div>

          {/* Commission */}
          <div>
            <label className="text-xs text-gray-400 block mb-1">Commission per Order (₹)</label>
            <input
              type="number" min={0} step={5}
              value={commission}
              onChange={(e) => setCommission(Number(e.target.value))}
              className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500"
            />
          </div>

          {/* Slippage */}
          <div>
            <label className="text-xs text-gray-400 block mb-1">Slippage (basis points)</label>
            <input
              type="number" min={0} max={100} step={1}
              value={slippage}
              onChange={(e) => setSlippage(Number(e.target.value))}
              className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500"
            />
            <p className="text-xs text-gray-600 mt-0.5">1 bp = 0.01%. Default: 5 bp per trade.</p>
          </div>

          {/* Date range */}
          <div className="space-y-2">
            <div>
              <label className="text-xs text-gray-400 block mb-1">Start Date</label>
              <input
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
                className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500"
              />
            </div>
            <div>
              <label className="text-xs text-gray-400 block mb-1">End Date (blank = today)</label>
              <input
                type="date"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
                className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500"
              />
            </div>
          </div>
        </div>
      </section>

      {/* ── Strategy Selection ──────────────────────────────────────────────── */}
      <section className="bg-gray-900/50 border border-gray-800 rounded-lg p-4 space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-white">Strategy Selection</h3>
          <div className="flex gap-2">
            <span className="text-xs text-gray-500">
              {selectedIds.size === 0 ? 'All strategies' : `${selectedIds.size} selected`}
            </span>
            <button onClick={handleSelectAll} className="text-xs text-blue-400 hover:text-blue-200">Select All</button>
            <span className="text-gray-700">|</span>
            <button onClick={handleClearSelect} className="text-xs text-gray-400 hover:text-gray-200">Clear (run all)</button>
          </div>
        </div>

        <div className="space-y-4 max-h-72 overflow-y-auto pr-1">
          {Object.entries(categorised).map(([cat, strats]) => (
            <div key={cat}>
              <div className="text-xs text-gray-500 font-semibold uppercase mb-1.5">{cat}</div>
              <div className="flex flex-wrap gap-2">
                {strats.map((s) => (
                  <button
                    key={s.id}
                    onClick={() => handleIdToggle(s.id)}
                    className={`px-2.5 py-1 text-xs rounded border transition-colors ${
                      selectedIds.has(s.id)
                        ? 'bg-blue-800/60 border-blue-600 text-blue-200'
                        : 'bg-gray-800 border-gray-700 text-gray-400 hover:border-gray-500'
                    }`}
                  >
                    {s.name}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      </section>

      <div className="flex gap-3">
        <button
          onClick={handleSave}
          disabled={saving || capital < 10000}
          className="flex-1 py-2.5 bg-blue-700 hover:bg-blue-600 text-white rounded font-medium text-sm disabled:opacity-50 transition-colors"
        >
          {saving ? 'Saving…' : 'Save Configuration'}
        </button>
        <button
          onClick={handleRunBacktest}
          disabled={running || saving || capital < 10000}
          className="flex-1 py-2.5 bg-emerald-700 hover:bg-emerald-600 text-white rounded font-medium text-sm disabled:opacity-50 transition-colors"
        >
          {running ? 'Starting…' : '▶ Run Backtest'}
        </button>
      </div>

      <p className="text-xs text-gray-600 text-center">
        Save stores config. Run launches a background backtest — view progress on the Backtesting page.
      </p>
    </div>
  );
}
