import { useState } from 'react'
import { useApi } from '../../api/useApi'
import { Loader } from '../../components/Loader'
import { formatDateTime } from '../../format'

interface NotificationRow {
  id: number
  channel: 'sms' | 'push' | 'call'
  reason: string | null
  recipient: string
  phone: string | null
  text: string | null
  status: 'pending' | 'sent' | 'failed'
  attempts: number
  provider: string | null
  alert_id: number | null
  created_at: string
  sent_at: string | null
  error: string | null
}

const STATUS: Record<string, string> = { pending: 'В очереди', sent: 'Отправлено', failed: 'Не доставлено' }
const CHANNEL: Record<string, string> = { sms: 'SMS', push: 'Push', call: 'Звонок' }

/** Журнал внешних уведомлений: кому, каким каналом, отправлено ли (193н п. 46 «д»). */
export function NotificationsPage() {
  const [channel, setChannel] = useState('')
  const [status, setStatus] = useState('')
  const qs = new URLSearchParams()
  if (channel) qs.set('channel', channel)
  if (status) qs.set('status', status)
  const state = useApi<NotificationRow[]>(`/api/admin/notifications?${qs}`)

  return (
    <>
      <h1>Журнал уведомлений</h1>
      <p className="muted">
        SMS и push по оповещениям и напоминаниям. Номера телефонов скрыты; текст доверенному лицу не показывается — в нём имя пациента.
        Провайдер <code>log</code> — тестовый режим: сообщение только записывается в журнал сервера, реальная отправка не выполняется.
      </p>
      <div className="toolbar">
        <label>
          Канал
          <select value={channel} onChange={(e) => setChannel(e.target.value)}>
            <option value="">все</option>
            <option value="sms">SMS</option>
            <option value="push">Push</option>
          </select>
        </label>
        <label>
          Статус
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">все</option>
            <option value="pending">в очереди</option>
            <option value="sent">отправлено</option>
            <option value="failed">не доставлено</option>
          </select>
        </label>
        <button type="button" className="secondary" onClick={state.reload}>Обновить</button>
      </div>
      <Loader state={state}>
        {(rows) => rows.length === 0 ? <p>Уведомлений нет.</p> : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">Создано</th>
                  <th scope="col">Канал</th>
                  <th scope="col">Получатель</th>
                  <th scope="col">Текст</th>
                  <th scope="col">Статус</th>
                  <th scope="col">Отправлено</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((n) => (
                  <tr key={n.id}>
                    <td className="nowrap">{formatDateTime(n.created_at)}</td>
                    <td>{CHANNEL[n.channel] ?? n.channel}</td>
                    <td>
                      {n.recipient}
                      {n.reason && n.reason !== n.recipient && <div className="muted small">{n.reason}</div>}
                      {n.phone && <div className="muted small">{n.phone}</div>}
                    </td>
                    <td className="small">{n.text ?? <span className="muted">скрыт</span>}</td>
                    <td>
                      <span className={`badge ${n.status === 'failed' ? 'badge-critical' : n.status === 'pending' ? 'badge-high' : 'badge-medium'}`}>
                        {STATUS[n.status] ?? n.status}
                      </span>
                      {n.provider && <div className="muted small">через {n.provider}, попыток: {n.attempts}</div>}
                      {n.error && <div className="small">{n.error}</div>}
                    </td>
                    <td className="nowrap">{formatDateTime(n.sent_at)}</td>
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
