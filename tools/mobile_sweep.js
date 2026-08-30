// The mobile sweep: every dashboard page at phone width, photographed and
// measured (MOBILE_PLAN.md M0, 2026-08-30).
//
//     python tools/mobile_sweep_seed.py --port 8499
//     node tools/mobile_sweep.js --url http://127.0.0.1:8499 --user owen --password <printed>
//
// It signs in with a real password (POST /login carrying the CSRF token read
// off the page), hands the session cookie to a headless Chrome over CDP, and
// for every page in PAGES at every width in --widths it writes
// docs/mobile/<width>/<page>.png and records three things:
//
//   FAIL  the page scrolls SIDEWAYS (documentElement.scrollWidth > innerWidth)
//   FAIL  a non-`.scroll-x` element scrolls sideways -- today `.main` has
//         `overflow-x: auto`, so the content column absorbs the overflow and
//         the check above never fires even while the grid is dragging left
//         and right under a thumb. See MEASURE and docs/mobile/SWEEP.md.
//         Round 2 (2026-08-30) names the CULPRIT with it: the widest visible
//         descendant reaching furthest past the container's content edge,
//         its width, three ancestors, and whether it refuses to wrap. The
//         container alone was `main.main` on every page, which told nobody
//         which template to open.
//   WARN  the smallest visible control among `button, a.chip, .btn, input,
//         select` is under 44 px on either axis, with the selector
//   WARN  the smallest computed font-size actually rendering text is under 12 px
//
// ...plus a fourth FAIL that is not about layout at all: a page that
// redirected to /login. Without it a broken session would sweep seventeen
// copies of the login box and report every one of them clean.
//
// No npm dependencies, on purpose (the same rule MulticamPipeline's
// tests/test_looks.js follows): node 24 has fetch and WebSocket built in, and
// this tool has to run on the base rig and on CI with nothing installed.
// Chrome is driven over the DevTools protocol directly.
//
// Exits non-zero if anything FAILed. --json writes the same findings to a file
// so two runs (the baseline and the merged branch) can be diffed.
const { spawn } = require('child_process');
const os = require('os'), path = require('path'), fs = require('fs');

const REPO = path.dirname(__dirname);
const CHROME_DEFAULT = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
// The 44 px guideline (Apple HIG / Material's 48 dp, rounded to the smaller of
// the two) and the 12 px floor from MOBILE_PLAN.md §2 goal 1.
const TAP_MIN = 44, FONT_MIN = 12;

function arg(name, fallback) {
  const i = process.argv.indexOf('--' + name);
  return i >= 0 && process.argv[i + 1] !== undefined ? process.argv[i + 1] : fallback;
}
function flag(name) { return process.argv.indexOf('--' + name) >= 0; }

const URL_BASE = String(arg('url', 'http://127.0.0.1:8499')).replace(/\/+$/, '');
const USER = arg('user', 'owen');
const PASSWORD = arg('password', '');
const OUT = path.resolve(REPO, arg('out', path.join('docs', 'mobile')));
const JSON_OUT = path.resolve(REPO, arg('json', path.join(OUT, 'report.json')));
const CHROME = arg('chrome', CHROME_DEFAULT);
const DBG = parseInt(arg('debug-port', '9358'), 10);
// A page's own resolve_project. /project-setup is only reachable with one
// (ui.page_project_setup redirects to / without it) and there is no link to
// it on a dashboard whose projects are all mapped, so it is a flag with the
// seed tool's value as the default.
const RESOLVE_PROJECT = arg('resolve-project', 'FF5 Elections E2');
// 390x844 is a normal Android phone at DPR 3; 768x1024 is the tablet/narrow
// window case. The device metrics are what the CSS sees; the DPR only changes
// how many real pixels the PNG has.
const WIDTHS = String(arg('widths', '390,768')).split(',')
  .map(s => parseInt(s.trim(), 10)).filter(n => n > 0);
const METRICS = {
  390: { height: 844, dpr: 3, mobile: true },
  768: { height: 1024, dpr: 2, mobile: true },
};

