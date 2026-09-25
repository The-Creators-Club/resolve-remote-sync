// Settings > Site, the terminal look (UI redesign port, phase 4, builder
// P4a, 2026-09-25). The classic static/site_settings.js stays frozen for the
// classic page; this is its fork for templates/cc/admin_settings.html.
//
// The WRITE half is the classic file's, call for call: the same routes, the
// same bodies (PUT /api/v1/admin/site {values}, the AI provider routes of
// ai_providers.py and cli_tools.py, the import dry run, undo-last-change with
// expected_at), the same serialisation of #settings-form. The RENDER half is
// a rewrite (plan 1.3, 5.3): only the providers that are set up are listed,
// each with a manage menu; ADD NEW opens a picker and then a short wizard
// (API key: get, paste, test; CLI: allow, install, sign in, test); a
// who-answers window says which AI answers the three things that ask one.
// Import and undo ask through #site-ask instead of window.confirm.
//
// The "how to get a key" words come from the API answer (`help`, i.e.
// ai_providers.PROVIDER_HELP), never from this file.
(function () {
  "use strict";

  function $(sel, root) { return (root || document).querySelector(sel); }

  function esc(s) {
    return String(s === undefined || s === null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function csrfToken() {
    var meta = document.querySelector('meta[name="csrf"]');
    return meta ? meta.content : "";
  }

  function api(path, opts) {
    opts = opts || {};
    opts.headers = Object.assign({"X-CSRF-Token": csrfToken()}, opts.headers || {});
    if (opts.body && !(opts.headers["Content-Type"])) {
      opts.headers["Content-Type"] = "application/json";
    }
    return fetch(path, opts).then(function (resp) {
      if (!resp.ok) {
        return resp.json().catch(function () { return {detail: resp.statusText}; })
          .then(function (body) {
            var d = body && body.detail;
            if (d && typeof d !== "string") d = JSON.stringify(d);
            throw new Error(d || ("HTTP " + resp.status));
          });
      }
      return resp.status === 204 ? null : resp.json();
    });
  }

  function clock() {
    var d = new Date();
    function two(n) { return (n < 10 ? "0" : "") + n; }
    return two(d.getHours()) + ":" + two(d.getMinutes()) + ":" + two(d.getSeconds());
  }

  function agoText(iso) {
    var t = Date.parse(iso || "");
    if (isNaN(t)) return String(iso || "");
    var s = Math.max(0, Math.floor((Date.now() - t) / 1000));
    if (s < 60) return s + "s ago";
    if (s < 3600) return Math.floor(s / 60) + "m ago";
    if (s < 86400) return Math.floor(s / 3600) + "h ago";
    return Math.floor(s / 86400) + "d ago";
  }

  // One answer per line, replacing the last (ui-dash-admin-6): an old "saved"
  // can never sit beside a new refusal.
  function showResult(el, ok, message) {
    if (!el) return;
    el.className = "res" + (el.classList.contains("save-res") ? " save-res" : "") +
      (message ? (ok ? " ok" : " bad") : "");
    el.textContent = message || "";
  }

  // A key keeps its width while its label changes (nothing shifts).
  function busy(key, on) {
    if (!key) return;
    if (on) { key.style.minWidth = key.offsetWidth + "px"; key.classList.add("busy"); }
    else key.classList.remove("busy");
  }

  // ------------------------------------------------------------- the ask
  var askYes = null;
  function ask(question, yesLabel, onYes) {
    var dlg = document.getElementById("site-ask");
    if (!dlg || !dlg.showModal) {
      if (window.confirm(question)) onYes();
      return;
    }
    $("#site-ask-q").textContent = question;
    $("#site-ask-yes .t").textContent = yesLabel || "Yes";
    askYes = onYes;
    dlg.showModal();
    var no = $("#site-ask-no");
    if (no) no.focus();
  }
  function wireAsk() {
    var dlg = document.getElementById("site-ask");
    if (!dlg) return;
    $("#site-ask-no").addEventListener("click", function () { askYes = null; dlg.close(); });
    $("#site-ask-yes").addEventListener("click", function () {
      var fn = askYes;
      askYes = null;
      dlg.close();
      if (fn) fn();
    });
    dlg.addEventListener("close", function () { askYes = null; });
  }

  // ======================================================== AI providers
  var CLAUDE = ["claude_code", "anthropic_api"];
  var TONE = {
    available: "ok", not_configured: "err", not_installed: "err",
    not_signed_in: "warn", disabled_by_site: "mute", unknown: "warn"
  };
  var STATUS_TIP = {
    available: "It works: this provider can answer right now.",
    not_configured: "No key is stored for it yet.",
    not_installed: "The tool is not on this server yet.",
    not_signed_in: "The tool is installed but has no account signed in, so it cannot answer yet.",
    disabled_by_site: "CLI tools are turned off for this site, so this one is not even checked.",
    unknown: "Not checked since the server started. Test it to find out."
  };
  var ORD = ["1st", "2nd", "3rd", "4th", "5th"];

  var S = null;          // the last GET /api/v1/admin/ai-providers answer
  var addMode = "idle";  // idle | pick | wiz
  var W = null;          // the open wizard
  var menuOpen = "";     // provider whose manage menu is open
  var tests = {};        // name -> "run" | {ok, detail, s}
  var flash = "";

  function byName(n) {
    var list = (S && S.providers) || [];
    for (var i = 0; i < list.length; i++) if (list[i].name === n) return list[i];
    return null;
  }
  function help(n) { return (S && S.help && S.help[n]) || {}; }

  function isSetUp(p) {
    if (!p) return false;
    if (p.kind === "api") return !!p.key_present;
    return !!(p.installed_by_wizard || p.configured_path ||
              p.status === "available" || p.status === "not_signed_in");
  }

  function showAiError(message) {
    var el = document.getElementById("ai-error");
    if (!el) return;
    el.hidden = !message;
    el.innerHTML = message ? '<span class="grow">&#9650; ' + esc(message) + "</span>" : "";
  }

  function loadAiProviders() {
    if (!document.getElementById("ai-providers")) return Promise.resolve();
    return api("/api/v1/admin/ai-providers")
      .then(function (data) { renderAi(data); })
      .catch(function (err) { showAiError("could not read the AI providers: " + err.message); });
  }

  // A refused write puts the control back, redraws from the server, and the
  // refusal is shown AFTER the redraw (ui-dash-static-9).
  function aiRefused(message) {
    showAiError(message);
    return api("/api/v1/admin/ai-providers")
      .then(function (data) { renderAi(data); showAiError(message); },
            function () { showAiError(message); });
  }

  function renderAi(data) {
    S = data;
    showAiError("");
    drawAll();
  }

  function drawAll() {
    if (!S) return;
    drawWho();
    drawList();
    drawAdd();
    drawCli();
  }

  function tag(tone, word, solid) {
    return '<span class="tag ' + (solid ? "solid " : "") + esc(tone) + '">' + esc(word) + "</span>";
  }

  function drawWho() {
    var r = S.resolved || {};
    var yt = r.name
      ? '<span class="v"><b>' + esc(r.label) + '</b><span class="why">' + esc(r.reason) + "</span></span>"
      : '<span class="v bad"><b>no usable AI provider</b><span class="why">' + esc(r.reason || "nothing is configured") + "</span></span>";
    var cards;
    if (!r.name) {
      cards = '<span class="v bad"><b>nothing to answer</b><span class="why">' + esc(r.reason || "nothing is configured") + "</span></span>";
    } else if (CLAUDE.indexOf(r.name) >= 0) {
      cards = '<span class="v"><b>' + esc(r.label) + '</b><span class="why">the same answer, and it is Claude</span></span>';
    } else {
      cards = '<span class="v bad"><b>refused</b><span class="why">this site\'s AI provider is ' + esc(r.label) +
        ", and Timeline Cards' translate, semantic search and summaries are written for Claude. Add the Claude API, or pin Claude.</span></span>";
    }
    var cc = byName("claude_code") || {};
    var check;
    if (!S.cli_enabled) {
      check = '<span class="v"><b>cannot run</b><span class="why">Claude Code is switched off on this server (CLI tools are off for this site)</span></span>';
    } else if (cc.status === "available") {
      check = '<span class="v"><b>Claude Code</b><span class="why">always Claude Code, whatever the order or the pin say</span></span>';
    } else if (cc.status === "not_signed_in") {
      check = '<span class="v"><b>Claude Code</b><span class="why sf-hint-warn">installed but not signed in: its runs fail and mail a plain summary until it is</span></span>';
    } else {
      check = '<span class="v"><b>cannot run</b><span class="why">Claude Code is not set up on this server</span></span>';
    }
    $("#ai-resolved").innerHTML =
      '<div class="ln"><span class="k" title="The YouTube page asks an AI twice per search: once to write search terms, once to judge which results are relevant.">YouTube downloader<small>search terms, then relevance</small></span>' + yt + "</div>" +
      '<div class="ln"><span class="k" title="Timeline Cards\' translations, transcript search and section summaries. They only run on Claude (Claude Code or the Claude API).">Timeline Cards<small>translate, semantic search, summaries</small></span>' + cards + "</div>" +
      '<div class="ln"><span class="k" title="The scheduled check that reads what is open on this server and mails you what needs a person. It is switched on under Settings, Alerts.">Server check<small>on the alerts page, when it is on</small></span>' + check + "</div>";
    var meta = $("#ai-who-meta");
    if (meta) {
      meta.innerHTML = r.pinned
        ? (r.name ? "pinned to <b>" + esc(r.label) + "</b>" : '<span class="red">pinned, not available</span>')
        : "auto: first available";
    }
    var pin = document.getElementById("ai-preference");
    if (pin) {
      var pref = S.preference || "auto";
      var html = '<option value="auto">auto: first available in the order</option>';
      (S.providers || []).forEach(function (p) {
        if (!isSetUp(p) && p.name !== pref) return;
        html += '<option value="' + esc(p.name) + '">' + esc(p.rank + ". " + p.label) +
          (isSetUp(p) ? "" : " (not set up)") + "</option>";
      });
      pin.innerHTML = html;
      pin.value = pref;
      pin.dataset.server = pref;
    }
  }

  function useLine(p) {
    var r = S.resolved || {};
    if (p.status === "disabled_by_site") return "not used: CLI tools are off for this site";
    if (p.status === "not_signed_in") return "not used until it is signed in";
    if (p.status !== "available") return "not used: it cannot answer";
    if (r.name === p.name) {
      var what = CLAUDE.indexOf(p.name) >= 0 ? "YouTube downloader, Timeline Cards" : "YouTube downloader";
      return (r.pinned ? "pinned, answers " : "in use for ") + "<b>" + what + "</b>" +
        (p.name === "claude_code" ? "<b>, server check</b>" : "");
    }
    if (r.pinned) return "standing by: " + esc((byName(S.preference) || {}).label || "another provider") + " is pinned";
    if (p.name === "claude_code") return "answers the <b>server check</b>; standing by for the rest";
    return "standing by: " + esc(r.label || "another provider") + " is ahead of it in the order";
  }

  function detailLine(p) {
    if (p.kind === "api") {
      return p.key_source === "env"
        ? "key <b>" + esc(p.masked) + "</b>, set by the deployment (" + esc(p.env_var) + ")"
        : "key <b>" + esc(p.masked) + "</b>, stored on this server";
    }
    var who = p.configured_path ? "your own copy at " + esc(p.configured_path)
      : (p.installed_by_wizard ? esc(p.label + " " + (p.installed_version || "")) + ", installed by set up"
        : (p.path ? esc(p.path) : esc(p.label)));
    return who + (p.signed_in_account ? ", signed in as " + esc(p.signed_in_account) : "");
  }

  function menuHtml(p) {
    function b(act, t, sub, cls) {
      return '<button type="button" role="menuitem" data-act="' + act + '" data-n="' + esc(p.name) + '" class="' + (cls || "") + '">' +
        esc(t) + (sub ? "<small>" + esc(sub) + "</small>" : "") + "</button>";
    }
    var h = b("test", "Test", "one real call, to prove it answers now");
    h += (S.preference === p.name)
      ? b("unpin", "Unpin", "back to the order: first available answers")
      : b("pin", "Pin as preferred", "it answers everything; if it stops working nothing else is used");
    h += '<div class="sep"></div>';
    if (p.kind === "api") {
      if (p.key_source === "env") {
        h += '<div class="fixed">Set by the deployment (' + esc(p.env_var) + " in the container's environment); the value here cannot change it, and it cannot be removed from this page.</div>";
      } else {
        h += b("replace", "Replace key", "paste a new key over this one") +
          b("clear", "Remove key", "deletes the stored key from this server", "danger");
      }
    } else if (p.status === "disabled_by_site") {
      h += '<div class="fixed">CLI tools are off for this site. Turn them on under the list to use it again.</div>';
    } else {
      h += (p.signin_state === "signed_in" || p.status === "available")
        ? b("signout", "Sign out", "signs it out of its account on this server")
        : b("signin", "Finish setting up: sign in", "opens the sign-in step");
      if (p.installed_by_wizard) h += b("update", "Update", "install the publisher's newer build, checked the same way");
      h += b("path", p.configured_path ? "Change its path" : "Use my own copy", "type the full path to a copy you installed yourself");
      if (p.installed_by_wizard) h += b("remove", "Remove", "deletes it and its sign-in from this server", "danger");
    }
    return h;
  }

  function testSmall(n) {
    var t = tests[n];
    if (!t) return "<small>&nbsp;</small>";
    if (t === "run") return "<small>testing...</small>";
    return '<small class="' + (t.ok ? "ok" : "bad") + '" title="' + esc((t.ok ? "OK: " : "FAILED: ") + t.detail) + '">' +
      (t.ok ? "test ok" : "test failed") + ", " + esc(t.s) + "s</small>";
  }

  function drawList() {
    var list = document.getElementById("ai-list");
    if (!list) return;
    var set = (S.providers || []).filter(isSetUp);
    var meta = $("#ai-prov-meta");
    if (meta) meta.innerHTML = "<b>" + set.length + "</b> of " + (S.providers || []).length + " set up &middot; in order";
    if (!set.length) {
      list.innerHTML = '<div class="none"><b>No AI provider is set up.</b><span>The YouTube downloader cannot search, Timeline Cards cannot translate and the server check mails a plain summary. Add one below: an API key takes a minute.</span></div>';
      return;
    }
    list.innerHTML = set.map(function (p) {
      var tone = TONE[p.status] || "warn";
      return '<div class="prow' + (flash === p.name ? " new" : "") + '" data-row="' + esc(p.name) + '">' +
        '<span class="rk" title="Its place in the order. With nothing pinned, the first one that works answers.">' + p.rank + ".</span>" +
        '<span class="nm"><b>' + esc(p.label) + '</b><small title="' + (p.kind === "cli"
          ? "A program installed on this server and signed in with a personal subscription."
          : "A key from the provider, billed per use to your own account.") + '">' +
          (p.kind === "cli" ? "command-line tool" : "api key") + "</small></span>" +
        '<span class="st"><span title="' + esc(STATUS_TIP[p.status] || "") + '">' + tag(tone, p.status_label || p.status, tone === "err") + "</span>" + testSmall(p.name) + "</span>" +
        '<span class="dt"><span title="' + esc(p.detail || "") + '">' + detailLine(p) + '</span><span class="use">' + useLine(p) + "</span>" +
          (p.detail && p.status !== "available" ? '<span class="sf-detail">' + esc(p.detail) + "</span>" : "") + "</span>" +
        '<span class="mg"><button class="key sm" type="button" data-menu="' + esc(p.name) + '" aria-haspopup="menu" aria-expanded="' + (menuOpen === p.name) + '" title="Test it, pin it, and the rest of what you can do with this provider."><span class="t">manage &#9662;</span></button></span>' +
        '<div class="mng' + (menuOpen === p.name ? " open" : "") + '" role="menu">' + menuHtml(p) + "</div>" +
        "</div>";
    }).join("");
    flash = "";
  }

  function drawCli() {
    var box = document.getElementById("ai-cli-enabled");
    if (box) box.checked = !!S.cli_enabled;
    var tos = document.getElementById("ai-cli-tos");
    if (tos) tos.title = S.cli_tos_note || "";
    var st = document.getElementById("ai-cli-state");
    if (st) {
      st.className = "res";
      st.textContent = S.cli_enabled ? "allowed for this site"
        : "not allowed. Adding Claude Code or Codex shows the notice and asks first.";
    }
  }

  // ---------------------------------------------------------- add new
  function drawAdd() {
    var box = document.getElementById("ai-add");
    if (!box) return;
    var left = (S.providers || []).filter(function (p) { return !isSetUp(p); });
    if (addMode === "wiz" && W) { drawWizard(); return; }
    if (addMode === "pick" && left.length) {
      box.innerHTML = '<div class="wz">' +
        '<div class="wz-head"><h3><span class="p">+</span>add a provider</h3><div class="steps"><span class="s cur"><b>1</b>pick one</span><span class="s"><b>2</b>set it up</span></div></div>' +
        '<div class="pick" role="list">' + left.map(function (p) {
          var hp = help(p.name);
          return '<button type="button" data-pick="' + esc(p.name) + '" role="listitem" title="Set up ' + esc(p.label) + ": " +
            (p.kind === "api" ? "get a key, paste it, test it." : "allow CLI tools, install, sign in, test.") + '">' +
            '<span class="rk">' + p.rank + ".</span>" +
            '<span class="nm"><b>' + esc(p.label) + "</b><small>" + (p.kind === "cli" ? "command-line tool" : "api key") + "</small></span>" +
            '<span class="ds">' + esc(hp.what || "") + "<small>" + esc(hp.needs || "") + "</small></span>" +
            '<span class="go">&gt;</span></button>';
        }).join("") + "</div>" +
        '<div class="wz-foot"><span class="hint grow" style="margin:0">Listed in the order they are tried. Only the ones not set up yet are here.</span><button class="key quiet sm" type="button" data-wz="cancel"><span class="t">cancel</span></button></div>' +
        "</div>";
      return;
    }
    addMode = "idle";
    box.innerHTML = '<div class="addrow">' + (left.length
      ? '<button class="key" type="button" id="ai-add-new" title="Pick a provider that is not set up yet, then follow its few steps."><span class="t">+ add new</span></button><span>' +
        left.length + " more you can set up: " + left.map(function (p) { return esc(p.label); }).join(", ") + "</span>"
      : "<span>All five providers are set up.</span>") + "</div>";
  }

  // ---------------------------------------------------------- the wizard
  var API_STEPS = ["get a key", "paste it", "test"];
  var CLI_STEPS = ["allow cli tools", "install", "sign in", "test"];

  function stopPolling() {
    if (W && W.timer) { window.clearTimeout(W.timer); W.timer = null; }
  }

  function closeWizard() {
    stopPolling();
    W = null;
    addMode = "idle";
  }

  function openWizard(name, step, extra) {
    stopPolling();
    var p = byName(name);
    if (!p) return;
    W = Object.assign({name: name, kind: p.kind, step: step === undefined ? 0 : step,
      touched: step !== undefined, saved: false, keyErr: "", testOut: null, accepted: !!S.cli_enabled,
      fallback: false, err: "", data: null, timer: null, mode: "subscription", minH: 0,
      replace: false, manage: false}, extra || {});
    addMode = "wiz";
    menuOpen = "";
    drawAll();
    if (W.kind === "cli") refreshSetup();
    var box = document.getElementById("ai-add");
    if (box && box.getBoundingClientRect().top > window.innerHeight - 120 && box.scrollIntoView) {
      box.scrollIntoView({block: "center"});
    }
  }

  function refreshSetup() {
    if (!W || W.kind !== "cli") return Promise.resolve();
    var w = W;
    return api("/api/v1/admin/ai-providers/" + w.name + "/setup")
      .then(function (data) {
        if (W !== w) return;
        w.data = data;
        if (!w.touched) {
          var installed = !!(data.install && data.install.installed);
          w.step = !data.cli_enabled ? 0 : (!installed ? 1 : (!data.signed_in ? 2 : 3));
        }
        drawWizard();
        pollIfNeeded();
      })
      .catch(function (err) { if (W === w) { w.err = err.message; drawWizard(); } });
  }

  function pollIfNeeded() {
    if (!W || !W.data) return;
    stopPolling();
    var w = W;
    var install = w.data.install || {};
    var signin = w.data.signin || {};
    if (install.state === "running") {
      w.timer = window.setTimeout(function () {
        if (W !== w) return;
        api("/api/v1/admin/ai-providers/" + w.name + "/install-status")
          .then(function (status) {
            if (W !== w) return;
            w.data.install = status;
            if (status.state !== "running") { w.touched = true; loadAiProviders(); }
            drawWizard();
            pollIfNeeded();
          })
          .catch(function (err) { if (W === w) { w.err = err.message; drawWizard(); } });
      }, 1000);
      return;
    }
    var st = signin.state;
    if (w.step === 2 && (st === "awaiting_code" || st === "awaiting_browser" ||
        st === "starting" || st === "awaiting_url" || st === "verifying")) {
      w.timer = window.setTimeout(function () {
        if (W !== w) return;
        api("/api/v1/admin/ai-providers/" + w.name + "/signin")
          .then(function (status) {
            if (W !== w) return;
            var was = (w.data.signin || {}).state;
            w.data.signin = status;
            if (status.state === "signed_in" && was !== "signed_in") {
              w.data.signed_in = true;
              loadAiProviders();
            }
            drawWizard();
            pollIfNeeded();
          })
          .catch(function (err) { if (W === w) { w.err = err.message; drawWizard(); } });
      }, 1500);
    }
  }

  function stepsHtml(labels) {
    var h = '<span class="s done"' + (W.manage || W.replace ? "" : ' data-back-pick title="Go back and pick a different provider."') +
      "><b>&#10003;</b>pick</span>";
    labels.forEach(function (s, i) {
      h += '<span class="s ' + (i < W.step ? "done" : "") + " " + (i === W.step ? "cur" : "") + '"><b>' +
        (i < W.step ? "&#10003;" : (i + 1)) + "</b>" + esc(s) + "</span>";
    });
    return h;
  }

  function outLine(o) {
    if (!o) return '<div class="out"></div>';
    return '<div class="out ' + (o.ok ? "ok" : "bad") + '">' + esc((o.ok ? "OK: " : "FAILED: ") + o.detail + (o.s ? " (" + o.s + "s)" : "")) + "</div>";
  }

  function orderLine(p) {
    var r = S.resolved || {};
    var s = "It is <b>" + (ORD[p.rank - 1] || p.rank) + "</b> in the order. ";
    if (r.name === p.name) s += "<b>It answers from now on</b>: " + esc(r.reason) + ".";
    else if (r.name) s += esc(r.label) + " still answers first; this one stands by behind it.";
    else s += "Nothing is answering yet: test it, or pick another.";
    if (CLAUDE.indexOf(p.name) < 0) s += " Timeline Cards will not use it: it only runs on Claude.";
    if (p.name === "claude_code") s += " The server check uses it whatever the order says.";
    return s;
  }

  function apiStep(p) {
    var hp = help(p.name);
    var body = "", canNext = false;
    if (W.step === 0) {
      body = "<h4><span class=\"n\">1.</span>Get a key from " + esc(hp.vendor || p.label) + "</h4>" +
        '<ol class="sf-steps">' + (hp.steps || []).map(function (g) { return "<li>" + esc(g) + "</li>"; }).join("") + "</ol>" +
        (hp.url ? '<div class="ctl"><a class="key sm" href="' + esc(hp.url) + '" target="_blank" rel="noopener noreferrer" title="Opens ' + esc(hp.site) + ' in a new tab. Come back here with the key."><span class="t">open ' + esc(hp.site) + " &#8599;</span></a></div>" : "") +
        "<p>" + esc(hp.needs || "") + (hp.vendor ? " Any spending limit is set there, on " + esc(hp.vendor) + "'s side." : "") + "</p>";
      canNext = true;
    } else if (W.step === 1) {
      body = "<h4><span class=\"n\">2.</span>" + (W.replace ? "Paste the new key" : "Paste it here") + " " + (W.saved ? tag("ok", "saved") : "") + "</h4>" +
        '<div class="ctl"><input class="inp" id="wz-key" type="password" autocomplete="off" placeholder="' +
          esc(W.saved ? p.masked : "paste the " + p.label + " key") + '" aria-label="' + esc(p.label) + ' API key">' +
          '<button class="key primary sm" type="button" data-wz="savekey" title="Stores the key on this server. It is never shown again, only its first and last characters."><span class="t">Save key</span><span class="busy-t">saving</span></button></div>' +
        '<div class="out ' + (W.keyErr ? "bad" : (W.saved ? "ok" : "")) + '">' +
          (W.keyErr ? "&#9650; could not save the key: " + esc(W.keyErr) : (W.saved ? "Stored as <b>" + esc(p.masked) + "</b>." : "")) + "</div>" +
        "<p>Paste the key alone, with no <b>Bearer</b> in front. It travels to this server once, in the body of one request, and is kept in its own file on this server, readable only by the dashboard. From then on this page shows it masked, like <b>sk-&hellip;abcd</b>, and never sends the key back.</p>";
      canNext = W.saved;
    } else {
      body = "<h4><span class=\"n\">3.</span>Test it</h4>" +
        "<p>One real call to " + esc(hp.vendor || p.label) + " with the key, to prove it answers now. Nothing is spent beyond that one call.</p>" +
        '<div class="ctl"><button class="key primary sm" type="button" data-wz="test"><span class="t">Test key</span><span class="busy-t">testing</span></button></div>' +
        outLine(W.testOut) + "<p>" + orderLine(p) + "</p>";
      canNext = true;
    }
    return {body: body, canNext: canNext, labels: API_STEPS};
  }

  function meterHtml(pct) {
    return '<span class="sf-meter" aria-hidden="true"><span style="width:' + Math.max(0, Math.min(100, Number(pct || 0))) + '%"></span></span>';
  }
  function mib(bytes) { return (Number(bytes || 0) / 1048576).toFixed(1) + " MiB"; }

  function cliStep(p) {
    var d = W.data;
    if (!d) return {body: "<p>reading what is on this server...</p>", canNext: false, labels: CLI_STEPS};
    var body = "", canNext = false;
    var install = d.install || {};
    var signin = d.signin || {};
    if (!d.supported && d.unsupported_detail) body += '<div class="note warn"><span class="grow">' + esc(d.unsupported_detail) + "</span></div>";
    if (W.step === 0) {
      var notice = d.notice || {};
      body += "<h4><span class=\"n\">1.</span>" + esc(notice.title || "Notice") + "</h4>" +
        String(notice.text || "").split("\n\n").map(function (t) { return "<p>" + esc(t) + "</p>"; }).join("") +
        '<label class="check" title="Ticking this and pressing next turns on CLI tools for this whole site."><input type="checkbox" id="wz-ok"' + (W.accepted ? " checked" : "") +
          '><span class="g"></span><span class="l">' + esc(notice.checkbox || "") + "</span></label>" +
        '<p class="hint" style="margin:0">Accepting this notice turns on <b>AI CLI providers</b> for this site. You can turn it off again under the list.</p>';
      canNext = W.accepted;
    } else if (W.step === 1) {
      var running = install.state === "running";
      body += "<h4><span class=\"n\">2.</span>Install " + esc(d.label || p.label) + " " + (install.installed ? tag("ok", "done") : "") + "</h4>" +
        "<p>From " + esc(d.publisher || "the publisher") + ", checked against its published sha256 before anything runs. It goes into this server's data folder and nowhere else.</p>" +
        '<div class="ctl"><button class="key ' + (install.installed ? "" : "primary ") + 'sm" type="button" data-wz="install"' + (running || !d.supported ? " disabled" : "") + ' title="' +
          (install.installed ? "Downloads the publisher's newer build, checked the same way, and swaps it in." : "Downloads the publisher's build and checks it before anything runs.") + '"><span class="t">' +
          (install.state === "interrupted" ? "Try again" : (install.installed ? "Update" : "Install")) + '</span><span class="busy-t">starting</span></button></div>';
      if (running) {
        body += '<div class="out">' + esc((install.step || "working") + ": " + mib(install.bytes) + (install.total ? " of " + mib(install.total) : "") + " (" + (install.percent || 0) + "%)") + "</div>" + meterHtml(install.percent);
      } else if (install.state === "interrupted") {
        body += '<div class="note err"><span class="grow">&#9650; interrupted: ' + esc(install.error || "that install did not finish.") + "</span></div>";
      } else if (install.state === "error" && install.error) {
        body += '<div class="note err"><span class="grow">&#9650; ' + esc(install.error) + "</span></div>";
      } else if (install.installed) {
        body += '<div class="out ok">installed: <b>' + esc(install.installed_version || "") + "</b>" +
          (install.unverified ? " (the publisher had no checksum for this download; the sha256 of what arrived is recorded instead)" : "") + "</div>";
      } else if (install.detail) {
        body += '<div class="out">' + esc(install.detail) + "</div>";
      }
      body += fallbackHtml(p);
      canNext = (!!install.installed || !!p.configured_path) && !running;
    } else if (W.step === 2) {
      var done = signin.state === "signed_in" || !!d.signed_in;
      var waiting = signin.state === "awaiting_code" || signin.state === "awaiting_browser";
      var starting = signin.state === "starting" || signin.state === "awaiting_url" || signin.state === "verifying";
      body += "<h4><span class=\"n\">3.</span>Sign in to " + esc(d.label || p.label) + " " + (done ? tag("ok", "done") : "") + "</h4>";
      if (done) {
        body += "<p>Signed in" + (signin.account ? " as <b>" + esc(signin.account) + "</b>" : "") + ".</p>" +
          '<div class="ctl"><button class="key quiet sm" type="button" data-wz="signout" title="Signs this account out of the tool on this server."><span class="t">sign out</span></button></div>';
      } else {
        if ((d.modes || []).length && !waiting && !starting) {
          body += '<div class="ctl"><label class="lbl" for="wz-mode" title="Which kind of account pays: a personal or team subscription, or a console with per-use billing.">account type</label>' +
            '<select class="sel" id="wz-mode">' + d.modes.map(function (m) {
              return '<option value="' + esc(m.value) + '"' + (m.value === W.mode ? " selected" : "") + ">" + esc(m.label) + "</option>";
            }).join("") + "</select></div>";
        }
        if (waiting) {
          body += '<div class="ctl"><a class="key sm" href="' + esc(signin.url || "#") + '" target="_blank" rel="noopener noreferrer" title="Opens the publisher\'s own sign-in page in a new tab. You sign in there, not here."><span class="t">open ' + esc(d.label || p.label) + " sign-in &#8599;</span></a></div>";
          if (signin.user_code) body += '<p>Type this code on that page:</p><div class="code-big" title="A one-time code. It only works for this sign-in.">' + esc(signin.user_code) + "</div>";
          if (signin.state === "awaiting_code") {
            body += "<p>Sign in there, then paste the code it shows you.</p>" +
              '<div class="ctl"><input class="inp" id="wz-code" type="text" autocomplete="off" placeholder="paste the code from that page" aria-label="' + esc(d.label || p.label) + ' sign-in code">' +
              '<button class="key primary sm" type="button" data-wz="code"><span class="t">Submit code</span><span class="busy-t">checking</span></button></div>';
          }
          body += '<div class="out">waiting for the sign-in to finish' + (signin.expires_in ? " (" + esc(signin.expires_in) + "s left)" : "") + "</div>";
        } else if (starting) {
          body += '<div class="out">starting the sign-in</div>';
        } else {
          body += '<div class="ctl"><button class="key primary sm" type="button" data-wz="signin" title="Opens the publisher\'s own sign-in page in a new tab. You sign in there, not here."><span class="t">open ' + esc(d.label || p.label) + ' sign-in &#8599;</span><span class="busy-t">starting</span></button></div>';
          if (signin.state === "failed" || signin.state === "cancelled") {
            body += '<div class="out bad">&#9650; ' + esc(signin.detail || signin.state) + "</div>";
          }
        }
        if (waiting || starting) {
          body += '<div class="ctl"><button class="key quiet sm" type="button" data-wz="cancelsign" title="Stops this sign-in. Nothing is signed in."><span class="t">cancel the sign-in</span></button></div>';
        }
        body += '<p class="hint" style="margin:0">The sign-in window is the publisher\'s own. Or run <b>' + esc(p.login_command || "") + "</b> on the host yourself, then test.</p>";
      }
      canNext = done;
    } else {
      body += "<h4><span class=\"n\">4.</span>Test and finish</h4>" +
        "<p>" + esc((d.label || p.label) + (install.installed_version ? " " + install.installed_version : "")) + " - " + (d.signed_in ? "signed in" : "not signed in") + "</p>" +
        '<div class="ctl"><button class="key primary sm" type="button" data-wz="test"><span class="t">Test</span><span class="busy-t">testing</span></button></div>' +
        outLine(W.testOut) + "<p>" + orderLine(p) + "</p>";
      canNext = true;
    }
    return {body: body, canNext: canNext, labels: CLI_STEPS};
  }

  function fallbackHtml(p) {
    return '<details class="fold" id="wz-fb"' + (W.fallback ? " open" : "") + '>' +
      '<summary title="If you installed ' + esc(p.label) + ' on the server yourself, point this page at it instead."><span>installed it yourself? type its full path</span></summary>' +
      '<div style="display:grid;gap:8px">' +
        '<div class="ctl"><input class="inp" id="wz-path" type="text" value="' + esc(p.configured_path || "") + '" placeholder="full path to the program (blank = search PATH)" aria-label="' + esc(p.label) + ' executable path">' +
        '<button class="key sm" type="button" data-wz="path"><span class="t">Save path</span><span class="busy-t">saving</span></button></div>' +
        '<p class="hint" style="margin:0">A typed path wins over anything set up installed: you are telling this server about a copy you installed and vouch for. Sign it in on the next step, or run <b>' + esc(p.login_command || "") + "</b> on the host.</p>" +
      "</div></details>";
  }

  // Redraws keep what the admin was typing and where the caret was.
  var KEEP = ["wz-key", "wz-code", "wz-path"];

  function drawWizard() {
    var box = document.getElementById("ai-add");
    if (!box || !W) return;
    var p = byName(W.name);
    if (!p) { closeWizard(); drawAdd(); return; }
    var kept = {};
    var focused = document.activeElement && document.activeElement.id;
    KEEP.forEach(function (id) { var el = document.getElementById(id); if (el) kept[id] = el.value; });
    var fb = document.getElementById("wz-fb");
    if (fb) W.fallback = fb.open;

    var step = p.kind === "api" ? apiStep(p) : cliStep(p);
    var last = W.step === step.labels.length - 1;
    box.innerHTML = '<div class="wz">' +
      '<div class="wz-head"><h3><span class="p">+</span>' + (W.replace ? "replacing the key for " : (W.manage ? "managing " : "adding ")) + esc(p.label) + "</h3>" +
        '<div class="steps">' + stepsHtml(step.labels) + "</div></div>" +
      (W.err ? '<div class="note err" role="alert"><span class="grow">&#9650; ' + esc(W.err) + "</span></div>" : "") +
      '<div class="wz-body">' + step.body + "</div>" +
      '<div class="wz-foot">' +
        '<button class="key quiet sm" type="button" data-wz="back"' + (W.step === 0 ? ' disabled style="visibility:hidden"' : "") + '><span class="t">back</span></button>' +
        '<span class="grow"></span>' +
        '<button class="key quiet sm" type="button" data-wz="cancel" title="Closes this without going further. Anything already saved stays saved."><span class="t">cancel</span></button>' +
        '<button class="key primary sm" type="button" data-wz="' + (last ? "finish" : "next") + '"' + (step.canNext ? "" : " disabled") + '><span class="t">' + (last ? "Finish" : "Next") + '</span><span class="busy-t">working</span></button>' +
      "</div></div>";
    KEEP.forEach(function (id) {
      var el = document.getElementById(id);
      if (el && kept[id]) el.value = kept[id];
    });
    if (focused) {
      var f = document.getElementById(focused);
      if (f && box.contains(f) && f.focus) try { f.focus(); } catch (e) { /* nothing */ }
    }
    // A step never gives height back while the wizard is open (nothing shifts).
    var bodyEl = box.querySelector(".wz-body");
    if (bodyEl) { W.minH = Math.max(W.minH || 0, bodyEl.offsetHeight); bodyEl.style.minHeight = W.minH + "px"; }
  }

  function runTest(name) {
    var started = Date.now();
    tests[name] = "run";
    drawList();
    return api("/api/v1/admin/ai-providers/" + name + "/test", {method: "POST"})
      .then(function (r) {
        var out = {ok: !!r.ok, detail: r.detail || "", s: ((Date.now() - started) / 1000).toFixed(1)};
        tests[name] = out;
        return out;
      }, function (err) {
        var out = {ok: false, detail: err.message, s: ((Date.now() - started) / 1000).toFixed(1)};
        tests[name] = out;
        return out;
      })
      .then(function (out) { return loadAiProviders().then(function () { return out; }); });
  }

  function validKeyError(v) {
    if (!v) return "the key is blank";
    if (/\s/.test(v)) return "the key contains a space: paste the key alone, with no 'Bearer' prefix";
    return "";
  }

  function onWizardAction(act, key) {
    if (act === "cancel") { closeWizard(); drawAdd(); return; }
    if (!W) return;
    var w = W;
    var p = byName(w.name);
    if (!p) return;
    w.err = "";
    switch (act) {
      case "back":
        stopPolling();
        w.touched = true;
        w.step = Math.max(0, w.step - 1);
        drawWizard();
        break;
      case "next":
        if (w.kind === "cli" && w.step === 0 && !S.cli_enabled) {
          // Accepting the notice IS turning the feature on (one decision).
          busy(key, true);
          api("/api/v1/admin/site", {method: "PUT", body: JSON.stringify({values: {"features.ai_cli_providers": "1"}})})
            .then(function () { w.touched = true; w.step = 1; return loadAiProviders(); })
            .then(function () { loadSiteHistory(); return refreshSetup(); })
            .catch(function (err) { busy(key, false); w.err = err.message; drawWizard(); });
          return;
        }
        w.touched = true;
        w.step++;
        w.testOut = null;
        w.keyErr = "";
        drawWizard();
        pollIfNeeded();
        break;
      case "finish":
        closeWizard();
        flash = p.name;
        loadAiProviders();
        break;
      case "savekey": {
        var input = document.getElementById("wz-key");
        var v = ((input && input.value) || "").trim();
        var bad = validKeyError(v);
        if (bad) { w.keyErr = bad; drawWizard(); return; }
        busy(key, true);
        // The key travels in the BODY, never a query string.
        api("/api/v1/admin/ai-providers/" + p.name + "/key", {method: "PUT", body: JSON.stringify({key: v})})
          .then(function (data) {
            if (input) input.value = "";
            w.saved = true; w.keyErr = "";
            renderAi(data);
          })
          .catch(function (err) { w.keyErr = err.message; busy(key, false); drawWizard(); });
        break;
      }
      case "test":
        busy(key, true);
        runTest(p.name).then(function (out) { if (W === w) { w.testOut = out; drawWizard(); } });
        break;
      case "install":
        busy(key, true);
        api("/api/v1/admin/ai-providers/" + p.name + "/install", {method: "POST"})
          .then(function (status) {
            if (W !== w) return;
            w.touched = true;
            if (w.data) w.data.install = status;
            drawWizard();
            pollIfNeeded();
          })
          .catch(function (err) { if (W === w) { w.err = err.message; drawWizard(); } });
        break;
      case "path": {
        var pin = document.getElementById("wz-path");
        busy(key, true);
        api("/api/v1/admin/ai-providers/" + p.name + "/path", {method: "PUT", body: JSON.stringify({path: pin ? pin.value : ""})})
          .then(function (data) {
            renderAi(data);
            if (W !== w) return;
            var np = byName(w.name);
            if (np && np.configured_path) { w.touched = true; w.step = 2; }
            return refreshSetup();
          })
          .catch(function (err) { if (W === w) { w.err = "could not save the path: " + err.message; drawWizard(); } });
        break;
      }
      case "signin": {
        var modeSel = document.getElementById("wz-mode");
        if (modeSel) w.mode = modeSel.value;
        busy(key, true);
        api("/api/v1/admin/ai-providers/" + p.name + "/signin", {method: "POST", body: JSON.stringify({mode: w.mode})})
          .then(function (status) {
            if (W !== w) return;
            w.touched = true;
            if (w.data) w.data.signin = status;
            // Opened from the click's own chain: a popup blocker eats one
            // opened from a later poll.
            if (status && status.url) window.open(status.url, "_blank", "noopener");
            drawWizard();
            pollIfNeeded();
          })
          .catch(function (err) { if (W === w) { w.err = err.message; drawWizard(); } });
        break;
      }
      case "code": {
        var cin = document.getElementById("wz-code");
        var code = ((cin && cin.value) || "").trim();
        if (!code) { w.err = "that code is blank"; drawWizard(); return; }
        busy(key, true);
        // The code travels in a BODY, and this page keeps no copy of it.
        api("/api/v1/admin/ai-providers/" + p.name + "/signin/code", {method: "POST", body: JSON.stringify({code: code})})
          .then(function (status) {
            if (W !== w) return;
            if (cin) cin.value = "";
            if (w.data) w.data.signin = status;
            drawWizard();
            pollIfNeeded();
          })
          .catch(function (err) { if (W === w) { w.err = err.message; drawWizard(); } });
        break;
      }
      case "cancelsign":
        stopPolling();
        api("/api/v1/admin/ai-providers/" + p.name + "/signin/cancel", {method: "POST"})
          .then(refreshSetup)
          .catch(function (err) { if (W === w) { w.err = err.message; drawWizard(); } });
        break;
      case "signout":
        api("/api/v1/admin/ai-providers/" + p.name + "/signin", {method: "DELETE"})
          .then(function () { w.touched = true; w.step = 2; return refreshSetup(); })
          .then(loadAiProviders)
          .catch(function (err) { if (W === w) { w.err = err.message; drawWizard(); } });
        break;
    }
  }

  function onMenuAction(act, name) {
    var p = byName(name);
    if (!p) return;
    menuOpen = "";
    switch (act) {
      case "test": runTest(name); break;
      case "pin": setPreference(name); break;
      case "unpin": setPreference("auto"); break;
      case "replace": openWizard(name, 1, {replace: true}); break;
      case "clear":
        drawList();
        ask("Remove the stored " + p.label + " key from this server? The YouTube downloader will fall back to the next available provider.", "Remove", function () {
          api("/api/v1/admin/ai-providers/" + name + "/key", {method: "DELETE"})
            .then(renderAi)
            .catch(function (err) { showAiError("could not clear the key: " + err.message); });
        });
        break;
      case "signin": openWizard(name, 2, {manage: true}); break;
      case "signout":
        drawList();
        api("/api/v1/admin/ai-providers/" + name + "/signin", {method: "DELETE"})
          .then(loadAiProviders)
          .catch(function (err) { showAiError("could not sign out: " + err.message); });
        break;
      case "update": openWizard(name, 1, {manage: true}); break;
      case "path": openWizard(name, 1, {manage: true, fallback: true}); break;
      case "remove":
        drawList();
        // Says what goes, because the sign-in goes with it.
        ask("Remove " + p.label + " and its sign-in from this server? The YouTube downloader will fall back to the next available provider.", "Remove", function () {
          api("/api/v1/admin/ai-providers/" + name + "/install", {method: "DELETE"})
            .then(function () { if (W && W.name === name) closeWizard(); return loadAiProviders(); })
            .catch(function (err) { showAiError("could not remove it: " + err.message); });
        });
        break;
    }
  }

  function setPreference(value) {
    return api("/api/v1/admin/ai-providers/preference", {method: "PUT", body: JSON.stringify({preference: value})})
      .then(renderAi)
      .catch(function (err) { aiRefused("could not pin: " + err.message); });
  }

  function wireAi() {
    if (!document.getElementById("ai-providers")) return;
    document.addEventListener("click", function (evt) {
      var t = evt.target;
      if (!t || !t.closest) return;
      var m = t.closest("[data-menu]");
      if (m) { menuOpen = menuOpen === m.getAttribute("data-menu") ? "" : m.getAttribute("data-menu"); drawList(); return; }
      var a = t.closest(".mng [data-act]");
      if (a) { onMenuAction(a.getAttribute("data-act"), a.getAttribute("data-n")); return; }
      if (menuOpen && !t.closest(".mng")) { menuOpen = ""; drawList(); }
      if (t.closest("#ai-add-new")) { addMode = "pick"; drawAdd(); return; }
      var pk = t.closest("[data-pick]");
      if (pk) { openWizard(pk.getAttribute("data-pick")); return; }
      if (t.closest("[data-back-pick]") && W && !W.manage && !W.replace) {
        closeWizard(); addMode = "pick"; drawAdd(); return;
      }
      var w = t.closest("#ai-add [data-wz]");
      if (w && !w.disabled) onWizardAction(w.getAttribute("data-wz"), w);
    });
    document.addEventListener("change", function (evt) {
      var t = evt.target;
      if (!t) return;
      if (t.id === "wz-ok" && W) { W.accepted = t.checked; drawWizard(); return; }
      if (t.id === "wz-mode" && W) { W.mode = t.value; return; }
      if (t.id === "ai-preference") {
        var was = t.dataset.server || "auto";
        api("/api/v1/admin/ai-providers/preference", {method: "PUT", body: JSON.stringify({preference: t.value})})
          .then(renderAi)
          .catch(function (err) { t.value = was; aiRefused("could not pin: " + err.message); });
        return;
      }
      if (t.id === "ai-cli-enabled") {
        // A site_setting like the YouTube ones: the manifest route, never a
        // second writer. It records a site change, so the history moves too.
        var values = {"features.ai_cli_providers": t.checked ? "1" : "0"};
        api("/api/v1/admin/site", {method: "PUT", body: JSON.stringify({values: values})})
          .then(function () {
            if (!t.checked && W && W.kind === "cli") closeWizard();
            return loadAiProviders();
          })
          .then(loadSiteHistory)
          .catch(function (err) {
            t.checked = !t.checked;
            aiRefused("could not change the CLI provider setting: " + err.message);
          });
      }
    });
    document.addEventListener("keydown", function (evt) {
      if (evt.key === "Escape" && menuOpen) { menuOpen = ""; drawList(); }
    });
    loadAiProviders();
  }

  // ============================================== import, history, undo
  function importQuestion(changes) {
    var n = changes.length;
    var shown = changes.slice(0, 3).map(function (c) {
      return c.key + " from " + (c.from || "(blank)") + " to " + (c.to || "(blank)");
    });
    var text = "This will change " + n + " setting" + (n === 1 ? "" : "s") + ", including " + shown.join(", ");
    if (n > 3) text += ", and " + (n - 3) + " more";
    return text + ". Apply it?";
  }

  function runImport(text, result, key) {
    busy(key, true);
    return api("/api/v1/admin/site/import?dry_run=1", {method: "POST", body: JSON.stringify({text: text})})
      .then(function (preview) {
        busy(key, false);
        if (!preview.count) {
          showResult(result, true, "Nothing in that text differs from the current settings. Nothing was changed.");
          return;
        }
        showResult(result, true, "");
        ask(importQuestion(preview.changes), "Apply", function () {
          api("/api/v1/admin/site/import", {method: "POST", body: JSON.stringify({text: text})})
            .then(function () { window.location.reload(); })
            .catch(function (err) { showResult(result, false, "could not import: " + err.message); });
        });
      });
  }

  // Called at load AND after every write that records a site change: the
  // undo must name the entry it will revert (ui-dash-static-3), and it is
  // disarmed while a reload is out.
  function loadSiteHistory() {
    var list = document.getElementById("site-history-list");
    var undo = document.getElementById("site-undo-btn");
    var meta = document.getElementById("site-history-meta");
    if (!list) return Promise.resolve();
    if (undo) { undo.disabled = true; undo.onclick = null; }
    return api("/api/v1/admin/site/history").then(function (body) {
      var entries = body.entries || [];
      if (meta) meta.innerHTML = entries.length ? "<b>" + entries.length + "</b> recorded" : "";
      if (!entries.length) {
        list.innerHTML = '<div class="empty" style="padding:10px 0;text-align:left">No site setting changes recorded yet.</div>';
        return;
      }
      list.innerHTML = '<table class="tbl tight"><tbody>' + entries.slice(0, 5).map(function (e) {
        var count = e.count || 0;
        return "<tr><td><span class=\"hi\">" + esc(e.action || "save") + "</span> by <b>" + esc(e.actor) + "</b></td>" +
          '<td title="' + esc(e.at) + '">' + esc(agoText(e.at)) + "</td>" +
          '<td class="num">' + count + " setting" + (count === 1 ? "" : "s") + "</td></tr>";
      }).join("") + "</tbody></table>";
      if (undo) {
        var latest = entries[0];
        undo.disabled = false;
        undo.onclick = function () {
          var count = latest.count || 0;
          ask("Put back the " + count + " setting" + (count === 1 ? "" : "s") + " changed by " + latest.actor + " " +
              agoText(latest.at) + " (" + latest.at + ")?", "Undo", function () {
            var res = document.getElementById("site-undo-result");
            showResult(res, true, "");
            api("/api/v1/admin/site/undo-last-change", {method: "POST", body: JSON.stringify({expected_at: latest.at})})
              .then(function () { window.location.reload(); })
              .catch(function (err) {
                showResult(res, false, "could not undo: " + err.message);
                loadSiteHistory();
              });
          });
        };
      }
    }).catch(function (err) {
      list.textContent = "could not load change history: " + err.message;
    });
  }

  // ================================================================ save
  // Serialised exactly as the classic page does: every named element of
  // #settings-form, readonly (auto-derived) skipped, a checkbox as "1"/"0",
  // only the checked radio of a group.
  function formValues(form) {
    var values = {};
    Array.prototype.forEach.call(form.elements, function (el) {
      if (!el.name) return;
      if (el.readOnly) return;
      if (el.type === "checkbox") values[el.name] = el.checked ? "1" : "0";
      else if (el.type === "radio") { if (el.checked) values[el.name] = el.value; }
      else if (el.type === "submit" || el.type === "button") return;
      else values[el.name] = el.value;
    });
    return values;
  }

  // A refusal that names a field opens the tab that holds it.
  function revealNamedField(form, message) {
    if (!window.ccsyncRevealField) return;
    var m = String(message || "");
    for (var i = 0; i < form.elements.length; i++) {
      var el = form.elements[i];
      if (el.name && m.indexOf(el.name) >= 0) {
        window.ccsyncRevealField(el);
        return;
      }
    }
  }

  function wireSave() {
    var form = document.getElementById("settings-form");
    if (!form) return;
    form.addEventListener("submit", function (evt) {
      evt.preventDefault();
      var keys = form.querySelectorAll('button[type="submit"]');
      var lines = form.querySelectorAll(".save-res");
      Array.prototype.forEach.call(keys, function (k) { busy(k, true); });
      Array.prototype.forEach.call(lines, function (l) { showResult(l, true, "saving..."); });
      api("/api/v1/admin/site", {method: "PUT", body: JSON.stringify({values: formValues(form)})})
        .then(function () {
          Array.prototype.forEach.call(lines, function (l) { showResult(l, true, "saved at " + clock()); });
          return loadSiteHistory();
        })
        .catch(function (err) {
          Array.prototype.forEach.call(lines, function (l) { showResult(l, false, "could not save: " + err.message); });
          revealNamedField(form, err.message);
        })
        .then(function () { Array.prototype.forEach.call(keys, function (k) { busy(k, false); }); });
    });
  }

  function wireImport() {
    var form = document.getElementById("settings-import-form");
    if (!form) return;
    form.addEventListener("submit", function (evt) {
      evt.preventDefault();
      var result = document.getElementById("settings-import-result");
      var key = form.querySelector('button[type="submit"]');
      var text = (form.text.value || "").trim();
      if (!text) { showResult(result, false, "could not import: paste a site.toml first"); return; }
      runImport(form.text.value, result, key).catch(function (err) {
        busy(key, false);
        showResult(result, false, "could not import: " + err.message);
      });
    });
  }

  function init() {
    wireAsk();
    wireSave();
    wireImport();
    wireAi();
    loadSiteHistory();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();

})();
