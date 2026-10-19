import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import type { KnowledgeRow } from '../../../api/types'
import { useApi } from '../../../api/useApi'
import { useAuth } from '../../../auth/AuthContext'
import { ConditionBuilder } from '../../../components/condition/ConditionBuilder'
import { describe, type Condition, type Variable } from '../../../components/condition/model'
import { Loader } from '../../../components/Loader'
import { SEVERITY_LABEL, LEVEL_LABEL } from '../../../format'
import { ProposeBar } from '../ProposeBar'
import { ActionsEditor, type Action } from './ActionsEditor'
import { RuleTester } from './RuleTester'

export interface Rule {
  id: string
  title?: string
  when: Condition
  severity?: 'critical' | 'high' | 'medium'
  level?: 'mandatory' | 'desirable'
  target?: string
  applies?: string
  urgency?: string
  message?: string
  actions?: Action[]
  source?: string
  [key: string]: unknown
}

interface RuleSet {
  rules: Rule[]
  thresholds?: Record<string, { default: number; title?: string }>
  targets?: Record<string, string>
  applies?: Record<string, Condition>
  verified?: boolean
  [key: string]: unknown
}

/** Наборы правил: оповещения (severity, actions, thresholds) и маршрутизация (target, level). */
export function RulesEditorPage() {
  const { code = '' } = useParams()
  const state = useApi<{ body: RuleSet; version: number }>(`/api/knowledge/rules/${encodeURIComponent(code)}`)
  const variables = useApi<Variable[]>('/api/knowledge/variables')
  return (
    <Loader state={state}>
      {(r) => (
        <Loader state={variables}>
          {(vars) => <RulesEditor code={code} initial={r.body} version={r.version} catalogue={vars} />}
        </Loader>
      )}
    </Loader>
  )
}

