import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../../api/client'
import { useAction, useApi } from '../../api/useApi'
import { ErrorMessage } from '../../components/ErrorMessage'
import { Loader } from '../../components/Loader'
import { formatDateTime } from '../../format'
import { KIND_LABEL } from './KnowledgePage'

interface Version {
  id: number
  version: number | null
  status: string
  change_note: string | null
  proposed_at: string
  decided_at: string | null
  decision_comment: string | null
}

const STATUS_LABEL: Record<string, string> = {
  draft: 'На рассмотрении',
  approved: 'Действует',
  superseded: 'Заменена',
  rejected: 'Отклонена',
}

export function VersionsPage() {
  const { kind = '', code = '' } = useParams()
  const state = useApi<Version[]>(`/api/admin/knowledge/${kind}/${encodeURIComponent(code)}/versions`)
  const [note, setNote] = useState('')
  const [done, setDone] = useState<number | null>(null)
  const rollback = useAction((id: number) =>
    api.post<{ draft_id: number }>(`/api/admin/knowledge/${kind}/${encodeURIComponent(code)}/rollback`, { to_version_id: id, change_note: note }))

  const onRollback = async (id: number) => {
    const r = await rollback.run(id)
    if (r) {
      setDone(r.draft_id)
      state.reload()
    }
  }

  return (
    <>
      <h1>История версий: {KIND_LABEL[kind] ?? kind} {code}</h1>
      <p><Link to="/knowledge">К справочникам</Link></p>
      {done !== null && (
        <p className="message" role="status">Откат оформлен черновиком № {done}; вступит в силу после одобрения рецензентом.</p>
      )}
      <label className="form">
        Причина отката (обязательна)
        <input value={note} minLength={5} maxLength={2000} onChange={(e) => setNote(e.target.value)} />
      </label>
      <ErrorMessage error={rollback.error} />
      <Loader state={state}>
        {(versions) => (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">Версия</th>
                  <th scope="col">Статус</th>
                  <th scope="col">Предложено</th>
                  <th scope="col">Решение</th>
                  <th scope="col">Комментарий</th>
                  <th scope="col"><span className="visually-hidden">Действия</span></th>
                </tr>
              </thead>
              <tbody>
                {versions.map((v) => (
                  <tr key={v.id}>
                    <td>{v.version ?? '—'}</td>
                    <td>{STATUS_LABEL[v.status] ?? v.status}</td>
                    <td>{formatDateTime(v.proposed_at)}</td>
                    <td>{formatDateTime(v.decided_at)}</td>
                    <td className="small">{[v.change_note, v.decision_comment].filter(Boolean).join(' / ')}</td>
                    <td>
                      {v.status === 'superseded' && (
                        <button type="button" className="secondary" disabled={rollback.pending || note.trim().length < 5}
                                onClick={() => onRollback(v.id)}>Вернуть эту версию</button>
                      )}
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
