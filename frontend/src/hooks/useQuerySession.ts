import { createContext, useContext } from 'react'
import type { QueryResponse } from '../types/api'

export interface QuerySession {
  /** The result currently shown in Workspace, SQL viewer and Results. */
  current: QueryResponse | null
  /** Results from this browser session, newest first (for quick switching). */
  recent: QueryResponse[]
  pending: string | null
  error: Error | null
  draft: string
  setDraft: (q: string) => void
  run: (question: string, useCache?: boolean) => Promise<void>
  select: (requestId: string) => void
  reset: () => void
}

export const QuerySessionContext = createContext<QuerySession | null>(null)

export function useQuerySession(): QuerySession {
  const ctx = useContext(QuerySessionContext)
  if (!ctx) throw new Error('useQuerySession must be used inside <QuerySessionProvider>')
  return ctx
}
