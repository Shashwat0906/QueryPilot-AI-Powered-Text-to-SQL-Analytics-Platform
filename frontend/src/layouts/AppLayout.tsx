import {
  ChartColumn,
  Code2,
  Database,
  History,
  Menu,
  MessageSquareText,
  PanelLeftClose,
  PanelLeftOpen,
  Settings,
  Table2,
  X,
} from 'lucide-react'
import { Suspense, useEffect, useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { useAsync } from '../hooks/useAsync'
import { Loading } from '../components/States'
import { api } from '../services/api'

const NAV = [
  { to: '/', label: 'Ask', icon: MessageSquareText, end: true },
  { to: '/sql', label: 'SQL viewer', icon: Code2 },
  { to: '/results', label: 'Results', icon: Table2 },
  { to: '/schema', label: 'Schema', icon: Database },
  { to: '/analytics', label: 'Analytics', icon: ChartColumn },
  { to: '/history', label: 'History', icon: History },
  { to: '/settings', label: 'Settings', icon: Settings },
]

const COLLAPSE_KEY = 'querypilot.sidebarCollapsed'

function readCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSE_KEY) === '1'
  } catch {
    return false
  }
}

function Logo({ compact }: { compact: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <svg width="26" height="26" viewBox="0 0 32 32" aria-hidden>
        <circle cx="16" cy="16" r="11" fill="none" stroke="#F2B544" strokeWidth="2.5" />
        <path d="M16 16 L23 9" stroke="#F2B544" strokeWidth="2.5" strokeLinecap="round" />
        <circle cx="16" cy="16" r="2.4" fill="#E6ECF3" />
      </svg>
      {!compact && <span className="text-[1.05rem] font-semibold tracking-tight text-ink">QueryPilot</span>}
    </div>
  )
}

export function AppLayout() {
  const [collapsed, setCollapsed] = useState(readCollapsed)
  const [mobileOpen, setMobileOpen] = useState(false)
  const health = useAsync(() => api.health(), [])

  // Re-check backend health every 30 s so the status dot doesn't go stale.
  const reloadHealth = health.reload
  useEffect(() => {
    const id = window.setInterval(reloadHealth, 30_000)
    return () => window.clearInterval(id)
  }, [reloadHealth])

  useEffect(() => {
    try {
      localStorage.setItem(COLLAPSE_KEY, collapsed ? '1' : '0')
    } catch {
      /* storage unavailable - preference just won't persist */
    }
  }, [collapsed])

  const nav = (compact: boolean) => (
    <nav aria-label="Main" className="flex flex-col gap-0.5">
      {NAV.map(({ to, label, icon: Icon, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          title={compact ? label : undefined}
          onClick={() => setMobileOpen(false)}
          className={({ isActive }) =>
            `flex h-10 items-center gap-3 rounded-lg px-3 text-sm transition-colors ${
              isActive ? 'bg-amber-soft text-amber' : 'text-muted hover:bg-raised hover:text-ink'
            } ${compact ? 'justify-center px-0' : ''}`
          }
        >
          <Icon size={18} aria-hidden />
          {compact ? <span className="sr-only">{label}</span> : label}
        </NavLink>
      ))}
    </nav>
  )

  // Free hosting puts the API to sleep when idle; the first request can take
  // about a minute. Say so instead of showing a silent spinner.
  const [slowStart, setSlowStart] = useState(false)
  const waiting = health.loading && !health.data
  useEffect(() => {
    if (!waiting) return
    const id = window.setTimeout(() => setSlowStart(true), 4000)
    return () => window.clearTimeout(id)
  }, [waiting])

  const h = health.data
  const statusLabel = health.error
    ? 'Backend offline'
    : !h
      ? 'Connecting…'
      : h.status === 'ok' || h.database === 'ok'
        ? h.llm_configured
          ? `${h.llm_provider === 'anthropic' ? 'Claude' : 'OpenAI-compatible LLM'} connected`
          : 'Offline mock LLM'
        : 'Database unavailable'
  const statusColor =
    health.error || h?.database === 'error'
      ? 'bg-bad'
      : !h
        ? 'bg-faint'
        : h.llm_configured && h.history_storage === 'persistent'
          ? 'bg-ok'
          : 'bg-warn'

  return (
    <div className="flex min-h-screen">
      {/* Desktop / tablet sidebar */}
      <aside
        className={`sticky top-0 hidden h-screen shrink-0 flex-col border-r border-line bg-panel transition-[width] duration-200 md:flex ${
          collapsed ? 'w-[68px] px-2.5' : 'w-60 px-3'
        }`}
      >
        <div className={`flex h-16 items-center ${collapsed ? 'justify-center' : 'px-2'}`}>
          <Logo compact={collapsed} />
        </div>
        {nav(collapsed)}
        <button
          type="button"
          onClick={() => setCollapsed((c) => !c)}
          className={`mt-auto mb-4 flex h-10 items-center gap-3 rounded-lg px-3 text-sm text-muted hover:bg-raised hover:text-ink ${collapsed ? 'justify-center px-0' : ''}`}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          aria-expanded={!collapsed}
        >
          {collapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}
          {!collapsed && 'Collapse'}
        </button>
      </aside>

      {/* Mobile drawer */}
      {mobileOpen && (
        <div className="fixed inset-0 z-40 md:hidden" role="dialog" aria-modal="true" aria-label="Navigation">
          <button type="button" className="absolute inset-0 bg-black/60" aria-label="Close navigation" onClick={() => setMobileOpen(false)} />
          <div className="absolute inset-y-0 left-0 flex w-64 flex-col border-r border-line bg-panel px-3">
            <div className="flex h-16 items-center justify-between px-2">
              <Logo compact={false} />
              <button type="button" onClick={() => setMobileOpen(false)} className="rounded-md p-2 text-muted hover:text-ink" aria-label="Close navigation">
                <X size={18} />
              </button>
            </div>
            {nav(false)}
          </div>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-line bg-night/90 px-4 backdrop-blur sm:px-6">
          <button type="button" onClick={() => setMobileOpen(true)} className="-ml-1 rounded-md p-2 text-muted hover:text-ink md:hidden" aria-label="Open navigation">
            <Menu size={20} />
          </button>
          <div className="md:hidden">
            <Logo compact={false} />
          </div>
          <div className="ml-auto flex items-center gap-2 text-sm text-muted" role="status">
            <span className={`h-2 w-2 rounded-full ${statusColor}`} aria-hidden />
            <span className="hidden sm:inline">{statusLabel}</span>
          </div>
        </header>
        {waiting && slowStart && (
          <div role="status" className="border-b border-warn/30 bg-warn/5 px-4 py-2 text-sm text-muted sm:px-6">
            <span className="font-medium text-ink">Waking up the server.</span> The free hosting plan sleeps when idle, so
            the first request can take about a minute.
          </div>
        )}
        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 sm:px-6 sm:py-8">
          <Suspense fallback={<Loading />}>
            <Outlet />
          </Suspense>
        </main>
      </div>
    </div>
  )
}
