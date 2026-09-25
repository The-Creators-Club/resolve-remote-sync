/* cc_spa.js: the terminal look's small helper for the mounted apps (UI port
   phase 6, plan 7.1 row 6). BYTE-IDENTICAL in every app's static directory
   that ships it (each suite's test_cc_body.py compares the copies), because
   the dashboard's own cc.js is not loaded here and the injected HUD carries
   no script.

   Everything it does is gated on html.cc, which the head script sets from the
   dashboard's readable cookie and the injected topbar's marker then confirms
   or clears. With html.cc absent it changes nothing, so the classic page is
   exactly what it was:

   windows  an element with data-cc-win="title" gets a bar (a real fold button
            and the title) and the window look. The fold state is kept per
            page in localStorage under ccsync.spafold:<path>. An element with
            data-cc-own-fold keeps the app's own fold control; it gets the
            window look only.
   labels   a control whose whole text is a bracketed label reads as the
            plain label (the owner's no-bracket rule for the terminal look),
            and bracketed labels inside running text read as a quoted label.
            The original text is kept and put back if the look is switched
            off, so the app's own code and its tests keep the bracketed form.
   tips     a title shows as the terminal tip on hover, and on tap for a
            non-control on a touch screen.
   confirm  ccSpa.confirm(question) answers a promise through a dialog; with
            the look off it is the browser's own confirm.

   No leading-slash URL, no regular-expression literal that begins with a
   slash after a bracket, no long dash: each app's mounted-prefix and
   dash scans read this file raw. */
