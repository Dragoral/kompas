import { api } from './client'

/** Web Push в этом браузере: поддержка, текущая подписка, включение и отключение. */

export type PushState = 'unsupported' | 'ios-install' | 'denied' | 'off' | 'on'

const isIos = () => /iphone|ipad|ipod/i.test(navigator.userAgent)
const isStandalone = () => window.matchMedia('(display-mode: standalone)').matches
  || (navigator as Navigator & { standalone?: boolean }).standalone === true

function keyBytes(b64url: string): Uint8Array {
  const b64 = (b64url + '='.repeat((4 - (b64url.length % 4)) % 4)).replace(/-/g, '+').replace(/_/g, '/')
  return Uint8Array.from(atob(b64), (c) => c.charCodeAt(0))
}

async function registration(): Promise<ServiceWorkerRegistration> {
  return (await navigator.serviceWorker.getRegistration('/')) ?? navigator.serviceWorker.register('/sw.js')
}

export async function pushState(): Promise<PushState> {
  if (!('serviceWorker' in navigator) || !('PushManager' in window) || !('Notification' in window)) {
    // На iPhone push доступен только приложению, добавленному на экран «Домой» (iOS 16.4+)
    return isIos() && !isStandalone() ? 'ios-install' : 'unsupported'
  }
  if (Notification.permission === 'denied') return 'denied'
  const reg = await navigator.serviceWorker.getRegistration('/')
  const sub = reg ? await reg.pushManager.getSubscription() : null
  return sub ? 'on' : 'off'
}

export async function enablePush(): Promise<void> {
  if (await Notification.requestPermission() !== 'granted') throw new Error('Уведомления запрещены в настройках браузера')
  const { public_key } = await api.get<{ public_key: string }>('/api/push/key')
  const reg = await registration()
  await navigator.serviceWorker.ready
  const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(public_key) })
  await api.post('/api/push/subscriptions', sub.toJSON())
}

export async function disablePush(): Promise<void> {
  const reg = await navigator.serviceWorker.getRegistration('/')
  const sub = reg ? await reg.pushManager.getSubscription() : null
  if (!sub) return
  await api.delete(`/api/push/subscriptions?endpoint=${encodeURIComponent(sub.endpoint)}`).catch(() => undefined)
  await sub.unsubscribe()
}
