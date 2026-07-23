// v18 — no-cache service worker
self.addEventListener('install', e => { self.skipWaiting(); });
self.addEventListener('activate', e => { e.waitUntil(
  caches.keys().then(keys => Promise.all(keys.map(k => caches.delete(k))))
  .then(() => clients.claim())
); });
self.addEventListener('fetch', e => {
  // Only cache static assets, never API or auth routes
  const url = new URL(e.request.url);
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/auth/')) {
    return e.respondWith(fetch(e.request));
  }
  // Network-first for everything else
  e.respondWith(
    fetch(e.request).then(r => r).catch(() => caches.match(e.request))
  );
});
