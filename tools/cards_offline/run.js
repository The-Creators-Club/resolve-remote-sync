// The installed Timeline Cards app, cold-launched with no network, in a real
// headless Chrome (Cards offline front door, 2026-10-14).
//
//   node tools/cards_offline/run.js --python <the dashboard venv's python> \
//        --page-src <Timeline Cards checkout>/multicam_pipeline/cards \
//        [--shots <dir for screenshots>]
//
// WHAT IT PROVES (each is a check; exit 1 if any fails):
//   first    a fresh phone opens /cards/ online ONCE: the worker registers at
//            scope /cards/ and the page and its assets are saved, whichever of
//            "page loaded" and "worker claimed it" happens first
//   hole     the app relaunched (a new browser process, so the worker is not
//            running) while the server is a BLACK HOLE (the proxy accepts and
//            never answers: Tailscale up, no network behind it): the offline
//            picker draws inside the worker's 8 s deadline
//   hard     the same with the connection refused / CDP offline: drawn at once
//   start    the start_url as Android sends it, with and without a query
//   upgrade  a phone still holding an older worker at the same URL: ONE online
//            visit after the dashboard updates is enough
//   episode  an episode with a downloaded copy is opened from the offline
//            picker and its own worker answers (the engine behind it is a
//            stub, so nothing here says what a downloaded cut list CONTAINS)
//
// No npm dependencies (the rule tools/mobile_sweep.js follows): node 24 has
// fetch and WebSocket, Chrome is driven over the DevTools protocol directly.
// A service worker needs a secure context, so this uses http://localhost.
// The profile lives under the OS temp dir on purpose: CacheStorage fails with
// "Unexpected internal error" under a long profile path on Windows.
const { spawn } = require('child_process');
const http = require('http'), os = require('os'), path = require('path'), fs = require('fs');

function arg(n, d) { const i = process.argv.indexOf('--' + n); return i >= 0 ? process.argv[i + 1] : d; }
const PORT = +arg('port', 8491), PROXY = +arg('proxy', 8492), DBG = +arg('debug-port', 9333);
const CHROME = arg('chrome', 'C:/Program Files/Google/Chrome/Application/chrome.exe');
const PYTHON = arg('python', 'python');
const PAGE_SRC = arg('page-src', process.env.CARDS_PAGE_SRC || '');
const WORK = path.resolve(arg('work', path.join(os.tmpdir(), 'cards_offline_run')));
const SHOTS = arg('shots', '');
const ORIGIN = 'http://localhost:' + PORT;
const sleep = ms => new Promise(r => setTimeout(r, ms));
const fails = [];
function check(ok, what, extra) {
  console.log((ok ? 'PASS ' : 'FAIL ') + what + (extra ? '  [' + extra + ']' : ''));
  if (!ok) fails.push(what);
}

// ---------------------------------------------------------------- the proxy
// pass: forward; hang: accept and never answer (a black hole); refuse: drop.
let mode = 'pass', staleWorker = '';
const held = new Set();
const proxy = http.createServer((q, r) => {
  if (mode === 'hang') { held.add(q.socket); return; }
  if (mode === 'refuse') { q.socket.destroy(); return; }
  const u = new URL(q.url);
  if (staleWorker && u.pathname === '/cards/sw.js') {
    const b = fs.readFileSync(staleWorker);
    r.writeHead(200, {'content-type': 'text/javascript', 'cache-control': 'no-cache', 'content-length': b.length});
    return r.end(b);
  }
  const o = http.request({host: u.hostname, port: u.port, path: u.pathname + u.search, method: q.method, headers: q.headers},
    rr => { r.writeHead(rr.statusCode, rr.headers); rr.pipe(r); });
  o.on('error', () => r.destroy());
  q.pipe(o);
});
proxy.on('connect', (q, s) => { if (mode === 'hang') held.add(s); else s.destroy(); });
function setMode(m) { mode = m; if (m !== 'hang') { for (const s of held) s.destroy(); held.clear(); } }

