import { useState, type FormEvent } from 'react'
import { api } from '../../../api/client'
import type { DrugAssessment, Recommendations } from '../../../api/types'
import { useAction, useApi } from '../../../api/useApi'
import { ErrorMessage } from '../../../components/ErrorMessage'
import { Loader } from '../../../components/Loader'
import { DRUG_STATUS_LABEL, formatDate, formatRegimen, LEVEL_LABEL } from '../../../format'
import { usePatient } from './PatientLayout'

const RX_STATUS: Record<string, string> = { active: 'Действует', paused: 'Приостановлено', stopped: 'Отменено' }

export function TherapyTab() {
  const { id, card, reload } = usePatient()
  const recs = useApi<Recommendations>(`/api/doctor/patients/${id}/recommendations`)
  const change = useAction((rid: number, action: 'stop' | 'pause' | 'resume') => api.post(`/api/doctor/prescriptions/${rid}`, { action }))

  const onChange = async (rid: number, action: 'stop' | 'pause' | 'resume') => {
    if (action === 'stop' && !window.confirm('Отменить назначение?')) return
    if (await change.run(rid, action)) reload()
  }

  const onPrescribed = () => {
    reload()
    recs.reload()
  }

  return (
    <>
      <section aria-labelledby="rx-h">
        <h2 id="rx-h">Назначения</h2>
        <ErrorMessage error={change.error} />
        {card.prescriptions.length === 0 ? <p>Назначений нет.</p> : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">Препарат</th>
                  <th scope="col">Режим</th>
                  <th scope="col">Статус</th>
                  <th scope="col">Начато</th>
                  <th scope="col"><span className="visually-hidden">Действия</span></th>
                </tr>
              </thead>
              <tbody>
                {card.prescriptions.map((r) => (
                  <tr key={r.id}>
                    <td>
                      {r.trade_name}
                      {r.off_label && <div><span className="badge badge-high">Вне инструкции</span></div>}
                    </td>
                    <td>{formatRegimen(r.regimen)}</td>
                    <td>{RX_STATUS[r.status] ?? r.status}</td>
                    <td>{formatDate(r.started_at)}</td>
                    <td className="nowrap">
                      {r.status === 'active' && (
                        <>
                          <button type="button" className="button-link" disabled={change.pending} onClick={() => onChange(r.id, 'pause')}>Приостановить</button>{' · '}
                          <button type="button" className="button-link" disabled={change.pending} onClick={() => onChange(r.id, 'stop')}>Отменить</button>
                        </>
                      )}
                      {r.status === 'paused' && (
                        <button type="button" className="button-link" disabled={change.pending} onClick={() => onChange(r.id, 'resume')}>Возобновить</button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section aria-labelledby="recs-h">
        <h2 id="recs-h">Рекомендации</h2>
        <p className="muted">По инструкциям к препаратам и клиническим рекомендациям Минздрава России. Назначение — только решением врача.</p>
        <Loader state={recs}>{(r) => <RecommendationsView id={id} data={r} onPrescribed={onPrescribed} />}</Loader>
      </section>
    </>
  )
}

function RecommendationsView({ id, data, onPrescribed }: { id: string; data: Recommendations; onPrescribed: () => void }) {
  const [selected, setSelected] = useState<string | null>(null)

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
              <th scope="col">Режим по инструкции</th>
              <th scope="col">Обоснование</th>
              <th scope="col"><span className="visually-hidden">Назначить</span></th>
            </tr>
          </thead>
          <tbody>
            {data.drugs.map((d) => (
              <tr key={d.drug_id}>
                <td>{d.trade_name}<div className="muted small">{d.inn}</div></td>
                <td><span className={`badge badge-drug-${d.status}`}>{DRUG_STATUS_LABEL[d.status]}</span></td>
                <td>{formatRegimen(d.regimen)}</td>
                <td className="small"><DrugReasons drug={d} /></td>
                <td>
                  <button type="button" className="secondary" onClick={() => setSelected(d.drug_id)}>Назначить…</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {selected && (
        <PrescribeForm id={id} drug={data.drugs.find((d) => d.drug_id === selected)!}
                       onCancel={() => setSelected(null)} onDone={() => { setSelected(null); onPrescribed() }} />
      )}
    </>
  )
}

function DrugReasons({ drug }: { drug: DrugAssessment }) {
  const findings = [
    ...drug.contraindications.map((f) => ({ kind: 'Противопоказание', ...f })),
    ...drug.interactions.map((f) => ({ kind: 'Взаимодействие', ...f })),
    ...drug.cautions.map((f) => ({ kind: 'С осторожностью', ...f })),
  ]
  return (
    <>
      <div>{drug.note}</div>
      {findings.length > 0 && (
        <details>
          <summary>Подробнее ({findings.length})</summary>
          <ul>
            {findings.map((f, i) => (
              <li key={i}>
                {f.kind}: {f.title ?? f.text}
                {f.source && <div className="muted">{f.source}</div>}
              </li>
            ))}
          </ul>
        </details>
      )}
    </>
  )
}

function PrescribeForm({ id, drug, onCancel, onDone }: {
  id: string
  drug: DrugAssessment
  onCancel: () => void
  onDone: () => void
}) {
  const [mode, setMode] = useState<'in_person' | 'remote'>('in_person')
  const [rationale, setRationale] = useState('')
  const [ack, setAck] = useState(false)
  const needsAck = drug.status !== 'indicated'
  const submit = useAction(() => api.post(`/api/doctor/patients/${id}/prescriptions`, {
    drug_id: drug.drug_id,
    mode,
    rationale: rationale.trim() || null,
    acknowledge_off_label: drug.status === 'off_label' && ack,
    acknowledge_contraindications: drug.status === 'contraindicated' && ack,
  }))

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault()
    if (await submit.run()) onDone()
  }

  return (
    <form className="form panel" onSubmit={onSubmit} aria-labelledby="prescribe-h">
      <h3 id="prescribe-h">Назначение: {drug.trade_name}</h3>
      <p>Режим по инструкции: {formatRegimen(drug.regimen)}</p>
      {needsAck && <p className={drug.status === 'contraindicated' ? 'message message-error' : 'message'}>{drug.note}</p>}
      <fieldset>
        <legend>Форма приёма</legend>
        <label className="radio">
          <input type="radio" name="mode" checked={mode === 'in_person'} onChange={() => setMode('in_person')} />
          Очный приём
        </label>
        <label className="radio">
          <input type="radio" name="mode" checked={mode === 'remote'} onChange={() => setMode('remote')} />
          Дистанционная коррекция (после очного приёма)
        </label>
      </fieldset>
      <label>
        Обоснование{needsAck ? ' (обязательно, не короче 20 символов)' : ''}
        <textarea rows={3} required={needsAck} minLength={needsAck ? 20 : undefined} maxLength={2000}
                  value={rationale} onChange={(e) => setRationale(e.target.value)} />
      </label>
      {needsAck && (
        <label className="checkbox">
          <input type="checkbox" required checked={ack} onChange={(e) => setAck(e.target.checked)} />
          {drug.status === 'contraindicated'
            ? 'Я ознакомлен(а) с противопоказаниями и принимаю решение о назначении'
            : 'Я принимаю решение о применении вне зарегистрированных показаний'}
        </label>
      )}
      <ErrorMessage error={submit.error} />
      <div className="row">
        <button type="submit" disabled={submit.pending}>Подтвердить назначение</button>
        <button type="button" className="secondary" onClick={onCancel}>Отмена</button>
      </div>
    </form>
  )
}
