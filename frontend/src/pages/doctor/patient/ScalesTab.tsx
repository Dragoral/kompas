import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../../api/client'
import type { KnowledgeRow } from '../../../api/types'
import { useAction, useApi } from '../../../api/useApi'
import { ErrorMessage } from '../../../components/ErrorMessage'
import { formatDate } from '../../../format'
import { usePatient } from './PatientLayout'

export function ScalesTab() {
  const { id, card, reload } = usePatient()
  const catalogue = useApi<KnowledgeRow[]>('/api/knowledge')
  const scales = (catalogue.data ?? []).filter((r) => r.kind === 'scale' && r.active)
  const [form, setForm] = useState({ scale_code: '', every_days: '', reason: '' })
  const assign = useAction(() => api.post(`/api/doctor/patients/${id}/assignments`, {
    scale_code: form.scale_code,
    every_days: form.every_days ? Number(form.every_days) : null,
    reason: form.reason.trim() || null,
  }))

  const onAssign = async (e: FormEvent) => {
    e.preventDefault()
    if (await assign.run()) {
      setForm({ scale_code: '', every_days: '', reason: '' })
      reload()
    }
  }

  return (
    <>
      <section aria-labelledby="results-h">
        <h2 id="results-h">Последние результаты</h2>
        {Object.keys(card.context.scales).length === 0 ? <p>Результатов нет.</p> : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">Шкала</th>
                  <th scope="col">Балл</th>
                  <th scope="col">Интерпретация</th>
                  <th scope="col">Изменение</th>
                  <th scope="col">Дней назад</th>
                  <th scope="col">Всего заполнений</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(card.context.scales).map(([code, s]) => (
                  <tr key={code}>
                    <td>{code}</td>
                    <td>{s.score}</td>
                    <td>{s.band ?? '—'}</td>
                    <td>{s.delta === null ? '—' : s.delta > 0 ? `+${s.delta}` : s.delta}</td>
                    <td>{s.days_ago ?? '—'}</td>
                    <td>{s.count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section aria-labelledby="fill-h">
        <h2 id="fill-h">Заполнить шкалу на приёме</h2>
        <ul className="actions">
          {scales.map((s) => (
            <li key={s.code}><Link to={`/doctor/patients/${id}/scales/${encodeURIComponent(s.code)}`}>{s.title}</Link></li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="assign-h">
        <h2 id="assign-h">Назначенные пациенту</h2>
        {card.assignments.length === 0 ? <p>Нет назначенных шкал.</p> : (
          <table>
            <thead>
              <tr><th scope="col">Шкала</th><th scope="col">Периодичность</th><th scope="col">Следующее заполнение</th><th scope="col">Причина</th></tr>
            </thead>
            <tbody>
              {card.assignments.map((a) => (
                <tr key={a.id}>
                  <td>{a.scale_code}</td>
                  <td>{a.every_days ? `раз в ${a.every_days} дн.` : 'однократно'}</td>
                  <td>{formatDate(a.next_due)}</td>
                  <td>{a.reason ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <form className="form" onSubmit={onAssign}>
          <h3>Назначить шкалу</h3>
          <div className="row">
            <label>
              Шкала
              <select required value={form.scale_code} onChange={(e) => setForm({ ...form, scale_code: e.target.value })}>
                <option value="">— выберите —</option>
                {scales.map((s) => <option key={s.code} value={s.code}>{s.title}</option>)}
              </select>
            </label>
            <label>
              Повторять каждые, дней
              <input type="number" min={1} max={365} placeholder="однократно" value={form.every_days}
                     onChange={(e) => setForm({ ...form, every_days: e.target.value })} />
            </label>
          </div>
          <label>
            Причина
            <input maxLength={256} value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} />
          </label>
          <ErrorMessage error={assign.error} />
          <button type="submit" disabled={assign.pending}>Назначить</button>
        </form>
      </section>
    </>
  )
}
