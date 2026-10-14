import { AlertTriangle, ArrowUpRight, Info, Loader2, Plus, Sparkles } from 'lucide-react'
import { lazy, Suspense, useRef, type FormEvent, type KeyboardEvent } from 'react'
import { Link } from 'react-router-dom'
import { Button } from '../components/Button'
import { PageHeader } from '../components/PageHeader'
import { Panel } from '../components/Panel'
import { PipelineTrace } from '../components/PipelineTrace'
import { ResultsTable } from '../components/ResultsTable'
import { SqlBlock } from '../components/SqlBlock'
import { ErrorNotice, Skeleton } from '../components/States'

// Charting library is only downloaded once a chartable result appears.
const ResultChart = lazy(() => import('../components/ResultChart').then((m) => ({ default: m.ResultChart })))
import { StatusBadge } from '../components/StatusBadge'
import { useAsync } from '../hooks/useAsync'
import { useQuerySession } from '../hooks/useQuerySession'
import { api } from '../services/api'
import type { QueryResponse } from '../types/api'
import { inferChart } from '../utils/chart'
import { formatTimestamp } from '../utils/format'

const EXAMPLES = [
  'Show the top five products by revenue.',
  'What is our total revenue?',
  'Which customers placed the most orders?',
  'What was our monthly revenue over the last six months?',
  'Which product categories perform best?',
  'What is the average order value?',
  'Which products have never been ordered?',
]

export function WorkspacePage() {
  const session = useQuerySession()
  const config = useAsync(() => api.config(), [])
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const skipCacheRef = useRef<HTMLInputElement>(null)
  const maxLength = config.data?.max_question_length ?? 500
  const busy = session.pending !== null

  function submit(question: string) {
    const q = question.trim()
    if (q.length < 3 || busy) return
    session.setDraft(q)
    void session.run(q, !skipCacheRef.current?.checked)
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    submit(session.draft)
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit(session.draft)
    }
  }

  function newQuestion() {
    session.reset()
    inputRef.current?.focus()
  }

  return (
    <>
      <PageHeader
        title="Ask your data"
        description="Your question becomes one read-only SQL query. QueryPilot checks it, runs it on the sales database, and answers from the rows it gets back."
        actions={
          session.current && (
            <Button icon={<Plus size={16} />} onClick={newQuestion}>
              New question
            </Button>
          )
        }
      />

      {config.data?.is_mock_provider && (
        <div className="mb-5 flex gap-3 rounded-xl border border-warn/30 bg-warn/5 px-4 py-3 text-sm">
          <Info size={18} className="mt-0.5 shrink-0 text-warn" aria-hidden />
          <p className="text-muted">
            <span className="font-medium text-ink">Offline mock mode.</span> No LLM API key is configured, so only the example
            questions below work, using pre-written SQL. Results still come from the real database. Add{' '}
            <code className="font-mono text-ink">ANTHROPIC_API_KEY</code> to <code className="font-mono text-ink">backend/.env</code> to
            ask anything.
          </p>
        </div>
      )}

      <form onSubmit={onSubmit} className="rounded-xl border border-line-strong bg-panel focus-within:border-amber/60">
        <label htmlFor="question" className="sr-only">
          Your question
        </label>
        <textarea
          id="question"
          ref={inputRef}
          value={session.draft}
          onChange={(e) => session.setDraft(e.target.value)}
          onKeyDown={onKeyDown}
          maxLength={maxLength}
          rows={2}
          placeholder="Which product categories grew fastest this year?"
          className="block w-full resize-none bg-transparent px-4 pt-4 pb-2 text-lg text-ink placeholder:text-faint focus:outline-none sm:text-xl"
          autoFocus
        />
        <div className="flex flex-wrap items-center justify-between gap-3 px-4 pb-3">
          <div className="flex items-center gap-4 text-xs text-faint">
            <span>Enter to run, Shift+Enter for a new line</span>
            <label className="inline-flex cursor-pointer items-center gap-1.5 text-muted">
              <input ref={skipCacheRef} type="checkbox" className="accent-amber" />
              Skip cache
            </label>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-xs tabular-nums text-faint">
              {session.draft.length}/{maxLength}
            </span>
            <Button
              type="submit"
              variant="primary"
              disabled={busy || session.draft.trim().length < 3}
              icon={busy ? <Loader2 size={16} className="animate-spin" /> : <Sparkles size={16} />}
            >
              {busy ? 'Running…' : 'Run query'}
            </Button>
          </div>
        </div>
      </form>

      <div className="mt-3 flex flex-wrap gap-2" aria-label="Example questions">
        {EXAMPLES.map((q) => (
          <button
            key={q}
            type="button"
            disabled={busy}
            onClick={() => submit(q)}
            className="rounded-full border border-line px-3 py-1 text-sm text-muted transition-colors hover:border-amber/50 hover:text-ink disabled:opacity-50"
          >
            {q}
          </button>
        ))}
      </div>

      <div className="mt-8 space-y-5" aria-live="polite">
        {session.pending && <PendingState question={session.pending} />}
        {!session.pending && session.error && <ErrorNotice error={session.error} onRetry={() => submit(session.draft)} />}
        {!session.pending && session.current && <ResultView result={session.current} />}
      </div>

      {session.recent.length > 1 && (
        <div className="mt-10">
          <h2 className="mb-2 text-sm font-medium text-muted">Earlier in this session</h2>
          <ul className="divide-y divide-line rounded-xl border border-line">
            {session.recent
              .filter((r) => r.request_id !== session.current?.request_id)
              .slice(0, 6)
              .map((r) => (
                <li key={r.request_id}>
                  <button
                    type="button"
                    onClick={() => session.select(r.request_id)}
                    className="flex w-full items-center justify-between gap-3 px-4 py-2.5 text-left text-sm hover:bg-panel"
                  >
                    <span className="truncate text-ink">{r.question}</span>
                    <StatusBadge status={r.status} />
                  </button>
                </li>
              ))}
          </ul>
        </div>
      )}
    </>
  )
}

