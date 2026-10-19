import { api } from './client'

type Handler = (event: string, data: unknown) => void

/**
 * SSE-подписка с одноразовыми билетами: при обрыве берётся новый билет и
 * пропущенные события досылаются сервером по last_event_id.
 */
export function subscribe(path: string, events: string[], onEvent: Handler): () => void {
  let source: EventSource | null = null
  let lastId: string | null = null
  let stopped = false
  let timer: number | undefined

  const connect = async () => {
    try {
      const { ticket } = await api.post<{ ticket: string }>('/api/auth/stream-ticket')
      if (stopped) return
      const qs = new URLSearchParams({ ticket })
      if (lastId) qs.set('last_event_id', lastId)
      source = new EventSource(`${path}?${qs}`)
      for (const name of events) {
        source.addEventListener(name, (e) => {
          const msg = e as MessageEvent<string>
          if (msg.lastEventId) lastId = msg.lastEventId
          onEvent(name, JSON.parse(msg.data))
        })
      }
      source.onerror = () => {
        source?.close()
        retry()
      }
    } catch {
      retry()
    }
  }

  const retry = () => {
    if (!stopped) timer = window.setTimeout(connect, 3000)
  }

  connect()
  return () => {
    stopped = true
    window.clearTimeout(timer)
    source?.close()
  }
}
