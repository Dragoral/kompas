import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useApi } from '../../api/useApi'
import { Loader } from '../../components/Loader'
import { ProposeBar } from './ProposeBar'
import type { Rule } from './rules/RulesEditorPage'

interface Policy {
  timezone_offset_hours: number
  working_hours: WorkingHours
  duty_service: boolean
  escalate_after_min: number
  trusted_contact: { rules: string[]; any_time: boolean; sms_template: string }
  doctor_sms_template: string
  duty_sms_template: string
  verified?: boolean
  [key: string]: unknown
}

export interface WorkingHours {
  days: number[]
  start: string
  end: string
}

export const WEEKDAYS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']

/** Политика реагирования на критические оповещения: кому, когда и как сообщать. */
export function ResponsePolicyPage() {
  const state = useApi<{ body: Policy; version: number }>('/api/knowledge/dictionary/response_policy')
  const alerts = useApi<{ body: { rules: Rule[] } }>('/api/knowledge/rules/alerts')
  return (
    <Loader state={state}>
      {(r) => <PolicyEditor initial={r.body} version={r.version} critical={(alerts.data?.body.rules ?? []).filter((x) => x.severity === 'critical')} />}
    </Loader>
  )
}

function PolicyEditor({ initial, version, critical }: { initial: Policy; version: number; critical: Rule[] }) {
  const [p, setP] = useState<Policy>(initial)
  const set = (patch: Partial<Policy>) => setP({ ...p, ...patch })
  const tc = p.trusted_contact

  return (
    <>
      <h1>Политика реагирования на критические оповещения</h1>
      <p className="muted">Действующая версия: {version}. Изменения вступят в силу после одобрения рецензентом.</p>
      <p><Link to="/knowledge">К справочникам</Link></p>
      <p>
        Лечащий врач получает SMS только в рабочее время; в кабинете оповещение видно всегда. Вне рабочего времени
        сообщение получает дежурный врач (если есть дежурная служба) и доверенное лицо пациента (если пациент дал согласие).
      </p>

      <div className="form wide">
        <section aria-labelledby="hours-h">
          <h2 id="hours-h">Рабочее время по умолчанию</h2>
          <p className="muted">Для отдельного врача рабочее время можно задать в разделе «Пользователи».</p>
          <WorkingHoursEditor value={p.working_hours} onChange={(working_hours) => set({ working_hours })} />
          <label>
            Часовой пояс клиники, часов от UTC
            <input type="number" min={-12} max={14} value={p.timezone_offset_hours} className="short"
                   onChange={(e) => set({ timezone_offset_hours: Number(e.target.value) })} />
          </label>
        </section>

        <section aria-labelledby="duty-h">
          <h2 id="duty-h">Дежурная служба</h2>
          <label className="checkbox">
            <input type="checkbox" checked={p.duty_service} onChange={(e) => set({ duty_service: e.target.checked })} />
            В клинике есть круглосуточная дежурная служба (врачи с отметкой «дежурный»)
          </label>
          <label>
            Если лечащий врач не принял оповещение в рабочее время, передать дежурному через, мин
            <input type="number" min={1} max={240} className="short" value={p.escalate_after_min}
                   onChange={(e) => set({ escalate_after_min: Number(e.target.value) })} />
          </label>
        </section>

        <section aria-labelledby="tc-h">
          <h2 id="tc-h">Доверенное лицо пациента</h2>
          <fieldset>
            <legend>При каких оповещениях сообщать</legend>
            {critical.map((r) => (
              <label key={r.id} className="checkbox">
                <input type="checkbox" checked={tc.rules.includes(r.id)}
                       onChange={(e) => set({ trusted_contact: { ...tc, rules: e.target.checked ? [...tc.rules, r.id] : tc.rules.filter((x) => x !== r.id) } })} />
                {r.title ?? r.id}
              </label>
            ))}
          </fieldset>
          <label className="checkbox">
            <input type="checkbox" checked={tc.any_time} onChange={(e) => set({ trusted_contact: { ...tc, any_time: e.target.checked } })} />
            Сообщать в любое время суток (иначе — только в рабочее время)
          </label>
          <label>
            Текст SMS доверенному лицу
            <textarea rows={3} maxLength={500} value={tc.sms_template} aria-describedby="tc-hint"
                      onChange={(e) => set({ trusted_contact: { ...tc, sms_template: e.target.value } })} />
            <span id="tc-hint" className="muted small">{'{patient_first_name}'} — имя пациента. Не указывайте диагноз и медицинские сведения.</span>
          </label>
        </section>

        <section aria-labelledby="sms-h">
          <h2 id="sms-h">Тексты SMS врачам</h2>
          <label>
            Лечащему врачу
            <input maxLength={300} value={p.doctor_sms_template} onChange={(e) => set({ doctor_sms_template: e.target.value })} />
          </label>
          <label>
            Дежурному врачу
            <input maxLength={300} value={p.duty_sms_template} onChange={(e) => set({ duty_sms_template: e.target.value })} />
          </label>
          <p className="muted small">{'{patient_code}'} — код пациента. ФИО и диагноз в SMS не передаются.</p>
        </section>
      </div>

      <ProposeBar kind="dictionary" code="response_policy" body={() => p} />
    </>
  )
}

export function WorkingHoursEditor({ value, onChange }: { value: WorkingHours; onChange: (v: WorkingHours) => void }) {
  return (
    <>
      <fieldset>
        <legend>Рабочие дни</legend>
        <div className="row">
          {WEEKDAYS.map((d, i) => (
            <label key={d} className="checkbox">
              <input type="checkbox" checked={value.days.includes(i + 1)}
                     onChange={(e) => onChange({ ...value, days: e.target.checked ? [...value.days, i + 1].sort() : value.days.filter((x) => x !== i + 1) })} />
              {d}
            </label>
          ))}
        </div>
      </fieldset>
      <div className="row">
        <label>С<input type="time" required value={value.start} onChange={(e) => onChange({ ...value, start: e.target.value })} /></label>
        <label>До<input type="time" required value={value.end} onChange={(e) => onChange({ ...value, end: e.target.value })} /></label>
      </div>
    </>
  )
}
