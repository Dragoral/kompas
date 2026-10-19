import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../../api/client'
import type { ImportResult } from '../../api/types'
import { useAction } from '../../api/useApi'
import { ErrorMessage } from '../../components/ErrorMessage'

type Source = 'csv' | 'fhir-url' | 'fhir-file'

const CSV_EXAMPLE = 'n;text;options\n1;Текст вопроса;0=Нет|1=Иногда|2=Часто|3=Постоянно'

/** Импорт заполняет конструктор шкалы; дальше врач дополняет и отправляет на одобрение. */
export function ImportScalePage() {
  const navigate = useNavigate()
  const [source, setSource] = useState<Source>('csv')
  const [input, setInput] = useState({ csv: '', code: '', title: '', url: '', file: '' })

  const importer = useAction(async (): Promise<ImportResult> => {
    if (source === 'csv') return api.post('/api/knowledge/import/csv', { csv: input.csv, code: input.code, title: input.title })
    if (source === 'fhir-url') return api.post('/api/knowledge/import/fhir-questionnaire', { url: input.url })
    let resource: unknown
    try {
      resource = JSON.parse(input.file)
    } catch {
      throw new Error('Файл не является корректным JSON')
    }
    return api.post('/api/knowledge/import/fhir-questionnaire', { resource })
  })

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault()
    const r = await importer.run()
    if (r) navigate('/knowledge/scales/new', { state: { draft: r.draft, todo: r.todo } })
  }

  const onFile = async (file: File | undefined) => {
    if (file) setInput({ ...input, file: await file.text() })
  }

  return (
    <>
      <h1>Импорт шкалы</h1>
      <p>Вопросы и варианты ответа загрузятся в конструктор. Градации, источники и лицензию нужно будет дополнить.</p>
      <form className="form" onSubmit={onSubmit}>
        <fieldset>
          <legend>Источник</legend>
          <label className="radio">
            <input type="radio" name="source" checked={source === 'csv'} onChange={() => setSource('csv')} />
            Таблица CSV (можно сохранить из Excel)
          </label>
          <label className="radio">
            <input type="radio" name="source" checked={source === 'fhir-url'} onChange={() => setSource('fhir-url')} />
            HL7 FHIR Questionnaire по ссылке
          </label>
          <label className="radio">
            <input type="radio" name="source" checked={source === 'fhir-file'} onChange={() => setSource('fhir-file')} />
            HL7 FHIR Questionnaire из файла
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
              Таблица: колонки n (номер), text (вопрос), options (варианты «балл=текст» через «|»)
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
        <button type="submit" disabled={importer.pending}>Загрузить в конструктор</button>
      </form>
    </>
  )
}
