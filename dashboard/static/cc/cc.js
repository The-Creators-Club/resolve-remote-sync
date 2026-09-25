// The terminal look's page script (docs/UI_REDESIGN_PORT_PLAN.md 3.1, 3.2;
// phase 0, 2026-09-25). Loaded last by cc/shell.html, on terminal pages only.
//
// What it does, and the rule each part keeps:
//   folds     every .win[data-win] folds from a real button in its bar; the
//             state is per page in localStorage (ccsync.fold:<path>) and is
//             re-applied to whatever htmx settles (htmx.onLoad), so a poll
//             never unfolds or refolds a window. A fold never hides an
//             answer: a swap the user started, a deep link, a banner or a
//             one-time secret unfolds its window WITHOUT writing the store.
//   tips      one floating tip for [data-tip] and tagged state elements, on a
//             fine pointer; Escape hides it, it follows the anchor's box, and
//             a poll that removes the anchor removes the tip.
//   confirms  every hx-confirm goes through ONE modal <dialog id="cc-confirm">;
//             polls are held while it is open, the pressed button's value is
//             kept, and a source a poll re-rendered is re-found by its
//             data-confirm-key and sent once.
//   tabs      the WAI-ARIA tabs pattern, the tab holding location.hash opened
//             before anything scrolls, the last tab per page remembered
//             (ccsync.cctab:<path>, never tab_memory's ccsync.tab:).
//   hidden    html.cc-hidden while the tab is hidden, so the grain stops.
// No bench settings panel and no single-key shortcuts ship (3.2).
(function () {
  "use strict";

  var FOLD_PREFIX = "ccsync.fold:";
  var TAB_PREFIX = "ccsync.cctab:";

  function pageKey(prefix) { return prefix + location.pathname; }

  function readStore(key) {
    try {
      var raw = window.localStorage.getItem(key);
      if (!raw) return {};
      var value = JSON.parse(raw);
      return value && typeof value === "object" ? value : {};
    } catch (err) { return {}; }
  }

  function writeStore(key, value) {
    try { window.localStorage.setItem(key, JSON.stringify(value)); } catch (err) { /* blocked: a no-op */ }
  }

  // ---------------------------------------------------------------- folds
  function winKey(win) { return win.getAttribute("data-win") || ""; }

  function foldButton(win) {
    var bar = win.querySelector(":scope > .bar");
    return bar ? bar.querySelector(":scope > button.fold") : null;
  }

  function setFolded(win, folded) {
    win.classList.toggle("collapsed", !!folded);
    var btn = foldButton(win);
    if (btn) btn.setAttribute("aria-expanded", folded ? "false" : "true");
  }

  function applyFolds(root) {
    var store = readStore(pageKey(FOLD_PREFIX));
    var wins = [];
    if (root.matches && root.matches(".win[data-win]")) wins.push(root);
    if (root.querySelectorAll) {
      Array.prototype.push.apply(wins, root.querySelectorAll(".win[data-win]"));
    }
    wins.forEach(function (win) {
      if (win.hasAttribute("data-nofold")) return;
      setFolded(win, store[winKey(win)] === 1);
    });
  }

  function toggleFold(win) {
    var key = winKey(win);
    if (!key || win.hasAttribute("data-nofold")) return;
    var folded = !win.classList.contains("collapsed");
    setFolded(win, folded);
    var store = readStore(pageKey(FOLD_PREFIX));
    if (folded) store[key] = 1; else delete store[key];
    writeStore(pageKey(FOLD_PREFIX), store);
  }

  // Unfold without remembering it: an answer must be seen, but the reader's
  // choice to keep the window folded stands for the next visit.
  function unfoldHolding(el) {
    var win = el && el.closest ? el.closest(".win.collapsed") : null;
    while (win) {
      setFolded(win, false);
      win = win.parentElement ? win.parentElement.closest(".win.collapsed") : null;
    }
  }

  document.addEventListener("click", function (evt) {
    var btn = evt.target.closest && evt.target.closest(".win > .bar > button.fold");
    if (btn) {
      toggleFold(btn.closest(".win"));
      return;
    }
    // The bar is a convenience target too, never over one of its controls.
    var bar = evt.target.closest && evt.target.closest(".win > .bar");
    if (!bar || evt.target.closest("a, button, input, select, label, textarea, summary")) return;
    var win = bar.parentElement;
    if (win && win.hasAttribute("data-win")) toggleFold(win);
  });

  // ---------------------------------------------------------------- tips
  // Controls too (a11y-copy-4, UI port review 2026-09-25): a key, a tab, a
  // dock link or a field that explains itself shows the floating tip on
  // keyboard focus, and on a touch screen gets a "?" beside it (tipButton).
  var TIP_SELECTOR = "[data-tip], .tag[title], .led[title], .hud-led[title], [data-chip-detail], " +
    "a[title], button[title], [role=tab][title], label[title], select[title], input[title], textarea[title]";
  var CONTROL = "a, button, input, select, textarea, label, summary";
  // Never a "?" in the dock, a dialog or a window's own fold, and never one
  // for the "?" itself.
  var NO_TIP_BTN = ".hud, .snav, dialog, .tip-btn, button.fold, [hidden], input[type=hidden]";
  var tipSeq = 0;
  var WS = new RegExp("\\s+");
  var tipEl = null;
  var tipAnchor = null;
  var tipTimer = null;
  var focusTip = null;     // the tip anchor keyboard focus is on, if any

  function finePointer() {
    return !(window.matchMedia && window.matchMedia("(pointer: coarse)").matches);
  }

  // title -> data-tip, once, keeping it as an accessible description and
  // making a non-control reachable by keyboard (the hint sheet reads the same).
  function adoptTips(root) {
    if (!root.querySelectorAll) return;
    var list = Array.prototype.slice.call(root.querySelectorAll(TIP_SELECTOR));
    if (root.matches && root.matches(TIP_SELECTOR)) list.push(root);
    list.forEach(function (el) {
      var title = el.getAttribute("title");
      if (title && !el.hasAttribute("data-tip")) el.setAttribute("data-tip", title);
      if (title) {
        el.setAttribute("aria-description", title);
        el.removeAttribute("title");
      }
      if (!el.matches(CONTROL) && !el.hasAttribute("tabindex")) el.setAttribute("tabindex", "0");
      tipButton(el);
    });
  }

  // A touch screen shows no title and a tap on a control acts, so a control
  // that explains itself gets a "?" beside it that opens the hint sheet
  // (plan 3.2, finding 126; a11y-copy-4). Only on a coarse pointer, so a
  // desktop page's DOM is unchanged; .tip-btn is display:none elsewhere.
  function tipButton(el) {
    if (finePointer() || !el.matches(CONTROL) || !tipText(el)) return;
    if (el.closest(NO_TIP_BTN)) return;
    // an input inside its label is explained by the label's "?"
    var anchor = el.matches("input, select, textarea") && el.closest("label") ? el.closest("label") : el;
    if (anchor !== el && tipText(anchor)) return;
    var next = anchor.nextElementSibling;
    if (!el.id) el.id = "cc-tipped-" + (++tipSeq);
    if (next && next.classList.contains("tip-btn") && next.getAttribute("data-tip-for") === el.id) return;
    var name = (el.getAttribute("aria-label") || el.textContent || "").split(WS).join(" ").trim();
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "tip-btn";
    btn.setAttribute("data-tip-for", el.id);
    btn.setAttribute("aria-label", name ? "What " + name + " does" : "What this does");
    btn.textContent = "?";
    anchor.insertAdjacentElement("afterend", btn);
  }

  // The hint sheet (cc/partials/hint_sheet.html) opened for a "?": the same
  // three hooks htmx_errors.js fills for a tapped tag. Its click handler
  // closes the sheet on the next tap anywhere.
  window.ccsyncOpenHint = function (label, text) {
    var sheet = document.getElementById("chip-sheet");
    if (!sheet || !text) return false;
    var l = sheet.querySelector(".chip-sheet-label");
    var t = sheet.querySelector(".chip-sheet-text");
    if (l) l.textContent = label || "";
    if (t) t.textContent = text;
    sheet.hidden = false;
    return true;
  };

  function tipText(el) {
    return el.getAttribute("data-tip") || el.getAttribute("data-chip-detail") ||
      el.getAttribute("title") || "";
  }

  function hideTip() {
    if (tipTimer) { clearTimeout(tipTimer); tipTimer = null; }
    tipAnchor = null;
    if (tipEl) tipEl.classList.remove("show");
  }

  function showTip(el) {
    var text = tipText(el);
    if (!text) return;
    if (!tipEl) {
      tipEl = document.createElement("div");
      tipEl.className = "cc-tip";
      tipEl.setAttribute("role", "tooltip");
      tipEl.style.pointerEvents = "auto";
      tipEl.addEventListener("mouseleave", function (evt) {
        if (tipAnchor && evt.relatedTarget && tipAnchor.contains(evt.relatedTarget)) return;
        hideTip();
      });
      document.body.appendChild(tipEl);
    }
    tipAnchor = el;
    tipEl.textContent = text;
    var r = el.getBoundingClientRect();
    var left = Math.max(8, Math.min(r.left, window.innerWidth - 348));
    var top = r.bottom + 6;
    if (top + 80 > window.innerHeight) top = Math.max(8, r.top - 6 - tipEl.offsetHeight);
    tipEl.style.left = left + "px";
    tipEl.style.top = top + "px";
    tipEl.classList.add("show");
  }

  document.addEventListener("mouseover", function (evt) {
    if (!finePointer()) return;
    var el = evt.target.closest && evt.target.closest(TIP_SELECTOR);
    if (!el || el === tipAnchor) return;
    if (tipTimer) clearTimeout(tipTimer);
    tipTimer = setTimeout(function () { showTip(el); }, 250);
  });
  document.addEventListener("mouseout", function (evt) {
    if (!tipAnchor && tipTimer) { clearTimeout(tipTimer); tipTimer = null; return; }
    if (!tipAnchor) return;
    var to = evt.relatedTarget;
    if (to && (tipAnchor.contains(to) || (tipEl && tipEl.contains(to)))) return;
    if (evt.target.closest && evt.target.closest(TIP_SELECTOR) === tipAnchor) hideTip();
  });
  document.addEventListener("focusin", function (evt) {
    var el = evt.target.closest && evt.target.closest(TIP_SELECTOR);
    focusTip = el;
    if (!el) { hideTip(); return; }
    // A control's tip waits, so tabbing along a row of keys does not drop a
    // box over the next one.
    if (tipTimer) clearTimeout(tipTimer);
    tipTimer = setTimeout(function () { showTip(el); }, el.matches(CONTROL) ? 900 : 0);
  });
  document.addEventListener("focusout", function () { focusTip = null; hideTip(); });
  document.addEventListener("keydown", function (evt) {
    if (evt.key === "Escape" && tipAnchor) hideTip();
  });
  window.addEventListener("hashchange", hideTip);
  // Tabbing onto something below the fold scrolls the page AFTER focusin, so
  // a plain hide-on-scroll cancelled every keyboard tip that needed a scroll
  // (verifier, 2026-09-25). A focus tip follows its control instead.
  window.addEventListener("scroll", function () {
    var a = document.activeElement;
    if (focusTip && a && focusTip.contains(a)) {
      if (tipAnchor === focusTip) showTip(focusTip);
      return;
    }
    hideTip();
  }, { passive: true });

  // "?" beside a control, for a touch device that cannot hover (3.2).
  document.addEventListener("click", function (evt) {
    var btn = evt.target.closest && evt.target.closest(".tip-btn");
    if (!btn) return;
    var target = document.getElementById(btn.getAttribute("data-tip-for") || "");
    if (!target) return;
    evt.preventDefault();
    if (typeof window.ccsyncOpenHint === "function") {
      window.ccsyncOpenHint(target.textContent.trim(), tipText(target));
    } else {
      showTip(target);
    }
  });

  // ---------------------------------------------------------------- confirms
  var dialog = null;
  var pending = null;      // {elt, issue, key, submitter:{name, value}}
  var tempInput = null;

  function removeTemp() {
    if (tempInput && tempInput.parentNode) tempInput.parentNode.removeChild(tempInput);
    tempInput = null;
  }

  function submitterOf(elt) {
    var active = document.activeElement;
    if (elt && elt.tagName === "FORM" && active && elt.contains(active) &&
        active.matches("button[type=submit], button:not([type]), input[type=submit]") && active.name) {
      return { name: active.name, value: active.value };
    }
    var last = elt && elt.lastButtonClicked;
    if (last && last.name) return { name: last.name, value: last.value };
    return null;
  }

  function closeDialog() {
    if (dialog && dialog.open) dialog.close();
  }

  function refind(key) {
    if (!key) return null;
    var list = document.querySelectorAll("[data-confirm-key]");
    for (var i = 0; i < list.length; i++) {
      if (list[i].getAttribute("data-confirm-key") === key) return list[i];
    }
    return null;
  }

  function triggerEvent(el) {
    var trig = (el.getAttribute("hx-trigger") || "").split(/[ ,]/)[0];
    if (trig) return trig;
    if (el.tagName === "FORM") return "submit";
    if (el.matches("input, select, textarea")) return "change";
    return "click";
  }

  function addTemp(form, sub) {
    removeTemp();
    if (!form || form.tagName !== "FORM" || !sub) return;
    tempInput = document.createElement("input");
    tempInput.type = "hidden";
    tempInput.name = sub.name;
    tempInput.value = sub.value;
    form.appendChild(tempInput);
  }

  function onOk() {
    var p = pending;
    pending = null;
    closeDialog();
    if (!p) return;
    if (p.elt && p.elt.isConnected) {
      addTemp(p.elt, p.submitter);
      p.issue(true);
      if (p.elt.focus) try { p.elt.focus(); } catch (err) { /* nothing */ }
      return;
    }
    var el = refind(p.key);
    if (!el) {
      if (dialog) {
        dialog.querySelector("[data-cc-confirm-q]").textContent =
          "This changed while you were reading; nothing was sent.";
        var ok = dialog.querySelector("[data-cc-confirm-ok]");
        if (ok) ok.hidden = true;
        dialog.showModal();
      }
      return;
    }
    el.__ccConfirmed = true;
    addTemp(el, p.submitter);
    if (el.tagName === "FORM" && el.requestSubmit) {
      el.requestSubmit();
    } else if (window.htmx) {
      window.htmx.trigger(el, triggerEvent(el));
    }
    var target = el.closest(".win");
    var focusTo = el.isConnected ? el : (target ? foldButton(target) : null);
    if (focusTo && focusTo.focus) try { focusTo.focus(); } catch (err) { /* nothing */ }
  }

  function ensureDialog() {
    if (dialog) return dialog;
    dialog = document.getElementById("cc-confirm");
    if (!dialog) return null;
    var ok = dialog.querySelector("[data-cc-confirm-ok]");
    var cancel = dialog.querySelector("[data-cc-confirm-cancel]");
    if (ok) ok.addEventListener("click", function (evt) { evt.preventDefault(); onOk(); });
    if (cancel) cancel.addEventListener("click", function (evt) { evt.preventDefault(); closeDialog(); });
    dialog.addEventListener("close", function () {
      // Every close without OK: nothing is sent and nothing is left behind.
      // A checkbox source (the projects tree) has already flipped by the time
      // htmx asks, so a Cancel puts it back (home-project-3, UI port review
      // 2026-09-25): the row showed unticked for 30 s with the server
      // unchanged. onOk clears `pending` before it closes, so this is only
      // ever a Cancel or Escape.
      var p = pending;
      pending = null;
      if (p && p.elt && p.elt.isConnected && p.elt.type === "checkbox") {
        p.elt.checked = !p.elt.checked;
      }
      var okBtn = dialog.querySelector("[data-cc-confirm-ok]");
      if (okBtn) okBtn.hidden = false;
    });
    return dialog;
  }

  document.addEventListener("htmx:confirm", function (evt) {
    var d = evt.detail || {};
    var elt = d.elt;
    if (elt && elt.__ccConfirmed) {
      elt.__ccConfirmed = false;
      evt.preventDefault();
      d.issueRequest(true);
      return;
    }
    // htmx fires this on EVERY request; only a real question opens a dialog.
    if (typeof d.question !== "string" || !d.question) return;
    var dlg = ensureDialog();
    if (!dlg) return;               // no dialog on this page: htmx's own confirm
    evt.preventDefault();
    pending = { elt: elt, issue: d.issueRequest, key: elt && elt.getAttribute("data-confirm-key"),
                submitter: submitterOf(elt) };
    dlg.querySelector("[data-cc-confirm-q]").textContent = d.question;
    var okBtn = dlg.querySelector("[data-cc-confirm-ok]");
    if (okBtn) okBtn.hidden = false;
    dlg.showModal();
    var cancel = dlg.querySelector("[data-cc-confirm-cancel]");
    if (cancel) cancel.focus();
  });

  // Hold every other request while the question is open: a poll that swapped
  // the source out from under the dialog would leave OK with nothing to send.
  document.addEventListener("htmx:beforeRequest", function (evt) {
    if (dialog && dialog.open) evt.preventDefault();
  });
  document.addEventListener("htmx:afterRequest", removeTemp);

  // ---------------------------------------------------------------- tabs
  function tabsOf(list) { return Array.prototype.slice.call(list.querySelectorAll("[role=tab]")); }

  function activate(tab, remember, focus) {
    var list = tab.closest("[role=tablist]");
    if (!list) return;
    tabsOf(list).forEach(function (t) {
      var on = t === tab;
      t.setAttribute("aria-selected", on ? "true" : "false");
      t.setAttribute("tabindex", on ? "0" : "-1");
      var panel = document.getElementById(t.getAttribute("aria-controls") || "");
      if (panel) panel.hidden = !on;
    });
    if (focus) tab.focus();
    if (remember && tab.id) {
      var store = readStore(pageKey(TAB_PREFIX));
      store[list.id || "tabs"] = tab.id;
      writeStore(pageKey(TAB_PREFIX), store);
    }
  }

  function initTabs(root) {
    if (!root.querySelectorAll) return;
    var store = readStore(pageKey(TAB_PREFIX));
    root.querySelectorAll("[role=tablist]").forEach(function (list) {
      if (list.__ccTabs) return;
      list.__ccTabs = true;
      var tabs = tabsOf(list);
      tabs.forEach(function (t) {
        var panel = document.getElementById(t.getAttribute("aria-controls") || "");
        if (panel) {
          panel.setAttribute("role", "tabpanel");
          if (t.id) panel.setAttribute("aria-labelledby", t.id);
          if (!panel.hasAttribute("tabindex")) panel.setAttribute("tabindex", "0");
        }
      });
      var remembered = store[list.id || "tabs"];
      var start = (remembered && document.getElementById(remembered)) ||
        tabs.filter(function (t) { return t.getAttribute("aria-selected") === "true"; })[0] || tabs[0];
      if (start && !location.hash) activate(start, false, false);
      else if (start) activate(start, false, false);
    });
  }

  document.addEventListener("click", function (evt) {
    var tab = evt.target.closest && evt.target.closest("[role=tablist] [role=tab]");
    if (!tab) return;
    evt.preventDefault();
    activate(tab, true, false);
  });
  document.addEventListener("keydown", function (evt) {
    var tab = evt.target.closest && evt.target.closest("[role=tablist] [role=tab]");
    if (!tab) return;
    var tabs = tabsOf(tab.closest("[role=tablist]"));
    var i = tabs.indexOf(tab);
    var next = null;
    if (evt.key === "ArrowRight") next = tabs[(i + 1) % tabs.length];
    else if (evt.key === "ArrowLeft") next = tabs[(i - 1 + tabs.length) % tabs.length];
    else if (evt.key === "Home") next = tabs[0];
    else if (evt.key === "End") next = tabs[tabs.length - 1];
    if (!next) return;
    evt.preventDefault();
    activate(next, true, true);
  });

  // The tab (or pane) holding the hash opens BEFORE anything scrolls; then an
  // anchor already in the page is scrolled to, and a load-triggered one is
  // left to the afterSwap scroller.
  function openHash() {
    var id = decodeURIComponent((location.hash || "").slice(1));
    if (!id) return;
    var target = document.getElementById(id);
    if (!target) return;
    var panel = target.closest("[role=tabpanel]");
    if (panel && panel.id) {
      var tab = document.querySelector("[role=tab][aria-controls='" + panel.id + "']");
      if (tab) activate(tab, false, false);
    }
    unfoldHolding(target);
    try { target.scrollIntoView(); } catch (err) { /* nothing */ }
  }
  window.addEventListener("hashchange", openHash);
  // settings-5 (UI port review 2026-09-25): an in-page link to the hash the
  // address already carries fires no hashchange, and a tab click does not
  // clear the hash, so "AI providers" on Site's features tab (and Health's
  // "notices") worked once and then did nothing. The same hash is opened
  // here; a different one is left to hashchange.
  document.addEventListener("click", function (evt) {
    if (evt.defaultPrevented || evt.button !== 0 || evt.metaKey || evt.ctrlKey || evt.shiftKey || evt.altKey) return;
    var a = evt.target.closest && evt.target.closest("a[href^='#']");
    if (!a) return;
    var href = a.getAttribute("href") || "";
    if (href.length < 2 || href !== location.hash) return;
    evt.preventDefault();
    openHash();
  });

  // A save refusal naming a field on a hidden tab opens that tab first
  // (site_settings' refusals scroll only).
  window.ccsyncRevealField = function (el) {
    if (!el) return;
    var panel = el.closest("[role=tabpanel]");
    if (panel && panel.id) {
      var tab = document.querySelector("[role=tab][aria-controls='" + panel.id + "']");
      if (tab) activate(tab, false, false);
    }
    unfoldHolding(el);
  };

  // ---------------------------------------------------------------- htmx
  // A re-read another window's plan answer asked for (cc-plan-changed,
  // home-project-2) is a poll too: it must never unfold what the reader folded.
  var POLL_EVENTS = { "cc-plan-changed": 1 };

  function isPoll(evt) {
    var trig = evt.detail && evt.detail.requestConfig && evt.detail.requestConfig.triggeringEvent;
    if (trig && POLL_EVENTS[trig.type]) return true;
    if (!trig) {
      var elt = evt.detail && evt.detail.elt;
      var spec = elt && elt.getAttribute && (elt.getAttribute("hx-trigger") || "");
      return /\bevery\b/.test(spec || "") || /\bload\b/.test(spec || "");
    }
    return false;
  }

  function reveal(target) {
    var win = target.closest ? (target.closest(".win") || target) : target;
    try { win.scrollIntoView({ block: "start" }); } catch (err) { /* nothing */ }
    if (!target.hasAttribute("tabindex")) target.setAttribute("tabindex", "-1");
    try { target.focus({ preventScroll: true }); } catch (err) { /* nothing */ }
  }

  document.addEventListener("htmx:beforeSwap", function (evt) {
    var target = evt.detail && evt.detail.target;
    if (tipAnchor && target && target.contains(tipAnchor)) hideTip();
  });

  document.addEventListener("htmx:afterSwap", function (evt) {
    var target = evt.detail && evt.detail.target;
    if (!target) return;
    // (a) an answer to something the user did
    if (!isPoll(evt)) unfoldHolding(target);
    // (b) an answer that lands in a window of its own, far from the key that
    // asked (data-reveal, e.g. "Read the answer" into what_computers_said):
    // bring it on screen and move focus there, or on a phone nothing visible
    // changes (home-project-11, UI port review 2026-09-25).
    if (!isPoll(evt) && target.hasAttribute && target.hasAttribute("data-reveal")) reveal(target);
    // (c) a banner or refusal landing in a folded body
    if (target.querySelector && target.querySelector(".error-banner, .result-banner, .htmx-refusal")) {
      unfoldHolding(target);
    }
  });
  document.addEventListener("htmx:oobAfterSwap", function (evt) {
    var target = evt.detail && evt.detail.target;
    if (target && (target.id === "minted-secret" || (target.closest && target.closest("#minted-secret")))) {
      unfoldHolding(target);
    }
  });

  // settings-2 (UI port review 2026-09-25): a refusal drawn on a ROW can sit
  // in a folded window AND a closed <details> (Packages' "other versions
  // held"). The (c) rule above searches detail.target, which after an
  // outerHTML swap is the DETACHED old box (htmx 1.9.12 leaves it there;
  // evt.target is the new element), and it unfolds only the target's own
  // ancestors, never what holds the refusal inside it. This runs on
  // afterSettle, after onLoad's applyFolds (settle) and the details keeper
  // (afterSwap) have put back what the reader had, so neither can shut it
  // again. Every refusal found is opened up to, polls included: a refusal is
  // only ever the answer to a click.
  var REFUSALS = ".row-refusal, .error-banner, .htmx-refusal";
  document.addEventListener("htmx:afterSettle", function (evt) {
    var root = evt.detail && evt.detail.target;
    if (root && root.isConnected === false && evt.target && evt.target.nodeType === 1) root = evt.target;
    if (!root || !root.querySelectorAll) return;
    var found = Array.prototype.slice.call(root.querySelectorAll(REFUSALS));
    if (root.matches && root.matches(REFUSALS)) found.push(root);
    found.forEach(function (el) {
      var d = el.parentElement ? el.parentElement.closest("details") : null;
      while (d) {
        d.setAttribute("open", "");
        d = d.parentElement ? d.parentElement.closest("details") : null;
      }
      unfoldHolding(el);
    });
  });

  function onLoad(elt) {
    applyFolds(elt);
    adoptTips(elt);
    initTabs(elt);
  }

  if (window.htmx && window.htmx.onLoad) {
    window.htmx.onLoad(onLoad);
  } else {
    document.addEventListener("DOMContentLoaded", function () { onLoad(document.body); });
  }

  function start() {
    onLoad(document.body);
    openHash();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();

  // ---------------------------------------------------------------- hidden tab
  function hiddenClass() {
    document.documentElement.classList.toggle("cc-hidden", document.hidden);
  }
  document.addEventListener("visibilitychange", hiddenClass);
  hiddenClass();
})();
