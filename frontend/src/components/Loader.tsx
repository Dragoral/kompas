import type { ReactNode } from 'react'
import type { ApiState } from '../api/useApi'
import { ErrorMessage } from './ErrorMessage'

export function Loader<T>({ state, children }: { state: ApiState<T>; children: (data: T) => ReactNode }) {
  if (state.error) return <ErrorMessage error={state.error} />
  if (state.data === null) return <p className="muted" aria-busy="true">Загрузка…</p>
  return <>{children(state.data)}</>
}
