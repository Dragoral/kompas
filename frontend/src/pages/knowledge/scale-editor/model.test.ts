import { expect, it } from 'vitest'
import { emptyScale, pathLabel, toBody } from './model'

it('ошибки сервера переводятся в понятные врачу места формы', () => {
  expect(pathLabel('items.3.options')).toBe('Вопрос 4, варианты ответа')
  expect(pathLabel('bands')).toBe('Градации')
  expect(pathLabel('')).toBe('Шкала')
})

it('описание шкалы для отправки: без пустых полей, код в верхнем регистре', () => {
  const s = { ...emptyScale(), code: ' sleep2 ', title: ' Сон ', validation: ['  Источник ', ''], period: '  ' }
  const body = toBody(s)
  expect(body.code).toBe('SLEEP2')
  expect(body.title).toBe('Сон')
  expect(body.validation).toEqual(['Источник'])
  expect(body).not.toHaveProperty('period')
  expect(body.items[0]).not.toHaveProperty('type')
})
