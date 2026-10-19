import { useState, type FormEvent } from 'react'
import { api } from '../../api/client'
import { useAction, useApi } from '../../api/useApi'
import { ErrorMessage } from '../../components/ErrorMessage'
import { Loader } from '../../components/Loader'
import type { StaffUser } from '../../api/types'
import { formatDateTime } from '../../format'

interface AuditRow {
  id: number
  at: string
  user_id: number | null
  action: string
  entity: string | null
  entity_id: number | null
  patient_id: number | null
  details: Record<string, unknown> | null
  ip: string | null
}

interface VerifyResult {
  ok: boolean
  checked: number
  broken_at_id?: number
}

export function AuditPage() {
  const [filter, setFilter] = useState({ action: '', patient_id: '' })
  const [query, setQuery] = useState('')
  const state = useApi<AuditRow[]>(`/api/admin/audit?limit=300${query}`)
  const users = useApi<StaffUser[]>('/api/admin/users')
  const login = (id: number | null) => (id === null ? '—' : users.data?.find((u) => u.id === id)?.login ?? `#${id}`)
  const [verified, setVerified] = useState<VerifyResult | null>(null)
  const verify = useAction(() => api.get<VerifyResult>('/api/admin/audit/verify'))

  const onFilter = (e: FormEvent) => {
    e.preventDefault()
    const qs = new URLSearchParams()
    if (filter.action.trim()) qs.set('action', filter.action.trim())
    if (filter.patient_id.trim()) qs.set('patient_id', filter.patient_id.trim())
    setQuery(qs.size ? `&${qs}` : '')
  }

  return (
    <>
      <h1>Журнал аудита</h1>
      <p>Записи журнала связаны цепочкой хешей: изменение или удаление любой записи обнаруживается проверкой.</p>
      <p>
        <button type="button" className="secondary" disabled={verify.pending}
                onClick={async () => setVerified((await verify.run()) ?? null)}>Проверить целостность журнала</button>
      </p>
      <ErrorMessage error={verify.error} />
      {verified && (
        <p className={verified.ok ? 'message' : 'message message-error'} role="status">
          {verified.ok
            ? `Журнал не изменён. Проверено записей: ${verified.checked}.`
            : `Нарушение целостности на записи № ${verified.broken_at_id}. Проверено записей: ${verified.checked}.`}
        </p>
      )}
      <form className="toolbar" onSubmit={onFilter}>
        <label>
          Действие
          <input value={filter.action} placeholder="например, login_failed" onChange={(e) => setFilter({ ...filter, action: e.target.value })} />
        </label>
        <label>
          ID пациента
          <input type="number" min={1} value={filter.patient_id} onChange={(e) => setFilter({ ...filter, patient_id: e.target.value })} />
        </label>
        <button type="submit">Показать</button>
      </form>
      <Loader state={state}>
        {(rows) => rows.length === 0 ? <p>Записей нет.</p> : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">№</th>
                  <th scope="col">Время</th>
                  <th scope="col">Пользователь</th>
                  <th scope="col">Действие</th>
                  <th scope="col">Объект</th>
                  <th scope="col">Пациент</th>
                  <th scope="col">Подробности</th>
                  <th scope="col">IP</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id}>
                    <td>{r.id}</td>
                    <td className="nowrap">{formatDateTime(r.at)}</td>
                    <td>{login(r.user_id)}</td>
                    <td><code>{r.action}</code></td>
                    <td>{r.entity ? `${r.entity} ${r.entity_id ?? ''}` : '—'}</td>
                    <td>{r.patient_id ?? '—'}</td>
                    <td className="small">{r.details && Object.keys(r.details).length ? JSON.stringify(r.details) : '—'}</td>
                    <td className="small">{r.ip ?? '—'}</td>
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
