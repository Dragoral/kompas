export interface Option {
  value: number
  label: string
}

export type ItemType = 'choice' | 'yes_no' | 'number'

export interface Item {
  n: number
  text: string
  type?: ItemType
  options?: Option[]
  min?: number
  max?: number
  reverse?: boolean
  critical?: boolean
  required?: boolean
  weight?: number
}

export interface Band {
  min: number
  max: number
  label: string
  severity?: number
}

export interface Subscale {
  title?: string
  items: number[]
  method?: string
  bands?: Band[]
}

export interface ScaleBody {
  code: string
  title: string
  respondent: 'patient' | 'clinician'
  period?: string
  license: string
  validation: string[]
  verified?: boolean
  items: Item[]
  bands: Band[]
  scoring?: { method?: string; subscales?: Record<string, Subscale> }
  [key: string]: unknown
}

export const DEFAULT_OPTIONS: Option[] = [
  { value: 0, label: 'Нет' },
  { value: 1, label: 'Иногда' },
  { value: 2, label: 'Часто' },
  { value: 3, label: 'Постоянно' },
]

export function emptyScale(): ScaleBody {
  return {
    code: '',
    title: '',
    respondent: 'patient',
    period: '',
    license: '',
    validation: [],
    verified: false,
    items: [{ n: 1, text: '', type: 'choice', options: DEFAULT_OPTIONS }],
    bands: [{ min: 0, max: 0, label: '', severity: 0 }],
    scoring: { method: 'sum' },
  }
}

export function renumber(items: Item[]): Item[] {
  return items.map((it, i) => ({ ...it, n: i + 1 }))
}

/** Описание для отправки: пустые необязательные поля убираются. */
export function toBody(s: ScaleBody): ScaleBody {
  const items = s.items.map((it) => {
    const out: Item = { n: it.n, text: it.text.trim() }
    const type = it.type ?? 'choice'
    if (type !== 'choice') out.type = type
    if (type === 'number') {
      out.min = it.min ?? 0
      out.max = it.max ?? 0
    } else {
      out.options = it.options ?? []
    }
    if (it.reverse) out.reverse = true
    if (it.critical) out.critical = true
    if (it.required === false) out.required = false
    if (it.weight !== undefined && s.scoring?.method === 'weighted_sum') out.weight = it.weight
    return out
  })
  const body: ScaleBody = { ...s, code: s.code.trim().toUpperCase(), title: s.title.trim(), items,
    validation: s.validation.map((v) => v.trim()).filter(Boolean) }
  if (!body.period?.trim()) delete body.period
  if (body.scoring?.subscales && Object.keys(body.scoring.subscales).length === 0) {
    body.scoring = { ...body.scoring }
    delete body.scoring.subscales
  }
  return body
}

const FIELD_LABEL: Record<string, string> = {
  code: 'Код',
  title: 'Название',
  respondent: 'Кто заполняет',
  period: 'Инструкция',
  license: 'Условия использования',
  validation: 'Источники',
  items: 'Вопросы',
  bands: 'Градации',
  scoring: 'Подсчёт',
  options: 'варианты ответа',
  text: 'текст',
  min: 'минимум',
  max: 'максимум',
  label: 'название',
  subscales: 'Подшкалы',
  verified: 'Сверка текста',
}

/** «items.3.options» -> «Вопрос 4, варианты ответа» */
export function pathLabel(path: string): string {
  if (!path) return 'Шкала'
  const parts = path.split('.')
  const out: string[] = []
  for (let i = 0; i < parts.length; i++) {
    const p = parts[i]
    const next = parts[i + 1]
    if ((p === 'items' || p === 'bands') && next !== undefined && /^\d+$/.test(next)) {
      out.push(`${p === 'items' ? 'Вопрос' : 'Градация'} ${Number(next) + 1}`)
      i++
    } else if (/^\d+$/.test(p)) {
      out.push(`№ ${Number(p) + 1}`)
    } else {
      out.push(FIELD_LABEL[p] ?? p)
    }
  }
  return out.join(', ')
}
