import { ChartColumn, RefreshCw } from 'lucide-react'
import { Link } from 'react-router-dom'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { Button } from '../components/Button'
import { PageHeader } from '../components/PageHeader'
import { Panel } from '../components/Panel'
import { EmptyState, ErrorNotice, Loading } from '../components/States'
import { useAsync } from '../hooks/useAsync'
import { api } from '../services/api'
import type { AnalyticsResponse } from '../types/api'
import { formatCost, formatMs, formatPercent, formatTokens, humanize } from '../utils/format'

const AXIS = { stroke: '#5d6f87', fontSize: 12, tickLine: false }
const TOOLTIP = {
  contentStyle: { background: '#1c2b3e', border: '1px solid #34496a', borderRadius: 8, fontSize: 13 },
  labelStyle: { color: '#e6ecf3' },
  itemStyle: { color: '#e6ecf3' },
  cursor: { fill: '#1c2b3e' },
}

export function AnalyticsPage() {
  const analytics = useAsync(() => api.analytics(), [])
  const d = analytics.data

  return (
    <>
      <PageHeader
        title="Analytics"
        description="Measured from every recorded request: reliability, speed, retries, caching and estimated LLM spend."
        actions={
          <Button size="sm" icon={<RefreshCw size={14} />} onClick={analytics.reload} disabled={analytics.loading}>
            Refresh
          </Button>
        }
      />
      {analytics.error ? (
        <ErrorNotice error={analytics.error} onRetry={analytics.reload} />
      ) : !d ? (
        <Loading />
      ) : d.total_requests === 0 ? (
        <EmptyState icon={<ChartColumn size={28} />} title="No requests recorded yet">
          <p>Metrics are computed from real requests only. Ask a few questions and they’ll show up here.</p>
          <Link to="/" className="mt-4 inline-flex h-10 items-center rounded-lg bg-amber px-4 text-sm font-semibold text-night">
            Ask a question
          </Link>
        </EmptyState>
      ) : (
        <Dashboard d={d} />
      )}
    </>
  )
}

