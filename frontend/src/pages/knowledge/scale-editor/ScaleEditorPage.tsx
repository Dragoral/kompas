import { useState, type FormEvent } from 'react'
import { Link, useLocation, useParams } from 'react-router-dom'
import { api } from '../../../api/client'
import type { ScaleDefinition, ValidationResult } from '../../../api/types'
import { useAction, useApi } from '../../../api/useApi'
import { ErrorMessage } from '../../../components/ErrorMessage'
import { Loader } from '../../../components/Loader'
import { ScaleQuestions, type Answers } from '../../../components/ScaleQuestions'
import { CheckResult } from '../ProposeBar'
import { BandsEditor } from './BandsEditor'
import { ItemsEditor } from './ItemsEditor'
import { emptyScale, pathLabel, toBody, type ScaleBody } from './model'
import { SubscalesEditor } from './SubscalesEditor'

const METHODS: Record<string, string> = {
  sum: 'Сумма баллов',
  mean: 'Среднее',
  weighted_sum: 'Взвешенная сумма',
  max_item_positive: 'Положительный ответ на любой пункт (скрининг)',
}

interface ImportState {
  draft?: ScaleBody
  todo?: string[]
}

export function ScaleEditorPage() {
  const { code } = useParams()
  const location = useLocation()
  const imported = location.state as ImportState | null

  if (code) return <ExistingScale code={code} />
  return <ScaleEditor initial={imported?.draft ?? emptyScale()} todo={imported?.todo ?? []} isNew />
}

function ExistingScale({ code }: { code: string }) {
  const state = useApi<{ body: ScaleBody; version: number }>(`/api/knowledge/scale/${encodeURIComponent(code)}`)
  return <Loader state={state}>{(r) => <ScaleEditor initial={r.body} todo={[]} version={r.version} />}</Loader>
}

function ScaleEditor({ initial, todo, isNew = false, version }: {
  initial: ScaleBody
  todo: string[]
  isNew?: boolean
  version?: number
}) {
  const [scale, setScale] = useState<ScaleBody>(initial)
  const [check, setCheck] = useState<ValidationResult | null>(null)
  const [note, setNote] = useState('')
  const [sent, setSent] = useState<number | null>(null)
  const methodsState = useApi<string[]>('/api/knowledge/scoring-methods')

  const set = (patch: Partial<ScaleBody>) => {
    setScale((s) => ({ ...s, ...patch }))
    setCheck(null)
  }
  const validate = useAction(() => api.post<ValidationResult>('/api/knowledge/validate', { kind: 'scale', body: toBody(scale) }))
  const propose = useAction(() => {
    const body = toBody(scale)
    return api.put<{ draft_id: number }>(`/api/knowledge/scale/${encodeURIComponent(body.code)}`, { body, change_note: note })
  })

  const onValidate = async () => {
    const r = await validate.run()
    if (r) setCheck(r)
  }

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault()
    const r = await propose.run()
    if (r) setSent(r.draft_id)
  }

  if (sent !== null) {
    return (
      <>
        <h1>Шкала отправлена на одобрение</h1>
        <p className="message" role="status">
          Черновик № {sent}. Изменение вступит в силу после одобрения врачом-рецензентом (не автором изменения).
        </p>
        <p><Link to="/knowledge">К справочникам</Link></p>
      </>
    )
  }

  const subscales = scale.scoring?.subscales ?? {}
  const method = scale.scoring?.method ?? 'sum'
  const methodOptions = (methodsState.data ?? Object.keys(METHODS)).map((value) => [value, METHODS[value] ?? value] as const)

  return (
    <>
      <h1>{isNew ? 'Новая шкала' : `Изменение шкалы ${scale.code}`}</h1>
      {version !== undefined && <p className="muted">Действующая версия: {version}. Изменения вступят в силу после одобрения рецензентом.</p>}
      {todo.length > 0 && (
        <div className="message">
          <p>После импорта нужно дополнить:</p>
          <ul>{todo.map((t) => <li key={t}>{t}</li>)}</ul>
        </div>
      )}

      <form className="form wide" onSubmit={onSubmit}>
        <section aria-labelledby="basics-h">
          <h2 id="basics-h">Основное</h2>
          <div className="row form-row-aligned">
            <label className="field-block">
              Код
              <input required pattern="[A-Za-z0-9_]{2,16}" readOnly={!isNew} value={scale.code}
                     aria-describedby="code-hint" onChange={(e) => set({ code: e.target.value.toUpperCase() })} />
              <span id="code-hint" className="field-hint">Латиница, цифры, «_», например PHQ9</span>
            </label>
            <label className="field-block">
              Кто заполняет
              <select value={scale.respondent} onChange={(e) => set({ respondent: e.target.value as ScaleBody['respondent'] })}>
                <option value="patient">Пациент</option>
                <option value="clinician">Врач</option>
              </select>
              <span className="field-hint field-hint-spacer" aria-hidden="true">&nbsp;</span>
            </label>
          </div>
          <label>
            Название
            <input required minLength={3} value={scale.title} onChange={(e) => set({ title: e.target.value })} />
          </label>
          <label>
            Инструкция перед вопросами
            <textarea rows={2} value={scale.period ?? ''} placeholder="Например: за последние 2 недели как часто вас беспокоило…"
                      onChange={(e) => set({ period: e.target.value })} />
          </label>
        </section>

        <section aria-labelledby="items-h">
          <h2 id="items-h">Вопросы</h2>
          <ItemsEditor items={scale.items} weighted={method === 'weighted_sum'} onChange={(items) => set({ items })} />
        </section>

        <section aria-labelledby="scoring-h">
          <h2 id="scoring-h">Подсчёт и интерпретация</h2>
          {methodsState.error && <p className="message message-error">Не удалось загрузить список методов из API; показаны локальные значения по умолчанию.</p>}
          <label>
            Способ подсчёта
            <select value={method} onChange={(e) => set({ scoring: { ...scale.scoring, method: e.target.value } })}>
              {methodOptions.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </label>
          <BandsEditor bands={scale.bands} onChange={(bands) => set({ bands })} />
          <h3>Подшкалы</h3>
          <SubscalesEditor subscales={subscales}
                           onChange={(s) => set({ scoring: { ...scale.scoring, subscales: s } })} />
        </section>

        <section aria-labelledby="source-h">
          <h2 id="source-h">Источники и лицензия</h2>
          <label>
            Публикации (по одной в строке): оригинал и валидация русскоязычной версии
            <textarea rows={3} required value={scale.validation.join('\n')}
                      onChange={(e) => set({ validation: e.target.value.split('\n') })} />
          </label>
          <label>
            Условия использования
            <input required minLength={3} value={scale.license} placeholder="Например: свободное использование, разрешение не требуется"
                   onChange={(e) => set({ license: e.target.value })} />
          </label>
          <label className="checkbox">
            <input type="checkbox" checked={!!scale.verified} onChange={(e) => set({ verified: e.target.checked })} />
            Текст сверен с валидированной русскоязычной версией
          </label>
        </section>

        <section aria-labelledby="check-h">
          <h2 id="check-h">Проверка</h2>
          <p><button type="button" className="secondary" disabled={validate.pending} onClick={onValidate}>Проверить шкалу</button></p>
          <ErrorMessage error={validate.error} />
          {check && <CheckResult result={check} pathLabel={pathLabel} />}
          <Preview scale={scale} />
        </section>

        <section aria-labelledby="send-h">
          <h2 id="send-h">Отправка на одобрение</h2>
          <label>
            Что изменено и почему
            <textarea rows={2} required minLength={5} maxLength={2000} value={note} onChange={(e) => setNote(e.target.value)} />
          </label>
          <ErrorMessage error={propose.error} />
          <p>
            <button type="submit" disabled={propose.pending}>Отправить на одобрение</button>
          </p>
          <details>
            <summary>Описание шкалы в формате JSON (для технических специалистов)</summary>
            <pre>{JSON.stringify(toBody(scale), null, 2)}</pre>
          </details>
        </section>
      </form>
    </>
  )
}

