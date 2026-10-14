import { useCallback, useEffect, useEffectEvent, useState } from 'react'

interface State<T> {
  key: string | null // which request these results belong to
  data: T | null
  error: Error | null
}

/**
 * Load data from the API. Re-runs when `deps` change or `reload()` is called.
 * `loading` is derived (results for the current key haven't arrived yet), and
 * results for an outdated request are ignored.
 */
export function useAsync<T>(loader: () => Promise<T>, deps: readonly unknown[]) {
  const [nonce, setNonce] = useState(0)
  const [state, setState] = useState<State<T>>({ key: null, data: null, error: null })
  const key = JSON.stringify([deps, nonce])
  const load = useEffectEvent(loader)

  useEffect(() => {
    let active = true
    load().then(
      (data) => active && setState({ key, data, error: null }),
      (e: unknown) => active && setState((s) => ({ key, data: s.data, error: e instanceof Error ? e : new Error(String(e)) })),
    )
    return () => {
      active = false
    }
  }, [key])

  const reload = useCallback(() => setNonce((n) => n + 1), [])

  return {
    data: state.data,
    error: state.key === key ? state.error : null,
    loading: state.key !== key,
    reload,
  }
}
