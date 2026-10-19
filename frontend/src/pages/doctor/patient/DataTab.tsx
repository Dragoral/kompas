import { useState, type FormEvent } from 'react'
import { api } from '../../../api/client'
import { useAction, useApi } from '../../../api/useApi'
import { ErrorMessage } from '../../../components/ErrorMessage'
import {
  coursesToRows, CoursesEditor, diagnosesToRows, medsToRows, RowsEditor, rowsToCourses, rowsToDiagnoses, rowsToMeds,
} from '../../../components/PatientFields'
import { formatDateTime } from '../../../format'
import { usePatient } from './PatientLayout'

export function DataTab() {
  return (
    <>
      <MedicalDataForm />
      <ThresholdsForm />
      <Documents />
    </>
  )
}

function MedicalDataForm() {
  const { id, card, reload } = usePatient()
  const p = card.patient
  const [diagnoses, setDiagnoses] = useState(() => diagnosesToRows(p.diagnoses))
  const [meds, setMeds] = useState(() => medsToRows(p.current_meds))
  const [courses, setCourses] = useState(() => coursesToRows(p.therapy_history))
  const [profile, setProfile] = useState({
    height_cm: p.profile.height_cm?.toString() ?? '',
    weight_kg: p.profile.weight_kg?.toString() ?? '',
    allergies: (p.profile.allergies ?? []).join(', '),
  })
  const [saved, setSaved] = useState(false)
  const save = useAction(() => api.patch(`/api/doctor/patients/${id}`, {
    profile: {
      ...p.profile,
      height_cm: profile.height_cm ? Number(profile.height_cm) : undefined,
      weight_kg: profile.weight_kg ? Number(profile.weight_kg) : undefined,
      allergies: profile.allergies.split(',').map((s) => s.trim()).filter(Boolean),
    },
    diagnoses: rowsToDiagnoses(diagnoses),
    current_meds: rowsToMeds(meds),
    therapy_history: rowsToCourses(courses),
  }))

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setSaved(false)
    if (await save.run()) {
      setSaved(true)
      reload()
    }
  }

  return (
    <form className="form" onSubmit={onSubmit} aria-labelledby="data-h">
      <h2 id="data-h">Медицинские данные</h2>
      <p className="muted">Рекомендации и проверки противопоказаний пересчитываются после сохранения.</p>
      <div className="row">
        <label>Рост, см<input type="number" min={50} max={250} value={profile.height_cm} onChange={(e) => setProfile({ ...profile, height_cm: e.target.value })} /></label>
        <label>Вес, кг<input type="number" min={20} max={300} step={0.1} value={profile.weight_kg} onChange={(e) => setProfile({ ...profile, weight_kg: e.target.value })} /></label>
      </div>
      <fieldset>
        <legend>Диагнозы (первый — основной)</legend>
        <RowsEditor rows={diagnoses} onChange={setDiagnoses} labels={['Код МКБ-10', 'Формулировка']} placeholders={['F41.1', '']} />
      </fieldset>
      <fieldset>
        <legend>Принимаемые препараты (назначенные другими врачами)</legend>
        <RowsEditor rows={meds} onChange={setMeds} labels={['Препарат', 'Доза и режим']} />
      </fieldset>
      <fieldset>
        <legend>Ранее проведённая терапия</legend>
        <CoursesEditor rows={courses} onChange={setCourses} />
      </fieldset>
      <label>
        Аллергии (через запятую)
        <input value={profile.allergies} onChange={(e) => setProfile({ ...profile, allergies: e.target.value })} />
      </label>
      <ErrorMessage error={save.error} />
      {saved && <p className="message" role="status">Сохранено.</p>}
      <button type="submit" disabled={save.pending}>Сохранить</button>
    </form>
  )
}

interface AlertRules {
  body: { thresholds?: Record<string, { default: number; title?: string }> }
}

