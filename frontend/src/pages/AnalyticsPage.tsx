import { useState } from 'react'
import { useApi } from '../api/useApi'
import { Loader } from '../components/Loader'
import { ErrorMessage } from '../components/ErrorMessage'

type Cell = number | string
interface AnalyticsSummary {
  period_days: number
  k_anonymity: number
  note: string
  patients_total: Cell
  patients_by_diagnosis: Record<string, Cell>
  therapy: { drug: string; patients: Cell; response_rate_pct: number | null; response_definition: string }[]
  adherence_median_pct: number | null
  adverse_events: { drug: string; total: Cell; serious: Cell; unexpected: Cell }[]
  alerts_by_type: Record<string, Cell>
  alert_ack_median_min: number | null
}

export function AnalyticsPage() {
  const [days, setDays] = useState(90)
  const [k, setK] = useState(5)
  const state = useApi<AnalyticsSummary>(`/api/analytics/summary?days=${days}&k=${k}`)
  return <>
    <div className="page-heading"><div><h1>Клиническая аналитика</h1><p className="page-lead">Только обезличенные агрегаты. Малые группы подавляются для снижения риска повторной идентификации.</p></div><button className="secondary" type="button" onClick={state.reload}>Обновить</button></div>
    <div className="filter-toolbar"><label>Период<select value={days} onChange={(e) => setDays(Number(e.target.value))}><option value={7}>7 дней</option><option value={30}>30 дней</option><option value={90}>90 дней</option><option value={180}>180 дней</option><option value={365}>365 дней</option></select></label><label>Порог k-анонимности<select value={k} onChange={(e) => setK(Number(e.target.value))}><option value={5}>k = 5</option><option value={10}>k = 10</option><option value={20}>k = 20</option></select></label></div>
    <Loader state={state}>{(d) => <>
      <p className="message">{d.note}. Период: {d.period_days} дней; порог k = {d.k_anonymity}.</p>
      <div className="patient-stat-grid"><div className="stat-card"><span className="stat-label">Пациенты</span><strong className="stat-value">{d.patients_total}</strong><span className="stat-note">Общий размер когорты</span></div><div className="stat-card stat-card-teal"><span className="stat-label">Медиана приверженности</span><strong className="stat-value">{d.adherence_median_pct === null ? 'Подавлено' : `${d.adherence_median_pct}%`}</strong><span className="stat-note">За последние 14 дней</span></div><div className="stat-card stat-card-blue"><span className="stat-label">Медиана подтверждения алерта</span><strong className="stat-value">{d.alert_ack_median_min === null ? 'Подавлено' : `${d.alert_ack_median_min} мин`}</strong><span className="stat-note">Только события с подтверждением</span></div></div>
      <section className="feature-card"><h2>Пациенты по группам диагнозов</h2><table><thead><tr><th>Группа</th><th>Количество</th></tr></thead><tbody>{Object.entries(d.patients_by_diagnosis).map(([name,value])=><tr key={name}><td>{name}</td><td>{value}</td></tr>)}</tbody></table></section>
      <section className="feature-card"><h2>Агрегаты по терапии</h2><div className="table-wrap"><table><thead><tr><th>Препарат</th><th>Пациенты</th><th>Доля ответивших</th><th>Определение ответа</th></tr></thead><tbody>{d.therapy.map((x,i)=><tr key={`${x.drug}-${i}`}><td>{x.drug}</td><td>{x.patients}</td><td>{x.response_rate_pct===null?'Недостаточно наблюдений':`${x.response_rate_pct}%`}</td><td>{x.response_definition}</td></tr>)}</tbody></table></div></section>
      <section className="feature-card"><h2>Нежелательные реакции</h2><div className="table-wrap"><table><thead><tr><th>Препарат</th><th>Всего</th><th>Серьёзные</th><th>Неожиданные</th></tr></thead><tbody>{d.adverse_events.map((x,i)=><tr key={`${x.drug}-${i}`}><td>{x.drug}</td><td>{x.total}</td><td>{x.serious}</td><td>{x.unexpected}</td></tr>)}</tbody></table></div></section>
      <section className="feature-card"><h2>Оповещения по типам</h2><table><thead><tr><th>Тип</th><th>Количество</th></tr></thead><tbody>{Object.entries(d.alerts_by_type).map(([name,value])=><tr key={name}><td>{name}</td><td>{value}</td></tr>)}</tbody></table></section>
      
    </>}</Loader>
    {state.error && <ErrorMessage error={state.error} />}
  </>
}
