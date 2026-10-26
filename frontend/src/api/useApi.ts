import { useCallback, useEffect, useState } from 'react'
import { api, ApiError } from './client'

export interface ApiState<T> {
  data: T | null
  error: ApiError | null
  loading: boolean
  reload: () => void
}

export function useApi<T>(path: string | null): ApiState<T> {
  const [state, setState] = useState<{ path: string | null; data: T | null; error: ApiError | null; loading: boolean }>({
    path: null, data: null, error: null, loading: path !== null,
  })
  const [version, setVersion] = useState(0)

  useEffect(() => {
    if (path === null) {
      setState({ path: null, data: null, error: null, loading: false })
      return
    }
    let cancelled = false
    setState({ path, data: null, error: null, loading: true })
    api.get<T>(path)
      .then((data) => { if (!cancelled) setState({ path, data, error: null, loading: false }) })
      .catch((e: ApiError) => {
        if (!cancelled) setState({ path, data: null, error: e, loading: false })
      })
    return () => { cancelled = true }
  }, [path, version])

  const reload = useCallback(() => setVersion((v) => v + 1), [])
  // A changed path can render before useEffect starts: never return the previous patient's data.
  if (path === null) return { data: null, error: null, loading: false, reload }
  if (state.path !== path) return { data: null, error: null, loading: true, reload }
  return { data: state.data, error: state.error, loading: state.loading, reload }
}

export function useAction<A extends unknown[], R>(fn: (...args: A) => Promise<R>) {
  const [error, setError] = useState<ApiError | null>(null)
  const [pending, setPending] = useState(false)

  const run = useCallback(async (...args: A): Promise<R | undefined> => {
    setPending(true)
    setError(null)
    try {
      return await fn(...args)
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError(0, String(e), null))
      return undefined
    } finally {
      setPending(false)
    }
  }, [fn])

  return { run, error, pending, clearError: () => setError(null) }
}
