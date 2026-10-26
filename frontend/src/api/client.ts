import { enqueueOfflineMutation } from './offlineQueue'
const TOKEN_KEY = 'kompas.token'

export interface FieldError {
  field?: string
  path?: string
  message: string
}

export class ApiError extends Error {
  status: number
  requestId: string | null
  errors: FieldError[]

  constructor(status: number, message: string, requestId: string | null, errors: FieldError[] = []) {
    super(message)
    this.status = status
    this.requestId = requestId
    this.errors = errors
  }
}

export function getToken(): string | null {
  try {
    return sessionStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

export function setToken(token: string | null): void {
  try {
    if (token) sessionStorage.setItem(TOKEN_KEY, token)
    else sessionStorage.removeItem(TOKEN_KEY)
  } catch {
    // sessionStorage недоступен — сессия живёт до перезагрузки страницы
  }
}

let onUnauthorized: () => void = () => {}

export function setUnauthorizedHandler(fn: () => void): void {
  onUnauthorized = fn
}

export async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  if (body !== undefined) headers['Content-Type'] = 'application/json'

  let res: Response
  try {
    res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) })
  } catch {
    if (method.toUpperCase() === 'POST') {
      const queued = await enqueueOfflineMutation(path, body)
      if (queued) return queued as T
    }
    throw new ApiError(0, 'Нет связи с сервером. Проверьте подключение.', null)
  }

  const requestId = res.headers.get('X-Request-ID')
  const isJson = (res.headers.get('Content-Type') ?? '').includes('json')
  const data = isJson ? await res.json().catch(() => null) : null

  if (!res.ok) {
    if (res.status === 401 && token) onUnauthorized()
    const message = data?.detail ?? data?.title ?? `Ошибка ${res.status}`
    throw new ApiError(res.status, message, data?.request_id ?? requestId, data?.errors ?? [])
  }
  return data as T
}

export const api = {
  get: <T>(path: string) => request<T>('GET', path),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, body ?? {}),
  put: <T>(path: string, body?: unknown) => request<T>('PUT', path, body ?? {}),
  patch: <T>(path: string, body?: unknown) => request<T>('PATCH', path, body ?? {}),
  delete: <T>(path: string) => request<T>('DELETE', path),
}
