import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../api/client'
import { useAction } from '../../api/useApi'
import { ErrorMessage } from '../../components/ErrorMessage'

const INTENSITY = [
  { value: 'mild', label: 'Слабо', hint: 'Не мешает повседневным делам' },
  { value: 'moderate', label: 'Умеренно', hint: 'Заметно, но терпимо' },
  { value: 'severe', label: 'Сильно', hint: 'Сильно мешает или пугает' },
] as const

export function AdverseEventPage() {
  const [form, setForm] = useState({ title: '', intensity: 'mild', serious: false, life_threatening: false, description: '' })
  const [sent, setSent] = useState(false)
  const [queuedOffline, setQueuedOffline] = useState(false)
  const submit = useAction(() => api.post<{ queued_offline?: boolean }>('/api/me/adverse-events', {
    ...form, title: form.title.trim(), description: form.description.trim() || null, client_id: crypto.randomUUID(),
  }))

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault()
    const result = await submit.run()
    if (result?.queued_offline) setQueuedOffline(true)
    else if (result) setSent(true)
  }

  if (queuedOffline) {
    return (
      <>
        <h1>Сообщение сохранено локально</h1>
        <p className="message message-error" role="alert">
          Сведения о нежелательной реакции ещё не доставлены врачу. При экстренном состоянии не ждите синхронизации и обратитесь за медицинской помощью.
        </p>
        <p><Link to="/me">На главную</Link></p>
      </>
    )
  }

  if (sent) {
    return (
      <>
        <h1>Сообщение отправлено</h1>
        <p className="message" role="status">
          Сообщение сохранено и доступно лечащему врачу. Это не гарантирует, что врач уже прочитал его; при экстренном состоянии не ждите ответа через приложение.
        </p>
        <p><Link to="/me">На главную</Link></p>
      </>
    )
  }

  return (
    <>
      <h1>Сообщить о нежелательной реакции</h1>
      <p className="page-lead">
        Опишите, что вы заметили после начала приёма препарата. Не прекращайте приём самостоятельно, не посоветовавшись с врачом.
      </p>
      <form className="form ae-form" onSubmit={onSubmit}>
        <label>
          Что произошло
          <input
            required
            minLength={2}
            maxLength={128}
            placeholder="Например: головокружение, тошнота"
            value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })}
          />
        </label>

        <div className="ae-intensity" role="group" aria-labelledby="ae-intensity-title">
          <div id="ae-intensity-title" className="ae-intensity-title">Насколько выражено</div>
          <div className="ae-intensity-options">
            {INTENSITY.map(({ value, label, hint }) => (
              <label
                key={value}
                className={`ae-intensity-card${form.intensity === value ? ' ae-intensity-card-active' : ''}`}
              >
                <input
                  type="radio"
                  name="intensity"
                  checked={form.intensity === value}
                  onChange={() => setForm({ ...form, intensity: value })}
                />
                <span className="ae-intensity-label">{label}</span>
                <span className="ae-intensity-hint">{hint}</span>
              </label>
            ))}
          </div>
        </div>

        <label className="checkbox ae-check">
          <input
            type="checkbox"
            checked={form.serious}
            onChange={(e) => setForm({ ...form, serious: e.target.checked })}
          />
          <span>Потребовалась госпитализация или обращение за неотложной помощью</span>
        </label>

        <label className="checkbox ae-check">
          <input
            type="checkbox"
            checked={form.life_threatening}
            onChange={(e) => setForm({ ...form, life_threatening: e.target.checked })}
          />
          <span>Состояние угрожало жизни</span>
        </label>

        <label>
          Подробности
          <textarea
            rows={4}
            maxLength={4000}
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
            placeholder="Когда началось, как долго длится, что ещё заметили…"
          />
        </label>

        <ErrorMessage error={submit.error} />
        <button type="submit" disabled={submit.pending}>
          {submit.pending ? 'Отправка…' : 'Отправить врачу'}
        </button>
      </form>
    </>
  )
}
