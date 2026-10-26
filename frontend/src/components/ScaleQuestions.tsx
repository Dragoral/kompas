import type { ScaleDefinition, ScaleItem } from '../api/types'

export type Answers = Record<string, number>

export function optionsFor(scale: ScaleDefinition, item: ScaleItem) {
  if (item.options?.length) return item.options
  if (item.type === 'yes_no') return [{ value: 0, label: 'Нет' }, { value: 1, label: 'Да' }]
  return scale.options ?? []
}

/** Вопросы шкалы. Используется пациентом, врачом и в предпросмотре конструктора. */
export function ScaleQuestions({ scale, answers, onChange, idPrefix = 'q', optional = false }: {
  scale: ScaleDefinition
  answers: Answers
  onChange: (answers: Answers) => void
  idPrefix?: string
  optional?: boolean
}) {
  return (
    <div className="scale-questions">
      {scale.items.map((item) => (
        <div key={item.n} className="scale-question-card" role="group" aria-labelledby={`${idPrefix}-q${item.n}`}>
          <p id={`${idPrefix}-q${item.n}`} className="scale-question-text">
            <span className="scale-q-num">{item.n}.</span> {item.text}
          </p>
          <div className="scale-question-options">
            {item.type === 'number' ? (
              <input type="number" required={!optional && item.required !== false} min={item.min} max={item.max} step="any"
                     aria-label={item.text} value={answers[item.n] ?? ''}
                     onChange={(e) => onChange({ ...answers, [item.n]: Number(e.target.value) })} />
            ) : (
              optionsFor(scale, item).map((o) => (
                <label key={o.value} className={`radio scale-option${answers[item.n] === o.value ? ' scale-option-active' : ''}`}>
                  <input type="radio" name={`${idPrefix}${item.n}`} value={o.value} required={!optional && item.required !== false}
                         checked={answers[item.n] === o.value}
                         onChange={() => onChange({ ...answers, [item.n]: o.value })} />
                  <span className="scale-option-label">{o.label}</span>
                </label>
              ))
            )}
          </div>
        </div>
      ))}
    </div>
  )
}
