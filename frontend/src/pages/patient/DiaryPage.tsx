import { useState, type FormEvent } from 'react'
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

export function DiaryPage() {
  const [form, setForm] = useState<Record<string, string>>({ mood: '5', anxiety: '5', sleep_quality: '5', sleep_hours: '', note: '' })
  const [saved, setSaved] = useState(false)
  const submit = useAction(() => api.post('/api/me/diary', {
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
    if (await submit.run()) setSaved(true)
  }

  const set = (name: string, value: string) => setForm({ ...form, [name]: value })

  return (
    <>
      <h1>Дневник самочувствия</h1>
      <form className="form" onSubmit={onSubmit}>
        {SCALES.map((s) => (
          <label key={s.name}>
            {s.label}: <output>{form[s.name]}</output>
            <input type="range" min={0} max={10} step={1} value={form[s.name]}
                   aria-describedby={`${s.name}-hint`} onChange={(e) => set(s.name, e.target.value)} />
            <span id={`${s.name}-hint`} className="muted small">{s.hint}</span>
          </label>
        ))}
        <label>
          Сон, часов
          <input type="number" min={0} max={24} step={0.5} value={form.sleep_hours}
                 onChange={(e) => set('sleep_hours', e.target.value)} />
        </label>
        <label>
          Заметка
          <textarea rows={4} maxLength={4000} value={form.note} onChange={(e) => set('note', e.target.value)} />
        </label>
        <ErrorMessage error={submit.error} />
        {saved && <p className="message" role="status">Запись сохранена.</p>}
        <button type="submit" disabled={submit.pending}>Сохранить</button>
      </form>
    </>
  )
}
