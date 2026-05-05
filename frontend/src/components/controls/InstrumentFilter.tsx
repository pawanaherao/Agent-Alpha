'use client';

import React, { useState } from 'react';
import { useDashboard } from '@/stores/dashboard';
import { api } from '@/lib/api';

export function InstrumentFilter() {
  const { instrumentFilter, alertThresholds, setInstrumentFilter, setAlertThresholds } = useDashboard();

  const [addInput,  setAddInput]  = useState('');
  const [saving,    setSaving]    = useState(false);
  const [msg,       setMsg]       = useState<{ text: string; ok: boolean } | null>(null);

  // Alert threshold local state
  const [sigStrength, setSigStrength] = useState(alertThresholds.min_signal_strength);
  const [vixLevel,    setVixLevel]    = useState(alertThresholds.vix_warning_level);
  const [minScore,    setMinScore]    = useState(alertThresholds.min_strategy_score);
  const [dailyWarn,   setDailyWarn]   = useState(alertThresholds.daily_loss_warning);
  const [approvalSnd, setApprovalSnd] = useState(alertThresholds.approval_sound);

  const toast = (text: string, ok = true) => {
    setMsg({ text, ok });
    setTimeout(() => setMsg(null), 3500);
  };

  const handleAdd = async () => {
    const symbols = addInput
      .split(/[,\s]+/)
      .map((s) => s.trim().toUpperCase())
      .filter(Boolean);
    if (!symbols.length) return;

    setSaving(true);
    try {
      const res = await api.fetch(`/api/controls/instrument-filter/add`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ symbols }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed');
      setInstrumentFilter({ blacklist: data.blacklist, count: data.blacklist.length });
      setAddInput('');
      toast(`Added ${data.added.join(', ')} to blacklist`);
    } catch (e: unknown) {
      toast(e instanceof Error ? e.message : 'Error', false);
    } finally {
      setSaving(false);
    }
  };

  const handleRemove = async (symbol: string) => {
    setSaving(true);
    try {
      const res = await api.fetch(`/api/controls/instrument-filter/remove`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ symbols: [symbol] }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed');
      setInstrumentFilter({ blacklist: data.blacklist, count: data.blacklist.length });
      toast(`Removed ${symbol} from blacklist`);
    } catch (e: unknown) {
      toast(e instanceof Error ? e.message : 'Error', false);
    } finally {
      setSaving(false);
    }
  };

  const handleSaveThresholds = async () => {
    setSaving(true);
    try {
      const body = {
        min_signal_strength: sigStrength,
        vix_warning_level:   vixLevel,
        min_strategy_score:  minScore,
        daily_loss_warning:  dailyWarn,
        approval_sound:      approvalSnd,
      };
      const res = await api.fetch(`/api/controls/alert-thresholds`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed');
      setAlertThresholds({ ...data, is_overridden: true });
      toast('Alert thresholds saved');
    } catch (e: unknown) {
      toast(e instanceof Error ? e.message : 'Error', false);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-semibold text-white">Instruments & Alerts</h2>

      {msg && (
        <div className={`px-3 py-2 rounded text-sm ${msg.ok ? 'bg-green-950 border border-green-800 text-green-300' : 'bg-red-950 border border-red-800 text-red-300'}`}>
          {msg.text}
        </div>
      )}

      {/* ── Instrument Blacklist ─────────────────────────────────────────────── */}
      <section className="bg-gray-900/50 border border-gray-800 rounded-lg p-4 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-white">Instrument Blacklist</h3>
          <span className="text-xs text-gray-500">{instrumentFilter.count} symbols blocked</span>
        </div>

        <p className="text-xs text-gray-500">
          Blacklisted instruments will be skipped by all strategies during signal generation and execution.
        </p>

        {/* Add */}
        <div className="flex gap-2">
          <input
            className="flex-1 bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-red-600"
            placeholder="Add symbols: RELIANCE, TCS, NIFTY50 (comma or space separated)"
            value={addInput}
            onChange={(e) => setAddInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleAdd()}
          />
          <button
            onClick={handleAdd}
            disabled={saving || !addInput.trim()}
            className="px-4 py-2 text-sm bg-red-800 hover:bg-red-700 text-white rounded disabled:opacity-50 font-medium"
          >
            Block
          </button>
        </div>

        {/* Current blacklist */}
        {instrumentFilter.blacklist.length > 0 ? (
          <div className="flex flex-wrap gap-2">
            {instrumentFilter.blacklist.map((sym) => (
              <span
                key={sym}
                className="inline-flex items-center gap-1.5 bg-red-950/50 border border-red-900/60 rounded-full px-3 py-1 text-xs text-red-300"
              >
                {sym}
                <button
                  onClick={() => handleRemove(sym)}
                  className="text-red-500 hover:text-red-200 font-bold leading-none"
                  title="Remove"
                >
                  ×
                </button>
              </span>
            ))}
          </div>
        ) : (
          <p className="text-xs text-gray-600 italic">No instruments blacklisted — all symbols allowed.</p>
        )}
      </section>

      {/* ── Alert Thresholds ─────────────────────────────────────────────────── */}
      <section className="bg-gray-900/50 border border-gray-800 rounded-lg p-4 space-y-4">
        <h3 className="text-sm font-semibold text-white">Alert Thresholds</h3>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* Min signal strength */}
          <div className="space-y-1.5">
            <label className="text-xs text-gray-400 block">
              Min Signal Strength:&nbsp;
              <span className="text-white font-semibold">{Math.round(sigStrength * 100)}%</span>
            </label>
            <input
              type="range" min={0} max={1} step={0.05}
              value={sigStrength}
              onChange={(e) => setSigStrength(parseFloat(e.target.value))}
              className="w-full accent-blue-500"
            />
            <p className="text-xs text-gray-600">Only surface signals above this confidence. Default: 60%.</p>
          </div>

          {/* VIX warning */}
          <div className="space-y-1.5">
            <label className="text-xs text-gray-400 block">
              VIX Warning Level:&nbsp;
              <span className="text-white font-semibold">{vixLevel.toFixed(1)}</span>
            </label>
            <input
              type="range" min={5} max={80} step={0.5}
              value={vixLevel}
              onChange={(e) => setVixLevel(parseFloat(e.target.value))}
              className="w-full accent-orange-500"
            />
            <p className="text-xs text-gray-600">Show a warning banner when India VIX exceeds this.</p>
          </div>

          {/* Min strategy score */}
          <div className="space-y-1.5">
            <label className="text-xs text-gray-400 block">
              Min Strategy Score (backtest):&nbsp;
              <span className="text-white font-semibold">{Math.round(minScore * 100)}%</span>
            </label>
            <input
              type="range" min={0} max={1} step={0.05}
              value={minScore}
              onChange={(e) => setMinScore(parseFloat(e.target.value))}
              className="w-full accent-green-500"
            />
            <p className="text-xs text-gray-600">Only paper-trade strategies with a backtest score above this.</p>
          </div>

          {/* Daily loss warning */}
          <div className="space-y-1.5">
            <label className="text-xs text-gray-400 block">
              Daily Loss Warning:&nbsp;
              <span className="text-white font-semibold">{dailyWarn.toFixed(1)}%</span>
            </label>
            <input
              type="range" min={-10} max={-0.5} step={0.1}
              value={dailyWarn}
              onChange={(e) => setDailyWarn(parseFloat(e.target.value))}
              className="w-full accent-red-500"
            />
            <p className="text-xs text-gray-600">Warn before the kill-switch fires at this portfolio % loss.</p>
          </div>
        </div>

        {/* Approval sound */}
        <div className="flex items-center gap-3">
          <input
            type="checkbox"
            id="approval-sound"
            checked={approvalSnd}
            onChange={(e) => setApprovalSnd(e.target.checked)}
            className="w-4 h-4 accent-blue-600"
          />
          <label htmlFor="approval-sound" className="text-sm text-gray-300 cursor-pointer">
            Play sound when a new trade approval arrives (MANUAL mode)
          </label>
        </div>

        <button
          onClick={handleSaveThresholds}
          disabled={saving}
          className="px-4 py-2 text-sm bg-blue-700 hover:bg-blue-600 text-white rounded disabled:opacity-50 font-medium"
        >
          Save Alert Thresholds
        </button>
      </section>
    </div>
  );
}
