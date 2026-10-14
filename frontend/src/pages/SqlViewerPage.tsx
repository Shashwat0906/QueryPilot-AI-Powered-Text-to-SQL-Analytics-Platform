import { AttemptList } from '../components/AttemptList'
import { NoActiveQuery } from '../components/NoActiveQuery'
import { PageHeader } from '../components/PageHeader'
import { Panel } from '../components/Panel'
import { SessionPicker } from '../components/SessionPicker'
import { SqlBlock } from '../components/SqlBlock'
import { StatusBadge } from '../components/StatusBadge'
import { useQuerySession } from '../hooks/useQuerySession'

export function SqlViewerPage() {
  const { current } = useQuerySession()

  return (
    <>
      <PageHeader
        title="SQL viewer"
        description="The exact query QueryPilot ran, and every attempt the model made on the way there."
        actions={<SessionPicker />}
      />
      {!current ? (
        <NoActiveQuery what="SQL" />
      ) : (
        <div className="space-y-5">
          <Panel
            title={current.question}
            description={current.cache.hit ? 'Served from cache - this SQL ran in an earlier request.' : undefined}
            actions={<StatusBadge status={current.status} />}
          >
            {current.sql ? (
              <>
                {current.explanation && <p className="mb-3 max-w-3xl text-muted">{current.explanation}</p>}
                <SqlBlock sql={current.sql} caption="Final query, as validated and executed" />
                <dl className="mt-4 grid gap-x-8 gap-y-3 text-sm sm:grid-cols-3">
                  <div>
                    <dt className="text-faint">Tables</dt>
                    <dd className="text-ink">{current.tables_used.join(', ') || '—'}</dd>
                  </div>
                  <div>
                    <dt className="text-faint">Rows returned</dt>
                    <dd className="tabular-nums text-ink">
                      {current.row_count.toLocaleString()}
                      {current.truncated && ' (row limit reached)'}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-faint">Attempts</dt>
                    <dd className="text-ink">
                      {current.attempts.length} ({current.retry_count} {current.retry_count === 1 ? 'correction' : 'corrections'})
                    </dd>
                  </div>
                </dl>
                {current.assumptions.length > 0 && (
                  <div className="mt-4">
                    <h3 className="text-sm text-faint">Assumptions the model made</h3>
                    <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-muted">
                      {current.assumptions.map((a) => (
                        <li key={a}>{a}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </>
            ) : (
              <p className="text-muted">
                No query was executed. <span className="text-ink">{current.error?.message}</span>
              </p>
            )}
          </Panel>

          <Panel
            title="Attempts"
            description="The model's own SQL for each try. The final query above is the validator's canonical version of the successful attempt."
          >
            <AttemptList attempts={current.attempts} />
          </Panel>
        </div>
      )}
    </>
  )
}
