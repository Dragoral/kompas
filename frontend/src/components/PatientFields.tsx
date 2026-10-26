import type { Diagnosis } from '../api/types'

/** Редакторы медицинских данных пациента: общие для создания пациента и правки карточки. */

export interface Row {
  a: string
  b: string
}

export interface Course {
  inn: string
  dose: string
  weeks: string
  outcome: string
}

export interface Medication {
  name?: string
  inn?: string | null
  dose?: string | null
}

export interface TherapyCourse {
  inn: string
  dose?: string | null
  weeks?: number | null
  outcome?: string
}

export const OUTCOMES: Record<string, string> = {
  response: 'Ответ',
  partial: 'Частичный ответ',
  no_response: 'Нет ответа',
  intolerance: 'Непереносимость',
  unknown: 'Неизвестно',
}

export const diagnosesToRows = (d: Diagnosis[]): Row[] => d.map((x) => ({ a: x.icd10, b: x.title ?? '' }))
export const rowsToDiagnoses = (rows: Row[]): Diagnosis[] =>
  rows.filter((d) => d.a.trim()).map((d, i) => ({ icd10: d.a.trim().toUpperCase(), title: d.b.trim(), primary: i === 0 }))

export const medsToRows = (m: Medication[]): Row[] => m.map((x) => ({ a: x.name ?? x.inn ?? '', b: x.dose ?? '' }))
export const rowsToMeds = (rows: Row[]): Medication[] =>
  rows.filter((m) => m.a.trim()).map((m) => ({ name: m.a.trim(), dose: m.b.trim() || null }))

export const coursesToRows = (c: TherapyCourse[]): Course[] =>
  c.map((x) => ({ inn: x.inn, dose: x.dose ?? '', weeks: x.weeks == null ? '' : String(x.weeks), outcome: x.outcome ?? 'unknown' }))
export const rowsToCourses = (rows: Course[]): TherapyCourse[] =>
  rows.filter((c) => c.inn.trim()).map((c) => ({
    inn: c.inn.trim().toLowerCase(), dose: c.dose.trim() || null, weeks: c.weeks ? Number(c.weeks) : null, outcome: c.outcome,
  }))

export function RowsEditor({ rows, onChange, labels, placeholders }: {
  rows: Row[]
  onChange: (rows: Row[]) => void
  labels: [string, string]
  placeholders?: [string, string]
}) {
  const update = (i: number, patch: Partial<Row>) => onChange(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)))
  return (
    <div className="med-rows">
      {rows.length > 0 && (
        <div className="med-rows-head" aria-hidden="true">
          <span>{labels[0]}</span>
          <span>{labels[1]}</span>
          <span />
        </div>
      )}
      {rows.map((r, i) => (
        <div key={i} className="med-rows-line">
          <input
            className="med-input med-input-code"
            aria-label={labels[0]}
            placeholder={placeholders?.[0] ?? labels[0]}
            value={r.a}
            onChange={(e) => update(i, { a: e.target.value })}
          />
          <input
            className="med-input med-input-text"
            aria-label={labels[1]}
            placeholder={placeholders?.[1] ?? labels[1]}
            value={r.b}
            onChange={(e) => update(i, { b: e.target.value })}
          />
          <button type="button" className="med-btn-remove" onClick={() => onChange(rows.filter((_, j) => j !== i))}>
            Удалить
          </button>
        </div>
      ))}
      <button type="button" className="med-btn-add" onClick={() => onChange([...rows, { a: '', b: '' }])}>
        + Добавить строку
      </button>
    </div>
  )
}

export function CoursesEditor({ rows, onChange }: { rows: Course[]; onChange: (rows: Course[]) => void }) {
  const update = (i: number, patch: Partial<Course>) => onChange(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)))
  return (
    <div className="med-rows">
      {rows.length > 0 && (
        <div className="med-rows-head med-rows-head-4" aria-hidden="true">
          <span>Препарат (МНН)</span>
          <span>Доза</span>
          <span>Недель</span>
          <span>Исход</span>
          <span />
        </div>
      )}
      {rows.map((r, i) => (
        <div key={i} className="med-rows-line med-rows-line-4">
          <input
            className="med-input"
            aria-label="Препарат"
            placeholder="МНН"
            required
            value={r.inn}
            onChange={(e) => update(i, { inn: e.target.value })}
          />
          <input
            className="med-input"
            aria-label="Доза"
            placeholder="Доза"
            value={r.dose}
            onChange={(e) => update(i, { dose: e.target.value })}
          />
          <input
            className="med-input med-input-weeks"
            aria-label="Недель"
            type="number"
            min={0}
            max={520}
            placeholder="0"
            value={r.weeks}
            onChange={(e) => update(i, { weeks: e.target.value })}
          />
          <select
            className="med-input"
            aria-label="Исход"
            value={r.outcome}
            onChange={(e) => update(i, { outcome: e.target.value })}
          >
            {Object.entries(OUTCOMES).map(([v, l]) => (
              <option key={v} value={v}>{l}</option>
            ))}
          </select>
          <button type="button" className="med-btn-remove" onClick={() => onChange(rows.filter((_, j) => j !== i))}>
            Удалить
          </button>
        </div>
      ))}
      <button
        type="button"
        className="med-btn-add"
        onClick={() => onChange([...rows, { inn: '', dose: '', weeks: '', outcome: 'unknown' }])}
      >
        + Добавить курс
      </button>
    </div>
  )
}
