import QRCode from 'qrcode'
import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, setToken } from '../api/client'
import { disablePush, enablePush, pushState, type PushState } from '../api/push'
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
      <PushSettings role={user.role} />
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
  const { user, logout } = useAuth()
  const [setup, setSetup] = useState<{ secret: string; otpauth_uri: string } | null>(null)
  const [qr, setQr] = useState('')
  const [code, setCode] = useState('')
  const [password, setPassword] = useState('')
  const [done, setDone] = useState(false)
  const start = useAction(() => api.post<{ secret: string; otpauth_uri: string }>('/api/auth/mfa/setup'))
  const confirm = useAction(() => api.post('/api/auth/mfa/confirm', { secret: setup?.secret, code, old_password: password }))

  useEffect(() => {
    if (setup) QRCode.toDataURL(setup.otpauth_uri, { margin: 1, width: 200 }).then(setQr)
  }, [setup])

  if (done) {
    return (
      <section aria-labelledby="mfa-h">
        <h2 id="mfa-h">Второй фактор</h2>
        <p className="message" role="status">Второй фактор подключён. Для следующего входа используйте новый код из приложения после его обновления.</p>
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
        <form className="form" onSubmit={async (e) => {
          e.preventDefault()
          if (await confirm.run()) {
            setDone(true)
            if (user?.mfa_setup_required) {
              await logout()
              window.location.assign('/login')
            }
          }
        }}>
          <p>1. Отсканируйте код в приложении или введите ключ вручную.</p>
          {qr && <img src={qr} width={200} height={200} alt="QR-код для приложения-аутентификатора" />}
          <p>Ключ: <code>{setup.secret}</code></p>
          <label>
            Текущий пароль
            <input type="password" autoComplete="current-password" required value={password}
                   onChange={(e) => setPassword(e.target.value)} />
          </label>
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

const PUSH_WHAT: Record<string, string> = {
  patient: 'время приёма лекарства, опросник на сегодня, дневник, новое сообщение от врача',
  doctor: 'новые оповещения по вашим пациентам, в том числе когда кабинет закрыт',
  admin: 'служебные уведомления',
}

function PushSettings({ role }: { role: string }) {
  const [state, setState] = useState<PushState | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [pending, setPending] = useState(false)
  const refresh = useCallback(() => { pushState().then(setState).catch(() => setState('unsupported')) }, [])

  useEffect(refresh, [refresh])

  const run = async (fn: () => Promise<unknown>, done: string) => {
    setPending(true)
    setError(null)
    setNotice(null)
    try {
      await fn()
      setNotice(done)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setPending(false)
      refresh()
    }
  }

  return (
    <section aria-labelledby="push-h">
      <h2 id="push-h">Уведомления на этом устройстве</h2>
      <p>Что приходит: {PUSH_WHAT[role] ?? PUSH_WHAT.admin}. В тексте уведомления нет диагнозов и названий препаратов.</p>
      {state === null && <p className="muted">Проверка…</p>}
      {state === 'unsupported' && <p className="message">Этот браузер не поддерживает push-уведомления.</p>}
      {state === 'ios-install' && (
        <p className="message">На iPhone уведомления работают в приложении: нажмите «Поделиться» → «На экран „Домой“», откройте «Компас» с экрана и включите уведомления здесь (iOS 16.4 и новее).</p>
      )}
      {state === 'denied' && <p className="message message-error">Уведомления запрещены в настройках браузера для этого сайта. Разрешите их и обновите страницу.</p>}
      {error && <p className="message message-error" role="alert">{error}</p>}
      {notice && <p className="message" role="status">{notice}</p>}
      {state === 'off' && (
        <button type="button" disabled={pending} onClick={() => run(enablePush, 'Уведомления включены.')}>Включить уведомления</button>
      )}
      {state === 'on' && (
        <div className="row">
          <button type="button" className="secondary" disabled={pending}
                  onClick={() => run(() => api.post('/api/push/test'), 'Тестовое уведомление отправлено. Если оно не появилось, проверьте режим «Не беспокоить» в системе.')}>Проверить</button>
          <button type="button" className="secondary" disabled={pending} onClick={() => run(disablePush, 'Уведомления отключены.')}>Отключить</button>
        </div>
      )}
    </section>
  )
}
