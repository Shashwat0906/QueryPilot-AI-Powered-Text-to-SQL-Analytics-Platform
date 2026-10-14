import type { Attempt } from '../types/api'
import { formatMs } from '../utils/format'
import { SqlBlock } from './SqlBlock'

const STATUS_TEXT: Record<string, { label: string; className: string }> = {
  success: { label: 'Executed successfully', className: 'text-ok' },
  validation_error: { label: 'Failed validation', className: 'text-bad' },
  execution_error: { label: 'Database error', className: 'text-bad' },
  security_violation: { label: 'Blocked by safety rules', className: 'text-warn' },
  result_check_failed: { label: 'Ran, but didn’t match the question', className: 'text-bad' },
  parse_error: { label: 'Malformed model reply', className: 'text-bad' },
  unanswerable: { label: 'Model said it can’t be answered', className: 'text-sky' },
  timeout: { label: 'Timed out', className: 'text-bad' },
  provider_error: { label: 'LLM provider error', className: 'text-bad' },
}

/** Every SQL attempt in order: the original generation and each correction. */
export function AttemptList({ attempts }: { attempts: Attempt[] }) {
  return (
    <ol className="space-y-5">
      {attempts.map((a) => {
        const s = STATUS_TEXT[a.status] ?? { label: a.status, className: 'text-muted' }
        return (
          <li key={a.number} className="relative border-l-2 border-line pl-4">
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <h3 className="font-medium text-ink">
                Attempt {a.number}: {a.kind === 'generation' ? 'initial SQL' : 'correction'}
              </h3>
              <span className={`text-sm ${s.className}`}>{s.label}</span>
              <span className="text-xs text-faint">
                LLM {formatMs(a.llm_latency_ms)}
                {a.db_latency_ms !== null && `, database ${formatMs(a.db_latency_ms)}`}
              </span>
            </div>
            {a.error_message && (
              <p className="mt-1 text-sm text-muted">
                {a.error_message}
                {a.error_code && <span className="ml-2 font-mono text-xs text-faint">{a.error_code}</span>}
              </p>
            )}
            {a.sql && (
              <div className="mt-3">
                <SqlBlock sql={a.sql} caption={a.status === 'success' ? 'As written by the model' : 'Rejected SQL'} dimmed={a.status !== 'success'} />
              </div>
            )}
          </li>
        )
      })}
    </ol>
  )
}
