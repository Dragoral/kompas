import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../api/client'
import { useAction } from '../../api/useApi'
import { ErrorMessage } from '../../components/ErrorMessage'
import {
  CoursesEditor, RowsEditor, rowsToCourses, rowsToDiagnoses, rowsToMeds, type Course, type Row,
} from '../../components/PatientFields'

interface Created {
  id: number
  code: string
  login: string
  temporary_password: string
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
    diagnoses: rowsToDiagnoses(diagnoses),
    current_meds: rowsToMeds(meds),
    therapy_history: rowsToCourses(courses),
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
