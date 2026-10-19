import { useState } from 'react'
import { api } from '../../api/client'
import type { KnowledgeDraft } from '../../api/types'
import { useAction, useApi } from '../../api/useApi'
import { ErrorMessage } from '../../components/ErrorMessage'
import { Loader } from '../../components/Loader'
import { formatDateTime } from '../../format'
import { KIND_LABEL } from './KnowledgePage'
import type { ScaleBody } from './scale-editor/model'

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
      <h2>{KIND_LABEL[draft.kind] ?? draft.kind} {draft.code}</h2>
      <p>
        {draft.current_version ? `Изменение версии ${draft.current_version}` : 'Новый элемент'} · предложено {formatDateTime(draft.proposed_at)}
      </p>
      {draft.change_note && <p>Комментарий автора: {draft.change_note}</p>}
      {draft.kind === 'scale' && <ScaleSummary scale={draft.body as ScaleBody} />}
      <details>
        <summary>Предлагаемое описание (JSON)</summary>
        <pre>{JSON.stringify(draft.body, null, 2)}</pre>
      </details>
      {draft.current_body !== null && (
        <details>
          <summary>Действующее описание (JSON)</summary>
          <pre>{JSON.stringify(draft.current_body, null, 2)}</pre>
        </details>
      )}
      <label>
        Комментарий рецензента
        <input value={comment} maxLength={2000} onChange={(e) => setComment(e.target.value)} />
      </label>
      <div className="row">
        <button type="button" disabled={pending} onClick={() => onDecide(draft.id, 'approve', comment)}>Одобрить</button>
        <button type="button" className="secondary" disabled={pending} onClick={() => onDecide(draft.id, 'reject', comment)}>Отклонить</button>
      </div>
    </article>
  )
}

function ScaleSummary({ scale }: { scale: ScaleBody }) {
  return (
    <>
      <dl className="summary">
        <dt>Название</dt><dd>{scale.title}</dd>
        <dt>Заполняет</dt><dd>{scale.respondent === 'clinician' ? 'Врач' : 'Пациент'}</dd>
        <dt>Источники</dt><dd>{scale.validation.join('; ')}</dd>
        <dt>Условия использования</dt><dd>{scale.license}</dd>
        <dt>Текст сверен</dt><dd>{scale.verified ? 'Да' : 'Нет'}</dd>
      </dl>
      <h3>Вопросы</h3>
      <ol>
        {scale.items.map((it) => (
          <li key={it.n}>
            {it.text}
            {it.options && <span className="muted small"> ({it.options.map((o) => `${o.value} — ${o.label}`).join('; ')})</span>}
            {it.reverse && <span className="badge badge-medium">обратный</span>}
            {it.critical && <span className="badge badge-critical">критический</span>}
          </li>
        ))}
      </ol>
      <h3>Градации</h3>
      <ul>
        {scale.bands.map((b) => <li key={`${b.min}-${b.max}`}>{b.min}–{b.max}: {b.label}</li>)}
      </ul>
    </>
  )
}
