/* "Who are you?" — one optional, anonymous click that tells us which kinds of people use the tool.
 *
 * Shown once per browser and per tool, in a corner, only after someone has actually used the page
 * (40 seconds in view and at least one click or key press). The answer is sent to GoatCounter as an
 * event "who/<tool>/<role>" and nothing else: no identifier, no cookie, no link to searches or to any
 * other page view. Answering or closing it is remembered in this browser (localStorage) so it is not
 * asked again. Not shown under Do-Not-Track / Global Privacy Control, with ?notrack=1, or to automated
 * browsers; counted only on lszoszk.github.io (elsewhere a click is only logged to the console).
 *
 * USAGE: <script src="assets/who.js" data-tool="hudoc-researcher"
 *          data-endpoint="https://hudoc-researcher.goatcounter.com/count" defer></script>
 * ?who=1 shows it at once (for testing).
 */
(function () {
  'use strict';
  var me = document.currentScript;
  if (!me) return;
  var TOOL = me.getAttribute('data-tool') || 'tool';
  var ENDPOINT = me.getAttribute('data-endpoint') || 'https://lszoszk.goatcounter.com/count';
  var BOTTOM = me.getAttribute('data-bottom');           // optional; by default it sits above any bar fixed to the bottom
  var KEY = 'who-v1:' + TOOL;
  var ROLES = [['practitioner', 'Lawyer / practitioner'], ['researcher', 'Researcher / academic'],
               ['student', 'Student'], ['ngo', 'NGO / civil society'],
               ['institution', 'Court / public institution'], ['other', 'Other']];
  var force = /[?&]who=1\b/.test(location.search);

  function suppressed() {
    try {
      if (navigator.webdriver || /HeadlessChrome/.test(navigator.userAgent || '')) return true;
      if (navigator.globalPrivacyControl === true) return true;
      var dnt = navigator.doNotTrack || window.doNotTrack || navigator.msDoNotTrack;
      if (dnt === '1' || dnt === 'yes') return true;
      if (/[?&]notrack=1\b/.test(location.search)) return true;
    } catch (e) { return true; }
    return false;
  }
  function done() { try { return !!localStorage.getItem(KEY); } catch (e) { return true; } }
  function remember(v) { try { localStorage.setItem(KEY, v + ' ' + new Date().toISOString().slice(0, 10)); } catch (e) {} }

  if (suppressed() || (done() && !force)) return;

  function send(role) {
    var vars = { path: 'who/' + TOOL + '/' + role, title: 'Who are you: ' + role, event: true };
    if (location.hostname !== 'lszoszk.github.io') { console.info('[who] not counted off the production host:', vars.path); return; }
    var gc = window.goatcounter;
    if (gc && typeof gc.count === 'function') { try { gc.count(vars); } catch (e) {} return; }
    var s = document.createElement('script');          // the page's own counter is not loaded: load it once
    s.async = true;
    s.src = 'https://gc.zgo.at/count.js';
    s.setAttribute('data-goatcounter', ENDPOINT);
    s.setAttribute('data-goatcounter-settings', '{"no_onload":true,"no_events":true}');
    s.onload = function () { try { window.goatcounter.count(vars); } catch (e) {} };
    document.head.appendChild(s);
  }

  function bottomOffset() {
    if (BOTTOM) return BOTTOM;
    var bars = [];
    Array.prototype.forEach.call(document.querySelectorAll('body *'), function (e) {
      var st = getComputedStyle(e);
      if (st.position !== 'fixed' && st.position !== 'sticky') return;
      var r = e.getBoundingClientRect();
      if (r.height && r.height < innerHeight / 3 && r.width > innerWidth / 2) bars.push(r);
    });
    var h = 0, grew = true;                                 // bars stacked on each other from the bottom up
    while (grew) {
      grew = false;
      bars.forEach(function (r) {
        if (r.bottom >= innerHeight - h - 2 && innerHeight - r.top > h) { h = innerHeight - r.top; grew = true; }
      });
    }
    return (h + 12) + 'px';
  }

  function show() {
    if (document.getElementById('who-card')) return;
    var bottom = bottomOffset();
    var css = document.createElement('style');
    css.textContent =
      '#who-card{position:fixed;left:16px;bottom:' + bottom + ';z-index:2147483000;max-width:min(360px,calc(100vw - 32px));' +
      'background:#fff;color:#1d1d1b;border:1px solid #d9d5ca;border-radius:10px;box-shadow:0 6px 24px rgba(0,0,0,.14);' +
      'padding:12px 14px 12px;font:13.5px/1.4 system-ui,-apple-system,"Segoe UI",sans-serif}' +
      '#who-card h2{font-size:14px;margin:0 22px 2px 0;font-weight:650}#who-card p{margin:0 0 8px;color:#5b5a55;font-size:12.5px}' +
      '#who-card .who-roles{display:flex;flex-wrap:wrap;gap:6px}' +
      '#who-card .who-roles button{font:inherit;font-size:12.5px;border:1px solid #cfcabd;background:#faf9f6;color:inherit;' +
      'border-radius:999px;padding:4px 10px;cursor:pointer}#who-card .who-roles button:hover,#who-card .who-roles button:focus-visible{border-color:#7a1f2b;color:#7a1f2b}' +
      '#who-card .who-x{position:absolute;top:6px;right:8px;border:0;background:none;font-size:18px;line-height:1;color:#8a877f;cursor:pointer;padding:4px}' +
      '@media (prefers-color-scheme:dark){#who-card{background:#232321;color:#ecebe6;border-color:#3a3935}' +
      '#who-card p{color:#a9a79f}#who-card .who-roles button{background:#2c2c29;border-color:#46453f}' +
      '#who-card .who-roles button:hover,#who-card .who-roles button:focus-visible{border-color:#e07a86;color:#e07a86}}' +
      '@media print{#who-card{display:none}}';
    document.head.appendChild(css);
    var card = document.createElement('div');
    card.id = 'who-card';
    card.setAttribute('role', 'dialog');
    card.setAttribute('aria-label', 'Who are you? An optional, anonymous question');
    card.innerHTML = '<button type="button" class="who-x" aria-label="Close, do not ask again">×</button>' +
      '<h2>Who are you?</h2><p>One anonymous click helps us show funders who uses this tool. Nothing else is recorded.</p>' +
      '<div class="who-roles"></div>';
    var roles = card.querySelector('.who-roles');
    ROLES.forEach(function (r) {
      var b = document.createElement('button');
      b.type = 'button';
      b.textContent = r[1];
      b.onclick = function () {
        send(r[0]);
        remember(r[0]);
        card.innerHTML = '<p style="margin:0">Thank you!</p>';
        setTimeout(function () { card.remove(); }, 1600);
      };
      roles.appendChild(b);
    });
    function close() { remember('closed'); card.remove(); document.removeEventListener('keydown', esc); }
    function esc(e) { if (e.key === 'Escape') close(); }
    card.querySelector('.who-x').onclick = close;
    document.addEventListener('keydown', esc);
    document.body.appendChild(card);
  }

  if (force) { document.readyState === 'loading' ? document.addEventListener('DOMContentLoaded', show) : show(); return; }
  // Engaged: 40 seconds with the page in view, and at least one click or key press.
  var seen = 0, touched = false;
  ['pointerdown', 'keydown'].forEach(function (t) { addEventListener(t, function () { touched = true; }, { once: true, passive: true }); });
  var timer = setInterval(function () {
    if (document.visibilityState === 'visible') seen++;
    if (seen >= 40 && touched) { clearInterval(timer); show(); }
  }, 1000);
})();
