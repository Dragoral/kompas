import { useState, type FormEvent } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { ApiError } from '../api/client'
import type { Role } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { ErrorMessage } from '../components/ErrorMessage'
import { homePath } from '../components/RequireRole'

function BrandMark() {
  return <span className="brand-symbol" aria-hidden="true"><span/><span/><span/></span>
}

export function LoginPage() {
  const { user, login, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [form, setForm] = useState({ login: '', password: '', totp: '' })
  const [selectedRole, setSelectedRole] = useState<Role | ''>('')
  const [error, setError] = useState<ApiError | null>(null)
  const [pending, setPending] = useState(false)

  if (user) return <Navigate to={(user.must_change_password || user.mfa_setup_required) ? '/account' : homePath(user.role)} replace />

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault()
    if (!selectedRole) {
      setError(new ApiError(400, 'Сначала выберите роль для входа.', null))
      return
    }
    setPending(true)
    setError(null)
    try {
      const u = await login(form.login.trim(), form.password, form.totp.trim())
      // The selector is a UX step only. The server remains authoritative for the account role.
      if (u.role !== selectedRole) {
        await logout()
        setError(new ApiError(403, `У этой учётной записи другая роль. Выберите роль «${({ doctor: 'Врач', patient: 'Пациент', admin: 'Администратор' } as const)[u.role]}» и повторите вход.`, null))
        return
      }
      const from = (location.state as { from?: string } | null)?.from
      navigate((u.must_change_password || u.mfa_setup_required) ? '/account' : (from ?? homePath(u.role)), { replace: true })
    } catch (err) {
      setError(err as ApiError)
    } finally {
      setPending(false)
    }
  }

  return (
    <main id="main" className="login-page">
      <section className="login-showcase" aria-label="О клиническом компасе">
        <div className="login-brand"><BrandMark/><span>Клинический компас</span></div>
        <div className="login-hero">
          <span className="login-eyebrow">Цифровой помощник врача</span>
          <h1>Внимание к деталям. Забота о человеке.</h1>
          <p>Единое пространство для наблюдения за динамикой состояния, коммуникации врача и пациента и поддержки клинических решений.</p>
          <ul className="login-feature-list">
            <li><span>✓</span> Единая история наблюдения и самоотчётов</li>
            <li><span>✓</span> Выделение сигналов, требующих внимания</li>
            <li><span>✓</span> Подтверждение клинических действий специалистом</li>
          </ul>
        </div>
        <div className="login-footnote">@by негрусteam · Защищённое рабочее пространство</div>
      </section>
      <section className="login-form-side" aria-label="Вход в систему">
        <div className="login-card">
          <h2>Добро пожаловать</h2>
          <p>Сначала выберите свою роль, затем введите данные учётной записи.</p>
          <form onSubmit={onSubmit} className="form">
            <ErrorMessage error={error} />
            <div className="role-picker" role="group" aria-labelledby="role-picker-title" aria-describedby="role-picker-help">
              <div id="role-picker-title" className="role-picker-title">Выберите роль</div>
              <div className="role-picker-options">
                {([
                  ['doctor', 'Врач', 'Клиника', '♧'],
                  ['patient', 'Пациент', 'Кабинет', '♡'],
                  ['admin', 'Админ', 'Система', '⚙'],
                ] as const).map(([role, title, description, symbol]) => (
                  <button key={role} type="button" className={`role-choice${selectedRole === role ? ' role-choice-active' : ''}`} aria-pressed={selectedRole === role} onClick={() => { setSelectedRole(role); setError(null) }}>
                    <span className="role-choice-symbol" aria-hidden="true">{symbol}</span>
                    <span className="role-choice-copy"><strong>{title}</strong><small>{description}</small></span>
                    <span className="role-choice-check" aria-hidden="true">{selectedRole === role ? '✓' : ''}</span>
                  </button>
                ))}
              </div>
              <p id="role-picker-help" className="role-picker-help">После входа откроется кабинет выбранной роли. Если роль не совпадёт с учётной записью, система сообщит об этом.</p>
            </div>
            <div className="login-credentials-title">Данные для входа</div>
            <label>
              Логин
              <input name="login" autoComplete="username" autoCapitalize="none" required disabled={!selectedRole} value={form.login}
                     onChange={(e) => setForm({ ...form, login: e.target.value })} placeholder="Введите логин" />
            </label>
            <label>
              Пароль
              <input name="password" type="password" autoComplete="current-password" required disabled={!selectedRole} value={form.password}
                     onChange={(e) => setForm({ ...form, password: e.target.value })} placeholder="Введите пароль" />
            </label>
            <label>
              Код подтверждения <span className="muted">(если включён второй фактор)</span>
              <input name="totp" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6} disabled={!selectedRole} value={form.totp}
                     onChange={(e) => setForm({ ...form, totp: e.target.value.replace(/\D/g, '').slice(0, 6) })} placeholder="000000" />
            </label>
            <button type="submit" disabled={pending || !selectedRole}>{pending ? 'Выполняется вход…' : 'Войти в систему'} <span aria-hidden="true">→</span></button>
          </form>
          <div className="login-security-note">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 22s8-4 8-11V5l-8-3-8 3v6c0 7 8 11 8 11Z"/><path d="m9 12 2 2 4-4"/></svg>
            <span>Не передавайте пароль и код подтверждения другим лицам. Выходите из учётной записи после завершения работы.</span>
          </div>
        </div>
      </section>
      <p className="login-about-link"><a href="/about">О сервисе и обработке данных</a></p>
      <footer className="login-disclaimer" aria-label="Юридический дисклеймер">
        <p><strong>Юридическое уведомление и дисклеймер ответственности:</strong> Данный сервис функционирует исключительно в качестве ознакомительного поисково-аналитического инструмента. Любая сгенерированная агентом информация базируется на сторонних текстовых публикациях и языковых закономерностях, ввиду чего может содержать неточности. Категорически запрещается использовать ответы системы для назначения лекарственных средств, изменения схем терапии или принятия любых юридически значимых клинических решений. Постановка диагноза и выбор терапии должны осуществляться строго дипломированным специалистом на основании очного осмотра, результатов лабораторно-инструментальных исследований и действующих национальных клинических рекомендаций. Принятие медицинских решений исключительно на основе текстовых выжимок искусственного интеллекта без надлежащей верификации влечет за собой прямую <strong>административную и уголовную ответственность</strong> в соответствии с действующим законодательством РФ.</p>
      </footer>
    </main>
  )
}
