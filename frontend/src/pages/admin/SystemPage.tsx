import type { SystemStatus } from '../../api/types'
import { useApi } from '../../api/useApi'
import { Loader } from '../../components/Loader'
import { formatDateTime } from '../../format'

const QUEUE_LABEL: Record<string, string> = {
  events_backlog: 'Недоставленные события',
  notifications_pending: 'Уведомления в очереди',
  notifications_failed: 'Уведомления с ошибкой',
}

export function SystemPage() {
  const state = useApi<SystemStatus>('/api/admin/system')
  const health = useApi<{ status: string; uptime_s: number }>('/api/health')
  const ready = useApi<{ status: string }>('/api/ready')

  return (
    <>
      <h1>Состояние системы</h1>
      <p className="row"><button type="button" className="secondary" onClick={() => { state.reload(); health.reload(); ready.reload() }}>Обновить</button><span className="muted small">Process health: {health.data?.status ?? (health.error ? 'ошибка' : 'проверка…')} · Readiness: {ready.data?.status ?? (ready.error ? 'не готов' : 'проверка…')}</span></p>
      <Loader state={state}>
        {(s) => (
          <>
            <dl className="summary">
              <dt>Окружение</dt><dd>{s.environment}</dd>
              <dt>База данных</dt><dd>{s.database}</dd>
              <dt>Работает</dt><dd>{Math.floor(s.uptime_s / 3600)} ч {Math.floor((s.uptime_s % 3600) / 60)} мин</dd>
              <dt>Черновики справочников</dt><dd>{s.knowledge_drafts_pending}</dd>
              <dt>Резервные копии</dt><dd>{s.backups.count}{s.backups.latest ? `, последняя ${s.backups.latest}` : ''}</dd>
              <dt>Проверено</dt><dd>{formatDateTime(s.checked_at)}</dd>
            </dl>

            <h2>Компоненты</h2>
            <table>
              <thead><tr><th scope="col">Компонент</th><th scope="col">Состояние</th></tr></thead>
              <tbody>
                {Object.entries(s.checks).map(([name, c]) => (
                  <tr key={name}>
                    <td>{name}</td>
                    <td>{c.ok ? 'Работает' : <span className="badge badge-critical">Сбой</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>

            <h2>Очереди</h2>
            <table>
              <tbody>
                {Object.entries(s.queues).map(([name, n]) => (
                  <tr key={name}><th scope="row">{QUEUE_LABEL[name] ?? name}</th><td>{n}</td></tr>
                ))}
              </tbody>
            </table>

            <h2>Последние проблемы</h2>
            {s.problems.length === 0 ? <p>Проблем не зафиксировано.</p> : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th scope="col">Время</th>
                      <th scope="col">Компонент</th>
                      <th scope="col">Объект</th>
                      <th scope="col">Ошибка</th>
                      <th scope="col">Номер запроса</th>
                    </tr>
                  </thead>
                  <tbody>
                    {s.problems.map((p, i) => (
                      <tr key={i}>
                        <td>{formatDateTime(new Date(p.ts * 1000).toISOString())}</td>
                        <td>{p.component}</td>
                        <td><code>{p.ref}</code></td>
                        <td>{p.error}</td>
                        <td className="small">{p.request_id ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </Loader>
    </>
  )
}
