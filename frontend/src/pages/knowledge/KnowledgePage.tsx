import { Link } from 'react-router-dom'
import { useAuth } from '../../auth/AuthContext'
import type { KnowledgeRow } from '../../api/types'
import { useApi } from '../../api/useApi'
import { Loader } from '../../components/Loader'
import { formatDate } from '../../format'

const KIND_LABEL: Record<string, string> = {
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
        <Link to="/knowledge/import">Добавить шкалу</Link>
        {user?.role === 'doctor' && <> · <Link to="/knowledge/review">Изменения на рассмотрении</Link></>}
      </p>
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
                  <th scope="col">Проверено врачами</th>
                  <th scope="col">Черновик</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={`${r.kind}/${r.code}`}>
                    <td>{KIND_LABEL[r.kind] ?? r.kind}</td>
                    <td><code>{r.code}</code></td>
                    <td>{r.title}</td>
                    <td>{r.version}</td>
                    <td>{formatDate(r.updated_at)}</td>
                    <td>{r.verified === null ? '—' : r.verified ? 'Да' : 'Нет'}</td>
                    <td>{r.has_draft ? 'Есть' : ''}</td>
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
