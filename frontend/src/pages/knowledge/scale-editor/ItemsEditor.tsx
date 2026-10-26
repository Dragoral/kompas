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
    <div className="items-editor">
      {items.map((it, i) => {
        const type = it.type ?? 'choice'
        return (
          <div key={i} className="item-editor panel">
            <h3 className="item-editor-title">Вопрос {it.n}</h3>
            <label>
              Текст
              <textarea rows={2} required value={it.text} onChange={(e) => update(i, { text: e.target.value })} />
            </label>
            <div className="row form-row-aligned">
              <label className="field-block">
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
                  <label className="field-block">Минимум<NumberInput value={it.min} onChange={(v) => update(i, { min: v })} /></label>
                  <label className="field-block">Максимум<NumberInput value={it.max} onChange={(v) => update(i, { max: v })} /></label>
                </>
              )}
              {weighted && (
                <label className="field-block">Вес<NumberInput value={it.weight} onChange={(v) => update(i, { weight: v })} /></label>
              )}
            </div>
            {type !== 'number' && (
              <OptionsEditor
                options={it.options ?? []}
                onChange={(options) => update(i, { options })}
                onApplyAll={type === 'choice' && items.length > 1 ? () => applyOptionsToAll(it.options ?? []) : undefined}
              />
            )}
            <div className="item-flag-row">
              <label className="checkbox">
                <input type="checkbox" checked={!!it.reverse} onChange={(e) => update(i, { reverse: e.target.checked })} />
                <span>Обратный подсчёт</span>
              </label>
              <label className="checkbox">
                <input type="checkbox" checked={!!it.critical} onChange={(e) => update(i, { critical: e.target.checked })} />
                <span>Критический пункт</span>
              </label>
              <label className="checkbox">
                <input type="checkbox" checked={it.required !== false} onChange={(e) => update(i, { required: e.target.checked })} />
                <span>Обязательный</span>
              </label>
            </div>
            <div className="actions item-move-row">
              <button type="button" className="secondary" disabled={i === 0} onClick={() => move(i, -1)}>Выше</button>
              <button type="button" className="secondary" disabled={i === items.length - 1} onClick={() => move(i, 1)}>Ниже</button>
              <button type="button" className="secondary danger" disabled={items.length === 1} onClick={() => remove(i)}>Удалить вопрос</button>
            </div>
          </div>
        )
      })}
      <button type="button" onClick={add}>Добавить вопрос</button>
    </div>
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
    <div className="options-editor">
      <div className="options-editor-title">Варианты ответа</div>
      <div className="line-editor">
        {options.map((o, i) => (
          <div key={i} className="line-editor-row">
            <label className="line-field line-field-score">
              <span className="line-field-label">Балл</span>
              <NumberInput value={o.value} required aria-label={`Балл варианта ${i + 1}`} onChange={(v) => update(i, { value: v ?? 0 })} />
            </label>
            <label className="line-field line-field-grow">
              <span className="line-field-label">Текст варианта</span>
              <input required value={o.label} aria-label={`Текст варианта ${i + 1}`} onChange={(e) => update(i, { label: e.target.value })} />
            </label>
            <button
              type="button"
              className="line-remove secondary"
              disabled={options.length <= 2}
              onClick={() => onChange(options.filter((_, j) => j !== i))}
            >
              Удалить
            </button>
          </div>
        ))}
      </div>
      <div className="actions options-editor-actions">
        <button type="button" className="secondary" onClick={add}>+ Добавить вариант</button>
        {onApplyAll && (
          <button type="button" className="secondary" onClick={onApplyAll}>Применить ко всем вопросам</button>
        )}
      </div>
    </div>
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
    <input
      type="number"
      step="any"
      {...rest}
      value={value ?? ''}
      onChange={(e) => onChange(e.target.value === '' ? undefined : Number(e.target.value))}
    />
  )
}
