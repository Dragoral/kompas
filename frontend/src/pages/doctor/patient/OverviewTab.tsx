import { useState } from 'react'
import { api } from '../../../api/client'
import type { Alert, ClinicalAction } from '../../../api/types'
import { useAction } from '../../../api/useApi'
import { ErrorMessage } from '../../../components/ErrorMessage'
import { formatDateTime, LEVEL_LABEL, SEVERITY_LABEL } from '../../../format'
import { usePatient } from './PatientLayout'
import { VisitsHistory } from './VisitsHistory'

export function OverviewTab() {
  const { id, card, reload } = usePatient()
  const visit = useAction(() => api.post(`/api/doctor/patients/${id}/visit`))
  const monitoring = useAction((active: boolean) => api.post(`/api/doctor/patients/${id}/monitoring`, { active }))
  const resetPatientPassword = useAction(() => api.post<{ temporary_password: string }>(`/api/doctor/patients/${id}/reset-patient-password`))
  const reviewAdverseEvent = useAction((eventId: number) => api.post(`/api/doctor/adverse-events/${eventId}/review`))
  const [temporaryPassword, setTemporaryPassword] = useState<string | null>(null)

  const openAlerts = card.alerts.filter((a) => a.status !== 'resolved')
  const proposed = card.actions.filter((a) => a.status === 'proposed')

  return (
    <>
      <Summary id={id} />
      <VisitsHistory patientId={id} onCreated={reload} />
      <section aria-labelledby="alerts-h">
        <h2 id="alerts-h">Оповещения</h2>
        {openAlerts.length === 0 ? <p>Открытых оповещений нет.</p> : openAlerts.map((a) => (
          <AlertItem key={a.id} alert={a} onChange={reload} />
        ))}
      </section>

      <section aria-labelledby="actions-h">
        <h2 id="actions-h">Предложения системы</h2>
        <p className="muted">Система только предлагает. Решение принимает врач.</p>
        {proposed.length === 0 ? <p>Нет предложений, ожидающих решения.</p> : proposed.map((a) => (
          <ActionItem key={a.id} action={a} onChange={reload} />
        ))}
      </section>

      <section aria-labelledby="adverse-events-h">
        <h2 id="adverse-events-h">Нежелательные реакции</h2>
        {card.adverse_events.length === 0 ? <p>Зарегистрированных нежелательных реакций нет.</p> : card.adverse_events.map((event) => (
          <article key={event.id} className={`panel ${event.serious || event.life_threatening ? 'panel-critical' : ''}`}>
            <div className="feature-card-heading"><strong>{event.title}</strong><span className={`badge ${event.life_threatening ? 'badge-critical' : event.serious ? 'badge-high' : 'badge-medium'}`}>{event.life_threatening ? 'Угроза жизни' : event.serious ? 'Серьёзная реакция' : event.intensity}</span></div>
            <p className="muted small">{formatDateTime(event.created_at)} · {event.expected === null ? 'Ожидаемость не установлена' : event.expected ? 'Ожидаемая по инструкции' : 'Неожидаемая'}</p>
            {event.description && <p>{event.description}</p>}
            {event.status === 'reviewed' ? <p className="message" role="status">Врачебный разбор зафиксирован.</p> : <>
              <ErrorMessage error={reviewAdverseEvent.error} />
              <button type="button" className="secondary" disabled={reviewAdverseEvent.pending} onClick={async () => { if (window.confirm('Зафиксировать, что нежелательная реакция рассмотрена врачом?') && await reviewAdverseEvent.run(event.id)) reload() }}>Отметить как рассмотренную</button>
            </>}
          </article>
        ))}
      </section>

      <section aria-labelledby="obs-h">
        <h2 id="obs-h">Наблюдение</h2>
        <dl className="summary">
          <dt>Очный приём</dt><dd>{formatDateTime(card.patient.in_person_visit_at)}</dd>
          <dt>Дистанционное наблюдение</dt><dd>{card.patient.monitoring_active ? 'Назначено' : 'Не назначено'}</dd>
          <dt>Приверженность (14 дней)</dt>
          <dd>{card.context.adherence.pct_14d === null ? '—' : `${card.context.adherence.pct_14d}%`}</dd>
        </dl>
        <ErrorMessage error={visit.error ?? monitoring.error} />
        <div className="row">
          <button type="button" className="secondary" disabled={visit.pending}
                  onClick={async () => { if (await visit.run()) reload() }}>Отметить очный приём сегодня</button>
          <button type="button" className="secondary" disabled={monitoring.pending}
                  onClick={async () => { if (await monitoring.run(!card.patient.monitoring_active)) reload() }}>
            {card.patient.monitoring_active ? 'Прекратить дистанционное наблюдение' : 'Назначить дистанционное наблюдение'}
          </button>
        </div>
        <p className="muted small">Дистанционное наблюдение назначается после очного приёма (приказ Минздрава России № 193н).</p>
      </section>

      <section aria-labelledby="patient-access-h">
        <h2 id="patient-access-h">Доступ пациента</h2>
        <p className="muted">При утрате доступа можно выдать новый временный пароль. После входа пациент обязан заменить его; передавайте пароль только защищённым каналом.</p>
        {temporaryPassword && <div className="message" role="status">
          <p>Новый временный пароль: <code>{temporaryPassword}</code></p>
          <button type="button" className="secondary" onClick={() => setTemporaryPassword(null)}>Скрыть пароль</button>
        </div>}
        <ErrorMessage error={resetPatientPassword.error} />
        <button type="button" className="secondary" disabled={resetPatientPassword.pending}
          onClick={async () => {
            if (!window.confirm('Завершить активные сеансы пациента и выдать новый временный пароль?')) return
            const result = await resetPatientPassword.run()
            if (result) setTemporaryPassword(result.temporary_password)
          }}>Выдать временный пароль</button>
      </section>
    </>
  )
}

