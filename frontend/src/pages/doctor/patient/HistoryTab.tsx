import { HistoryView } from '../../../components/HistoryView'
import { usePatient } from './PatientLayout'

export function HistoryTab() {
  const { card } = usePatient()
  return <HistoryView history={card.history} />
}
