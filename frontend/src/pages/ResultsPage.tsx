import { Download } from 'lucide-react'
import { Button } from '../components/Button'
import { NoActiveQuery } from '../components/NoActiveQuery'
import { PageHeader } from '../components/PageHeader'
import { Panel } from '../components/Panel'
import { ResultChart } from '../components/ResultChart'
import { ResultsTable } from '../components/ResultsTable'
import { SessionPicker } from '../components/SessionPicker'
import { useQuerySession } from '../hooks/useQuerySession'
import type { QueryResponse } from '../types/api'
import { inferChart } from '../utils/chart'

function downloadCsv(result: QueryResponse) {
  const escape = (v: unknown) => {
    const s = v === null || v === undefined ? '' : String(v)
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
  }
  const lines = [result.columns.map((c) => escape(c.name)).join(','), ...result.rows.map((r) => r.map(escape).join(','))]
  const url = URL.createObjectURL(new Blob([lines.join('\n')], { type: 'text/csv' }))
  const a = document.createElement('a')
  a.href = url
  a.download = `querypilot-${result.request_id.slice(0, 8)}.csv`
  a.click()
  URL.revokeObjectURL(url)
}

export function ResultsPage() {
  const { current } = useQuerySession()
  const chart = current ? inferChart(current.columns, current.rows) : null

  return (
    <>
      <PageHeader
        title="Results explorer"
        description="Rows exactly as the database returned them. Sort by any column or chart the numbers."
        actions={<SessionPicker />}
      />
      {!current ? (
        <NoActiveQuery what="results" />
      ) : current.status !== 'success' ? (
        <Panel title={current.question}>
          <p className="text-muted">This question didn’t produce results: {current.error?.message}</p>
        </Panel>
      ) : (
        <div className="space-y-5">
          {chart && chart.kind !== 'none' && (
            <Panel title="Chart" description="Pick the columns to plot. Only returned rows are used.">
              <ResultChart key={current.request_id} columns={current.columns} rows={current.rows} height={320} showControls />
            </Panel>
          )}
          <Panel
            title={current.question}
            description={
              <>
                {current.row_count.toLocaleString()} {current.row_count === 1 ? 'row' : 'rows'}, {current.columns.length}{' '}
                {current.columns.length === 1 ? 'column' : 'columns'}
                {current.truncated && `. Showing the first ${current.max_rows.toLocaleString()} (row limit).`}
                {chart?.kind === 'none' && current.row_count > 0 && ` No chart: ${chart.reason.toLowerCase()}`}
              </>
            }
            actions={
              current.row_count > 0 && (
                <Button size="sm" icon={<Download size={14} />} onClick={() => downloadCsv(current)}>
                  Download CSV
                </Button>
              )
            }
          >
            {current.row_count === 0 ? (
              <p className="text-muted">No matching records were found.</p>
            ) : (
              <ResultsTable columns={current.columns} rows={current.rows} maxHeight="36rem" />
            )}
          </Panel>
        </div>
      )}
    </>
  )
}