function AlertItem({ alert, onChange }: { alert: Alert; onChange: () => void }) {
  const [resolution, setResolution] = useState('')
  const [closing, setClosing] = useState(false)
  const ack = useAction(() => api.post(`/api/doctor/alerts/${alert.id}/ack`))
  const resolve = useAction(() => api.post(`/api/doctor/alerts/${alert.id}/resolve`, { resolution }))

  return (
    <article className={`panel panel-${alert.severity}`}>
      <p>
        <span className={`badge badge-${alert.severity}`}>{SEVERITY_LABEL[alert.severity]}</span>{' '}
        <strong>{alert.title}</strong>
      </p>
      {alert.message && <p>{alert.message}</p>}
      <p className="muted small">
        {formatDateTime(alert.created_at)} · {alert.acknowledged_at ? `принято ${formatDateTime(alert.acknowledged_at)}` : 'не принято'}
      </p>
      <ErrorMessage error={ack.error ?? resolve.error} />
      {closing ? (
        <form className="form" onSubmit={async (e) => { e.preventDefault(); if (await resolve.run()) onChange() }}>
          <label>
            Что сделано
            <input required minLength={3} maxLength={2000} value={resolution} onChange={(e) => setResolution(e.target.value)} />
          </label>
          <div className="row">
            <button type="submit" disabled={resolve.pending}>Закрыть оповещение</button>
            <button type="button" className="secondary" onClick={() => setClosing(false)}>Отмена</button>
          </div>
        </form>
      ) : (
        <div className="row">
          {!alert.acknowledged_at && (
            <button type="button" disabled={ack.pending} onClick={async () => { if (await ack.run()) onChange() }}>Принять</button>
          )}
          <button type="button" className="secondary" onClick={() => setClosing(true)}>Закрыть…</button>
        </div>
      )}
    </article>
  )
}

