import { useState } from 'react'
import { Link } from 'react-router-dom'
import type { ClinicalAction } from '../../api/types'
import { api } from '../../api/client'
import { useAction, useApi } from '../../api/useApi'
import { ErrorMessage } from '../../components/ErrorMessage'
import { Loader } from '../../components/Loader'
import { formatDateTime, LEVEL_LABEL } from '../../format'

interface PvReportData {
  mandatory: boolean
  deadline: string | null
  deadline_rule: string
  legal_basis: string
  submit_to: string
  suspected_drug: { trade_name: string; inn: string } | null
  reaction: { title: string; intensity: string; serious: boolean; life_threatening: boolean; description: string | null } | null
}

export function ClinicalActionsPage() {
  const [status, setStatus] = useState<'proposed' | 'confirmed' | 'rejected'>('proposed')
  const state = useApi<ClinicalAction[]>(`/api/doctor/actions?status=${status}`)
  const onChange = () => state.reload()

  return (
    <>
      <div className="page-heading">
        <div><h1>Очередь клинических решений</h1></div>
      </div>
      <div className="toolbar-row status-tabs" role="group" aria-label="Статус решений">
        {([['proposed', 'Ожидают решения'], ['confirmed', 'Подтверждены'], ['rejected', 'Отклонены']] as const).map(([value, label]) => (
          <button key={value} className={status === value ? 'button-primary' : 'secondary'} type="button" onClick={() => setStatus(value)}>{label}</button>
        ))}
        <button type="button" className="secondary" onClick={state.reload}>Обновить</button>
      </div>
      <Loader state={state}>
        {(items) => items.length === 0 ? <div className="empty-state"><strong>Нет записей в этой очереди</strong><p>Попробуйте другой статус или обновите список.</p></div> : (
          <div className="action-queue">
            {items.map((action) => <ActionCard key={action.id} action={action} onChange={onChange} />)}
          </div>
        )}
      </Loader>
    </>
  )
}

function ActionCard({ action, onChange }: { action: ClinicalAction; onChange: () => void }) {
  const [comment, setComment] = useState(action.comment ?? '')
  const [showPayload, setShowPayload] = useState(false)
  const decide = useAction((decision: 'confirm' | 'reject') =>
    api.post(`/api/doctor/actions/${action.id}/decide`, { decision, comment: comment.trim() || null }))

  return (
    <article className={`panel ${action.level ? `route-${action.level}` : ''}`}>
      <div className="feature-card-heading">
        <div>
          <p><strong>{action.title}</strong>{action.level && <> <span className={`badge badge-${action.level}`}>{LEVEL_LABEL[action.level]}</span></>}</p>
          <p className="muted small">{action.patient_name ?? `Пациент #${action.patient_id}`} · {formatDateTime(action.created_at)} · {action.kind}</p>
        </div>
        <span className={`badge ${action.status === 'proposed' ? 'badge-high' : action.status === 'confirmed' ? 'badge-low' : 'badge-medium'}`}>{action.status === 'proposed' ? 'Ожидает решения' : action.status === 'confirmed' ? 'Подтверждено' : 'Отклонено'}</span>
      </div>
      <p><Link to={`/doctor/patients/${action.patient_id}`}>Открыть карточку пациента →</Link></p>
      {action.due_at && <p className="small"><strong>Срок:</strong> {formatDateTime(action.due_at)}</p>}
      {action.sources?.length ? <div className="small"><strong>Источники:</strong> {action.sources.join('; ')}</div> : null}
      {action.payload && <details open={showPayload} onToggle={(e) => setShowPayload(e.currentTarget.open)}><summary>Причины и данные, на которых основано предложение</summary><pre className="plain-text">{JSON.stringify(action.payload, null, 2)}</pre></details>}
      {action.kind === 'pv_report' && <PvReport actionId={action.id} />}
      {action.status === 'proposed' && (
        <>
          <label className="form">Комментарий врача<input value={comment} maxLength={2000} onChange={(e) => setComment(e.target.value)} placeholder="Обоснование решения (необязательно)" /></label>
          <ErrorMessage error={decide.error} />
          <div className="actions decision-actions">
            <button type="button" disabled={decide.pending} onClick={async () => { if (await decide.run('confirm')) onChange() }}>Подтвердить решение</button>
            <button type="button" className="secondary" disabled={decide.pending} onClick={async () => { if (await decide.run('reject')) onChange() }}>Отклонить</button>
          </div>
        </>
      )}
      {action.status !== 'proposed' && <p className="muted small">Решение: {formatDateTime(action.decided_at ?? null)}{action.comment ? ` · ${action.comment}` : ''}</p>}
    </article>
  )
}

function PvReport({ actionId }: { actionId: number }) {
  const [report, setReport] = useState<PvReportData | null>(null)
  const getReport = useAction(() => api.get<PvReportData>(`/api/doctor/actions/${actionId}/pv-report`))
  return (
    <section className="nested-panel">
      <h3>Извещение о нежелательной реакции</h3>
      {!report ? <>
        <ErrorMessage error={getReport.error} />
        <button type="button" className="secondary" disabled={getReport.pending} onClick={async () => setReport((await getReport.run()) ?? null)}>Сформировать черновик извещения</button>
      </> : <div className={report.mandatory ? 'message message-error' : 'message'}>
        <strong>{report.mandatory ? 'Требуется обязательное извещение' : 'Обязательность требует оценки врача'}</strong>
        <dl className="summary"><dt>Срок</dt><dd>{report.deadline ? formatDateTime(report.deadline) : 'Не указан'}</dd><dt>Правило срока</dt><dd>{report.deadline_rule}</dd><dt>Препарат</dt><dd>{report.suspected_drug ? `${report.suspected_drug.trade_name} (${report.suspected_drug.inn})` : '—'}</dd><dt>Реакция</dt><dd>{report.reaction ? `${report.reaction.title} · ${report.reaction.intensity}` : '—'}</dd><dt>Куда</dt><dd>{report.submit_to}</dd><dt>Основание</dt><dd>{report.legal_basis}</dd></dl>
        {report.reaction?.description && <p>{report.reaction.description}</p>}
      </div>}
    </section>
  )
}