// The page list from MOBILE_PLAN.md §M0: every page route except /setup,
// /download*, /admin/alerts/preview and /admin/site*. `anon` pages are
// visited with the cookies cleared (a signed-in browser is redirected off
// /login, so the login box can only be measured signed out).
const PAGES = [
  { name: 'login', url: '/login', anon: true },
  { name: 'home', url: '/' },
  { name: 'transfers', url: '/transfers' },
  { name: 'project', url: '/project/{project}' },
  { name: 'project-setup', url: '/project-setup?resolve_project={resolve}' },
  { name: 'installer', url: '/installer' },
  { name: 'admin-users', url: '/admin/users' },
  { name: 'admin-assignments', url: '/admin/assignments' },
  { name: 'admin-jobs', url: '/admin/jobs' },
  { name: 'admin-packages', url: '/admin/packages' },
  { name: 'admin-settings', url: '/admin/settings' },
  { name: 'admin-audit', url: '/admin/audit' },
  { name: 'admin-alerts', url: '/admin/alerts' },
  { name: 'admin-invariants', url: '/admin/invariants' },
  { name: 'admin-protection', url: '/admin/protection' },
  { name: 'admin-recovery', url: '/admin/recovery' },
];

const sleep = ms => new Promise(r => setTimeout(r, ms));
let ws, msgId = 0, pending = new Map(), chrome = null;
const profile = path.join(os.tmpdir(), 'ccsync-mobile-sweep-' + process.pid);

function send(method, params) {
  const n = ++msgId;
  ws.send(JSON.stringify({ id: n, method, params: params || {} }));
  return new Promise((res, rej) => pending.set(n, { res, rej }));
}
async function ev(expression, awaitPromise) {
  const r = await send('Runtime.evaluate',
    { expression, returnByValue: true, awaitPromise: !!awaitPromise });
  if (r.exceptionDetails) throw new Error(JSON.stringify(
    (r.exceptionDetails.exception && r.exceptionDetails.exception.description)
    || r.exceptionDetails.text));
  return r.result.value;
}

// ------------------------------------------------------------ sign in

// The dashboard's CSRF token is an HMAC over the session id (auth.csrf_token),
// so it is EMPTY on the signed-out login page and /login is exempt from the
// gate anyway (app._CSRF_EXEMPT_EXACT). It is read and sent regardless: the
// day that exemption goes away, this keeps working instead of 403ing, and
// reading it proves the page rendered rather than 500ed.
async function login() {
  const page = await fetch(URL_BASE + '/login');
  if (!page.ok) throw new Error('GET /login answered ' + page.status);
  const html = await page.text();
  const meta = html.match(/<meta name="csrf" content="([^"]*)"/);
  const field = html.match(/name="csrf"[^>]*value="([^"]*)"/);
  const token = (field && field[1]) || (meta && meta[1]) || '';
  const body = new URLSearchParams({
    username: USER, password: PASSWORD, next: '/', csrf: token,
  });
  const res = await fetch(URL_BASE + '/login', {
    method: 'POST', body, redirect: 'manual',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded',
               'X-CSRF-Token': token },
  });
  const cookies = res.headers.getSetCookie ? res.headers.getSetCookie()
    : [res.headers.get('set-cookie') || ''];
  const session = cookies.map(c => (c.match(/^ccsync_session=([^;]*)/) || [])[1])
    .filter(Boolean)[0];
  if (!session) {
    throw new Error('login did not set ccsync_session (status ' + res.status
      + ') -- wrong password, or the dashboard is not the seeded one');
  }
  return session;
}

// ------------------------------------------------------------ the measurement

