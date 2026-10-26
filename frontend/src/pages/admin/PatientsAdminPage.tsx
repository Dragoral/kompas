import { useState } from 'react'
import { api } from '../../api/client'
import type { StaffUser } from '../../api/types'
import { useAction, useApi } from '../../api/useApi'
import { ErrorMessage } from '../../components/ErrorMessage'
import { Loader } from '../../components/Loader'

interface PatientRow {
  id: number
  code: string
  doctor_id: number
  doctor_name: string | null
  monitoring_active: boolean
}

/** Смена лечащего врача. Администратор видит только код пациента и врача — без медицинских данных. */
export function PatientsAdminPage() {
  const state = useApi<PatientRow[]>('/api/admin/patients')
  const doctors = useApi<StaffUser[]>('/api/admin/users?role=doctor')
  const [editing, setEditing] = useState<PatientRow | null>(null)
  const requests = useApi<ReassignmentRow[]>('/api/admin/attending-requests')

  return (
    <>
      <h1>Пациенты</h1>
      <p className="muted">Для администрирования показаны только коды пациентов и лечащие врачи. Смена врача применяется после подтверждения другим администратором.</p>
      <section aria-labelledby="reassign-requests-h">
        <h2 id="reassign-requests-h">Запросы на смену врача</h2>
        <Loader state={requests}>
          {(items) => items.length === 0 ? <p>Нет запросов, ожидающих подтверждения.</p> : (
            <div className="table-wrap"><table>
              <thead><tr><th scope="col">Пациент</th><th scope="col">Было</th><th scope="col">Станет</th><th scope="col">Запросил</th><th scope="col">Причина</th><th scope="col">Действия</th></tr></thead>
              <tbody>{items.map((item) => <ReassignmentReviewRow key={item.id} item={item} onDone={() => { requests.reload(); state.reload() }} />)}</tbody>
            </table></div>
          )}
        </Loader>
      </section>
      <Loader state={state}>
        {(rows) => (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">Код</th>
                  <th scope="col">Лечащий врач</th>
                  <th scope="col">Наблюдение</th>
                  <th scope="col"><span className="visually-hidden">Действия</span></th>
                </tr>
              </thead>
              <tbody>
                {rows.map((p) => (
                  <tr key={p.id}>
                    <td>{p.code}</td>
                    <td>{p.doctor_name ?? '—'}</td>
                    <td>{p.monitoring_active ? 'Назначено' : 'Нет'}</td>
                    <td><button type="button" className="button-link" onClick={() => setEditing(p)}>Сменить врача</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Loader>
      {editing && (
        <ReassignForm patient={editing} doctors={(doctors.data ?? []).filter((d) => d.active)}
                      onDone={() => { setEditing(null); state.reload() }} onCancel={() => setEditing(null)} />
      )}
    </>
  )
}

function ReassignForm({ patient, doctors, onDone, onCancel }: {
  patient: PatientRow
  doctors: StaffUser[]
  onDone: () => void
  onCancel: () => void
}) {
  const [doctorId, setDoctorId] = useState('')
  const [reason, setReason] = useState('')
  const save = useAction(() => api.post(`/api/admin/patients/${patient.id}/attending`, { doctor_id: Number(doctorId), reason }))

  return (
    <form className="form panel" aria-labelledby="reassign-h" onSubmit={async (e) => { e.preventDefault(); if (await save.run()) onDone() }}>
      <h2 id="reassign-h">Запрос смены лечащего врача: {patient.code}</h2>
      <p className="muted">Запрос отправится на подтверждение второму администратору. Смена не вступит в силу сразу.</p>
      <p className="muted">Причина будет сохранена в журнале аудита.</p>
      <label>
        Новый лечащий врач
        <select required value={doctorId} onChange={(e) => setDoctorId(e.target.value)}>
          <option value="">— выберите —</option>
          {doctors.filter((d) => d.id !== patient.doctor_id).map((d) => <option key={d.id} value={d.id}>{d.full_name}</option>)}
        </select>
      </label>
      <label>
        Причина
        <input required minLength={5} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} />
      </label>
      <ErrorMessage error={save.error} />
      <div className="row">
        <button type="submit" disabled={save.pending}>Отправить запрос</button>
        <button type="button" className="secondary" onClick={onCancel}>Отмена</button>
      </div>
    </form>
  )
}


interface ReassignmentRow {
  id: number
  patient_id: number
  patient_code: string
  from_doctor_name: string | null
  to_doctor_name: string | null
  requested_by: number
  requested_by_name: string | null
  reason: string
  created_at: string
}

function ReassignmentReviewRow({ item, onDone }: { item: ReassignmentRow; onDone: () => void }) {
  const [comment, setComment] = useState('')
  const approve = useAction(() => api.post(`/api/admin/attending-requests/${item.id}/approve`, { comment }))
  const reject = useAction(() => api.post(`/api/admin/attending-requests/${item.id}/reject`, { comment }))
  const run = async (decision: 'approve' | 'reject') => {
    const action = decision === 'approve' ? approve : reject
    if (await action.run()) onDone()
  }
  return <tr>
    <td>{item.patient_code}</td><td>{item.from_doctor_name ?? '—'}</td><td>{item.to_doctor_name ?? '—'}</td>
    <td>{item.requested_by_name ?? `ID ${item.requested_by}`}</td><td>{item.reason}</td>
    <td>
      <label className="small">Комментарий решения<input maxLength={1000} value={comment} onChange={(e) => setComment(e.target.value)} /></label>
      <ErrorMessage error={approve.error ?? reject.error} />
      <div className="row"><button type="button" disabled={approve.pending || reject.pending} onClick={() => run('approve')}>Подтвердить</button>
      <button type="button" className="secondary" disabled={approve.pending || reject.pending} onClick={() => run('reject')}>Отклонить</button></div>
    </td>
  </tr>
}
