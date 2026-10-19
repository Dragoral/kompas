import { useState, type FormEvent } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { ApiError } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { ErrorMessage } from '../components/ErrorMessage'
import { homePath } from '../components/RequireRole'

export function LoginPage() {
  const { user, login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [form, setForm] = useState({ login: '', password: '', totp: '' })
  const [error, setError] = useState<ApiError | null>(null)
  const [pending, setPending] = useState(false)

  if (user) return <Navigate to={homePath(user.role)} replace />

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setPending(true)
    setError(null)
    try {
      const u = await login(form.login, form.password, form.totp)
      const from = (location.state as { from?: string } | null)?.from
      navigate(from ?? homePath(u.role), { replace: true })
    } catch (err) {
      setError(err as ApiError)
    } finally {
      setPending(false)
    }
  }

  return (
    <main id="main" className="container narrow">
      <h1>Вход в систему «Компас»</h1>
      <form onSubmit={onSubmit} className="form">
        <ErrorMessage error={error} />
        <label>
          Логин
          <input name="login" autoComplete="username" required value={form.login}
                 onChange={(e) => setForm({ ...form, login: e.target.value })} />
        </label>
        <label>
          Пароль
          <input name="password" type="password" autoComplete="current-password" required value={form.password}
                 onChange={(e) => setForm({ ...form, password: e.target.value })} />
        </label>
        <label>
          Код подтверждения <span className="muted">(если подключён второй фактор)</span>
          <input name="totp" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" value={form.totp}
                 onChange={(e) => setForm({ ...form, totp: e.target.value })} />
        </label>
        <button type="submit" disabled={pending}>{pending ? 'Вход…' : 'Войти'}</button>
      </form>
    </main>
  )
}
