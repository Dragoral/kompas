import { useState } from 'react'
import { api } from '../../api/client'
import type { KnowledgeDraft } from '../../api/types'
import { useAction, useApi } from '../../api/useApi'
import { ErrorMessage } from '../../components/ErrorMessage'
import { Loader } from '../../components/Loader'
import { formatDateTime } from '../../format'

type Draft = KnowledgeDraft & { body: unknown; current_body: unknown }

export function ReviewPage() {
  const state = useApi<Draft[]>('/api/review/knowledge')
  const decide = useAction((id: number, decision: 'approve' | 'reject', comment: string) =>
    api.post(`/api/review/knowledge/${id}`, { decision, comment: comment || null }))

  const onDecide = async (id: number, decision: 'approve' | 'reject', comment: string) => {
    if (await decide.run(id, decision, comment)) state.reload()
  }

  return (
    <>
      <h1>Изменения справочников на рассмотрении</h1>
      <p className="muted">Автор изменения не может одобрить его сам.</p>
      <ErrorMessage error={decide.error} />
      <Loader state={state}>
        {(drafts) => drafts.length === 0 ? <p>Нет изменений на рассмотрении.</p> : (
          drafts.map((d) => <DraftItem key={d.id} draft={d} pending={decide.pending} onDecide={onDecide} />)
        )}
      </Loader>
    </>
  )
}

function DraftItem({ draft, pending, onDecide }: {
  draft: Draft
  pending: boolean
  onDecide: (id: number, decision: 'approve' | 'reject', comment: string) => void
}) {
  const [comment, setComment] = useState('')
  return (
    <article className="panel">
      <h2>{draft.kind} / {draft.code}</h2>
      <p>
        {draft.current_version ? `Изменение версии ${draft.current_version}` : 'Новый элемент'} · предложено {formatDateTime(draft.proposed_at)}
      </p>
      {draft.change_note && <p>Комментарий автора: {draft.change_note}</p>}
      <details>
        <summary>Предлагаемое описание</summary>
        <pre>{JSON.stringify(draft.body, null, 2)}</pre>
      </details>
      {draft.current_body !== null && (
        <details>
          <summary>Действующее описание</summary>
          <pre>{JSON.stringify(draft.current_body, null, 2)}</pre>
        </details>
      )}
      <label>
        Комментарий рецензента
        <input value={comment} maxLength={2000} onChange={(e) => setComment(e.target.value)} />
      </label>
      <p>
        <button type="button" disabled={pending} onClick={() => onDecide(draft.id, 'approve', comment)}>Одобрить</button>{' '}
        <button type="button" className="secondary" disabled={pending} onClick={() => onDecide(draft.id, 'reject', comment)}>Отклонить</button>
      </p>
    </article>
  )
}
