import { useState } from 'react'
import type { Subscale } from './model'

function parseItems(text: string): number[] {
  const out: number[] = []
  for (const part of text.split(/[,;\s]+/).filter(Boolean)) {
    const range = part.match(/^(\d+)-(\d+)$/)
    if (range) {
      for (let n = Number(range[1]); n <= Number(range[2]); n++) out.push(n)
    } else if (/^\d+$/.test(part)) {
      out.push(Number(part))
    }
  }
  return [...new Set(out)]
}

export function SubscalesEditor({ subscales, onChange }: {
  subscales: Record<string, Subscale>
  onChange: (s: Record<string, Subscale>) => void
}) {
  const [newKey, setNewKey] = useState('')
  const entries = Object.entries(subscales)

  const update = (key: string, patch: Partial<Subscale>) => onChange({ ...subscales, [key]: { ...subscales[key], ...patch } })
  const remove = (key: string) => {
    const next = { ...subscales }
    delete next[key]
    onChange(next)
  }
  const add = () => {
    const key = newKey.trim().toLowerCase().replace(/[^a-z0-9_]/g, '_')
    if (!key || subscales[key]) return
    onChange({ ...subscales, [key]: { title: '', items: [] } })
    setNewKey('')
  }

  return (
    <>
      {entries.length === 0 && <p className="muted">Подшкал нет. Если шкала их не предусматривает, раздел можно пропустить.</p>}
      {entries.length > 0 && (
        <div className="table-wrap">
          <table className="compact">
            <thead>
              <tr>
                <th scope="col">Код</th>
                <th scope="col">Название</th>
                <th scope="col">Номера вопросов</th>
                <th scope="col"><span className="visually-hidden">Удалить</span></th>
              </tr>
            </thead>
            <tbody>
              {entries.map(([key, s]) => (
                <tr key={key}>
                  <td><code>{key}</code></td>
                  <td><input value={s.title ?? ''} aria-label="Название подшкалы" onChange={(e) => update(key, { title: e.target.value })} /></td>
                  <td>
                    <ItemsInput value={s.items} onChange={(items) => update(key, { items })} />
                  </td>
                  <td><button type="button" className="button-link" onClick={() => remove(key)}>Удалить</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="row">
        <label>
          Код новой подшкалы (латиница)
          <input value={newKey} pattern="[A-Za-z0-9_]+" onChange={(e) => setNewKey(e.target.value)} />
        </label>
        <button type="button" className="secondary" onClick={add}>Добавить подшкалу</button>
      </div>
    </>
  )
}

/** Список номеров вводится как «1, 2, 5-7»; разбирается при выходе из поля. */
function ItemsInput({ value, onChange }: { value: number[]; onChange: (v: number[]) => void }) {
  const [text, setText] = useState(value.join(', '))
  return (
    <input value={text} aria-label="Номера вопросов" placeholder="1, 2, 5-7"
           onChange={(e) => setText(e.target.value)}
           onBlur={() => { const items = parseItems(text); onChange(items); setText(items.join(', ')) }} />
  )
}
