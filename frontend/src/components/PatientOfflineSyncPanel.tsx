import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import { listOfflineQueue, removeOfflineQueue, type OfflineQueueItem } from '../api/offlineQueue'
import { useAuth } from '../auth/AuthContext'

interface SyncResult { client_id: string | null; ok: boolean; id?: number; error?: string; retry?: boolean }
const KIND_LABEL: Record<string, string> = { scale: 'Результат шкалы', diary: 'Запись дневника', dose: 'Отметка приёма', adverse: 'Нежелательная реакция', message: 'Сообщение врачу' }

/** Visible only for the patient account; data is sent to the existing idempotent /api/me/sync endpoint. */
export function PatientOfflineSyncPanel() {
  const { user } = useAuth()
  const patientUserId = user?.role === 'patient' ? user.id : null
  const [items, setItems] = useState<OfflineQueueItem[]>([])
  const [loading, setLoading] = useState(false)
  const [notice, setNotice] = useState('')
  const [failures, setFailures] = useState<SyncResult[]>([])
  const [isOnline, setIsOnline] = useState(() => typeof navigator === 'undefined' || navigator.onLine)

  const refresh = useCallback(async () => {
    if (patientUserId === null) { setItems([]); return }
    try { setItems(await listOfflineQueue(patientUserId)) }
    catch { setNotice('Не удалось прочитать локальную очередь. Проверьте поддержку хранилища браузера.') }
  }, [patientUserId])

  const syncNow = useCallback(async () => {
    if (patientUserId === null) return
    if (!isOnline) { setNotice('Нет подключения. Записи останутся на этом устройстве до восстановления связи.'); return }
    setLoading(true); setNotice(''); setFailures([])
    try {
      const queued = await listOfflineQueue(patientUserId)
      if (!queued.length) { setItems([]); setNotice(''); return }
      const response = await api.post<{ results: SyncResult[] }>('/api/me/sync', { items: queued.map((item) => ({ kind: item.kind, data: item.data })) })
      const acceptedIds = new Set(response.results.filter((r) => r.ok && r.client_id).map((r) => r.client_id as string))
      const acceptedKeys = queued.filter((item) => acceptedIds.has(String(item.data.client_id))).map((item) => item.key)
      await removeOfflineQueue(acceptedKeys)
      const failed = response.results.filter((r) => !r.ok)
      setFailures(failed)
      setNotice(`Синхронизировано записей: ${acceptedKeys.length}. Ошибок: ${failed.length}.`)
      await refresh()
    } catch (e) {
      setNotice(e instanceof Error ? `Синхронизация не выполнена: ${e.message}` : 'Синхронизация не выполнена; записи сохранены локально.')
    } finally { setLoading(false) }
  }, [patientUserId, refresh, isOnline])

  useEffect(() => {
    if (patientUserId === null) return
    void refresh()
    if (navigator.onLine) void syncNow()
    const onQueue = () => {
      void refresh()
      // A request can fail while navigator.onLine remains true (for example, API downtime).
      // One retry against /api/me/sync is safe because that endpoint is not queued recursively.
      if (navigator.onLine) void syncNow()
    }
    const onOnline = () => { setIsOnline(true); void syncNow() }
    const onOffline = () => { setIsOnline(false); setNotice('Нет подключения. Записи останутся на этом устройстве до восстановления связи.') }
    window.addEventListener('kompas:offline-queue-updated', onQueue)
    window.addEventListener('online', onOnline)
    window.addEventListener('offline', onOffline)
    return () => {
      window.removeEventListener('kompas:offline-queue-updated', onQueue)
      window.removeEventListener('online', onOnline)
      window.removeEventListener('offline', onOffline)
    }
  }, [patientUserId, refresh, syncNow])

  if (!user || user.role !== 'patient' || (!items.length && !notice && !failures.length)) return null
  return <section className={`offline-sync-panel ${isOnline ? '' : 'offline'}`} aria-live="polite">
    <div className="offline-sync-heading"><strong>{isOnline ? 'Синхронизация самоотчётов' : 'Нет подключения к сети'}</strong><span className="badge">В очереди: {items.length}</span></div>
    <p>{notice || (items.length ? 'Записи сохранены локально и будут отправлены после восстановления связи.' : 'Очередь пуста.')}</p>
    {items.length > 0 && <><ul>{items.slice(0, 5).map((item) => <li key={item.key}>{KIND_LABEL[item.kind] ?? item.kind} · {new Date(item.queued_at).toLocaleString()}</li>)}</ul>{items.length > 5 && <p className="muted small">И ещё {items.length - 5} записей.</p>}<button type="button" disabled={loading || !isOnline} onClick={() => void syncNow()}>{loading ? 'Синхронизация…' : 'Синхронизировать сейчас'}</button></>}
    {failures.length > 0 && <details><summary>Записи, которые сервер не принял</summary><ul>{failures.map((f, i) => <li key={`${f.client_id ?? 'failed'}-${i}`}><code>{f.client_id ?? 'без client_id'}</code>: {f.error ?? 'Неизвестная ошибка'} {f.retry ? '(можно повторить)' : '(проверьте запись; повтор может не помочь)'}</li>)}</ul></details>}
    <p className="muted small">Не очищайте данные браузера, пока очередь не синхронизирована. Для реальной эксплуатации устройство должно иметь пароль и полнодисковое шифрование.</p>
  </section>
}
