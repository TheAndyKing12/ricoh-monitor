const CACHE_NAME = 'ricoh-monitor-v1';
const STATIC_ASSETS = [
    '/frontend/dashboard.html',
    '/frontend/style.css',
    '/frontend/bootstrap-icons.min.css',
    '/frontend/inter.css'
];

// Instalación — cachear assets estáticos
self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(CACHE_NAME).then(cache => cache.addAll(STATIC_ASSETS))
    );
    self.skipWaiting();
});

// Activación — limpiar caches viejos
self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys().then(keys =>
            Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
        )
    );
    self.clients.claim();
});

// Fetch — Network first, cache fallback (solo GET, nunca APIs)
self.addEventListener('fetch', event => {
    const url = new URL(event.request.url);

    // No interceptar llamadas a la API del backend
    if (url.pathname.startsWith('/printers') ||
        url.pathname.startsWith('/inventory') ||
        url.pathname.startsWith('/toner-control') ||
        url.pathname.startsWith('/counters')) {
        return;
    }

    if (event.request.method !== 'GET') return;

    event.respondWith(
        fetch(event.request)
            .then(response => {
                const clone = response.clone();
                caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
                return response;
            })
            .catch(() => caches.match(event.request))
    );
});