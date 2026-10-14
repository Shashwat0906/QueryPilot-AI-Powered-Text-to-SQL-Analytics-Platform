import { useQuerySession } from '../hooks/useQuerySession'

/** Switch which query from this session the page is showing. */
export function SessionPicker() {
  const { recent, current, select } = useQuerySession()
  if (recent.length < 2) return null
  return (
    <label className="flex items-center gap-2 text-sm text-muted">
      Showing
      <select
        value={current?.request_id ?? ''}
        onChange={(e) => select(e.target.value)}
        className="h-9 max-w-[16rem] truncate rounded-lg border border-line-strong bg-raised px-2 text-ink sm:max-w-xs"
      >
        {recent.map((r) => (
          <option key={r.request_id} value={r.request_id}>
            {r.question}
          </option>
        ))}
      </select>
    </label>
  )
}
