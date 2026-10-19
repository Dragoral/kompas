import { Link } from 'react-router-dom'
import { useAuth } from '../../auth/AuthContext'
import type { KnowledgeRow } from '../../api/types'
import { useApi } from '../../api/useApi'
import { Loader } from '../../components/Loader'
import { formatDate } from '../../format'

export const KIND_LABEL: Record<string, string> = {
  scale: 'Шкала',
  drug: 'Препарат',
  rules: 'Правила',
  guideline: 'Клинические рекомендации',
  dictionary: 'Словарь',
}

export function KnowledgePage() {
  const { user } = useAuth()
  const state = useApi<KnowledgeRow[]>('/api/knowledge')

  return (
    <>
      <h1>Справочники</h1>
      <p>
        Изменения справочников вступают в силу после одобрения врачом-рецензентом. Автор изменения не может одобрить его сам.
      </p>
      <ul className="actions">
        <li><Link to="/knowledge/scales/new">Создать шкалу</Link></li>
        <li><Link to="/knowledge/import">Импортировать шкалу (CSV, FHIR)</Link></li>
        {user?.role === 'doctor' && <li><Link to="/knowledge/review">Изменения на рассмотрении</Link></li>}
      </ul>
      <Loader state={state}>
        {(rows) => (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">Тип</th>
                  <th scope="col">Код</th>
                  <th scope="col">Название</th>
                  <th scope="col">Версия</th>
                  <th scope="col">Обновлено</th>
                  <th scope="col">Сверено</th>
                  <th scope="col"><span className="visually-hidden">Действия</span></th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={`${r.kind}/${r.code}`}>
                    <td>{KIND_LABEL[r.kind] ?? r.kind}</td>
                    <td><code>{r.code}</code></td>
                    <td>
                      {r.title}
                      {r.has_draft && <div className="small"><span className="badge badge-high">Есть изменение на рассмотрении</span></div>}
                    </td>
                    <td>{r.version}</td>
                    <td>{formatDate(r.updated_at)}</td>
                    <td>{r.verified === null || r.verified === undefined ? '—' : r.verified ? 'Да' : 'Нет'}</td>
                    <td className="nowrap">
                      {r.kind === 'scale' && <Link to={`/knowledge/scales/${encodeURIComponent(r.code)}`}>Изменить</Link>}
                      {user?.role === 'admin' && (
                        <> {r.kind === 'scale' && '· '}<Link to={`/knowledge/${r.kind}/${encodeURIComponent(r.code)}/versions`}>Версии</Link></>
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
