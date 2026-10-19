import { NumberInput } from './ItemsEditor'
import type { Band } from './model'

const SEVERITY = ['Нет', 'Лёгкая', 'Умеренная', 'Тяжёлая']

export function BandsEditor({ bands, onChange, caption = 'Градации суммарного балла' }: {
  bands: Band[]
  onChange: (bands: Band[]) => void
  caption?: string
}) {
  const update = (i: number, patch: Partial<Band>) => onChange(bands.map((b, j) => (j === i ? { ...b, ...patch } : b)))
  const add = () => {
    const last = bands[bands.length - 1]
    const start = last ? last.max + 1 : 0
    onChange([...bands, { min: start, max: start, label: '', severity: Math.min((last?.severity ?? -1) + 1, 3) }])
  }

  return (
    <div className="table-wrap">
      <table className="compact">
        <caption>{caption}</caption>
        <thead>
          <tr>
            <th scope="col">От</th>
            <th scope="col">До</th>
            <th scope="col">Интерпретация</th>
            <th scope="col">Тяжесть</th>
            <th scope="col"><span className="visually-hidden">Удалить</span></th>
          </tr>
        </thead>
        <tbody>
          {bands.map((b, i) => (
            <tr key={i}>
              <td className="col-number"><NumberInput value={b.min} required aria-label="От" onChange={(v) => update(i, { min: v ?? 0 })} /></td>
              <td className="col-number"><NumberInput value={b.max} required aria-label="До" onChange={(v) => update(i, { max: v ?? 0 })} /></td>
              <td><input required value={b.label} aria-label="Интерпретация" onChange={(e) => update(i, { label: e.target.value })} /></td>
              <td>
                <select value={b.severity ?? 0} aria-label="Тяжесть" onChange={(e) => update(i, { severity: Number(e.target.value) })}>
                  {SEVERITY.map((s, v) => <option key={v} value={v}>{s}</option>)}
                </select>
              </td>
              <td>
                <button type="button" className="button-link" disabled={bands.length <= 1}
                        onClick={() => onChange(bands.filter((_, j) => j !== i))}>Удалить</button>
              </td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr><td colSpan={5}><button type="button" className="button-link" onClick={add}>Добавить градацию</button></td></tr>
        </tfoot>
      </table>
    </div>
  )
}
