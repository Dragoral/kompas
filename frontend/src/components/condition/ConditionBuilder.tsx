import { useState } from 'react'
import {
  defaultValue, findVariable, OP_LABEL, opsFor, parse, serialize,
  type Clause, type ClauseOp, type Condition, type Group, type Value, type Variable,
} from './model'

const WILDCARD_HINT: Record<string, string> = {
  scales: 'код шкалы',
  items: 'номер пункта',
  subscales: 'код подшкалы',
  thresholds: 'код порога',
}

/**
 * Условие правила: форма для простых условий (переменная — оператор — значение, через И/ИЛИ)
 * или JSON для сложных. Переменные — из каталога сервера (GET /api/knowledge/variables).
 */
export function ConditionBuilder({ value, onChange, catalogue, thresholds = [], label = 'Условие' }: {
  value: Condition
  onChange: (c: Condition) => void
  catalogue: Variable[]
  thresholds?: string[]
  label?: string
}) {
  const parsed = parse(value)
  const [asJson, setAsJson] = useState(parsed === null)
  const [json, setJson] = useState(() => JSON.stringify(value, null, 2))
  const [jsonError, setJsonError] = useState<string | null>(null)

  const onJson = (text: string) => {
    setJson(text)
    try {
      onChange(JSON.parse(text))
      setJsonError(null)
    } catch {
      setJsonError('Некорректный JSON')
    }
  }

  const switchToForm = () => {
    if (parse(value)) setAsJson(false)
  }

  return (
    <fieldset className="condition">
      <legend>{label}</legend>
      {asJson || !parsed ? (
        <>
          <label>
            Условие в формате JSON-logic
            <textarea rows={4} className="mono" spellCheck={false} value={json} aria-invalid={!!jsonError}
                      onChange={(e) => onJson(e.target.value)} />
          </label>
          {jsonError && <p className="small" role="alert">{jsonError}</p>}
          {parse(value) ? (
            <button type="button" className="button-link" onClick={switchToForm}>Редактировать формой</button>
          ) : (
            <p className="muted small">Условие сложнее, чем позволяет форма: доступно редактирование как JSON.</p>
          )}
        </>
      ) : (
        <GroupEditor group={parsed} catalogue={catalogue} thresholds={thresholds}
                     onChange={(g) => { onChange(serialize(g)); setJson(JSON.stringify(serialize(g), null, 2)) }}
                     onJson={() => { setJson(JSON.stringify(value, null, 2)); setAsJson(true) }} />
      )}
    </fieldset>
  )
}

function GroupEditor({ group, catalogue, thresholds, onChange, onJson }: {
  group: Group
  catalogue: Variable[]
  thresholds: string[]
  onChange: (g: Group) => void
  onJson: () => void
}) {
  const update = (i: number, c: Clause) => onChange({ ...group, clauses: group.clauses.map((x, j) => (j === i ? c : x)) })
  const add = () => {
    const v = catalogue[0]
    onChange({ ...group, clauses: [...group.clauses, { path: v.path, op: opsFor(v.type)[0], value: defaultValue(v.type, opsFor(v.type)[0]) }] })
  }

  return (
    <>
      {group.clauses.length > 1 && (
        <label className="inline">
          Срабатывает, если выполнены{' '}
          <select value={group.join} onChange={(e) => onChange({ ...group, join: e.target.value as 'and' | 'or' })}>
            <option value="and">все условия</option>
            <option value="or">любое из условий</option>
          </select>
        </label>
      )}
      {group.clauses.map((c, i) => (
        <ClauseEditor key={i} clause={c} catalogue={catalogue} thresholds={thresholds} onChange={(x) => update(i, x)}
                      onRemove={group.clauses.length > 1 ? () => onChange({ ...group, clauses: group.clauses.filter((_, j) => j !== i) }) : undefined} />
      ))}
      <p>
        <button type="button" className="button-link" onClick={add}>Добавить условие</button>
        {' · '}
        <button type="button" className="button-link" onClick={onJson}>Редактировать как JSON</button>
      </p>
    </>
  )
}

