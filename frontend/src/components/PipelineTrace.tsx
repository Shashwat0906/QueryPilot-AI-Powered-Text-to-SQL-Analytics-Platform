import type { Attempt, QueryResponse } from '../types/api'
import { formatCost, formatMs, formatTokens } from '../utils/format'

type StageState = 'done' | 'failed' | 'blocked' | 'info'

interface Stage {
  label: string
  detail?: string
  state: StageState
}

const DOT: Record<StageState, string> = {
  done: 'bg-amber border-amber',
  failed: 'bg-bad border-bad',
  blocked: 'bg-warn border-warn',
  info: 'bg-sky border-sky',
}

function stagesFor(attempt: Attempt, isLast: boolean, result: QueryResponse): Stage[] {
  const verb = attempt.kind === 'generation' ? 'Generate' : 'Correct'
  const gen: Stage = { label: verb, detail: formatMs(attempt.llm_latency_ms), state: 'done' }
  const err = attempt.error_message ?? undefined
  switch (attempt.status) {
    case 'parse_error':
    case 'provider_error':
      return [{ ...gen, state: 'failed', detail: err }]
    case 'unanswerable':
      return [gen, { label: 'Not answerable', detail: err, state: 'info' }]
    case 'validation_error':
      return [gen, { label: 'Validate', detail: err, state: 'failed' }]
    case 'security_violation':
      return attempt.error_code === 'operation_not_permitted'
        ? [gen, { label: 'Validate', state: 'done' }, { label: 'Execute', detail: err, state: 'blocked' }]
        : [gen, { label: 'Validate', detail: err, state: 'blocked' }]
    case 'result_check_failed':
      return [
        gen,
        { label: 'Validate', state: 'done' },
        { label: 'Execute', detail: formatMs(attempt.db_latency_ms), state: 'done' },
        { label: 'Check result', detail: err, state: 'failed' },
      ]
    case 'execution_error':
    case 'timeout':
      return [gen, { label: 'Validate', state: 'done' }, { label: 'Execute', detail: err, state: 'failed' }]
    case 'success': {
      const stages: Stage[] = [
        gen,
        { label: 'Validate', state: 'done' },
        { label: 'Execute', detail: `${formatMs(attempt.db_latency_ms)}, ${result.row_count} ${result.row_count === 1 ? 'row' : 'rows'}`, state: 'done' },
      ]
      if (isLast && result.answer) stages.push({ label: 'Answer', detail: formatMs(result.timings.answer_ms), state: 'done' })
      return stages
    }
    default:
      return [gen]
  }
}

export function PipelineTrace({ result }: { result: QueryResponse }) {
  const { timings, usage } = result

  return (
    <div className="grid gap-5 lg:grid-cols-[1fr_auto]">
      <ol className="space-y-3" aria-label="How this answer was produced">
        {result.cache.hit ? (
          <li className="trace-step flex items-center gap-3 text-sm">
            <span className="h-2.5 w-2.5 rounded-full border-2 border-teal bg-teal" aria-hidden />
            <span className="font-medium text-ink">Served from cache</span>
            <span className="text-muted">same question, schema and model ran recently - no LLM call made</span>
          </li>
        ) : (
          result.attempts.map((attempt, ai) => {
            const stages = stagesFor(attempt, ai === result.attempts.length - 1, result)
            return (
              <li key={attempt.number} className="flex flex-col gap-1.5 sm:flex-row sm:items-start sm:gap-4">
                <span className="w-20 shrink-0 pt-px text-xs text-faint">Attempt {attempt.number}</span>
                <ol className="flex min-w-0 flex-1 flex-col gap-1.5 sm:flex-row sm:flex-wrap sm:items-start sm:gap-0">
                  {stages.map((stage, si) => (
                    <li
                      key={stage.label}
                      className="trace-step flex min-w-0 items-start gap-2 sm:items-center"
                      style={{ animationDelay: `${(ai * stages.length + si) * 70}ms` }}
                    >
                      {si > 0 && <span className="hidden h-px w-6 bg-line-strong sm:block" aria-hidden />}
                      <span className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full border-2 sm:mt-0 ${DOT[stage.state]}`} aria-hidden />
                      <span className="min-w-0 text-sm">
                        <span className={stage.state === 'done' ? 'text-ink' : 'font-medium text-ink'}>{stage.label}</span>
                        {stage.detail && (
                          <span
                            className={`ml-1.5 ${stage.state === 'done' ? 'text-muted' : stage.state === 'info' ? 'text-sky' : stage.state === 'blocked' ? 'text-warn' : 'text-bad'}`}
                          >
                            {stage.detail}
                          </span>
                        )}
                        <span className="sr-only"> ({stage.state})</span>
                      </span>
                    </li>
                  ))}
                </ol>
              </li>
            )
          })
        )}
      </ol>

      <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-4 lg:grid-cols-2 lg:border-l lg:border-line lg:pl-5">
        <Metric label="Total time" value={formatMs(timings.total_ms)} />
        <Metric label="Retries" value={String(result.retry_count)} />
        <Metric
          label="Tokens in / out"
          value={usage.input_tokens === null ? 'Unavailable' : `${formatTokens(usage.input_tokens)} / ${formatTokens(usage.output_tokens)}`}
        />
        <Metric label="Estimated cost" value={formatCost(usage.estimated_cost_usd)} title={usage.cost_note} />
      </dl>
    </div>
  )
}

function Metric({ label, value, title }: { label: string; value: string; title?: string }) {
  return (
    <div title={title}>
      <dt className="text-xs text-faint">{label}</dt>
      <dd className="font-medium tabular-nums text-ink">{value}</dd>
    </div>
  )
}
