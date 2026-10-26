import { useEffect, useState, type FormEvent } from 'react'
import { api } from '../api/client'
import { subscribe } from '../api/stream'
import type { Message } from '../api/types'
import { useAction, useApi } from '../api/useApi'
import { formatDateTime } from '../format'
import { ErrorMessage } from './ErrorMessage'
import { Loader } from './Loader'

/** Переписка врача и пациента. path — адрес списка/отправки, stream — канал событий для обновления. */
export function Chat({ path, stream, me }: { path: string; stream: string; me: 'doctor' | 'patient' }) {
  const state = useApi<Message[]>(path)
  const { reload } = state
  const [text, setText] = useState('')
  const send = useAction(() => api.post<{ crisis?: boolean; queued_offline?: boolean }>(path, { text: text.trim(), client_id: crypto.randomUUID() }))
  const [crisis, setCrisis] = useState(false)
  const [queuedOffline, setQueuedOffline] = useState(false)

  useEffect(() => subscribe(stream, ['message'], reload), [stream, reload])

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault()
    const r = await send.run()
    if (r?.queued_offline) {
      setQueuedOffline(true)
      setText('')
    } else if (r) {
      setQueuedOffline(false)
      setText('')
      setCrisis(!!r.crisis)
      reload()
    }
  }

  return (
    <>
      {queuedOffline && me === 'patient' && <p className="message" role="status">Сообщение сохранено локально и ещё не доставлено врачу. Оно будет отправлено после восстановления соединения.</p>}
      {crisis && (
        <p className="message message-error" role="alert">
          Система сформировала срочный сигнал, но это не подтверждает, что врач уже увидел его. Если есть непосредственная опасность, не ждите ответа в чате — звоните 112 или 103.
        </p>
      )}
      <Loader state={state}>
        {(messages) => messages.length === 0 ? <p>Сообщений пока нет.</p> : (
          <ol className="chat" aria-live="polite">
            {messages.map((m) => (
              <li key={m.id} className={m.sender_role === me ? 'chat-mine' : 'chat-theirs'}>
                <div className="small muted">
                  {m.sender_role === me ? 'Вы' : m.sender_role === 'doctor' ? 'Врач' : 'Пациент'}, {formatDateTime(m.created_at)}
                </div>
                <div className="chat-text">{m.text}</div>
              </li>
            ))}
          </ol>
        )}
      </Loader>
      <form className="form" onSubmit={onSubmit}>
        <label>
          Сообщение
          <textarea rows={3} required maxLength={4000} value={text} onChange={(e) => setText(e.target.value)} />
        </label>
        <ErrorMessage error={send.error} />
        <button type="submit" disabled={send.pending || !text.trim()}>Отправить</button>
      </form>
    </>
  )
}
