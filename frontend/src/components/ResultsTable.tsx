import { ArrowDown, ArrowUp } from 'lucide-react'
import { useMemo, useState } from 'react'
import type { CellValue, ColumnMeta } from '../types/api'
import { formatCell, humanize } from '../utils/format'

interface ResultsTableProps {
  columns: ColumnMeta[]
  rows: CellValue[][]
  maxHeight?: string
}

/** Real query rows. Click a header to sort locally (display only). */
export function ResultsTable({ columns, rows, maxHeight = '28rem' }: ResultsTableProps) {
  const [sort, setSort] = useState<{ index: number; dir: 'asc' | 'desc' } | null>(null)

  const sorted = useMemo(() => {
    if (!sort) return rows
    const { index, dir } = sort
    return [...rows].sort((a, b) => {
      const x = a[index]
      const y = b[index]
      if (x === y) return 0
      if (x === null) return 1
      if (y === null) return -1
      const cmp = typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y))
      return dir === 'asc' ? cmp : -cmp
    })
  }, [rows, sort])

  function toggle(index: number) {
    setSort((s) => (s?.index !== index ? { index, dir: 'desc' } : s.dir === 'desc' ? { index, dir: 'asc' } : null))
  }

  return (
    <div className="overflow-auto rounded-lg border border-line" style={{ maxHeight }} tabIndex={0} aria-label="Query results">
      <table className="w-full border-collapse text-sm">
        <thead className="sticky top-0 z-10 bg-raised">
          <tr>
            <th scope="col" className="w-10 border-b border-line px-3 py-2 text-right text-xs font-normal text-faint">
              #
            </th>
            {columns.map((c, i) => {
              const numeric = c.type === 'number'
              const active = sort?.index === i
              return (
                <th
                  key={c.name}
                  scope="col"
                  aria-sort={active ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}
                  className={`border-b border-line px-3 py-2 font-medium whitespace-nowrap text-muted ${numeric ? 'text-right' : 'text-left'}`}
                >
                  <button
                    type="button"
                    onClick={() => toggle(i)}
                    className={`inline-flex items-center gap-1 hover:text-ink ${active ? 'text-ink' : ''}`}
                    title={`${c.name} (${c.type})`}
                  >
                    {humanize(c.name)}
                    {active && (sort.dir === 'asc' ? <ArrowUp size={12} /> : <ArrowDown size={12} />)}
                  </button>
                </th>
              )
            })}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row, ri) => (
            <tr key={ri} className="border-b border-line/60 last:border-0 hover:bg-raised/50">
              <td className="px-3 py-2 text-right text-xs tabular-nums text-faint">{ri + 1}</td>
              {row.map((cell, ci) => {
                const col = columns[ci]
                return (
                  <td
                    key={ci}
                    className={`px-3 py-2 whitespace-nowrap ${col.type === 'number' ? 'text-right tabular-nums' : ''} ${cell === null ? 'text-faint' : 'text-ink'}`}
                  >
                    {formatCell(cell, col)}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
