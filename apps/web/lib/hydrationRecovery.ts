/**
 * Blank-screen recovery for a wedged React root.
 *
 * THE FAILURE. React #329 ("Unknown root exit status") is thrown from
 * `finishConcurrentRender` (react-dom 18.3.1 development build, :26026), called from
 * `performConcurrentWorkOnRoot`, running inside the Scheduler's `performWorkUntilDeadline`
 * — which has no catch, by its own comment. There is no fiber return chain, so
 * `throwException` / `captureCommitPhaseError` never run and NO ERROR BOUNDARY CAN CATCH IT,
 * `app/global-error.tsx` included. `commitRoot` is never reached, so `clearContainer`
 * (:11177) never runs and the server HTML is left exactly as it arrived. On /pay that HTML is
 * an empty <body> — the page bails out to client rendering
 * (`<template data-dgst="BAILOUT_TO_CLIENT_SIDE_RENDERING">`, zero rendered elements), so the
 * payer is left staring at white with nothing on screen and no way back but a manual reload.
 *
 * Measured on the deployed build across 71 cold runs of the reproducing arm (six
 * `document_start` browser extensions): 5.6% of loads never painted. The trigger is in the
 * extension layer, on the payer's machine — four wallets racing for `window.ethereum` plus
 * two DOM-mutating extensions. THIS DOES NOT PREVENT THE MISMATCH. It cannot: a crypto
 * gateway's users have wallet extensions by definition. It exists so that the 5.6% are
 * offered a reload instead of a white rectangle.
 *
 * WHY THIS IS NOT REACT. There is no committed tree to render into and the renderer is
 * wedged, so the fallback has to be plain DOM, installed before the failure, with no React,
 * no app components and no i18n bundle. It touches the DOM only when it decides to fire —
 * pre-rendering anything into <body> would itself be an un-hydratable node, i.e. the very bug
 * this exists to survive.
 *
 * TWO LAYERS.
 *   1. The wedged fingerprint, read off React's own FiberRoot. Fires at ~3.2s.
 *      False positives 0/62 instrumented painted runs.
 *   2. A DOM backstop: nothing rendered at all by N. Fires at 12s.
 *      False positives 0/67 painted runs.
 *
 * Full data: the D5 study, `results.md`, arms `clean` / `tronlink` / `allext` /
 * `allext-novercel` / `tail`.
 */

/**
 * The inlined recovery script, as source.
 *
 * Exported as a string rather than a function because it must run from an inline <head>
 * script before any application module evaluates — see app/layout.tsx. Keeping it as a
 * string is also what makes it testable: app/__tests__/app/hydrationRecovery.test.ts
 * evaluates this exact text in jsdom, so the tests exercise the shipped bytes rather than a
 * parallel implementation.
 *
 * Deliberately ES5 and dependency-free. It runs before the polyfill chunk.
 */
