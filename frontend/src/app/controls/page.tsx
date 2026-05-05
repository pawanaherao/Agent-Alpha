'use client';

import React, { useEffect, useState, useCallback } from 'react';
import { useDashboard } from '@/stores/dashboard';
import { StrategyManager }      from '@/components/controls/StrategyManager';
import { OperationsControlPanel } from '@/components/controls/OperationsControlPanel';
import { RiskControlPanel }     from '@/components/controls/RiskControlPanel';
import { InstrumentFilter }     from '@/components/controls/InstrumentFilter';
import { BacktestConfig }       from '@/components/controls/BacktestConfig';
import { ScannerControlPanel }  from '@/components/controls/ScannerControlPanel';
import { MonteCarloPanel }      from '@/components/controls/MonteCarloPanel';
import { ControlsSnapshot } from '@/types';
import { api } from '@/lib/api';

type TabId = 'strategies' | 'risk' | 'scanners' | 'instruments' | 'backtest' | 'montecarlo' | 'paper' | 'operations';

const TABS: { id: TabId; label: string; icon: string }[] = [
  { id: 'strategies',  label: 'Strategies',    icon: '⚡' },
  { id: 'risk',        label: 'Risk',           icon: '🛡' },
  { id: 'scanners',    label: 'Scanners',       icon: '🔍' },
  { id: 'instruments', label: 'Instruments',    icon: '🎯' },
  { id: 'backtest',    label: 'Backtest Config',  icon: '📊' },
  { id: 'montecarlo',  label: 'Monte Carlo',    icon: '🎲' },
  { id: 'paper',       label: 'Paper Testing',  icon: '🧪' },
  { id: 'operations',  label: 'Operations',     icon: '🧭' },
];

