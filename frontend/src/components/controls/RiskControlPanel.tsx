'use client';

import React, { useState } from 'react';
import { useDashboard } from '@/stores/dashboard';
import { MarketRegime } from '@/types';
import { api } from '@/lib/api';

const REGIMES: MarketRegime[] = ['BULL', 'BEAR', 'SIDEWAYS', 'VOLATILE'];
const REGIME_COLORS: Record<MarketRegime, string> = {
  BULL:     'bg-green-700 hover:bg-green-600 text-white',
  BEAR:     'bg-red-800 hover:bg-red-700 text-white',
  SIDEWAYS: 'bg-slate-700 hover:bg-slate-600 text-white',
  VOLATILE: 'bg-orange-700 hover:bg-orange-600 text-white',
};
const REGIME_ACTIVE: Record<MarketRegime, string> = {
  BULL:     'ring-2 ring-green-400',
  BEAR:     'ring-2 ring-red-400',
  SIDEWAYS: 'ring-2 ring-slate-400',
  VOLATILE: 'ring-2 ring-orange-400',
};

export function RiskControlPanel() {
  const {
    regimeOverride,    setRegimeOverride,
    positionSizing,   setPositionSizing,
    rateLimitConfig,  setRateLimit,
    approvalTimeout,  setApprovalTimeout,
    maxDailyTrades,   setMaxDailyTrades,
    ordersPerSecond,  setOrdersPerSecond,
    confluenceMin,    setConfluenceMin,
    qualityGradeMin,  setQualityGradeMin,
    ivRegimePrefs,    setIVRegimePrefs,
  } = useDashboard();

  const [regimeDuration, setRegimeDuration] = useState(60);
  const [sizingMulti,    setSizingMulti]    = useState(positionSizing.multiplier);
  const [sizingHours,    setSizingHours]    = useState(4);
  const [rateLimit,      setRateLimitLocal] = useState(rateLimitConfig.max_orders_per_cycle);
  const [approvalSecs,   setApprovalSecs]   = useState(approvalTimeout.timeout_seconds);
  const [dailyCap,       setDailyCap]       = useState(maxDailyTrades?.max_daily_trades ?? 0);
  const [opsLimit,       setOpsLimit]       = useState(ordersPerSecond?.orders_per_second ?? 10);
  const [confMin,        setConfMin]        = useState(confluenceMin?.min_confluence_score ?? 3);
  const [qualGrade,      setQualGrade]      = useState(qualityGradeMin?.min_quality_grade ?? 'C');
  const [ivTiers,        setIvTiers]        = useState(ivRegimePrefs?.tiers ?? { IV_CHEAP: true, IV_NORMAL: true, IV_RICH: true, IV_EXTREME: true });
  const [saving,         setSaving]         = useState<string | null>(null);
  const [msg,            setMsg]            = useState<{ text: string; ok: boolean } | null>(null);

  const toast = (text: string, ok = true) => {
    setMsg({ text, ok });
    setTimeout(() => setMsg(null), 3500);
  };

  // ── Regime override ────────────────────────────────────────────────────────
  const handleSetRegime = async (regime: MarketRegime) => {
    setSaving('regime');
    try {
      const res = await api.fetch(`/api/controls/regime-override`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ regime, duration_minutes: regimeDuration }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed');
      setRegimeOverride({ active: true, regime, expires_at: data.expires_at, duration_min: regimeDuration });
      toast(`Regime locked to ${regime} for ${regimeDuration} min`);
    } catch (e: unknown) {
      toast(e instanceof Error ? e.message : 'Error', false);
    } finally {
      setSaving(null);
    }
  };

  const handleClearRegime = async () => {
    setSaving('regime-clear');
    try {
      await api.fetch(`/api/controls/regime-override`, { method: 'DELETE' });
      setRegimeOverride({ active: false, regime: null });
      toast('Regime override cleared — auto-detection resumed');
    } finally {
      setSaving(null);
    }
  };

  // ── Position sizing ────────────────────────────────────────────────────────
  const handleSetSizing = async () => {
    setSaving('sizing');
    try {
      const res = await api.fetch(`/api/controls/position-sizing`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ multiplier: sizingMulti, duration_hours: sizingHours }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed');
      setPositionSizing({ multiplier: sizingMulti, is_overridden: true, expires_at: data.expires_at });
      toast(`Position sizing set to ${Math.round(sizingMulti * 100)}% for ${sizingHours}h`);
    } catch (e: unknown) {
      toast(e instanceof Error ? e.message : 'Error', false);
    } finally {
      setSaving(null);
    }
  };

  const handleResetSizing = async () => {
    setSaving('sizing-reset');
    try {
      await api.fetch(`/api/controls/position-sizing`, { method: 'DELETE' });
      setPositionSizing({ multiplier: 1.0, is_overridden: false });
      setSizingMulti(1.0);
      toast('Position sizing restored to 100%');
    } finally {
      setSaving(null);
    }
  };

  // ── Rate limit ─────────────────────────────────────────────────────────────
  const handleSetRateLimit = async () => {
    setSaving('rate');
    try {
      const res = await api.fetch(`/api/controls/rate-limit`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ max_orders_per_cycle: rateLimit }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed');
      setRateLimit({ max_orders_per_cycle: rateLimit, is_overridden: true });
      toast(`Rate limit set to ${rateLimit} orders/cycle`);
    } catch (e: unknown) {
      toast(e instanceof Error ? e.message : 'Error', false);
    } finally {
      setSaving(null);
    }
  };

  // ── Approval timeout ───────────────────────────────────────────────────────
  const handleSetTimeout = async () => {
    setSaving('timeout');
    try {
      const res = await api.fetch(`/api/controls/approval-timeout`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ timeout_seconds: approvalSecs }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed');
      setApprovalTimeout({ timeout_seconds: approvalSecs, is_overridden: true });
      toast(`Approval timeout set to ${approvalSecs}s`);
    } catch (e: unknown) {
      toast(e instanceof Error ? e.message : 'Error', false);
    } finally {
      setSaving(null);
    }
  };

  // ── Max daily trades ───────────────────────────────────────────────────────
  const handleSetDailyCap = async () => {
    setSaving('daily-cap');
    try {
      const res = await api.fetch(`/api/controls/max-daily-trades`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ max_daily_trades: dailyCap }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed');
      setMaxDailyTrades({ max_daily_trades: dailyCap, is_overridden: dailyCap > 0, today_count: maxDailyTrades?.today_count ?? 0 });
      toast(dailyCap === 0 ? 'Daily trade cap removed (unlimited)' : `Daily trade cap set to ${dailyCap}`);
    } catch (e: unknown) {
      toast(e instanceof Error ? e.message : 'Error', false);
    } finally {
      setSaving(null);
    }
  };

  // ── Orders per second (SEBI) ───────────────────────────────────────────────
  const handleSetOps = async () => {
    setSaving('ops');
    try {
      const res = await api.fetch(`/api/controls/orders-per-second`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ orders_per_second: opsLimit }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed');
      setOrdersPerSecond({ orders_per_second: opsLimit, is_overridden: true });
      toast(`SEBI rate cap set to ${opsLimit} orders/sec`);
    } catch (e: unknown) {
      toast(e instanceof Error ? e.message : 'Error', false);
    } finally {
      setSaving(null);
    }
  };

  // ── Min confluence score ───────────────────────────────────────────────────
  const handleSetConfluence = async () => {
    setSaving('confluence');
    try {
      const res = await api.fetch(`/api/controls/min-confluence-score`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ min_confluence_score: confMin }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed');
      setConfluenceMin({ min_confluence_score: confMin, is_overridden: true });
      toast(`Confluence gate set to ${confMin}/5 factors`);
    } catch (e: unknown) {
      toast(e instanceof Error ? e.message : 'Error', false);
    } finally {
      setSaving(null);
    }
  };

  // ── Min quality grade ──────────────────────────────────────────────────────
  const handleSetQualityGrade = async () => {
    setSaving('quality');
    try {
      const res = await api.fetch(`/api/controls/min-quality-grade`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ min_quality_grade: qualGrade }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed');
      setQualityGradeMin({ min_quality_grade: qualGrade, is_overridden: true });
      toast(`Quality gate set to grade ${qualGrade} minimum`);
    } catch (e: unknown) {
      toast(e instanceof Error ? e.message : 'Error', false);
    } finally {
      setSaving(null);
    }
  };

  // ── IV regime preferences ──────────────────────────────────────────────────
  const handleSetIVPrefs = async () => {
    setSaving('iv-prefs');
    try {
      const res = await api.fetch(`/api/controls/iv-regime-preferences`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ tiers: ivTiers }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Failed');
      setIVRegimePrefs({ tiers: ivTiers, is_overridden: true });
      const blocked = Object.entries(ivTiers).filter(([, v]) => !v).map(([k]) => k);
      toast(blocked.length ? `Blocked IV tiers: ${blocked.join(', ')}` : 'All IV tiers allowed');
    } catch (e: unknown) {
      toast(e instanceof Error ? e.message : 'Error', false);
    } finally {
      setSaving(null);
    }
  };

  const pct = Math.round(sizingMulti * 100);

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-semibold text-white">Risk Controls</h2>

      {msg && (
        <div className={`px-3 py-2 rounded text-sm ${msg.ok ? 'bg-green-950 border border-green-800 text-green-300' : 'bg-red-950 border border-red-800 text-red-300'}`}>
          {msg.text}
        </div>
      )}

      {/* ── Market Regime Override ───────────────────────────────────────────── */}
      <section className="bg-gray-900/50 border border-gray-800 rounded-lg p-4 space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-white">Market Regime Override</h3>
          {regimeOverride.active && (
            <span className="text-xs text-orange-400 animate-pulse">
              LOCKED: {regimeOverride.regime}
              {regimeOverride.expires_at && ` · expires ${new Date(regimeOverride.expires_at).toLocaleTimeString()}`}
            </span>
          )}
        </div>

        <div className="flex flex-wrap gap-2">
          {REGIMES.map((r) => (
            <button
              key={r}
              disabled={saving === 'regime'}
              onClick={() => handleSetRegime(r)}
              className={`px-4 py-2 text-sm rounded font-medium transition-all ${REGIME_COLORS[r]} ${
                regimeOverride.regime === r ? REGIME_ACTIVE[r] : ''
              } ${saving === 'regime' ? 'opacity-50 cursor-not-allowed' : ''}`}
            >
              {r}
            </button>
          ))}
          {regimeOverride.active && (
            <button
              onClick={handleClearRegime}
              className="px-4 py-2 text-sm rounded bg-gray-700 hover:bg-gray-600 text-gray-200 font-medium"
            >
              Clear Override
            </button>
          )}
        </div>

        <div className="flex items-center gap-3">
          <label className="text-xs text-gray-400 w-24">Duration (min):</label>
          <select
            value={regimeDuration}
            onChange={(e) => setRegimeDuration(Number(e.target.value))}
            className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs text-white"
          >
            {[15, 30, 60, 120, 240, 480].map((m) => (
              <option key={m} value={m}>{m} min</option>
            ))}
          </select>
        </div>

        {!regimeOverride.active && (
          <p className="text-xs text-gray-500">Auto-detection is active. Select a regime to override.</p>
        )}
      </section>

      {/* ── Position Sizing Multiplier ──────────────────────────────────────── */}
      <section className="bg-gray-900/50 border border-gray-800 rounded-lg p-4 space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-white">Position Sizing</h3>
          {positionSizing.is_overridden && (
            <span className="text-xs text-yellow-400">
              OVERRIDE: {Math.round(positionSizing.multiplier * 100)}%
              {positionSizing.expires_at && ` · until ${new Date(positionSizing.expires_at).toLocaleTimeString()}`}
            </span>
          )}
        </div>

        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-xs text-gray-400">
              Multiplier:&nbsp;
              <span className={`font-semibold ${pct < 80 ? 'text-red-400' : pct > 120 ? 'text-orange-400' : 'text-green-400'}`}>
                {pct}%
              </span>
            </span>
            <span className="text-xs text-gray-500">0.1x – 3.0x (default: 1.0x)</span>
          </div>
          <input
            type="range"
            min={0.1} max={3.0} step={0.05}
            value={sizingMulti}
            onChange={(e) => setSizingMulti(parseFloat(e.target.value))}
            className="w-full accent-blue-500"
          />
          <div className="flex items-center gap-3">
            <label className="text-xs text-gray-400 w-24">Duration:</label>
            <select
              value={sizingHours}
              onChange={(e) => setSizingHours(Number(e.target.value))}
              className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs text-white"
            >
              {[1, 2, 4, 8, 24].map((h) => <option key={h} value={h}>{h}h</option>)}
            </select>
            <button
              onClick={handleSetSizing}
              disabled={saving === 'sizing'}
              className="px-3 py-1 text-xs bg-blue-700 hover:bg-blue-600 text-white rounded disabled:opacity-50"
            >
              Apply {pct}%
            </button>
            {positionSizing.is_overridden && (
              <button
                onClick={handleResetSizing}
                className="px-3 py-1 text-xs bg-gray-700 hover:bg-gray-600 text-gray-200 rounded"
              >
                Reset to 100%
              </button>
            )}
          </div>
        </div>
      </section>

      {/* ── Rate Limiter ─────────────────────────────────────────────────────── */}
      <section className="bg-gray-900/50 border border-gray-800 rounded-lg p-4 space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-white">Order Rate Limiter</h3>
          {rateLimitConfig.is_overridden && (
            <span className="text-xs text-yellow-400">OVERRIDE: {rateLimitConfig.max_orders_per_cycle}/cycle</span>
          )}
        </div>
        <div className="flex items-center gap-3">
          <label className="text-xs text-gray-400 w-32">Max orders/cycle:</label>
          <input
            type="number"
            min={1} max={50} step={1}
            value={rateLimit}
            onChange={(e) => setRateLimitLocal(Number(e.target.value))}
            className="w-20 bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm text-white text-center"
          />
          <button
            onClick={handleSetRateLimit}
            disabled={saving === 'rate'}
            className="px-3 py-1 text-xs bg-blue-700 hover:bg-blue-600 text-white rounded disabled:opacity-50"
          >
            Apply
          </button>
        </div>
        <p className="text-xs text-gray-500">Default: 10. Range: 1–50. Protects against runaway order generation.</p>
      </section>

      {/* ── Approval Timeout ──────────────────────────────────────────────────── */}
      <section className="bg-gray-900/50 border border-gray-800 rounded-lg p-4 space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-white">Approval Timeout (MANUAL mode)</h3>
          {approvalTimeout.is_overridden && (
            <span className="text-xs text-yellow-400">OVERRIDE: {approvalTimeout.timeout_seconds}s</span>
          )}
        </div>
        <div className="flex items-center gap-3">
          <label className="text-xs text-gray-400 w-32">Timeout (seconds):</label>
          <input
            type="number"
            min={10} max={300} step={5}
            value={approvalSecs}
            onChange={(e) => setApprovalSecs(Number(e.target.value))}
            className="w-20 bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm text-white text-center"
          />
          <button
            onClick={handleSetTimeout}
            disabled={saving === 'timeout'}
            className="px-3 py-1 text-xs bg-blue-700 hover:bg-blue-600 text-white rounded disabled:opacity-50"
          >
            Apply
          </button>
        </div>
        <p className="text-xs text-gray-500">
          Default: 30s. When a trade approval expires (no action taken), it is automatically rejected.
        </p>
      </section>

      {/* ── Max Daily Trades ──────────────────────────────────────────────────── */}
      <section className="bg-gray-900/50 border border-gray-800 rounded-lg p-4 space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-white">Daily Trade Cap</h3>
          {maxDailyTrades?.is_overridden && (
            <span className="text-xs text-yellow-400">
              CAP: {maxDailyTrades?.max_daily_trades} · Today: {maxDailyTrades?.today_count ?? 0}
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          <label className="text-xs text-gray-400 w-32">Max trades/day:</label>
          <input
            type="number"
            min={0} max={500} step={1}
            value={dailyCap}
            onChange={(e) => setDailyCap(Number(e.target.value))}
            className="w-20 bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm text-white text-center"
          />
          <button
            onClick={handleSetDailyCap}
            disabled={saving === 'daily-cap'}
            className="px-3 py-1 text-xs bg-blue-700 hover:bg-blue-600 text-white rounded disabled:opacity-50"
          >
            Apply
          </button>
        </div>
        <p className="text-xs text-gray-500">
          0 = unlimited. Signal funnel runs full — only executions are capped. Today: {maxDailyTrades?.today_count ?? 0} trades.
        </p>
      </section>

      {/* ── Orders Per Second (SEBI) ──────────────────────────────────────────── */}
      <section className="bg-gray-900/50 border border-gray-800 rounded-lg p-4 space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-white">SEBI Orders/Second Cap</h3>
          {ordersPerSecond?.is_overridden && (
            <span className="text-xs text-yellow-400">OVERRIDE: {ordersPerSecond?.orders_per_second}/sec</span>
          )}
        </div>
        <div className="flex items-center gap-3">
          <label className="text-xs text-gray-400 w-32">Max orders/sec:</label>
          <input
            type="number"
            min={1} max={25} step={1}
            value={opsLimit}
            onChange={(e) => setOpsLimit(Number(e.target.value))}
            className="w-20 bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm text-white text-center"
          />
          <button
            onClick={handleSetOps}
            disabled={saving === 'ops'}
            className="px-3 py-1 text-xs bg-blue-700 hover:bg-blue-600 text-white rounded disabled:opacity-50"
          >
            Apply
          </button>
        </div>
        <p className="text-xs text-gray-500">
          Default: 10. SEBI/NSE non-co-location limit. Keep ≤10 to avoid algo ID registration requirement.
        </p>
      </section>

      {/* ── Min Confluence Score ───────────────────────────────────────────────── */}
      <section className="bg-gray-900/50 border border-gray-800 rounded-lg p-4 space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-white">Confluence Quality Gate</h3>
          {confluenceMin?.is_overridden && (
            <span className="text-xs text-yellow-400">OVERRIDE: {confluenceMin?.min_confluence_score}/5</span>
          )}
        </div>
        <div className="flex items-center gap-3">
          <label className="text-xs text-gray-400 w-32">Min factors (1-5):</label>
          {[1, 2, 3, 4, 5].map((n) => (
            <button
              key={n}
              onClick={() => setConfMin(n)}
              className={`w-8 h-8 text-sm rounded font-medium border ${
                confMin === n
                  ? 'bg-blue-700 border-blue-500 text-white'
                  : 'bg-gray-800 border-gray-700 text-gray-400 hover:border-gray-500'
              }`}
            >
              {n}
            </button>
          ))}
          <button
            onClick={handleSetConfluence}
            disabled={saving === 'confluence'}
            className="px-3 py-1 text-xs bg-blue-700 hover:bg-blue-600 text-white rounded disabled:opacity-50"
          >
            Apply
          </button>
        </div>
        <p className="text-xs text-gray-500">
          Factors: Regime + IV + OFI + Sector + MTF. Default 3 = balanced. 5 = only perfect setups. 1 = very loose.
        </p>
      </section>

      {/* ── Min Quality Grade ─────────────────────────────────────────────────── */}
      <section className="bg-gray-900/50 border border-gray-800 rounded-lg p-4 space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-white">AI Signal Quality Gate</h3>
          {qualityGradeMin?.is_overridden && (
            <span className="text-xs text-yellow-400">OVERRIDE: Grade {qualityGradeMin?.min_quality_grade}+</span>
          )}
        </div>
        <div className="flex items-center gap-3">
          <label className="text-xs text-gray-400 w-32">Min grade:</label>
          {['A', 'B', 'C', 'D', 'F'].map((g) => (
            <button
              key={g}
              onClick={() => setQualGrade(g)}
              className={`w-8 h-8 text-sm rounded font-medium border ${
                qualGrade === g
                  ? 'bg-blue-700 border-blue-500 text-white'
                  : 'bg-gray-800 border-gray-700 text-gray-400 hover:border-gray-500'
              }`}
            >
              {g}
            </button>
          ))}
          <button
            onClick={handleSetQualityGrade}
            disabled={saving === 'quality'}
            className="px-3 py-1 text-xs bg-blue-700 hover:bg-blue-600 text-white rounded disabled:opacity-50"
          >
            Apply
          </button>
        </div>
        <p className="text-xs text-gray-500">
          A = only top-tier signals, C = balanced (default), F = accept all. AI classifier grades each signal before execution.
        </p>
      </section>

      {/* ── IV Regime Preferences ─────────────────────────────────────────────── */}
      <section className="bg-gray-900/50 border border-gray-800 rounded-lg p-4 space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-white">IV Regime Preferences</h3>
          {ivRegimePrefs?.is_overridden && (
            <span className="text-xs text-yellow-400">
              CUSTOM: {Object.entries(ivRegimePrefs?.tiers ?? {}).filter(([, v]) => !v).length} blocked
            </span>
          )}
        </div>
        <div className="flex flex-wrap gap-3">
          {(['IV_CHEAP', 'IV_NORMAL', 'IV_RICH', 'IV_EXTREME'] as const).map((tier) => {
            const allowed = ivTiers[tier] ?? true;
            const colors: Record<string, string> = {
              IV_CHEAP:   'border-green-700 text-green-400',
              IV_NORMAL:  'border-slate-600 text-slate-300',
              IV_RICH:    'border-orange-700 text-orange-400',
              IV_EXTREME: 'border-red-700 text-red-400',
            };
            return (
              <button
                key={tier}
                onClick={() => setIvTiers((prev: Record<string, boolean>) => ({ ...prev, [tier]: !prev[tier] }))}
                className={`px-3 py-2 text-xs rounded border font-medium transition-all ${
                  allowed
                    ? `${colors[tier]} bg-gray-800`
                    : 'border-gray-700 text-gray-600 bg-gray-900 line-through'
                }`}
              >
                {tier.replace('IV_', '')} {allowed ? '✓' : '✗'}
              </button>
            );
          })}
          <button
            onClick={handleSetIVPrefs}
            disabled={saving === 'iv-prefs'}
            className="px-3 py-2 text-xs bg-blue-700 hover:bg-blue-600 text-white rounded disabled:opacity-50"
          >
            Save
          </button>
        </div>
        <p className="text-xs text-gray-500">
          Block IV tiers to prevent trading in specific volatility environments. E.g., block IV_EXTREME to avoid selling premium during spikes.
        </p>
      </section>
    </div>
  );
}
