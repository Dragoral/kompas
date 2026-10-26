import { useApi } from '../../api/useApi'
import { Loader } from '../../components/Loader'
import { ErrorMessage } from '../../components/ErrorMessage'

type Percentiles = { n: number; p50_ms: number | null; p95_ms: number | null; max_ms: number }
interface MetricsData {
  requests: Record<string, Percentiles>
  errors: { '5xx': number; '4xx': number; total: number }
  alerts: { server_ms_p50: number | null; server_ms_p95: number | null; delivery_ms_p50: number | null; delivery_ms_p95: number | null; ack_s_median: number | null; n: number }
  recommendations_ms: { p50: number | null; p95: number | null; n: number }
  extraction: Record<string, unknown> | null
  backup_drill: Record<string, unknown> | null
  realtime_listeners: number
  db: { patients: number }
}
interface Health { status: string; uptime_s: number }
interface Readiness { status: string }
const ms = (v: number | null | undefined) => v === null || v === undefined ? 'Нет замеров' : `${v.toFixed(1)} мс`

export function MetricsPage() {
  const state = useApi<MetricsData>('/api/metrics')
  const health = useApi<Health>('/api/health')
  const ready = useApi<Readiness>('/api/ready')
  return <>
    <div className="page-heading"><div><h1>Технические метрики</h1><p className="page-lead">Время ответа API, доставка алертов, формирование рекомендаций и доступность инфраструктуры.</p></div><button type="button" className="secondary" onClick={() => { state.reload(); health.reload(); ready.reload() }}>Обновить замеры</button></div>
    <div className="patient-stat-grid"><div className="stat-card stat-card-teal"><span className="stat-label">API health</span><strong className="stat-value">{health.data?.status ?? (health.loading ? '…' : 'Ошибка')}</strong><span className="stat-note">Проверка доступности процесса</span></div><div className="stat-card"><span className="stat-label">Запросов в метриках</span><strong className="stat-value">{state.data?.errors.total ?? '—'}</strong><span className="stat-note">В рамках текущего процесса</span></div><div className="stat-card stat-card-attention"><span className="stat-label">Ошибки 5xx</span><strong className="stat-value">{state.data?.errors['5xx'] ?? '—'}</strong><span className="stat-note">Серверные ошибки</span></div><div className="stat-card stat-card-blue"><span className="stat-label">SSE подписчики</span><strong className="stat-value">{state.data?.realtime_listeners ?? '—'}</strong><span className="stat-note">Живые соединения в процессе</span></div></div>
    <ErrorMessage error={state.error} /><Loader state={state}>{(m) => <>
      <section className="feature-card"><h2>Проверка готовности</h2><p className="muted small">Health проверяет работающий процесс; readiness дополнительно проверяет инфраструктуру и фоновые задачи.</p><p><strong>Health:</strong> {health.data ? `OK · uptime ${Math.floor(health.data.uptime_s/60)} мин` : 'Недоступен'}</p><p><strong>Readiness:</strong> {ready.data?.status ?? (ready.loading ? 'Проверяется…' : ready.error ? `Не готов: ${ready.error.message}` : 'Неизвестно')}</p><p className="muted small">Подробная диагностика компонентов доступна только в защищённом разделе администратора «Состояние системы».</p></section>
      <section className="feature-card"><h2>Время ответа маршрутов</h2><div className="table-wrap"><table><thead><tr><th>Маршрут</th><th>Число запросов</th><th>P50</th><th>P95</th><th>Максимум</th></tr></thead><tbody>{Object.entries(m.requests).map(([route,v])=><tr key={route}><td><code>{route}</code></td><td>{v.n}</td><td>{ms(v.p50_ms)}</td><td>{ms(v.p95_ms)}</td><td>{ms(v.max_ms)}</td></tr>)}</tbody></table></div>{!Object.keys(m.requests).length&&<p className="muted">Замеров пока нет.</p>}</section>
      <section className="feature-card"><h2>Доставка и подтверждение алертов</h2><dl className="summary"><dt>Серверная обработка P50/P95</dt><dd>{ms(m.alerts.server_ms_p50)} / {ms(m.alerts.server_ms_p95)}</dd><dt>Доставка клиенту P50/P95</dt><dd>{ms(m.alerts.delivery_ms_p50)} / {ms(m.alerts.delivery_ms_p95)}</dd><dt>Медиана подтверждения</dt><dd>{m.alerts.ack_s_median===null?'Нет замеров':`${m.alerts.ack_s_median} с`}</dd><dt>Событий в выборке</dt><dd>{m.alerts.n}</dd></dl></section>
      <section className="feature-card"><h2>Формирование рекомендаций</h2><dl className="summary"><dt>P50</dt><dd>{ms(m.recommendations_ms.p50)}</dd><dt>P95</dt><dd>{ms(m.recommendations_ms.p95)}</dd><dt>Количество пациентов в замере</dt><dd>{m.recommendations_ms.n}</dd><dt>Пациентов в базе</dt><dd>{m.db.patients}</dd></dl></section>
      <div className="two-col"><section className="feature-card"><h2>Оценка извлечения документов</h2><pre className="plain-text">{m.extraction?JSON.stringify(m.extraction,null,2):'Нет файла data/extraction_eval.json. Метрика ещё не измерена.'}</pre></section><section className="feature-card"><h2>Тест восстановления резервной копии</h2><pre className="plain-text">{m.backup_drill?JSON.stringify(m.backup_drill,null,2):'Нет data/backup_drill.json. Учение по восстановлению не зарегистрировано.'}</pre></section></div>
    </>}</Loader>
  </>
}
