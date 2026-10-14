import type { CellValue, ColumnMeta } from '../types/api'

const MONEY_HINT = /(revenue|price|cost|amount|value|sales|total|fee|spend|aov)/i

export function humanize(name: string): string {
  const s = name.replace(/_/g, ' ')
  return s.charAt(0).toUpperCase() + s.slice(1)
}

export function isMoneyColumn(name: string): boolean {
  return MONEY_HINT.test(name) && !/(count|quantity|units|orders|id)$/i.test(name)
}

export function formatNumber(value: number, maxFraction = 2): string {
  return value.toLocaleString(undefined, { maximumFractionDigits: maxFraction })
}

export function formatCell(value: CellValue, column: ColumnMeta): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'number') {
    if (/_id$|^id$/i.test(column.name)) return String(value)
    if (isMoneyColumn(column.name) && !Number.isInteger(value)) {
      return value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    }
    return formatNumber(value)
  }
  if (column.type === 'date' && typeof value === 'string') return formatDateValue(value)
  return String(value)
}

export function formatDateValue(value: string): string {
  if (/^\d{4}-\d{2}$/.test(value)) {
    const [y, m] = value.split('-').map(Number)
    return new Date(y, m - 1, 1).toLocaleDateString(undefined, { year: 'numeric', month: 'short' })
  }
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    const [y, m, d] = value.split('-').map(Number)
    return new Date(y, m - 1, d).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
  }
  return value
}

export function formatMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return '—'
  if (ms < 1) return '<1 ms'
  if (ms < 1000) return `${Math.round(ms)} ms`
  return `${(ms / 1000).toFixed(2)} s`
}

export function formatCost(usd: number | null | undefined): string {
  if (usd === null || usd === undefined) return 'Unavailable'
  if (usd === 0) return '$0.00'
  if (usd < 0.01) return `$${usd.toFixed(4)}`
  return `$${usd.toFixed(2)}`
}

export function formatPercent(rate: number | null | undefined): string {
  if (rate === null || rate === undefined) return '—'
  return `${(rate * 100).toFixed(rate === 1 || rate === 0 ? 0 : 1)}%`
}

export function formatTimestamp(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function formatTokens(n: number | null | undefined): string {
  if (n === null || n === undefined) return 'Unavailable'
  return n.toLocaleString()
}
