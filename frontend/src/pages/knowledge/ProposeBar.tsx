import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../api/client'
import type { ValidationResult } from '../../api/types'
import { useAction } from '../../api/useApi'
import { ErrorMessage } from '../../components/ErrorMessage'

/**
 * Общий для всех редакторов справочников блок: проверка, отправка на одобрение
 * рецензентом и просмотр JSON. body() вызывается в момент нажатия.
 */
export function ProposeBar({ kind, code, body, pathLabel = (p) => p || '—' }: {
  kind: string
  code: string
  body: () => unknown
  pathLabel?: (path: string) => string
}) {
  const [check, setCheck] = useState<ValidationResult | null>(null)
  const [note, setNote] = useState('')
  const [sent, setSent] = useState<number | null>(null)
  const [json, setJson] = useState<string | null>(null)
  const validate = useAction(() => api.post<ValidationResult>('/api/knowledge/validate', { kind, body: body() }))
  const propose = useAction(() =>
    api.put<{ draft_id: number }>(`/api/knowledge/${kind}/${encodeURIComponent(code)}`, { body: body(), change_note: note }))

  if (sent !== null) {
    return (
      <div className="message" role="status">
        <p>Черновик № {sent} отправлен. Изменение вступит в силу после одобрения врачом-рецензентом (не автором изменения).</p>
        <p><Link to="/knowledge">К справочникам</Link></p>
      </div>
    )
  }

  return (
    <section aria-labelledby="propose-h" className="propose">
      <h2 id="propose-h">Проверка и отправка на одобрение</h2>
      <p><button type="button" className="secondary" disabled={validate.pending}
                 onClick={async () => setCheck((await validate.run()) ?? null)}>Проверить</button></p>
      <ErrorMessage error={validate.error} />
      {check && <CheckResult result={check} pathLabel={pathLabel} />}
      <label>
        Что изменено и почему
        <textarea rows={2} minLength={5} maxLength={2000} value={note} onChange={(e) => setNote(e.target.value)} />
      </label>
      <ErrorMessage error={propose.error} />
      <p>
        <button type="button" disabled={propose.pending || note.trim().length < 5}
                onClick={async () => { const r = await propose.run(); if (r) setSent(r.draft_id) }}>Отправить на одобрение</button>
      </p>
      <details onToggle={(e) => { if ((e.target as HTMLDetailsElement).open) setJson(JSON.stringify(body(), null, 2)) }}>
        <summary>Описание в формате JSON (для технических специалистов)</summary>
        <pre>{json}</pre>
      </details>
    </section>
  )
}

export function CheckResult({ result, pathLabel = (p) => p || '—' }: {
  result: ValidationResult
  pathLabel?: (path: string) => string
}) {
  return (
    <div className={result.valid ? 'message' : 'message message-error'} role="status">
      <p>{result.valid ? 'Ошибок не найдено.' : 'Исправьте ошибки:'}</p>
      {result.errors.length > 0 && (
        <ul>{result.errors.map((e, i) => <li key={i}><strong>{pathLabel(e.path)}:</strong> {e.message}</li>)}</ul>
      )}
      {result.warnings.length > 0 && (
        <>
          <p>Предупреждения:</p>
          <ul>{result.warnings.map((w, i) => <li key={i}><strong>{pathLabel(w.path)}:</strong> {w.message}</li>)}</ul>
        </>
      )}
    </div>
  )
}