function PendingState({ question }: { question: string }) {
  return (
    <Panel>
      <p className="text-sm text-muted">{question}</p>
      <div className="mt-4 flex items-center gap-2 text-ink" role="status">
        <Loader2 size={18} className="animate-spin text-amber" aria-hidden />
        Writing SQL, validating it and running it…
      </div>
      <div className="mt-5 space-y-2">
        <Skeleton className="h-4 w-3/4" />
        <Skeleton className="h-4 w-1/2" />
      </div>
    </Panel>
  )
}

const FAILURE_TITLE: Record<string, string> = {
  failed: 'QueryPilot could not answer this question',
  rejected: 'The generated query was blocked',
  unanswerable: 'This question can’t be answered from the available data',
}

function ResultView({ result }: { result: QueryResponse }) {
  const ok = result.status === 'success'
  const lastSql = result.sql ?? [...result.attempts].reverse().find((a) => a.sql)?.sql ?? null

  return (
    <>
      <Panel bodyClassName="p-5 sm:p-6">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted">
          <StatusBadge status={result.status} />
          <span>{formatTimestamp(result.created_at)}</span>
          {result.cache.hit && <span className="text-teal">From cache</span>}
          {result.is_mock_provider && <span className="text-warn">Mock SQL</span>}
        </div>
        <p className="mt-3 text-muted">{result.question}</p>
        {ok ? (
          <>
            <p className="mt-2 max-w-3xl text-xl leading-relaxed text-ink sm:text-[1.375rem]">{result.answer}</p>
            {result.warnings.length > 0 && (
              <ul className="mt-3 space-y-1 text-sm text-warn">
                {result.warnings.map((w) => (
                  <li key={w} className="flex gap-2">
                    <AlertTriangle size={15} className="mt-0.5 shrink-0" aria-hidden />
                    {w}
                  </li>
                ))}
              </ul>
            )}
          </>
        ) : (
          <div className="mt-2 max-w-3xl">
            <p className="text-xl text-ink">{FAILURE_TITLE[result.status]}</p>
            <p className={`mt-1.5 ${result.status === 'rejected' ? 'text-warn' : result.status === 'unanswerable' ? 'text-sky' : 'text-bad'}`}>
              {result.error?.message}
            </p>
            {result.status === 'rejected' && (
              <p className="mt-2 text-sm text-muted">Only read-only SELECT queries on approved tables can run. Nothing was executed against the database.</p>
            )}
          </div>
        )}
      </Panel>

      <Panel title="How this answer was produced" description={`${result.provider === 'anthropic' ? 'Claude' : result.provider} (${result.model})`}>
        <PipelineTrace result={result} />
      </Panel>

      {ok && result.row_count > 0 && <ChartPanel result={result} />}

      {ok && (
        <Panel
          title="Results"
          description={
            result.truncated
              ? `First ${result.row_count.toLocaleString()} rows (row limit reached)`
              : `${result.row_count.toLocaleString()} ${result.row_count === 1 ? 'row' : 'rows'}`
          }
          actions={
            <Link to="/results" className="inline-flex items-center gap-1 text-sm text-muted hover:text-ink">
              Explore <ArrowUpRight size={14} />
            </Link>
          }
        >
          {result.row_count === 0 ? (
            <p className="text-muted">No matching records were found.</p>
          ) : (
            <ResultsTable columns={result.columns} rows={result.rows} maxHeight="22rem" />
          )}
        </Panel>
      )}

      {lastSql && (
        <Panel
          title={ok ? 'Executed SQL' : 'Last generated SQL'}
          actions={
            <Link to="/sql" className="inline-flex items-center gap-1 text-sm text-muted hover:text-ink">
              All attempts <ArrowUpRight size={14} />
            </Link>
          }
        >
          {result.explanation && <p className="mb-3 max-w-3xl text-muted">{result.explanation}</p>}
          <SqlBlock sql={lastSql} caption={ok ? 'Validated and executed' : 'Not executed'} dimmed={!ok} />
          {result.assumptions.length > 0 && (
            <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-muted">
              {result.assumptions.map((a) => (
                <li key={a}>{a}</li>
              ))}
            </ul>
          )}
        </Panel>
      )}
    </>
  )
}

function ChartPanel({ result }: { result: QueryResponse }) {
  // Only chart results with a label/date column and a numeric measure.
  if (inferChart(result.columns, result.rows).kind === 'none') return null
  return (
    <Panel title="Chart">
      <Suspense fallback={<Skeleton className="h-[280px] w-full" />}>
        <ResultChart columns={result.columns} rows={result.rows} />
      </Suspense>
    </Panel>
  )
}
