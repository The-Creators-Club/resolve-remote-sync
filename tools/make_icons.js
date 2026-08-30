// The dashboard's PWA icons, rasterised from dashboard/static/icons/icon.svg.
//
//     node tools/make_icons.js [--check]
//
// Why a node script and not PIL: the dashboard venv has no PIL and this repo
// does not add a dependency to draw five PNGs once a year (MOBILE_PLAN.md 4 M4,
// 2026-08-30). Chrome is on every rig that builds this, it already renders the
// SVG the browser will show, and the CDP pattern is the one MulticamPipeline's
// tests/test_looks.js uses -- no npm packages, no build step. The PNGs are
// COMMITTED, so nobody needs node to ship a release; this tool exists to redraw
// them when the mark changes, and `--check` re-renders into a temp dir and
// compares the sizes so CI could notice a stale commit.
//
// The mark's paths live in icon.svg only. This script re-embeds them at two
// scales: `any` is icon.svg as drawn (the mark at 74% of the box, inside a
// rounded panel), `maskable` is full bleed with the mark at 55% so it clears
// the 80% safe circle Android crops to.
const { spawn } = require('child_process');
const os = require('os'), path = require('path'), fs = require('fs');

const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const DBG = 9358;
const ROOT = path.dirname(__dirname);
const ICONS = path.join(ROOT, 'dashboard', 'static', 'icons');
const CHECK = process.argv.indexOf('--check') >= 0;
const OUT = CHECK ? fs.mkdtempSync(path.join(os.tmpdir(), 'ccsync-icons-')) : ICONS;
const profile = path.join(os.tmpdir(), 'ccsync-icons-' + process.pid);
const sleep = ms => new Promise(r => setTimeout(r, ms));
let ws, id = 0, chrome = null;
const pending = new Map();

// name -> [size, purpose]. 180 is the apple-touch-icon (base.html), 192/512
// are what Chrome's install prompt and the splash screen want.
const TARGETS = [
  ['icon-180.png', 180, 'any'],
  ['icon-192.png', 192, 'any'],
  ['icon-512.png', 512, 'any'],
  ['icon-192-maskable.png', 192, 'maskable'],
  ['icon-512-maskable.png', 512, 'maskable'],
];

function send(m, p) {
  const n = ++id;
  ws.send(JSON.stringify({ id: n, method: m, params: p || {} }));
  return new Promise((res, rej) => pending.set(n, { res, rej }));
}

// The two <path> elements out of icon.svg. A regex rather than a parser
// because this file is ours and it has exactly two of them; if that stops
// being true the count check below fails loudly instead of drawing half a mark.
function markPaths() {
  const src = fs.readFileSync(path.join(ICONS, 'icon.svg'), 'utf8');
  const paths = src.match(/<path\b[\s\S]*?\/>/g) || [];
  if (paths.length !== 2) {
    console.log('icon.svg no longer holds exactly two <path> elements: ' + paths.length);
    process.exit(1);
  }
  return paths.join('\n');
}

function doc(size, purpose, paths) {
  // The mark's own box is 654.89 x 305.2 (favicon.svg), centred in a 512 box.
  const frac = purpose === 'maskable' ? 0.55 : 0.74;
  const scale = (512 * frac) / 654.89;
  const w = 654.89 * scale, h = 305.2 * scale;
  const x = (512 - w) / 2, y = (512 - h) / 2;
  const panel = purpose === 'maskable'
    ? '<rect width="512" height="512" fill="#0a0a0d"/>'
    : '<rect width="512" height="512" rx="96" fill="#0a0a0d"/>'
      + '<rect x="10" y="10" width="492" height="492" rx="88" fill="none"'
      + ' stroke="#7c1322" stroke-width="10"/>';
  return '<!doctype html><html><body style="margin:0;background:#0a0a0d">'
    + '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="'
    + size + '" height="' + size + '">' + panel
    + '<g transform="translate(' + x.toFixed(2) + ' ' + y.toFixed(2)
    + ') scale(' + scale.toFixed(5) + ')">' + paths + '</g></svg></body></html>';
}

(async () => {
  const paths = markPaths();
  chrome = spawn(CHROME, ['--headless=new', '--remote-debugging-port=' + DBG,
    '--user-data-dir=' + profile, '--no-first-run', '--disable-gpu',
    '--hide-scrollbars', 'about:blank'], { stdio: 'ignore' });
  let target = null;
  for (let i = 0; i < 40 && !target; i++) {
    await sleep(500);
    try {
      const rr = await fetch('http://127.0.0.1:' + DBG + '/json/list');
      target = (await rr.json()).filter(x => x.type === 'page')[0] || null;
    } catch (e) { /* not up yet */ }
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
  await send('Page.enable');

  for (const [name, size, purpose] of TARGETS) {
    await send('Emulation.setDeviceMetricsOverride',
      { width: size, height: size, deviceScaleFactor: 1, mobile: false });
    const url = 'data:text/html;base64,'
      + Buffer.from(doc(size, purpose, paths), 'utf8').toString('base64');
    await send('Page.navigate', { url });
    await sleep(400);
    const shot = await send('Page.captureScreenshot', {
      format: 'png', captureBeyondViewport: true,
      clip: { x: 0, y: 0, width: size, height: size, scale: 1 },
    });
    const file = path.join(OUT, name);
    fs.writeFileSync(file, Buffer.from(shot.data, 'base64'));
    console.log('  ' + name + '  ' + size + 'x' + size + ' ' + purpose
      + '  ' + fs.statSync(file).size + ' bytes');
  }

  if (CHECK) {
    let bad = 0;
    for (const [name] of TARGETS) {
      const a = path.join(ICONS, name), b = path.join(OUT, name);
      if (!fs.existsSync(a)) { console.log('  MISSING ' + name); bad++; continue; }
      // Byte equality is too strong (a Chrome update changes the encoder), so
      // this only says the committed file is a PNG of the right size.
      const head = fs.readFileSync(a).subarray(16, 24), want = fs.readFileSync(b).subarray(16, 24);
      if (!head.equals(want)) { console.log('  WRONG SIZE ' + name); bad++; }
    }
    console.log(bad ? 'stale icons: ' + bad : 'icons are current');
    if (bad) process.exit(1);
  } else {
    console.log('wrote ' + TARGETS.length + ' icons into ' + ICONS);
  }
  try { ws.close(); } catch (e) { /* going away anyway */ }
  if (chrome) chrome.kill();
  process.exit(0);
})();
