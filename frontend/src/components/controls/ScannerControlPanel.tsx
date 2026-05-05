'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { api } from '@/lib/api';

interface ScannerControls {
  is_overridden: boolean;
  equity_scanner_enabled: boolean;
  option_scanner_enabled: boolean;
  scan_frequency_sec: number;
  scanner_min_score: number;
  scanner_concurrency: number;
  scanner_ai_enabled: boolean;
  option_scanner_equity_count: number;
  option_scanner_min_score: number;
  option_scanner_gemini_enabled: boolean;
  legmonitor_enabled: boolean;
  legmonitor_max_loss_pct: number;
  legmonitor_profit_target_pct: number;
  legmonitor_exit_time: string;
  event_penalty_high: number;
  event_penalty_medium: number;
  event_penalty_low: number;
}

interface RiskOverrides {
  is_overridden: boolean;
  kelly_fraction: number;
  max_position_pct: number;
  max_daily_loss_pct: number;
  max_sector_exposure_pct: number;
  max_open_positions: number;
  max_options_positions: number;
}

interface ParamOverride {
  id: string;
  strategy_id: string;
  parameter_name: string;
  override_value: number;
  created_at: string;
  expires_at: string;
  reason: string;
}

export function ScannerControlPanel() {
  const [controls, setControls] = useState<ScannerControls | null>(null);
  const [risk, setRisk] = useState<RiskOverrides | null>(null);
  const [paramOverrides, setParamOverrides] = useState<ParamOverride[]>([]);
  const [saving, setSaving] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ text: string; ok: boolean } | null>(null);

  // Parameter override form
  const [poStrategy, setPoStrategy] = useState('');
  const [poParam, setPoParam] = useState('');
  const [poValue, setPoValue] = useState('');
  const [poTtl, setPoTtl] = useState(60);
  const [poReason, setPoReason] = useState('');

  // Dropdown data from backend
  const [strategyOptions, setStrategyOptions] = useState<{id: string; name: string; category: string; module: string}[]>([]);
  const [strategyParams, setStrategyParams] = useState<Record<string, Record<string, {min: number; max: number; step: number; default: number}>>>({});

  // Risk override form
  const [roType, setRoType] = useState('kelly_fraction');
  const [roValue, setRoValue] = useState('');
  const [roTtl, setRoTtl] = useState(0);

  const toast = (text: string, ok = true) => {
    setMsg({ text, ok });
    setTimeout(() => setMsg(null), 3500);
  };

  const loadAll = useCallback(async () => {
    try {
      const [sc, rs, po, dd] = await Promise.all([
        api.fetch('/api/controls/scanners').then(r => r.json()),
        api.fetch('/api/manual-controls/risk-state').then(r => r.json()),
        api.fetch('/api/manual-controls/parameter-overrides').then(r => r.json()),
        api.fetch('/api/manual-controls/dropdown-options').then(r => r.json()),
      ]);
      setControls(sc);
      setRisk(rs);
      setParamOverrides(po.overrides || []);
      if (dd.strategies) setStrategyOptions(dd.strategies);
      if (dd.strategy_params) setStrategyParams(dd.strategy_params);
    } catch {
      toast('Failed to load scanner controls', false);
    }
  }, []);

  useEffect(() => { loadAll(); }, [loadAll]);

  // ── Toggle handlers ─────────────────────────────────────────────────────────
  const toggleScanner = async (type: 'equity' | 'options' | 'legmonitor', enabled: boolean) => {
    setSaving(type);
    try {
      await api.fetch(`/api/controls/scanners/${type}/toggle`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled, reason: `Manual ${type} ${enabled ? 'enable' : 'disable'}` }),
      });
      toast(`${type} scanner ${enabled ? 'enabled' : 'disabled'}`);
      loadAll();
    } catch {
      toast(`Failed to toggle ${type}`, false);
    } finally {
      setSaving(null);
    }
  };

  const updateScannerParam = async (key: string, value: number) => {
    setSaving(key);
    try {
      await api.fetch('/api/controls/scanners', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ [key]: value, reason: `Updated ${key} to ${value}` }),
      });
      toast(`${key} updated to ${value}`);
      loadAll();
    } catch {
      toast(`Failed to update ${key}`, false);
    } finally {
      setSaving(null);
    }
  };

  // ── Parameter override handlers ────────────────────────────────────────────
  const addParamOverride = async () => {
    if (!poStrategy || !poParam || !poValue) return;
    setSaving('param');
    try {
      const res = await api.fetch('/api/manual-controls/parameter-override', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          strategy_id: poStrategy, parameter_name: poParam,
          override_value: parseFloat(poValue), ttl_minutes: poTtl, reason: poReason,
        }),
      });
      const data = await res.json();
      if (!data.success) throw new Error(data.error || 'Validation failed');
      toast(`Parameter ${poParam} set to ${poValue}`);
      setPoStrategy(''); setPoParam(''); setPoValue(''); setPoReason('');
      loadAll();
    } catch (e: unknown) {
      toast(e instanceof Error ? e.message : 'Error', false);
    } finally {
      setSaving(null);
    }
  };

  const removeParamOverride = async (id: string) => {
    setSaving(`del-${id}`);
    try {
      await api.fetch(`/api/manual-controls/parameter-override/${id}`, { method: 'DELETE' });
      toast('Override removed');
      loadAll();
    } catch {
      toast('Failed to remove override', false);
    } finally {
      setSaving(null);
    }
  };

  // ── Risk override handlers ─────────────────────────────────────────────────
  const setRiskOverride = async () => {
    if (!roValue) return;
    setSaving('risk');
    try {
      await api.fetch('/api/manual-controls/risk-override', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ override_type: roType, override_value: parseFloat(roValue), ttl_minutes: roTtl }),
      });
      toast(`${roType} set to ${roValue}`);
      setRoValue('');
      loadAll();
    } catch {
      toast('Failed to set risk override', false);
    } finally {
      setSaving(null);
    }
  };

  const clearRiskOverrides = async () => {
    setSaving('risk-clear');
    try {
      await api.fetch('/api/manual-controls/risk-override', { method: 'DELETE' });
      toast('Risk overrides reset to defaults');
      loadAll();
    } catch {
      toast('Failed to clear risk overrides', false);
    } finally {
      setSaving(null);
    }
  };

  if (!controls) return <div className="text-gray-500 text-sm py-8 text-center">Loading scanner controls…</div>;

  return (
    <div className="space-y-6">
      {msg && (
        <div className={`px-4 py-2 rounded-lg text-sm font-medium ${msg.ok ? 'bg-green-900/40 text-green-300 border border-green-800' : 'bg-red-900/40 text-red-300 border border-red-800'}`}>
          {msg.text}
        </div>
      )}

      {/* ── Scanner Toggles ─────────────────────────────────────────────────── */}
      <div>
        <h3 className="text-sm font-bold text-blue-400 uppercase tracking-wide mb-3">🔍 Scanner Agents</h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {/* Equity Scanner */}
          <div className="bg-gray-800/50 rounded-lg p-4 border border-gray-700/50">
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-medium text-white">Equity Scanner</span>
              <button
                onClick={() => toggleScanner('equity', !controls.equity_scanner_enabled)}
                disabled={saving === 'equity'}
                className={`px-3 py-1 rounded-full text-xs font-bold transition-all ${
                  controls.equity_scanner_enabled
                    ? 'bg-green-700 text-green-100 hover:bg-green-600'
                    : 'bg-red-800 text-red-200 hover:bg-red-700'
                }`}
              >
                {saving === 'equity' ? '…' : controls.equity_scanner_enabled ? 'ON' : 'OFF'}
              </button>
            </div>
            <p className="text-xs text-gray-500">225 stocks, 14 indicators, {controls.scan_frequency_sec}s cycle</p>
          </div>

          {/* Option Scanner */}
          <div className="bg-gray-800/50 rounded-lg p-4 border border-gray-700/50">
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-medium text-white">Option Scanner</span>
              <button
                onClick={() => toggleScanner('options', !controls.option_scanner_enabled)}
                disabled={saving === 'options'}
                className={`px-3 py-1 rounded-full text-xs font-bold transition-all ${
                  controls.option_scanner_enabled
                    ? 'bg-green-700 text-green-100 hover:bg-green-600'
                    : 'bg-red-800 text-red-200 hover:bg-red-700'
                }`}
              >
                {saving === 'options' ? '…' : controls.option_scanner_enabled ? 'ON' : 'OFF'}
              </button>
            </div>
            <p className="text-xs text-gray-500">F&O universe, min score {controls.option_scanner_min_score}</p>
          </div>

          {/* Leg Monitor */}
          <div className="bg-gray-800/50 rounded-lg p-4 border border-gray-700/50">
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-medium text-white">Leg Monitor</span>
              <button
                onClick={() => toggleScanner('legmonitor', !controls.legmonitor_enabled)}
                disabled={saving === 'legmonitor'}
                className={`px-3 py-1 rounded-full text-xs font-bold transition-all ${
                  controls.legmonitor_enabled
                    ? 'bg-green-700 text-green-100 hover:bg-green-600'
                    : 'bg-red-800 text-red-200 hover:bg-red-700'
                }`}
              >
                {saving === 'legmonitor' ? '…' : controls.legmonitor_enabled ? 'ON' : 'OFF'}
              </button>
            </div>
            <p className="text-xs text-gray-500">Max loss {controls.legmonitor_max_loss_pct}%, exit {controls.legmonitor_exit_time}</p>
          </div>
        </div>
      </div>

      {/* ── Scanner Parameters ──────────────────────────────────────────────── */}
      <div>
        <h3 className="text-sm font-bold text-blue-400 uppercase tracking-wide mb-3">⚙️ Scanner Parameters</h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[
            { key: 'scanner_concurrency', label: 'Concurrency', value: controls.scanner_concurrency, min: 2, max: 24, step: 1 },
            { key: 'scan_frequency_sec', label: 'Frequency (sec)', value: controls.scan_frequency_sec, min: 60, max: 600, step: 30 },
            { key: 'scanner_min_score', label: 'Min Score', value: controls.scanner_min_score, min: 0, max: 100, step: 5 },
            { key: 'event_penalty_high', label: 'Event Penalty (High)', value: controls.event_penalty_high, min: 0, max: 30, step: 1 },
          ].map((p) => (
            <div key={p.key} className="bg-gray-800/50 rounded-lg p-3 border border-gray-700/50">
              <label className="text-xs text-gray-400 block mb-1">{p.label}</label>
              <input
                type="range" min={p.min} max={p.max} step={p.step} value={p.value}
                onChange={(e) => updateScannerParam(p.key, Number(e.target.value))}
                className="w-full accent-blue-500"
              />
              <span className="text-xs text-white font-mono">{p.value}</span>
            </div>
          ))}
        </div>
      </div>

      {/* ── Risk Overrides ──────────────────────────────────────────────────── */}
      <div>
        <h3 className="text-sm font-bold text-amber-400 uppercase tracking-wide mb-3">🛡 Risk Parameter Overrides</h3>
        {risk && (
          <div className="bg-gray-800/50 rounded-lg p-4 border border-gray-700/50 space-y-3">
            <div className="grid grid-cols-3 md:grid-cols-6 gap-2 text-center text-xs">
              {Object.entries(risk).filter(([k]) => k !== 'is_overridden').map(([k, v]) => (
                <div key={k} className="bg-gray-900/50 rounded p-2">
                  <div className="text-gray-500 truncate">{k.replace(/_/g, ' ')}</div>
                  <div className="text-white font-mono">{typeof v === 'number' ? v.toFixed(2) : String(v)}</div>
                </div>
              ))}
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              <select value={roType} onChange={e => setRoType(e.target.value)}
                className="bg-gray-900 text-white text-xs px-2 py-1 rounded border border-gray-700">
                {['kelly_fraction', 'max_position_pct', 'max_daily_loss_pct', 'max_sector_exposure_pct', 'max_open_positions', 'max_options_positions'].map(k => (
                  <option key={k} value={k}>{k.replace(/_/g, ' ')}</option>
                ))}
              </select>
              <input type="number" step="0.01" placeholder="Value" value={roValue} onChange={e => setRoValue(e.target.value)}
                className="bg-gray-900 text-white text-xs px-2 py-1 rounded border border-gray-700 w-24" />
              <input type="number" placeholder="TTL min (0=∞)" value={roTtl} onChange={e => setRoTtl(Number(e.target.value))}
                className="bg-gray-900 text-white text-xs px-2 py-1 rounded border border-gray-700 w-28" />
              <button onClick={setRiskOverride} disabled={saving === 'risk'}
                className="bg-amber-700 hover:bg-amber-600 text-white text-xs px-3 py-1 rounded font-medium">
                {saving === 'risk' ? '…' : 'Apply'}
              </button>
              {risk.is_overridden && (
                <button onClick={clearRiskOverrides} disabled={saving === 'risk-clear'}
                  className="bg-red-800 hover:bg-red-700 text-white text-xs px-3 py-1 rounded font-medium">
                  {saving === 'risk-clear' ? '…' : 'Reset All'}
                </button>
              )}
            </div>
          </div>
        )}
      </div>

      {/* ── Parameter Overrides ─────────────────────────────────────────────── */}
      <div>
        <h3 className="text-sm font-bold text-purple-400 uppercase tracking-wide mb-3">🎛 Strategy Parameter Overrides</h3>
        <div className="bg-gray-800/50 rounded-lg p-4 border border-gray-700/50 space-y-3">
          {/* Active overrides */}
          {paramOverrides.length > 0 ? (
            <div className="space-y-2">
              {paramOverrides.map((o) => (
                <div key={o.id} className="flex items-center justify-between bg-gray-900/50 rounded p-2 text-xs">
                  <div>
                    <span className="text-purple-300 font-medium">{o.strategy_id}</span>
                    <span className="text-gray-500 mx-1">→</span>
                    <span className="text-white">{o.parameter_name} = {o.override_value}</span>
                    {o.reason && <span className="text-gray-600 ml-2">({o.reason})</span>}
                  </div>
                  <button onClick={() => removeParamOverride(o.id)}
                    className="text-red-400 hover:text-red-300 text-xs px-2">✕</button>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-gray-600">No active parameter overrides</p>
          )}

          {/* Add new override form */}
          <div className="flex items-center gap-2 flex-wrap pt-2 border-t border-gray-700/50">
            <select value={poStrategy} onChange={e => { setPoStrategy(e.target.value); setPoParam(''); setPoValue(''); }}
              className="bg-gray-900 text-white text-xs px-2 py-1 rounded border border-gray-700 w-48">
              <option value="">Select Strategy…</option>
              {strategyOptions.map(s => (
                <option key={s.id} value={s.id}>{s.id} — {s.name}</option>
              ))}
            </select>
            <select value={poParam} onChange={e => {
              const p = e.target.value;
              setPoParam(p);
              const params = poStrategy ? (strategyParams[poStrategy] || {}) : {};
              const info = params[p];
              if (info) setPoValue(String(info.default));
              else setPoValue('');
            }}
              className="bg-gray-900 text-white text-xs px-2 py-1 rounded border border-gray-700 w-40"
              disabled={!poStrategy}>
              <option value="">{poStrategy ? 'Select Parameter…' : 'Select strategy first…'}</option>
              {poStrategy && strategyParams[poStrategy] && Object.keys(strategyParams[poStrategy]).map(name => (
                <option key={name} value={name}>{name.replace(/_/g, ' ')}</option>
              ))}
            </select>
            {poParam && poStrategy && strategyParams[poStrategy]?.[poParam] && (
              <span className="text-[10px] text-gray-500 whitespace-nowrap">
                default: {strategyParams[poStrategy][poParam].default} [{strategyParams[poStrategy][poParam].min}–{strategyParams[poStrategy][poParam].max}]
              </span>
            )}
            <input type="number" step={poParam && poStrategy && strategyParams[poStrategy]?.[poParam] ? strategyParams[poStrategy][poParam].step : 0.01}
              min={poParam && poStrategy && strategyParams[poStrategy]?.[poParam] ? strategyParams[poStrategy][poParam].min : undefined}
              max={poParam && poStrategy && strategyParams[poStrategy]?.[poParam] ? strategyParams[poStrategy][poParam].max : undefined}
              placeholder="Value" value={poValue} onChange={e => setPoValue(e.target.value)}
              className="bg-gray-900 text-white text-xs px-2 py-1 rounded border border-gray-700 w-24" />
            <input type="number" placeholder="TTL min" value={poTtl} onChange={e => setPoTtl(Number(e.target.value))}
              className="bg-gray-900 text-white text-xs px-2 py-1 rounded border border-gray-700 w-24" />
            <input placeholder="Reason" value={poReason} onChange={e => setPoReason(e.target.value)}
              className="bg-gray-900 text-white text-xs px-2 py-1 rounded border border-gray-700 flex-1 min-w-[120px]" />
            <button onClick={addParamOverride} disabled={saving === 'param'}
              className="bg-purple-700 hover:bg-purple-600 text-white text-xs px-3 py-1 rounded font-medium">
              {saving === 'param' ? '…' : 'Add Override'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
