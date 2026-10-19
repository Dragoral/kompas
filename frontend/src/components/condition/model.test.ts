import { describe as group, expect, it } from 'vitest'
import { describe, parse, serialize, type Condition, type Variable } from './model'

const catalogue: Variable[] = [
  { path: 'scales.*.score', type: 'число', description: 'Последний общий балл шкалы' },
  { path: 'scales.*.items.*', type: 'число', description: 'Ответ на пункт' },
  { path: 'patient.conditions', type: 'список', description: 'Состояния' },
  { path: 'patient.pregnant', type: 'да/нет', description: 'Беременность' },
  { path: 'patient.child_pugh', type: 'строка', description: 'Чайлд–Пью' },
]

const roundtrip = (c: Condition) => serialize(parse(c)!)

group('условия правил: форма <-> JSON-logic', () => {
  it.each<[string, Condition]>([
    ['сравнение с числом', { '>': [{ var: 'scales.PHQ9.items.9' }, 0] }],
    ['сравнение с порогом', { '>=': [{ var: 'scales.PHQ9.score' }, { var: 'thresholds.phq9_severe' }] }],
    ['да/нет', { '==': [{ var: 'patient.pregnant' }, true] }],
    ['список содержит', { in: ['epilepsy', { var: 'patient.conditions' }] }],
    ['список содержит любое из', { some_in: [['diabetes', 'endocrine'], { var: 'patient.conditions' }] }],
    ['значение одно из', { in: [{ var: 'patient.child_pugh' }, ['A', 'B', 'C']] }],
    ['И', { and: [{ '>=': [{ var: 'scales.GAD7.score' }, 10] }, { '==': [{ var: 'patient.pregnant' }, false] }] }],
    ['ИЛИ', { or: [{ '>': [{ var: 'scales.PHQ9.items.9' }, 0] }, { '>=': [{ var: 'scales.CSSRS.score' }, 2] }] }],
  ])('%s: разбор и сборка дают исходное условие', (_, c) => {
    expect(roundtrip(c)).toEqual(c)
  })

  it('вложенные группы не разбираются — редактируются как JSON', () => {
    expect(parse({ and: [{ or: [{ '>': [{ var: 'a' }, 1] }] }] })).toBeNull()
    expect(parse({ '!': [{ var: 'patient.pregnant' }] })).toBeNull()
  })

  it('человекочитаемое описание с уточнением шаблона', () => {
    expect(describe({ '>=': [{ var: 'scales.PHQ9.score' }, 20] }, catalogue)).toBe('Последний общий балл шкалы (PHQ9) не меньше 20')
    expect(describe({ or: [{ '==': [{ var: 'patient.pregnant' }, true] }, { in: ['epilepsy', { var: 'patient.conditions' }] }] }, catalogue))
      .toBe('Беременность равно да ИЛИ Состояния содержит epilepsy')
  })
})
