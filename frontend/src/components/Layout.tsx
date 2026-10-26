import { useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import type { Role } from '../api/types'
import { ROLE_LABEL } from '../format'
import { ErrorBoundary } from './ErrorBoundary'
import { api } from '../api/client'
import { subscribe } from '../api/stream'
import { PatientOfflineSyncPanel } from './PatientOfflineSyncPanel'

type IconName = 'grid' | 'users' | 'bell' | 'book' | 'clipboard' | 'activity' | 'message' | 'calendar' | 'user' | 'settings' | 'shield' | 'database' | 'clock' | 'file' | 'heart' | 'phone' | 'search' | 'plus' | 'logout' | 'chevron' | 'menu' | 'close' | 'external'

function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  const common = { width: size, height: size, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const, 'aria-hidden': true as const }
  const paths: Record<IconName, ReactNode> = {
    grid: <><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></>,
    users: <><path d="M16 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="10" cy="7" r="4"/><path d="M20 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/></>,
    bell: <><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9"/><path d="M10 21h4"/></>,
    book: <><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v17H6.5A2.5 2.5 0 0 1 4 17.5z"/><path d="M4 17.5A2.5 2.5 0 0 1 6.5 15H20M8 7h8M8 10h6"/></>,
    clipboard: <><rect x="5" y="5" width="14" height="16" rx="2"/><path d="M9 5V3h6v2M8 10h8M8 14h8M8 18h5"/></>,
    activity: <><path d="M3 12h4l3-8 4 16 3-8h4"/></>,
    message: <><path d="M21 11.5a7.5 7.5 0 0 1-7.5 7.5H6l-3 2v-6.5A7.5 7.5 0 1 1 21 11.5Z"/><path d="M8 11h8M8 14h5"/></>,
    calendar: <><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M16 3v4M8 3v4M3 10h18M7 14h3M7 17h3"/></>,
    user: <><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/></>,
    settings: <><circle cx="12" cy="12" r="3"/><path d="m19.4 15 .1.1 1.1 1.9-2 3.4-2.2-.5a8 8 0 0 1-1.8 1L14 23h-4l-.6-2.1a8 8 0 0 1-1.8-1l-2.2.5-2-3.4 1.1-1.9A8 8 0 0 1 4.5 12c0-.7.1-1.4.3-2.1L3.7 8l2-3.4 2.2.5a8 8 0 0 1 1.8-1L10.3 2h4l.6 2.1a8 8 0 0 1 1.8 1l2.2-.5 2 3.4-1.1 1.9c.2.7.3 1.4.3 2.1s-.2 1.4-.7 2Z"/></>,
    shield: <><path d="M12 22s8-4 8-11V5l-8-3-8 3v6c0 7 8 11 8 11Z"/><path d="m9 12 2 2 4-4"/></>,
    database: <><ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/></>,
    clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
    file: <><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/><path d="M14 2v6h6M8 13h8M8 17h8"/></>,
    heart: <><path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8l1.1 1.1L12 21l7.8-7.5 1.1-1.1a5.5 5.5 0 0 0-.1-7.8Z"/></>,
    phone: <><path d="M22 16.9v3a2 2 0 0 1-2.2 2A19.8 19.8 0 0 1 11.2 19a19.4 19.4 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7l.4 2.5a2 2 0 0 1-.6 1.7L7.6 9.2a16 16 0 0 0 7.2 7.2l1.3-1.3a2 2 0 0 1 1.7-.6l2.5.4a2 2 0 0 1 1.7 2Z"/></>,
    search: <><circle cx="10.8" cy="10.8" r="6.8"/><path d="m16 16 5 5"/></>,
    plus: <><path d="M12 5v14M5 12h14"/></>,
    logout: <><path d="M10 17l5-5-5-5M15 12H3"/><path d="M12 3h6a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-6"/></>,
    chevron: <path d="m9 18 6-6-6-6"/>,
    menu: <><path d="M4 6h16M4 12h16M4 18h16"/></>,
    close: <><path d="m6 6 12 12M18 6 6 18"/></>,
    external: <><path d="M14 3h7v7M10 14 21 3"/><path d="M19 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h6"/></>,
  }
  return <svg {...common}>{paths[name]}</svg>
}

