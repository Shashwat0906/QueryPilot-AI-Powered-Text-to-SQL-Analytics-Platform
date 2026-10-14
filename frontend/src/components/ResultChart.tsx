import { useMemo, useState } from 'react'
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
import type { CellValue, ColumnMeta } from '../types/api'
import { inferChart, SERIES_COLORS, toChartData, type ChartKind } from '../utils/chart'
import { formatDateValue, formatNumber, humanize } from '../utils/format'

interface ResultChartProps {
  columns: ColumnMeta[]
  rows: CellValue[][]
  height?: number
  showControls?: boolean
}

const AXIS = { stroke: '#5d6f87', fontSize: 12, tickLine: false }

/** Charts the actual returned rows. If they don't chart well, renders nothing. */
export function ResultChart({ columns, rows, height = 280, showControls = false }: ResultChartProps) {
  const auto = useMemo(() => inferChart(columns, rows), [columns, rows])
  const [kind, setKind] = useState<ChartKind | null>(null)
  const [x, setX] = useState<string | null>(null)
  const [y, setY] = useState<string | null>(null)

  const data = useMemo(() => toChartData(columns, rows), [columns, rows])
  if (auto.kind === 'none') return null

  const activeKind = kind ?? auto.kind
  const activeX = x && columns.some((c) => c.name === x) ? x : auto.x!
  const measures = columns.filter((c) => c.type === 'number' && c.name !== activeX).map((c) => c.name)
  const activeY = y && measures.includes(y) ? [y] : auto.y.filter((m) => m !== activeX)
  const xIsDate = columns.find((c) => c.name === activeX)?.type === 'date'
  const tickX = (v: CellValue) => (xIsDate && typeof v === 'string' ? formatDateValue(v) : String(v).slice(0, 18))

  const common = {
    data,
    margin: { top: 8, right: 12, bottom: 4, left: 4 },
  }
  const series = activeY.map((name, i) => ({ name, color: SERIES_COLORS[i % SERIES_COLORS.length] }))

  return (
    <div>
      {showControls && (
        <div className="mb-3 flex flex-wrap items-center gap-3 text-sm">
          <Select label="Chart" value={activeKind} onChange={(v) => setKind(v as ChartKind)} options={['bar', 'line']} />
          <Select label="X axis" value={activeX} onChange={setX} options={columns.map((c) => c.name)} />
          <Select label="Y axis" value={activeY[0] ?? ''} onChange={setY} options={measures} />
        </div>
      )}
      <div style={{ height }} role="img" aria-label={`${activeKind} chart of ${activeY.map(humanize).join(', ')} by ${humanize(activeX)}`}>
        <ResponsiveContainer width="100%" height="100%">
          {activeKind === 'line' ? (
            <LineChart {...common}>
              <CartesianGrid stroke="#26384f" vertical={false} />
              <XAxis dataKey={activeX} tickFormatter={tickX} minTickGap={12} {...AXIS} />
              <YAxis tickFormatter={(v: number) => formatNumber(v, 0)} width={64} {...AXIS} axisLine={false} />
              <Tooltip content={<ChartTooltip labelFormatter={tickX} />} />
              {series.length > 1 && <Legend formatter={(v: string) => humanize(v)} />}
              {series.map((s) => (
                <Line key={s.name} type="monotone" dataKey={s.name} stroke={s.color} strokeWidth={2} dot={{ r: 3, fill: s.color }} />
              ))}
            </LineChart>
          ) : (
            <BarChart {...common}>
              <CartesianGrid stroke="#26384f" vertical={false} />
              <XAxis dataKey={activeX} tickFormatter={tickX} interval="preserveStartEnd" minTickGap={12} {...AXIS} />
              <YAxis tickFormatter={(v: number) => formatNumber(v, 0)} width={64} {...AXIS} axisLine={false} />
              <Tooltip cursor={{ fill: '#1c2b3e' }} content={<ChartTooltip labelFormatter={tickX} />} />
              {series.length > 1 && <Legend formatter={(v: string) => humanize(v)} />}
              {series.map((s) => (
                <Bar key={s.name} dataKey={s.name} fill={s.color} radius={[3, 3, 0, 0]} maxBarSize={48} />
              ))}
            </BarChart>
          )}
        </ResponsiveContainer>
      </div>
    </div>
  )
}

interface TooltipPayload {
  name?: string | number
  value?: unknown
  color?: string
}

function ChartTooltip({
  active,
  payload,
  label,
  labelFormatter,
}: {
  active?: boolean
  payload?: TooltipPayload[]
  label?: CellValue
  labelFormatter: (v: CellValue) => string
}) {
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-lg border border-line-strong bg-raised px-3 py-2 text-sm shadow-lg">
      <p className="mb-1 font-medium text-ink">{labelFormatter(label ?? '')}</p>
      {payload.map((p) => (
        <p key={String(p.name)} className="flex items-center gap-2 text-muted">
          <span className="h-2 w-2 rounded-full" style={{ background: p.color }} aria-hidden />
          {humanize(String(p.name))}: <span className="tabular-nums text-ink">{typeof p.value === 'number' ? formatNumber(p.value) : String(p.value)}</span>
        </p>
      ))}
    </div>
  )
}

function Select({ label, value, onChange, options }: { label: string; value: string; onChange: (v: string) => void; options: string[] }) {
  return (
    <label className="inline-flex items-center gap-2 text-muted">
      {label}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="h-8 rounded-md border border-line-strong bg-raised px-2 text-ink"
      >
        {options.map((o) => (
          <option key={o} value={o}>
            {humanize(o)}
          </option>
        ))}
      </select>
    </label>
  )
}
