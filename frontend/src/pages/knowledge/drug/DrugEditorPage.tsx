import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import type { KnowledgeRow } from '../../../api/types'
import { useApi } from '../../../api/useApi'
import { ConditionBuilder } from '../../../components/condition/ConditionBuilder'
import type { Condition, Variable } from '../../../components/condition/model'
import { Loader } from '../../../components/Loader'
import { ProposeBar } from '../ProposeBar'

interface Regimen {
  dose_mg?: number
  times_per_day?: number
  daily_mg?: number
  max_daily_mg?: number
  timing?: string
  duration?: string
}

interface Indication {
  id: string
  title: string
  icd10: string[]
  requires?: Condition
  regimen?: Regimen
  [key: string]: unknown
}

interface Finding {
  id: string
  title: string
  when: Condition
  note?: string
}

interface Interaction {
  classes: string[]
  severity: 'contraindicated' | 'major' | 'moderate'
  text: string
}

interface Drug {
  id: string
  trade_name: string
  inn: string
  atc?: string
  pharm_group?: string
  classes?: string[]
  additional_monitoring?: boolean
  verified?: boolean
  registration: { number: string; date?: string; holder?: string; [key: string]: unknown }
  sources: Record<string, { title: string; url?: string }>
  indications: Indication[]
  contraindications?: Finding[]
  cautions?: Finding[]
  interactions?: Interaction[]
  special_instructions?: string[]
  monitoring?: { scales?: { scale: string; every_days: number }[]; [key: string]: unknown }
  [key: string]: unknown
}

const SEVERITY: Record<Interaction['severity'], string> = {
  contraindicated: 'Противопоказано',
  major: 'Значимое',
  moderate: 'Умеренное',
}

const DEFAULT_WHEN: Condition = { '==': [{ var: 'patient.pregnant' }, true] }

function emptyDrug(): Drug {
  return {
    id: '', trade_name: '', inn: '', classes: [], additional_monitoring: false, verified: false,
    registration: { number: '' },
    sources: { instruction: { title: '', url: 'https://grls.rosminzdrav.ru' } },
    indications: [{ id: 'main', title: '', icd10: [], regimen: { times_per_day: 1 } }],
    contraindications: [], cautions: [], interactions: [], special_instructions: [], monitoring: { scales: [] },
  }
}

const list = (s: string) => s.split(',').map((x) => x.trim()).filter(Boolean)
const num = (s: string) => (s === '' ? undefined : Number(s))

export function DrugEditorPage() {
  const { code } = useParams()
  const variables = useApi<Variable[]>('/api/knowledge/variables')
  const existing = useApi<{ body: Drug; version: number }>(code ? `/api/knowledge/drug/${encodeURIComponent(code)}` : null)

  return (
    <Loader state={variables}>
      {(vars) => code
        ? <Loader state={existing}>{(r) => <DrugEditor initial={r.body} version={r.version} catalogue={vars} />}</Loader>
        : <DrugEditor initial={emptyDrug()} catalogue={vars} isNew />}
    </Loader>
  )
}

