import { Link } from 'react-router-dom'
import { useApi } from '../api/useApi'
import { Loader } from '../components/Loader'

interface AboutData {
  service?: string
  status?: string
  data_storage?: string
  telemedicine_basis?: string
  related_materials_retention_days?: number
  [key: string]: unknown
}

const LABELS: Record<string, string> = {
  service: 'Сервис',
  status: 'Статус',
  data_storage: 'Хранение данных',
  telemedicine_basis: 'Основание телемедицины',
  related_materials_retention_days: 'Срок хранения сопутствующих материалов (дней)',
  version: 'Версия',
  environment: 'Среда',
  build: 'Сборка',
  privacy: 'Конфиденциальность',
  operator: 'Оператор',
}

function labelFor(key: string): string {
  if (LABELS[key]) return LABELS[key]
  return key
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

function formatValue(value: unknown): string {
  if (value == null || value === '') return '—'
  if (typeof value === 'boolean') return value ? 'Да' : 'Нет'
  if (typeof value === 'object') return JSON.stringify(value, null, 2)
  return String(value)
}

export function AboutPage() {
  const state = useApi<AboutData>('/api/about')

  return (
    <div className="about-page">
      <section className="about-card">
        <div className="about-brand">
          <span className="brand-symbol" aria-hidden="true"><span /><span /><span /></span>
          <span>Клинический компас</span>
        </div>
        <h1>О сервисе</h1>
        <p className="about-lead">
          Сведения о работе сервиса и обработке данных. Ниже — актуальные параметры с сервера.
        </p>

        <Loader state={state}>
          {(about) => (
            <div className="about-grid">
              {Object.entries(about).map(([key, value]) => (
                <article key={key} className="about-item">
                  <h2 className="about-item-title">{labelFor(key)}</h2>
                  <p className="about-item-value">{formatValue(value)}</p>
                </article>
              ))}
            </div>
          )}
        </Loader>

        <div className="about-actions">
          <Link to="/login" className="button-anchor">Перейти ко входу</Link>
        </div>
      </section>
    </div>
  )
}
