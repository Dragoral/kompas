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

  return (
    <>
      <h1>Пациенты</h1>
      <p className="muted">Для администрирования показаны только коды пациентов и лечащие врачи.</p>
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
      <h2 id="reassign-h">Смена лечащего врача: {patient.code}</h2>
      <p className="muted">Данные пациента станут доступны новому врачу и перестанут быть доступны прежнему. Действие записывается в журнал аудита.</p>
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
        <button type="submit" disabled={save.pending}>Сменить</button>
        <button type="button" className="secondary" onClick={onCancel}>Отмена</button>
      </div>
    </form>
  )
}
