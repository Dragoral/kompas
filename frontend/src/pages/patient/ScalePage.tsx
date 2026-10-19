import { useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../../api/client'
import type { ScaleDefinition, ScaleResult } from '../../api/types'
import { useAction, useApi } from '../../api/useApi'
import { ErrorMessage } from '../../components/ErrorMessage'
import { Loader } from '../../components/Loader'
import { ScaleQuestions, type Answers } from '../../components/ScaleQuestions'

export function ScalePage() {
  const { code } = useParams()
  const state = useApi<ScaleDefinition>(`/api/scales/${code}`)
  return <Loader state={state}>{(scale) => <ScaleForm scale={scale} />}</Loader>
}

function ScaleForm({ scale }: { scale: ScaleDefinition }) {
  const [answers, setAnswers] = useState<Answers>({})
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
        <ScaleQuestions scale={scale} answers={answers} onChange={setAnswers} />
        <ErrorMessage error={submit.error} />
        <button type="submit" disabled={submit.pending}>Отправить</button>
      </form>
    </>
  )
}
