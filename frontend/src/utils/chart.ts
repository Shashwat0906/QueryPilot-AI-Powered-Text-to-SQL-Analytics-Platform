import type { CellValue, ColumnMeta } from '../types/api'

export type ChartKind = 'bar' | 'line' | 'none'

export interface ChartSpec {
  kind: ChartKind
  x: string | null
  y: string[]
  reason: string
}

const MAX_CHART_ROWS = 60

/**
 * Decide whether the ACTUAL result can be charted and how.
 *  - a date-like column + numeric column(s)        -> line chart over time
 *  - a text column + numeric column(s), <= 60 rows -> bar chart
 *  - a single value, or no numeric column           -> no chart (a table is clearer)
 * Identifier columns (`*_id`) are never plotted as measures. Only the first
 * measure is plotted by default (different units on one axis mislead); the
 * Results explorer lets the user pick another.
 */
export function inferChart(columns: ColumnMeta[], rows: CellValue[][]): ChartSpec {
  if (rows.length < 2) return { kind: 'none', x: null, y: [], reason: 'A single row reads better as a number than a chart.' }
  if (rows.length > MAX_CHART_ROWS) return { kind: 'none', x: null, y: [], reason: `Too many rows (${rows.length}) for a readable chart.` }

  const measures = columns.filter((c) => c.type === 'number' && !/(_id|^id)$/i.test(c.name)).map((c) => c.name)
  if (measures.length === 0) return { kind: 'none', x: null, y: [], reason: 'No numeric column to plot.' }

  const dateCol = columns.find((c) => c.type === 'date')
  if (dateCol) return { kind: 'line', x: dateCol.name, y: measures.slice(0, 1), reason: 'Values over time.' }

  const labelCol = columns.find((c) => c.type === 'string')
  if (labelCol) return { kind: 'bar', x: labelCol.name, y: measures.slice(0, 1), reason: 'Values per category.' }

  return { kind: 'none', x: null, y: [], reason: 'No label column for the x-axis.' }
}

export function toChartData(columns: ColumnMeta[], rows: CellValue[][]): Record<string, CellValue>[] {
  return rows.map((row) => Object.fromEntries(columns.map((c, i) => [c.name, row[i]])))
}

export const SERIES_COLORS = ['#F2B544', '#4FC3B5', '#6EA8FE']
