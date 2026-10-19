import { useState } from 'react'
import type { History } from '../../api/types'
import { useApi } from '../../api/useApi'
import { HistoryView } from '../../components/HistoryView'
import { Loader } from '../../components/Loader'

const PERIODS = [14, 30, 90, 365]

export function HistoryPage() {
  const [days, setDays] = useState(30)
  const state = useApi<History>(`/api/me/history?days=${days}`)

  return (
    <>
      <h1>Моя история</h1>
      <label className="inline">
        Период{' '}
        <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
          {PERIODS.map((d) => <option key={d} value={d}>{d} дней</option>)}
        </select>
      </label>
      <Loader state={state}>{(h) => <HistoryView history={h} />}</Loader>
    </>
  )
}
