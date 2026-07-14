/* GymLog service worker — cache-first，離線可用 */
const VER = 'gymlog-v7'; // 每次改動任何檔案都要升版，否則已安裝的 PWA 拿不到更新
const ASSETS = ['./', './index.html', './manifest.json', './icon.png', './icon-180.png',
  './firebase-app-compat.js', './firebase-firestore-compat.js', './firebase-config.js'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(VER).then(c => c.addAll(ASSETS)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys => Promise.all(keys.filter(k => k !== VER).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  if (new URL(e.request.url).origin !== self.location.origin) return; // 跨網域(如 Firestore)一律走網路，不快取

  e.respondWith(
    caches.match(e.request, { ignoreSearch: true }).then(hit =>
      hit || fetch(e.request).then(res => {
        const copy = res.clone();
        caches.open(VER).then(c => c.put(e.request, copy));
        return res;
      }).catch(() => caches.match('./index.html'))
    )
  );
});