// Runs INSIDE the page. Kept as one expression so a page that throws does so
// once, visibly, rather than half-reporting.
const MEASURE = `(function () {
  function sel(el) {
    // Short and human, not unique: this string is read by a person deciding
    // which template to fix, so tag + id + the first two classes is plenty.
    if (!el) return '?';
    let s = el.tagName.toLowerCase();
    if (el.id) return s + '#' + el.id;
    const cls = (el.className && el.className.baseVal !== undefined
      ? el.className.baseVal : String(el.className || '')).trim().split(/\\s+/)
      .filter(Boolean).slice(0, 2);
    if (cls.length) s += '.' + cls.join('.');
    if (el.getAttribute && el.getAttribute('type')) s += '[type=' + el.getAttribute('type') + ']';
    const p = el.parentElement;
    if (p && p !== document.body) s = p.tagName.toLowerCase()
      + (p.className ? '.' + String(p.className).trim().split(/\\s+/)[0] : '') + ' > ' + s;
    return s;
  }
  function sel1(el) {
    // The element's OWN token, with no parent prefix: what the ancestor
    // chain is made of, where sel()'s built-in parent would repeat itself.
    if (!el) return '?';
    if (el.id) return el.tagName.toLowerCase() + '#' + el.id;
    var cls = (el.className && el.className.baseVal !== undefined
      ? el.className.baseVal : String(el.className || '')).trim().split(/\s+/)
      .filter(Boolean).slice(0, 2);
    return el.tagName.toLowerCase() + (cls.length ? '.' + cls.join('.') : '');
  }
  function depth(el) {
    var d = 0;
    while (el.parentElement) { d++; el = el.parentElement; }
    return d;
  }
  function culpritOf(box) {
    // WHICH element makes the container scroll (round 2, 2026-08-30). Naming
    // the container names the symptom: \`main.main\` is on every page and
    // tells nobody which template to open. The edge to beat is the
    // container's own content-box right edge in viewport coordinates, with
    // the container scrolled to 0, which it is -- nothing has scrolled it.
    var br = box.getBoundingClientRect();
    var edge = br.left + box.clientLeft + box.clientWidth;
    var best = null, bestOver = 1;
    var kids = box.querySelectorAll('*');
    for (var q = 0; q < kids.length; q++) {
      var k = kids[q], kcs = getComputedStyle(k);
      if (!shown(k, kcs)) continue;
      var kr = k.getBoundingClientRect();
      // Two ways an element reaches past the edge: its own box does, or its
      // box fits and its CONTENT does not (a nowrap run inside a narrow cell).
      var over = Math.max(kr.right, kr.left + k.scrollWidth) - edge;
      if (over <= 1) continue;
      // Deepest wins a tie: every ancestor of the real culprit reaches
      // exactly as far, and the leaf is the one somebody can fix.
      if (!best || over > bestOver + 1
          || (Math.abs(over - bestOver) <= 1 && depth(k) > depth(best))) {
        if (over > bestOver) bestOver = over;
        best = k;
      }
    }
    if (!best) return null;
    var brr = best.getBoundingClientRect();
    var reach = Math.max(brr.right, brr.left + best.scrollWidth);
    var ws = getComputedStyle(best).whiteSpace;
    var anc = [], up = best.parentElement, n = 0;
    while (up && n < 3) { anc.push(sel1(up)); up = up.parentElement; n++; }
    return {
      selector: sel(best),
      right: Math.round(reach),
      past: Math.round(reach - edge),
      width: Math.round(Math.max(brr.width, best.scrollWidth)),
      white_space: ws,
      // Only the two that REFUSE to wrap: pre-wrap and pre-line both do.
      nowrap: ws === 'nowrap' || ws === 'pre',
      text: (best.textContent || '').trim().slice(0, 60),
      ancestors: anc,
    };
  }
  function shown(el, cs) {
    if (cs.display === 'none' || cs.visibility === 'hidden') return false;
    if (parseFloat(cs.opacity || '1') === 0) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  }
  var de = document.documentElement;
  var out = {
    path: location.pathname + location.search,
    title: document.title,
    scrollWidth: de.scrollWidth,
    innerWidth: window.innerWidth,
    tap: null, font: null, inner: null, counted: { taps: 0, texts: 0 },
  };
  // The SECOND overflow check, and on this codebase the one that fires:
  // \`.main { overflow-x: auto }\` (style.css:375) means the content column
  // takes the sideways scroll instead of the page, so the documentElement
  // measurement above stays clean while a phone is dragging the fleet grid
  // left and right. §3.2 says horizontal scroll is allowed INSIDE a
  // \`.scroll-x\` wrapper and nowhere else, so an element that is really
  // scrollable sideways and is not one (nor inside one) is the failure that
  // vocabulary exists to remove. Form controls are exempt: a text input
  // longer than its box scrolls by definition.
  var scrollers = document.body ? document.body.querySelectorAll('*') : [];
  for (var s = 0; s < scrollers.length; s++) {
    var sc = scrollers[s], scs = getComputedStyle(sc);
    if (scs.overflowX !== 'auto' && scs.overflowX !== 'scroll') continue;
    if (sc.closest('.scroll-x')) continue;
    if (/^(input|select|textarea)$/i.test(sc.tagName)) continue;
    if (!shown(sc, scs)) continue;
    var by = sc.scrollWidth - sc.clientWidth;
    if (by <= 1) continue;
    if (!out.inner || by > out.inner.by) out.inner = {
      by: Math.round(by), scrollWidth: sc.scrollWidth, clientWidth: sc.clientWidth,
      selector: sel(sc), culprit: null, _at: s,
    };
  }
  if (out.inner) {
    out.inner.culprit = culpritOf(scrollers[out.inner._at]);
    delete out.inner._at;
  }
  var els = document.querySelectorAll('button, a.chip, .btn, input, select');
  for (var i = 0; i < els.length; i++) {
    var el = els[i], cs = getComputedStyle(el);
    if (!shown(el, cs)) continue;
    out.counted.taps++;
    var r = el.getBoundingClientRect();
    var m = Math.min(r.width, r.height);
    if (!out.tap || m < out.tap.min) out.tap = {
      min: Math.round(m * 10) / 10, w: Math.round(r.width * 10) / 10,
      h: Math.round(r.height * 10) / 10, selector: sel(el),
    };
  }
  // The smallest font actually rendering text, not the smallest rule in the
  // stylesheet: an 8 px class nothing uses is not a phone problem.
  var all = document.body ? document.body.querySelectorAll('*') : [];
  for (var j = 0; j < all.length; j++) {
    var e2 = all[j], has = false;
    for (var k = 0; k < e2.childNodes.length; k++) {
      var n = e2.childNodes[k];
      if (n.nodeType === 3 && n.nodeValue && n.nodeValue.trim()) { has = true; break; }
    }
    if (!has) continue;
    var cs2 = getComputedStyle(e2);
    if (!shown(e2, cs2)) continue;
    out.counted.texts++;
    var size = parseFloat(cs2.fontSize);
    if (!(size > 0)) continue;
    if (!out.font || size < out.font.min) out.font = {
      min: Math.round(size * 10) / 10, selector: sel(e2),
      sample: (e2.textContent || '').trim().slice(0, 40),
    };
  }
  return out;
})()`;

