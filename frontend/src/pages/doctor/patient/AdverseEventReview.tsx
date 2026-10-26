import { useState } from 'react'
import { api } from '../../../api/client'
import type { AdverseEvent } from '../../../api/types'
import { useAction } from '../../../api/useApi'
import { ErrorMessage } from '../../../components/ErrorMessage'
import { formatDateTime } from '../../../format'

const INTENSITY: Record<string, string> = { mild: 'слабо', moderate: 'умеренно', severe: 'сильно' }
const RELATION: Record<string, string> = {
  current: 'текущее назначение',
  recently_stopped: 'отменён недавно (возможен синдром отмены)',
  concomitant: 'сопутствующая терапия',
}

function expectedLabel(v: boolean | null): string {
  return v === null ? 'не установлено' : v ? 'описана в инструкции текущего препарата' : 'не описана в инструкции текущего препарата'
}

/** Нежелательная реакция: слова пациента, разбор системы и решение врача. */
export function AdverseEventReview({ event, onChange }: { event: AdverseEvent; onChange: () => void }) {
  const a = event.analysis
  const [expected, setExpected] = useState<string>(event.expected === null ? '' : String(event.expected))
  const [serious, setSerious] = useState(event.serious)
  const review = useAction(() => api.post(`/api/doctor/adverse-events/${event.id}/review`, {
    expected: expected === '' ? null : expected === 'true',
    serious,
  }))
  const flags = a?.red_flags ?? []

  return (
    <article className={`panel ${event.life_threatening || flags.some((f) => f.level === 'critical') ? 'panel-critical' : event.serious || flags.length ? 'panel-high' : ''}`}>
      <p>
        <strong>{event.title}</strong>{' '}
        <span className="muted small">{formatDateTime(event.created_at)} · выраженность: {INTENSITY[event.intensity] ?? event.intensity}</span>
      </p>
      {event.description && <blockquote className="patient-words">{event.description}</blockquote>}

      {flags.length > 0 && (
        <div className="message message-error" role="alert">
          <p><strong>Тревожные признаки:</strong></p>
          <ul>{flags.map((f) => <li key={f.id}>{f.title}</li>)}</ul>
        </div>
      )}

      {a && (
        <details open={event.status !== 'reviewed'}>
          <summary>Разбор системы: {expectedLabel(a.expected)}</summary>
          {!a.recognized ? (
            <p className="muted">Формулировка не распознана словарём — оцените по описанию пациента.</p>
          ) : (
            <table className="compact">
              <thead><tr><th scope="col">Распознано</th><th scope="col">В инструкциях</th></tr></thead>
              <tbody>
                {a.terms.map((t) => (
                  <tr key={t.term}>
                    <td>{t.term}</td>
                    <td>
                      {t.in_instructions.length === 0 ? 'не описано' : t.in_instructions.map((m) => (
                        <div key={m.drug_id}>{m.trade_name}{m.frequency_label ? `: ${m.frequency_label}` : ''} <span className="muted small">({RELATION[m.relation] ?? m.relation})</span></div>
                      ))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <p className="muted small">
            Проверены: {a.drugs_checked.length ? a.drugs_checked.map((d) => `${d.trade_name} (${RELATION[d.relation] ?? d.relation})`).join('; ') : 'нет препаратов в справочнике'}.
            Сравнение по словарю формулировок — окончательную оценку даёт врач.
          </p>
        </details>
      )}

      {event.status === 'reviewed' ? (
        <p className="message" role="status">Разбор врача зафиксирован: {expectedLabel(event.expected)}{event.serious ? ', серьёзная' : ''}.</p>
      ) : (
        <form className="form" onSubmit={async (e) => { e.preventDefault(); if (await review.run()) onChange() }}>
          <fieldset>
            <legend>Решение врача</legend>
            <label className="radio"><input type="radio" name={`exp-${event.id}`} checked={expected === 'true'} onChange={() => setExpected('true')} />Описана в инструкции (ожидаемая)</label>
            <label className="radio"><input type="radio" name={`exp-${event.id}`} checked={expected === 'false'} onChange={() => setExpected('false')} />Не описана в инструкции (неожиданная)</label>
            <label className="radio"><input type="radio" name={`exp-${event.id}`} checked={expected === ''} onChange={() => setExpected('')} />Связь с препаратом не установлена</label>
          </fieldset>
          <label className="checkbox">
            <input type="checkbox" checked={serious} onChange={(e) => setSerious(e.target.checked)} />
            Серьёзная (госпитализация, угроза жизни, инвалидизация)
          </label>
          <ErrorMessage error={review.error} />
          <button type="submit" className="secondary" disabled={review.pending}>Зафиксировать разбор</button>
        </form>
      )}
    </article>
  )
}
