/* The design bench's shared shell (2026-09-25).
 *
 * Every page under dashboard/design loads cc-terminal.css and this file and
 * calls CC.page({...}). It draws what every real page has around its
 * content - the HUD, the Settings strip, the phone dock, the toast - and the
 * TUNE panel, whose settings are ONE store for the whole bench, so a tweak
 * made on any page is the look of every page.
 *
 * Page markup contract:
 *   <body data-page="home">            which nav entry is current
 *   <div id="settings-nav"></div>      optional: the Settings strip goes here
 *   CC.page({ page: 'users', settings: true, onData: fn })
 *       onData(mode) is called with 'busy' or 'calm' now and whenever the
 *       TUNE "data" switch moves, so a page can draw its empty states.
 *
 * Helpers for pages: CC.esc, CC.meter(n, of, cells), CC.win(name, meta, body),
 * CC.toast(text), CC.led(tone), CC.tag(tone, text, solid).
 */
(function () {
  'use strict';

  const NAV = [
    ['sync', 'home.html'], ['b-roll', 'broll.html'], ['music', 'music.html'],
    ['youtube', 'youtube.html'], ['cards', 'cards.html'], ['transfers', 'transfers.html'],
    ['settings', 'health.html'],
  ];
  // The real SETTINGS_NAV_GROUPS (dashboard ui.py), in its order and words.
  const SETTINGS = [
    ['run the fleet', [['site', 'SITE', 'site.html'], ['users', 'USERS', 'users.html'],
      ['assignments', 'SYNC PLANS', 'sync-plans.html'], ['transfers', 'TRANSFERS', 'transfers.html'],
      ['packages', 'PACKAGES', 'packages.html'], ['jobs', 'JOBS', 'jobs.html'],
      ['audit', 'HISTORY', 'history.html'], ['setup', 'SETUP', 'setup.html']]],
    ['is it healthy', [['health', 'HEALTH', 'health.html'], ['invariants', 'INVARIANTS', 'invariants.html'],
      ['protection', 'PROTECTION', 'protection.html'], ['alerts', 'ALERTS', 'alerts.html']]],
    ['when it breaks', [['recovery', 'RECOVERY', 'recovery.html'], ['help', 'HELP', 'help.html']]],
  ];
  const SETTINGS_KEYS = SETTINGS.flatMap(g => g[1].map(e => e[0]));
  const DOCK = [['sync', '⇅', 'home.html'], ['b-roll', '▣', 'broll.html'],
    ['cards', '≡', 'cards.html'], ['transfers', '↕', 'transfers.html'], ['more', '…', 'index.html']];

  const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const meter = (n, of, cells) => {
    const full = of ? Math.max(0, Math.min(cells, Math.round((n / of) * cells))) : 0;
    return '█'.repeat(full) + '<span class="rest">' + '░'.repeat(cells - full) + '</span>';
  };
  const win = (name, meta, body, cls) => `
    <section class="win ${cls || ''}">
      <div class="bar"><span>┌─╡</span><span class="t">${name}</span><span>╞</span><span class="rule"></span>${meta ? `<span class="meta">${meta}</span>` : ''}<span>═┐</span></div>
      ${body}
    </section>`;
  const led = tone => `<span class="led ${tone || ''}"></span>`;
  const tag = (tone, text, solid) => `<span class="tag ${solid ? 'solid ' : ''}${tone || ''}">${esc(text)}</span>`;

  // ------------------------------------------------------------ settings
  const KEY = 'ccsync.design.terminal';
  const HI = [['cyan', '0 229 255'], ['green', '58 255 110'], ['amber', '255 176 46'], ['white', '255 255 255'], ['violet', '181 140 255']];
  const DEFAULTS = { hi: '0 229 255', disp: "'Orbitron'", grain: '0.05', scan: '0.05', glow: '1', dither: '1', fs: '14px', d: '1', data: 'busy' };
  let settings = { ...DEFAULTS };
  try { settings = { ...DEFAULTS, ...JSON.parse(localStorage.getItem(KEY) || '{}') }; } catch (e) { /* blocked */ }
  try {
    const h = new URLSearchParams(location.hash.slice(1)).get('s');
    if (h) settings = { ...settings, ...JSON.parse(atob(h)) };
  } catch (e) { /* a bad hash is the defaults */ }
  let onData = null;

  function applySettings() {
    const r = document.documentElement.style;
    r.setProperty('--hi-rgb', settings.hi);
    r.setProperty('--disp', settings.disp + ", 'JetBrains Mono', sans-serif");
    r.setProperty('--fx-grain', settings.grain);
    r.setProperty('--fx-scan', settings.scan);
    r.setProperty('--fx-glow', settings.glow);
    r.setProperty('--fx-dither', settings.dither);
    r.setProperty('--fs', settings.fs);
    r.setProperty('--d', settings.d);
    document.querySelectorAll('.tune .opts[data-key]').forEach(o =>
      o.querySelectorAll('button').forEach(b => b.setAttribute('aria-pressed', String(settings[o.dataset.key] === b.dataset.v))));
    const sel = document.querySelector('.tune select[data-key=disp]');
    if (sel) sel.value = settings.disp;
    try { localStorage.setItem(KEY, JSON.stringify(settings)); } catch (e) { /* blocked */ }
  }
  // Another tab of the bench changed a setting: follow it.
  window.addEventListener('storage', e => {
    if (e.key !== KEY) return;
    try { settings = { ...DEFAULTS, ...JSON.parse(e.newValue || '{}') }; } catch (err) { return; }
    applySettings();
    if (onData) onData(settings.data);
  });

  // ------------------------------------------------------------ chrome
  const MARK = '<svg class="hud-mark" viewBox="0 0 654.89 305.2" aria-hidden="true"><path d="M363.02,134.4h109.96l-23.42,41.25c-7.12,12.22-16.72,21.9-28.77,29.02c-12.04,7.12-25.2,10.69-39.46,10.69H0L100.81,39.71c6.79-12.22,16.29-21.9,28.5-29.02C141.53,3.56,154.6,0,168.52,0h231.67L214.85,61.08c-13.57,4.42-23.93,12.91-31.06,25.46l-59.56,103.88h174.63c9.84,0,19.09-2.46,27.75-7.38c8.65-4.93,15.53-11.81,20.62-20.65L363.02,134.4z"/><path d="M291.86,170.81H181.91l23.42-41.25c7.12-12.22,16.72-21.9,28.77-29.02c12.04-7.12,25.2-10.69,39.46-10.69h381.33L554.07,265.5c-6.79,12.22-16.29,21.9-28.5,29.02c-12.22,7.12-25.29,10.69-39.21,10.69H254.7l185.33-61.08c13.57-4.42,23.93-12.91,31.06-25.46l59.56-103.88H356.03c-9.84,0-19.09,2.46-27.75,7.38c-8.65,4.93-15.53,11.81-20.62,20.65L291.86,170.81z"/></svg>';

  function hud(current, bare) {
    const navCur = SETTINGS_KEYS.includes(current) && current !== 'transfers' ? 'settings'
      : current === 'home' ? 'sync' : current;
    const nav = bare ? '' : `<nav class="hud-nav" aria-label="main">${NAV.map(([n, href]) =>
      `<a href="${href}" ${n === navCur ? 'aria-current="page"' : ''}><span class="slash">&gt;</span>${n}</a>`).join('')}</nav>`;
    const meta = bare ? '' : `<div class="hud-meta">
        <a href="home.html#problems" title="problems the server found"><span class="led err"></span><b>4</b> problems</a>
        <a class="hide-sm" href="health.html" title="alerts"><span class="led warn"></span><b>22</b> alerts</a>
        <a class="user hide-sm" href="account.html" title="your account: name, computers, settings">owen<b>@admin</b></a>
        <span class="hud-clock" id="cc-clock"></span>
      </div>`;
    return `<header class="hud">
      <a class="hud-brand" href="index.html" title="the design bench: every page">${MARK}<span class="hud-name">CC SYNC<small>/ the creators club</small></span></a>
      ${nav}<span class="hud-spacer"></span>${meta}
    </header>`;
  }

  function settingsStrip(current) {
    return `<nav class="snav" aria-label="settings">${SETTINGS.map(([group, entries]) => `
      <div class="snav-g"><span class="snav-h">${group}</span>${entries.map(([k, label, href]) =>
        `<a href="${href}" ${k === current ? 'aria-current="page"' : ''}>${label.toLowerCase()}</a>`).join('')}</div>`).join('')}
    </nav>`;
  }

  function tunePanel() {
    return `<button class="key tune-key" type="button" id="cc-tune-key"><span class="t">tune</span><span class="kbd">T</span></button>
    <aside class="tune win" id="cc-tune" aria-label="design tuning">
      <div class="bar"><span>┌─╡</span><span class="t">tune.cfg</span><span>╞</span><span class="rule"></span><span class="meta">every page</span><span>═┐</span></div>
      <div class="body">
        <div class="row"><span>live colour</span><div class="opts" data-key="hi">${HI.map(([n, rgb]) => `<button class="swatch" data-v="${rgb}" title="${n}" style="background:rgb(${rgb})"></button>`).join('')}</div></div>
        <div class="row"><span>display</span><select data-key="disp">
          <option value="'Orbitron'">Orbitron (the site)</option>
          <option value="'JetBrains Mono'">JetBrains Mono</option>
          <option value="'Space Mono'">Space Mono</option></select></div>
        <div class="row"><span>grain</span><div class="opts" data-key="grain"><button data-v="0">off</button><button data-v="0.05">subtle</button><button data-v="0.1">heavy</button></div></div>
        <div class="row"><span>scanlines</span><div class="opts" data-key="scan"><button data-v="0">off</button><button data-v="0.05">subtle</button><button data-v="0.1">heavy</button></div></div>
        <div class="row"><span>glow</span><div class="opts" data-key="glow"><button data-v="0">off</button><button data-v="1">on</button></div></div>
        <div class="row"><span>dos shadow</span><div class="opts" data-key="dither"><button data-v="0">off</button><button data-v="1">on</button></div></div>
        <div class="row"><span>text size</span><div class="opts" data-key="fs"><button data-v="13px">13</button><button data-v="14px">14</button><button data-v="15px">15</button><button data-v="16px">16</button></div></div>
        <div class="row"><span>density</span><div class="opts" data-key="d"><button data-v="0.8">tight</button><button data-v="1">normal</button><button data-v="1.2">airy</button></div></div>
        <div class="row"><span>data</span><div class="opts" data-key="data"><button data-v="busy">busy day</button><button data-v="calm">calm day</button></div></div>
        <div class="opts" style="margin-top:6px"><button type="button" id="cc-copy">copy settings</button><button type="button" id="cc-reset">reset</button></div>
      </div>
    </aside>`;
  }

  let toastTimer = null;
  function toast(text) {
    const t = document.getElementById('cc-toast');
    if (!t) return;
    t.querySelector('.tt').textContent = text;
    t.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.remove('show'), 2400);
  }

  function page(opts) {
    opts = opts || {};
    const current = opts.page || document.body.dataset.page || 'home';
    onData = opts.onData || null;
    document.body.insertAdjacentHTML('afterbegin', hud(current, opts.bare));
    const slot = document.getElementById('settings-nav');
    if (slot) slot.outerHTML = settingsStrip(current);
    if (!opts.bare) {
      document.body.insertAdjacentHTML('beforeend', `<nav class="dock" aria-label="main">${DOCK.map(([n, g, href]) =>
        `<a href="${href}" ${(n === 'sync' && current === 'home') || n === current ? 'aria-current="page"' : ''}><span class="g">${g}</span>${n}</a>`).join('')}</nav>`);
    }
    document.body.insertAdjacentHTML('beforeend', `<div class="toast" id="cc-toast" role="status"><span class="p">&gt;</span><span class="tt"></span></div>${tunePanel()}`);

    const tune = document.getElementById('cc-tune');
    tune.addEventListener('click', e => {
      const b = e.target.closest('.opts[data-key] button');
      if (!b) return;
      settings[b.parentElement.dataset.key] = b.dataset.v;
      applySettings();
      if (b.parentElement.dataset.key === 'data' && onData) onData(settings.data);
    });
    tune.querySelector('select[data-key=disp]').addEventListener('change', e => { settings.disp = e.target.value; applySettings(); });
    document.getElementById('cc-tune-key').addEventListener('click', () => tune.classList.toggle('open'));
    document.getElementById('cc-reset').addEventListener('click', () => { settings = { ...DEFAULTS }; applySettings(); if (onData) onData(settings.data); });
    document.getElementById('cc-copy').addEventListener('click', () => {
      const json = JSON.stringify(settings);
      const text = json + '\n' + location.href.split('#')[0] + '#s=' + btoa(json);
      if (navigator.clipboard) navigator.clipboard.writeText(text).then(() => toast('settings copied'), () => toast('copy refused'));
      else prompt('copy these settings', json);
    });
    document.addEventListener('keydown', e => {
      if (/input|select|textarea/i.test(e.target.tagName) || e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.key === 't' || e.key === 'T') tune.classList.toggle('open');
    });

    // Generic behaviour every page gets for free: busy keys and dismissals.
    document.addEventListener('click', e => {
      const busy = e.target.closest('.key[data-busy]');
      if (busy) {
        // the key keeps its width while its label changes: nothing beside it moves
        busy.style.minWidth = busy.offsetWidth + 'px';
        busy.classList.add('busy');
        setTimeout(() => { busy.classList.remove('busy'); toast(busy.dataset.busy || 'done'); }, 1400);
      }
      const dis = e.target.closest('[data-dismiss]');
      if (dis) {
        const row = dis.closest(dis.dataset.dismiss || '.prob');
        if (row) { row.classList.add('gone'); setTimeout(() => row.remove(), 200); }
      }
    });

    const clock = document.getElementById('cc-clock');
    const tick = () => { if (clock) clock.textContent = new Date().toLocaleTimeString('en-GB', { timeZone: 'Asia/Taipei', hour12: false }) + ' TPE'; };
    tick(); setInterval(tick, 1000);

    applySettings();
    if (onData) onData(settings.data);
    foldable(current);
    tooltips();
  }

  // ---------------------------------------------------------- folding
  // Every .win folds from its bar. Windows are often re-rendered by a page's
  // own script, so new bars are decorated as they appear. The state is kept
  // per page and per window title.
  function foldable(page) {
    const FKEY = 'ccsync.design.fold.' + page;
    let folded = {};
    try { folded = JSON.parse(localStorage.getItem(FKEY) || '{}'); } catch (e) { /* blocked */ }
    const nameOf = bar => ((bar.querySelector('.t') || bar).textContent || '').trim();
    const decorate = root => {
      (root.querySelectorAll ? root.querySelectorAll('.win > .bar') : []).forEach(bar => {
        if (bar.classList.contains('can-fold') || bar.closest('.tune')) return;
        bar.classList.add('can-fold');
        bar.setAttribute('title', bar.getAttribute('title') || 'fold or unfold this window');
        const g = document.createElement('span');
        g.className = 'fold-g';
        g.textContent = '\u25BE';
        bar.insertBefore(g, bar.firstChild);
        if (folded[nameOf(bar)]) bar.parentElement.classList.add('collapsed');
      });
    };
    decorate(document);
    new MutationObserver(ms => ms.forEach(m => m.addedNodes.forEach(n => { if (n.nodeType === 1) decorate(n.parentElement || n); })))
      .observe(document.body, { childList: true, subtree: true });
    document.addEventListener('click', e => {
      const bar = e.target.closest('.win > .bar.can-fold');
      if (!bar || e.target.closest('a, button, input, select, label, .iv-switch')) return;
      const w = bar.parentElement;
      w.classList.toggle('collapsed');
      folded[nameOf(bar)] = w.classList.contains('collapsed');
      try { localStorage.setItem(FKEY, JSON.stringify(folded)); } catch (err) { /* blocked */ }
    });
  }

  // ---------------------------------------------------------- tooltips
  // Any title="" becomes the bench's tooltip (the attribute moves to
  // data-tip so the browser's own grey box does not also appear).
  function tooltips() {
    const tip = document.createElement('div');
    tip.className = 'cc-tip';
    tip.setAttribute('role', 'tooltip');
    document.body.appendChild(tip);
    let cur = null;
    const show = (el, x, y) => {
      if (el.hasAttribute('title')) { el.dataset.tip = el.getAttribute('title'); el.removeAttribute('title'); }
      const text = el.dataset.tip;
      if (!text) return;
      cur = el;
      tip.textContent = text;
      const r = el.getBoundingClientRect();
      const tx = Math.min(window.innerWidth - tip.offsetWidth - 12, Math.max(8, (x == null ? r.left : x) + 12));
      let ty = (y == null ? r.bottom : y) + 14;
      if (ty + tip.offsetHeight > window.innerHeight - 8) ty = r.top - tip.offsetHeight - 8;
      tip.style.left = tx + 'px';
      tip.style.top = ty + 'px';
      tip.classList.add('show');
    };
    const hide = () => { cur = null; tip.classList.remove('show'); };
    document.addEventListener('mouseover', e => {
      const el = e.target.closest('[title], [data-tip]');
      if (!el) { if (cur) hide(); return; }
      if (el !== cur) show(el, e.clientX, e.clientY);
    });
    document.addEventListener('mousemove', e => { if (cur && !cur.contains(e.target)) hide(); });
    document.addEventListener('focusin', e => { const el = e.target.closest('[title], [data-tip]'); if (el) show(el); });
    document.addEventListener('focusout', hide);
    window.addEventListener('scroll', hide, true);
  }

  window.CC = { page, esc, meter, win, led, tag, toast, get data() { return settings.data; } };
})();
