/* Six ways to show a computer's issues (design bench, 2026-09-25).
 *
 * Owner: "I don't like the issues being these card boxes in general. Let's
 * come up with some variants for visualising issues." Every variant fits the
 * computer row's fixed three-line slot (the rows stay symmetrical) and says
 * the same thing: how bad the worst issue is, how many there are, and what
 * each one is. Switched from a strip on the computers window; the choice is
 * remembered in the browser like TUNE.
 *
 *   log     one coloured line per issue, a severity glyph, no boxes
 *   tree    the same lines hung off box-drawing branches
 *   matrix  a fixed 3x3 panel of issue codes that light up (hover for detail)
 *   counts  severity counters and the worst issue in words, "+N more"
 *   bar     one segment per issue as a strip, the worst issue beside it
 *   ticker  one line, issues joined by a dot, faded at the edge, scrollable
 *   tags    today's framed boxes, for comparison
 *
 * An issue is [severity, text] with severity 'err' | 'warn' | 'hi' (info).
 */
(function () {
  'use strict';
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const GLYPH = { err: '✕', warn: '▲', hi: '●' };
  const RANK = { err: 0, warn: 1, hi: 2 };
  const sorted = list => list.slice().sort((a, b) => RANK[a[0]] - RANK[b[0]]);

  // The matrix's nine fixed cells, in reading order. An issue lights the
  // first cell whose words it matches; the cell takes its worst severity.
  const CELLS = [
    ['ENG', 'Sync engine: the programs that move files (Syncthing and the upload and download lanes)', /engine|stopped itself|folder error|not heard/],
    ['DSK', 'Disk space: room left on the drive the footage lives on', /free|disk|full/],
    ['UPD', 'Updates: whether this computer runs the newest CC Sync', /update|behind|version/],
    ['CLK', 'Clock: whether this computer and the server agree on the time with the server (a wrong clock confuses sync)', /clock/],
    ['CFL', 'Conflicts: files changed in two places at once, so two copies now exist', /conflict/],
    ['UPL', 'Uploads: footage that cannot be sent up, for example because it sits outside the project folders', /upload|outside the tree|unfiltered|orphan/],
    ['CRS', 'Crashes: times the CC Sync app closed unexpectedly', /crash/],
    ['HLT', 'Stopped: syncing paused on purpose, by an admin or by a safety check', /stopped by|paused|halt/],
    ['JOB', 'Job: work the server handed this computer, such as making proxies', /job/],
  ];

  const none = '<span class="iv-none" title="Nothing wrong on this computer.">✓ none</span>';
  const title = list => esc(sorted(list).map(i => `${GLYPH[i[0]]} ${i[1]}`).join('\n'));

  const V = {
    log(list) {
      if (!list.length) return none;
      return `<div class="iv-log">${sorted(list).map(i =>
        `<div class="iv-l ${i[0]}"><span class="g">${GLYPH[i[0]]}</span><span class="x">${esc(i[1])}</span></div>`).join('')}</div>`;
    },
    tree(list) {
      if (!list.length) return none;
      const s = sorted(list);
      return `<div class="iv-log iv-tree">${s.map((i, n) =>
        `<div class="iv-l ${i[0]}"><span class="br">${n === s.length - 1 ? '└─' : '├─'}</span><span class="g">${GLYPH[i[0]]}</span><span class="x">${esc(i[1])}</span></div>`).join('')}</div>`;
    },
    matrix(list) {
      const lit = CELLS.map(([code, name, re]) => {
        const hits = list.filter(i => re.test(i[1].toLowerCase()));
        const sev = hits.length ? sorted(hits)[0][0] : '';
        return `<span class="iv-c ${sev}" title="${esc(code + ' = ' + name)}${hits.length ? '\n' + esc(hits.map(h => h[1]).join('\n')) : '\nnothing wrong here'}">${code}</span>`;
      }).join('');
      return `<div class="iv-matrix" title="${list.length ? title(list) : 'no issues'}">${lit}</div>`;
    },
    counts(list) {
      if (!list.length) return none;
      const n = s => list.filter(i => i[0] === s).length;
      const worst = sorted(list)[0];
      const more = list.length - 1;
      return `<div class="iv-counts" title="${title(list)}">
        <div class="iv-n">${['err', 'warn', 'hi'].filter(n).map(s => `<span class="${s}"><b>${n(s)}</b> ${GLYPH[s]}</span>`).join('')}</div>
        <div class="iv-worst ${worst[0]}">${esc(worst[1])}</div>
        ${more ? `<div class="iv-more">+${more} more</div>` : ''}
      </div>`;
    },
    bar(list) {
      if (!list.length) return none;
      const s = sorted(list);
      return `<div class="iv-bar" title="${title(list)}">
        <div class="iv-seg">${s.map(i => `<i class="${i[0]}"></i>`).join('')}<span class="iv-segn">${list.length}</span></div>
        <div class="iv-worst ${s[0][0]}">${esc(s[0][1])}</div>
        ${s.length > 1 ? `<div class="iv-more">${esc(s.slice(1).map(i => i[1]).join(', '))}</div>` : ''}
      </div>`;
    },
    ticker(list) {
      if (!list.length) return none;
      return `<div class="iv-ticker" title="${title(list)}"><div class="iv-tk">${sorted(list).map(i =>
        `<span class="${i[0]}"><span class="g">${GLYPH[i[0]]}</span> ${esc(i[1])}</span>`).join('<span class="dot">·</span>')}</div></div>`;
    },
    tags(list) {
      if (!list.length) return '<span class="none">none</span>';
      return list.map(f => `<span class="tag ${f[0]}" title="${esc(f[1])}">${esc(f[1])}</span>`).join('');
    },
  };
  const TIPS = {
    log: 'One line per issue, worst first.',
    tree: 'The same lines, hung off a tree.',
    matrix: 'Nine fixed boxes, one per kind of issue, that light up. Hover a box for what it means.',
    counts: 'How many of each severity, and the worst issue in words.',
    bar: 'One coloured block per issue, and the worst one in words.',
    ticker: 'Every issue on one line; scroll sideways for the rest.',
    tags: 'Each issue as a coloured word.',
  };
  const NAMES = ['log', 'tree', 'matrix', 'counts', 'bar', 'ticker', 'tags'];
  const KEY = 'ccsync.design.issues';
  let current = 'log';
  try { current = localStorage.getItem(KEY) || 'log'; } catch (e) { /* blocked */ }
  try { const q = new URLSearchParams(location.search).get('iv'); if (q) current = q; } catch (e) { /* no query */ }
  if (!NAMES.includes(current)) current = 'log';

  window.ISSUES = {
    get variant() { return current; },
    render(list) { return V[current](list || []); },
    // the switcher, drawn into a window's title bar meta slot
    switcher(onChange) {
      const el = document.createElement('span');
      el.className = 'iv-switch';
      el.innerHTML = '<span class="lab" title="Design bench only: switch how the issues column is drawn. Not part of the real page.">issues:</span>' + NAMES.map(n =>
        `<button type="button" data-v="${n}" aria-pressed="${n === current}" title="${esc(TIPS[n])}">${n}</button>`).join('');
      el.addEventListener('click', e => {
        const b = e.target.closest('button[data-v]');
        if (!b) return;
        current = b.dataset.v;
        try { localStorage.setItem(KEY, current); } catch (err) { /* blocked */ }
        el.querySelectorAll('button').forEach(x => x.setAttribute('aria-pressed', String(x.dataset.v === current)));
        onChange();
      });
      return el;
    },
  };
})();
