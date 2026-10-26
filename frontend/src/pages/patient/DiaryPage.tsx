import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../api/client'
import { useAction } from '../../api/useApi'
import { ErrorMessage } from '../../components/ErrorMessage'

function today(): string {
  const d = new Date()
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10)
}

const SCALES = [
  { name: 'mood', label: 'Настроение', hint: '0 — очень плохое, 10 — отличное' },
  { name: 'anxiety', label: 'Тревога', hint: '0 — нет, 10 — очень сильная' },
  { name: 'sleep_quality', label: 'Качество сна', hint: '0 — очень плохое, 10 — отличное' },
] as const

const SCORE_VALUES = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]

export function DiaryPage() {
  const [form, setForm] = useState<Record<string, string>>({ mood: '5', anxiety: '5', sleep_quality: '5', sleep_hours: '', note: '' })
  const [saved, setSaved] = useState(false)
  const [queuedOffline, setQueuedOffline] = useState(false)
  const submit = useAction(() => api.post<{ queued_offline?: boolean }>('/api/me/diary', {
    day: today(),
    mood: Number(form.mood),
    anxiety: Number(form.anxiety),
    sleep_quality: Number(form.sleep_quality),
    sleep_hours: form.sleep_hours === '' ? null : Number(form.sleep_hours),
    note: form.note.trim() || null,
    client_id: crypto.randomUUID(),
  }))

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setSaved(false)
    setQueuedOffline(false)
    const result = await submit.run()
    if (result?.queued_offline) setQueuedOffline(true)
    else if (result) {
      setSaved(true)
      try { localStorage.setItem(`kompas.diary.done.${today()}`, '1') } catch { /* ignore */ }
    }
  }

  const set = (name: string, value: string) => setForm({ ...form, [name]: value })

  return (
    <>
      <h1>Дневник самочувствия</h1>
      <form className="form diary-form" onSubmit={onSubmit}>
        {SCALES.map((s) => (
          <div key={s.name} className="diary-scale-block">
            <div className="diary-scale-head">
              <span className="diary-scale-label">{s.label}</span>
              <span className="diary-scale-value" aria-live="polite">{form[s.name]}</span>
            </div>
            <p className="diary-scale-hint">{s.hint}</p>
            <div className="score-circles" role="group" aria-label={s.label}>
              {SCORE_VALUES.map((n) => (
                <button
                  key={n}
                  type="button"
                  className={`score-circle${form[s.name] === String(n) ? ' score-circle-active' : ''}`}
                  aria-label={`${s.label}: ${n}`}
                  aria-pressed={form[s.name] === String(n)}
                  onClick={() => set(s.name, String(n))}
                >
                  {n}
                </button>
              ))}
            </div>
          </div>
        ))}
        <label className="diary-field">
          Сон, часов
          <input type="number" min={0} max={24} step={0.5} value={form.sleep_hours}
                 onChange={(e) => set('sleep_hours', e.target.value)} />
        </label>
        <label className="diary-field">
          Заметка
          <textarea rows={4} maxLength={4000} value={form.note} onChange={(e) => set('note', e.target.value)} />
        </label>
        <ErrorMessage error={submit.error} />
        {queuedOffline && <p className="message" role="status">Запись сохранена на устройстве и будет отправлена при появлении связи.</p>}
        {saved && <p className="message" role="status">Дневник сохранён. <Link to="/me">На главную</Link></p>}
        <button type="submit" disabled={submit.pending}>{submit.pending ? 'Сохранение…' : 'Сохранить'}</button>
      </form>
    </>
  )
}
