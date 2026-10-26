import { Link } from 'react-router-dom'
import { useApi } from '../api/useApi'
import { Loader } from '../components/Loader'

interface AboutData { service?: string; status?: string; data_storage?: string; telemedicine_basis?: string; related_materials_retention_days?: number; [key: string]: unknown }

export function AboutPage() {
  const state = useApi<AboutData>('/api/about')
  return <div className="login-page about-page"><section className="about-card"><div className="login-brand"><span className="app-brand-mark">✚</span><span>Клинический компас</span></div><h1>О сервисе</h1><p className="muted">Информация о сервисе и обработке данных, предоставленная backend.</p><Loader state={state}>{(about) => <dl className="summary">{Object.entries(about).map(([key, value]) => <div key={key} className="about-field"><dt>{key.replace('_', ' ')}</dt><dd>{typeof value === 'object' ? JSON.stringify(value) : String(value ?? '—')}</dd></div>)}</dl>}</Loader><p><Link to="/login" className="button-primary button-anchor">Перейти ко входу</Link></p><p className="muted small">Эта страница показывает сведения непосредственно из API, а не из статического текста.</p></section></div>
}