export const HYDRATION_RECOVERY_SCRIPT = `
(function () {
  "use strict";

  // ── Thresholds ───────────────────────────────────────────────────────────────
  //
  // CAVEAT — carried verbatim from the study that set these numbers. Read it before
  // changing DWELL_MS.
  //
  //   The 1.5 s dwell is only safe because layer 1 also requires that no #418/#423 has
  //   arrived since the #329. That suppression rests on one uninstrumented observation
  //   (allext-novercel-run1) in which the 418s are known to have arrived after the #329 in
  //   order, but not when. If a 418 can arrive later than the fingerprint + 1.5 s, the
  //   suppression does not fire in time and layer 1 false-positives on a page that was going
  //   to recover. Nothing in 71 runs tests this. If the suppression is ever removed, or if a
  //   false-positive is reported in the field, the dwell must go to >= 7 s — at which point
  //   layer 1 is no better than the backstop and should be deleted rather than tuned.
  //
  var DWELL_MS = 1500;     // layer 1: fingerprint must hold this long
  var BACKSTOP_MS = 12000; // layer 2: nothing rendered by here
  var TICK_MS = 250;

  var SKIP = { SCRIPT: 1, TEMPLATE: 1, STYLE: 1, LINK: 1 };

  var t0 = Date.now();
  var sawFatal = false;        // a #329 has been seen
  var retryAfterFatal = false; // a #418/#423 arrived AFTER that #329 — React is retrying
  var wedgeSince = 0;
  var shown = false;
  var timer = null;

  // ── Error stream ─────────────────────────────────────────────────────────────
  // Next's onRecoverableError (next/dist/client/on-recoverable-error.js) calls the global
  // reportError, which dispatches a real ErrorEvent, so recoverable hydration errors reach a
  // plain listener. #329 is a genuinely uncaught throw and reaches it too. Messages are
  // minified in production ("Minified React error #329"), hence the substring match.
  // Capture phase, so Next's own listener (app-index.js:35) cannot pre-empt us.
  window.addEventListener("error", function (ev) {
    var msg = "";
    try {
      msg = (ev && ev.error && ev.error.message) || (ev && ev.message) || "";
    } catch (e) {
      msg = "";
    }
    if (msg.indexOf("#329") !== -1) { sawFatal = true; return; }
    if (sawFatal && (msg.indexOf("#418") !== -1 || msg.indexOf("#423") !== -1)) {
      retryAfterFatal = true;
    }
  }, true);

  // ── Has anything rendered? ───────────────────────────────────────────────────
  function renderedCount() {
    if (!document.body) return 0;
    var all = document.body.getElementsByTagName("*");
    var n = 0;
    for (var i = 0; i < all.length; i++) {
      if (!SKIP[all[i].tagName]) n++;
    }
    return n;
  }

  // ── The FiberRoot probe ──────────────────────────────────────────────────────
  // hydrateRoot(document, ...) stores the HostRoot fiber on the container under
  // "__reactContainer$" + Math.random().toString(36).slice(2) (react-dom :11481, :11500).
  // The suffix is random per page load, so it has to be found by prefix.
  //
  // Every failure path returns a status that is NOT "wedged", which disables layer 1 and
  // leaves layer 2 to do the work. Absence must never be read as "not wedged, therefore
  // healthy" — that would silently turn the whole thing off.
  //
  //   no-key         React changed the prefix, or never hydrated this document
  //   key-but-null   a real React state: unmarkContainerAsRoot sets it to null (:11502)
  //   no-stateNode   fiber present but no FiberRoot hanging off it
  //   shape-changed  FiberRoot no longer carries finishedWork
  //   threw          anything else at all
  //
  // PREDICATE IS finishedWork != null && child == null, AND NOTHING ELSE. React has
  // completed a render and has never committed a child. Lanes are deliberately excluded:
  // suspendedLanes was 0 in one wedged run and 128 in two others, so it is not invariant.
  function probeRoot() {
    try {
      var keys = Object.keys(document);
      var key = null;
      for (var i = 0; i < keys.length; i++) {
        if (keys[i].lastIndexOf("__reactContainer$", 0) === 0) { key = keys[i]; break; }
      }
      if (key === null) return "no-key";
      var hostFiber = document[key];
      if (hostFiber === null || hostFiber === undefined || typeof hostFiber !== "object") {
        return "key-but-null";
      }
      var root = hostFiber.stateNode;
      if (root === null || root === undefined || typeof root !== "object") {
        return "no-stateNode";
      }
      if (!("finishedWork" in root)) return "shape-changed";
      return (root.finishedWork !== null && root.finishedWork !== undefined &&
              (hostFiber.child === null || hostFiber.child === undefined))
        ? "wedged"
        : "live";
    } catch (e) {
      return "threw";
    }
  }

  // ── Copy ─────────────────────────────────────────────────────────────────────
  // Static strings, no message bundle — this runs outside React and outside next-intl.
  // The five locales the product ships (i18n/routing.ts).
  var COPY = {
    en: ["This page did not finish loading.", "Reload"],
    it: ["Questa pagina non si e caricata del tutto.", "Ricarica"],
    es: ["Esta pagina no termino de cargarse.", "Recargar"],
    fr: ["Cette page n a pas fini de se charger.", "Recharger"],
    de: ["Diese Seite wurde nicht vollstandig geladen.", "Neu laden"]
  };
  // On /pay the payer must not be left thinking their money moved. At the point this fires
  // nothing has been signed and no transaction has been submitted.
  var PAY_NOTE = {
    en: "No payment has been sent. Nothing was signed or submitted.",
    it: "Nessun pagamento e stato inviato. Non hai firmato ne inviato nulla.",
    es: "No se ha enviado ningun pago. No se ha firmado ni enviado nada.",
    fr: "Aucun paiement n a ete envoye. Rien n a ete signe ni soumis.",
    de: "Es wurde keine Zahlung gesendet. Es wurde nichts signiert oder ubermittelt."
  };

  function lang() {
    var l = "";
    try { l = (navigator.language || "").slice(0, 2).toLowerCase(); } catch (e) { l = ""; }
    return COPY[l] ? l : "en";
  }

  function isPay() {
    try { return location.pathname.indexOf("/pay") === 0; } catch (e) { return false; }
  }

  // ── The fallback ─────────────────────────────────────────────────────────────
  function show(reason) {
    if (shown) return;
    shown = true;
    if (timer) { clearInterval(timer); timer = null; }
    try {
      var l = lang();
      var box = document.createElement("div");
      box.id = "rs-hydration-recovery";
      box.setAttribute("role", "alert");
      box.setAttribute("lang", l);
      box.setAttribute("data-reason", reason);
      box.style.position = "fixed";
      box.style.inset = "0";
      box.style.zIndex = "2147483647";
      box.style.display = "flex";
      box.style.flexDirection = "column";
      box.style.alignItems = "center";
      box.style.justifyContent = "center";
      box.style.gap = "16px";
      box.style.padding = "24px";
      box.style.background = "#EFEEEA";
      box.style.color = "#0A0A0A";
      box.style.font = "14px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace";
      box.style.textAlign = "center";

      var msg = document.createElement("p");
      msg.textContent = COPY[l][0];
      msg.style.margin = "0";
      msg.style.maxWidth = "34ch";
      box.appendChild(msg);

      if (isPay()) {
        var note = document.createElement("p");
        note.textContent = PAY_NOTE[l];
        note.style.margin = "0";
        note.style.maxWidth = "42ch";
        note.style.opacity = "0.65";
        box.appendChild(note);
      }

      var btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = COPY[l][1];
      btn.style.font = "inherit";
      btn.style.padding = "10px 24px";
      btn.style.borderRadius = "10px";
      btn.style.border = "1px solid rgba(10,10,10,0.25)";
      btn.style.background = "transparent";
      btn.style.color = "inherit";
      btn.style.cursor = "pointer";
      btn.onclick = function () { location.reload(); };
      box.appendChild(btn);

      (document.body || document.documentElement).appendChild(box);
    } catch (e) {
      // A fallback that throws is worse than no fallback.
    }
  }

  // ── Poll ─────────────────────────────────────────────────────────────────────
  function tick() {
    if (shown) return;
    if (renderedCount() > 0) {
      // Something painted. Nothing more to do for this document — note that on /pay the
      // first thing to paint is CheckoutSkeleton, which is the correct place to stop:
      // the user is no longer looking at nothing.
      if (timer) { clearInterval(timer); timer = null; }
      return;
    }

    var status = probeRoot();
    if (status === "wedged" && !retryAfterFatal) {
      if (wedgeSince === 0) wedgeSince = Date.now();
      else if (Date.now() - wedgeSince >= DWELL_MS) { show("wedged"); return; }
    } else {
      // Not wedged, suppressed by a retry, or the probe is unavailable — reset the dwell.
      wedgeSince = 0;
    }

    if (Date.now() - t0 >= BACKSTOP_MS) show("backstop");
  }

  timer = setInterval(tick, TICK_MS);
})();
`
