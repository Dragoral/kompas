import { useState, type FormEvent } from 'react'
import { api } from '../../api/client'
import type { ConsentText } from '../../api/types'
import { useAction, useApi } from '../../api/useApi'
import { ErrorMessage } from '../../components/ErrorMessage'
import { Loader } from '../../components/Loader'
import { formatDate } from '../../format'

interface TrustedContact {
  id: number
  name: string
  phone: string
  relation: string | null
  consent_at: string
}

export function TrustedContactsPage() {
  const list = useApi<TrustedContact[]>('/api/me/trusted-contacts')
  const revoke = useAction((id: number) => api.delete(`/api/me/trusted-contacts/${id}`))

  const onRevoke = async (c: TrustedContact) => {
    if (!window.confirm(`Отозвать согласие на информирование ${c.name}?`)) return
    if (await revoke.run(c.id)) list.reload()
  }

  return (
    <>
      <h1>Доверенное лицо</h1>
      <p>
        Близкий человек, которому система сообщит по SMS, если врач не сможет быстро связаться с вами при угрозе жизни.
        Диагноз и медицинские сведения в сообщении не передаются.
      </p>
      <ErrorMessage error={revoke.error} />
      <Loader state={list}>
        {(contacts) => contacts.length === 0 ? <p>Доверенное лицо не указано.</p> : (
          <ul>
            {contacts.map((c) => (
              <li key={c.id}>
                {c.name}{c.relation ? ` (${c.relation})` : ''}, {c.phone} · согласие от {formatDate(c.consent_at)}{' '}
                <button type="button" className="button-link" disabled={revoke.pending} onClick={() => onRevoke(c)}>Отозвать</button>
              </li>
            ))}
          </ul>
        )}
      </Loader>
      <AddForm onAdded={list.reload} />
    </>
  )
}

function AddForm({ onAdded }: { onAdded: () => void }) {
  const text = useApi<ConsentText>('/api/consent/trusted-contact')
  const [form, setForm] = useState({ name: '', phone: '', relation: '', agree: false })
  const add = useAction((c: ConsentText) => api.post('/api/me/trusted-contacts', {
    name: form.name.trim(), phone: form.phone.trim(), relation: form.relation.trim() || null,
    consent_version: c.version, consent_sha256: c.sha256,
  }))

  return (
    <Loader state={text}>
      {(c) => (
        <form className="form" aria-labelledby="add-h" onSubmit={async (e: FormEvent) => {
          e.preventDefault()
          if (await add.run(c)) {
            setForm({ name: '', phone: '', relation: '', agree: false })
            onAdded()
          }
        }}>
          <h2 id="add-h">Добавить доверенное лицо</h2>
          <label>
            Имя
            <input required minLength={2} maxLength={128} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </label>
          <div className="row">
            <label>
              Телефон
              <input type="tel" required pattern="\+?[0-9 ()\-]{10,20}" placeholder="+7 900 000-00-00" value={form.phone}
                     onChange={(e) => setForm({ ...form, phone: e.target.value })} />
            </label>
            <label>
              Кем приходится
              <input maxLength={32} placeholder="например, сестра" value={form.relation}
                     onChange={(e) => setForm({ ...form, relation: e.target.value })} />
            </label>
          </div>
          <div className="document">{c.text}</div>
          <label className="checkbox">
            <input type="checkbox" required checked={form.agree} onChange={(e) => setForm({ ...form, agree: e.target.checked })} />
            Даю согласие на информирование этого человека на условиях выше
          </label>
          <ErrorMessage error={add.error} />
          <button type="submit" disabled={add.pending}>Добавить</button>
        </form>
      )}
    </Loader>
  )
}
