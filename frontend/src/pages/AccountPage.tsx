import QRCode from 'qrcode'
import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, setToken } from '../api/client'
import { useAction } from '../api/useApi'
import { useAuth } from '../auth/AuthContext'
import { ErrorMessage } from '../components/ErrorMessage'

export function AccountPage() {
  const { user } = useAuth()
  if (!user) return null
  return (
    <>
      <h1>Учётная запись</h1>
      <dl className="summary">
        <dt>Логин</dt><dd><code>{user.login}</code></dd>
        {user.role !== 'patient' && <><dt>ФИО</dt><dd>{user.full_name}</dd></>}
        <dt>Второй фактор</dt><dd>{user.mfa_enabled ? 'Подключён' : 'Не подключён'}</dd>
      </dl>
      <PasswordForm />
      {!user.mfa_enabled && <MfaSetup />}
    </>
  )
}

function PasswordForm() {
  const navigate = useNavigate()
  const [form, setForm] = useState({ old_password: '', new_password: '', repeat: '' })
  const change = useAction(() => api.post('/api/auth/password', { old_password: form.old_password, new_password: form.new_password }))
  const mismatch = form.repeat !== '' && form.repeat !== form.new_password

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault()
    if (mismatch) return
    if (await change.run()) {
      // после смены пароля все сеансы завершены — нужен повторный вход
      setToken(null)
      navigate('/login', { replace: true })
      window.location.reload()
    }
  }

  return (
    <form className="form" onSubmit={onSubmit} aria-labelledby="password-h">
      <h2 id="password-h">Смена пароля</h2>
      <label>
        Текущий пароль
        <input type="password" required autoComplete="current-password" value={form.old_password}
               onChange={(e) => setForm({ ...form, old_password: e.target.value })} />
      </label>
      <label>
        Новый пароль
        <input type="password" required minLength={10} autoComplete="new-password" aria-describedby="password-hint"
               value={form.new_password} onChange={(e) => setForm({ ...form, new_password: e.target.value })} />
        <span id="password-hint" className="muted small">Не короче 10 символов и без логина. После смены потребуется войти заново на всех устройствах.</span>
      </label>
      <label>
        Новый пароль ещё раз
        <input type="password" required autoComplete="new-password" aria-invalid={mismatch} value={form.repeat}
               onChange={(e) => setForm({ ...form, repeat: e.target.value })} />
        {mismatch && <span className="small" role="alert">Пароли не совпадают</span>}
      </label>
      <ErrorMessage error={change.error} />
      <button type="submit" disabled={change.pending || mismatch}>Сменить пароль</button>
    </form>
  )
}

function MfaSetup() {
  const [setup, setSetup] = useState<{ secret: string; otpauth_uri: string } | null>(null)
  const [qr, setQr] = useState('')
  const [code, setCode] = useState('')
  const [done, setDone] = useState(false)
  const start = useAction(() => api.post<{ secret: string; otpauth_uri: string }>('/api/auth/mfa/setup'))
  const confirm = useAction(() => api.post('/api/auth/mfa/confirm', { secret: setup?.secret, code }))

  useEffect(() => {
    if (setup) QRCode.toDataURL(setup.otpauth_uri, { margin: 1, width: 200 }).then(setQr)
  }, [setup])

  if (done) {
    return (
      <section aria-labelledby="mfa-h">
        <h2 id="mfa-h">Второй фактор</h2>
        <p className="message" role="status">Второй фактор подключён. При следующем входе понадобится код из приложения.</p>
      </section>
    )
  }

  return (
    <section aria-labelledby="mfa-h">
      <h2 id="mfa-h">Второй фактор</h2>
      <p>Вход по паролю и одноразовому коду из приложения-аутентификатора (Яндекс Ключ, Google Authenticator и др.).</p>
      <ErrorMessage error={start.error} />
      {!setup ? (
        <button type="button" className="secondary" disabled={start.pending}
                onClick={async () => setSetup((await start.run()) ?? null)}>Подключить</button>
      ) : (
        <form className="form" onSubmit={async (e) => { e.preventDefault(); if (await confirm.run()) setDone(true) }}>
          <p>1. Отсканируйте код в приложении или введите ключ вручную.</p>
          {qr && <img src={qr} width={200} height={200} alt="QR-код для приложения-аутентификатора" />}
          <p>Ключ: <code>{setup.secret}</code></p>
          <label>
            2. Код из приложения
            <input inputMode="numeric" autoComplete="one-time-code" required pattern="[0-9]{6}" value={code}
                   onChange={(e) => setCode(e.target.value)} />
          </label>
          <ErrorMessage error={confirm.error} />
          <button type="submit" disabled={confirm.pending}>Подтвердить</button>
        </form>
      )}
    </section>
  )
}
