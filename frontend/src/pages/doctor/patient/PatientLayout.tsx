import { NavLink, Outlet, useOutletContext, useParams } from 'react-router-dom'
import type { PatientCard } from '../../../api/types'
import { useApi } from '../../../api/useApi'
import { Loader } from '../../../components/Loader'
import { formatRegimen } from '../../../format'

export interface PatientContext {
  id: string
  card: PatientCard
  reload: () => void
}

export function usePatient(): PatientContext {
  return useOutletContext<PatientContext>()
}

const TABS = [
  { to: '', label: 'Обзор', end: true },
  { to: 'therapy', label: 'Терапия' },
  { to: 'scales', label: 'Шкалы' },
  { to: 'history', label: 'Динамика' },
  { to: 'messages', label: 'Сообщения' },
]

export function PatientLayout() {
  const { id = '' } = useParams()
  const state = useApi<PatientCard>(`/api/doctor/patients/${id}`)

  return (
    <Loader state={state}>
      {(c) => (
        <>
          <h1>{c.header.full_name}</h1>
          <dl className="summary">
            <dt>Код</dt><dd>{c.patient.code}</dd>
            <dt>Возраст, пол</dt><dd>{c.header.age ?? '—'}, {c.header.sex === 'f' ? 'ж' : 'м'}</dd>
            <dt>ИМТ</dt><dd>{c.header.bmi ?? '—'}</dd>
            <dt>Диагнозы</dt>
            <dd>{c.header.diagnoses.map((d) => `${d.icd10}${d.title ? ` ${d.title}` : ''}`).join('; ') || '—'}</dd>
            <dt>Препараты</dt>
            <dd>{c.header.medications.map((m) => [m.name, m.regimen ? formatRegimen(m.regimen) : m.dose].filter(Boolean).join(', ')).join('; ') || '—'}</dd>
            <dt>Аллергии</dt><dd>{c.header.allergies.join(', ') || 'нет данных'}</dd>
          </dl>
          <nav aria-label="Разделы карточки">
            <ul className="tabs">
              {TABS.map((t) => (
                <li key={t.to}><NavLink to={t.to} end={t.end}>{t.label}</NavLink></li>
              ))}
            </ul>
          </nav>
          <Outlet context={{ id, card: c, reload: state.reload } satisfies PatientContext} />
        </>
      )}
    </Loader>
  )
}
