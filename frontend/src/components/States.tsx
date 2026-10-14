import { AlertTriangle, Loader2 } from 'lucide-react'
import type { ReactNode } from 'react'
import { ApiError } from '../services/api'
import { Button } from './Button'

export function EmptyState({ icon, title, children, action }: { icon?: ReactNode; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-start gap-3 rounded-xl border border-dashed border-line-strong px-6 py-10 sm:items-center sm:text-center">
      {icon && <div className="text-faint">{icon}</div>}
      <div>
        <p className="font-medium text-ink">{title}</p>
        {children && <div className="mt-1 max-w-md text-sm text-muted">{children}</div>}
      </div>
      {action}
    </div>
  )
}

export function ErrorNotice({ error, onRetry }: { error: Error; onRetry?: () => void }) {
  const requestId = error instanceof ApiError ? error.requestId : null
  return (
    <div role="alert" className="flex flex-wrap items-start gap-3 rounded-xl border border-bad/30 bg-bad/5 px-4 py-3">
      <AlertTriangle className="mt-0.5 shrink-0 text-bad" size={18} aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="font-medium text-ink">{error.message}</p>
        {requestId && <p className="mt-0.5 text-xs text-muted">Request ID {requestId}</p>}
      </div>
      {onRetry && (
        <Button size="sm" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  )
}

export function Loading({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-10 text-muted" role="status">
      <Loader2 className="animate-spin" size={18} aria-hidden />
      {label}
    </div>
  )
}

export function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`animate-pulse rounded-md bg-raised ${className}`} />
}
