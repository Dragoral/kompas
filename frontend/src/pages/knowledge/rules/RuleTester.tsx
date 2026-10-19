import { useState } from 'react'
import { api } from '../../../api/client'
import type { PatientRow } from '../../../api/types'
import { useAction, useApi } from '../../../api/useApi'
import type { Condition } from '../../../components/condition/model'
import { ErrorMessage } from '../../../components/ErrorMessage'

interface Explain {
  expr: unknown
  value: unknown
  args?: Explain[]
}

const OP_TEXT: Record<string, string> = {
  and: 'все условия', or: 'любое из условий', '!': 'не', not: 'не',
  '==': '=', '!=': '≠', '>': '>', '>=': '≥', '<': '<', '<=': '≤',
  in: 'входит в', some_in: 'есть общее с', starts_any: 'начинается с',
}

const show = (v: unknown) => (v === null || v === undefined ? 'нет данных' : typeof v === 'boolean' ? (v ? 'да' : 'нет') : JSON.stringify(v))

/** Проверка условия на своём пациенте с пошаговым объяснением (только для врача). */
export function RuleTester({ condition }: { condition: Condition }) {
  const patients = useApi<PatientRow[]>('/api/doctor/patients?sort=name&desc=false')
  const [patientId, setPatientId] = useState('')
  const [result, setResult] = useState<{ result: boolean; explain: Explain } | null>(null)
  const test = useAction(() => api.post<{ result: boolean; explain: Explain }>('/api/knowledge/rules/test',
    { condition, patient_id: Number(patientId) }))

  return (
    <fieldset>
      <legend>Проверить на пациенте</legend>
      <div className="row">
        <label>
          Пациент
          <select value={patientId} onChange={(e) => { setPatientId(e.target.value); setResult(null) }}>
            <option value="">— выберите —</option>
            {(patients.data ?? []).map((p) => <option key={p.id} value={p.id}>{p.full_name} ({p.code})</option>)}
          </select>
        </label>
        <button type="button" className="secondary" disabled={!patientId || test.pending}
                onClick={async () => setResult((await test.run()) ?? null)}>Проверить</button>
      </div>
      <ErrorMessage error={test.error} />
      {result && (
        <div className={result.result ? 'message message-error' : 'message'} role="status">
          <p><strong>{result.result ? 'Правило сработало бы' : 'Правило не сработало бы'}</strong></p>
          <ExplainTree node={result.explain} />
        </div>
      )}
    </fieldset>
  )
}

function ExplainTree({ node }: { node: Explain }) {
  const op = typeof node.expr === 'string' ? node.expr : JSON.stringify(node.expr)
  return (
    <ul className="explain">
      <li>
        {op.startsWith('переменная ') ? op : node.args ? OP_TEXT[op] ?? op : 'значение'}: <strong>{show(node.value)}</strong>
        {node.args?.map((a, i) => <ExplainTree key={i} node={a} />)}
      </li>
    </ul>
  )
}
