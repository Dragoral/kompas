import { Chat } from '../../components/Chat'

export function MessagesPage() {
  return (
    <>
      <h1>Сообщения врачу</h1>
      <p className="muted">
        Врач отвечает в рабочее время. Если вам срочно нужна помощь, звоните 112 или 103.
      </p>
      <Chat path="/api/me/messages" stream="/api/me/stream" me="patient" />
    </>
  )
}