// htmx settles asynchronously and several partials paint on hx-trigger="load",
// so a measurement taken at load time measures the skeleton. Wait for the
// first afterSettle, and give up after 1500 ms for the pages that have no
// htmx on them at all (login, installer).
const SETTLE = `new Promise(function (res) {
  var done = false;
  function fin(how) { if (!done) { done = true; res(how); } }
  document.body.addEventListener('htmx:afterSettle', function () {
    setTimeout(function () { fin('settled'); }, 250);
  });
  setTimeout(function () { fin('timeout'); }, 1500);
})`;

// ------------------------------------------------------------ the run

function verdicts(m, pageName) {
  const fails = [], warns = [];
  if (/^\/login/.test(m.path) && pageName !== 'login') {
    fails.push('redirected to /login (the session did not stick)');
  }
  const over = m.scrollWidth - m.innerWidth;
  if (over > 0) fails.push('the PAGE scrolls sideways by ' + over + ' px'
    + ' (scrollWidth ' + m.scrollWidth + ' > innerWidth ' + m.innerWidth + ')');
  if (m.inner) {
    const c = m.inner.culprit;
    fails.push('content scrolls sideways by ' + m.inner.by + ' px  '
      + m.inner.selector
      + (c ? '  <- ' + c.selector + ' (' + c.width + ' px wide, ' + c.past
             + ' px past the edge'
             + (c.nowrap ? ', white-space: ' + c.white_space : '') + ')'
           : '  <- nothing visible reaches past the edge'));
  }
  if (m.tap && m.tap.min < TAP_MIN) warns.push('tap target ' + m.tap.w + 'x'
    + m.tap.h + ' px  ' + m.tap.selector);
  else if (!m.tap) warns.push('no visible tap target on the page at all');
  if (m.font && m.font.min < FONT_MIN) warns.push('font ' + m.font.min + ' px  '
    + m.font.selector);
  return { fails, warns };
}

