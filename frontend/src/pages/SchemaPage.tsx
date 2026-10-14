import { ChevronRight, KeyRound, Link2, RefreshCw } from 'lucide-react'
import { useState } from 'react'
import { Button } from '../components/Button'
import { PageHeader } from '../components/PageHeader'
import { Panel } from '../components/Panel'
import { ErrorNotice, Loading } from '../components/States'
import { useAsync } from '../hooks/useAsync'
import { api } from '../services/api'
import type { SchemaResponse, TableSchema } from '../types/api'

export function SchemaPage() {
  const schema = useAsync(() => api.schema(), [])
  const [open, setOpen] = useState<Set<string>>(new Set(['orders']))

  function toggle(name: string) {
    setOpen((prev) => {
      const next = new Set(prev)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })
  }

  const data = schema.data

  return (
    <>
      <PageHeader
        title="Database schema"
        description="The tables QueryPilot is allowed to query, read live from the database. This structure, not the data, is what the model sees."
        actions={
          <Button size="sm" icon={<RefreshCw size={14} />} onClick={schema.reload} disabled={schema.loading}>
            Refresh
          </Button>
        }
      />
      {schema.error ? (
        <ErrorNotice error={schema.error} onRetry={schema.reload} />
      ) : !data ? (
        <Loading />
      ) : (
        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_20rem]">
          <div className="space-y-3">
            {data.tables.map((t) => (
              <TableCard key={t.name} table={t} open={open.has(t.name)} onToggle={() => toggle(t.name)} />
            ))}
          </div>
          <aside className="space-y-5">
            <Relationships data={data} />
            <Panel title="Business rules" description="Sent to the model with the schema.">
              <ul className="space-y-2 text-sm text-muted">
                {data.business_rules.map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
            </Panel>
            <Panel title="About this database">
              <dl className="space-y-2 text-sm">
                <Row label="Engine" value={data.database_type} />
                <Row label="Newest data" value={data.data_reference_date ?? '—'} />
                <Row label="Schema version" value={data.version} mono />
              </dl>
            </Panel>
          </aside>
        </div>
      )}
    </>
  )
}

function TableCard({ table, open, onToggle }: { table: TableSchema; open: boolean; onToggle: () => void }) {
  const fks = new Map(table.foreign_keys.map((f) => [f.column, f]))
  return (
    <section className="rounded-xl border border-line bg-panel">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-raised/40 sm:px-5"
      >
        <ChevronRight size={16} className={`shrink-0 text-muted transition-transform ${open ? 'rotate-90' : ''}`} aria-hidden />
        <span className="font-mono text-[0.95rem] text-ink">{table.name}</span>
        <span className="text-sm text-muted">
          {table.columns.length} columns, {table.row_count.toLocaleString()} rows
        </span>
      </button>
      {open && (
        <div className="border-t border-line px-4 pt-3 pb-4 sm:px-5">
          {table.note && <p className="mb-3 text-sm text-muted">{table.note}</p>}
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-faint">
                <tr>
                  <th scope="col" className="py-1.5 pr-4 font-normal">Column</th>
                  <th scope="col" className="py-1.5 pr-4 font-normal">Type</th>
                  <th scope="col" className="py-1.5 pr-4 font-normal">Key</th>
                  <th scope="col" className="py-1.5 font-normal">Notes</th>
                </tr>
              </thead>
              <tbody>
                {table.columns.map((c) => {
                  const fk = fks.get(c.name)
                  return (
                    <tr key={c.name} className="border-t border-line/60 align-top">
                      <td className="py-2 pr-4 font-mono whitespace-nowrap text-ink">{c.name}</td>
                      <td className="py-2 pr-4 font-mono text-xs whitespace-nowrap text-sky">
                        {c.type}
                        {!c.nullable && !c.primary_key && <span className="ml-1 text-faint">not null</span>}
                      </td>
                      <td className="py-2 pr-4 whitespace-nowrap">
                        {c.primary_key && (
                          <span className="inline-flex items-center gap-1 text-amber">
                            <KeyRound size={13} aria-hidden /> Primary
                          </span>
                        )}
                        {fk && (
                          <span className="inline-flex items-center gap-1 text-teal">
                            <Link2 size={13} aria-hidden /> {fk.references_table}.{fk.references_column}
                          </span>
                        )}
                      </td>
                      <td className="py-2 text-muted">
                        {c.note}
                        {c.sample_values && (
                          <span className="block text-xs text-faint">Values: {c.sample_values.join(', ')}</span>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  )
}

function Relationships({ data }: { data: SchemaResponse }) {
  return (
    <Panel title="Relationships" description="Foreign keys. Each arrow is many-to-one.">
      <ul className="space-y-3">
        {data.relationships.map((r) => (
          <li key={`${r.from_table}.${r.from_column}`} className="text-sm">
            <div className="font-mono text-ink">
              {r.from_table}
              <span className="text-faint">.{r.from_column}</span>
            </div>
            <div className="flex items-center gap-2 pl-2 font-mono text-teal">
              <span aria-hidden>↳</span>
              {r.to_table}
              <span className="text-faint">.{r.to_column}</span>
            </div>
          </li>
        ))}
      </ul>
    </Panel>
  )
}

function Row({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="text-faint">{label}</dt>
      <dd className={`text-ink ${mono ? 'font-mono text-xs' : ''}`}>{value}</dd>
    </div>
  )
}
