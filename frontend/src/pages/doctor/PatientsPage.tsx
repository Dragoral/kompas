import { useEffect, useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import type { PatientRow } from '../../api/types'
import { useApi } from '../../api/useApi'
import { Loader } from '../../components/Loader'
import { LEVEL_LABEL } from '../../format'

type PatientView = 'all' | 'monitoring' | 'attention' | 'mandatory'

function StatCard({ label, value, hint, tone = 'neutral', active = false, attentionActive = false, onClick }: {
  label: string
  value: number | string
  hint: string
  tone?: 'neutral' | 'danger' | 'teal' | 'gold'
  active?: boolean
  attentionActive?: boolean
  onClick: () => void
}) {
  return <button type="button" className={`stat-card stat-card-button stat-card-${tone}${active ? ' stat-card-selected' : ''}${attentionActive ? ' stat-card-attention-active' : ''}`} onClick={onClick} aria-pressed={active}>
    <span className="stat-card-label">{label}</span><strong className="stat-card-value">{value}</strong><span className="stat-card-hint">{hint}</span>
    <span className="stat-card-action">{active ? 'Открыт этот список' : 'Открыть список →'}</span>
  </button>
}

export function PatientsPage() {
  const [params, setParams] = useSearchParams()
  const [q, setQ] = useState(params.get('q') ?? '')
  const requestedView = params.get('view')
  const view: PatientView = requestedView === 'monitoring' || requestedView === 'attention' || requestedView === 'mandatory' ? requestedView : 'all'
  const apiParams = new URLSearchParams(params)
  apiParams.delete('view')
  apiParams.set('limit', '1000')
  if (view === 'attention') apiParams.set('needs_attention', 'true')
  else if (view === 'monitoring') apiParams.set('monitoring', 'true')
  else if (view === 'mandatory') apiParams.set('referral', 'mandatory')
  const state = useApi<PatientRow[]>(`/api/doctor/patients?${apiParams.toString()}`)
  const summaryParams = new URLSearchParams()
  summaryParams.set('limit', '1000')
  if (params.get('q')) summaryParams.set('q', params.get('q') as string)
  if (params.get('only_alerts') === 'true') summaryParams.set('only_alerts', 'true')
  const summaryState = useApi<PatientRow[]>(`/api/doctor/patients?${summaryParams.toString()}`)

  useEffect(() => { setQ(params.get('q') ?? '') }, [params])

  const setView = (nextView: PatientView) => {
    const next = new URLSearchParams(params)
    if (nextView === 'all') next.delete('view')
    else next.set('view', nextView)
    setParams(next)
  }

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
      <div className="page-heading-row">
        <div><div className="page-eyebrow">КЛИНИЧЕСКАЯ РАБОТА</div><h1>Мои пациенты</h1><p className="page-lead">Обзор наблюдения, текущих сигналов и динамики состояния пациентов.</p></div>
        <Link className="button-anchor" to="/doctor/patients/new"><span aria-hidden="true">＋</span> Добавить пациента</Link>
      </div>
      <form className="toolbar patient-toolbar" role="search" onSubmit={onSearch}>
        <label className="patient-search-field">
          <span>Поиск пациента</span>
          <input type="search" placeholder="Введите ФИО или код пациента" value={q} onChange={(e) => setQ(e.target.value)} />
        </label>
        <div className="patient-toolbar-actions">
          <button type="submit">Найти</button>
          <label className="checkbox patient-alert-filter">
            <input type="checkbox" checked={params.get('only_alerts') === 'true'} onChange={(e) => toggleAlerts(e.target.checked)} />
            <span>Только с оповещениями</span>
          </label>
        </div>
      </form>
      <Loader state={state}>
        {(rows) => {
          const summaryRows = summaryState.data ?? rows
          const critical = summaryRows.reduce((sum, p) => sum + (p.alerts.critical ?? 0), 0)
          const high = summaryRows.reduce((sum, p) => sum + (p.alerts.high ?? 0), 0)
          const monitored = summaryRows.filter((p) => p.monitoring_active).length
          const mandatory = summaryRows.filter((p) => p.referral === 'mandatory').length
          const attention = summaryRows.filter((p) => (p.alerts.critical ?? 0) > 0 || (p.alerts.high ?? 0) > 0 || p.referral === 'mandatory' || p.pending_actions > 0).length
          const visibleRows = rows
          const viewTitle: Record<PatientView, string> = {
            all: 'Все пациенты',
            monitoring: 'Пациенты на активном наблюдении',
            attention: 'Пациенты, требующие внимания',
            mandatory: 'Пациенты с обязательной маршрутизацией',
          }
          return <>
            <section className="stats-grid" aria-label="Сводные показатели. Нажмите карточку, чтобы открыть соответствующий список">
              <StatCard label="Пациентов в списке" value={summaryRows.length} hint="По текущему поиску" tone="neutral" active={view === 'all'} onClick={() => setView('all')}/>
              <StatCard label="Активное наблюдение" value={monitored} hint={`${summaryRows.length ? Math.round(monitored / summaryRows.length * 100) : 0}% от списка`} tone="teal" active={view === 'monitoring'} onClick={() => setView('monitoring')}/>
              <StatCard label="Требуют внимания" value={attention} hint={`${critical} критических · ${high} высоких сигналов`} tone={attention ? 'danger' : 'neutral'} active={view === 'attention'} attentionActive={attention > 0} onClick={() => setView('attention')}/>
              <StatCard label="Обязательная маршрутизация" value={mandatory} hint="Требует врачебного подтверждения" tone={mandatory ? 'gold' : 'neutral'} active={view === 'mandatory'} onClick={() => setView('mandatory')}/>
            </section>
            <div className="section-heading-row"><div><h2>{viewTitle[view]}</h2></div><span className="record-count">{visibleRows.length} записей</span></div>
            {visibleRows.length === 0 ? <div className="empty-state"><div className="empty-state-icon">⌕</div><h3>В этой категории пациентов нет</h3><p>Выберите другую карточку или измените поисковый запрос.</p>{(q || params.has('only_alerts') || view !== 'all') && <button type="button" className="secondary" onClick={() => { setQ(''); setParams({}) }}>Сбросить фильтры</button>}</div> : (
              <div className="table-wrap patient-table-wrap">
                <table>
                  <thead><tr>
                    <th scope="col">Пациент</th><th scope="col">Возраст</th><th scope="col">Диагноз</th><th scope="col">Терапия</th><th scope="col">Шкалы</th><th scope="col">Приверженность</th><th scope="col">Оповещения</th><th scope="col">Маршрутизация</th>
                  </tr></thead>
                  <tbody>{visibleRows.map((p) => (
                    <tr key={p.id}>
                      <td><Link className="patient-name-link" to={`/doctor/patients/${p.id}`}>{p.full_name}</Link><div className="muted small patient-code">{p.code}</div></td>
                      <td>{p.age ?? '—'}</td>
                      <td>{p.diagnoses.map((d) => d.icd10).join(', ') || '—'}</td>
                      <td>{p.therapy ?? '—'}</td>
                      <td className="small patient-scales">{Object.entries(p.scales).length ? Object.entries(p.scales).map(([code, s]) => <div key={code}><span>{code}</span><strong>{s.score}</strong>{s.band ? <small>{s.band}</small> : null}</div>) : 'Нет данных'}</td>
                      <td>{p.adherence_pct === null ? '—' : <span className={`adherence-value ${p.adherence_pct < 60 ? 'adherence-low' : p.adherence_pct >= 80 ? 'adherence-good' : ''}`}>{p.adherence_pct}%</span>}</td>
                      <td className="patient-alerts-cell">
                        {p.alerts.critical ? <span className="badge badge-critical">Крит.: {p.alerts.critical}</span> : null}
                        {p.alerts.high ? <span className="badge badge-high">Высокие: {p.alerts.high}</span> : null}
                        {p.alerts.medium ? <span className="badge badge-medium">Средние: {p.alerts.medium}</span> : null}
                        {!p.alerts.critical && !p.alerts.high && !p.alerts.medium && <span className="muted">Нет</span>}
                      </td>
                      <td>{p.referral ? <span className={`badge badge-${p.referral}`}>{LEVEL_LABEL[p.referral]}</span> : <span className="muted">—</span>}</td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            )}
          </>
        }}
      </Loader>
    </>
  )
}
