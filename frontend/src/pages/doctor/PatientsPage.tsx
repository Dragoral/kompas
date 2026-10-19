import { useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import type { PatientRow } from '../../api/types'
import { useApi } from '../../api/useApi'
import { Loader } from '../../components/Loader'
import { LEVEL_LABEL } from '../../format'

export function PatientsPage() {
  const [params, setParams] = useSearchParams()
  const [q, setQ] = useState(params.get('q') ?? '')
  const state = useApi<PatientRow[]>(`/api/doctor/patients?${params}`)

  const onSearch = (e: FormEvent) => {
    e.preventDefault()
    const next = new URLSearchParams(params)
    if (q.trim()) next.set('q', q.trim())
    else next.delete('q')
    setParams(next)
  }

  const toggleAlerts = (checked: boolean) => {
    const next = new URLSearchParams(params)
    if (checked) next.set('only_alerts', 'true')
    else next.delete('only_alerts')
    setParams(next)
  }

  return (
    <>
      <h1>Мои пациенты</h1>
      <form className="toolbar" role="search" onSubmit={onSearch}>
        <label>
          Поиск
          <input type="search" placeholder="ФИО или код" value={q} onChange={(e) => setQ(e.target.value)} />
        </label>
        <button type="submit">Найти</button>
        <label className="checkbox">
          <input type="checkbox" checked={params.get('only_alerts') === 'true'}
                 onChange={(e) => toggleAlerts(e.target.checked)} />
          Только с оповещениями
        </label>
      </form>
      <Loader state={state}>
        {(rows) => rows.length === 0 ? <p>Пациентов не найдено.</p> : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">Пациент</th>
                  <th scope="col">Возраст</th>
                  <th scope="col">Диагноз</th>
                  <th scope="col">Терапия</th>
                  <th scope="col">Шкалы</th>
                  <th scope="col">Приверженность</th>
                  <th scope="col">Оповещения</th>
                  <th scope="col">Направление</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((p) => (
                  <tr key={p.id}>
                    <td>
                      <Link to={`/doctor/patients/${p.id}`}>{p.full_name}</Link>
                      <div className="muted small">{p.code}</div>
                    </td>
                    <td>{p.age ?? '—'}</td>
                    <td>{p.diagnoses.map((d) => d.icd10).join(', ') || '—'}</td>
                    <td>{p.therapy ?? '—'}</td>
                    <td className="small">
                      {Object.entries(p.scales).map(([code, s]) => (
                        <div key={code}>{code}: {s.score}{s.band ? ` (${s.band})` : ''}</div>
                      ))}
                    </td>
                    <td>{p.adherence_pct === null ? '—' : `${p.adherence_pct}%`}</td>
                    <td>
                      {p.alerts.critical ? <span className="badge badge-critical">Критических: {p.alerts.critical}</span> : null}
                      {p.alerts.high ? <span className="badge badge-high">Высоких: {p.alerts.high}</span> : null}
                      {p.alerts.medium ? <span className="badge badge-medium">Средних: {p.alerts.medium}</span> : null}
                    </td>
                    <td>
                      {p.referral && <span className={`badge badge-${p.referral}`}>{LEVEL_LABEL[p.referral]}</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Loader>
    </>
  )
}
