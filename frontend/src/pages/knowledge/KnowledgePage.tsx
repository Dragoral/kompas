import { Link } from 'react-router-dom'
import { useState } from 'react'
import { useAuth } from '../../auth/AuthContext'
import { api } from '../../api/client'
import { useAction } from '../../api/useApi'
import { ErrorMessage } from '../../components/ErrorMessage'
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

/** Отдельная форма для типа справочника; остальное редактируется как JSON. */
export function editorPath(kind: string, code: string): string | null {
  const c = encodeURIComponent(code)
  if (kind === 'scale') return `/knowledge/scales/${c}`
  if (kind === 'drug') return `/knowledge/drugs/${c}`
  if (kind === 'rules') return `/knowledge/rules/${c}`
  if (kind === 'dictionary' && code === 'response_policy') return '/knowledge/response-policy'
  return null
}

export function KnowledgePage() {
  const { user } = useAuth()
  const state = useApi<KnowledgeRow[]>(user?.role === 'admin' ? '/api/admin/knowledge' : '/api/knowledge')
  const [reloadResult, setReloadResult] = useState<number | null>(null)
  const reloadYaml = useAction(() => api.post<{ drafts: number }>('/api/admin/knowledge/reload'))

  return (
    <>
      <h1>Справочники</h1>
      <p>
        Изменения справочников вступают в силу после одобрения врачом-рецензентом. Автор изменения не может одобрить его сам.
      </p>
      {user?.role === 'admin' && <section className="feature-card"><h2>Загрузка обновлений YAML</h2><p className="muted">Изменения из файлов репозитория будут оформлены как черновики для последующего согласования; этот процесс не активирует их автоматически.</p><ErrorMessage error={reloadYaml.error} />{reloadResult !== null && <p className="message" role="status">Создано черновиков: {reloadResult}</p>}<button type="button" disabled={reloadYaml.pending} onClick={async () => { if (window.confirm('Сравнить YAML-файлы с базой знаний и предложить изменения черновиками?')) { const r = await reloadYaml.run(); if (r) { setReloadResult(r.drafts); state.reload() } } }}>{reloadYaml.pending ? 'Проверяем…' : 'Проверить YAML и создать черновики'}</button></section>}
      <ul className="actions">
        <li><Link to="/knowledge/scales/new">Создать шкалу</Link></li>
        <li><Link to="/knowledge/import">Импортировать шкалу (CSV, FHIR)</Link></li>
        <li><Link to="/knowledge/drugs/new">Добавить препарат</Link></li>
        {user?.role === 'doctor' && user.is_reviewer && <li><Link to="/knowledge/review">Изменения на рассмотрении</Link></li>}
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
                      {editorPath(r.kind, r.code) && <><Link to={editorPath(r.kind, r.code)!}>Изменить</Link> · </>}
                      <Link to={`/knowledge/${r.kind}/${encodeURIComponent(r.code)}/json`}>JSON</Link>
                      {r.kind === 'scale' && <> · <FhirScaleExport code={r.code} /></>}
                      {user?.role === 'admin' && (
                        <> · <Link to={`/knowledge/${r.kind}/${encodeURIComponent(r.code)}/versions`}>Версии</Link></>
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


function FhirScaleExport({ code }: { code: string }) {
  const exportScale = useAction(() => api.get<unknown>(`/api/knowledge/scales/${encodeURIComponent(code)}/fhir`))
  const run = async () => {
    const resource = await exportScale.run()
    if (!resource) return
    const url = URL.createObjectURL(new Blob([JSON.stringify(resource, null, 2)], { type: 'application/fhir+json' }))
    const link = document.createElement('a')
    link.href = url
    link.download = `${code}-questionnaire.fhir.json`
    link.click()
    URL.revokeObjectURL(url)
  }
  return <><button type="button" className="link-button" disabled={exportScale.pending} onClick={run}>FHIR</button><ErrorMessage error={exportScale.error} /></>
}