// ------------------------------------------------------------------ chrome
class Conn {
  constructor(url) {
    this.id = 0; this.cb = new Map(); this.ws = new WebSocket(url);
    this.ready = new Promise(r => this.ws.addEventListener('open', r));
    this.ws.addEventListener('message', m => {
      const d = JSON.parse(m.data);
      if (d.id && this.cb.has(d.id)) {
        const c = this.cb.get(d.id); this.cb.delete(d.id);
        d.error ? c.rej(new Error(JSON.stringify(d.error))) : c.res(d.result);
      }
    });
  }
  send(method, params = {}, sessionId) {
    return new Promise((res, rej) => {
      const id = ++this.id; this.cb.set(id, {res, rej});
      this.ws.send(JSON.stringify({id, method, params, sessionId}));
    });
  }
}
async function browser(profile) {
  const proc = spawn(CHROME, ['--headless=new', '--remote-debugging-port=' + DBG, '--user-data-dir=' + profile, '--no-first-run',
    '--no-default-browser-check', '--disable-background-networking', '--proxy-server=127.0.0.1:' + PROXY,
    '--proxy-bypass-list=<-loopback>', 'about:blank'], {stdio: 'ignore'});
  for (let i = 0; i < 100; i++) {
    try {
      const j = await (await fetch(`http://127.0.0.1:${DBG}/json/version`)).json();
      const c = new Conn(j.webSocketDebuggerUrl); await c.ready;
      return {c, close: async () => {
        try { await c.send('Browser.close'); } catch (e) { /* gone */ }
        await sleep(700); try { proc.kill(); } catch (e) { /* gone */ } await sleep(300);
      }};
    } catch (e) { await sleep(150); }
  }
  throw new Error('chrome did not start');
}
// a cold launch: a new tab, navigate, wait for first paint and load
async function launch(b, url, {offlineEmu = false, timeout = 40000, shot} = {}) {
  const {targetId} = await b.c.send('Target.createTarget', {url: 'about:blank'});
  const {sessionId} = await b.c.send('Target.attachToTarget', {targetId, flatten: true});
  const s = (m, p) => b.c.send(m, p, sessionId);
  await s('Page.enable'); await s('Runtime.enable'); await s('Network.enable');
  await s('Page.setLifecycleEventsEnabled', {enabled: true});
  await s('Emulation.setDeviceMetricsOverride', {width: 412, height: 915, deviceScaleFactor: 2, mobile: true});
  if (offlineEmu) await s('Network.emulateNetworkConditions', {offline: true, latency: 0, downloadThroughput: -1, uploadThroughput: -1});
  const life = {}; let t0 = 0;
  b.c.ws.addEventListener('message', m => {
    const d = JSON.parse(m.data);
    if (d.sessionId === sessionId && d.method === 'Page.lifecycleEvent' && t0 && !(d.params.name in life)) life[d.params.name] = Date.now() - t0;
  });
  t0 = Date.now();
  await s('Page.navigate', {url});
  while (Date.now() - t0 < timeout && !(('firstContentfulPaint' in life) && ('load' in life))) await sleep(100);
  const page = {ev: async expr => {
    const r = await s('Runtime.evaluate', {expression: expr, awaitPromise: true, returnByValue: true});
    if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails).slice(0, 300));
    return r.result.value;
  }};
  if (shot && SHOTS) {
    const x = await s('Page.captureScreenshot', {format: 'png'});
    fs.writeFileSync(path.join(SHOTS, shot), Buffer.from(x.data, 'base64'));
  }
  return {fcp: life.firstContentfulPaint ?? null, load: life.load ?? null, page};
}
const swState = p => p.ev(`(async()=>{const regs=await navigator.serviceWorker.getRegistrations();
  const o={regs:regs.map(r=>({scope:r.scope,active:r.active&&r.active.scriptURL})),caches:{}};
  for(const n of await caches.keys()){const c=await caches.open(n);o.caches[n]=(await c.keys()).map(r=>r.url.replace(location.origin,''));}
  return o;})()`);

