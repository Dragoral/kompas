/* Offline app-shell cache only. Deliberately never cache /api or authenticated responses. */
const CACHE_PREFIX = 'kompas-app-shell-';
const CACHE_NAME = `${CACHE_PREFIX}v1`;
const SHELL_URLS = ['/', '/index.html', '/manifest.webmanifest', '/kompas-icon.svg'];
self.addEventListener('install', (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE_NAME);
    await Promise.all(SHELL_URLS.map(async (url) => {
      try { const response = await fetch(url, { cache: 'reload' }); if (response.ok) await cache.put(url, response); }
      catch { /* offline first install may be incomplete; the current page still works */ }
    }));
    await self.skipWaiting();
  })());
});
self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(names.filter((name) => name.startsWith(CACHE_PREFIX) && name !== CACHE_NAME).map((name) => caches.delete(name)));
    await self.clients.claim();
  })());
});
self.addEventListener('fetch', (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== 'GET' || url.origin !== self.location.origin || url.pathname.startsWith('/api/')) return;
  if (request.mode === 'navigate') {
    event.respondWith((async () => {
      try {
        const response = await fetch(request);
        if (response.ok) { const cache = await caches.open(CACHE_NAME); await cache.put('/index.html', response.clone()); }
        return response;
      } catch {
        return (await caches.match('/index.html')) || (await caches.match('/')) || Response.error();
      }
    })());
    return;
  }
  if (/\.(?:js|css|svg|png|webp|woff2?)$/i.test(url.pathname) || url.pathname === '/manifest.webmanifest') {
    // Network-first refreshes versioned assets when online, falling back to the last
    // successful same-origin static asset when offline. Never intercept /api here.
    event.respondWith((async () => {
      const cache = await caches.open(CACHE_NAME);
      try {
        const response = await fetch(request);
        if (response.ok && response.type === 'basic') await cache.put(request, response.clone());
        return response;
      } catch {
        return (await cache.match(request)) || Response.error();
      }
    })());
  }
});

/* Web Push: show the notification and open the related page on click. Payload carries no medical details. */
self.addEventListener('push', (event) => {
  let data = { title: 'Компас', body: 'Откройте приложение', url: '/', tag: 'kompas' };
  try { if (event.data) data = { ...data, ...event.data.json() }; } catch { /* keep defaults */ }
  event.waitUntil(self.registration.showNotification(data.title, {
    body: data.body,
    tag: data.tag,
    icon: '/kompas-icon.svg',
    badge: '/kompas-icon.svg',
    data: { url: data.url },
    requireInteraction: data.urgency === 'high',
  }));
});
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const target = new URL(event.notification.data?.url || '/', self.location.origin).href;
  event.waitUntil((async () => {
    const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    const same = windows.find((w) => w.url === target) || windows.find((w) => new URL(w.url).origin === self.location.origin);
    if (same) { await same.focus(); if (same.url !== target && 'navigate' in same) await same.navigate(target); return; }
    await self.clients.openWindow(target);
  })());
});