function ActionItem({ action, onChange }: { action: ClinicalAction; onChange: () => void }) {
  const [comment, setComment] = useState('')
  const decide = useAction((decision: 'confirm' | 'reject') =>
    api.post(`/api/doctor/actions/${action.id}/decide`, { decision, comment: comment || null }))

  const run = async (decision: 'confirm' | 'reject') => {
    if (await decide.run(decision)) onChange()
  }

  return (
    <article className={action.level ? `panel route-${action.level}` : 'panel'}>
      <p>
        <strong>{action.title}</strong>
        {action.level && !action.title.toLowerCase().includes(LEVEL_LABEL[action.level].toLowerCase()) && (
          <> <span className={`badge badge-${action.level}`}>{LEVEL_LABEL[action.level]}</span></>
        )}
      </p>
      <p className="muted small">{formatDateTime(action.created_at)}</p>
      {action.payload?.urgency && <p><strong>Срочность:</strong> {String(action.payload.urgency)}</p>}
      {Array.isArray(action.payload?.reasons) && action.payload.reasons.length > 0 && <div>
        <strong>Основания маршрутизации</strong>
        <ul>{(action.payload.reasons as { title?: string; source?: string; id?: string }[]).map((reason, i) => <li key={reason.id ?? i}>
          {String(reason.title ?? 'Основание')}{reason.source ? <span className="muted small"> — {reason.source}</span> : null}
        </li>)}</ul>
      </div>}
      {(action.sources?.length ?? 0) > 0 && <p className="muted small">Источники: {action.sources!.join('; ')}</p>}
      {action.kind === 'pv_report' && <PvReport actionId={action.id} />}
      <label>
        Комментарий
        <input value={comment} maxLength={2000} onChange={(e) => setComment(e.target.value)} />
      </label>
      <ErrorMessage error={decide.error} />
      <div className="row">
        <button type="button" disabled={decide.pending} onClick={() => run('confirm')}>Подтвердить</button>
        <button type="button" className="secondary" disabled={decide.pending} onClick={() => run('reject')}>Отклонить</button>
      </div>
    </article>
  )
}

interface PvReportData {
  mandatory: boolean
  deadline: string | null
  deadline_rule: string
  legal_basis: string
  submit_to: string
  suspected_drug: { trade_name: string; inn: string } | null
  reaction: { title: string; intensity: string; serious: boolean; life_threatening: boolean; description: string | null } | null
}

function PvReport({ actionId }: { actionId: number }) {
  const [data, setData] = useState<PvReportData | null>(null)
  const load = useAction(() => api.get<PvReportData>(`/api/doctor/actions/${actionId}/pv-report`))

  if (!data) {
    return (
      <>
        <ErrorMessage error={load.error} />
        <p>
          <button type="button" className="secondary" disabled={load.pending}
                  onClick={async () => setData((await load.run()) ?? null)}>Сформировать извещение</button>
        </p>
      </>
    )
  }
  return (
    <div className={data.mandatory ? 'message message-error' : 'message'}>
      <p><strong>{data.mandatory ? 'Сообщение в Росздравнадзор обязательно' : 'Обязательное сообщение не требуется'}</strong></p>
      <p>{data.deadline_rule}{data.deadline ? ` Срок: ${formatDateTime(data.deadline)}.` : ''}</p>
      <dl className="summary">
        <dt>Препарат</dt><dd>{data.suspected_drug ? `${data.suspected_drug.trade_name} (${data.suspected_drug.inn})` : '—'}</dd>
        <dt>Реакция</dt><dd>{data.reaction ? data.reaction.title : '—'}</dd>
        <dt>Куда направить</dt><dd>{data.submit_to}</dd>
        <dt>Основание</dt><dd>{data.legal_basis}</dd>
      </dl>
    </div>
  )
}

function Summary({ id }: { id: string }) {
  const summary = useAction(() => api.get<{ text: string; generated: string }>(`/api/doctor/patients/${id}/summary`))
  const fhir = useAction(() => api.get<unknown>(`/api/doctor/patients/${id}/fhir`))
  const [text, setText] = useState<string | null>(null)

  const onFhir = async () => {
    const data = await fhir.run()
    if (!data) return
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/fhir+json' }))
    const a = document.createElement('a')
    a.href = url
    a.download = `patient-${id}-fhir.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <section aria-labelledby="summary-h">
      <h2 id="summary-h">Сводка к визиту</h2>
      {text !== null && <pre className="plain-text">{text || 'Недостаточно данных наблюдения.'}</pre>}
      <ErrorMessage error={summary.error ?? fhir.error} />
      <div className="row">
        <button type="button" className="secondary" disabled={summary.pending}
                onClick={async () => { const r = await summary.run(); if (r) setText(r.text) }}>Сформировать сводку</button>
        <button type="button" className="secondary" disabled={fhir.pending} onClick={onFhir}>Выгрузить в HL7 FHIR</button>
      </div>
    </section>
  )
}