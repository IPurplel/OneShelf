// OneShelf's service worker does one small thing: when the app is opened and the computer it lives on cannot
// be reached (away from home Wi-Fi, switched off), it shows a short page that says so instead of the
// browser's error.
//
// It never stores the interface, the library, covers or books, and answers no other request. Everything is
// fetched fresh from your own computer, so an update is never hidden behind an old copy.
const CACHE = "oneshelf-offline-v1";
const OFFLINE = "/offline.html";

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.add(OFFLINE)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((names) => Promise.all(names.filter((name) => name !== CACHE).map((name) => caches.delete(name))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  // Only opening a page. Every other request goes straight to the network, untouched.
  if (request.mode !== "navigate" || request.method !== "GET") return;
  event.respondWith(fetch(request).catch(() => caches.match(OFFLINE)));
});
