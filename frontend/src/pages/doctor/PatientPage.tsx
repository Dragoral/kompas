import { useParams } from 'react-router-dom'
import { api } from '../../api/client'
import type { PatientCard, Recommendations } from '../../api/types'
import { useAction, useApi } from '../../api/useApi'
import { ErrorMessage } from '../../components/ErrorMessage'
import { Loader } from '../../components/Loader'
import { DRUG_STATUS_LABEL, formatDate, formatRegimen, LEVEL_LABEL } from '../../format'
import { AlertTable } from './AlertsPage'

export function PatientPage() {
  const { id } = useParams()
  const card = useApi<PatientCard>(`/api/doctor/patients/${id}`)
  const recs = useApi<Recommendations>(`/api/doctor/patients/${id}/recommendations`)
  const ack = useAction((aid: number) => api.post(`/api/doctor/alerts/${aid}/ack`))

  const onAck = async (aid: number) => {
    await ack.run(aid)
    card.reload()
  }

  return (
    <Loader state={card}>
      {(c) => (
        <>
          <h1>{c.header.full_name}</h1>
          <dl className="summary">
            <dt>Код</dt><dd>{c.patient.code}</dd>
            <dt>Возраст</dt><dd>{c.header.age ?? '—'}</dd>
            <dt>ИМТ</dt><dd>{c.header.bmi ?? '—'}</dd>
            <dt>Диагнозы</dt>
            <dd>{c.header.diagnoses.map((d) => `${d.icd10}${d.title ? ` ${d.title}` : ''}`).join('; ') || '—'}</dd>
            <dt>Препараты</dt>
            <dd>{c.header.medications.map((m) => [m.name, m.regimen ? formatRegimen(m.regimen) : m.dose].filter(Boolean).join(', ')).join('; ') || '—'}</dd>
            <dt>Аллергии</dt><dd>{c.header.allergies.join(', ') || 'нет данных'}</dd>
            <dt>Наблюдение</dt><dd>{c.patient.monitoring_active ? 'Дистанционное наблюдение назначено' : 'Не назначено'}</dd>
            <dt>Приверженность (14 дней)</dt>
            <dd>{c.context.adherence.pct_14d === null ? '—' : `${c.context.adherence.pct_14d}%`}</dd>
          </dl>

          <section aria-labelledby="alerts-h">
            <h2 id="alerts-h">Оповещения</h2>
            <ErrorMessage error={ack.error} />
            {c.alerts.length === 0 ? <p>Оповещений нет.</p> : (
              <AlertTable alerts={c.alerts.filter((a) => a.status !== 'resolved')} onAck={onAck} pending={ack.pending} />
            )}
          </section>

          <section aria-labelledby="scales-h">
            <h2 id="scales-h">Шкалы</h2>
            {Object.keys(c.context.scales).length === 0 ? <p>Результатов нет.</p> : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th scope="col">Шкала</th>
                      <th scope="col">Балл</th>
                      <th scope="col">Интерпретация</th>
                      <th scope="col">Изменение</th>
                      <th scope="col">Дней назад</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(c.context.scales).map(([code, s]) => (
                      <tr key={code}>
                        <td>{code}</td>
                        <td>{s.score}</td>
                        <td>{s.band ?? '—'}</td>
                        <td>{s.delta === null ? '—' : s.delta > 0 ? `+${s.delta}` : s.delta}</td>
                        <td>{s.days_ago ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section aria-labelledby="rx-h">
            <h2 id="rx-h">Назначения</h2>
            {c.prescriptions.length === 0 ? <p>Назначений нет.</p> : (
              <ul>
                {c.prescriptions.map((r) => (
                  <li key={r.id}>
                    {r.trade_name}{r.regimen ? `, ${formatRegimen(r.regimen)}` : ''} — {r.status === 'active' ? 'действует' : 'отменено'} с {formatDate(r.started_at)}
                    {r.off_label && <span className="badge badge-high">Вне инструкции</span>}
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section aria-labelledby="recs-h">
            <h2 id="recs-h">Рекомендации</h2>
            <p className="muted">Решение о назначении и направлении принимает врач.</p>
            <Loader state={recs}>{(r) => <RecommendationsView data={r} />}</Loader>
          </section>
        </>
      )}
    </Loader>
  )
}

function RecommendationsView({ data }: { data: Recommendations }) {
  return (
    <>
      {data.routing && (
        <>
          <h3>Маршрутизация</h3>
          <ul className="plain">
            {data.routing.routes.map((route) => (
              <li key={route.target} className={route.level ? `route route-${route.level}` : 'route'}>
                <strong>{route.title}</strong>
                {route.level && <span className={`badge badge-${route.level}`}>{LEVEL_LABEL[route.level]}</span>}
                {route.reasons.length > 0 && (
                  <ul>
                    {route.reasons.map((x) => (
                      <li key={x.id}>{x.title}{x.source && <span className="muted small"> — {x.source}</span>}</li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        </>
      )}

      <h3>Препараты</h3>
      {data.guidelines_note && <p className="message">{data.guidelines_note}</p>}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th scope="col">Препарат</th>
              <th scope="col">Статус</th>
              <th scope="col">Режим</th>
              <th scope="col">Противопоказания, предостережения, взаимодействия</th>
            </tr>
          </thead>
          <tbody>
            {data.drugs.map((d) => (
              <tr key={d.drug_id}>
                <td>{d.trade_name}<div className="muted small">{d.inn}</div></td>
                <td><span className={`badge badge-drug-${d.status}`}>{DRUG_STATUS_LABEL[d.status]}</span></td>
                <td>{formatRegimen(d.regimen)}</td>
                <td className="small">
                  {[...d.contraindications, ...d.interactions, ...d.cautions].map((f, i) => (
                    <div key={i}>{f.title ?? f.text}</div>
                  ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}
