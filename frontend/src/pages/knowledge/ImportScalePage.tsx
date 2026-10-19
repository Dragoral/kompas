import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../api/client'
import type { ImportResult, ValidationResult } from '../../api/types'
import { useAction } from '../../api/useApi'
import { ErrorMessage } from '../../components/ErrorMessage'

type Source = 'csv' | 'fhir-url' | 'fhir-file'

const CSV_EXAMPLE = 'n;text;options\n1;Текст вопроса;0=Нет|1=Иногда|2=Часто|3=Постоянно'

export function ImportScalePage() {
  const [source, setSource] = useState<Source>('csv')
  const [input, setInput] = useState({ csv: '', code: '', title: '', url: '', file: '' })
  const [json, setJson] = useState('')
  const [todo, setTodo] = useState<string[]>([])
  const [check, setCheck] = useState<ValidationResult | null>(null)
  const [note, setNote] = useState('')
  const [sent, setSent] = useState<number | null>(null)

  const importer = useAction(async (): Promise<ImportResult> => {
    if (source === 'csv') return api.post('/api/knowledge/import/csv', { csv: input.csv, code: input.code, title: input.title })
    if (source === 'fhir-url') return api.post('/api/knowledge/import/fhir-questionnaire', { url: input.url })
    return api.post('/api/knowledge/import/fhir-questionnaire', { resource: JSON.parse(input.file) })
  })
  const validate = useAction((body: unknown) => api.post<ValidationResult>('/api/knowledge/validate', { kind: 'scale', body }))
  const propose = useAction((code: string, body: unknown) =>
    api.put<{ draft_id: number }>(`/api/knowledge/scale/${encodeURIComponent(code)}`, { body, change_note: note }))

  const parsed = (): Record<string, unknown> | null => {
    try {
      return JSON.parse(json)
    } catch {
      return null
    }
  }

  const onImport = async (e: FormEvent) => {
    e.preventDefault()
    const r = await importer.run()
    if (!r) return
    setJson(JSON.stringify(r.draft, null, 2))
    setTodo(r.todo)
    setCheck({ valid: r.errors.length === 0, errors: r.errors, warnings: r.warnings })
  }

  const onFile = async (file: File | undefined) => {
    if (file) setInput({ ...input, file: await file.text() })
  }

  const onValidate = async () => {
    const body = parsed()
    if (!body) {
      setCheck({ valid: false, errors: [{ path: '', message: 'Описание не является корректным JSON' }], warnings: [] })
      return
    }
    const r = await validate.run(body)
    if (r) setCheck(r)
  }

  const onPropose = async (e: FormEvent) => {
    e.preventDefault()
    const body = parsed()
    if (!body) return
    const r = await propose.run(String(body.code ?? ''), body)
    if (r) setSent(r.draft_id)
  }

  if (sent !== null) {
    return (
      <>
        <h1>Шкала отправлена на рассмотрение</h1>
        <p className="message" role="status">
          Черновик № {sent} вступит в силу после одобрения врачом-рецензентом (не автором изменения).
        </p>
        <p><Link to="/knowledge">К справочникам</Link></p>
      </>
    )
  }

  return (
    <>
      <h1>Добавить шкалу</h1>
      <form className="form" onSubmit={onImport}>
        <fieldset>
          <legend>Источник</legend>
          <label className="radio">
            <input type="radio" name="source" checked={source === 'csv'} onChange={() => setSource('csv')} />
            Таблица CSV
          </label>
          <label className="radio">
            <input type="radio" name="source" checked={source === 'fhir-url'} onChange={() => setSource('fhir-url')} />
            FHIR Questionnaire по ссылке
          </label>
          <label className="radio">
            <input type="radio" name="source" checked={source === 'fhir-file'} onChange={() => setSource('fhir-file')} />
            FHIR Questionnaire из файла
          </label>
        </fieldset>

        {source === 'csv' && (
          <>
            <label>
              Код шкалы
              <input required minLength={2} maxLength={16} value={input.code}
                     onChange={(e) => setInput({ ...input, code: e.target.value })} />
            </label>
            <label>
              Название
              <input required minLength={3} maxLength={200} value={input.title}
                     onChange={(e) => setInput({ ...input, title: e.target.value })} />
            </label>
            <label>
              Таблица (колонки n, text, options; разделитель «;» или «,»)
              <textarea required rows={8} className="mono" placeholder={CSV_EXAMPLE} value={input.csv}
                        onChange={(e) => setInput({ ...input, csv: e.target.value })} />
            </label>
          </>
        )}
        {source === 'fhir-url' && (
          <label>
            Ссылка (https)
            <input type="url" required pattern="https://.*" value={input.url}
                   onChange={(e) => setInput({ ...input, url: e.target.value })} />
          </label>
        )}
        {source === 'fhir-file' && (
          <label>
            Файл JSON
            <input type="file" required accept=".json,application/json,application/fhir+json"
                   onChange={(e) => onFile(e.target.files?.[0])} />
          </label>
        )}
        <ErrorMessage error={importer.error} />
        <button type="submit" disabled={importer.pending}>Загрузить</button>
      </form>

      {json && (
        <form className="form" onSubmit={onPropose}>
          <h2>Описание шкалы</h2>
          {todo.length > 0 && (
            <div className="message">
              <p>Нужно дополнить:</p>
              <ul>{todo.map((t) => <li key={t}>{t}</li>)}</ul>
            </div>
          )}
          <label>
            Описание (JSON)
            <textarea rows={20} className="mono" spellCheck={false} value={json}
                      onChange={(e) => { setJson(e.target.value); setCheck(null) }} />
          </label>
          <p>
            <button type="button" className="secondary" disabled={validate.pending} onClick={onValidate}>Проверить</button>
          </p>
          <ErrorMessage error={validate.error} />
          {check && <CheckResult result={check} />}
          <label>
            Комментарий к изменению
            <input required minLength={5} maxLength={2000} value={note} onChange={(e) => setNote(e.target.value)} />
          </label>
          <ErrorMessage error={propose.error} />
          <button type="submit" disabled={!check?.valid || propose.pending}>Отправить на одобрение</button>
        </form>
      )}
    </>
  )
}

function CheckResult({ result }: { result: ValidationResult }) {
  return (
    <div className={result.valid ? 'message' : 'message message-error'} role="status">
      <p>{result.valid ? 'Ошибок нет.' : 'Найдены ошибки:'}</p>
      {result.errors.length > 0 && (
        <ul>{result.errors.map((e, i) => <li key={i}><code>{e.path || '—'}</code> {e.message}</li>)}</ul>
      )}
      {result.warnings.length > 0 && (
        <>
          <p>Предупреждения:</p>
          <ul>{result.warnings.map((w, i) => <li key={i}><code>{w.path || '—'}</code> {w.message}</li>)}</ul>
        </>
      )}
    </div>
  )
}