function ClauseEditor({ clause, catalogue, thresholds, onChange, onRemove }: {
  clause: Clause
  catalogue: Variable[]
  thresholds: string[]
  onChange: (c: Clause) => void
  onRemove?: () => void
}) {
  const variable = findVariable(catalogue, clause.path)
  const template = variable?.path ?? clause.path
  const type = variable?.type ?? 'строка'
  const tParts = template.split('.')
  const pParts = clause.path.split('.')

  const setTemplate = (t: string) => {
    const v = catalogue.find((x) => x.path === t)!
    const op = opsFor(v.type)[0]
    onChange({ path: t, op, value: defaultValue(v.type, op) })
  }
  const setPart = (i: number, s: string) => {
    const parts = [...pParts]
    parts[i] = s.trim() || '*'
    onChange({ ...clause, path: parts.join('.') })
  }
  const setOp = (op: ClauseOp) => {
    const needsList = op === 'contains_any' || op === 'one_of'
    const isList = clause.value.kind === 'list'
    onChange({ ...clause, op, value: needsList === isList ? clause.value : defaultValue(type, op) })
  }

  return (
    <div className="clause">
      <label>
        Показатель
        <select value={template} onChange={(e) => setTemplate(e.target.value)}>
          {catalogue.map((v) => <option key={v.path} value={v.path}>{v.description}</option>)}
        </select>
      </label>
      {tParts.map((t, i) => t === '*' && (
        <label key={i} className="clause-part">
          {WILDCARD_HINT[tParts[i - 1]] ?? 'уточнение'}
          <input required value={pParts[i] === '*' ? '' : pParts[i]} onChange={(e) => setPart(i, e.target.value)} />
        </label>
      ))}
      <label className="clause-op">
        Сравнение
        <select value={clause.op} onChange={(e) => setOp(e.target.value as ClauseOp)}>
          {opsFor(type).map((op) => <option key={op} value={op}>{OP_LABEL[op]}</option>)}
        </select>
      </label>
      <ValueEditor value={clause.value} type={type} thresholds={thresholds} onChange={(value) => onChange({ ...clause, value })} />
      {onRemove && <button type="button" className="button-link" onClick={onRemove}>Удалить</button>}
    </div>
  )
}

function ValueEditor({ value, type, thresholds, onChange }: {
  value: Value
  type: string
  thresholds: string[]
  onChange: (v: Value) => void
}) {
  if (value.kind === 'bool') {
    return (
      <label className="clause-value">
        Значение
        <select value={value.value ? 'true' : 'false'} onChange={(e) => onChange({ kind: 'bool', value: e.target.value === 'true' })}>
          <option value="true">да</option>
          <option value="false">нет</option>
        </select>
      </label>
    )
  }
  if (value.kind === 'list') {
    return (
      <label className="clause-value">
        Значения через запятую
        <input required value={value.value} onChange={(e) => onChange({ kind: 'list', value: e.target.value })} />
      </label>
    )
  }
  if (type === 'число' && thresholds.length > 0) {
    return (
      <div className="clause-value">
        <label>
          С чем сравнить
          <select value={value.kind} onChange={(e) => onChange(e.target.value === 'threshold'
            ? { kind: 'threshold', value: thresholds[0] } : { kind: 'number', value: '' })}>
            <option value="number">с числом</option>
            <option value="threshold">с порогом</option>
          </select>
        </label>
        {value.kind === 'threshold' ? (
          <label>
            Порог
            <select value={value.value} onChange={(e) => onChange({ kind: 'threshold', value: e.target.value })}>
              {thresholds.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </label>
        ) : (
          <label>
            Число
            <input type="number" step="any" required value={value.value} onChange={(e) => onChange({ kind: 'number', value: e.target.value })} />
          </label>
        )}
      </div>
    )
  }
  return (
    <label className="clause-value">
      Значение
      <input required type={type === 'число' ? 'number' : 'text'} step="any" value={String(value.value)}
             onChange={(e) => onChange({ kind: type === 'число' ? 'number' : 'text', value: e.target.value })} />
    </label>
  )
}
