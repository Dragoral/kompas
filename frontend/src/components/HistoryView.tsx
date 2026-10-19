import type { History } from '../api/types'
import { formatDate, formatDateTime } from '../format'
import { LineChart } from './LineChart'

/** История наблюдения: дневник, шкалы, приём препарата. Общая для пациента и врача. */
export function HistoryView({ history }: { history: History }) {
  const diary = history.diary
  return (
    <>
      <h2>Дневник</h2>
      {diary.length === 0 ? <p>Записей нет.</p> : (
        <>
          <LineChart title="Самочувствие, 0–10" yMax={10} series={[
            { name: 'Настроение', className: 'series-1', points: diary.map((d) => ({ x: d.day, y: d.mood })) },
            { name: 'Тревога', className: 'series-2', points: diary.map((d) => ({ x: d.day, y: d.anxiety })) },
            { name: 'Качество сна', className: 'series-3', points: diary.map((d) => ({ x: d.day, y: d.sleep_quality })) },
          ]} />
          <details>
            <summary>Таблица записей</summary>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th scope="col">Дата</th>
                    <th scope="col">Настроение</th>
                    <th scope="col">Тревога</th>
                    <th scope="col">Сон, ч</th>
                    <th scope="col">Качество сна</th>
                  </tr>
                </thead>
                <tbody>
                  {[...diary].reverse().map((d) => (
                    <tr key={d.day}>
                      <td>{formatDate(d.day)}</td>
                      <td>{d.mood ?? '—'}</td>
                      <td>{d.anxiety ?? '—'}</td>
                      <td>{d.sleep_hours ?? '—'}</td>
                      <td>{d.sleep_quality ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        </>
      )}

      <h2>Опросники</h2>
      {Object.keys(history.scales).length === 0 ? <p>Результатов нет.</p> : (
        Object.entries(history.scales).map(([code, results]) => (
          <section key={code}>
            <h3>{code}</h3>
            <LineChart title={`${code}, балл`} series={[
              { name: 'Балл', className: 'series-1', points: results.map((r) => ({ x: r.at, y: r.score })) },
            ]} />
            <details>
              <summary>Таблица результатов</summary>
              <table>
                <thead><tr><th scope="col">Дата</th><th scope="col">Балл</th><th scope="col">Интерпретация</th></tr></thead>
                <tbody>
                  {[...results].reverse().map((r) => (
                    <tr key={r.at}><td>{formatDateTime(r.at)}</td><td>{r.score}</td><td>{r.band ?? '—'}</td></tr>
                  ))}
                </tbody>
              </table>
            </details>
          </section>
        ))
      )}

      {history.adherence.length > 0 && (
        <>
          <h2>Приём препарата</h2>
          <LineChart title="Принято доз за день, %" yMax={100} series={[{
            name: 'Принято', className: 'series-1',
            points: history.adherence.map((a) => ({ x: a.day, y: a.planned ? Math.round((a.taken / a.planned) * 100) : null })),
          }]} />
        </>
      )}
    </>
  )
}
