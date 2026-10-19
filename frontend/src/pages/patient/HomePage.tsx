import { Link } from 'react-router-dom'
import { api } from '../../api/client'
import type { ConsentText, Overview } from '../../api/types'
import { useAction, useApi } from '../../api/useApi'
import { ErrorMessage } from '../../components/ErrorMessage'
import { Loader } from '../../components/Loader'
import { formatDateTime, formatRegimen } from '../../format'

export function HomePage() {
  const state = useApi<Overview>('/api/me/overview')
  const dose = useAction((id: number, status: 'taken' | 'skipped') =>
    api.post('/api/me/doses', { dose_id: id, status, client_id: crypto.randomUUID() }))

  const onDose = async (id: number, status: 'taken' | 'skipped') => {
    await dose.run(id, status)
    state.reload()
  }

  return (
    <Loader state={state}>
      {(o) => !o.consent.accepted || o.consent.version !== o.consent.current_version
        ? <ConsentForm onAccepted={state.reload} />
        : (
          <>
            {o.crisis && <CrisisBlock contacts={o.crisis_contacts} />}
            <h1>Здравствуйте, {o.patient.full_name}</h1>
            <p>Лечащий врач: {o.doctor.full_name}</p>
            {!o.monitoring_active && (
              <p className="message">Дистанционное наблюдение пока не назначено. Его назначает врач на очном приёме.</p>
            )}

            <section aria-labelledby="todo-h">
              <h2 id="todo-h">На сегодня</h2>
              <ul>
                {!o.diary_done_today && <li><Link to="/me/diary">Заполнить дневник самочувствия</Link></li>}
                {o.due_scales.map((s) => (
                  <li key={s.code}><Link to={`/me/scales/${s.code}`}>Пройти опросник: {s.title}</Link></li>
                ))}
                {o.diary_done_today && o.due_scales.length === 0 && <li>Все задания выполнены.</li>}
              </ul>
            </section>

            {o.therapy && (
              <section aria-labelledby="therapy-h">
                <h2 id="therapy-h">Терапия</h2>
                <p>{o.therapy.trade_name}{o.therapy.regimen ? `, ${formatRegimen(o.therapy.regimen)}` : ''}</p>
                <ErrorMessage error={dose.error} />
                {o.doses_today.length > 0 && (
                  <table>
                    <caption>Приёмы сегодня</caption>
                    <thead>
                      <tr><th scope="col">Время</th><th scope="col">Статус</th><th scope="col"><span className="visually-hidden">Отметить</span></th></tr>
                    </thead>
                    <tbody>
                      {o.doses_today.map((d) => (
                        <tr key={d.id}>
                          <td>{formatDateTime(d.scheduled_for)}</td>
                          <td>{{ taken: 'Принято', skipped: 'Пропущено' }[d.status] ?? 'Ожидается'}</td>
                          <td>
                            {d.status === 'pending' && (
                              <>
                                <button type="button" disabled={dose.pending} onClick={() => onDose(d.id, 'taken')}>Принял(а)</button>{' '}
                                <button type="button" className="secondary" disabled={dose.pending} onClick={() => onDose(d.id, 'skipped')}>Пропустил(а)</button>
                              </>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
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

function CrisisBlock({ contacts }: { contacts: Overview['crisis_contacts'] }) {
  return (
    <div className="message message-error" role="alert">
      <h2>Если вам сейчас плохо — позвоните</h2>
      <ContactList contacts={contacts} />
      <p>Врач уже получил оповещение и свяжется с вами.</p>
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
