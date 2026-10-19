import { useCallback, useEffect, useState } from 'react'
import { api, ApiError } from './client'

export interface ApiState<T> {
  data: T | null
  error: ApiError | null
  loading: boolean
  reload: () => void
}

export function useApi<T>(path: string | null): ApiState<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [loading, setLoading] = useState(path !== null)
  const [version, setVersion] = useState(0)

  useEffect(() => {
    if (path === null) return
    let cancelled = false
    setLoading(true)
    setError(null)
    api.get<T>(path)
      .then((d) => { if (!cancelled) setData(d) })
      .catch((e: ApiError) => { if (!cancelled) setError(e) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [path, version])

  const reload = useCallback(() => setVersion((v) => v + 1), [])
  return { data, error, loading, reload }
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
