import { useApi } from '../../../api/useApi'

/** Действие правила: имя или {имя: параметр}, например {escalate: {after_min: 15}}, {request_scale: "CSSRS"}. */
export type Action = string | Record<string, unknown>

const nameOf = (a: Action) => (typeof a === 'string' ? a : Object.keys(a)[0])
const argOf = (a: Action) => (typeof a === 'string' ? undefined : Object.values(a)[0])

export function ActionsEditor({ actions, onChange, thresholds, scaleCodes }: {
  actions: Action[]
  onChange: (a: Action[]) => void
  thresholds: string[]
  scaleCodes: string[]
}) {
  const catalogue = useApi<{ name: string; description: string }[]>('/api/knowledge/actions')
  const byName = new Map(actions.map((a) => [nameOf(a), a]))

  const toggle = (name: string, on: boolean) => {
    if (!on) return onChange(actions.filter((a) => nameOf(a) !== name))
    const initial: Action = name === 'escalate' ? { escalate: { after_min: 15 } }
      : name === 'request_scale' ? { request_scale: scaleCodes[0] ?? '' } : name
    onChange([...actions, initial])
  }
  const setArg = (name: string, arg: unknown) => onChange(actions.map((a) => (nameOf(a) === name ? { [name]: arg } : a)))

  const escalate = argOf(byName.get('escalate') ?? '') as { after_min?: number | string } | undefined
  const scale = argOf(byName.get('request_scale') ?? '') as string | undefined

  return (
    <fieldset>
      <legend>Что сделать при срабатывании</legend>
      {(catalogue.data ?? []).map((a) => (
        <div key={a.name}>
          <label className="checkbox">
            <input type="checkbox" checked={byName.has(a.name)} onChange={(e) => toggle(a.name, e.target.checked)} />
            {a.description || a.name}
          </label>
          {a.name === 'escalate' && byName.has('escalate') && (
            <label className="inline nested">
              Эскалировать через{' '}
              <select value={typeof escalate?.after_min === 'string' ? escalate.after_min : 'number'}
                      onChange={(e) => setArg('escalate', { after_min: e.target.value === 'number' ? 15 : e.target.value })}>
                <option value="number">заданное число минут</option>
                {thresholds.map((t) => <option key={t} value={`thresholds.${t}`}>порог {t}</option>)}
              </select>
              {typeof escalate?.after_min !== 'string' && (
                <> <input type="number" min={1} className="short" aria-label="Минут" value={escalate?.after_min ?? 15}
                          onChange={(e) => setArg('escalate', { after_min: Number(e.target.value) })} /> мин</>
              )}
            </label>
          )}
          {a.name === 'request_scale' && byName.has('request_scale') && (
            <label className="inline nested">
              Шкала{' '}
              <select value={scale ?? ''} onChange={(e) => setArg('request_scale', e.target.value)}>
                {scaleCodes.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </label>
          )}
        </div>
      ))}
    </fieldset>
  )
}
