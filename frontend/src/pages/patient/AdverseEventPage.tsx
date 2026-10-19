import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../api/client'
import { useAction } from '../../api/useApi'
import { ErrorMessage } from '../../components/ErrorMessage'

export function AdverseEventPage() {
  const [form, setForm] = useState({ title: '', intensity: 'mild', serious: false, life_threatening: false, description: '' })
  const [sent, setSent] = useState(false)
  const submit = useAction(() => api.post('/api/me/adverse-events', {
    ...form, title: form.title.trim(), description: form.description.trim() || null, client_id: crypto.randomUUID(),
  }))

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault()
    if (await submit.run()) setSent(true)
  }

  if (sent) {
    return (
      <>
        <h1>Сообщение отправлено</h1>
        <p className="message" role="status">Врач получил ваше сообщение о нежелательной реакции.</p>
        <p><Link to="/me">На главную</Link></p>
      </>
    )
  }

  return (
    <>
      <h1>Сообщить о нежелательной реакции</h1>
      <p>Опишите, что вы заметили после начала приёма препарата. Не прекращайте приём самостоятельно, не посоветовавшись с врачом.</p>
      <form className="form" onSubmit={onSubmit}>
        <label>
          Что произошло
          <input required minLength={2} maxLength={128} placeholder="Например: головокружение, тошнота"
                 value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
        </label>
        <fieldset>
          <legend>Насколько выражено</legend>
          {[['mild', 'Слабо'], ['moderate', 'Умеренно'], ['severe', 'Сильно']].map(([v, l]) => (
            <label key={v} className="radio">
              <input type="radio" name="intensity" checked={form.intensity === v} onChange={() => setForm({ ...form, intensity: v })} />
              {l}
            </label>
          ))}
        </fieldset>
        <label className="checkbox">
          <input type="checkbox" checked={form.serious} onChange={(e) => setForm({ ...form, serious: e.target.checked })} />
          Потребовалась госпитализация или обращение за неотложной помощью
        </label>
        <label className="checkbox">
          <input type="checkbox" checked={form.life_threatening}
                 onChange={(e) => setForm({ ...form, life_threatening: e.target.checked })} />
          Состояние угрожало жизни
        </label>
        <label>
          Подробности
          <textarea rows={4} maxLength={4000} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
        </label>
        <ErrorMessage error={submit.error} />
        <button type="submit" disabled={submit.pending}>Отправить врачу</button>
      </form>
    </>
  )
}
