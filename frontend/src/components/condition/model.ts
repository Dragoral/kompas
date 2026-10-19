/**
 * Условия правил хранятся как JSON-logic. Здесь — перевод простых условий
 * («переменная оператор значение», объединённые через И/ИЛИ) в модель формы и обратно.
 * Условия сложнее этой модели редактируются как JSON.
 */

export type Condition = Record<string, unknown>

export interface Variable {
  path: string
  type: string
  description: string
}

export type ClauseOp = '==' | '!=' | '>' | '>=' | '<' | '<=' | 'contains' | 'contains_any' | 'one_of'

export type Value =
  | { kind: 'number'; value: string }
  | { kind: 'text'; value: string }
  | { kind: 'bool'; value: boolean }
  | { kind: 'list'; value: string }
  | { kind: 'threshold'; value: string }

export interface Clause {
  path: string
  op: ClauseOp
  value: Value
}

export interface Group {
  join: 'and' | 'or'
  clauses: Clause[]
}

export const OP_LABEL: Record<ClauseOp, string> = {
  '==': 'равно',
  '!=': 'не равно',
  '>': 'больше',
  '>=': 'не меньше',
  '<': 'меньше',
  '<=': 'не больше',
  contains: 'содержит',
  contains_any: 'содержит любое из',
  one_of: 'одно из',
}

export function opsFor(type: string): ClauseOp[] {
  if (type === 'число') return ['>=', '>', '<=', '<', '==', '!=']
  if (type === 'да/нет') return ['==']
  if (type === 'список') return ['contains', 'contains_any']
  return ['==', '!=', 'one_of']
}

export function defaultValue(type: string, op: ClauseOp): Value {
  if (op === 'contains_any' || op === 'one_of') return { kind: 'list', value: '' }
  if (type === 'число') return { kind: 'number', value: '' }
  if (type === 'да/нет') return { kind: 'bool', value: true }
  return { kind: 'text', value: '' }
}

/** Шаблон каталога (scales.*.score) подходит к конкретному пути (scales.PHQ9.score). */
export function matchTemplate(template: string, path: string): boolean {
  const t = template.split('.')
  const p = path.split('.')
  return t.length === p.length && t.every((x, i) => x === '*' || x === p[i])
}

export function findVariable(catalogue: Variable[], path: string): Variable | undefined {
  return catalogue.find((v) => v.path === path) ?? catalogue.find((v) => matchTemplate(v.path, path))
}

const isVar = (x: unknown): x is { var: string } =>
  typeof x === 'object' && x !== null && 'var' in x && typeof (x as { var: unknown }).var === 'string'
const isLiteral = (x: unknown) => ['string', 'number', 'boolean'].includes(typeof x)
const splitList = (s: string) => s.split(',').map((x) => x.trim()).filter(Boolean)
const literal = (s: string) => (s.trim() !== '' && !Number.isNaN(Number(s)) ? Number(s) : s.trim())

function literalValue(x: unknown): Value | null {
  if (typeof x === 'number') return { kind: 'number', value: String(x) }
  if (typeof x === 'boolean') return { kind: 'bool', value: x }
  if (typeof x === 'string') return { kind: 'text', value: x }
  if (isVar(x) && x.var.startsWith('thresholds.')) return { kind: 'threshold', value: x.var.slice('thresholds.'.length) }
  return null
}

function parseClause(c: unknown): Clause | null {
  if (typeof c !== 'object' || c === null || Array.isArray(c)) return null
  const entries = Object.entries(c)
  if (entries.length !== 1) return null
  const [op, args] = entries[0]
  if (!Array.isArray(args) || args.length !== 2) return null
  const [a, b] = args
  if (['==', '!=', '>', '>=', '<', '<='].includes(op) && isVar(a)) {
    const v = literalValue(b)
    return v ? { path: a.var, op: op as ClauseOp, value: v } : null
  }
  if (op === 'in' && isLiteral(a) && isVar(b)) return { path: b.var, op: 'contains', value: { kind: 'text', value: String(a) } }
  if (op === 'in' && isVar(a) && Array.isArray(b) && b.every(isLiteral)) {
    return { path: a.var, op: 'one_of', value: { kind: 'list', value: b.join(', ') } }
  }
  if (op === 'some_in' && Array.isArray(a) && a.every(isLiteral) && isVar(b)) {
    return { path: b.var, op: 'contains_any', value: { kind: 'list', value: a.join(', ') } }
  }
  return null
}

/** null — условие нельзя показать формой (редактируется как JSON). */
export function parse(cond: unknown): Group | null {
  if (typeof cond === 'object' && cond !== null && !Array.isArray(cond)) {
    const keys = Object.keys(cond)
    if (keys.length === 1 && (keys[0] === 'and' || keys[0] === 'or')) {
      const list = (cond as Record<string, unknown>)[keys[0]]
      if (!Array.isArray(list)) return null
      const clauses = list.map(parseClause)
      return clauses.every(Boolean) ? { join: keys[0] as 'and' | 'or', clauses: clauses as Clause[] } : null
    }
  }
  const one = parseClause(cond)
  return one ? { join: 'and', clauses: [one] } : null
}

function valueJson(v: Value): unknown {
  switch (v.kind) {
    case 'number': return Number(v.value)
    case 'bool': return v.value
    case 'threshold': return { var: `thresholds.${v.value}` }
    case 'list': return splitList(v.value).map(literal)
    default: return v.value
  }
}

function clauseJson(c: Clause): Condition {
  const v = { var: c.path }
  if (c.op === 'contains') return { in: [literal(c.value.value as string), v] }
  if (c.op === 'contains_any') return { some_in: [valueJson(c.value), v] }
  if (c.op === 'one_of') return { in: [v, valueJson(c.value)] }
  return { [c.op]: [v, valueJson(c.value)] }
}

export function serialize(g: Group): Condition {
  const parts = g.clauses.map(clauseJson)
  return parts.length === 1 ? parts[0] : { [g.join]: parts }
}

/** Человекочитаемая запись условия — для списков правил и подтверждений. */
export function describe(cond: unknown, catalogue: Variable[]): string {
  const g = parse(cond)
  if (!g) return JSON.stringify(cond)
  const text = g.clauses.map((c) => {
    const name = findVariable(catalogue, c.path)?.description ?? c.path
    const where = c.path.split('.').filter((_, i) => findVariable(catalogue, c.path)?.path.split('.')[i] === '*')
    const label = where.length ? `${name} (${where.join(', ')})` : name
    const v = c.value
    const val = v.kind === 'bool' ? (v.value ? 'да' : 'нет') : v.kind === 'threshold' ? `порог «${v.value}»` : String(v.value)
    return `${label} ${OP_LABEL[c.op]} ${val}`
  })
  return text.join(g.join === 'and' ? ' И ' : ' ИЛИ ')
}