type NavItem = { to: string; label: string; icon: IconName; end?: boolean; badge?: string }
type NavGroup = { label: string; items: NavItem[] }
const NAV: Record<Role, NavGroup[]> = {
  doctor: [
    { label: 'Клиническая работа', items: [
      { to: '/doctor/patients', label: 'Пациенты', icon: 'users' },
      { to: '/doctor/actions', label: 'Очередь клинических решений', icon: 'clipboard' },
      { to: '/doctor/alerts', label: 'Оповещения', icon: 'bell' },
    ] },
    { label: 'Инструменты', items: [
      { to: '/knowledge', label: 'База знаний', icon: 'book', end: true },
    ] },
  ],
  patient: [
    { label: 'Моё здоровье', items: [
      { to: '/me', label: 'Обзор', icon: 'grid', end: true },
      { to: '/me/diary', label: 'Дневник самочувствия', icon: 'activity' },
      { to: '/me/history', label: 'Динамика', icon: 'calendar' },
      { to: '/me/messages', label: 'Сообщения', icon: 'message' },
    ] },
    { label: 'Мои данные', items: [
      { to: '/me/adverse-event', label: 'Нежелательная реакция', icon: 'heart' },
      { to: '/me/trusted-contacts', label: 'Доверенные контакты', icon: 'phone' },
      { to: '/me/data', label: 'Личные данные', icon: 'user' },
    ] },
  ],
  admin: [
    { label: 'Управление', items: [
      { to: '/admin/system', label: 'Состояние системы', icon: 'activity' },
      { to: '/admin/metrics', label: 'Технические метрики', icon: 'activity' },
      { to: '/analytics', label: 'Клиническая аналитика', icon: 'activity' },
      { to: '/admin/users', label: 'Пользователи', icon: 'users' },
      { to: '/admin/patients', label: 'Пациенты', icon: 'heart' },
      { to: '/admin/audit', label: 'Журнал аудита', icon: 'clipboard' },
      { to: '/admin/notifications', label: 'Журнал уведомлений', icon: 'bell' },
    ] },
    { label: 'Клинические данные', items: [
      { to: '/knowledge', label: 'База знаний', icon: 'book', end: true },
    ] },
  ],
}

const PAGE_TITLES: Array<[string, string]> = [
  ['/doctor/patients/new', 'Новый пациент'], ['/doctor/patients', 'Пациенты'], ['/doctor/actions', 'Очередь решений'], ['/doctor/alerts', 'Оповещения'], ['/analytics', 'Клиническая аналитика'], ['/admin/metrics', 'Технические метрики'], ['/about', 'О сервисе'],
  ['/knowledge/review', 'Согласование знаний'], ['/knowledge/import', 'Импорт шкалы'], ['/knowledge', 'База знаний'],
  ['/admin/system', 'Состояние системы'], ['/admin/users', 'Пользователи'], ['/admin/patients', 'Пациенты'], ['/admin/audit', 'Журнал аудита'], ['/admin/notifications', 'Журнал уведомлений'],
  ['/me/diary', 'Дневник самочувствия'], ['/me/history', 'Динамика состояния'], ['/me/messages', 'Сообщения'], ['/me/adverse-event', 'Нежелательная реакция'], ['/me/trusted-contacts', 'Доверенные контакты'], ['/me/data', 'Личные данные'], ['/me', 'Мой обзор'], ['/account', 'Учётная запись'],
]

type AlertEvent = { id: number; patient_id: number; severity: 'critical' | 'high' | 'medium'; title: string }

