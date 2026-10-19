import { useEffect } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../api/client'
import { subscribe } from '../../api/stream'
import type { Alert } from '../../api/types'
import { useAction, useApi } from '../../api/useApi'
import { ErrorMessage } from '../../components/ErrorMessage'
import { Loader } from '../../components/Loader'
import { formatDateTime, SEVERITY_LABEL } from '../../format'

export function AlertsPage() {
  const state = useApi<Alert[]>('/api/doctor/alerts?status=open')
  const { reload } = state
  const ack = useAction((id: number) => api.post(`/api/doctor/alerts/${id}/ack`))

  useEffect(() => subscribe('/api/doctor/stream', ['alert'], reload), [reload])

  const onAck = async (id: number) => {
    await ack.run(id)
    reload()
  }

  return (
    <>
      <h1>Оповещения</h1>
      <p className="muted">Список обновляется автоматически при появлении новых оповещений.</p>
      <ErrorMessage error={ack.error} />
      <Loader state={state}>
        {(alerts) => alerts.length === 0 ? <p>Открытых оповещений нет.</p> : (
          <AlertTable alerts={alerts} onAck={onAck} pending={ack.pending} showPatient />
        )}
      </Loader>
    </>
  )
}

export function AlertTable({ alerts, onAck, pending, showPatient = false }: {
  alerts: Alert[]
  onAck: (id: number) => void
  pending: boolean
  showPatient?: boolean
}) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th scope="col">Уровень</th>
            {showPatient && <th scope="col">Пациент</th>}
            <th scope="col">Оповещение</th>
            <th scope="col">Создано</th>
            <th scope="col">Статус</th>
            <th scope="col"><span className="visually-hidden">Действия</span></th>
          </tr>
        </thead>
        <tbody>
          {alerts.map((a) => (
            <tr key={a.id} className={`row-${a.severity}`}>
              <td><span className={`badge badge-${a.severity}`}>{SEVERITY_LABEL[a.severity]}</span></td>
              {showPatient && (
                <td><Link to={`/doctor/patients/${a.patient_id}`}>{a.patient_name ?? `#${a.patient_id}`}</Link></td>
              )}
              <td>
                <strong>{a.title}</strong>
                {a.message && <div className="small">{a.message}</div>}
              </td>
              <td>{formatDateTime(a.created_at)}</td>
              <td>{a.acknowledged_at ? 'Принято' : 'Новое'}</td>
              <td>
                {!a.acknowledged_at && a.status !== 'resolved' && (
                  <button type="button" disabled={pending} onClick={() => onAck(a.id)}>Принять</button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