function pad(s, n) { s = String(s); return s + ' '.repeat(Math.max(0, n - s.length)); }

(async () => {
  if (!PASSWORD) {
    console.log('--password is required (mobile_sweep_seed.py prints one)');
    process.exit(2);
  }
  const session = await login();
  console.log('signed in as ' + USER + ' at ' + URL_BASE);

  chrome = spawn(CHROME, ['--headless=new', '--remote-debugging-port=' + DBG,
    '--user-data-dir=' + profile, '--no-first-run', '--disable-gpu',
    '--hide-scrollbars', 'about:blank'], { stdio: 'ignore' });
  let target = null;
  for (let i = 0; i < 40 && !target; i++) {
    await sleep(500);
    try {
      const r = await fetch('http://127.0.0.1:' + DBG + '/json/list');
      target = (await r.json()).filter(x => x.type === 'page')[0] || null;
    } catch (e) { /* chrome is not listening yet */ }
  }
  if (!target) { console.log('chrome never came up'); process.exit(1); }
  ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise(r => ws.addEventListener('open', r));
  ws.addEventListener('message', e => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) {
      const p = pending.get(m.id); pending.delete(m.id);
      m.error ? p.rej(new Error(JSON.stringify(m.error))) : p.res(m.result);
    }
  });
  await send('Runtime.enable');
  await send('Page.enable');
  await send('Network.enable');

  const findings = [];
  let project = null;

  for (const width of WIDTHS) {
    const metric = METRICS[width] || { height: 1024, dpr: 2, mobile: true };
    const dir = path.join(OUT, String(width));
    fs.mkdirSync(dir, { recursive: true });
    await send('Emulation.setDeviceMetricsOverride', {
      width, height: metric.height, deviceScaleFactor: metric.dpr,
      mobile: metric.mobile,
    });
    await send('Emulation.setTouchEmulationEnabled',
      { enabled: !!metric.mobile, maxTouchPoints: 5 });
    await send('Emulation.setEmitTouchEventsForMouse',
      { enabled: !!metric.mobile, configuration: metric.mobile ? 'mobile' : 'desktop' });
    console.log('\n== ' + width + ' x ' + metric.height + ' @' + metric.dpr + 'x');

    let signedIn = false;
    for (const page of PAGES) {
      if (page.anon) {
        await send('Network.clearBrowserCookies');
        signedIn = false;
      } else if (!signedIn) {
        await send('Network.setCookie', {
          name: 'ccsync_session', value: session, url: URL_BASE, path: '/',
        });
        signedIn = true;
      }
      // /project/{slug} is whatever project this dashboard actually has:
      // hard-coding the seed's slug would make the tool useless against a
      // real deployment.
      if (page.url.includes('{project}') && project === null) {
        await send('Page.navigate', { url: URL_BASE + '/' });
        await sleep(800);
        project = await ev(`(function(){var a=document.querySelector('a[href^="/project/"]');
          return a?a.getAttribute('href').split('/')[2].split('?')[0]:'';})()`);
      }
      const target_url = URL_BASE + page.url
        .replace('{project}', project || 'unknown')
        .replace('{resolve}', encodeURIComponent(RESOLVE_PROJECT));

      await send('Page.navigate', { url: target_url });
      await sleep(300);
      let settle = 'no-body';
      try { settle = await ev(SETTLE, true); } catch (e) { settle = 'threw'; }
      // The capture forces the renderer to commit a frame; the measurement
      // has to be read AFTER it or a page whose last partial landed during
      // the settle wait is measured mid-paint (test_looks.js, 2026-08-30).
      const shot = await send('Page.captureScreenshot', { format: 'png' });
      const png = path.join(dir, page.name + '.png');
      fs.writeFileSync(png, Buffer.from(shot.data, 'base64'));
      const m = await ev(MEASURE);
      const v = verdicts(m, page.name);
      findings.push({
        page: page.name, url: page.url, width, dpr: metric.dpr,
        landed: m.path, title: m.title, settle,
        scrollWidth: m.scrollWidth, innerWidth: m.innerWidth,
        overflow: Math.max(0, m.scrollWidth - m.innerWidth),
        inner_overflow: m.inner,
        tap: m.tap, font: m.font, counted: m.counted,
        fails: v.fails, warns: v.warns,
        png: path.relative(REPO, png).replace(/\\/g, '/'),
      });
      console.log('  ' + pad(page.name, 20)
        + (v.fails.length ? 'FAIL ' : v.warns.length ? 'warn ' : 'ok   ')
        + [...v.fails, ...v.warns].join('; '));
    }
  }

  // ------------------------------------------------------------ the table
  console.log('\n' + pad('page', 20) + pad('width', 6) + pad('page-ovf', 9)
    + pad('content-ovf', 12) + pad('tap', 6) + pad('font', 6) + pad('verdict', 8)
    + 'culprit');
  console.log('-'.repeat(120));
  for (const f of findings) {
    const c = f.inner_overflow && f.inner_overflow.culprit;
    console.log(pad(f.page, 20) + pad(f.width, 6)
      + pad(f.overflow ? '+' + f.overflow + ' px' : '-', 9)
      + pad(f.inner_overflow ? '+' + f.inner_overflow.by + ' px' : '-', 12)
      + pad(f.tap ? f.tap.min : '-', 6)
      + pad(f.font ? f.font.min : '-', 6)
      + pad(f.fails.length ? 'FAIL' : f.warns.length ? 'WARN' : 'ok', 8)
      + (c ? c.selector + '  ' + c.width + ' px'
             + (c.nowrap ? '  ' + c.white_space : '') : '-'));
  }
  const failed = findings.filter(f => f.fails.length).length;
  const warned = findings.filter(f => !f.fails.length && f.warns.length).length;
  console.log('-'.repeat(120));
  console.log(findings.length + ' page renders: ' + failed + ' FAIL, '
    + warned + ' WARN only, ' + (findings.length - failed - warned) + ' clean');

  fs.mkdirSync(path.dirname(JSON_OUT), { recursive: true });
  fs.writeFileSync(JSON_OUT, JSON.stringify({
    generated_at: new Date().toISOString(),
    url: URL_BASE, user: USER, widths: WIDTHS,
    thresholds: { tap_px: TAP_MIN, font_px: FONT_MIN },
    totals: { renders: findings.length, fail: failed, warn: warned },
    findings,
  }, null, 2) + '\n');
  console.log('report -> ' + path.relative(REPO, JSON_OUT).replace(/\\/g, '/'));

  try { ws.close(); } catch (e) { /* the socket is already gone */ }
  if (chrome) chrome.kill();
  try { fs.rmSync(profile, { recursive: true, force: true }); } catch (e) { /* windows lock */ }
  process.exit(failed ? 1 : 0);
})().catch(e => {
  console.log('THREW: ' + ((e && e.stack) || e));
  if (chrome) chrome.kill();
  process.exit(1);
});
