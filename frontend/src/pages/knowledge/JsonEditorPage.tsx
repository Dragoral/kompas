import { useState } from 'react'
import { useAuth } from '../../auth/AuthContext'
import { Link, useParams } from 'react-router-dom'
import { useApi } from '../../api/useApi'
import { Loader } from '../../components/Loader'
import { KIND_LABEL } from './KnowledgePage'
import { ProposeBar } from './ProposeBar'

/**
 * Редактирование любого справочника как JSON — для технических специалистов и для
 * справочников без отдельной формы (клинические рекомендации, словари). Структура
 * проверяется сервером по JSON Schema (GET /api/knowledge/schemas/{kind}).
 */
export function JsonEditorPage() {
  const { kind = '', code = '' } = useParams()
  const { user } = useAuth()
  const base = user?.role === 'admin' ? '/api/admin/knowledge' : '/api/knowledge'
  const state = useApi<{ body: unknown; version: number }>(`${base}/${kind}/${encodeURIComponent(code)}`)
  const schema = useApi<unknown>(`/api/knowledge/schemas/${kind}`)
  return <Loader state={state}>{(r) => <Editor kind={kind} code={code} initial={r.body} version={r.version} schema={schema.data} schemaError={schema.error} schemaLoading={schema.loading} />}</Loader>
}

function Editor({ kind, code, initial, version, schema, schemaError, schemaLoading }: { kind: string; code: string; initial: unknown; version: number; schema: unknown; schemaError: import('../../api/client').ApiError | null; schemaLoading: boolean }) {
  const [text, setText] = useState(() => JSON.stringify(initial, null, 2))
  const [error, setError] = useState<string | null>(null)

  const parse = () => {
    try {
      const v = JSON.parse(text)
      setError(null)
      return v
    } catch (e) {
      setError(`Некорректный JSON: ${(e as Error).message}`)
      return null
    }
  }

  return (
    <>
      <h1>{KIND_LABEL[kind] ?? kind}: {code}</h1>
      <p className="muted">Действующая версия: {version}. Изменения вступят в силу после одобрения рецензентом.</p>
      <p><Link to="/knowledge">К справочникам</Link></p>
      <div className="form wide">
        <label>
          Описание (JSON)
          <textarea rows={28} className="mono" spellCheck={false} value={text} aria-invalid={!!error}
                    onChange={(e) => setText(e.target.value)} onBlur={parse} />
        </label>
        {error && <p className="message message-error" role="alert">{error}</p>}
      </div>
      <ProposeBar kind={kind} code={code} body={parse} />
      <details className="feature-card"><summary>JSON Schema для этого справочника</summary>{schemaLoading ? <p className="muted">Загрузка схемы…</p> : schemaError ? <p className="message message-error">Не удалось загрузить схему: {schemaError.message}</p> : <pre className="plain-text">{JSON.stringify(schema, null, 2)}</pre>}</details>
    </>
  )
}