// ─── Paper Testing Panel ──────────────────────────────────────────────────────
function PaperTestingPanel() {
  const [status, setStatus] = useState<{
    mode: string; agents_running: boolean; market_open: boolean; database: string; redis: string;
  } | null>(null);
  const [tradingMode, setTradingMode] = useState<string>('PAPER');
  const [isTrigger, setIsTrigger] = useState(false);
  const [forceMode, setForceMode] = useState(true);
  const [lastResult, setLastResult] = useState<Record<string, unknown> | null>(null);
  const [signals, setSignals] = useState<unknown[]>([]);
  const [log, setLog] = useState<string[]>([]);

  const addLog = (msg: string) =>
    setLog(prev => [`[${new Date().toLocaleTimeString()}] ${msg}`, ...prev.slice(0, 49)]);

  const refreshStatus = useCallback(async () => {
    try {
      const [hRes, mRes] = await Promise.all([
        api.fetch('/health'),
        api.fetch('/api/trading/mode'),
      ]);
      if (hRes.ok) setStatus(await hRes.json());
      if (mRes.ok) { const d = await mRes.json(); setTradingMode(d.mode ?? 'PAPER'); }
    } catch { /* backend may be down */ }
  }, []);

  useEffect(() => {
    refreshStatus();
    const t = setInterval(refreshStatus, 10_000);
    return () => clearInterval(t);
  }, [refreshStatus]);

  const handleTrigger = async () => {
    setIsTrigger(true);
    addLog(`Triggering cycle (force=${forceMode})…`);
    try {
      const res = await api.fetch(`/trigger-cycle?force=${forceMode}`, { method: 'POST' });
      
      // Check if response is OK before parsing JSON
      if (!res.ok) {
        const errorText = await res.text();
        let errorMsg = `HTTP ${res.status}`;
        try {
          const errorData = JSON.parse(errorText);
          errorMsg = errorData.error || errorData.message || errorMsg;
        } catch {
          errorMsg = errorText.substring(0, 100); // Show first 100 chars of error
        }
        addLog(`❌ Error: ${errorMsg}`);
        return;
      }
      
      const data = await res.json();
      setLastResult(data);
      addLog(`✅ Cycle done in ${data.elapsed_ms ?? '?'}ms — market_open=${data.market_open}, agents=${data.agents_running}`);
      // Fetch any new pending signals
      const sRes = await api.fetch('/api/trading/approvals');
      if (sRes.ok) {
        const sd = await sRes.json();
        setSignals(sd.approvals ?? []);
        addLog(`📡 ${sd.approvals?.length ?? 0} pending signal(s) in approval queue`);
      }
    } catch (e: unknown) {
      addLog(`❌ Error: ${e instanceof Error ? e.message : 'request failed'}`);
    } finally {
      setIsTrigger(false);
      refreshStatus();
    }
  };

  const statusDot = (ok: boolean | undefined) =>
    ok ? 'bg-green-400 animate-pulse' : 'bg-red-500';

  return (
    <div className="space-y-5">
      {/* ── System Status strip ── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[
          { label: 'Backend',      value: status ? 'Online' : 'Checking…', ok: !!status },
          { label: 'Agents',       value: status?.agents_running ? 'Running' : 'Stopped',    ok: status?.agents_running },
          { label: 'Market',       value: status?.market_open   ? 'Open (NSE)' : 'Closed',  ok: status?.market_open },
          { label: 'Trading Mode', value: tradingMode,
            ok: tradingMode === 'PAPER' },
        ].map(({ label, value, ok }) => (
          <div key={label} className="bg-gray-900 border border-gray-800 rounded-lg p-3 flex items-center gap-2">
            <span className={`w-2 h-2 rounded-full shrink-0 ${statusDot(ok as boolean)}`} />
            <div>
              <p className="text-[10px] text-gray-500 uppercase tracking-wide">{label}</p>
              <p className="text-xs font-bold text-white">{value}</p>
            </div>
          </div>
        ))}
      </div>

      {/* ── Trigger Panel ── */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
        <h3 className="text-sm font-bold text-white mb-1">Manual Cycle Trigger</h3>
        <p className="text-xs text-gray-400 mb-4">
          Fires one full orchestration cycle (Sense → Strategy → Risk → Execute).
          Use <strong className="text-yellow-400">Force Mode</strong> to run outside market hours (09:15–15:30) during paper testing.
        </p>

        <div className="flex flex-wrap items-center gap-3 mb-4">
          <label className="flex items-center gap-2 cursor-pointer select-none">
            <div
              onClick={() => setForceMode(f => !f)}
              className={`w-10 h-5 rounded-full transition-colors relative cursor-pointer ${
                forceMode ? 'bg-yellow-600' : 'bg-gray-700'
              }`}
            >
              <span className={`absolute top-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${
                forceMode ? 'translate-x-5' : 'translate-x-0.5'
              }`} />
            </div>
            <span className="text-xs text-gray-300">
              Force Mode <span className="text-gray-500">(bypass market-hours gate)</span>
            </span>
          </label>

          {!forceMode && !status?.market_open && (
            <span className="text-xs text-amber-400 bg-amber-950/40 border border-amber-800/40 px-2 py-1 rounded">
              ⚠ Market closed — cycle will be skipped unless Force Mode is on
            </span>
          )}
        </div>

        <button
          onClick={handleTrigger}
          disabled={isTrigger}
          className={`px-6 py-2.5 rounded-lg text-sm font-bold transition-all ${
            isTrigger
              ? 'bg-gray-700 text-gray-500 cursor-not-allowed'
              : 'bg-blue-600 hover:bg-blue-500 text-white shadow-lg shadow-blue-900/40'
          }`}
        >
          {isTrigger ? '⏳ Running Cycle…' : '▶ Trigger Signal Cycle Now'}
        </button>

        {lastResult && (
          <div className="mt-4 bg-green-950/30 border border-green-800/40 rounded-lg p-3 text-xs text-green-300 font-mono">
            <pre>{JSON.stringify(lastResult, null, 2)}</pre>
          </div>
        )}
      </div>

      {/* ── Pending Signals ── */}
      {signals.length > 0 && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
          <h3 className="text-sm font-bold text-white mb-3">📊 Pending Signals ({signals.length})</h3>
          <div className="space-y-2">
            {(signals as Array<Record<string,unknown>>).map((s, i) => (
              <div key={i} className="flex items-center justify-between bg-gray-800/60 rounded-lg px-3 py-2 text-xs">
                <span className="text-white font-medium">{String(s.symbol ?? s.ticker ?? 'N/A')}</span>
                <span className={`px-2 py-0.5 rounded font-bold ${
                  String(s.action ?? s.direction ?? '') === 'BUY'
                    ? 'bg-green-900/60 text-green-300'
                    : 'bg-red-900/60 text-red-300'
                }`}>{String(s.action ?? s.direction ?? 'SIGNAL')}</span>
                <span className="text-gray-400">{String(s.strategy ?? s.strategyId ?? '')}</span>
                <span className="text-gray-500">{String(s.strength ? `${(Number(s.strength)*100).toFixed(0)}%` : '')}</span>
              </div>
            ))}
          </div>
        </div>
      )}
      {signals.length === 0 && lastResult && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 text-center">
          <p className="text-gray-500 text-sm">No signals generated this cycle.</p>
          <p className="text-gray-600 text-xs mt-1">
            Strategies need market data. With DB disconnected, scanner returns synthetic data.
            Signals fire when strategy conditions are met (e.g. Donchian breakout, RSI divergence).
          </p>
        </div>
      )}

      {/* ── Cycle Log ── */}
      {log.length > 0 && (
        <div className="bg-gray-950 border border-gray-800 rounded-xl p-4">
          <h3 className="text-xs font-bold text-gray-500 uppercase tracking-wider mb-2">Cycle Log</h3>
          <div className="space-y-1 font-mono text-xs">
            {log.map((entry, i) => (
              <p key={i} className={`${
                entry.includes('✅') ? 'text-green-400' :
                entry.includes('❌') ? 'text-red-400' :
                entry.includes('📡') ? 'text-blue-400' : 'text-gray-500'
              }`}>{entry}</p>
            ))}
          </div>
        </div>
      )}

      {/* ── Why no signals? ── */}
      <div className="bg-amber-950/20 border border-amber-800/30 rounded-xl p-4">
        <h3 className="text-xs font-bold text-amber-400 uppercase tracking-wide mb-2">Why are no strategies recommended?</h3>
        <ol className="space-y-1.5 text-xs text-gray-400 list-decimal list-inside">
          <li><strong className="text-white">DB disconnected</strong> — PostgreSQL not running. Start with <code className="text-indigo-400">docker-compose up postgres redis</code></li>
          <li><strong className="text-white">Market closed</strong> — Cycles skip outside 09:15–15:30 IST unless Force Mode is enabled above</li>
          <li><strong className="text-white">No broker data</strong> — DhanHQ credentials empty in <code className="text-indigo-400">.env</code>. Scanner uses synthetic data fallback</li>
          <li><strong className="text-white">Strategy conditions not met</strong> — Most strategies need volatility conditions (e.g. ATR breakout, IV rank &gt;50). SIDEWAYS regime suppresses directional signals</li>
          <li><strong className="text-white">Grade F strategies disabled</strong> — Strategies scored F are not recommended until they accumulate paper trade history</li>
        </ol>
      </div>
    </div>
  );
}

