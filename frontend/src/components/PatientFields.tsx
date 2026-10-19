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
    <div className="table-wrap">
      <table className="compact">
        <thead>
          <tr><th scope="col">{labels[0]}</th><th scope="col">{labels[1]}</th><th scope="col"><span className="visually-hidden">Удалить</span></th></tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td><input aria-label={labels[0]} placeholder={placeholders?.[0]} value={r.a} onChange={(e) => update(i, { a: e.target.value })} /></td>
              <td><input aria-label={labels[1]} placeholder={placeholders?.[1]} value={r.b} onChange={(e) => update(i, { b: e.target.value })} /></td>
              <td><button type="button" className="button-link" onClick={() => onChange(rows.filter((_, j) => j !== i))}>Удалить</button></td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr><td colSpan={3}><button type="button" className="button-link" onClick={() => onChange([...rows, { a: '', b: '' }])}>Добавить строку</button></td></tr>
        </tfoot>
      </table>
    </div>
  )
}

export function CoursesEditor({ rows, onChange }: { rows: Course[]; onChange: (rows: Course[]) => void }) {
  const update = (i: number, patch: Partial<Course>) => onChange(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)))
  return (
    <div className="table-wrap">
      <table className="compact">
        <thead>
          <tr>
            <th scope="col">Препарат (МНН)</th>
            <th scope="col">Доза</th>
            <th scope="col">Недель</th>
            <th scope="col">Исход</th>
            <th scope="col"><span className="visually-hidden">Удалить</span></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td><input aria-label="Препарат" required value={r.inn} onChange={(e) => update(i, { inn: e.target.value })} /></td>
              <td><input aria-label="Доза" value={r.dose} onChange={(e) => update(i, { dose: e.target.value })} /></td>
              <td className="col-number">
                <input aria-label="Недель" type="number" min={0} max={520} value={r.weeks} onChange={(e) => update(i, { weeks: e.target.value })} />
              </td>
              <td>
                <select aria-label="Исход" value={r.outcome} onChange={(e) => update(i, { outcome: e.target.value })}>
                  {Object.entries(OUTCOMES).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                </select>
              </td>
              <td><button type="button" className="button-link" onClick={() => onChange(rows.filter((_, j) => j !== i))}>Удалить</button></td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <td colSpan={5}>
              <button type="button" className="button-link"
                      onClick={() => onChange([...rows, { inn: '', dose: '', weeks: '', outcome: 'unknown' }])}>Добавить курс</button>
            </td>
          </tr>
        </tfoot>
      </table>
    </div>
  )
}
