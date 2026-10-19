export interface Series {
  name: string
  points: { x: string; y: number | null }[]
  className: string
}

/** Простой линейный график без зависимостей: ось X — даты (строки ISO), ось Y — от yMin до yMax. */
export function LineChart({ series, yMin = 0, yMax, title }: {
  series: Series[]
  yMin?: number
  yMax?: number
  title: string
}) {
  const xs = [...new Set(series.flatMap((s) => s.points.map((p) => p.x)))].sort()
  const values = series.flatMap((s) => s.points.map((p) => p.y)).filter((v): v is number => v !== null)
  if (xs.length === 0 || values.length === 0) return null
  const top = yMax ?? Math.max(...values, yMin + 1)
  const W = 640
  const H = 200
  const pad = { l: 32, r: 8, t: 8, b: 24 }
  const x = (v: string) => pad.l + (xs.length === 1 ? 0 : (xs.indexOf(v) / (xs.length - 1)) * (W - pad.l - pad.r))
  const y = (v: number) => pad.t + (1 - (v - yMin) / (top - yMin || 1)) * (H - pad.t - pad.b)
  const ticks = [yMin, (yMin + top) / 2, top]

  return (
    <figure className="chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={title}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={pad.l} x2={W - pad.r} y1={y(t)} y2={y(t)} className="chart-grid" />
            <text x={pad.l - 4} y={y(t) + 4} textAnchor="end" className="chart-label">{Math.round(t * 10) / 10}</text>
          </g>
        ))}
        <text x={pad.l} y={H - 6} className="chart-label">{xs[0].slice(0, 10)}</text>
        <text x={W - pad.r} y={H - 6} textAnchor="end" className="chart-label">{xs[xs.length - 1].slice(0, 10)}</text>
        {series.map((s) => {
          const pts = s.points.filter((p) => p.y !== null) as { x: string; y: number }[]
          return (
            <g key={s.name} className={s.className}>
              <polyline fill="none" points={pts.map((p) => `${x(p.x)},${y(p.y)}`).join(' ')} />
              {pts.map((p) => <circle key={p.x} cx={x(p.x)} cy={y(p.y)} r={2.5} />)}
            </g>
          )
        })}
      </svg>
      <figcaption>
        {title}: {series.map((s) => <span key={s.name} className={`legend ${s.className}`}>{s.name}</span>)}
      </figcaption>
    </figure>
  )
}
