import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import type { Role } from '../api/types'
import { ROLE_LABEL } from '../format'
import { ErrorBoundary } from './ErrorBoundary'

const NAV: Record<Role, { to: string; label: string }[]> = {
  doctor: [
    { to: '/doctor/patients', label: 'Пациенты' },
    { to: '/doctor/alerts', label: 'Оповещения' },
    { to: '/knowledge', label: 'Справочники' },
  ],
  patient: [
    { to: '/me', label: 'Главная' },
    { to: '/me/diary', label: 'Дневник' },
    { to: '/me/history', label: 'Моя история' },
    { to: '/me/messages', label: 'Сообщения' },
    { to: '/me/trusted-contacts', label: 'Доверенное лицо' },
    { to: '/me/data', label: 'Мои данные' },
  ],
  admin: [
    { to: '/admin/system', label: 'Состояние системы' },
    { to: '/admin/users', label: 'Пользователи' },
    { to: '/admin/patients', label: 'Пациенты' },
    { to: '/admin/audit', label: 'Журнал аудита' },
    { to: '/knowledge', label: 'Справочники' },
  ],
}

export function Layout() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  if (!user) return null

  const onLogout = async () => {
    await logout()
    navigate('/login', { replace: true })
  }

  return (
    <>
      <a className="skip-link" href="#main">Перейти к содержимому</a>
      <header className="app-header">
        <div className="container header-row">
          <span className="brand">Компас</span>
          <nav aria-label="Основное меню">
            <ul className="nav">
              {NAV[user.role].map((item) => (
                <li key={item.to}>
                  <NavLink to={item.to} end={item.to === '/me'}>{item.label}</NavLink>
                </li>
              ))}
            </ul>
          </nav>
          <div className="user-box">
            {user.role !== 'patient' && <span>{user.full_name} <span className="muted">({ROLE_LABEL[user.role]})</span></span>}
            <NavLink to="/account">Учётная запись</NavLink>
            <button type="button" className="button-link" onClick={onLogout}>Выйти</button>
          </div>
        </div>
      </header>
      <main id="main" className="container">
        <ErrorBoundary resetKey={location.pathname}>
          <Outlet />
        </ErrorBoundary>
      </main>
    </>
  )
}
