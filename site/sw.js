// MadisonPulse offline support: the page itself opens from cache; event data is always
// fetched fresh when there's a connection and falls back to the last copy offline.
const SHELL = "mp-shell-v1";
const FILES = ["./", "index.html", "app.js", "spots.js", "manifest.webmanifest", "icons/icon-192.png"];
self.addEventListener("install", e => e.waitUntil(caches.open(SHELL).then(c => c.addAll(FILES)).then(() => self.skipWaiting())));
self.addEventListener("activate", e => e.waitUntil(
  caches.keys().then(keys => Promise.all(keys.filter(k => k !== SHELL && k !== "mp-data").map(k => caches.delete(k)))).then(() => self.clients.claim())));
self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;
  if (url.pathname.includes("/data/")){  // network first, then last saved copy
    e.respondWith(fetch(e.request).then(r => { const copy = r.clone(); caches.open("mp-data").then(c => c.put(e.request, copy)); return r; })
      .catch(() => caches.match(e.request)));
    return;
  }
  // page files: fresh when online (so updates show right away), cached copy offline
  e.respondWith(fetch(e.request).then(r => { const copy = r.clone(); caches.open(SHELL).then(c => c.put(e.request, copy)); return r; })
    .catch(() => caches.match(e.request).then(m => m || caches.match("./"))));
});
