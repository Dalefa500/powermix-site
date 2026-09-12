/* Кэш оболочки приложения: интерфейс открывается мгновенно, а цифры
   всегда берутся из сети — финансовые данные не кэшируются никогда. */

const CACHE = "profix-shell-v9";
const SHELL = [
  "/",
  "/styles.css?v=9",
  "/app.js?v=9",
  "/manifest.json",
  "/icons/icon-192.png",
  "/icons/logo.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/")) return;

  // Свежая оболочка, если сеть есть; из кэша — если нет.
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        const copy = response.clone();
        caches.open(CACHE).then((cache) => cache.put(event.request, copy));
        return response;
      })
      .catch(() => caches.match(event.request).then((hit) => hit || caches.match("/"))),
  );
});
