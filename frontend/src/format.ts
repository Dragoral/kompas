import type { Regimen } from './api/types'

const dateFmt = new Intl.DateTimeFormat('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric' })
const dateTimeFmt = new Intl.DateTimeFormat('ru-RU', {
  day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
})

// Сервер отдаёт время в UTC без суффикса зоны
function parse(value: string): Date {
  return new Date(/[zZ]|[+-]\d\d:\d\d$/.test(value) || value.length <= 10 ? value : `${value}Z`)
}

export function formatDate(value: string | null | undefined): string {
  return value ? dateFmt.format(parse(value)) : '—'
}

export function formatDateTime(value: string | null | undefined): string {
  return value ? dateTimeFmt.format(parse(value)) : '—'
}

export function formatRegimen(r: Regimen | null | undefined): string {
  if (!r) return '—'
  const dose = r.dose_mg && r.times_per_day ? `${r.dose_mg} мг × ${r.times_per_day} р/сут` : r.daily_mg ? `${r.daily_mg} мг/сут` : ''
  return [dose, r.timing].filter(Boolean).join(', ') || '—'
}

export const SEVERITY_LABEL: Record<string, string> = {
  critical: 'Критический',
  high: 'Высокий',
  medium: 'Средний',
}

export const LEVEL_LABEL: Record<string, string> = {
  mandatory: 'Обязательно',
  desirable: 'Желательно',
}

export const DRUG_STATUS_LABEL: Record<string, string> = {
  indicated: 'Показан',
  off_label: 'Вне инструкции',
  contraindicated: 'Противопоказан',
}

export const SPECIALTY_LABEL: Record<string, string> = {
  psychiatrist: 'психиатр',
  psychotherapist: 'психотерапевт',
  therapist: 'терапевт',
  neurologist: 'невролог',
  gp: 'врач общей практики',
  other: 'другая',
}

export const ROLE_LABEL: Record<string, string> = {
  doctor: 'Врач',
  patient: 'Пациент',
  admin: 'Администратор',
}
