import { DEFAULT_OPTIONS, renumber, type Item, type ItemType, type Option } from './model'

const TYPE_LABEL: Record<ItemType, string> = {
  choice: 'Выбор варианта',
  yes_no: 'Да / нет',
  number: 'Число',
}

export function ItemsEditor({ items, weighted, onChange }: {
  items: Item[]
  weighted: boolean
  onChange: (items: Item[]) => void
}) {
  const update = (i: number, patch: Partial<Item>) => onChange(items.map((it, j) => (j === i ? { ...it, ...patch } : it)))
  const remove = (i: number) => onChange(renumber(items.filter((_, j) => j !== i)))
  const move = (i: number, d: -1 | 1) => {
    const next = [...items]
    ;[next[i], next[i + d]] = [next[i + d], next[i]]
    onChange(renumber(next))
  }
  const add = () => {
    const prev = items[items.length - 1]
    onChange(renumber([...items, {
      n: 0, text: '', type: prev?.type ?? 'choice', options: prev?.options ?? DEFAULT_OPTIONS,
      min: prev?.min, max: prev?.max,
    }]))
  }
  const applyOptionsToAll = (options: Option[]) =>
    onChange(items.map((it) => ((it.type ?? 'choice') === 'choice' ? { ...it, options } : it)))

  return (
    <>
      {items.map((it, i) => {
        const type = it.type ?? 'choice'
        return (
          <fieldset key={i} className="item-editor">
            <legend>Вопрос {it.n}</legend>
            <label>
              Текст
              <textarea rows={2} required value={it.text} onChange={(e) => update(i, { text: e.target.value })} />
            </label>
            <div className="row">
              <label>
                Тип ответа
                <select value={type} onChange={(e) => {
                  const t = e.target.value as ItemType
                  update(i, t === 'yes_no'
                    ? { type: t, options: [{ value: 0, label: 'Нет' }, { value: 1, label: 'Да' }] }
                    : t === 'choice' ? { type: t, options: it.options?.length ? it.options : DEFAULT_OPTIONS } : { type: t })
                }}>
                  {Object.entries(TYPE_LABEL).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                </select>
              </label>
              {type === 'number' && (
                <>
                  <label>Минимум<NumberInput value={it.min} onChange={(v) => update(i, { min: v })} /></label>
                  <label>Максимум<NumberInput value={it.max} onChange={(v) => update(i, { max: v })} /></label>
                </>
              )}
              {weighted && <label>Вес<NumberInput value={it.weight} onChange={(v) => update(i, { weight: v })} /></label>}
            </div>
            {type !== 'number' && (
              <OptionsEditor options={it.options ?? []} onChange={(options) => update(i, { options })}
                             onApplyAll={type === 'choice' && items.length > 1 ? () => applyOptionsToAll(it.options ?? []) : undefined} />
            )}
            <div className="row">
              <label className="checkbox">
                <input type="checkbox" checked={!!it.reverse} onChange={(e) => update(i, { reverse: e.target.checked })} />
                Обратный подсчёт
              </label>
              <label className="checkbox">
                <input type="checkbox" checked={!!it.critical} onChange={(e) => update(i, { critical: e.target.checked })} />
                Критический пункт
              </label>
              <label className="checkbox">
                <input type="checkbox" checked={it.required !== false} onChange={(e) => update(i, { required: e.target.checked })} />
                Обязательный
              </label>
            </div>
            <div className="row">
              <button type="button" className="secondary" disabled={i === 0} onClick={() => move(i, -1)}>Выше</button>
              <button type="button" className="secondary" disabled={i === items.length - 1} onClick={() => move(i, 1)}>Ниже</button>
              <button type="button" className="secondary danger" disabled={items.length === 1} onClick={() => remove(i)}>Удалить вопрос</button>
            </div>
          </fieldset>
        )
      })}
      <button type="button" onClick={add}>Добавить вопрос</button>
    </>
  )
}

function OptionsEditor({ options, onChange, onApplyAll }: {
  options: Option[]
  onChange: (options: Option[]) => void
  onApplyAll?: () => void
}) {
  const update = (i: number, patch: Partial<Option>) => onChange(options.map((o, j) => (j === i ? { ...o, ...patch } : o)))
  const add = () => {
    const last = options[options.length - 1]
    onChange([...options, { value: last ? last.value + 1 : 0, label: '' }])
  }

  return (
    <table className="compact">
      <caption>Варианты ответа</caption>
      <thead>
        <tr><th scope="col">Балл</th><th scope="col">Текст варианта</th><th scope="col"><span className="visually-hidden">Удалить</span></th></tr>
      </thead>
      <tbody>
        {options.map((o, i) => (
          <tr key={i}>
            <td className="col-number">
              <NumberInput value={o.value} required aria-label={`Балл варианта ${i + 1}`} onChange={(v) => update(i, { value: v ?? 0 })} />
            </td>
            <td>
              <input required value={o.label} aria-label={`Текст варианта ${i + 1}`} onChange={(e) => update(i, { label: e.target.value })} />
            </td>
            <td>
              <button type="button" className="button-link" disabled={options.length <= 2}
                      onClick={() => onChange(options.filter((_, j) => j !== i))}>Удалить</button>
            </td>
          </tr>
        ))}
      </tbody>
      <tfoot>
        <tr>
          <td colSpan={3}>
            <button type="button" className="button-link" onClick={add}>Добавить вариант</button>
            {onApplyAll && <> · <button type="button" className="button-link" onClick={onApplyAll}>Применить эти варианты ко всем вопросам</button></>}
          </td>
        </tr>
      </tfoot>
    </table>
  )
}

export function NumberInput({ value, onChange, ...rest }: {
  value: number | undefined
  onChange: (v: number | undefined) => void
  required?: boolean
  min?: number
  max?: number
  'aria-label'?: string
}) {
  return (
    <input type="number" step="any" {...rest} value={value ?? ''}
           onChange={(e) => onChange(e.target.value === '' ? undefined : Number(e.target.value))} />
  )
}
