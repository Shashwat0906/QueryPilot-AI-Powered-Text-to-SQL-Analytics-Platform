import { CheckCircle2, CircleHelp, ShieldAlert, XCircle } from 'lucide-react'
import type { QueryStatus } from '../types/api'

const MAP: Record<QueryStatus, { label: string; className: string; Icon: typeof CheckCircle2 }> = {
  success: { label: 'Succeeded', className: 'text-ok bg-ok/10 border-ok/25', Icon: CheckCircle2 },
  failed: { label: 'Failed', className: 'text-bad bg-bad/10 border-bad/25', Icon: XCircle },
  rejected: { label: 'Blocked', className: 'text-warn bg-warn/10 border-warn/25', Icon: ShieldAlert },
  unanswerable: { label: 'Not answerable', className: 'text-sky bg-sky/10 border-sky/25', Icon: CircleHelp },
}

export function StatusBadge({ status }: { status: QueryStatus }) {
  const { label, className, Icon } = MAP[status] ?? MAP.failed
  return (
    <span className={`inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-xs font-medium ${className}`}>
      <Icon size={13} aria-hidden />
      {label}
    </span>
  )
}
