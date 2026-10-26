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
  const [queuedOffline, setQueuedOffline] = useState(false)
  const submit = useAction(() =>
    api.post<ScaleResult>('/api/me/scales', { scale_code: scale.code, answers, client_id: clientId, taken_at: new Date().toISOString() }))

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault()
    const r = await submit.run()
    if (r?.queued_offline) setQueuedOffline(true)
    else if (r) {
      setResult(r)
      try {
        const day = new Date(); const key = `kompas.scale.done.${day.getFullYear()}-${String(day.getMonth()+1).padStart(2,'0')}-${String(day.getDate()).padStart(2,'0')}.${scale.code}`
        localStorage.setItem(key, scale.title || scale.code)
      } catch { /* ignore */ }
    }
  }

  if (queuedOffline) return <><h1>{scale.title}</h1><p className="message" role="status">Ответы зашифрованы и сохранены на устройстве. Они ещё не отправлены врачу и будут синхронизированы после восстановления связи.</p><p><Link to="/me">Вернуться на главную</Link></p></>

  if (result) {
    return (
      <>
        <h1>{scale.title}</h1>
        <p className="message" role="status">Ответы отправлены врачу. Спасибо!</p>
        {result.crisis && (
          <p className="message message-error" role="alert">
            Система сформировала срочный сигнал, но это не подтверждает, что врач уже увидел его. При непосредственной опасности не ждите ответа через приложение — звоните 112 или 103. Телефоны помощи также доступны на <Link to="/me">главной странице</Link>.
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
        <button type="submit" disabled={submit.pending}>Сохранить ответы</button>
      </form>
    </>
  )
}