function DoctorAlertWatcher() {
  const [live, setLive] = useState<AlertEvent[]>([])
  useEffect(() => subscribe('/api/doctor/stream', ['alert'], (_event, data) => {
    const alert = data as AlertEvent
    if (!alert || typeof alert.id !== 'number') return
    void api.post(`/api/doctor/alerts/${alert.id}/delivered`).catch(() => undefined)
    setLive((items) => [alert, ...items.filter((item) => item.id !== alert.id)].slice(0, 4))
    if (alert.severity === 'critical' && typeof window !== 'undefined' && 'Notification' in window && Notification.permission === 'granted') {
      new Notification('Критическое оповещение — Компас', { body: alert.title, requireInteraction: true })
    }
  }), [])
  if (!live.length) return null
  return <section className="live-alerts shell-live-alerts" role="alert" aria-label="Новые оповещения">
    <div className="live-alerts-heading"><span className="live-pulse"/><strong>Новые оповещения</strong><span className="muted">{live.length}</span></div>
    <ul>{live.map((alert) => <li key={alert.id}>
      <Link to={`/doctor/patients/${alert.patient_id}`}>{alert.title}</Link>
      <span className={`badge badge-${alert.severity}`}>{alert.severity === 'critical' ? 'Критично' : alert.severity === 'high' ? 'Высокий' : 'Средний'}</span>
    </li>)}</ul>
  </section>
}

function PatientLiveWatcher() {
  const [crisis, setCrisis] = useState(false)
  const [therapyChanged, setTherapyChanged] = useState(false)
  const [referralChanged, setReferralChanged] = useState(false)
  useEffect(() => subscribe('/api/me/stream', ['crisis', 'therapy_changed', 'referral'], (event) => {
    if (event === 'crisis') setCrisis(true)
    if (event === 'therapy_changed') setTherapyChanged(true)
    if (event === 'referral') setReferralChanged(true)
  }), [])
  return <>
    {crisis && <div className="live-alerts live-alerts-critical shell-patient-alert" role="alert">
      <strong>Важное уведомление о безопасности</strong>
      <p>Откройте рекомендации на главной странице. При непосредственной опасности звоните 112 или 103.</p>
      <Link to="/me">Открыть главную</Link>
      <button type="button" className="button-link" onClick={() => setCrisis(false)}>Скрыть</button>
    </div>}
    {referralChanged && <div className="live-alerts shell-patient-alert" role="status"><strong>Врач обновил маршрутизацию</strong><p>Проверьте новые сведения в личном кабинете.</p><Link to="/me/history">Посмотреть историю</Link><button type="button" className="button-link" onClick={() => setReferralChanged(false)}>Скрыть</button></div>}
    {therapyChanged && <div className="live-alerts shell-patient-alert" role="status">
      <strong>Врач обновил план терапии</strong>
      <p>Проверьте актуальную информацию в личном кабинете.</p>
      <Link to="/me/history">Посмотреть историю</Link>
      <button type="button" className="button-link" onClick={() => setTherapyChanged(false)}>Скрыть</button>
    </div>}
  </>
}

function initials(name: string): string {
  return name.trim().split(/\s+/).slice(0, 2).map((part) => part[0]?.toLocaleUpperCase('ru-RU') ?? '').join('') || 'К'
}

