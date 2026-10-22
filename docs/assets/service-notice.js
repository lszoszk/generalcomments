/* Service notice for the university's preventive restriction of its web
 * services (from 21 October 2026). The wording is fixed; only the tool's name
 * and the line about what does not work vary, and both are set on the script
 * tag. The notice probes the server first and stays hidden if it answers, so
 * it disappears by itself once access is restored, without a redeploy. */
(function () {
  "use strict";
  var me = document.currentScript;
  // Not for automated browsers: the sites' test suites mock their API but not this probe, and the
  // notice would sit over the page they click through (UNHRDB's pre-push suite failed on it)
  if (!me || navigator.webdriver) return;
  var APP = me.getAttribute("data-app") || "This tool";
  var EFFECT = me.getAttribute("data-effect") || "";
  var PROBE = me.getAttribute("data-probe") || "";
  var KEY = "svc-notice-closed:2026-10-21";
  var SHOW_AFTER_MS = 1500;   // a reachable server answers well within this
  var PROBE_LIMIT_MS = 8000;

  try { if (sessionStorage.getItem(KEY) === "1") return; } catch (e) { /* private mode */ }

  var node = null, btn = null, reachable = false, closed = false, lastFocus = null;

  function close(remember) {
    if (!node) return;
    node.remove();
    node = null;
    document.removeEventListener("keydown", onKey, true);
    document.removeEventListener("focusin", onFocus, true);
    closed = true;  // a probe that fails after the reader closed it must not reopen it
    if (remember) { try { sessionStorage.setItem(KEY, "1"); } catch (e) { /* private mode */ } }
    if (lastFocus && lastFocus.focus) lastFocus.focus();
  }

  // Escape closes only the notice, not another dialog under it (on HUDOC Researcher the first-visit tour)
  function onKey(e) { if (e.key === "Escape") { e.stopPropagation(); close(true); } }
  // A dialog that opens later (the tour waits for the unreachable server first) must not take focus from it
  function onFocus(e) { if (node && !node.contains(e.target)) btn.focus(); }

  function para(text) { var p = document.createElement("p"); p.textContent = text; return p; }

  function show() {
    if (node || reachable || closed) return;
    if (!document.body) { document.addEventListener("DOMContentLoaded", show, { once: true }); return; }
    if (!document.getElementById("svcn-style")) {
      var st = document.createElement("style");
      st.id = "svcn-style";
      st.textContent =
        ".svcn-bg{position:fixed;inset:0;z-index:2147483000;display:flex;align-items:center;justify-content:center;" +
        "background:rgba(20,20,24,.45);padding:16px}" +
        ".svcn{--svcn-bg:#fffdf8;--svcn-ink:#242328;--svcn-mute:#5c5a60;--svcn-edge:#242328;--svcn-accent:#8d2f2f;" +
        "background:var(--svcn-bg);color:var(--svcn-ink);border:1px solid var(--svcn-edge);border-radius:3px;" +
        "box-shadow:0 2px 0 rgba(36,35,40,.18);max-width:520px;width:100%;max-height:85vh;overflow:auto;" +
        "padding:22px 24px 18px;font:15px/1.55 Georgia,'Times New Roman',serif}" +
        ".svcn h2{margin:0 0 10px;font:600 13px/1.3 ui-monospace,Menlo,Consolas,monospace;letter-spacing:.08em;" +
        "text-transform:uppercase;color:var(--svcn-accent)}" +
        ".svcn p{margin:0 0 10px}.svcn p.svcn-end{color:var(--svcn-mute);font-size:14px}" +
        ".svcn button{margin-top:6px;padding:7px 18px;border:1px solid var(--svcn-edge);background:transparent;" +
        "color:var(--svcn-ink);font:500 13px/1 ui-monospace,Menlo,Consolas,monospace;letter-spacing:.06em;" +
        "text-transform:uppercase;cursor:pointer;border-radius:2px}" +
        ".svcn button:hover,.svcn button:focus-visible{color:var(--svcn-accent);border-color:var(--svcn-accent)}" +
        "@media (prefers-color-scheme:dark){:root:not([data-theme=light]) .svcn{--svcn-bg:#1f1e22;--svcn-ink:#f3efe6;" +
        "--svcn-mute:#b9b4ab;--svcn-edge:#6d6a70;--svcn-accent:#e08a8a}}" +
        "[data-theme=dark] .svcn{--svcn-bg:#1f1e22;--svcn-ink:#f3efe6;--svcn-mute:#b9b4ab;--svcn-edge:#6d6a70;--svcn-accent:#e08a8a}";
      document.head.appendChild(st);
    }
    lastFocus = document.activeElement;
    node = document.createElement("div");
    node.className = "svcn-bg";
    var box = document.createElement("div");
    box.className = "svcn";
    box.setAttribute("role", "dialog");
    box.setAttribute("aria-modal", "true");
    box.setAttribute("aria-labelledby", "svcn-title");
    var h = document.createElement("h2");
    h.id = "svcn-title";
    h.textContent = "Temporary interruption";
    box.appendChild(h);
    box.appendChild(para(
      "Since 21 October 2026, Adam Mickiewicz University in Poznań, which hosts the servers of this tool, " +
      "has temporarily restricted access to its web services. According to the university, this is a preventive " +
      "step taken after reports of critical security vulnerabilities in PHP software, and it is not the result of " +
      "a detected security breach. " + APP + " does not use PHP, and the interruption is not caused by any problem " +
      "with the tool itself."));
    if (EFFECT) box.appendChild(para(EFFECT));
    var end = para("We will remove this notice as soon as access is restored.");
    end.className = "svcn-end";
    box.appendChild(end);
    btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = "Close";
    btn.addEventListener("click", function () { close(true); });
    box.appendChild(btn);
    node.appendChild(box);
    node.addEventListener("click", function (e) { if (e.target === node) close(true); });
    document.body.appendChild(node);
    document.addEventListener("keydown", onKey, true);
    document.addEventListener("focusin", onFocus, true);
    btn.focus();
  }

  // mode "no-cors": an opaque answer already means the server is reachable,
  // which is all this needs; a blocked port, a timeout and a certificate the
  // browser refuses all reject. CORS headers are therefore irrelevant here.
  if (PROBE && window.fetch && window.AbortController) {
    var ctrl = new AbortController();
    var limit = setTimeout(function () { ctrl.abort(); }, PROBE_LIMIT_MS);
    fetch(PROBE, { mode: "no-cors", cache: "no-store", signal: ctrl.signal })
      .then(function () { reachable = true; clearTimeout(limit); close(false); })
      .catch(function () { clearTimeout(limit); show(); });
  }
  setTimeout(function () { if (!reachable) show(); }, SHOW_AFTER_MS);
})();
