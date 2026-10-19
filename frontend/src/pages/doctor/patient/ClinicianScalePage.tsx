import { useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../../../api/client'
import type { ScaleDefinition, ScaleResult } from '../../../api/types'
import { useAction, useApi } from '../../../api/useApi'
import { ErrorMessage } from '../../../components/ErrorMessage'
import { Loader } from '../../../components/Loader'
import { ScaleQuestions, type Answers } from '../../../components/ScaleQuestions'

/** Заполнение шкалы врачом на приёме (например, HAM-A). */
export function ClinicianScalePage() {
  const { id = '', code = '' } = useParams()
  const state = useApi<ScaleDefinition>(`/api/scales/${encodeURIComponent(code)}`)
  return <Loader state={state}>{(scale) => <Form id={id} scale={scale} />}</Loader>
}

function Form({ id, scale }: { id: string; scale: ScaleDefinition }) {
  const [answers, setAnswers] = useState<Answers>({})
  const [clientId] = useState(() => crypto.randomUUID())
  const [result, setResult] = useState<ScaleResult | null>(null)
  const submit = useAction(() => api.post<ScaleResult>(`/api/doctor/patients/${id}/scales`,
    { scale_code: scale.code, answers, client_id: clientId }))

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault()
    const r = await submit.run()
    if (r) setResult(r)
  }

  return (
    <>
      <h1>{scale.title}</h1>
      <p><Link to={`/doctor/patients/${id}/scales`}>Вернуться к карточке пациента</Link></p>
      {result ? (
        <p className="message" role="status">Сохранено. Балл: {result.score}{result.band ? ` (${result.band})` : ''}.</p>
      ) : (
        <form className="form" onSubmit={onSubmit}>
          {scale.period && <p>{scale.period}</p>}
          <ScaleQuestions scale={scale} answers={answers} onChange={setAnswers} />
          <ErrorMessage error={submit.error} />
          <button type="submit" disabled={submit.pending}>Сохранить результат</button>
        </form>
      )}
    </>
  )
}