(function () {
  'use strict';
  if (window.ccSpa) return;
  var root = document.documentElement;
  var FOLD_KEY = 'ccsync.spafold:' + location.pathname;
  var WHOLE = new RegExp('^\\s*\\[ ([^\\[\\]]+?) \\]\\s*$');
  var TOGGLE = new RegExp('^\\s*\\[[-+]\\] (.+)$');
  var INLINE = new RegExp('\\[ ([A-Z0-9][A-Z0-9 .,:/\'&-]*?) \\]', 'g');
  var KEEP = { NAS: 1, AI: 1, URL: 1, CSV: 1, EN: 1, ZH: 1, OK: 1, BPM: 1, CPU: 1, GPU: 1, AVC: 1, PO: 1, JS: 1, CLAP: 1, ID: 1 };
  var PROPER = { resolve: 'Resolve', youtube: 'YouTube', claude: 'Claude', 'cc': 'CC' };
  var saved = new WeakMap();
  var observer = null;

  function active() { return root.classList.contains('cc'); }

  // "ADD MUSIC" -> "Add music"; acronyms and product names keep their case.
  function sentence(s) {
    var words = String(s).trim().split(' ');
    return words.map(function (w, i) {
      if (KEEP[w]) return w;
      var lw = w.toLowerCase();
      if (PROPER[lw]) return PROPER[lw];
      if (w !== w.toUpperCase()) return w;
      return i === 0 ? lw.charAt(0).toUpperCase() + lw.slice(1) : lw;
    }).join(' ');
  }

  // The terminal form of one control's text, or null when it is not bracketed.
  function label(text) {
    var m = WHOLE.exec(text);
    if (m) return sentence(m[1]);
    m = TOGGLE.exec(text);
    if (m) return sentence(m[1]);
    return null;
  }

  // Running text: "press [ RETRY ] to" -> "press "Retry" to".
  function inline(text) {
    if (text.indexOf('[ ') === -1) return null;
    var out = text.replace(INLINE, function (_, l) { return '"' + sentence(l) + '"'; });
    return out === text ? null : out;
  }

  function isControl(el) {
    return !!(el && el.closest && el.closest('button, a, .text-btn, .modebtn, [role="button"]'));
  }

  function rewriteNode(node) {
    if (node.nodeType !== 3) return;
    var p = node.parentNode;
    if (!p || p.nodeType !== 1) return;
    var tag = p.tagName;
    if (tag === 'SCRIPT' || tag === 'STYLE' || tag === 'TEXTAREA' || tag === 'PRE') return;
    var text = node.nodeValue;
    if (!text || text.indexOf('[') === -1) return;
    var next = null;
    if (isControl(p) && p.childNodes.length === 1) next = label(text);
    if (next === null) next = inline(text);
    if (next === null || next === text) return;
    saved.set(node, text);
    node.nodeValue = next;
  }

  function rewrite(scope) {
    if (!scope) return;
    if (scope.nodeType === 3) { rewriteNode(scope); return; }
    if (scope.nodeType !== 1 && scope.nodeType !== 9) return;
    var walker = document.createTreeWalker(scope, 4, null);
    var n;
    var nodes = [];
    while ((n = walker.nextNode())) nodes.push(n);
    nodes.forEach(rewriteNode);
  }

  function restoreText() {
    var walker = document.createTreeWalker(document.body, 4, null);
    var n;
    while ((n = walker.nextNode())) {
      if (saved.has(n)) {
        var was = saved.get(n);
        saved.delete(n);
        n.nodeValue = was;
      }
    }
  }

  // ------------------------------------------------------------- windows
  function readFolds() {
    try { return JSON.parse(localStorage.getItem(FOLD_KEY) || '{}') || {}; } catch (e) { return {}; }
  }
  function writeFolds(f) {
    try { localStorage.setItem(FOLD_KEY, JSON.stringify(f)); } catch (e) { /* this visit only */ }
  }

  function setFolded(win, folded) {
    win.classList.toggle('cc-folded', !!folded);
    var btn = win.querySelector(':scope > .cc-bar > .cc-fold');
    if (btn) btn.setAttribute('aria-expanded', folded ? 'false' : 'true');
  }

  function decorate(win) {
    if (win.hasAttribute('data-cc-own-fold')) { win.classList.add('cc-win'); return; }
    if (win.querySelector(':scope > .cc-bar')) return;
    var title = win.getAttribute('data-cc-win') || '';
    if (!title) {
      var h = win.querySelector(':scope > h2, :scope > h3');
      title = h ? h.textContent.trim().toLowerCase().replace(new RegExp('\\s+', 'g'), '_') : 'window';
    }
    var bar = document.createElement('div');
    bar.className = 'cc-bar';
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'cc-fold';
    btn.setAttribute('aria-expanded', 'true');
    btn.setAttribute('aria-label', 'fold or unfold ' + title.replace(new RegExp('_', 'g'), ' '));
    var g = document.createElement('span');
    g.className = 'cc-fold-g';
    g.setAttribute('aria-hidden', 'true');
    g.textContent = '▾';
    var t = document.createElement('span');
    t.className = 't';
    t.textContent = title;
    btn.appendChild(g);
    btn.appendChild(t);
    var rule = document.createElement('span');
    rule.className = 'cc-rule';
    rule.setAttribute('aria-hidden', 'true');
    bar.appendChild(btn);
    bar.appendChild(rule);
    win.insertBefore(bar, win.firstChild);
    win.classList.add('cc-win');
    if (readFolds()[title]) setFolded(win, true);
  }

  function decorateAll(scope) {
    var s = scope && scope.querySelectorAll ? scope : document;
    if (s.matches && s.matches('[data-cc-win]')) decorate(s);
    Array.prototype.forEach.call(s.querySelectorAll('[data-cc-win]'), decorate);
  }

  document.addEventListener('click', function (e) {
    if (!active()) return;
    var bar = e.target.closest && e.target.closest('.cc-win > .cc-bar');
    if (!bar) return;
    var win = bar.parentNode;
    var title = (bar.querySelector('.t') || bar).textContent.trim();
    var folded = !win.classList.contains('cc-folded');
    setFolded(win, folded);
    var f = readFolds();
    if (folded) f[title] = 1; else delete f[title];
    writeFolds(f);
  });

  // ---------------------------------------------------------------- tips
  var tip = null;
  var tipFor = null;
  function hideTip() { if (tip) tip.classList.remove('show'); tipFor = null; }
  function showTip(el) {
    if (el.hasAttribute('title')) {
      el.setAttribute('data-cc-tip', el.getAttribute('title'));
      el.removeAttribute('title');
    }
    var text = el.getAttribute('data-cc-tip');
    if (!text) return;
    if (!tip) {
      tip = document.createElement('div');
      tip.className = 'cc-spa-tip';
      tip.setAttribute('role', 'tooltip');
      document.body.appendChild(tip);
    }
    tip.textContent = text;
    tipFor = el;
    var r = el.getBoundingClientRect();
    tip.classList.add('show');
    var w = tip.offsetWidth;
    var h = tip.offsetHeight;
    var x = Math.max(8, Math.min(window.innerWidth - w - 8, r.left));
    var y = r.bottom + 6;
    if (y + h > window.innerHeight - 8) y = Math.max(8, r.top - h - 6);
    tip.style.left = x + 'px';
    tip.style.top = y + 'px';
  }
  function tipTarget(t) { return t && t.closest ? t.closest('[title], [data-cc-tip]') : null; }
  document.addEventListener('mouseover', function (e) {
    if (!active()) return;
    var el = tipTarget(e.target);
    if (el && el !== tipFor) showTip(el); else if (!el) hideTip();
  });
  document.addEventListener('click', function (e) {
    if (!active()) return;
    var el = tipTarget(e.target);
    var coarse = window.matchMedia && window.matchMedia('(pointer: coarse)').matches;
    if (el && coarse && !isControl(el) && !el.closest('input, select, textarea, label')) {
      if (tipFor === el) hideTip(); else showTip(el);
      return;
    }
    if (tipFor && el !== tipFor) hideTip();
  });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') hideTip(); });
  window.addEventListener('scroll', hideTip, { passive: true });

  function restoreTitles() {
    Array.prototype.forEach.call(document.querySelectorAll('[data-cc-tip]'), function (el) {
      if (!el.hasAttribute('title')) el.setAttribute('title', el.getAttribute('data-cc-tip'));
      el.removeAttribute('data-cc-tip');
    });
    hideTip();
  }

  // ------------------------------------------------------------- confirm
  var dialog = null;
  function confirmBox(question) {
    if (!active() || typeof HTMLDialogElement === 'undefined') {
      return Promise.resolve(typeof window.confirm === 'function' && window.confirm(question));
    }
    if (!dialog) {
      dialog = document.createElement('dialog');
      dialog.className = 'cc-spa-dialog';
      var form = document.createElement('form');
      form.method = 'dialog';
      var q = document.createElement('p');
      q.className = 'cc-spa-q';
      var row = document.createElement('div');
      row.className = 'cc-spa-acts';
      var cancel = document.createElement('button');
      cancel.value = 'cancel';
      cancel.className = 'cc-spa-key';
      cancel.textContent = 'Cancel';
      cancel.autofocus = true;
      var ok = document.createElement('button');
      ok.value = 'ok';
      ok.className = 'cc-spa-key primary';
      ok.textContent = 'Go ahead';
      row.appendChild(cancel);
      row.appendChild(ok);
      form.appendChild(q);
      form.appendChild(row);
      dialog.appendChild(form);
      document.body.appendChild(dialog);
    }
    dialog.querySelector('.cc-spa-q').textContent = question;
    return new Promise(function (resolve) {
      var done = function () {
        dialog.removeEventListener('close', done);
        resolve(dialog.returnValue === 'ok');
      };
      dialog.returnValue = '';
      dialog.addEventListener('close', done);
      dialog.showModal();
    });
  }

  // ---------------------------------------------------------- the switch
  function apply() {
    if (!document.body) return;
    if (active()) {
      decorateAll(document);
      rewrite(document.body);
      if (!observer) {
        observer = new MutationObserver(function (ms) {
          if (!active()) return;
          ms.forEach(function (m) {
            if (m.type === 'characterData') { rewriteNode(m.target); return; }
            m.addedNodes.forEach(function (n) {
              if (n.nodeType === 1) decorateAll(n);
              rewrite(n);
            });
          });
        });
        observer.observe(document.body, { childList: true, subtree: true, characterData: true });
      }
    } else {
      restoreText();
      restoreTitles();
    }
  }

  new MutationObserver(apply).observe(root, { attributes: true, attributeFilter: ['class'] });
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', apply);
  else apply();

  window.ccSpa = { active: active, confirm: confirmBox, label: label, inline: inline, sentence: sentence };
})();