function currentTitle(pathname: string): string {
  if (pathname.startsWith('/me/scales/')) return 'Опросник самочувствия'
  if (/^\/knowledge\/[^/]+\/[^/]+\/versions(?:\/|$)/.test(pathname)) return 'Версии справочника'
  if (/^\/knowledge\/[^/]+\/[^/]+\/json(?:\/|$)/.test(pathname)) return 'Редактор справочника'
  if (pathname.startsWith('/knowledge/response-policy')) return 'Политика реагирования'
  if (pathname.startsWith('/knowledge/scales/')) return 'Редактор шкалы'
  if (pathname.startsWith('/knowledge/drugs/')) return 'Карточка препарата'
  if (pathname.startsWith('/knowledge/rules/')) return 'Редактор правил'
  if (/^\/doctor\/patients\/\d+\/therapy(?:\/|$)/.test(pathname)) return 'Терапия пациента'
  if (/^\/doctor\/patients\/\d+\/scales(?:\/|$)/.test(pathname)) return 'Шкалы пациента'
  if (/^\/doctor\/patients\/\d+\/history(?:\/|$)/.test(pathname)) return 'История пациента'
  if (/^\/doctor\/patients\/\d+\/messages(?:\/|$)/.test(pathname)) return 'Сообщения пациента'
  if (/^\/doctor\/patients\/\d+\/data(?:\/|$)/.test(pathname)) return 'Данные пациента'
  if (/^\/doctor\/patients\/\d+(?:\/|$)/.test(pathname) && !pathname.endsWith('/new')) return 'Карточка пациента'
  const match = [...PAGE_TITLES].sort((a, b) => b[0].length - a[0].length).find(([path]) => pathname === path || pathname.startsWith(`${path}/`))
  if (match) return match[1]
  if (pathname.includes('/therapy')) return 'Терапия'
  if (pathname.includes('/scales')) return 'Шкалы'
  if (pathname.includes('/messages')) return 'Сообщения'
  if (pathname.includes('/history')) return 'История'
  if (pathname.includes('/data')) return 'Данные пациента'
  return 'Рабочее пространство'
}

