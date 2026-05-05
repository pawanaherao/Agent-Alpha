'use client';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  LayoutDashboard, Brain, Shield, Activity,
  BarChart2, ChevronLeft, ChevronRight,
  Zap, Target, BookOpen, Cpu, SlidersHorizontal, LineChart
} from 'lucide-react';
import { useDashboard } from '@/stores/dashboard';
import { useMarketStore } from '@/stores/marketStore';
import { DataFeedAlerts } from '@/components/DataFeedAlerts';

const NAV_ITEMS = [
  {
    group: 'TRADING',
    items: [
      { href: '/', icon: LayoutDashboard, label: 'Dashboard', badge: null },
      { href: '/charts', icon: LineChart, label: 'Charts', badge: 'LIVE' },
      { href: '/positions', icon: Target, label: 'Positions', badge: null },
      { href: '/options', icon: Activity, label: 'Options', badge: 'NEW' },
    ]
  },
  {
    group: 'INTELLIGENCE',
    items: [
      { href: '/intelligence', icon: Brain, label: 'AI Layer', badge: 'AI' },
      { href: '/agents', icon: Cpu, label: 'Agents', badge: null },
      { href: '/strategy-builder', icon: BookOpen, label: 'Strategy AI', badge: null },
    ]
  },
  {
    group: 'ANALYTICS',
    items: [
      { href: '/backtesting', icon: BarChart2, label: 'Backtesting', badge: null },
      { href: '/risk', icon: Shield, label: 'Risk', badge: null },
      { href: '/controls', icon: SlidersHorizontal, label: 'Controls', badge: null },
    ]
  },
] as const;

interface AppShellProps {
  children: React.ReactNode;
}

