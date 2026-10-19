import { useState, type FormEvent } from 'react'
import { api } from '../../api/client'
import type { StaffUser } from '../../api/types'
import { useAction, useApi } from '../../api/useApi'
import { useAuth } from '../../auth/AuthContext'
import { ErrorMessage } from '../../components/ErrorMessage'
import { Loader } from '../../components/Loader'
import { formatDateTime, ROLE_LABEL, SPECIALTY_LABEL } from '../../format'
import { WEEKDAYS, WorkingHoursEditor, type WorkingHours } from '../knowledge/ResponsePolicyPage'

const SPECIALTIES = ['psychiatrist', 'psychotherapist', 'therapist', 'neurologist', 'gp', 'other']

export function UsersPage() {
  const { user: me } = useAuth()
  const state = useApi<StaffUser[]>('/api/admin/users')
  const [secret, setSecret] = useState<{ login: string; password: string } | null>(null)
  const [hoursFor, setHoursFor] = useState<StaffUser | null>(null)
  const patch = useAction((id: number, body: Partial<StaffUser>) => api.patch(`/api/admin/users/${id}`, body))
  const reset = useAction((id: number) => api.post<{ temporary_password: string }>(`/api/admin/users/${id}/reset-password`))

  const onPatch = async (id: number, body: Partial<StaffUser>) => {
    if (await patch.run(id, body)) state.reload()
  }

  const onReset = async (u: StaffUser) => {
    if (!window.confirm(`Сбросить пароль пользователя ${u.login}? Все его сеансы будут завершены.`)) return
    const r = await reset.run(u.id)
    if (r) setSecret({ login: u.login, password: r.temporary_password })
  }

  return (
    <>
      <h1>Пользователи</h1>
      {secret && <TemporaryPassword {...secret} onClose={() => setSecret(null)} />}
      <ErrorMessage error={patch.error ?? reset.error} />
      <Loader state={state}>
        {(users) => (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">Логин</th>
                  <th scope="col">ФИО</th>
                  <th scope="col">Роль</th>
                  <th scope="col">Рецензент</th>
                  <th scope="col">Дежурный</th>
                  <th scope="col">SMS-уведомления</th>
                  <th scope="col">Второй фактор</th>
                  <th scope="col">Статус</th>
                  <th scope="col"><span className="visually-hidden">Действия</span></th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.id}>
                    <td><code>{u.login}</code></td>
                    <td>{u.full_name}</td>
                    <td>{ROLE_LABEL[u.role]}{u.specialty ? `, ${SPECIALTY_LABEL[u.specialty] ?? u.specialty}` : ''}</td>
                    <td>
                      {u.role === 'doctor' && (
                        <input type="checkbox" aria-label={`Рецензент: ${u.login}`} checked={u.is_reviewer} disabled={patch.pending}
                               onChange={(e) => onPatch(u.id, { is_reviewer: e.target.checked })} />
                      )}
                    </td>
                    <td>
                      {u.role === 'doctor' && (
                        <input type="checkbox" aria-label={`Дежурный: ${u.login}`} checked={u.is_duty} disabled={patch.pending}
                               onChange={(e) => onPatch(u.id, { is_duty: e.target.checked })} />
                      )}
                    </td>
                    <td>
                      {u.role === 'doctor' && (
                        <>
                          {u.working_hours ? formatHours(u.working_hours) : 'по политике клиники'}{' '}
                          <button type="button" className="button-link" onClick={() => setHoursFor(u)}>изменить</button>
                        </>
                      )}
                    </td>
                    <td>{u.mfa_enabled ? 'Да' : 'Нет'}</td>
                    <td>{!u.active ? 'Заблокирован' : u.locked_until ? `Вход заблокирован до ${formatDateTime(u.locked_until)}` : 'Активен'}</td>
                    <td className="nowrap">
                      <button type="button" className="button-link" disabled={reset.pending} onClick={() => onReset(u)}>Сбросить пароль</button>
                      {u.id !== me?.id && (
                        <>
                          {' · '}
                          <button type="button" className="button-link" disabled={patch.pending}
                                  onClick={() => onPatch(u.id, { active: !u.active })}>{u.active ? 'Заблокировать' : 'Разблокировать'}</button>
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Loader>
      {hoursFor && (
        <HoursForm user={hoursFor} onClose={() => setHoursFor(null)} onSaved={() => { setHoursFor(null); state.reload() }} />
      )}
      <NewUserForm onCreated={(login, password) => { setSecret({ login, password }); state.reload() }} />
    </>
  )
}

function TemporaryPassword({ login, password, onClose }: { login: string; password: string; onClose: () => void }) {
  return (
    <div className="message" role="status">
      <p>Временный пароль для <code>{login}</code>: <code>{password}</code></p>
      <p className="small">Передайте его пользователю защищённым способом. Пароль больше не будет показан.</p>
      <button type="button" className="secondary" onClick={onClose}>Скрыть</button>
    </div>
  )
}

function NewUserForm({ onCreated }: { onCreated: (login: string, password: string) => void }) {
  const empty = { login: '', full_name: '', role: 'doctor', specialty: 'psychiatrist', phone: '', is_reviewer: false, is_duty: false }
  const [form, setForm] = useState(empty)
  const create = useAction(() => api.post<StaffUser & { temporary_password: string }>('/api/admin/users', {
    ...form,
    login: form.login.trim().toLowerCase(),
    specialty: form.role === 'doctor' ? form.specialty : null,
    phone: form.phone.trim() || null,
    is_reviewer: form.role === 'doctor' && form.is_reviewer,
    is_duty: form.role === 'doctor' && form.is_duty,
  }))

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault()
    const r = await create.run()
    if (r) {
      onCreated(r.login, r.temporary_password)
      setForm(empty)
    }
  }

  const set = (patch: Partial<typeof form>) => setForm({ ...form, ...patch })

  return (
    <form className="form" onSubmit={onSubmit} aria-labelledby="new-user-h">
      <h2 id="new-user-h">Новый сотрудник</h2>
      <div className="row">
        <label>
          Логин
          <input required minLength={3} maxLength={64} pattern="[a-z0-9._-]+" autoComplete="off" value={form.login}
                 aria-describedby="login-hint" onChange={(e) => set({ login: e.target.value })} />
          <span id="login-hint" className="muted small">Строчная латиница, цифры, «.», «_», «-»</span>
        </label>
        <label>
          Роль
          <select value={form.role} onChange={(e) => set({ role: e.target.value })}>
            <option value="doctor">Врач</option>
            <option value="admin">Администратор</option>
          </select>
        </label>
      </div>
      <label>
        ФИО
        <input required minLength={3} maxLength={128} value={form.full_name} onChange={(e) => set({ full_name: e.target.value })} />
      </label>
      {form.role === 'doctor' && (
        <>
          <div className="row">
            <label>
              Специальность
              <select value={form.specialty} onChange={(e) => set({ specialty: e.target.value })}>
                {SPECIALTIES.map((s) => <option key={s} value={s}>{SPECIALTY_LABEL[s] ?? s}</option>)}
              </select>
            </label>
            <label>
              Телефон для срочных оповещений
              <input type="tel" pattern="\+?[0-9 ()\-]{10,20}" value={form.phone} onChange={(e) => set({ phone: e.target.value })} />
            </label>
          </div>
          <label className="checkbox">
            <input type="checkbox" checked={form.is_reviewer} onChange={(e) => set({ is_reviewer: e.target.checked })} />
            Клинический рецензент справочников
          </label>
          <label className="checkbox">
            <input type="checkbox" checked={form.is_duty} onChange={(e) => set({ is_duty: e.target.checked })} />
            Дежурный врач
          </label>
        </>
      )}
      <ErrorMessage error={create.error} />
      <button type="submit" disabled={create.pending}>Создать</button>
    </form>
  )
}

function formatHours(h: WorkingHours): string {
  return `${h.days.map((d) => WEEKDAYS[d - 1]).join(', ')} ${h.start}–${h.end}`
}

function HoursForm({ user, onClose, onSaved }: { user: StaffUser; onClose: () => void; onSaved: () => void }) {
  const [hours, setHours] = useState<WorkingHours>(user.working_hours ?? { days: [1, 2, 3, 4, 5], start: '09:00', end: '18:00' })
  const save = useAction((value: WorkingHours | null) => api.patch(`/api/admin/users/${user.id}`, { working_hours: value }))

  return (
    <form className="form panel" aria-labelledby="hours-h" onSubmit={async (e) => { e.preventDefault(); if (await save.run(hours)) onSaved() }}>
      <h2 id="hours-h">Когда отправлять SMS: {user.full_name}</h2>
      <p className="muted">Вне этого времени срочные оповещения получает дежурный врач. В кабинете оповещения видны всегда.</p>
      <WorkingHoursEditor value={hours} onChange={setHours} />
      <ErrorMessage error={save.error} />
      <div className="row">
        <button type="submit" disabled={save.pending}>Сохранить</button>
        <button type="button" className="secondary" disabled={save.pending}
                onClick={async () => { if (await save.run(null)) onSaved() }}>Как в политике клиники</button>
        <button type="button" className="secondary" onClick={onClose}>Отмена</button>
      </div>
    </form>
  )
}
