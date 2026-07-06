/* sw.js — 數據獵手 PWA service worker
   app shell 快取供離線開殼；資料(state/api/stream)一律 network-first(拿最新)，離線退快取。 */
const CACHE = 'dh-shell-v1';
const SHELL = ['/', '/dashboard.html', '/three.module.min.js', '/manifest.json', '/icon-192.png', '/icon-512.png'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL).catch(() => {})).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET') return;                       // 只快取 GET
  // 即時資料：network-first（永遠先拿最新，離線才退快取）
  if (url.pathname.startsWith('/api/') || url.pathname.endsWith('.json')) {
    e.respondWith(fetch(e.request).catch(() => caches.match(e.request)));
    return;
  }
  // app shell：cache-first（離線也開得了殼），背景更新
  e.respondWith(
    caches.match(e.request).then(cached => {
      const net = fetch(e.request).then(r => {
        if (r && r.ok) { const cp = r.clone(); caches.open(CACHE).then(c => c.put(e.request, cp)); }
        return r;
      }).catch(() => cached);
      return cached || net;
    })
  );
});
