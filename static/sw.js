// v32 — offline-first static shell caching
const CACHE_NAME = 'listmate-static-v32';
const PRECACHE_ASSETS = [
  '/static/index.html',
  '/static/settings.html',
  '/static/confetti.browser.min.js',
  '/manifest.json',
  '/icon-192.png',
  '/icon-512.png'
];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      return cache.addAll(PRECACHE_ASSETS).catch(err => console.log('Precache warning:', err));
    })
  );
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys => Promise.all(
      keys.map(k => {
        if (k !== CACHE_NAME) return caches.delete(k);
      })
    )).then(() => clients.claim())
  );
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  // Never cache or intercept API or auth routes in Service Worker
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/auth/')) {
    return e.respondWith(fetch(e.request));
  }
  
  // Network-first with Cache fallback and background cache update
  e.respondWith(
    fetch(e.request).then(response => {
      if (response && response.status === 200 && response.type === 'basic') {
        const responseToCache = response.clone();
        caches.open(CACHE_NAME).then(cache => {
          cache.put(e.request, responseToCache);
        });
      }
      return response;
    }).catch(() => {
      return caches.match(e.request).then(cached => {
        if (cached) return cached;
        if (e.request.mode === 'navigate') {
          return caches.match('/static/index.html') || caches.match('/') || caches.match('/index.html');
        }
      });
    })
  );
});