export function AppShell({ children }: AppShellProps) {
  const [collapsed, setCollapsed] = useState(false);
  const pathname = usePathname();
  const { mode, regime, vix, capital, availableCapital } = useDashboard();
  const { isConnected, setConnected } = useMarketStore();

  // Poll backend health every 30 s — drives SYSTEM ON/OFF indicator.
  // Uses the REST API (not WebSocket) so it reflects actual data availability.
  useEffect(() => {
    let cancelled = false;
    const check = async () => {
      try {
        const res = await fetch('/health', { method: 'GET', cache: 'no-store' });
        if (!cancelled) setConnected(res.ok);
      } catch {
        if (!cancelled) setConnected(false);
      }
    };
    check(); // immediate check on mount
    const id = setInterval(check, 10_000);
    return () => { cancelled = true; clearInterval(id); };
  }, [setConnected]);

  const deployed = capital - availableCapital;
  const deployedPct = capital > 0 ? (deployed / capital) * 100 : 0;

  const regimeColor: Record<string, string> = {
    BULL: 'text-emerald-400',
    BEAR: 'text-red-400',
    SIDEWAYS: 'text-amber-400',
    VOLATILE: 'text-purple-400',
  };

  const [isMounted, setIsMounted] = useState(false);
  React.useEffect(() => {
    setIsMounted(true);
  }, []);

  if (!isMounted) return null;

  return (
    <div className="flex h-screen overflow-hidden bg-slate-950 font-sans">
      {/* ─── Sidebar ─────────────────────────────────────────────────── */}
      <aside
        className={`flex flex-col border-r border-slate-800 bg-slate-900 transition-all duration-200 ${collapsed ? 'w-[56px]' : 'w-[220px]'
          }`}
      >
        {/* Logo */}
        <div className="flex items-center gap-3 px-3 py-4 border-b border-slate-800">
          <div className="w-8 h-8 bg-gradient-to-br from-indigo-600 to-purple-600 rounded-lg flex-shrink-0 flex items-center justify-center">
            <Zap className="w-4 h-4 text-white" />
          </div>
          {!collapsed && (
            <div className="overflow-hidden">
              <span className="text-sm font-bold text-white tracking-widest">AGENT</span>
              <span className="text-sm font-bold text-purple-400 tracking-widest"> ALPHA</span>
              <sup className="text-[9px] text-purple-500 ml-0.5">PRO</sup>
            </div>
          )}
        </div>

        {/* Status pill */}
        {!collapsed && (
          <div className="mx-3 mt-3 px-2 py-1.5 rounded bg-slate-950/50 border border-slate-800 text-[10px] space-y-1">
            <div className="flex items-center justify-between">
              <span className="text-slate-400">SYSTEM</span>
              <span className={`font-bold ${isConnected ? 'text-emerald-400' : 'text-red-400'}`}>
                {isConnected ? '● LIVE' : '○ OFF'}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-400">MODE</span>
              <span className={`font-bold ${mode === 'LIVE' ? 'text-red-400' : 'text-amber-400'}`}>
                {mode}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-400">REGIME</span>
              <span className={`font-bold ${regimeColor[regime] ?? 'text-slate-400'}`}>{regime}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-400">VIX</span>
              <span className={`font-bold ${vix > 20 ? 'text-red-400' : 'text-emerald-400'}`}>{vix.toFixed(1)}</span>
            </div>
          </div>
        )}

        {/* Nav */}
        <nav className="flex-1 overflow-y-auto py-3 px-1.5 space-y-4">
          {NAV_ITEMS.map((group) => (
            <div key={group.group}>
              {!collapsed && (
                <p className="px-2 mb-1 text-[9px] font-bold text-slate-500 tracking-widest">
                  {group.group}
                </p>
              )}
              {group.items.map((item) => {
                const Icon = item.icon;
                const active = pathname === item.href ||
                  (item.href !== '/' && pathname.startsWith(item.href));
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    title={collapsed ? item.label : undefined}
                    className={`flex items-center gap-2.5 px-2 py-2 rounded-md text-xs transition-all group ${active
                      ? 'bg-blue-950/40 text-blue-300 border border-blue-900/50 shadow-sm'
                      : 'text-slate-400 hover:text-slate-100 hover:bg-slate-800'
                      }`}
                  >
                    <Icon className={`w-4 h-4 flex-shrink-0 ${active ? 'text-indigo-400' : 'group-hover:text-gray-300'}`} />
                    {!collapsed && (
                      <>
                        <span className="flex-1 font-medium">{item.label}</span>
                        {item.badge && (
                          <span className={`text-[9px] px-1 py-0.5 rounded font-bold ${item.badge === 'AI' ? 'bg-purple-900/60 text-purple-300 border border-purple-700' :
                            item.badge === 'NEW' ? 'bg-emerald-900/60 text-emerald-300 border border-emerald-700' :
                              'bg-gray-800 text-gray-400'
                            }`}>
                            {item.badge}
                          </span>
                        )}
                      </>
                    )}
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>

        {/* Capital bar */}
        {!collapsed && (
          <div className="mx-3 mb-3 px-2 py-2 rounded bg-slate-950/50 border border-slate-800 text-[10px]">
            <div className="flex justify-between mb-1">
              <span className="text-slate-400">DEPLOYED</span>
              <span className="text-white font-bold font-mono">₹{(deployed / 1000).toFixed(0)}K / ₹{(capital / 100000).toFixed(1)}L</span>
            </div>
            <div className="h-1 bg-slate-800 rounded-full overflow-hidden">
              <div
                className="h-full bg-gradient-to-r from-blue-500 to-indigo-500 rounded-full transition-all"
                style={{ width: `${Math.min(deployedPct, 100)}%` }}
              />
            </div>
          </div>
        )}

        {/* Collapse toggle */}
        <button
          onClick={() => setCollapsed(!collapsed)}
          className="flex items-center justify-center h-9 border-t border-slate-800 text-slate-500 hover:text-slate-200 transition-colors bg-slate-900"
        >
          {collapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
        </button>
      </aside>

      {/* ─── Main content ─────────────────────────────────────────────── */}
      <main className="flex-1 overflow-auto">
        {children}
      </main>

      {/* ─── Global notifications ─────────────────────────────────────── */}
      <DataFeedAlerts />
    </div>
  );
}
