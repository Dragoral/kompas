import { useState, type FormEvent } from 'react'
import { api } from '../../../api/client'
import { useAction, useApi } from '../../../api/useApi'
import { ErrorMessage } from '../../../components/ErrorMessage'
import { Loader } from '../../../components/Loader'
import { formatDateTime } from '../../../format'

interface VisitRecord {
  id: number
  kind: 'in_person' | 'telemedicine' | 'async' | string
  at: string
  doctor_id: number
  reason: string | null
  notes: string | null
  plan: Record<string, unknown>
  next_visit_at: string | null
}

const KIND_LABEL: Record<string, string> = {
  in_person: 'Очный приём',
  telemedicine: 'Телемедицинская консультация',
  async: 'Отложенная консультация',
}

const PLAN_LABELS: Record<string, string> = {
  remote_monitoring: 'Дистанционное наблюдение',
  monitoring: 'Наблюдение',
  therapy_review: 'Пересмотр терапии',
  scales: 'Опросники',
  next_steps: 'Следующие шаги',
}

function formatPlanValue(value: unknown): string {
  if (typeof value === 'boolean') return value ? 'да' : 'нет'
  if (value == null) return '—'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function PlanBlock({ plan }: { plan: Record<string, unknown> }) {
  const entries = Object.entries(plan)
  if (entries.length === 0) return null
  return (
    <details className="visit-plan">
      <summary>Структурированный план</summary>
      <ul className="plan-list">
        {entries.map(([key, value]) => (
          <li key={key}>
            <span className="plan-key">{PLAN_LABELS[key] ?? key.replace(/_/g, ' ')}</span>
            <span className="plan-val">{formatPlanValue(value)}</span>
          </li>
        ))}
      </ul>
    </details>
  )
}

export function VisitsHistory({ patientId }: { patientId: number }) {
  const state = useApi<VisitRecord[]>(`/api/doctor/patients/${patientId}/visits`)
  const [kind, setKind] = useState('in_person')
  const [reason, setReason] = useState('')
  const [notes, setNotes] = useState('')
  const [nextVisit, setNextVisit] = useState('')
  const [diagnosisConfirmed, setDiagnosisConfirmed] = useState(false)
  const [showForm, setShowForm] = useState(false)
  const create = useAction(() => api.post(`/api/doctor/patients/${patientId}/visits`, {
    kind,
    reason: reason.trim() || null,
    notes: notes.trim() || null,
    plan: diagnosisConfirmed ? { remote_monitoring: true } : {},
    next_visit_at: nextVisit ? new Date(nextVisit).toISOString() : null,
    diagnosis_confirmed_in_person: kind === 'in_person' ? diagnosisConfirmed : null,
  }))

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (await create.run()) {
      setReason(''); setNotes(''); setNextVisit(''); setDiagnosisConfirmed(false); setShowForm(false)
      state.reload()
    }
  }

  return (
    <section className="feature-card" aria-labelledby="visits-heading">
      <div className="feature-card-heading visits-heading-row">
        <div>
          <h2 id="visits-heading">История визитов</h2>
          <p className="muted small">Записи приёмов, консультаций и запланированных следующих визитов.</p>
        </div>
        <div className="actions visits-heading-actions">
          <button type="button" className="secondary" onClick={state.reload}>Обновить</button>
          <button type="button" onClick={() => setShowForm((v) => !v)}>
            {showForm ? 'Скрыть форму' : 'Добавить визит'}
          </button>
        </div>
      </div>

      {showForm && (
        <form className="form wide visit-form" onSubmit={submit}>
          <div className="two-col">
            <label>
              Тип визита
              <select value={kind} onChange={(e) => setKind(e.target.value)}>
                <option value="in_person">Очный приём</option>
                <option value="telemedicine">Телемедицинская консультация</option>
                <option value="async">Отложенная консультация</option>
              </select>
            </label>
            <label>
              Следующий визит
              <input type="datetime-local" value={nextVisit} onChange={(e) => setNextVisit(e.target.value)} />
            </label>
          </div>
          <label>
            Причина обращения
            <input maxLength={256} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Причина визита (необязательно)" />
          </label>
          <label>
            Заметки врача
            <textarea rows={3} maxLength={20000} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Факты визита, наблюдения и согласованный план" />
          </label>
          {kind === 'in_person' && (
            <label className="checkbox">
              <input type="checkbox" checked={diagnosisConfirmed} onChange={(e) => setDiagnosisConfirmed(e.target.checked)} />
              <span>Диагноз подтверждён на очном приёме</span>
            </label>
          )}
          <ErrorMessage error={create.error} />
          <div className="actions">
            <button type="submit" disabled={create.pending}>{create.pending ? 'Сохраняем…' : 'Сохранить запись о визите'}</button>
            <button type="button" className="secondary" onClick={() => setShowForm(false)}>Отмена</button>
          </div>
        </form>
      )}

      <Loader state={state}>
        {(visits) => visits.length === 0 ? (
          <div className="empty-state">
            <strong>Истории визитов пока нет</strong>
            <p>Нажмите «Добавить визит», чтобы создать первую запись.</p>
          </div>
        ) : (
          <div className="visit-list">
            {visits.map((v) => (
              <article className="visit-item" key={v.id}>
                <div className="feature-card-heading">
                  <h3>{KIND_LABEL[v.kind] ?? v.kind}</h3>
                  <span className="muted small">{formatDateTime(v.at)}</span>
                </div>
                {v.reason && <p><strong>Причина:</strong> {v.reason}</p>}
                {v.notes && <p className="plain-text">{v.notes}</p>}
                {v.next_visit_at && <p><strong>Следующий визит:</strong> {formatDateTime(v.next_visit_at)}</p>}
                <PlanBlock plan={v.plan ?? {}} />
              </article>
            ))}
          </div>
        )}
      </Loader>
    </section>
  )
}
