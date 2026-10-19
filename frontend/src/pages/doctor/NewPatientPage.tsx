import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../api/client'
import { useAction } from '../../api/useApi'
import { ErrorMessage } from '../../components/ErrorMessage'

interface Created {
  id: number
  code: string
  login: string
  temporary_password: string
}

interface Row {
  a: string
  b: string
}

function RowsEditor({ rows, onChange, labels, placeholders }: {
  rows: Row[]
  onChange: (rows: Row[]) => void
  labels: [string, string]
  placeholders?: [string, string]
}) {
  const update = (i: number, patch: Partial<Row>) => onChange(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)))
  return (
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
  )
}

interface Course {
  inn: string
  dose: string
  weeks: string
  outcome: string
}

const OUTCOMES: Record<string, string> = {
  response: 'Ответ',
  partial: 'Частичный ответ',
  no_response: 'Нет ответа',
  intolerance: 'Непереносимость',
  unknown: 'Неизвестно',
}

function CoursesEditor({ rows, onChange }: { rows: Course[]; onChange: (rows: Course[]) => void }) {
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
              <td className="col-number"><input aria-label="Недель" type="number" min={0} max={520} value={r.weeks} onChange={(e) => update(i, { weeks: e.target.value })} /></td>
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

export function NewPatientPage() {
  const [form, setForm] = useState({
    full_name: '', birth_date: '', sex: 'f', phone: '', emergency_contact: '',
    height_cm: '', weight_kg: '', allergies: '', in_person_visit: true,
  })
  const [diagnoses, setDiagnoses] = useState<Row[]>([{ a: '', b: '' }])
  const [meds, setMeds] = useState<Row[]>([])
  const [courses, setCourses] = useState<Course[]>([])
  const [created, setCreated] = useState<Created | null>(null)

  const submit = useAction(() => api.post<Created>('/api/doctor/patients', {
    full_name: form.full_name.trim(),
    birth_date: form.birth_date,
    sex: form.sex,
    phone: form.phone.trim() || null,
    emergency_contact: form.emergency_contact.trim() || null,
    profile: {
      height_cm: form.height_cm ? Number(form.height_cm) : undefined,
      weight_kg: form.weight_kg ? Number(form.weight_kg) : undefined,
      allergies: form.allergies.split(',').map((s) => s.trim()).filter(Boolean),
    },
    diagnoses: diagnoses.filter((d) => d.a.trim()).map((d, i) => ({ icd10: d.a.trim().toUpperCase(), title: d.b.trim(), primary: i === 0 })),
    current_meds: meds.filter((m) => m.a.trim()).map((m) => ({ name: m.a.trim(), dose: m.b.trim() || null })),
    therapy_history: courses.map((c) => ({
      inn: c.inn.trim().toLowerCase(), dose: c.dose.trim() || null, weeks: c.weeks ? Number(c.weeks) : null, outcome: c.outcome,
    })),
    in_person_visit: form.in_person_visit,
  }))

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault()
    const r = await submit.run()
    if (r) setCreated(r)
  }

  if (created) {
    return (
      <>
        <h1>Пациент добавлен</h1>
        <div className="message" role="status">
          <p>Передайте пациенту данные для входа. Пароль показывается один раз.</p>
          <dl className="summary">
            <dt>Код пациента</dt><dd>{created.code}</dd>
            <dt>Логин</dt><dd><code>{created.login}</code></dd>
            <dt>Временный пароль</dt><dd><code>{created.temporary_password}</code></dd>
          </dl>
        </div>
        <p><Link to={`/doctor/patients/${created.id}`}>Открыть карточку пациента</Link></p>
      </>
    )
  }

  const set = (patch: Partial<typeof form>) => setForm({ ...form, ...patch })

  return (
    <>
      <h1>Новый пациент</h1>
      <form className="form" onSubmit={onSubmit}>
        <label>
          ФИО
          <input required minLength={3} maxLength={128} autoComplete="off" value={form.full_name} onChange={(e) => set({ full_name: e.target.value })} />
        </label>
        <div className="row">
          <label>
            Дата рождения
            <input type="date" required value={form.birth_date} onChange={(e) => set({ birth_date: e.target.value })} />
          </label>
          <label>
            Пол
            <select value={form.sex} onChange={(e) => set({ sex: e.target.value })}>
              <option value="f">Женский</option>
              <option value="m">Мужской</option>
            </select>
          </label>
        </div>
        <div className="row">
          <label>Рост, см<input type="number" min={50} max={250} value={form.height_cm} onChange={(e) => set({ height_cm: e.target.value })} /></label>
          <label>Вес, кг<input type="number" min={20} max={300} step={0.1} value={form.weight_kg} onChange={(e) => set({ weight_kg: e.target.value })} /></label>
        </div>
        <div className="row">
          <label>Телефон<input type="tel" maxLength={32} value={form.phone} onChange={(e) => set({ phone: e.target.value })} /></label>
          <label>Контакт для экстренной связи<input maxLength={128} value={form.emergency_contact} onChange={(e) => set({ emergency_contact: e.target.value })} /></label>
        </div>
        <fieldset>
          <legend>Диагнозы (первый — основной)</legend>
          <RowsEditor rows={diagnoses} onChange={setDiagnoses} labels={['Код МКБ-10', 'Формулировка']} placeholders={['F41.1', '']} />
        </fieldset>
        <fieldset>
          <legend>Принимаемые препараты</legend>
          <RowsEditor rows={meds} onChange={setMeds} labels={['Препарат', 'Доза и режим']} />
        </fieldset>
        <fieldset>
          <legend>Ранее проведённая терапия</legend>
          <CoursesEditor rows={courses} onChange={setCourses} />
        </fieldset>
        <label>
          Аллергии (через запятую)
          <input value={form.allergies} onChange={(e) => set({ allergies: e.target.value })} />
        </label>
        <label className="checkbox">
          <input type="checkbox" checked={form.in_person_visit} onChange={(e) => set({ in_person_visit: e.target.checked })} />
          Пациент на очном приёме, диагноз установлен
        </label>
        <ErrorMessage error={submit.error} />
        <button type="submit" disabled={submit.pending}>Добавить пациента</button>
      </form>
    </>
  )
}