function DrugEditor({ initial, version, catalogue, isNew = false }: {
  initial: Drug
  version?: number
  catalogue: Variable[]
  isNew?: boolean
}) {
  const [d, setD] = useState<Drug>(initial)
  const set = (patch: Partial<Drug>) => setD({ ...d, ...patch })
  const scales = useApi<KnowledgeRow[]>('/api/knowledge')
  const scaleCodes = (scales.data ?? []).filter((x) => x.kind === 'scale').map((x) => x.code)
  const instr = d.sources.instruction ?? { title: '', url: '' }

  return (
    <>
      <h1>{isNew ? 'Новый препарат' : `Препарат: ${d.trade_name}`}</h1>
      {version !== undefined && <p className="muted">Действующая версия: {version}. Изменения вступят в силу после одобрения рецензентом.</p>}
      <p><Link to="/knowledge">К справочникам</Link></p>
      <p className="message">
        Данные вносятся строго по инструкции по медицинскому применению из Государственного реестра лекарственных средств
        (grls.rosminzdrav.ru). Система рекомендует только в рамках зарегистрированных показаний.
      </p>

      <div className="form wide">
        <section aria-labelledby="basic-h">
          <h2 id="basic-h">Основное</h2>
          <div className="row">
            <label>
              Код
              <input required pattern="[a-z0-9_]{2,40}" readOnly={!isNew} value={d.id} aria-describedby="drug-id-hint"
                     onChange={(e) => set({ id: e.target.value.toLowerCase() })} />
              <span id="drug-id-hint" className="muted small">Строчная латиница, например sertraline</span>
            </label>
            <label>Код АТХ<input value={d.atc ?? ''} onChange={(e) => set({ atc: e.target.value || undefined })} /></label>
          </div>
          <div className="row">
            <label>Торговое наименование<input required value={d.trade_name} onChange={(e) => set({ trade_name: e.target.value })} /></label>
            <label>МНН<input required value={d.inn} onChange={(e) => set({ inn: e.target.value })} /></label>
          </div>
          <label>Фармакологическая группа<input value={d.pharm_group ?? ''} onChange={(e) => set({ pharm_group: e.target.value || undefined })} /></label>
          <label>
            Фармакологические классы (через запятую)
            <input value={(d.classes ?? []).join(', ')} aria-describedby="classes-hint" onChange={(e) => set({ classes: list(e.target.value) })} />
            <span id="classes-hint" className="muted small">Используются для проверки взаимодействий, например ssri, cyp2d6_inhibitor</span>
          </label>
          <label className="checkbox">
            <input type="checkbox" checked={!!d.additional_monitoring} onChange={(e) => set({ additional_monitoring: e.target.checked })} />
            Препарат под дополнительным мониторингом безопасности (▼)
          </label>
          <label className="checkbox">
            <input type="checkbox" checked={!!d.verified} onChange={(e) => set({ verified: e.target.checked })} />
            Сведения сверены с инструкцией в ГРЛС
          </label>
        </section>

        <section aria-labelledby="reg-h">
          <h2 id="reg-h">Регистрация и источник</h2>
          <div className="row">
            <label>Номер регистрационного удостоверения<input required value={d.registration.number}
                   onChange={(e) => set({ registration: { ...d.registration, number: e.target.value } })} /></label>
            <label>Дата регистрации<input type="date" value={d.registration.date ?? ''}
                   onChange={(e) => set({ registration: { ...d.registration, date: e.target.value || undefined } })} /></label>
          </div>
          <label>Держатель удостоверения<input value={d.registration.holder ?? ''}
                 onChange={(e) => set({ registration: { ...d.registration, holder: e.target.value || undefined } })} /></label>
          <label>Инструкция (название документа)<input required value={instr.title}
                 onChange={(e) => set({ sources: { ...d.sources, instruction: { ...instr, title: e.target.value } } })} /></label>
          <label>Ссылка на инструкцию<input type="url" value={instr.url ?? ''}
                 onChange={(e) => set({ sources: { ...d.sources, instruction: { ...instr, url: e.target.value } } })} /></label>
        </section>

        <section aria-labelledby="ind-h">
          <h2 id="ind-h">Показания</h2>
          {d.indications.map((ind, i) => (
            <IndicationEditor key={i} value={ind} catalogue={catalogue}
                              onChange={(x) => set({ indications: d.indications.map((y, j) => (j === i ? x : y)) })}
                              onRemove={d.indications.length > 1 ? () => set({ indications: d.indications.filter((_, j) => j !== i) }) : undefined} />
          ))}
          <p><button type="button" className="secondary"
                     onClick={() => set({ indications: [...d.indications, { id: `ind_${d.indications.length + 1}`, title: '', icd10: [], regimen: { times_per_day: 1 } }] })}>
            Добавить показание
          </button></p>
        </section>

        <FindingsEditor title="Противопоказания" hint="При срабатывании назначение блокируется (врач может назначить только с обоснованием)."
                        items={d.contraindications ?? []} catalogue={catalogue} withNote
                        onChange={(contraindications) => set({ contraindications })} />
        <FindingsEditor title="С осторожностью" hint="Показывается врачу как предостережение."
                        items={d.cautions ?? []} catalogue={catalogue}
                        onChange={(cautions) => set({ cautions })} />

        <section aria-labelledby="int-h">
          <h2 id="int-h">Взаимодействия</h2>
          <div className="table-wrap">
            <table className="compact">
              <thead><tr><th scope="col">Классы препаратов (через запятую)</th><th scope="col">Значимость</th><th scope="col">Описание</th><th scope="col"><span className="visually-hidden">Удалить</span></th></tr></thead>
              <tbody>
                {(d.interactions ?? []).map((x, i) => {
                  const upd = (patch: Partial<Interaction>) => set({ interactions: (d.interactions ?? []).map((y, j) => (j === i ? { ...y, ...patch } : y)) })
                  return (
                    <tr key={i}>
                      <td><ListInput aria-label="Классы" value={x.classes} onChange={(classes) => upd({ classes })} /></td>
                      <td>
                        <select aria-label="Значимость" value={x.severity} onChange={(e) => upd({ severity: e.target.value as Interaction['severity'] })}>
                          {Object.entries(SEVERITY).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                        </select>
                      </td>
                      <td><input aria-label="Описание" required value={x.text} onChange={(e) => upd({ text: e.target.value })} /></td>
                      <td><button type="button" className="button-link" onClick={() => set({ interactions: (d.interactions ?? []).filter((_, j) => j !== i) })}>Удалить</button></td>
                    </tr>
                  )
                })}
              </tbody>
              <tfoot>
                <tr><td colSpan={4}>
                  <button type="button" className="button-link"
                          onClick={() => set({ interactions: [...(d.interactions ?? []), { classes: [], severity: 'moderate', text: '' }] })}>Добавить взаимодействие</button>
                </td></tr>
              </tfoot>
            </table>
          </div>
        </section>

        <section aria-labelledby="mon-h">
          <h2 id="mon-h">План мониторинга при назначении</h2>
          <p className="muted">Шкалы, которые автоматически назначаются пациенту вместе с препаратом.</p>
          <div className="table-wrap">
            <table className="compact">
              <thead><tr><th scope="col">Шкала</th><th scope="col">Каждые, дней</th><th scope="col"><span className="visually-hidden">Удалить</span></th></tr></thead>
              <tbody>
                {(d.monitoring?.scales ?? []).map((s, i) => {
                  const rows = d.monitoring?.scales ?? []
                  const upd = (patch: Partial<typeof s>) => set({ monitoring: { ...d.monitoring, scales: rows.map((y, j) => (j === i ? { ...y, ...patch } : y)) } })
                  return (
                    <tr key={i}>
                      <td>
                        <select aria-label="Шкала" value={s.scale} onChange={(e) => upd({ scale: e.target.value })}>
                          {scaleCodes.map((c) => <option key={c} value={c}>{c}</option>)}
                        </select>
                      </td>
                      <td className="col-number"><input type="number" min={1} max={365} aria-label="Каждые, дней" value={s.every_days}
                                                        onChange={(e) => upd({ every_days: Number(e.target.value) })} /></td>
                      <td><button type="button" className="button-link" onClick={() => set({ monitoring: { ...d.monitoring, scales: rows.filter((_, j) => j !== i) } })}>Удалить</button></td>
                    </tr>
                  )
                })}
              </tbody>
              <tfoot>
                <tr><td colSpan={3}>
                  <button type="button" className="button-link"
                          onClick={() => set({ monitoring: { ...d.monitoring, scales: [...(d.monitoring?.scales ?? []), { scale: scaleCodes[0] ?? '', every_days: 14 }] } })}>Добавить шкалу</button>
                </td></tr>
              </tfoot>
            </table>
          </div>
        </section>

        <section aria-labelledby="si-h">
          <h2 id="si-h">Особые указания для пациента</h2>
          <label>
            По одному в строке
            <textarea rows={4} value={(d.special_instructions ?? []).join('\n')}
                      onChange={(e) => set({ special_instructions: e.target.value.split('\n') })} />
          </label>
        </section>
      </div>

      <ProposeBar kind="drug" code={d.id} body={() => ({
        ...d, special_instructions: (d.special_instructions ?? []).map((s) => s.trim()).filter(Boolean),
      })} />
    </>
  )
}

function IndicationEditor({ value, catalogue, onChange, onRemove }: {
  value: Indication
  catalogue: Variable[]
  onChange: (v: Indication) => void
  onRemove?: () => void
}) {
  const r = value.regimen ?? {}
  const setR = (patch: Partial<Regimen>) => onChange({ ...value, regimen: { ...r, ...patch } })
  return (
    <fieldset className="item-editor">
      <legend>{value.title || 'Показание'}</legend>
      <div className="row">
        <label>Код<input required pattern="[a-z0-9_]+" value={value.id} onChange={(e) => onChange({ ...value, id: e.target.value })} /></label>
        <label>
          Коды МКБ-10 (через запятую)
          <ListInput required value={value.icd10} onChange={(icd10) => onChange({ ...value, icd10: icd10.map((c) => c.toUpperCase()) })} />
        </label>
      </div>
      <label>Формулировка по инструкции<input required value={value.title} onChange={(e) => onChange({ ...value, title: e.target.value })} /></label>
      <div className="row">
        <label>Разовая доза, мг<input type="number" step="any" min={0} value={r.dose_mg ?? ''} onChange={(e) => setR({ dose_mg: num(e.target.value) })} /></label>
        <label>Приёмов в сутки<input type="number" min={1} max={6} value={r.times_per_day ?? ''} onChange={(e) => setR({ times_per_day: num(e.target.value) })} /></label>
        <label>Суточная доза, мг<input type="number" step="any" min={0} value={r.daily_mg ?? ''} onChange={(e) => setR({ daily_mg: num(e.target.value) })} /></label>
        <label>Максимальная суточная, мг<input type="number" step="any" min={0} value={r.max_daily_mg ?? ''} onChange={(e) => setR({ max_daily_mg: num(e.target.value) })} /></label>
      </div>
      <label>Режим приёма<input value={r.timing ?? ''} onChange={(e) => setR({ timing: e.target.value || undefined })} /></label>
      <label>Длительность курса<input value={r.duration ?? ''} onChange={(e) => setR({ duration: e.target.value || undefined })} /></label>
      <label className="checkbox">
        <input type="checkbox" checked={!!value.requires}
               onChange={(e) => { const next = { ...value }; if (e.target.checked) next.requires = { '==': [{ var: 'patient.post_covid' }, true] }; else delete next.requires; onChange(next) }} />
        Показание действует только при дополнительном условии
      </label>
      {value.requires && (
        <ConditionBuilder value={value.requires} catalogue={catalogue} label="Дополнительное условие"
                          onChange={(requires) => onChange({ ...value, requires })} />
      )}
      {onRemove && <p><button type="button" className="secondary danger" onClick={onRemove}>Удалить показание</button></p>}
    </fieldset>
  )
}

function FindingsEditor({ title, hint, items, catalogue, withNote = false, onChange }: {
  title: string
  hint: string
  items: Finding[]
  catalogue: Variable[]
  withNote?: boolean
  onChange: (items: Finding[]) => void
}) {
  const upd = (i: number, patch: Partial<Finding>) => onChange(items.map((x, j) => (j === i ? { ...x, ...patch } : x)))
  return (
    <section>
      <h2>{title}</h2>
      <p className="muted">{hint}</p>
      {items.map((f, i) => (
        <fieldset key={`${i}-${f.id}`} className="item-editor">
          <legend>{f.title || 'Новый пункт'}</legend>
          <div className="row">
            <label>Код<input required pattern="[a-z0-9_]+" value={f.id} onChange={(e) => upd(i, { id: e.target.value })} /></label>
          </div>
          <label>Формулировка по инструкции<input required value={f.title} onChange={(e) => upd(i, { title: e.target.value })} /></label>
          <ConditionBuilder value={f.when} catalogue={catalogue} label="Когда применяется" onChange={(when) => upd(i, { when })} />
          {withNote && (
            <label>Пояснение для врача<input value={f.note ?? ''} onChange={(e) => upd(i, { note: e.target.value || undefined })} /></label>
          )}
          <p><button type="button" className="secondary danger" onClick={() => onChange(items.filter((_, j) => j !== i))}>Удалить</button></p>
        </fieldset>
      ))}
      <p><button type="button" className="secondary"
                 onClick={() => onChange([...items, { id: `item_${items.length + 1}`, title: '', when: DEFAULT_WHEN }])}>Добавить</button></p>
    </section>
  )
}

/** Список через запятую: текст редактируется свободно, разбирается при выходе из поля. */
function ListInput({ value, onChange, ...rest }: { value: string[]; onChange: (v: string[]) => void; required?: boolean; 'aria-label'?: string }) {
  const [text, setText] = useState(value.join(', '))
  return <input {...rest} value={text} onChange={(e) => setText(e.target.value)} onBlur={() => { const v = list(text); onChange(v); setText(v.join(', ')) }} />
}