export default function ControlsPage() {
  const {
    controlsLoaded,
    setControlsSnapshot,
    regimeOverride,
    positionSizing,
    rateLimitConfig,
    instrumentFilter,
  } = useDashboard();

  const [tab, setTab]   = useState<TabId>('strategies');
  const [loading, setLoading] = useState(!controlsLoaded);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    if (controlsLoaded) return;
    (async () => {
      try {
        const res = await api.fetch(`/api/controls/snapshot`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const snap: ControlsSnapshot = await res.json();
        setControlsSnapshot(snap);
      } catch (e: unknown) {
        setLoadError(e instanceof Error ? e.message : 'Failed to load controls');
      } finally {
        setLoading(false);
      }
    })();
  }, [controlsLoaded, setControlsSnapshot]);

  // Build active-override badges for the header
  const activeOverrides: string[] = [];
  if (regimeOverride.active && regimeOverride.regime)    activeOverrides.push(`Regime: ${regimeOverride.regime}`);
  if (positionSizing.is_overridden)  activeOverrides.push(`Sizing: ${Math.round(positionSizing.multiplier * 100)}%`);
  if (rateLimitConfig.is_overridden) activeOverrides.push(`Rate: ${rateLimitConfig.max_orders_per_cycle}/cycle`);
  if (instrumentFilter.count > 0)    activeOverrides.push(`Blacklist: ${instrumentFilter.count}`);

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      <div className="max-w-7xl mx-auto px-4 py-8 space-y-6">

        {/* ─── Page header ────────────────────────────────────────────────────── */}
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-white">Manual Controls</h1>
            <p className="text-sm text-gray-400 mt-1">
              All user-driven overrides. Every change is logged to the SEBI audit trail.
            </p>
          </div>

          {/* Active override badges */}
          {activeOverrides.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {activeOverrides.map((o) => (
                <span key={o} className="px-2.5 py-1 bg-yellow-900/60 border border-yellow-700/50 rounded-full text-xs text-yellow-300 font-medium">
                  {o}
                </span>
              ))}
            </div>
          )}
        </div>

        {/* ─── Loading / error state ──────────────────────────────────────────── */}
        {loading && (
          <div className="flex items-center justify-center py-20 text-gray-500">
            <svg className="animate-spin w-5 h-5 mr-2" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            Loading controls…
          </div>
        )}

        {loadError && !loading && (
          <div className="bg-red-950 border border-red-800 rounded-lg p-4 text-sm text-red-300">
            <strong>Failed to load controls:</strong> {loadError}
            <br />
            <span className="text-gray-500">Is the backend running on localhost:8000?</span>
          </div>
        )}

        {!loading && !loadError && (
          <>
            {/* ─── Tab bar ─────────────────────────────────────────────────────── */}
            <div className="flex gap-1 bg-gray-900/60 rounded-xl p-1 w-fit">
              {TABS.map((t) => (
                <button
                  key={t.id}
                  onClick={() => setTab(t.id)}
                  className={`flex items-center gap-1.5 px-4 py-2 text-sm rounded-lg font-medium transition-all ${
                    tab === t.id
                      ? 'bg-blue-600 text-white shadow'
                      : 'text-gray-400 hover:text-white hover:bg-gray-800'
                  }`}
                >
                  <span>{t.icon}</span>
                  {t.label}
                </button>
              ))}
            </div>

            {/* ─── Tab content ─────────────────────────────────────────────────── */}
            <div className="bg-gray-900/30 border border-gray-800/60 rounded-xl p-5">
              {tab === 'strategies'  && <StrategyManager />}
              {tab === 'risk'        && <RiskControlPanel />}
              {tab === 'scanners'    && <ScannerControlPanel />}
              {tab === 'instruments' && <InstrumentFilter />}
              {tab === 'backtest'    && <><BacktestConfig /><div className="mt-3 text-center"><a href="/backtesting" className="text-xs text-indigo-400 hover:text-indigo-300 underline">Open Full Backtesting Analysis →</a></div></>}
              {tab === 'montecarlo'  && <MonteCarloPanel />}
              {tab === 'paper'       && <PaperTestingPanel />}
              {tab === 'operations'  && <OperationsControlPanel />}
            </div>

            {/* ─── SEBI audit footer ────────────────────────────────────────────── */}
            <div className="flex items-center justify-between text-xs text-gray-600 border-t border-gray-800 pt-4">
              <span>All actions are logged to the SEBI-compliant audit trail.</span>
              <a
                href="/api/controls/audit-log"
                target="_blank"
                rel="noopener noreferrer"
                className="text-blue-600 hover:text-blue-400 underline"
              >
                View Audit Log →
              </a>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
