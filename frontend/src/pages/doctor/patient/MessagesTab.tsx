import { Chat } from '../../../components/Chat'
import { usePatient } from './PatientLayout'

export function MessagesTab() {
  const { id } = usePatient()
  return <Chat path={`/api/doctor/patients/${id}/messages`} stream="/api/doctor/stream" me="doctor" />
}
