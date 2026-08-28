// Consequence-spelled-out confirmations for the controls htmx's hx-confirm
// cannot reach (UX-9 / C-3, resilience sweep 2026-08-28).
//
// The feed policy is a <select> that submits its own form on change, so one
// arrow key used to arm "auto-publish + make current": unattended fleet-wide
// upgrades from the vendor feed, with nothing asked and nothing to undo. The
// confirm lives here rather than inline because the copy contains both kinds
// of quote, and because a select that the admin CANCELS has to be put back to
// what it was showing before.
(function () {
  "use strict";

  var CURRENT_POLICY =
    "Publish new builds automatically AND make them current? " +
    "Every editor's machine will take each new build from the vendor feed " +
    "without anyone approving it first. " +
    "Choose 'stage' if you want to test a build before the fleet gets it.";

  function onPolicyChange(evt) {
    var select = evt.target;
    if (!select || select.name !== "policy") return;
    var previous = select.getAttribute("data-previous") || "";
    if (select.value === "current" && !window.confirm(CURRENT_POLICY)) {
      // Cancelled: the select is showing a policy that is not in force, so
      // put the real one back before anything reads it.
      select.value = previous;
      return;
    }
    select.setAttribute("data-previous", select.value);
    if (select.form && select.form.requestSubmit) select.form.requestSubmit();
    else if (select.form) select.form.submit();
  }

  // Delegated: the packages panel is swapped in by htmx every 30 s, so a
  // listener bound to the element itself would survive exactly one poll.
  document.addEventListener("change", onPolicyChange);
})();
