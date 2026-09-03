// The dashboard's service worker (MOBILE_PLAN.md 4 M4, 2026-08-30).
// version: __VERSION__
//
// Served by ui.py at /sw.js, not from /static/, because a worker may only
// claim a scope at or below its own path and this one wants "/". That route
// substitutes __VERSION__ above and in CACHE below with the dashboard's
// VERSION, so a release changes these bytes and every installed phone picks
// the new worker up (a byte-identical sw.js is never re-installed).
//
// The one rule that matters here: THIS WORKER NEVER CACHES ANYTHING THAT
// DEPENDS ON WHO IS ASKING. A cached page served to a signed-out phone, or a
// cached /partials/ fragment served after a fleet halt, would be the dashboard
// lying about whether footage is syncing -- which outranks every offline
// nicety. So: pages are network-first (the offline page only when the network
// genuinely fails), /static/ is cache-first (it is versioned by release and
// carries no session), and everything under PASS_THROUGH is handed to the
// network untouched, with no respondWith at all.
const VERSION = '__VERSION__';
const CACHE = 'ccsync-' + VERSION;

// Enough to paint the offline page and a first screen of chrome. Nothing
// here is session-specific: /offline renders the same for everyone.
const PRECACHE = [
  '/offline',
  '/static/style.css',
  '/static/mobile.css',
  '/static/htmx.min.js',
  '/static/pwa.js',
  // DUI-2 (2026-09-04): the "this page has stopped updating" banner is the
  // one script a phone on a bad connection needs most, so it is precached
  // beside htmx rather than fetched at the moment the network is failing.
  '/static/htmx_errors.js',
  '/static/icons/icon.svg',
  '/static/icons/icon-180.png',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/static/icons/icon-192-maskable.png',
  '/static/icons/icon-512-maskable.png'
];

// Prefixes this worker keeps its hands off entirely: live data, the htmx
// fragments that carry it, the three mounted SPAs and Timeline Cards (which
// has its own manifest and its own worker scope), and the two ends of a
// session. Not "cached carefully" -- not touched.
const PASS_THROUGH = [
  '/api/',
  '/partials/',
  '/cards/',
  '/broll/',
  '/music/',
  '/ytdl/',
  '/login',
  '/logout',
  '/.well-known/'
];

const OFFLINE_URL = '/offline';

function passThrough(pathname) {
  for (var i = 0; i < PASS_THROUGH.length; i++) {
    if (pathname === PASS_THROUGH[i] || pathname.indexOf(PASS_THROUGH[i]) === 0) return true;
  }
  return false;
}

self.addEventListener('install', function (event) {
  event.waitUntil(
    caches.open(CACHE).then(function (cache) {
      // Per file, not cache.addAll: addAll rejects as a whole, so one asset
      // a build dropped (mobile.css before it merged, say) would leave the
      // worker with NO precache at all rather than one file short.
      return Promise.all(PRECACHE.map(function (url) {
        return cache.add(new Request(url, { cache: 'reload' })).catch(function () { });
      }));
    }).then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener('activate', function (event) {
  event.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(keys.map(function (key) {
        if (key !== CACHE && key.indexOf('ccsync-') === 0) return caches.delete(key);
        return null;
      }));
    }).then(function () { return self.clients.claim(); })
  );
});

self.addEventListener('fetch', function (event) {
  var req = event.request;
  if (req.method !== 'GET') return;
  var url;
  try { url = new URL(req.url); } catch (e) { return; }
  if (url.origin !== self.location.origin) return;
  if (passThrough(url.pathname)) return;

  // Navigations: always ask the network first, so a 303 to /login, a fleet
  // halt banner and a stale project all come from the server. The cache is
  // reached only when the fetch itself fails.
  if (req.mode === 'navigate') {
    event.respondWith(
      fetch(req).catch(function () {
        return caches.match(OFFLINE_URL).then(function (hit) {
          return hit || new Response('offline', {
            status: 503,
            headers: { 'Content-Type': 'text/plain' }
          });
        });
      })
    );
    return;
  }

  // Static assets: cache first, and fill the cache on the way past. They are
  // replaced by a release, which changes VERSION, which drops the old cache.
  if (url.pathname.indexOf('/static/') === 0) {
    event.respondWith(
      caches.match(req).then(function (hit) {
        if (hit) return hit;
        return fetch(req).then(function (res) {
          if (res && res.ok && res.type === 'basic') {
            var copy = res.clone();
            caches.open(CACHE).then(function (cache) { cache.put(req, copy); });
          }
          return res;
        });
      })
    );
    return;
  }

  // Everything else (the manifest, the favicon, /sw.js itself): the network,
  // uncached.
});
