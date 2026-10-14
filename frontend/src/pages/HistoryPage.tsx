import { History as HistoryIcon, Play, Search, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AttemptList } from '../components/AttemptList'
import { Button } from '../components/Button'
import { PageHeader } from '../components/PageHeader'
import { Panel } from '../components/Panel'
import { SqlBlock } from '../components/SqlBlock'
import { EmptyState, ErrorNotice, Loading } from '../components/States'
import { StatusBadge } from '../components/StatusBadge'
import { useAsync } from '../hooks/useAsync'
import { useQuerySession } from '../hooks/useQuerySession'
import { api } from '../services/api'
import type { HistoryDetail } from '../types/api'
import { formatCost, formatMs, formatTimestamp, formatTokens } from '../utils/format'

const PAGE = 25
const FILTERS = [
  { value: '', label: 'All' },
  { value: 'success', label: 'Succeeded' },
  { value: 'failed', label: 'Failed' },
  { value: 'rejected', label: 'Blocked' },
  { value: 'unanswerable', label: 'Not answerable' },
]

export function HistoryPage() {
  const [status, setStatus] = useState('')
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  const [offset, setOffset] = useState(0)
  const [selected, setSelected] = useState<string | null>(null)
  const list = useAsync(() => api.history({ limit: PAGE, offset, status, search }), [status, search, offset])
  const config = useAsync(() => api.config(), [])
  const privateHistory = config.data?.history_scope === 'client'

  useEffect(() => {
    const t = window.setTimeout(() => {
      setSearch(searchInput.trim())
      setOffset(0)
    }, 300)
    return () => window.clearTimeout(t)
  }, [searchInput])

  const data = list.data
  // With the detail panel open, numeric columns move into it so questions stay readable.

  return (
    <>
      <PageHeader
        title="Query history"
        description={
          privateHistory
            ? 'Questions asked from this browser, newest first. Other visitors can’t see them.'
            : 'Every question asked through this backend, newest first. Stored on the server, so it survives restarts.'
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="relative min-w-0 flex-1 sm:max-w-sm">
          <Search size={16} className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-faint" aria-hidden />
          <input
            type="search"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="Search questions"
            aria-label="Search questions"
            className="h-10 w-full rounded-lg border border-line-strong bg-panel pr-3 pl-9 text-sm text-ink placeholder:text-faint"
          />
        </div>
        <div className="flex flex-wrap gap-1" role="group" aria-label="Filter by status">
          {FILTERS.map((f) => (
            <button
              key={f.value}
              type="button"
              aria-pressed={status === f.value}
              onClick={() => {
                setStatus(f.value)
                setOffset(0)
              }}
              className={`h-9 rounded-lg px-3 text-sm ${status === f.value ? 'bg-raised text-ink' : 'text-muted hover:text-ink'}`}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {list.error ? (
        <ErrorNotice error={list.error} onRetry={list.reload} />
      ) : !data && list.loading ? (
        <Loading />
      ) : data && data.total === 0 ? (
        <EmptyState icon={<HistoryIcon size={28} />} title={search || status ? 'No matching requests' : 'No questions asked yet'}>
          {search || status ? 'Try a different search or filter.' : 'Requests appear here as soon as you run one from the Ask page.'}
        </EmptyState>
      ) : data ? (
        <div className={`grid gap-5 ${selected ? 'lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]' : ''}`}>
          <div>
            <div className="overflow-x-auto rounded-xl border border-line">
              <table className="w-full text-sm">
                <thead className="bg-panel text-left text-muted">
                  <tr>
                    <th scope="col" className="px-4 py-2.5 font-medium">Question</th>
                    <th scope="col" className="px-3 py-2.5 font-medium">Status</th>
                    <th scope="col" className={`hidden px-3 py-2.5 text-right font-medium ${selected ? '' : 'sm:table-cell'}`}>Time</th>
                    <th scope="col" className={`hidden px-3 py-2.5 text-right font-medium ${selected ? '' : 'md:table-cell'}`}>Retries</th>
                    <th scope="col" className={`hidden px-3 py-2.5 text-right font-medium ${selected ? '' : 'lg:table-cell'}`}>Cost</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((item) => (
                    <tr
                      key={item.request_id}
                      className={`border-t border-line ${selected === item.request_id ? 'bg-amber-soft' : 'hover:bg-panel'}`}
                    >
                      <td className="px-4 py-2.5">
                        <button
                          type="button"
                          onClick={() => setSelected(item.request_id)}
                          className="line-clamp-2 block w-full text-left text-ink hover:text-amber"
                          aria-label={`Inspect: ${item.question}`}
                        >
                          {item.question}
                        </button>
                        <span className="text-xs text-faint">
                          {formatTimestamp(item.created_at)}
                          {item.cache_hit && ', from cache'}
                        </span>
                      </td>
                      <td className="px-3 py-2.5 whitespace-nowrap">
                        <StatusBadge status={item.status} />
                      </td>
                      <td className={`hidden px-3 py-2.5 text-right tabular-nums whitespace-nowrap text-muted ${selected ? '' : 'sm:table-cell'}`}>{formatMs(item.total_ms)}</td>
                      <td className={`hidden px-3 py-2.5 text-right tabular-nums text-muted ${selected ? '' : 'md:table-cell'}`}>{item.retry_count}</td>
                      <td className={`hidden px-3 py-2.5 text-right tabular-nums whitespace-nowrap text-muted ${selected ? '' : 'lg:table-cell'}`}>
                        {item.cost_status === 'unavailable' ? <span className="text-faint">n/a</span> : formatCost(item.estimated_cost_usd)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="mt-3 flex items-center justify-between text-sm text-muted">
              <span>
                {offset + 1}–{Math.min(offset + PAGE, data.total)} of {data.total}
              </span>
              <div className="flex gap-2">
                <Button size="sm" disabled={offset === 0} onClick={() => setOffset((o) => Math.max(0, o - PAGE))}>
                  Newer
                </Button>
                <Button size="sm" disabled={offset + PAGE >= data.total} onClick={() => setOffset((o) => o + PAGE)}>
                  Older
                </Button>
              </div>
            </div>
          </div>
          {selected && <DetailPanel id={selected} onClose={() => setSelected(null)} />}
        </div>
      ) : null}
    </>
  )
}

function DetailPanel({ id, onClose }: { id: string; onClose: () => void }) {
  const detail = useAsync(() => api.historyDetail(id), [id])
  const session = useQuerySession()
  const navigate = useNavigate()

  function rerun(d: HistoryDetail) {
    session.setDraft(d.question)
    void session.run(d.question)
    navigate('/')
  }

  return (
    <Panel
      className="self-start xl:sticky xl:top-20"
      title="Request details"
      actions={
        <button type="button" onClick={onClose} className="rounded-md p-1.5 text-muted hover:bg-raised hover:text-ink" aria-label="Close details">
          <X size={16} />
        </button>
      }
    >
      {detail.error ? (
        <ErrorNotice error={detail.error} onRetry={detail.reload} />
      ) : !detail.data || detail.loading ? (
        <Loading />
      ) : (
        <div className="space-y-5">
          <div>
            <div className="flex flex-wrap items-center gap-3">
              <StatusBadge status={detail.data.status} />
              <span className="text-sm text-muted">{formatTimestamp(detail.data.created_at)}</span>
            </div>
            <p className="mt-2 text-lg text-ink">{detail.data.question}</p>
            {detail.data.answer && <p className="mt-2 text-muted">{detail.data.answer}</p>}
            {detail.data.error_message && (
              <p className={`mt-2 ${detail.data.status === 'unanswerable' ? 'text-sky' : detail.data.status === 'rejected' ? 'text-warn' : 'text-bad'}`}>
                {detail.data.error_message}
              </p>
            )}
          </div>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm sm:grid-cols-3">
            <Item label="Total time" value={formatMs(detail.data.total_ms)} />
            <Item label="LLM time" value={formatMs(detail.data.generation_ms)} />
            <Item label="Database time" value={formatMs(detail.data.db_ms)} />
            <Item label="Rows" value={detail.data.row_count === null ? '—' : detail.data.row_count.toLocaleString()} />
            <Item label="Retries" value={String(detail.data.retry_count)} />
            <Item label="LLM calls" value={String(detail.data.llm_calls)} />
            <Item label="Tokens in / out" value={detail.data.input_tokens === null ? 'Unavailable' : `${formatTokens(detail.data.input_tokens)} / ${formatTokens(detail.data.output_tokens)}`} />
            <Item label="Estimated cost" value={formatCost(detail.data.estimated_cost_usd)} />
            <Item label="Model" value={`${detail.data.provider} / ${detail.data.model}`} />
          </dl>
          {detail.data.status === 'success' && detail.data.final_sql && <SqlBlock sql={detail.data.final_sql} caption="Executed SQL" />}
          {!detail.data.cache_hit && detail.data.attempts.length > 0 && (
            <div>
              <h3 className="mb-3 text-sm font-medium text-muted">Attempts</h3>
              <AttemptList attempts={detail.data.attempts} />
            </div>
          )}
          <div className="flex flex-wrap items-center gap-3 border-t border-line pt-4">
            <Button variant="primary" icon={<Play size={14} />} onClick={() => rerun(detail.data!)} disabled={session.pending !== null}>
              Run again
            </Button>
            <span className="text-xs text-faint">Result rows aren’t stored in history; running again fetches them.</span>
          </div>
        </div>
      )}
    </Panel>
  )
}

function Item({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-faint">{label}</dt>
      <dd className="truncate tabular-nums text-ink" title={value}>
        {value}
      </dd>
    </div>
  )
}
