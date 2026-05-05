'use client';

import React, { useCallback, useEffect, useState } from 'react';

import { useDashboard } from '@/stores/dashboard';
import { ControlsSnapshot } from '@/types';
import { api } from '@/lib/api';

type CommandJournalEntry = {
  command_id?: string;
  ts?: string;
  action?: string;
  scope?: string;
  status?: string;
  operator?: string;
  reason?: string;
  note?: string;
};

type MorningBriefResponse = {
  status: 'found' | 'empty' | 'accepted' | 'error';
  context?: Record<string, unknown>;
  stored?: Record<string, unknown>;
  message?: string;
  detail?: string;
};

type DiagnosticsLatest = {
  cycle_id?: string;
  timestamp?: string;
  findings?: Array<Record<string, unknown>>;
  critical_count?: number;
  warning_count?: number;
  info_count?: number;
  auto_fixes_applied?: number | unknown[];
  run_duration_ms?: number;
  message?: string;
  error?: string;
};

type AlphaDecaySummary = {
  total?: number;
  green?: number;
  amber?: number;
  red?: number;
  retire_candidates?: string[];
};

type AlphaDecayStatus = {
  generated_at?: string;
  crowding_score?: number;
  crowding_alert?: boolean;
  crowding_message?: string;
  summary?: AlphaDecaySummary;
};

type ActionBanner = {
  text: string;
  ok: boolean;
};

type TextCommandPlan = {
  command: string;
  normalized_command?: string;
  intent?: string;
  scope?: string;
  mutates_state?: boolean;
  requires_confirmation?: boolean;
  operator?: string;
  reason?: string;
  summary?: string;
  parameters?: Record<string, unknown>;
};

type TextCommandApprovalRequest = {
  id: string;
  requestId: string;
  command: string;
  intent?: string;
  summary?: string;
  parameters: Record<string, unknown>;
  timestamp: string;
  expiresAt: string;
  expiresIn: number;
  status: 'PENDING' | 'APPROVED' | 'REJECTED';
  scope?: string;
};

type TextCommandResponse = {
  success: boolean;
  recognized: boolean;
  dry_run: boolean;
  queued_for_approval?: boolean;
  plan?: TextCommandPlan;
  approval_request?: {
    request_id: string;
    status: string;
    expires_at: string;
    ttl_seconds: number;
  };
  result?: Record<string, unknown>;
  error?: string;
  supported_examples?: string[];
};

type TextCommandApprovalsResponse = {
  count: number;
  approvals: TextCommandApprovalRequest[];
};

type TextCommandDecisionResponse = {
  success: boolean;
  approved: boolean;
  request_id: string;
  command: string;
  result?: Record<string, unknown>;
  message?: string;
  error?: string;
};

const TEXT_COMMAND_EXAMPLES = [
  'disable equity scanner',
  'enable option scanner',
  'disable leg monitor',
  'set approval timeout to 45 seconds',
  'set regime override to bear for 30 minutes',
  'clear regime override',
  'set position sizing to 0.5x for 4 hours',
  'set rate limit to 6 orders per cycle',
];