export function Layout() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  const [search, setSearch] = useState('')
  const role = user?.role
  const searchInputRef = useRef<HTMLInputElement>(null)
  const groups = user ? (user.role === 'doctor'
    ? NAV.doctor.map((group) => ({ ...group, items: group.items.filter((item) => item.to !== '/knowledge/review') }))
    : NAV[user.role]) : []
  if (user?.role === 'doctor' && user.is_reviewer) {
    groups.push({ label: 'Клиническое качество', items: [
      { to: '/knowledge/review', label: 'Согласование справочников', icon: 'clipboard' },
      { to: '/analytics', label: 'Клиническая аналитика', icon: 'activity' },
    ] })
  }
  const title = useMemo(() => currentTitle(location.pathname), [location.pathname])

  useEffect(() => { setMobileNavOpen(false) }, [location.pathname])
  useEffect(() => {
    if (role !== 'doctor') return
    const onSlash = (event: KeyboardEvent) => {
      if (event.key !== '/' || event.ctrlKey || event.metaKey || event.altKey) return
      const target = event.target
      if (target instanceof HTMLElement && (target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName))) return
      event.preventDefault()
      searchInputRef.current?.focus()
    }
    window.addEventListener('keydown', onSlash)
    return () => window.removeEventListener('keydown', onSlash)
  }, [role])
  useEffect(() => {
    if (!mobileNavOpen) return
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === 'Escape') setMobileNavOpen(false) }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [mobileNavOpen])

  if (!user) return null

  const onLogout = async () => {
    await logout()
    navigate('/login', { replace: true })
  }
  const onSearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const value = search.trim()
    if (!value) return
    navigate(`/doctor/patients?q=${encodeURIComponent(value)}`)
    setSearch('')
  }
  const quickAction = user.role === 'doctor'
    ? { to: '/doctor/patients/new', label: 'Новый пациент', icon: 'plus' as IconName }
    : user.role === 'patient'
      ? { to: '/me/diary', label: 'Заполнить дневник', icon: 'plus' as IconName }
      : { to: '/admin/users', label: 'Пользователи', icon: 'users' as IconName }

  return (
    <div className={`app-shell role-${user.role}`}>
      <a className="skip-link" href="#main">Перейти к содержимому</a>
      {mobileNavOpen && <button className="sidebar-backdrop" type="button" aria-label="Закрыть меню" onClick={() => setMobileNavOpen(false)} />}
      <aside className={`sidebar ${mobileNavOpen ? 'sidebar-open' : ''}`} aria-label="Боковая навигация">
        <Link to={user.role === 'patient' ? '/me' : user.role === 'admin' ? '/admin/system' : '/doctor/patients'} className="brand-lockup">
          <span className="brand-symbol"><span/><span/><span/></span>
          <span className="brand-copy"><strong>Клинический компас</strong><small>Сопровождение пациента</small></span>
        </Link>
        <div className="sidebar-profile">
          <span className={`role-avatar avatar-${user.role}`}>{initials(user.full_name)}</span>
          <span className="sidebar-profile-copy"><strong>{user.full_name}</strong><small>{ROLE_LABEL[user.role]}</small></span>
          <span className="profile-status" title="Вход выполнен" aria-label="Вход выполнен" />
        </div>
        <nav className="sidebar-nav" aria-label="Разделы приложения">
          {groups.map((group) => <div className="nav-group" key={group.label}>
            <div className="nav-group-label">{group.label}</div>
            {group.items.map((item) => <NavLink key={item.to} to={item.to} end={item.end} className={({ isActive }) => `side-link${isActive ? ' side-link-active' : ''}`}>
              <Icon name={item.icon} size={18}/><span>{item.label}</span>{item.badge && <span className="side-link-badge">{item.badge}</span>}
            </NavLink>)}
          </div>)}
        </nav>
        <div className="sidebar-bottom">
          <div className="sidebar-help-card"><span className="help-card-icon"><Icon name="shield" size={17}/></span><div><strong>Рабочее пространство</strong><p>Проверяйте данные и подтверждайте клинические действия.</p></div></div>
          <NavLink to="/account" className={({ isActive }) => `side-link sidebar-account${isActive ? ' side-link-active' : ''}`}><Icon name="settings"/><span>Настройки аккаунта</span></NavLink>
          <button type="button" className="side-link sidebar-logout" onClick={onLogout}><Icon name="logout"/><span>Выйти из системы</span></button>
          <div className="sidebar-version"><span className="sidebar-signature">@by негрусteam</span><span>Демо-версия</span></div>
        </div>
      </aside>

      <div className="workspace">
        <header className="topbar">
          <div className="topbar-left">
            <button type="button" className="mobile-menu-button icon-button" aria-label={mobileNavOpen ? 'Закрыть меню' : 'Открыть меню'} aria-expanded={mobileNavOpen} onClick={() => setMobileNavOpen((open) => !open)}><Icon name={mobileNavOpen ? 'close' : 'menu'} size={20}/></button>
            <div className="topbar-page"><div className="breadcrumbs"><span>Компас</span><Icon name="chevron" size={13}/><strong>{title}</strong></div><div className="topbar-subtitle">{user.role === 'doctor' ? 'Клиническая работа' : user.role === 'patient' ? 'Личный кабинет пациента' : 'Администрирование системы'}</div></div>
          </div>
          <div className="topbar-actions">
            {user.role === 'doctor' && <form className="global-search" role="search" onSubmit={onSearch}><Icon name="search" size={17}/><input ref={searchInputRef} aria-label="Поиск пациента" placeholder="Найти пациента…" value={search} onChange={(event) => setSearch(event.target.value)}/><kbd>/</kbd></form>}
            <Link className="quick-action" to={quickAction.to}><Icon name={quickAction.icon} size={17}/><span>{quickAction.label}</span></Link>
            {user.role === 'doctor' && <Link to="/doctor/alerts" className="topbar-icon-link" aria-label="Оповещения" title="Оповещения"><Icon name="bell" size={19}/></Link>}
            <span className="topbar-separator"/>
            <div className="topbar-user"><span className={`role-avatar avatar-${user.role}`}>{initials(user.full_name)}</span><div><strong>{user.full_name}</strong><small>{ROLE_LABEL[user.role]}</small></div></div>
          </div>
        </header>
        {user.role === 'doctor' && <DoctorAlertWatcher/>}
        {user.role === 'patient' && <><PatientOfflineSyncPanel/><PatientLiveWatcher/></>}
        <main id="main" className="app-main">
          <div className="page-container">
            <ErrorBoundary resetKey={location.pathname}><Outlet/></ErrorBoundary>
          </div>
        </main>
      </div>
    </div>
  )
}
