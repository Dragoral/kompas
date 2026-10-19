import { useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../../api/client'
import type { ScaleDefinition, ScaleItem, ScaleResult } from '../../api/types'
import { useAction, useApi } from '../../api/useApi'
import { ErrorMessage } from '../../components/ErrorMessage'
import { Loader } from '../../components/Loader'

export function ScalePage() {
  const { code } = useParams()
  const state = useApi<ScaleDefinition>(`/api/scales/${code}`)
  return <Loader state={state}>{(scale) => <ScaleForm scale={scale} />}</Loader>
}

function optionsFor(scale: ScaleDefinition, item: ScaleItem) {
  if (item.type === 'yes_no') return item.options ?? [{ value: 0, label: 'Нет' }, { value: 1, label: 'Да' }]
  return item.options ?? scale.options ?? []
}

function ScaleForm({ scale }: { scale: ScaleDefinition }) {
  const [answers, setAnswers] = useState<Record<string, number>>({})
  const [clientId] = useState(() => crypto.randomUUID())
  const [result, setResult] = useState<ScaleResult | null>(null)
  const submit = useAction(() =>
    api.post<ScaleResult>('/api/me/scales', { scale_code: scale.code, answers, client_id: clientId }))

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault()
    const r = await submit.run()
    if (r) setResult(r)
  }

  if (result) {
    return (
      <>
        <h1>{scale.title}</h1>
        <p className="message" role="status">Ответы отправлены врачу. Спасибо!</p>
        {result.crisis && (
          <p className="message message-error" role="alert">
            Врач получил срочное оповещение. Телефоны экстренной помощи — на <Link to="/me">главной странице</Link>.
          </p>
        )}
        <p><Link to="/me">Вернуться на главную</Link></p>
      </>
    )
  }

  return (
    <>
      <h1>{scale.title}</h1>
      {scale.period && <p>{scale.period}</p>}
      <form className="form" onSubmit={onSubmit}>
        {scale.items.map((item) => (
          <fieldset key={item.n}>
            <legend>{item.n}. {item.text}</legend>
            {item.type === 'number' ? (
              <input type="number" required={item.required !== false} min={item.min} max={item.max} step="any"
                     aria-label={item.text} value={answers[item.n] ?? ''}
                     onChange={(e) => setAnswers({ ...answers, [item.n]: Number(e.target.value) })} />
            ) : (
              optionsFor(scale, item).map((o) => (
                <label key={o.value} className="radio">
                  <input type="radio" name={`q${item.n}`} value={o.value} required={item.required !== false}
                         checked={answers[item.n] === o.value}
                         onChange={() => setAnswers({ ...answers, [item.n]: o.value })} />
                  {o.label}
                </label>
              ))
            )}
          </fieldset>
        ))}
        <ErrorMessage error={submit.error} />
        <button type="submit" disabled={submit.pending}>Отправить</button>
      </form>
    </>
  )
}