function RulesEditor({ code, initial, version, catalogue }: {
  code: string
  initial: RuleSet
  version: number
  catalogue: Variable[]
}) {
  const { user } = useAuth()
  const [set, setSet] = useState<RuleSet>(initial)
  const [open, setOpen] = useState<number | null>(null)
  const scales = useApi<KnowledgeRow[]>('/api/knowledge')
  const scaleCodes = (scales.data ?? []).filter((x) => x.kind === 'scale').map((x) => x.code)
  const isAlerts = set.rules.some((r) => r.severity) || !!set.thresholds
  const thresholds = Object.keys(set.thresholds ?? {})

  const updateRule = (i: number, r: Rule) => setSet({ ...set, rules: set.rules.map((x, j) => (j === i ? r : x)) })
  const addRule = () => {
    const base: Rule = isAlerts
      ? { id: `rule_${set.rules.length + 1}`, title: '', severity: 'medium', when: { '>=': [{ var: 'scales.PHQ9.score' }, 10] }, actions: ['notify_doctor'], source: '' }
      : { id: `rule_${set.rules.length + 1}`, title: '', target: Object.keys(set.targets ?? {})[0], level: 'desirable', applies: 'all',
          when: { '>=': [{ var: 'scales.PHQ9.score' }, 10] }, source: '' }
    setSet({ ...set, rules: [...set.rules, base] })
    setOpen(set.rules.length)
  }

  return (
    <>
      <h1>{isAlerts ? 'Правила оповещений' : 'Правила маршрутизации'}</h1>
      <p className="muted">Действующая версия: {version}. Изменения вступят в силу после одобрения рецензентом.</p>
      <p><Link to="/knowledge">К справочникам</Link></p>

      {set.thresholds && (
        <ThresholdsEditor thresholds={set.thresholds} onChange={(t) => setSet({ ...set, thresholds: t })} />
      )}
      {set.targets && (
        <TargetsEditor targets={set.targets} onChange={(t) => setSet({ ...set, targets: t })} />
      )}

      <h2>Правила</h2>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th scope="col">Правило</th>
              <th scope="col">{isAlerts ? 'Уровень' : 'Направление'}</th>
              <th scope="col">Срабатывает, если</th>
              <th scope="col"><span className="visually-hidden">Действия</span></th>
            </tr>
          </thead>
          <tbody>
            {set.rules.map((r, i) => (
              <tr key={i}>
                <td>{r.title || <code>{r.id}</code>}</td>
                <td>
                  {r.severity && <span className={`badge badge-${r.severity}`}>{SEVERITY_LABEL[r.severity]}</span>}
                  {r.level && <span className={`badge badge-${r.level}`}>{LEVEL_LABEL[r.level]}</span>}
                  {r.target && <div className="small">{set.targets?.[r.target] ?? r.target}</div>}
                </td>
                <td className="small">{describe(r.when, catalogue)}</td>
                <td className="nowrap">
                  <button type="button" className="button-link" onClick={() => setOpen(open === i ? null : i)}>
                    {open === i ? 'Свернуть' : 'Изменить'}
                  </button>
                  {' · '}
                  <button type="button" className="button-link"
                          onClick={() => { if (window.confirm(`Удалить правило «${r.title || r.id}»?`)) { setSet({ ...set, rules: set.rules.filter((_, j) => j !== i) }); setOpen(null) } }}>
                    Удалить
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {open !== null && set.rules[open] && (
        <RuleForm key={open} rule={set.rules[open]} isAlerts={isAlerts} catalogue={catalogue} thresholds={thresholds}
                  targets={set.targets ?? {}} applies={Object.keys(set.applies ?? {})} scaleCodes={scaleCodes}
                  canTest={user?.role === 'doctor'} onChange={(r) => updateRule(open, r)} />
      )}
      <p><button type="button" className="secondary" onClick={addRule}>Добавить правило</button></p>

      <ProposeBar kind="rules" code={code} body={() => set} />
    </>
  )
}

function RuleForm({ rule, isAlerts, catalogue, thresholds, targets, applies, scaleCodes, canTest, onChange }: {
  rule: Rule
  isAlerts: boolean
  catalogue: Variable[]
  thresholds: string[]
  targets: Record<string, string>
  applies: string[]
  scaleCodes: string[]
  canTest: boolean
  onChange: (r: Rule) => void
}) {
  const set = (patch: Partial<Rule>) => onChange({ ...rule, ...patch })
  return (
    <div className="form panel wide">
      <h3>Правило {rule.title || rule.id}</h3>
      <div className="row">
        <label>
          Код правила
          <input required pattern="[a-z0-9_]{2,64}" value={rule.id} aria-describedby="rule-id-hint"
                 onChange={(e) => set({ id: e.target.value })} />
          <span id="rule-id-hint" className="muted small">Строчная латиница, цифры, «_»</span>
        </label>
        {isAlerts ? (
          <label>
            Уровень оповещения
            <select value={rule.severity} onChange={(e) => set({ severity: e.target.value as Rule['severity'] })}>
              {Object.entries(SEVERITY_LABEL).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </label>
        ) : (
          <label>
            Уровень направления
            <select value={rule.level} onChange={(e) => set({ level: e.target.value as Rule['level'] })}>
              {Object.entries(LEVEL_LABEL).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </label>
        )}
      </div>
      <label>
        Название
        <input required value={rule.title ?? ''} onChange={(e) => set({ title: e.target.value })} />
      </label>
      {!isAlerts && (
        <div className="row">
          <label>
            Направление
            <select value={rule.target} onChange={(e) => set({ target: e.target.value })}>
              {Object.entries(targets).map(([k, t]) => <option key={k} value={k}>{t}</option>)}
            </select>
          </label>
          <label>
            Для кого действует
            <select value={rule.applies ?? 'all'} onChange={(e) => set({ applies: e.target.value })}>
              {applies.map((a) => <option key={a} value={a}>{a === 'all' ? 'для всех врачей' : a === 'non_psychiatrist' ? 'для врачей-непсихиатров' : a}</option>)}
            </select>
          </label>
          <label>
            Срочность
            <input value={rule.urgency ?? ''} onChange={(e) => set({ urgency: e.target.value || undefined })} />
          </label>
        </div>
      )}
      <ConditionBuilder value={rule.when} onChange={(when) => set({ when })} catalogue={catalogue} thresholds={thresholds}
                        label="Срабатывает, если" />
      {isAlerts && (
        <>
          <label>
            Текст оповещения для врача
            <input value={rule.message ?? ''} aria-describedby="msg-hint" onChange={(e) => set({ message: e.target.value })} />
            <span id="msg-hint" className="muted small">Можно подставлять значения: {'{scales.PHQ9.score}'}, {'{adherence.pct_14d}'} и т. п.</span>
          </label>
          <ActionsEditor actions={rule.actions ?? []} onChange={(actions) => set({ actions })} thresholds={thresholds} scaleCodes={scaleCodes} />
        </>
      )}
      <label>
        Источник (клиническая рекомендация, публикация)
        <input value={rule.source ?? ''} onChange={(e) => set({ source: e.target.value })} />
      </label>
      {canTest && <RuleTester condition={rule.when} />}
    </div>
  )
}

function ThresholdsEditor({ thresholds, onChange }: {
  thresholds: NonNullable<RuleSet['thresholds']>
  onChange: (t: NonNullable<RuleSet['thresholds']>) => void
}) {
  const [newKey, setNewKey] = useState('')
  return (
    <section aria-labelledby="thr-h">
      <h2 id="thr-h">Пороги</h2>
      <p className="muted">Значения по умолчанию для всех пациентов. Для отдельного пациента их можно изменить в карточке.</p>
      <div className="table-wrap">
        <table className="compact">
          <thead><tr><th scope="col">Код</th><th scope="col">Описание</th><th scope="col">Значение</th></tr></thead>
          <tbody>
            {Object.entries(thresholds).map(([k, t]) => (
              <tr key={k}>
                <td><code>{k}</code></td>
                <td><input aria-label={`Описание ${k}`} value={t.title ?? ''} onChange={(e) => onChange({ ...thresholds, [k]: { ...t, title: e.target.value } })} /></td>
                <td className="col-number">
                  <input type="number" step="any" required aria-label={`Значение ${k}`} value={t.default}
                         onChange={(e) => onChange({ ...thresholds, [k]: { ...t, default: Number(e.target.value) } })} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="row">
        <label>
          Код нового порога (латиница)
          <input value={newKey} pattern="[a-z0-9_]+" onChange={(e) => setNewKey(e.target.value)} />
        </label>
        <button type="button" className="secondary" onClick={() => {
          const k = newKey.trim().toLowerCase()
          if (k && !thresholds[k]) { onChange({ ...thresholds, [k]: { default: 0, title: '' } }); setNewKey('') }
        }}>Добавить порог</button>
      </div>
    </section>
  )
}

function TargetsEditor({ targets, onChange }: { targets: Record<string, string>; onChange: (t: Record<string, string>) => void }) {
  return (
    <section aria-labelledby="targets-h">
      <h2 id="targets-h">Направления</h2>
      <div className="table-wrap">
        <table className="compact">
          <thead><tr><th scope="col">Код</th><th scope="col">Как показывается врачу</th></tr></thead>
          <tbody>
            {Object.entries(targets).map(([k, t]) => (
              <tr key={k}>
                <td><code>{k}</code></td>
                <td><input aria-label={`Направление ${k}`} value={t} onChange={(e) => onChange({ ...targets, [k]: e.target.value })} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
