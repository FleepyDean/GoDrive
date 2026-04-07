const CACHE_NAME = 'godrive-v2';
const ASSETS = ['/', '/index.html', '/history.html', '/record.html', '/style.css', '/app.js', '/manifest.json'];

self.addEventListener('install', e => {
    e.waitUntil(
        caches.open(CACHE_NAME).then(cache => cache.addAll(ASSETS))
    );
});

self.addEventListener('fetch', e => {
    if (e.request.url.includes('/api/')) {
        // Network first for API
        e.respondWith(
            fetch(e.request).catch(() => caches.match(e.request))
        );
    } else {
        // Cache first for assets
        e.respondWith(
            caches.match(e.request).then(r => r || fetch(e.request))
        );
    }
});
