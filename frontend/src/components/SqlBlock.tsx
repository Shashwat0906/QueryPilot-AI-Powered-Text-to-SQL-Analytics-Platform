import { useMemo } from 'react'
import { tokenizeSql } from '../utils/sqlHighlight'
import { CopyButton } from './CopyButton'

interface SqlBlockProps {
  sql: string
  caption?: string
  copyable?: boolean
  dimmed?: boolean
}

export function SqlBlock({ sql, caption, copyable = true, dimmed = false }: SqlBlockProps) {
  const lines = useMemo(() => sql.split('\n'), [sql])
  const tokens = useMemo(() => tokenizeSql(sql), [sql])

  return (
    <div className={`overflow-hidden rounded-lg border border-line bg-night ${dimmed ? 'opacity-80' : ''}`}>
      {(caption || copyable) && (
        <div className="flex items-center justify-between gap-2 border-b border-line px-3 py-1.5">
          <span className="text-xs text-muted">{caption ?? 'SQL'}</span>
          {copyable && <CopyButton text={sql} />}
        </div>
      )}
      <div className="flex overflow-x-auto text-[0.8125rem] leading-6">
        <div aria-hidden className="select-none border-r border-line px-3 py-3 text-right font-mono text-faint">
          {lines.map((_, i) => (
            <div key={i}>{i + 1}</div>
          ))}
        </div>
        <pre className="flex-1 px-4 py-3 font-mono text-ink">
          <code>
            {tokens.map((t, i) =>
              t.kind === 'text' ? <span key={i}>{t.text}</span> : <span key={i} className={`sql-${t.kind}`}>{t.text}</span>,
            )}
          </code>
        </pre>
      </div>
    </div>
  )
}
