import type { StaffUser } from '../../api/types'
import { useApi } from '../../api/useApi'
import { Loader } from '../../components/Loader'
import { formatDateTime, ROLE_LABEL, SPECIALTY_LABEL } from '../../format'

export function UsersPage() {
  const state = useApi<StaffUser[]>('/api/admin/users')

  return (
    <>
      <h1>Пользователи</h1>
      <Loader state={state}>
        {(users) => (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">Логин</th>
                  <th scope="col">ФИО</th>
                  <th scope="col">Роль</th>
                  <th scope="col">Права</th>
                  <th scope="col">Второй фактор</th>
                  <th scope="col">Статус</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.id}>
                    <td><code>{u.login}</code></td>
                    <td>{u.full_name}</td>
                    <td>{ROLE_LABEL[u.role]}{u.specialty ? `, ${SPECIALTY_LABEL[u.specialty] ?? u.specialty}` : ''}</td>
                    <td>{[u.is_reviewer && 'рецензент', u.is_duty && 'дежурный'].filter(Boolean).join(', ') || '—'}</td>
                    <td>{u.mfa_enabled ? 'Да' : 'Нет'}</td>
                    <td>
                      {!u.active ? 'Отключён' : u.locked_until ? `Заблокирован до ${formatDateTime(u.locked_until)}` : 'Активен'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Loader>
    </>
  )
}