async function main() {
  fs.mkdirSync(WORK, {recursive: true});
  if (SHOTS) fs.mkdirSync(SHOTS, {recursive: true});
  await new Promise(r => proxy.listen(PROXY, '127.0.0.1', r));
  const srv = spawn(PYTHON, [path.join(__dirname, 'serve.py'), '--port', String(PORT), '--work', path.join(WORK, 'srv'), '--page-src', PAGE_SRC],
    {stdio: ['ignore', 'ignore', fs.openSync(path.join(WORK, 'serve.log'), 'w')]});
  try {
    for (let i = 0; ; i++) {
      try { if ((await fetch(ORIGIN + '/cards/icon.svg')).ok) break; } catch (e) { /* not yet */ }
      if (i >= 60) throw new Error('dashboard did not start, see ' + WORK + '/serve.log');
      await sleep(500);
    }
    const cookie = fs.readFileSync(path.join(WORK, 'srv', 'cookie.txt'), 'utf8');
    const cname = fs.readFileSync(path.join(WORK, 'srv', 'cookie_name.txt'), 'utf8');
    const fresh = async name => {
      const p = path.join(WORK, 'prof-' + name);
      fs.rmSync(p, {recursive: true, force: true});
      const b = await browser(p);
      await b.c.send('Storage.setCookies', {cookies: [{name: cname, value: cookie, domain: 'localhost', path: '/',
        expires: Date.now() / 1000 + 86400, httpOnly: true}]});
      return {p, b};
    };
    const offlineMeta = pg => pg.ev(`!!document.querySelector('meta[name=cards-offline]')`).catch(() => false);
    const rows = pg => pg.ev(`document.querySelectorAll('.cl-ep').length`).catch(() => 0);

    // ---- first visit, then the relaunches
    setMode('pass');
    let {p, b} = await fresh('main');
    let r = await launch(b, ORIGIN + '/cards/'); await sleep(2500);
    let st = await swState(r.page);
    check(st.regs.some(x => x.scope === ORIGIN + '/cards/' && /\/cards\/sw\.js$/.test(x.active || '')), 'first: worker registered at scope /cards/');
    const saved = st.caches['cards-landing'] || [];
    check(saved.includes('/cards/'), 'first: the landing page is saved on the very first visit');
    check(saved.some(u => /\.css/.test(u)) && saved.some(u => /\.js/.test(u)), 'first: its css and js are saved', saved.length + ' entries');
    await b.close();

    setMode('hang'); b = await browser(p);
    r = await launch(b, ORIGIN + '/cards/', {shot: 'hole.png'});
    check(await offlineMeta(r.page), 'hole: the saved picker is served when the server is a black hole');
    check(r.fcp !== null && r.fcp < 10000, 'hole: first paint inside the 8 s deadline', 'fcp ' + r.fcp + ' ms');
    check(await rows(r.page) > 0, 'hole: the episode list is on screen');
    await b.close();

    setMode('refuse'); b = await browser(p);
    r = await launch(b, ORIGIN + '/cards/', {shot: 'refused.png'});
    check(await offlineMeta(r.page) && r.fcp !== null && r.fcp < 2000, 'hard: a refused connection draws at once', 'fcp ' + r.fcp + ' ms');
    r = await launch(b, ORIGIN + '/cards/', {offlineEmu: true});
    check(await offlineMeta(r.page) && r.fcp !== null && r.fcp < 2000, 'hard: CDP offline (navigator.onLine false) draws at once', 'fcp ' + r.fcp + ' ms');
    for (const q of ['?source=pwa', '?utm_source=x&a=1']) {
      r = await launch(b, ORIGIN + '/cards/' + q);
      check(await offlineMeta(r.page) && r.fcp !== null && r.fcp < 2000, 'start: /cards/' + q + ' finds the saved page', 'fcp ' + r.fcp + ' ms');
    }
    await b.close();

    // ---- an older worker at the same URL, one online visit after the update
    setMode('pass'); staleWorker = path.join(__dirname, 'stale_worker.js');
    ({p, b} = await fresh('upgrade'));
    r = await launch(b, ORIGIN + '/cards/'); await sleep(2500);
    st = await swState(r.page);
    check(!(st.caches['cards-landing'] || []).includes('/cards/'), 'upgrade: (setup) the stale worker saved nothing');
    await b.close(); staleWorker = '';
    b = await browser(p); r = await launch(b, ORIGIN + '/cards/'); await sleep(3500);
    st = await swState(r.page);
    check((st.caches['cards-landing'] || []).includes('/cards/'), 'upgrade: ONE online visit after the update saves the page');
    await b.close();
    setMode('hang'); b = await browser(p);
    r = await launch(b, ORIGIN + '/cards/');
    check(await offlineMeta(r.page), 'upgrade: and the next black-hole launch is the offline picker');
    await b.close();

    // ---- an episode with a downloaded copy
    setMode('pass'); ({p, b} = await fresh('episode'));
    r = await launch(b, ORIGIN + '/cards/'); await sleep(2000);
    const eps = JSON.parse(await r.page.ev(`JSON.stringify([...document.querySelectorAll('.cl-ep[data-slug]')].map(e=>({slug:e.dataset.slug,root:e.dataset.root})))`));
    const ep = eps.find(e => /Civil/.test(e.root)) || eps[0];
    await r.page.ev(`fetch('/cards/open',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'slug=${ep.slug}',credentials:'same-origin',redirect:'manual'}).then(x=>x.status)`);
    for (let i = 0; i < 40; i++) {
      if (await r.page.ev(`fetch('/cards/state.json').then(x=>x.json()).then(j=>j.episodes.find(e=>e.slug==='${ep.slug}').state)`) === 'ready') break;
      await sleep(500);
    }
    const e1 = await launch(b, ORIGIN + '/cards/p/' + ep.slug + '/'); await sleep(4000);
    st = await swState(e1.page);
    check(Object.keys(st.caches).some(k => k.startsWith('cards-shell-') && st.caches[k].includes('/cards/p/' + ep.slug + '/')), 'episode: its own worker saved its page');
    const key = ep.root + '\\Script Docs\\main.cut.md', idx = {};
    idx[key] = {path: key, file: 'main.cut.md', q: 2, cuts: 12, when: Date.now()};
    await e1.page.ev(`new Promise(res=>{const rq=indexedDB.open('cards-offline',1);rq.onupgradeneeded=()=>{const db=rq.result;if(!db.objectStoreNames.contains('kv'))db.createObjectStore('kv')};rq.onsuccess=()=>{const db=rq.result;const tx=db.transaction('kv','readwrite');tx.objectStore('kv').put(${JSON.stringify(idx)},'index');tx.oncomplete=()=>{db.close();res(1)}}})`);
    await b.close();
    setMode('hang'); b = await browser(p);
    r = await launch(b, ORIGIN + '/cards/', {shot: 'picker-with-download.png'});
    check(await r.page.ev(`!!document.querySelector('.cl-offline .cl-offline-open')`), 'episode: the offline picker lists the downloaded cut list');
    check(await r.page.ev(`(document.querySelector('.cl-offline .cl-info .nm')||{offsetWidth:0}).offsetWidth > 100`), 'episode: its row is wide enough to read (not one letter per line)');
    const t0 = Date.now();
    await r.page.ev(`document.querySelector('.cl-offline-open').click(), 1`).catch(() => {});
    let at = '';
    for (let i = 0; i < 200; i++) {
      await sleep(100);
      try {
        at = await r.page.ev(`location.pathname + ' ' + document.readyState + ' ' + (navigator.serviceWorker.controller ? 'controlled' : 'free')`);
        if (at.startsWith('/cards/p/') && !/loading/.test(at)) break;
      } catch (e) { /* mid-navigation */ }
    }
    check(at.startsWith('/cards/p/' + ep.slug + '/') && /controlled/.test(at), 'episode: tapping it opens the episode offline, served by its own worker', (Date.now() - t0) + ' ms, ' + at);
    await b.close();
  } finally {
    setMode('pass');
    try { srv.kill(); } catch (e) { /* gone */ }
    proxy.close(); if (proxy.closeAllConnections) proxy.closeAllConnections();
  }
  console.log(fails.length ? `\n${fails.length} FAILED` : '\nall passed');
  process.exit(fails.length ? 1 : 0);
}
main().catch(e => { console.error(e); process.exit(2); });