function formatDisplayValue(value: unknown): string {
  if (value == null) return '—';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function formatTs(ts?: string): string {
  if (!ts) return '—';
  const date = new Date(ts);
  return Number.isNaN(date.getTime()) ? ts : date.toLocaleString('en-IN');
}

function formatExpiresIn(expiresIn?: number): string {
  if (typeof expiresIn !== 'number' || Number.isNaN(expiresIn)) return '—';
  if (expiresIn >= 60) return `${Math.ceil(expiresIn / 60)}m left`;
  return `${Math.max(0, Math.ceil(expiresIn))}s left`;
}

export function OperationsControlPanel() {
  const setControlsSnapshot = useDashboard((state) => state.setControlsSnapshot);

  const [briefNote, setBriefNote] = useState('');
  const [briefData, setBriefData] = useState<Record<string, unknown> | null>(null);
  const [diagnostics, setDiagnostics] = useState<DiagnosticsLatest | null>(null);
  const [alphaDecay, setAlphaDecay] = useState<AlphaDecayStatus | null>(null);
  const [journalEntries, setJournalEntries] = useState<CommandJournalEntry[]>([]);
  const [lastPortfolioAction, setLastPortfolioAction] = useState<Record<string, unknown> | null>(null);
  const [textCommand, setTextCommand] = useState('');
  const [textCommandReason, setTextCommandReason] = useState('');
  const [textCommandResponse, setTextCommandResponse] = useState<TextCommandResponse | null>(null);
  const [textCommandApprovals, setTextCommandApprovals] = useState<TextCommandApprovalRequest[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [banner, setBanner] = useState<ActionBanner | null>(null);

  const toast = useCallback((text: string, ok = true) => {
    setBanner({ text, ok });
    window.setTimeout(() => setBanner(null), 4000);
  }, []);

  const refreshJournal = useCallback(async () => {
    const data = await api.get<{ entries?: CommandJournalEntry[] }>('/api/controls/command-journal?limit=15');
    setJournalEntries(data.entries ?? []);
  }, []);

  const refreshControlsSnapshot = useCallback(async () => {
    const data = await api.get<ControlsSnapshot>('/api/controls/snapshot');
    setControlsSnapshot(data);
  }, [setControlsSnapshot]);

  const refreshTextCommandApprovals = useCallback(async () => {
    const data = await api.get<TextCommandApprovalsResponse>('/api/controls/text-command/approvals');
    setTextCommandApprovals(data.approvals ?? []);
  }, []);

  const refreshMorningBrief = useCallback(async () => {
    const data = await api.get<MorningBriefResponse>('/api/project-lead/morning-brief');
    const context = data.context ?? data.stored ?? null;
    setBriefData(context);
    setBriefNote(typeof context?.operator_note === 'string' ? context.operator_note : '');
  }, []);

  const refreshDiagnostics = useCallback(async () => {
    const data = await api.get<DiagnosticsLatest>('/api/system/diagnostics');
    setDiagnostics(data);
  }, []);

  const refreshAlphaDecay = useCallback(async () => {
    const data = await api.get<AlphaDecayStatus>('/api/alpha-decay/status');
    setAlphaDecay(data);
  }, []);

  const refreshAll = useCallback(async () => {
    setLoading(true);
    try {
      await Promise.all([
        refreshControlsSnapshot(),
        refreshMorningBrief(),
        refreshDiagnostics(),
        refreshAlphaDecay(),
        refreshJournal(),
        refreshTextCommandApprovals(),
      ]);
    } catch (error) {
      toast(error instanceof Error ? error.message : 'Failed to load operations data', false);
    } finally {
      setLoading(false);
    }
  }, [
    refreshAlphaDecay,
    refreshControlsSnapshot,
    refreshDiagnostics,
    refreshJournal,
    refreshMorningBrief,
    refreshTextCommandApprovals,
    toast,
  ]);

  useEffect(() => {
    refreshAll();
  }, [refreshAll]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      void refreshTextCommandApprovals().catch(() => undefined);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [refreshTextCommandApprovals]);

  const runAction = useCallback(async <T,>(
    actionId: string,
    runner: () => Promise<T>,
    onSuccess: (result: T) => Promise<void> | void,
    successMessage: string,
  ) => {
    setBusyAction(actionId);
    try {
      const result = await runner();
      await onSuccess(result);
      toast(successMessage, true);
      await refreshJournal();
    } catch (error) {
      toast(error instanceof Error ? error.message : 'Operation failed', false);
    } finally {
      setBusyAction(null);
    }
  }, [refreshJournal, toast]);

  const handleBriefSubmit = async () => {
    await runAction(
      'brief-submit',
      () => api.post<MorningBriefResponse>('/api/project-lead/morning-brief', { operator_note: briefNote }),
      async (result) => {
        const stored = result.stored ?? result.context ?? null;
        setBriefData(stored);
        setBriefNote(typeof stored?.operator_note === 'string' ? stored.operator_note : briefNote.trim().slice(0, 200));
      },
      'Morning brief saved for the next pre-market cycle.',
    );
  };

  const handleForcePreMarketFetch = async () => {
    await runAction(
      'pre-market-fetch',
      () => api.post<{ context?: Record<string, unknown> }>('/api/system/force-pre-market-fetch'),
      async (result) => {
        setBriefData(result.context ?? null);
      },
      'Pre-market context refreshed from backend.',
    );
  };

  const handlePortfolioRestore = async () => {
    await runAction(
      'portfolio-restore',
      () => api.post<Record<string, unknown>>('/api/portfolio/restore'),
      async (result) => {
        setLastPortfolioAction(result);
      },
      'Paper portfolio restored from backend state.',
    );
  };

  const handlePortfolioReset = async () => {
    if (!window.confirm('Reset the paper portfolio and clear simulated positions?')) {
      return;
    }
    await runAction(
      'portfolio-reset',
      () => api.post<Record<string, unknown>>('/api/portfolio/reset'),
      async (result) => {
        setLastPortfolioAction(result);
      },
      'Paper portfolio reset completed.',
    );
  };

  const handleDiagnosticsRun = async () => {
    await runAction(
      'diagnostics-run',
      () => api.post<DiagnosticsLatest>('/api/system/diagnostics/run'),
      async (result) => {
        setDiagnostics(result);
      },
      'Diagnostics run finished with latest backend findings.',
    );
  };

  const handleAlphaDecayRefresh = async () => {
    await runAction(
      'alpha-decay-refresh',
      () => api.post<Record<string, unknown>>('/api/alpha-decay/refresh'),
      async () => {
        await refreshAlphaDecay();
      },
      'Alpha-decay dashboard refreshed from backend state.',
    );
  };

  const handleTextCommandSubmit = useCallback(async (dryRun: boolean) => {
    const command = textCommand.trim();
    if (!command) {
      toast('Enter a text command before submitting.', false);
      return;
    }

    const actionId = dryRun ? 'text-command-preview' : 'text-command-queue';
    setBusyAction(actionId);

    try {
      const result = await api.post<TextCommandResponse>('/api/controls/text-command', {
        command,
        dry_run: dryRun,
        operator: 'controls_console',
        reason: textCommandReason.trim(),
      });

      setTextCommandResponse(result);
      await Promise.all([refreshJournal(), refreshTextCommandApprovals()]);

      if (!result.success || !result.recognized) {
        toast(result.error ?? 'Text command not recognized.', false);
        return;
      }

      if (!dryRun && result.queued_for_approval) {
        setTextCommand('');
        toast('Text command queued for approval.', true);
        return;
      }

      if (!dryRun) {
        await refreshControlsSnapshot();
      }

      toast(dryRun ? 'Text command preview generated.' : 'Text command executed.', true);
    } catch (error) {
      toast(error instanceof Error ? error.message : 'Text command request failed', false);
    } finally {
      setBusyAction(null);
    }
  }, [
    refreshControlsSnapshot,
    refreshJournal,
    refreshTextCommandApprovals,
    textCommand,
    textCommandReason,
    toast,
  ]);

  const handleTextCommandDecision = useCallback(async (requestId: string, approve: boolean) => {
    const actionId = `${approve ? 'text-command-approve' : 'text-command-reject'}-${requestId}`;
    setBusyAction(actionId);

    try {
      const result = await api.post<TextCommandDecisionResponse>(
        `/api/controls/text-command/approvals/${requestId}/${approve ? 'approve' : 'reject'}`,
        {
          operator: 'controls_console',
          reason: approve ? 'approved_from_controls_console' : 'rejected_from_controls_console',
        },
      );

      if (!result.success) {
        toast(result.error ?? 'Unable to resolve text command approval.', false);
        return;
      }

      await Promise.all([
        refreshJournal(),
        refreshTextCommandApprovals(),
        approve ? refreshControlsSnapshot() : Promise.resolve(),
      ]);
      toast(approve ? 'Text command approved and applied.' : 'Text command rejected.', true);
    } catch (error) {
      toast(error instanceof Error ? error.message : 'Approval action failed', false);
    } finally {
      setBusyAction(null);
    }
  }, [refreshControlsSnapshot, refreshJournal, refreshTextCommandApprovals, toast]);

  const busy = (actionId: string) => busyAction === actionId;
  const diagnosticFindings = diagnostics?.findings ?? [];
  const autoFixCount = Array.isArray(diagnostics?.auto_fixes_applied)
    ? diagnostics?.auto_fixes_applied.length
    : Number(diagnostics?.auto_fixes_applied ?? 0);
  const supportedExamples = textCommandResponse?.supported_examples?.length
    ? textCommandResponse.supported_examples
    : TEXT_COMMAND_EXAMPLES;

  return (
    <div className="space-y-6">
      {banner && (
        <div className={`rounded-lg border px-4 py-3 text-sm ${banner.ok ? 'bg-emerald-950/30 border-emerald-700/40 text-emerald-300' : 'bg-red-950/30 border-red-700/40 text-red-300'}`}>
          {banner.text}
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold text-white">Operations Console</h2>
          <p className="text-sm text-gray-400 mt-1">
            User-facing controls for pre-market context, portfolio recovery, diagnostics, alpha-decay refresh, and command-journal visibility.
          </p>
        </div>
        <button
          onClick={refreshAll}
          disabled={loading}
          className="px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 disabled:opacity-50"
        >
          {loading ? 'Refreshing…' : 'Refresh All'}
        </button>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
        <section className="xl:col-span-2 bg-gray-950/70 border border-gray-800 rounded-xl p-5 space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h3 className="text-sm font-bold text-white">Text Admin Controls</h3>
              <p className="text-xs text-gray-400 mt-1">
                Preview bounded text commands first. Mutating commands queue for approval and expire after five minutes.
              </p>
            </div>
            <div className="flex items-center gap-2">
              <span className="rounded-full border border-slate-700 bg-slate-900/80 px-3 py-1 text-xs text-slate-300">
                Pending: {textCommandApprovals.length}
              </span>
              <button
                onClick={refreshTextCommandApprovals}
                disabled={loading}
                className="px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 disabled:opacity-50"
              >
                Refresh Queue
              </button>
            </div>
          </div>

          <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1.2fr)_minmax(0,0.8fr)] gap-5">
            <div className="space-y-4">
              <div className="space-y-3">
                <textarea
                  value={textCommand}
                  onChange={(event) => {
                    setTextCommand(event.target.value);
                    setTextCommandResponse(null);
                  }}
                  placeholder="Example: disable equity scanner"
                  className="w-full min-h-28 bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-blue-500"
                />
                <input
                  value={textCommandReason}
                  onChange={(event) => setTextCommandReason(event.target.value.slice(0, 160))}
                  placeholder="Optional operator note for the journal"
                  className="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-blue-500"
                />
                <div className="flex flex-wrap gap-2">
                  <button
                    onClick={() => void handleTextCommandSubmit(true)}
                    disabled={busy('text-command-preview')}
                    className="px-4 py-2 rounded-lg text-sm font-medium bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-50"
                  >
                    {busy('text-command-preview') ? 'Previewing…' : 'Preview Plan'}
                  </button>
                  <button
                    onClick={() => void handleTextCommandSubmit(false)}
                    disabled={busy('text-command-queue')}
                    className="px-4 py-2 rounded-lg text-sm font-medium bg-amber-700 hover:bg-amber-600 text-white disabled:opacity-50"
                  >
                    {busy('text-command-queue') ? 'Queueing…' : 'Queue for Approval'}
                  </button>
                </div>
              </div>

              <div className="space-y-2">
                <p className="text-[11px] font-semibold text-gray-300 uppercase tracking-wide">Quick Examples</p>
                <div className="flex flex-wrap gap-2">
                  {supportedExamples.map((example) => (
                    <button
                      key={example}
                      onClick={() => {
                        setTextCommand(example);
                        setTextCommandResponse(null);
                      }}
                      className="rounded-full border border-gray-700 bg-gray-900/80 px-3 py-1 text-xs text-gray-300 hover:border-blue-500 hover:text-white"
                    >
                      {example}
                    </button>
                  ))}
                </div>
              </div>

              <div className="bg-gray-900/80 border border-gray-800 rounded-lg p-3 space-y-3">
                <p className="text-[11px] font-semibold text-gray-300 uppercase tracking-wide">Latest Text Command Result</p>
                {textCommandResponse ? (
                  <>
                    <div className="flex flex-wrap items-center gap-2 text-xs">
                      <span className={`rounded-full px-2.5 py-1 font-semibold ${
                        textCommandResponse.success && textCommandResponse.recognized
                          ? 'bg-emerald-900/40 text-emerald-300 border border-emerald-700/40'
                          : 'bg-red-900/40 text-red-300 border border-red-700/40'
                      }`}>
                        {textCommandResponse.success && textCommandResponse.recognized
                          ? textCommandResponse.queued_for_approval
                            ? 'Queued'
                            : textCommandResponse.dry_run
                              ? 'Preview Ready'
                              : 'Applied'
                          : 'Unsupported'}
                      </span>
                      {textCommandResponse.plan?.intent && (
                        <span className="text-gray-400">Intent: <span className="text-gray-200">{textCommandResponse.plan.intent}</span></span>
                      )}
                    </div>

                    {textCommandResponse.plan?.summary && (
                      <p className="text-sm text-white font-medium">{textCommandResponse.plan.summary}</p>
                    )}

                    {textCommandResponse.error && (
                      <p className="text-sm text-red-300">{textCommandResponse.error}</p>
                    )}

                    {textCommandResponse.plan?.parameters && (
                      <div className="rounded-lg border border-gray-800 bg-gray-950 px-3 py-2">
                        <p className="text-[11px] uppercase tracking-wide text-gray-500 mb-1">Parameters</p>
                        <pre className="text-xs text-gray-300 whitespace-pre-wrap break-all">{JSON.stringify(textCommandResponse.plan.parameters, null, 2)}</pre>
                      </div>
                    )}

                    {textCommandResponse.approval_request && (
                      <div className="rounded-lg border border-amber-700/30 bg-amber-950/20 px-3 py-2 text-xs text-amber-200">
                        Request {textCommandResponse.approval_request.request_id} queued until {formatTs(textCommandResponse.approval_request.expires_at)}.
                      </div>
                    )}
                  </>
                ) : (
                  <p className="text-xs text-gray-500">No text command has been previewed or queued from the UI yet.</p>
                )}
              </div>
            </div>

            <div className="bg-gray-900/80 border border-gray-800 rounded-lg p-3 space-y-3">
              <div className="flex items-center justify-between gap-3">
                <p className="text-[11px] font-semibold text-gray-300 uppercase tracking-wide">Pending Approvals</p>
                <span className="text-xs text-gray-500">Auto-refresh 5s</span>
              </div>

              <div className="space-y-2 max-h-[28rem] overflow-y-auto pr-1">
                {textCommandApprovals.length > 0 ? textCommandApprovals.map((approval) => (
                  <div key={approval.id} className="rounded-lg border border-gray-800 bg-gray-950 px-3 py-3 space-y-3">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div>
                        <p className="text-sm font-semibold text-white">{approval.summary ?? approval.command}</p>
                        <p className="text-xs text-gray-400 mt-1">{approval.command}</p>
                      </div>
                      <div className="text-right text-xs">
                        <p className="text-amber-300">{formatExpiresIn(approval.expiresIn)}</p>
                        <p className="text-gray-500">{formatTs(approval.expiresAt)}</p>
                      </div>
                    </div>

                    <div className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-gray-400">
                      <span>Intent: <span className="text-gray-200">{approval.intent ?? '—'}</span></span>
                      <span>Status: <span className="text-gray-200">{approval.status}</span></span>
                      <span>Queued: <span className="text-gray-200">{formatTs(approval.timestamp)}</span></span>
                    </div>

                    <div className="rounded-lg border border-gray-800 bg-gray-900/80 px-3 py-2">
                      <p className="text-[11px] uppercase tracking-wide text-gray-500 mb-1">Parameters</p>
                      <pre className="text-xs text-gray-300 whitespace-pre-wrap break-all">{JSON.stringify(approval.parameters ?? {}, null, 2)}</pre>
                    </div>

                    <div className="flex flex-wrap gap-2">
                      <button
                        onClick={() => void handleTextCommandDecision(approval.requestId, true)}
                        disabled={busy(`text-command-approve-${approval.requestId}`)}
                        className="px-3 py-1.5 rounded-lg text-xs font-medium bg-emerald-700 hover:bg-emerald-600 text-white disabled:opacity-50"
                      >
                        {busy(`text-command-approve-${approval.requestId}`) ? 'Approving…' : 'Approve and Apply'}
                      </button>
                      <button
                        onClick={() => void handleTextCommandDecision(approval.requestId, false)}
                        disabled={busy(`text-command-reject-${approval.requestId}`)}
                        className="px-3 py-1.5 rounded-lg text-xs font-medium bg-red-700 hover:bg-red-600 text-white disabled:opacity-50"
                      >
                        {busy(`text-command-reject-${approval.requestId}`) ? 'Rejecting…' : 'Reject'}
                      </button>
                    </div>
                  </div>
                )) : (
                  <p className="text-xs text-gray-500">No text command approvals are pending right now.</p>
                )}
              </div>
            </div>
          </div>
        </section>

        <section className="bg-gray-950/70 border border-gray-800 rounded-xl p-5 space-y-4">
          <div>
            <h3 className="text-sm font-bold text-white">Morning Brief</h3>
            <p className="text-xs text-gray-400 mt-1">Push operator guidance into the next day commander cycle and inspect the stored pre-market context.</p>
          </div>
          <textarea
            value={briefNote}
            onChange={(event) => setBriefNote(event.target.value.slice(0, 200))}
            placeholder="Example: RBI hawkish, avoid early longs until breadth confirms."
            className="w-full min-h-28 bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-blue-500"
          />
          <div className="flex flex-wrap gap-2">
            <button
              onClick={handleBriefSubmit}
              disabled={busy('brief-submit')}
              className="px-4 py-2 rounded-lg text-sm font-medium bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-50"
            >
              {busy('brief-submit') ? 'Saving…' : 'Save Morning Brief'}
            </button>
            <button
              onClick={handleForcePreMarketFetch}
              disabled={busy('pre-market-fetch')}
              className="px-4 py-2 rounded-lg text-sm font-medium bg-violet-700 hover:bg-violet-600 text-white disabled:opacity-50"
            >
              {busy('pre-market-fetch') ? 'Refreshing…' : 'Force Pre-Market Fetch'}
            </button>
          </div>
          <div className="bg-gray-900/80 border border-gray-800 rounded-lg p-3">
            <p className="text-[11px] font-semibold text-gray-300 uppercase tracking-wide mb-2">Current Context</p>
            {briefData ? (
              <div className="space-y-1 text-xs">
                {Object.entries(briefData).slice(0, 8).map(([key, value]) => (
                  <div key={key} className="flex items-start justify-between gap-3">
                    <span className="text-gray-500 uppercase tracking-wide">{key}</span>
                    <span className="text-right text-gray-200 break-all">{formatDisplayValue(value)}</span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-gray-500">No morning brief or pre-market context has been stored yet.</p>
            )}
          </div>
        </section>

        <section className="bg-gray-950/70 border border-gray-800 rounded-xl p-5 space-y-4">
          <div>
            <h3 className="text-sm font-bold text-white">Diagnostics and Alpha Decay</h3>
            <p className="text-xs text-gray-400 mt-1">Run backend diagnostics on demand and refresh alpha-decay status without leaving the controls console.</p>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {[
              { label: 'Critical', value: diagnostics?.critical_count ?? 0, tone: 'text-red-400' },
              { label: 'Warnings', value: diagnostics?.warning_count ?? 0, tone: 'text-yellow-400' },
              { label: 'Info', value: diagnostics?.info_count ?? 0, tone: 'text-sky-400' },
              { label: 'Auto Fixes', value: autoFixCount, tone: 'text-emerald-400' },
            ].map((item) => (
              <div key={item.label} className="bg-gray-900 border border-gray-800 rounded-lg p-3">
                <p className="text-[10px] uppercase tracking-wide text-gray-500">{item.label}</p>
                <p className={`mt-1 text-lg font-bold ${item.tone}`}>{item.value}</p>
              </div>
            ))}
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              onClick={handleDiagnosticsRun}
              disabled={busy('diagnostics-run')}
              className="px-4 py-2 rounded-lg text-sm font-medium bg-amber-700 hover:bg-amber-600 text-white disabled:opacity-50"
            >
              {busy('diagnostics-run') ? 'Running…' : 'Run Diagnostics Now'}
            </button>
            <button
              onClick={handleAlphaDecayRefresh}
              disabled={busy('alpha-decay-refresh')}
              className="px-4 py-2 rounded-lg text-sm font-medium bg-emerald-700 hover:bg-emerald-600 text-white disabled:opacity-50"
            >
              {busy('alpha-decay-refresh') ? 'Refreshing…' : 'Refresh Alpha Decay'}
            </button>
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            <div className="bg-gray-900/80 border border-gray-800 rounded-lg p-3 space-y-2">
              <p className="text-[11px] font-semibold text-gray-300 uppercase tracking-wide">Latest Diagnostics</p>
              {diagnostics ? (
                <>
                  <p className="text-xs text-gray-400">Last run: <span className="text-gray-200">{formatTs(diagnostics.timestamp)}</span></p>
                  <p className="text-xs text-gray-400">Duration: <span className="text-gray-200">{diagnostics.run_duration_ms ?? '—'} ms</span></p>
                  {diagnosticFindings.length > 0 ? (
                    <ul className="space-y-1 text-xs text-gray-300">
                      {diagnosticFindings.slice(0, 3).map((finding, index) => (
                        <li key={`${finding.finding_id ?? finding.id ?? index}`} className="border-t border-gray-800 pt-2 first:border-0 first:pt-0">
                          <span className="font-medium text-white">{formatDisplayValue(finding.title ?? finding.message ?? finding.id ?? 'Finding')}</span>
                          <span className="block text-gray-500">{formatDisplayValue(finding.severity ?? finding.level ?? 'unknown')}</span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-xs text-gray-500">{diagnostics.message ?? 'No findings reported yet.'}</p>
                  )}
                </>
              ) : (
                <p className="text-xs text-gray-500">Diagnostics data not loaded yet.</p>
              )}
            </div>
            <div className="bg-gray-900/80 border border-gray-800 rounded-lg p-3 space-y-2">
              <p className="text-[11px] font-semibold text-gray-300 uppercase tracking-wide">Alpha Decay Snapshot</p>
              {alphaDecay ? (
                <>
                  <p className="text-xs text-gray-400">Generated: <span className="text-gray-200">{formatTs(alphaDecay.generated_at)}</span></p>
                  <p className="text-xs text-gray-400">Crowding: <span className={`${alphaDecay.crowding_alert ? 'text-red-400' : 'text-emerald-400'}`}>{typeof alphaDecay.crowding_score === 'number' ? alphaDecay.crowding_score.toFixed(3) : '—'}</span></p>
                  <div className="grid grid-cols-2 gap-2 text-xs">
                    <div className="bg-gray-950 border border-gray-800 rounded px-2 py-2 text-gray-300">Green: {alphaDecay.summary?.green ?? 0}</div>
                    <div className="bg-gray-950 border border-gray-800 rounded px-2 py-2 text-yellow-300">Amber: {alphaDecay.summary?.amber ?? 0}</div>
                    <div className="bg-gray-950 border border-gray-800 rounded px-2 py-2 text-red-300">Red: {alphaDecay.summary?.red ?? 0}</div>
                    <div className="bg-gray-950 border border-gray-800 rounded px-2 py-2 text-sky-300">Retire: {alphaDecay.summary?.retire_candidates?.length ?? 0}</div>
                  </div>
                  {alphaDecay.crowding_message && (
                    <p className="text-xs text-gray-400 border-t border-gray-800 pt-2">{alphaDecay.crowding_message}</p>
                  )}
                </>
              ) : (
                <p className="text-xs text-gray-500">Alpha-decay status not loaded yet.</p>
              )}
            </div>
          </div>
        </section>

        <section className="bg-gray-950/70 border border-gray-800 rounded-xl p-5 space-y-4">
          <div>
            <h3 className="text-sm font-bold text-white">Portfolio Recovery Actions</h3>
            <p className="text-xs text-gray-400 mt-1">Restore or reset paper-trading state and see the latest backend response immediately.</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              onClick={handlePortfolioRestore}
              disabled={busy('portfolio-restore')}
              className="px-4 py-2 rounded-lg text-sm font-medium bg-sky-700 hover:bg-sky-600 text-white disabled:opacity-50"
            >
              {busy('portfolio-restore') ? 'Restoring…' : 'Restore Portfolio'}
            </button>
            <button
              onClick={handlePortfolioReset}
              disabled={busy('portfolio-reset')}
              className="px-4 py-2 rounded-lg text-sm font-medium bg-red-700 hover:bg-red-600 text-white disabled:opacity-50"
            >
              {busy('portfolio-reset') ? 'Resetting…' : 'Reset Portfolio'}
            </button>
          </div>
          <div className="bg-gray-900/80 border border-gray-800 rounded-lg p-3">
            <p className="text-[11px] font-semibold text-gray-300 uppercase tracking-wide mb-2">Latest Portfolio Action</p>
            {lastPortfolioAction ? (
              <pre className="text-xs text-gray-300 whitespace-pre-wrap break-all">{JSON.stringify(lastPortfolioAction, null, 2)}</pre>
            ) : (
              <p className="text-xs text-gray-500">No portfolio action has been triggered from the UI yet.</p>
            )}
          </div>
        </section>

        <section className="bg-gray-950/70 border border-gray-800 rounded-xl p-5 space-y-4">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h3 className="text-sm font-bold text-white">Command Journal</h3>
              <p className="text-xs text-gray-400 mt-1">Latest privileged actions recorded through the shared backend journal.</p>
            </div>
            <button
              onClick={refreshJournal}
              disabled={loading}
              className="px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 disabled:opacity-50"
            >
              Refresh Journal
            </button>
          </div>
          <div className="space-y-2 max-h-80 overflow-y-auto pr-1">
            {journalEntries.length > 0 ? journalEntries.slice().reverse().map((entry) => (
              <div key={entry.command_id ?? `${entry.action}-${entry.ts}`} className="rounded-lg border border-gray-800 bg-gray-900/80 px-3 py-2">
                <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                  <span className="font-semibold text-white">{entry.action ?? 'unknown_action'}</span>
                  <span className="text-gray-500">{formatTs(entry.ts)}</span>
                </div>
                <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-gray-400">
                  <span>Scope: <span className="text-gray-200">{entry.scope ?? '—'}</span></span>
                  <span>Status: <span className="text-gray-200">{entry.status ?? '—'}</span></span>
                  <span>Operator: <span className="text-gray-200">{entry.operator ?? '—'}</span></span>
                </div>
                {(entry.note || entry.reason) && (
                  <p className="mt-2 text-xs text-gray-300">{entry.note ?? entry.reason}</p>
                )}
              </div>
            )) : (
              <p className="text-xs text-gray-500">No command-journal entries are available yet.</p>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}