function ThresholdsForm() {
  const { id, card, reload } = usePatient()
  const rules = useApi<AlertRules>('/api/knowledge/rules/alerts')
  const [overrides, setOverrides] = useState<Record<string, string>>(() =>
    Object.fromEntries(Object.entries(card.patient.threshold_overrides ?? {}).map(([k, v]) => [k, String(v)])))
  const [saved, setSaved] = useState(false)
  const save = useAction(() => api.patch(`/api/doctor/patients/${id}`, {
    alert_thresholds: Object.fromEntries(Object.entries(overrides).filter(([, v]) => v !== '').map(([k, v]) => [k, Number(v)])),
  }))

  const defs = rules.data?.body.thresholds ?? {}

  return (
    <form className="form" aria-labelledby="thr-h" onSubmit={async (e) => {
      e.preventDefault()
      setSaved(false)
      if (await save.run()) {
        setSaved(true)
        reload()
      }
    }}>
      <h2 id="thr-h">Индивидуальные пороги оповещений</h2>
      <p className="muted">Пустое поле — значение по умолчанию для всех пациентов.</p>
      <ErrorMessage error={rules.error} />
      <div className="table-wrap">
        <table className="compact">
          <thead>
            <tr><th scope="col">Порог</th><th scope="col">По умолчанию</th><th scope="col">Для этого пациента</th></tr>
          </thead>
          <tbody>
            {Object.entries(defs).map(([key, d]) => (
              <tr key={key}>
                <td>{d.title ?? key}</td>
                <td>{d.default}</td>
                <td className="col-number">
                  <input type="number" min={0} step="any" aria-label={d.title ?? key} value={overrides[key] ?? ''}
                         onChange={(e) => setOverrides({ ...overrides, [key]: e.target.value })} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ErrorMessage error={save.error} />
      {saved && <p className="message" role="status">Пороги сохранены.</p>}
      <button type="submit" disabled={save.pending}>Сохранить пороги</button>
    </form>
  )
}

interface Extracted {
  id: number
  extractor: string
  elapsed_ms: number
  data: {
    diagnoses: { icd10: string; title?: string }[]
    medications: { name?: string; inn?: string | null; dose?: string | null }[]
    past_medications: { inn?: string | null; dose?: string | null }[]
    allergies: string[]
    conditions: string[]
    egfr: number | null
    pregnant: boolean | null
  }
}

function Documents() {
  const { id, card, reload } = usePatient()
  const [text, setText] = useState('')
  const [filename, setFilename] = useState('')
  const [result, setResult] = useState<Extracted | null>(null)
  const upload = useAction(() => api.post<Extracted>(`/api/doctor/patients/${id}/documents`, { filename: filename || 'Выписка', text }))
  const apply = useAction((did: number) => api.post(`/api/doctor/documents/${did}/apply`))

  const onFile = async (file: File | undefined) => {
    if (!file) return
    setFilename(file.name)
    setText(await file.text())
  }

  const onApply = async () => {
    if (result && await apply.run(result.id)) {
      setResult(null)
      setText('')
      reload()
    }
  }

  const d = result?.data
  return (
    <section aria-labelledby="docs-h">
      <h2 id="docs-h">Выписки и истории болезни</h2>
      <p>Система извлечёт из текста диагнозы, препараты, аллергии и сопутствующие состояния. Перед переносом в карточку проверьте результат.</p>
      <form className="form" onSubmit={async (e) => { e.preventDefault(); setResult((await upload.run()) ?? null) }}>
        <label>
          Файл (текст, .txt)
          <input type="file" accept=".txt,text/plain" onChange={(e) => onFile(e.target.files?.[0])} />
        </label>
        <label>
          Или вставьте текст
          <textarea rows={6} required minLength={10} maxLength={200000} value={text} onChange={(e) => setText(e.target.value)} />
        </label>
        <ErrorMessage error={upload.error} />
        <button type="submit" disabled={upload.pending}>Извлечь данные</button>
      </form>

      {d && (
        <div className="panel">
          <h3>Найдено в документе</h3>
          <dl className="summary">
            <dt>Диагнозы</dt><dd>{d.diagnoses.map((x) => `${x.icd10}${x.title ? ` ${x.title}` : ''}`).join('; ') || '—'}</dd>
            <dt>Препараты</dt><dd>{d.medications.map((m) => [m.name ?? m.inn, m.dose].filter(Boolean).join(' ')).join('; ') || '—'}</dd>
            <dt>Ранее принимал</dt><dd>{d.past_medications.map((m) => m.inn).filter(Boolean).join(', ') || '—'}</dd>
            <dt>Аллергии</dt><dd>{d.allergies.join(', ') || '—'}</dd>
            <dt>Состояния</dt><dd>{d.conditions.join(', ') || '—'}</dd>
            <dt>СКФ</dt><dd>{d.egfr ?? '—'}</dd>
            <dt>Беременность</dt><dd>{d.pregnant === null ? 'нет данных' : d.pregnant ? 'да' : 'нет'}</dd>
          </dl>
          <p className="muted small">Способ: {result.extractor === 'rules' ? 'по правилам и словарям' : result.extractor}, {result.elapsed_ms} мс</p>
          <ErrorMessage error={apply.error} />
          <div className="row">
            <button type="button" disabled={apply.pending} onClick={onApply}>Перенести в карточку</button>
            <button type="button" className="secondary" onClick={() => setResult(null)}>Не переносить</button>
          </div>
        </div>
      )}

      {card.documents.length > 0 && (
        <table>
          <caption>Загруженные документы</caption>
          <thead><tr><th scope="col">Файл</th><th scope="col">Загружен</th><th scope="col">Перенесён в карточку</th></tr></thead>
          <tbody>
            {card.documents.map((doc) => (
              <tr key={doc.id}><td>{doc.filename}</td><td>{formatDateTime(doc.created_at)}</td><td>{doc.applied ? 'Да' : 'Нет'}</td></tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}
