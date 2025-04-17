// Cache name
const CACHE_NAME = 'my-django-pwa-v1';
const urlsToCache = [
    '/',
    '/static/css/uistyle.css', 
    '/static/css/group_chat.css', // Add your CSS files
    '/static/js/main.js',     // Add your JS files
      
    '/offline/',              // Add an offline page URL
];

// Install event - cache assets
self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then(cache => {
                console.log('Opened cache');
                return cache.addAll(urlsToCache);
            })
    );
});

// Fetch event - serve cached content when offline
self.addEventListener('fetch', event => {
    event.respondWith(
        caches.match(event.request)
            .then(response => {
                // Return cached response if found, otherwise fetch from network
                return response || fetch(event.request);
            })
            .catch(() => {
                // If both cache and network fail, show offline page
                return caches.match('/offline/');
            })
    );
});

// Activate event - clean up old caches
self.addEventListener('activate', event => {
    const cacheWhitelist = [CACHE_NAME];
    event.waitUntil(
        caches.keys().then(cacheNames => {
            return Promise.all(
                cacheNames.map(cacheName => {
                    if (!cacheWhitelist.includes(cacheName)) {
                        return caches.delete(cacheName);
                    }
                })
            );
        })
    );
});