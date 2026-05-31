/* MOOD · service worker
   Стратегия:
   - Статика (CSS/JS/иконки/manifest) — cache-first
   - /api/* — network-only (всегда свежее, без offline-кеша)
   - index.html — network-first c fallback на cache (для offline shell)
*/
const CACHE = "mood-v16";
// app.js/style.css НЕ прекэшируем — они версионируются (?v=) и идут network-first.
const STATIC = [
  "/manifest.json",
  "/icon.svg",
  "/icon-192.png",
  "/icon-512.png",
  "/apple-touch-icon.png",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(STATIC)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)));
      await self.clients.claim();
    })()
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET") return;

  // API — всегда сеть, без кеша
  if (url.pathname.startsWith("/api/")) return;

  const p = url.pathname;
  // Код и разметка (html/js/css) — network-first: всегда свежее, кэш только для offline.
  const isCode = p === "/" || p.endsWith(".html") || p.endsWith(".js") || p.endsWith(".css");
  if (isCode) {
    e.respondWith(
      fetch(e.request)
        .then((r) => {
          const copy = r.clone();
          caches.open(CACHE).then((c) => c.put(e.request, copy));
          return r;
        })
        .catch(() => caches.match(e.request).then((c) => c || caches.match("/index.html")))
    );
    return;
  }

  // Иконки/manifest/прочее — cache-first (не меняется)
  e.respondWith(
    caches.match(e.request).then((cached) => {
      if (cached) return cached;
      return fetch(e.request).then((r) => {
        if (r.ok && r.type === "basic") {
          const copy = r.clone();
          caches.open(CACHE).then((c) => c.put(e.request, copy));
        }
        return r;
      });
    })
  );
});
