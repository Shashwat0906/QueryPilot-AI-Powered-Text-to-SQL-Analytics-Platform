import { useCallback, useMemo, useState, type ReactNode } from 'react'
import { QuerySessionContext, type QuerySession } from '../hooks/useQuerySession'
import { api } from '../services/api'
import type { QueryResponse } from '../types/api'

export function QuerySessionProvider({ children }: { children: ReactNode }) {
  const [recent, setRecent] = useState<QueryResponse[]>([])
  const [currentId, setCurrentId] = useState<string | null>(null)
  const [pending, setPending] = useState<string | null>(null)
  const [error, setError] = useState<Error | null>(null)
  const [draft, setDraft] = useState('')

  const run = useCallback(async (question: string, useCache = true) => {
    setPending(question)
    setError(null)
    try {
      const result = await api.query(question, useCache)
      setRecent((prev) => [result, ...prev].slice(0, 20))
      setCurrentId(result.request_id)
    } catch (e) {
      setError(e instanceof Error ? e : new Error(String(e)))
    } finally {
      setPending(null)
    }
  }, [])

  const reset = useCallback(() => {
    setCurrentId(null)
    setError(null)
    setDraft('')
  }, [])

  const value = useMemo<QuerySession>(
    () => ({
      current: recent.find((r) => r.request_id === currentId) ?? null,
      recent,
      pending,
      error,
      draft,
      setDraft,
      run,
      select: setCurrentId,
      reset,
    }),
    [recent, currentId, pending, error, draft, run, reset],
  )

  return <QuerySessionContext.Provider value={value}>{children}</QuerySessionContext.Provider>
}
