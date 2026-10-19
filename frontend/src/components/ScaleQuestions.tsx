import type { ScaleDefinition, ScaleItem } from '../api/types'

export type Answers = Record<string, number>

export function optionsFor(scale: ScaleDefinition, item: ScaleItem) {
  if (item.options?.length) return item.options
  if (item.type === 'yes_no') return [{ value: 0, label: 'Нет' }, { value: 1, label: 'Да' }]
  return scale.options ?? []
}

/** Вопросы шкалы. Используется пациентом, врачом (шкалы для врача) и в предпросмотре конструктора. */
export function ScaleQuestions({ scale, answers, onChange, idPrefix = 'q', optional = false }: {
  scale: ScaleDefinition
  answers: Answers
  onChange: (answers: Answers) => void
  idPrefix?: string
  optional?: boolean
}) {
  return (
    <>
      {scale.items.map((item) => (
        <fieldset key={item.n}>
          <legend>{item.n}. {item.text}</legend>
          {item.type === 'number' ? (
            <input type="number" required={!optional && item.required !== false} min={item.min} max={item.max} step="any"
                   aria-label={item.text} value={answers[item.n] ?? ''}
                   onChange={(e) => onChange({ ...answers, [item.n]: Number(e.target.value) })} />
          ) : (
            optionsFor(scale, item).map((o) => (
              <label key={o.value} className="radio">
                <input type="radio" name={`${idPrefix}${item.n}`} value={o.value} required={!optional && item.required !== false}
                       checked={answers[item.n] === o.value}
                       onChange={() => onChange({ ...answers, [item.n]: o.value })} />
                {o.label}
              </label>
            ))
          )}
        </fieldset>
      ))}
    </>
  )
}