interface PreviewResult {
  score: number
  band: string | null
  range: [number, number]
  subscales: Record<string, { score: number; band?: string | null; title?: string }>
  critical_items: number[]
}

function Preview({ scale }: { scale: ScaleBody }) {
  const [answers, setAnswers] = useState<Answers>({})
  const [result, setResult] = useState<PreviewResult | null>(null)
  const run = useAction(() => api.post<PreviewResult>('/api/knowledge/scales/preview', { scale: toBody(scale), answers }))

  const onRun = async () => {
    const r = await run.run()
    setResult(r ?? null)
  }

  return (
    <details>
      <summary>Пробное заполнение</summary>
      <p className="muted">Ответьте на вопросы так, как ответил бы пациент, и проверьте подсчёт. Ответы никуда не сохраняются.</p>
      <ScaleQuestions scale={toBody(scale) as unknown as ScaleDefinition} answers={answers} onChange={setAnswers} idPrefix="preview" optional />
      <p><button type="button" className="secondary" disabled={run.pending} onClick={onRun}>Посчитать</button></p>
      <ErrorMessage error={run.error} />
      {result && (
        <dl className="summary" role="status">
          <dt>Балл</dt><dd>{result.score} (диапазон {result.range[0]}–{result.range[1]})</dd>
          <dt>Интерпретация</dt><dd>{result.band ?? '—'}</dd>
          {Object.entries(result.subscales ?? {}).map(([k, s]) => (
            <div key={k} className="contents"><dt>{s.title || `Подшкала ${k}`}</dt><dd>{s.score}{s.band ? ` (${s.band})` : ''}</dd></div>
          ))}
          {result.critical_items?.length > 0 && <><dt>Критические пункты</dt><dd>{result.critical_items.join(', ')}</dd></>}
        </dl>
      )}
    </details>
  )
}
