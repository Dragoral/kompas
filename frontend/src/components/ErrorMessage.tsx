import type { ApiError } from '../api/client'

export function ErrorMessage({ error }: { error: ApiError | null }) {
  if (!error) return null
  return (
    <div className="message message-error" role="alert">
      <p>{error.message}</p>
      {error.errors.length > 0 && (
        <ul>
          {error.errors.map((e, i) => (
            <li key={i}>
              {(e.field ?? e.path) && <code>{e.field ?? e.path}</code>} {e.message}
            </li>
          ))}
        </ul>
      )}
      {error.requestId && <p className="muted small">Номер запроса: {error.requestId}</p>}
    </div>
  )
}
