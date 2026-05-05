'use client';

import React, { useState, useCallback } from 'react';
import { useDashboard } from '@/stores/dashboard';
import { StrategyControlEntry, FullStrategyCategory } from '@/types';

type ModuleFilter = 'ALL' | 'EQUITY' | 'OPTIONS';
import { api } from '@/lib/api';

const CATEGORY_COLORS: Record<string, string> = {
  MOMENTUM:       'bg-blue-900/60 text-blue-300',
  MEAN_REVERSION: 'bg-purple-900/60 text-purple-300',
  SWING:          'bg-teal-900/60 text-teal-300',
  OPTIONS:        'bg-orange-900/60 text-orange-300',
  QUANT:          'bg-pink-900/60 text-pink-300',
  HEDGING:        'bg-yellow-900/60 text-yellow-300',
  VOLATILITY:     'bg-red-900/60 text-red-300',
  META:           'bg-green-900/60 text-green-300',
};

const ALL_CATEGORIES: FullStrategyCategory[] = [
  'MOMENTUM', 'MEAN_REVERSION', 'SWING', 'OPTIONS', 'QUANT', 'HEDGING', 'VOLATILITY', 'META',
];

export function StrategyManager() {
  const {
    strategyControls,
    activeSet,
    setStrategyControls,
    setActiveSet,
  } = useDashboard();

  const [categoryFilter, setCategoryFilter] = useState<FullStrategyCategory | 'ALL'>('ALL');
  const [moduleFilter, setModuleFilter]     = useState<ModuleFilter>('ALL');
  const [searchQuery, setSearchQuery]       = useState('');
  const [savingId, setSavingId]             = useState<string | null>(null);
  const [limitInputs, setLimitInputs]       = useState<Record<string, { loss: string; pct: string }>>({});
  const [error, setError]                   = useState<string | null>(null);

  // ─── Derived list ────────────────────────────────────────────────────────
  const filtered = strategyControls.filter((s) => {
    const catOk  = categoryFilter === 'ALL' || s.category === categoryFilter;
    const modOk  = moduleFilter === 'ALL' || (s.module ?? 'EQUITY') === moduleFilter;
    const nameOk = s.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
                   s.id.toLowerCase().includes(searchQuery.toLowerCase());
    return catOk && modOk && nameOk;
  });

  const inActiveSet = new Set(activeSet.active_set);

  // ─── Toggle enabled ──────────────────────────────────────────────────────
  const handleToggle = useCallback(async (strategy: StrategyControlEntry) => {
    setSavingId(strategy.id);
    setError(null);
    try {
      const res = await api.fetch(`/api/controls/strategies/${strategy.id}/toggle`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ enabled: !strategy.enabled }),
      });
      if (!res.ok) throw new Error(await res.text());
      setStrategyControls(
        strategyControls.map((s) =>
          s.id === strategy.id ? { ...s, enabled: !s.enabled } : s
        )
      );
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Toggle failed');
    } finally {
      setSavingId(null);
    }
  }, [strategyControls, setStrategyControls]);

  // ─── Reset circuit breaker ───────────────────────────────────────────────
  const handleResetCB = useCallback(async (strategyId: string) => {
    setSavingId(strategyId);
    setError(null);
    try {
      const res = await api.fetch(`/api/controls/strategies/${strategyId}/reset-circuit-breaker`, {
        method: 'POST',
      });
      if (!res.ok) throw new Error(await res.text());
      setStrategyControls(
        strategyControls.map((s) =>
          s.id === strategyId
            ? { ...s, enabled: true, circuit_breaker_triggered: false, circuit_breaker_reason: '' }
            : s
        )
      );
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Reset failed');
    } finally {
      setSavingId(null);
    }
  }, [strategyControls, setStrategyControls]);

  // ─── Set limit ───────────────────────────────────────────────────────────
  const handleSetLimit = useCallback(async (strategyId: string) => {
    const inp = limitInputs[strategyId];
    if (!inp) return;
    setSavingId(strategyId);
    setError(null);
    try {
      const res = await api.fetch(`/api/controls/strategies/${strategyId}/limits`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({
          max_loss:     parseFloat(inp.loss || '0'),
          max_loss_pct: parseFloat(inp.pct  || '0'),
        }),
      });
      if (!res.ok) throw new Error(await res.text());
      setLimitInputs((prev) => {
        const next = { ...prev };
        delete next[strategyId];
        return next;
      });
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Set limit failed');
    } finally {
      setSavingId(null);
    }
  }, [limitInputs]);

  // ─── Active set toggle ───────────────────────────────────────────────────
  const handleActiveSetToggle = useCallback(async (strategyId: string) => {
    const current = new Set(activeSet.active_set);
    if (current.has(strategyId)) {
      current.delete(strategyId);
    } else {
      current.add(strategyId);
    }
    const newSet = [...current];
    try {
      const res = await api.fetch(`/api/controls/active-set`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ strategy_ids: newSet }),
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      setActiveSet(data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Active set update failed');
    }
  }, [activeSet, setActiveSet]);

  // ─── Bulk enable / disable ───────────────────────────────────────────────
  const handleBulk = useCallback(async (enabled: boolean) => {
    const ids = filtered.map((s) => s.id);
    setError(null);
    try {
      const res = await api.fetch(`/api/controls/strategies/bulk-toggle`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ strategy_ids: ids, enabled }),
      });
      if (!res.ok) throw new Error(await res.text());
      setStrategyControls(
        strategyControls.map((s) => ids.includes(s.id) ? { ...s, enabled } : s)
      );
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Bulk toggle failed');
    }
  }, [filtered, strategyControls, setStrategyControls]);

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-xl font-semibold text-white">Strategy Manager</h2>
        <div className="flex gap-2">
          <button
            onClick={() => handleBulk(true)}
            className="px-3 py-1.5 text-xs rounded bg-green-800 hover:bg-green-700 text-green-100 font-medium transition-colors"
          >
            Enable All Visible
          </button>
          <button
            onClick={() => handleBulk(false)}
            className="px-3 py-1.5 text-xs rounded bg-red-900 hover:bg-red-800 text-red-200 font-medium transition-colors"
          >
            Disable All Visible
          </button>
        </div>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-2 items-center">
        <input
          className="flex-1 min-w-48 bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-blue-500"
          placeholder="Search strategy name or ID…"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
        />
        {/* Module filter */}
        <div className="flex gap-1">
          {(['ALL', 'EQUITY', 'OPTIONS'] as const).map((mod) => (
            <button
              key={mod}
              onClick={() => setModuleFilter(mod)}
              className={`px-2 py-1 text-xs rounded transition-colors ${
                moduleFilter === mod
                  ? 'bg-emerald-600 text-white'
                  : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
              }`}
            >
              {mod === 'ALL' ? '🔄 ALL' : mod === 'EQUITY' ? '📈 EQUITY' : '📊 OPTIONS'}
            </button>
          ))}
        </div>
        {/* Category filter */}
        <div className="flex gap-1 flex-wrap">
          {(['ALL', ...ALL_CATEGORIES] as const).map((cat) => (
            <button
              key={cat}
              onClick={() => setCategoryFilter(cat)}
              className={`px-2 py-1 text-xs rounded transition-colors ${
                categoryFilter === cat
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
              }`}
            >
              {cat}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className="bg-red-950 border border-red-800 rounded px-3 py-2 text-sm text-red-300">
          {error}
        </div>
      )}

      {/* Active set info */}
      <div className="bg-blue-950/40 border border-blue-900/50 rounded px-3 py-2 text-xs text-blue-300">
        Active execution set:{' '}
        <span className="font-semibold text-blue-200">
          {activeSet.mode === 'all_enabled' ? 'All enabled strategies' : `${activeSet.count} selected`}
        </span>
        {activeSet.mode === 'subset' && (
          <button
            className="ml-3 text-blue-400 hover:text-blue-200 underline"
            onClick={async () => {
              const res = await api.fetch(`/api/controls/active-set`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ strategy_ids: [] }),
              });
              if (res.ok) setActiveSet(await res.json());
            }}
          >
            Reset to all
          </button>
        )}
      </div>

      {/* Table */}
      <div className="overflow-x-auto rounded-lg border border-gray-800">
        <table className="w-full text-sm">
          <thead className="bg-gray-900/80 text-gray-400">
            <tr>
              <th className="text-left px-3 py-2 font-medium">Strategy</th>
              <th className="text-left px-3 py-2 font-medium">Module</th>
              <th className="text-left px-3 py-2 font-medium">Category</th>
              <th className="text-center px-3 py-2 font-medium">Broker</th>
              <th className="text-center px-3 py-2 font-medium">Enabled</th>
              <th className="text-center px-3 py-2 font-medium">Active Set</th>
              <th className="text-right px-3 py-2 font-medium">Today P&L</th>
              <th className="text-left px-3 py-2 font-medium">Max Loss</th>
              <th className="text-left px-3 py-2 font-medium">Circuit</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800/60">
            {filtered.length === 0 && (
              <tr>
                <td colSpan={9} className="text-center py-6 text-gray-500">
                  No strategies match the current filter.
                </td>
              </tr>
            )}
            {filtered.map((s) => {
              const isSaving = savingId === s.id;
              const cbTripped = s.circuit_breaker_triggered;
              const inp = limitInputs[s.id] || { loss: '', pct: '' };

              return (
                <tr key={s.id} className={`transition-colors ${cbTripped ? 'bg-red-950/20' : 'hover:bg-gray-800/40'}`}>
                  {/* Name + ID */}
                  <td className="px-3 py-2">
                    <div className="font-medium text-white">{s.name}</div>
                    <div className="text-xs text-gray-500">{s.id}</div>
                  </td>
                  {/* Module */}
                  <td className="px-3 py-2">
                    <span className={`inline-block px-2 py-0.5 text-xs rounded-full ${
                      (s.module ?? 'EQUITY') === 'OPTIONS'
                        ? 'bg-orange-900/60 text-orange-300'
                        : 'bg-emerald-900/60 text-emerald-300'
                    }`}>
                      {s.module ?? 'EQUITY'}
                    </span>
                  </td>
                  {/* Category */}
                  <td className="px-3 py-2">
                    <span className={`inline-block px-2 py-0.5 text-xs rounded-full ${CATEGORY_COLORS[s.category] || 'bg-gray-800 text-gray-300'}`}>
                      {s.category}
                    </span>
                  </td>
                  {/* Default broker */}
                  <td className="px-3 py-2 text-center">
                    <span className={`text-xs ${s.default_broker === 'dhan' ? 'text-cyan-400' : 'text-yellow-400'}`}>
                      {s.default_broker.toUpperCase()}
                    </span>
                  </td>
                  {/* Enabled toggle */}
                  <td className="px-3 py-2 text-center">
                    <button
                      disabled={isSaving}
                      onClick={() => handleToggle(s)}
                      className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors focus:outline-none ${
                        s.enabled ? 'bg-green-600' : 'bg-gray-700'
                      } ${isSaving ? 'opacity-50 cursor-not-allowed' : ''}`}
                      title={s.enabled ? 'Click to disable' : 'Click to enable'}
                    >
                      <span
                        className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform ${
                          s.enabled ? 'translate-x-4' : 'translate-x-0.5'
                        }`}
                      />
                    </button>
                  </td>
                  {/* Active set checkbox */}
                  <td className="px-3 py-2 text-center">
                    <input
                      type="checkbox"
                      checked={inActiveSet.has(s.id)}
                      onChange={() => handleActiveSetToggle(s.id)}
                      className="w-3.5 h-3.5 rounded accent-blue-600 cursor-pointer"
                      title="Include in live execution subset"
                    />
                  </td>
                  {/* Today P&L */}
                  <td className={`px-3 py-2 text-right font-mono text-xs ${s.today_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {s.today_pnl >= 0 ? '+' : ''}₹{s.today_pnl.toLocaleString()}
                  </td>
                  {/* Max loss input */}
                  <td className="px-3 py-2">
                    <div className="flex gap-1 items-center">
                      <input
                        type="number"
                        placeholder={s.max_loss ? `₹${s.max_loss}` : 'Max ₹'}
                        value={inp.loss}
                        onChange={(e) => setLimitInputs((prev) => ({ ...prev, [s.id]: { ...prev[s.id] || { loss: '', pct: '' }, loss: e.target.value } }))}
                        className="w-20 bg-gray-900 border border-gray-700 rounded px-2 py-0.5 text-xs text-white focus:outline-none focus:border-yellow-600"
                      />
                      <input
                        type="number"
                        placeholder={s.max_loss_pct ? `${s.max_loss_pct}%` : '%'}
                        value={inp.pct}
                        onChange={(e) => setLimitInputs((prev) => ({ ...prev, [s.id]: { ...prev[s.id] || { loss: '', pct: '' }, pct: e.target.value } }))}
                        className="w-14 bg-gray-900 border border-gray-700 rounded px-2 py-0.5 text-xs text-white focus:outline-none focus:border-yellow-600"
                      />
                      {(inp.loss || inp.pct) && (
                        <button
                          onClick={() => handleSetLimit(s.id)}
                          className="px-1.5 py-0.5 text-xs bg-yellow-700 hover:bg-yellow-600 text-white rounded"
                        >
                          Set
                        </button>
                      )}
                    </div>
                  </td>
                  {/* Circuit breaker */}
                  <td className="px-3 py-2">
                    {cbTripped ? (
                      <div className="flex items-center gap-1">
                        <span className="text-xs text-red-400 font-semibold">TRIPPED</span>
                        <button
                          onClick={() => handleResetCB(s.id)}
                          className="text-xs text-yellow-400 hover:text-yellow-200 underline"
                        >
                          Reset
                        </button>
                      </div>
                    ) : (
                      <span className="text-xs text-gray-600">OK</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="text-xs text-gray-600 text-right">
        Showing {filtered.length} of {strategyControls.length} strategies
      </div>
    </div>
  );
}
