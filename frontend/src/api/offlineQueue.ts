/**
 * Encrypted, patient-scoped queue for POST /api/me/sync. Only supported patient mutations
 * can be queued; auth/session requests and all clinician/admin requests are never persisted.
 */
export type OfflineKind = 'scale' | 'diary' | 'dose' | 'adverse' | 'message'
export interface OfflineQueueItem {
  key: string
  user_id: number
  kind: OfflineKind
  data: Record<string, unknown>
  queued_at: string
}
interface StoredQueueItem {
  key: string
  user_id: number
  kind: OfflineKind
  queued_at: string
  iv: string
  ciphertext: string
}
interface StoredCryptoKey { id: 'queue-key'; key: CryptoKey }
const DB_NAME = 'kompas-patient-offline-v2'
const QUEUE_STORE = 'queue'
const KEY_STORE = 'keys'
let activePatientId: number | null = null
let dbPromise: Promise<IDBDatabase> | null = null

export function setOfflineQueueUser(userId: number | null): void { activePatientId = userId }

function openDb(): Promise<IDBDatabase> {
  if (dbPromise) return dbPromise
  if (typeof indexedDB === 'undefined') return Promise.reject(new Error('IndexedDB недоступен'))
  
  dbPromise = new Promise<IDBDatabase>((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1)
    request.onupgradeneeded = () => {
      const db = request.result
      if (!db.objectStoreNames.contains(QUEUE_STORE)) db.createObjectStore(QUEUE_STORE, { keyPath: 'key' })
      if (!db.objectStoreNames.contains(KEY_STORE)) db.createObjectStore(KEY_STORE, { keyPath: 'id' })
    }
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error ?? new Error('Не удалось открыть локальную очередь'))
    request.onblocked = () => reject(new Error('Локальная очередь занята другой вкладкой'))
  }).catch((error) => { dbPromise = null; throw error })
  
  return dbPromise
}

function requestValue<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error ?? new Error('Ошибка локального хранилища'))
  })
}

async function cryptoKey(db: IDBDatabase): Promise<CryptoKey> {
  if (!globalThis.crypto?.subtle) throw new Error('Безопасное шифрование браузером не поддерживается')
  const tx = db.transaction(KEY_STORE, 'readonly')
  const saved = await requestValue(tx.objectStore(KEY_STORE).get('queue-key')) as StoredCryptoKey | undefined
  if (saved?.key) return saved.key
  const key = await crypto.subtle.generateKey({ name: 'AES-GCM', length: 256 }, false, ['encrypt', 'decrypt'])
  await new Promise<void>((resolve, reject) => {
    const write = db.transaction(KEY_STORE, 'readwrite')
    write.objectStore(KEY_STORE).put({ id: 'queue-key', key } satisfies StoredCryptoKey)
    write.oncomplete = () => resolve()
    write.onerror = () => reject(write.error ?? new Error('Не удалось сохранить ключ шифрования'))
    write.onabort = () => reject(write.error ?? new Error('Сохранение ключа шифрования отменено'))
  })
  return key
}

function toBase64(bytes: Uint8Array): string {
  let binary = ''
  for (const byte of bytes) binary += String.fromCharCode(byte)
  return btoa(binary)
}
function fromBase64(value: string): Uint8Array {
  const binary = atob(value)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
  return bytes
}

async function encrypt(data: Record<string, unknown>, key: CryptoKey): Promise<{ iv: string; ciphertext: string }> {
  const iv = crypto.getRandomValues(new Uint8Array(12))
  const plain = new TextEncoder().encode(JSON.stringify(data))
  const encrypted = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, plain)
  return { iv: toBase64(iv), ciphertext: toBase64(new Uint8Array(encrypted)) }
}
async function decrypt(item: StoredQueueItem, key: CryptoKey): Promise<OfflineQueueItem> {
  const plain = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: fromBase64(item.iv) }, key, fromBase64(item.ciphertext))
  const data = JSON.parse(new TextDecoder().decode(plain)) as Record<string, unknown>
  return { key: item.key, user_id: item.user_id, kind: item.kind, queued_at: item.queued_at, data }
}

function kindForPath(path: string): OfflineKind | null {
  const pathname = new URL(path, window.location.origin).pathname
  if (pathname === '/api/me/scales') return 'scale'
  if (pathname === '/api/me/diary') return 'diary'
  if (pathname === '/api/me/doses') return 'dose'
  if (pathname === '/api/me/adverse-events') return 'adverse'
  if (pathname === '/api/me/messages') return 'message'
  return null
}

export async function enqueueOfflineMutation(path: string, body: unknown): Promise<{ queued_offline: true; client_id: string } | null> {
  if (activePatientId === null || typeof window === 'undefined' || !body || typeof body !== 'object' || Array.isArray(body)) return null
  const kind = kindForPath(path)
  if (!kind) return null
  try {
    const data = { ...(body as Record<string, unknown>) }
    const clientId = typeof data.client_id === 'string' && data.client_id ? data.client_id : crypto.randomUUID()
    data.client_id = clientId
    const db = await openDb()
    const key = await cryptoKey(db)
    const sealed = await encrypt(data, key)
    const item: StoredQueueItem = { key: `${activePatientId}:${clientId}`, user_id: activePatientId, kind, queued_at: new Date().toISOString(), ...sealed }
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(QUEUE_STORE, 'readwrite')
      tx.objectStore(QUEUE_STORE).put(item)
      tx.oncomplete = () => resolve()
      tx.onerror = () => reject(tx.error ?? new Error('Не удалось сохранить офлайн-запись'))
      tx.onabort = () => reject(tx.error ?? new Error('Сохранение офлайн-записи отменено'))
    })
    window.dispatchEvent(new CustomEvent('kompas:offline-queue-updated'))
    return { queued_offline: true, client_id: clientId }
  } catch {
    // Fail closed: do not persist patient information unencrypted if WebCrypto is unavailable.
    return null
  }
}

export async function listOfflineQueue(userId: number): Promise<OfflineQueueItem[]> {
  const db = await openDb()
  const all = await requestValue(db.transaction(QUEUE_STORE, 'readonly').objectStore(QUEUE_STORE).getAll()) as StoredQueueItem[]
  const selected = all.filter((item) => item.user_id === userId).sort((a, b) => a.queued_at.localeCompare(b.queued_at))
  if (!selected.length) return []
  const key = await cryptoKey(db)
  const result: OfflineQueueItem[] = []
  // Don't lose the rest of the queue if a single stored entry cannot be decrypted.
  for (const item of selected) {
    try { result.push(await decrypt(item, key)) } catch { /* surface a generic storage warning from the component */ }
  }
  if (result.length !== selected.length) throw new Error('Часть локальных записей не удалось расшифровать; очередь сохранена без изменений')
  return result
}

export async function removeOfflineQueue(keys: string[]): Promise<void> {
  if (!keys.length) return
  const db = await openDb()
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction(QUEUE_STORE, 'readwrite')
    const store = tx.objectStore(QUEUE_STORE)
    keys.forEach((key) => store.delete(key))
    tx.oncomplete = () => resolve()
    tx.onerror = () => reject(tx.error ?? new Error('Не удалось очистить синхронизированные записи'))
    tx.onabort = () => reject(tx.error ?? new Error('Очистка очереди отменена'))
  })
}