function Dashboard({ d }: { d: AnalyticsResponse }) {
  const recent = d.recent_requests.map((r, i) => ({
    n: i + 1,
    total: r.total_ms,
    llm: r.generation_ms,
    status: r.status,
  }))

  return (
    <div className="space-y-5">
      {/* Primary readouts */}
      <div className="grid gap-px overflow-hidden rounded-xl border border-line bg-line sm:grid-cols-2 lg:grid-cols-4">
        <Readout
          label="Requests"
          value={d.total_requests.toLocaleString()}
          sub={`${d.successful_requests} succeeded, ${d.failed_requests} did not`}
        />
        <Readout label="Success rate" value={formatPercent(d.success_rate)} sub={`${d.rejected_requests} blocked, ${d.unanswerable_requests} not answerable`} />
        <Readout label="Average latency" value={formatMs(d.avg_latency_ms)} sub={`p95 ${formatMs(d.p95_latency_ms)}`} />
        <Readout
          label="Estimated LLM cost"
          value={d.priced_requests ? formatCost(d.total_estimated_cost_usd) : 'Unavailable'}
          sub={
            d.priced_requests
              ? `${formatCost(d.avg_estimated_cost_per_request_usd)} per priced request`
              : 'No request reported token usage'
          }
        />
      </div>

      <dl className="grid grid-cols-2 gap-x-6 gap-y-4 rounded-xl border border-line bg-panel px-5 py-4 text-sm sm:grid-cols-3 lg:grid-cols-6">
        <Small label="Retry rate" value={formatPercent(d.retry_rate)} />
        <Small label="Retries that recovered" value={formatPercent(d.retry_success_rate)} />
        <Small label="Cache hit rate" value={formatPercent(d.cache_hit_rate)} hint={`${d.cache_hits} hits`} />
        <Small label="LLM calls" value={d.llm_calls.toLocaleString()} />
        <Small label="Input tokens" value={formatTokens(d.total_input_tokens)} />
        <Small label="Output tokens" value={formatTokens(d.total_output_tokens)} />
      </dl>
      {d.unpriced_requests > 0 && (
        <p className="text-sm text-muted">
          {d.unpriced_requests} {d.unpriced_requests === 1 ? 'request' : 'requests'} had no token usage (for example the offline mock
          provider), so {d.unpriced_requests === 1 ? 'its' : 'their'} cost is unknown and excluded rather than counted as $0.
          Costs are estimates at list price.
        </p>
      )}

      <div className="grid gap-5 lg:grid-cols-2">
        <Panel title="Requests per day">
          <div className="h-64">
            <ResponsiveContainer>
              <BarChart data={d.requests_by_day} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
                <CartesianGrid stroke="#26384f" vertical={false} />
                <XAxis dataKey="date" {...AXIS} />
                <YAxis allowDecimals={false} {...AXIS} axisLine={false} />
                <Tooltip {...TOOLTIP} />
                <Legend formatter={(v: string) => humanize(v)} />
                <Bar dataKey="success" stackId="a" fill="#5bd08a" maxBarSize={40} />
                <Bar dataKey="failed" stackId="a" fill="#f07a8a" radius={[3, 3, 0, 0]} maxBarSize={40} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Panel>

        <Panel title="Latency of recent requests" description="Total request time vs time spent waiting on the LLM.">
          <div className="h-64">
            <ResponsiveContainer>
              <LineChart data={recent} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                <CartesianGrid stroke="#26384f" vertical={false} />
                <XAxis dataKey="n" {...AXIS} />
                <YAxis {...AXIS} axisLine={false} tickFormatter={(v: number) => formatMs(v)} width={64} />
                <Tooltip {...TOOLTIP} formatter={(v) => formatMs(Number(v))} labelFormatter={(n) => `Request ${n}`} />
                <Legend formatter={(v: string) => (v === 'total' ? 'Total' : 'LLM')} />
                <Line type="monotone" dataKey="total" stroke="#f2b544" strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="llm" stroke="#6ea8fe" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Panel>

        <Panel title="Why requests didn’t succeed">
          {d.failure_categories.length === 0 ? (
            <p className="text-muted">Every recorded request succeeded.</p>
          ) : (
            <div style={{ height: Math.max(120, d.failure_categories.length * 44) }}>
              <ResponsiveContainer>
                <BarChart data={d.failure_categories} layout="vertical" margin={{ top: 0, right: 16, left: 8, bottom: 0 }}>
                  <XAxis type="number" allowDecimals={false} {...AXIS} />
                  <YAxis type="category" dataKey="category" width={150} tickFormatter={(v: string) => humanize(v)} {...AXIS} />
                  <Tooltip {...TOOLTIP} labelFormatter={(v) => humanize(String(v))} />
                  <Bar dataKey="count" fill="#f0a35b" radius={[0, 3, 3, 0]} maxBarSize={22} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </Panel>

        <Panel title="Time breakdown" description="Averages over requests that ran the full pipeline (cache hits excluded).">
          <dl className="space-y-3 text-sm">
            <Breakdown label="LLM (generation + corrections)" value={d.avg_generation_ms} total={d.avg_latency_ms} color="bg-sky" />
            <Breakdown label="Database execution" value={d.avg_db_ms} total={d.avg_latency_ms} color="bg-teal" />
          </dl>
          <p className="mt-4 text-sm text-muted">
            Cache: {d.cache.entries} of {d.cache.max_entries} entries in memory, {d.cache.ttl_seconds / 60} minute lifetime.
          </p>
        </Panel>
      </div>
    </div>
  )
}

function Readout({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div className="bg-panel px-5 py-4">
      <p className="text-sm text-muted">{label}</p>
      <p className="mt-1 text-[1.75rem] font-semibold tabular-nums tracking-tight text-ink">{value}</p>
      <p className="mt-0.5 text-xs text-faint">{sub}</p>
    </div>
  )
}

function Small({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div>
      <dt className="text-faint">{label}</dt>
      <dd className="font-medium tabular-nums text-ink" title={hint}>
        {value}
      </dd>
    </div>
  )
}

function Breakdown({ label, value, total, color }: { label: string; value: number | null; total: number | null; color: string }) {
  const pct = value !== null && total ? Math.min(100, (value / total) * 100) : 0
  return (
    <div>
      <div className="flex justify-between">
        <dt className="text-muted">{label}</dt>
        <dd className="tabular-nums text-ink">{formatMs(value)}</dd>
      </div>
      <div className="mt-1.5 h-1.5 rounded-full bg-raised">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}
