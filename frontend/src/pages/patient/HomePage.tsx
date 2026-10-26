import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, download } from '../../api/client'
import type { ConsentText, Overview } from '../../api/types'
import { useAction, useApi } from '../../api/useApi'
import { ErrorMessage } from '../../components/ErrorMessage'
import { Loader } from '../../components/Loader'
import { formatDateTime, formatRegimen } from '../../format'

function todayKey(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function readDoneScales(): { code: string; title: string }[] {
  try {
    const prefix = `kompas.scale.done.${todayKey()}.`
    const out: { code: string; title: string }[] = []
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i)
      if (k?.startsWith(prefix)) out.push({ code: k.slice(prefix.length), title: localStorage.getItem(k) || k.slice(prefix.length) })
    }
    return out
  } catch { return [] }
}

function isDiaryDoneLocal(): boolean {
  try { return localStorage.getItem(`kompas.diary.done.${todayKey()}`) === '1' } catch { return false }
}

export function HomePage() {
  const state = useApi<Overview>('/api/me/overview')
  const [queuedDose, setQueuedDose] = useState(false)
  const reminders = useAction(() => download('/api/me/doses.ics', 'kompas-reminders.ics'))
  const dose = useAction((id: number, status: 'taken' | 'skipped') =>
    api.post<{ queued_offline?: boolean }>('/api/me/doses', { dose_id: id, status, client_id: crypto.randomUUID(), taken_at: new Date().toISOString() }))

  const onDose = async (id: number, status: 'taken' | 'skipped') => {
    const result = await dose.run(id, status)
    if (result?.queued_offline) setQueuedDose(true)
    else if (result) { setQueuedDose(false); state.reload() }
  }

  return (
    <Loader state={state}>
      {(o) => !o.consent.accepted || o.consent.version !== o.consent.current_version
        ? <ConsentForm onAccepted={state.reload} />
        : (
          <>
            {queuedDose && <p className="message" role="status">Отметка сохранена на устройстве и ожидает синхронизации. Сервер и лечащий врач пока не получили запись.</p>}
            {o.crisis && <CrisisBlock contacts={o.crisis_contacts} />}
            <h1>Здравствуйте, {o.patient.full_name}</h1>
            <p>Лечащий врач: {o.doctor.full_name}</p>
            {!o.monitoring_active && (
              <p className="message">Дистанционное наблюдение пока не назначено. Его назначает врач на очном приёме.</p>
            )}

            <section aria-labelledby="todo-h" className="patient-today">
              <h2 id="todo-h">На сегодня</h2>
              <PatientTodayTasks
                diaryDone={o.diary_done_today || isDiaryDoneLocal()}
                dueScales={o.due_scales}
                doneScales={readDoneScales()}
              />
              {o.unread_messages > 0 && (
                <p className="patient-msg-link"><Link to="/me/messages">Новые сообщения от врача: {o.unread_messages}</Link></p>
              )}
            </section>

            {o.therapy && (
              <section aria-labelledby="therapy-h" className="patient-therapy">
                <h2 id="therapy-h">Терапия</h2>
                <div className="therapy-grid">
                  <article className="therapy-card panel">
                    <h3 className="therapy-card-title">Назначение</h3>
                    <p className="therapy-drug">{o.therapy.trade_name}</p>
                    {o.therapy.regimen && (
                      <p className="therapy-regimen">{formatRegimen(o.therapy.regimen)}</p>
                    )}
                    <p>
                      <button type="button" className="secondary" disabled={reminders.pending} onClick={() => reminders.run()}>
                        Напоминания в календарь телефона
                      </button>
                    </p>
                    <p className="muted small">Откройте скачанный файл: календарь будет напоминать о каждом приёме 4 недели, даже без интернета. Если врач изменит назначение, скачайте напоминания заново.</p>
                    <ErrorMessage error={reminders.error} />
                    {o.doses_today.length > 0 && (
                      <ul className="therapy-schedule">
                        {o.doses_today.map((d) => (
                          <li key={d.id}>
                            <span>{formatDateTime(d.scheduled_for)}</span>
                            <span className="therapy-status">{{ taken: 'Принято', skipped: 'Пропущено' }[d.status] ?? 'Ожидается'}</span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </article>
                  <article className="therapy-card panel">
                    <h3 className="therapy-card-title">Отметить приём</h3>
                    <ErrorMessage error={dose.error} />
                    {o.doses_today.filter((d) => d.status === 'pending').length === 0 ? (
                      <p className="muted">Нет приёмов, ожидающих отметки.</p>
                    ) : (
                      <ul className="therapy-dose-actions">
                        {o.doses_today.filter((d) => d.status === 'pending').map((d) => (
                          <li key={d.id} className="therapy-dose-row">
                            <span className="therapy-dose-time">{formatDateTime(d.scheduled_for)}</span>
                            <div className="actions">
                              <button type="button" disabled={dose.pending} onClick={() => onDose(d.id, 'taken')}>Принял(а)</button>
                              <button type="button" className="secondary" disabled={dose.pending} onClick={() => onDose(d.id, 'skipped')}>Пропустил(а)</button>
                            </div>
                          </li>
                        ))}
                      </ul>
                    )}
                    <Link to="/me/adverse-event" className="therapy-ae-btn secondary">Сообщить о побочном эффекте</Link>
                  </article>
                </div>
              </section>
            )}

            {!o.crisis && (
              <section aria-labelledby="help-h">
                <h2 id="help-h">Экстренная помощь</h2>
                <ContactList contacts={o.crisis_contacts} />
              </section>
            )}
          </>
        )}
    </Loader>
  )
}



function PatientTodayTasks({ diaryDone, dueScales, doneScales }: {
  diaryDone: boolean
  dueScales: { code: string; title: string; reason: string | null }[]
  doneScales: { code: string; title: string }[]
}) {
  const dueCodes = new Set(dueScales.map((s) => s.code))
  const completedOnly = doneScales.filter((s) => !dueCodes.has(s.code))
  const allDone = diaryDone && dueScales.length === 0

  return (
    <>
      <div className="patient-task-grid">
        <Link
          to="/me/diary"
          className={`patient-task-btn${diaryDone ? ' patient-task-btn-done' : ''}`}
        >
          <span className="patient-task-title">Дневник самочувствия</span>
          <span className="patient-task-hint">{diaryDone ? 'Пройдено' : 'Отметьте настроение и сон'}</span>
        </Link>
        {dueScales.map((s) => (
          <Link key={s.code} to={`/me/scales/${s.code}`} className="patient-task-btn">
            <span className="patient-task-title">{s.title}</span>
            <span className="patient-task-hint">Опросник · нажмите, чтобы пройти</span>
          </Link>
        ))}
        {completedOnly.map((s) => (
          <Link key={s.code} to={`/me/scales/${s.code}`} className="patient-task-btn patient-task-btn-done">
            <span className="patient-task-title">{s.title}</span>
            <span className="patient-task-hint">Пройдено</span>
          </Link>
        ))}
      </div>
      {allDone && completedOnly.length === 0 && dueScales.length === 0 && (
        <p className="message" role="status">На сегодня всё выполнено. Спасибо!</p>
      )}
    </>
  )
}

function CrisisBlock({ contacts }: { contacts: Overview['crisis_contacts'] }) {
  return (
    <div className="message message-error" role="alert">
      <h2>Если вам сейчас плохо — позвоните</h2>
      <ContactList contacts={contacts} />
      <p>Система сформировала сигнал для медицинской команды, но это не гарантирует, что врач уже увидел его или сможет ответить немедленно. При непосредственной опасности не ждите ответа через приложение — звоните 112 или 103.</p>
    </div>
  )
}

function ContactList({ contacts }: { contacts: Overview['crisis_contacts'] }) {
  return (
    <ul>
      {contacts.map((c) => (
        <li key={c.phone + c.title}>{c.title}: <a href={`tel:${c.phone.replace(/[^\d+]/g, '')}`}>{c.phone}</a></li>
      ))}
    </ul>
  )
}

function ConsentForm({ onAccepted }: { onAccepted: () => void }) {
  const text = useApi<ConsentText>('/api/consent')
  const accept = useAction((c: ConsentText) => api.post('/api/me/consent', { version: c.version, sha256: c.sha256 }))

  return (
    <Loader state={text}>
      {(c) => (
        <>
          <h1>Согласие на обработку персональных данных</h1>
          <div className="document">{c.text}</div>
          <ErrorMessage error={accept.error} />
          <button type="button" disabled={accept.pending}
                  onClick={async () => { if (await accept.run(c)) onAccepted() }}>
            Я ознакомлен(а) и даю согласие
          </button>
        </>
      )}
    </Loader>
  )
}
