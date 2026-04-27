/* =========================================================
   The Geneva Reporter · Skeleton search app
   Vanilla JS, no dependencies. Substring search for parity
   with the existing Flask app; FlexSearch comes in step 4+.
   ========================================================= */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

// ─────────── State ───────────
const state = {
  manifest: null,
  paragraphs: [],
  documents: new Map(),
  facets: null,
  scope: 'gc',         // 'gc' | 'sp' | 'all'
  query: '',
  filters: {
    committees: new Set(),
    labels: new Set(),
    labelsMode: 'any',     // 'any' | 'all' — match-mode for concerned groups
    yearMin: null,
    yearMax: null,
  },
  results: [],
  activeId: null,
  bannerShownForSp: false,
};

const DATA_BASE = './';      // corpus.json etc. live alongside index.html
const RESULT_LIMIT = 200;    // render cap; "more" hint shown when hit

// ─────────── URL state ───────────
// Short keys keep shareable URLs human-readable.
const URL_KEYS = { q: 'q', scope: 'scope', tb: 'tb', g: 'g', gm: 'gm', y1: 'y1', y2: 'y2', p: 'p' };

function encodeUrlState() {
  if (!state.facets) return;
  const u = new URLSearchParams();
  if (state.query) u.set(URL_KEYS.q, state.query);
  if (state.scope !== 'gc') u.set(URL_KEYS.scope, state.scope);
  if (state.filters.committees.size) u.set(URL_KEYS.tb, [...state.filters.committees].join('|'));
  if (state.filters.labels.size) u.set(URL_KEYS.g, [...state.filters.labels].join('|'));
  if (state.filters.labelsMode !== 'any') u.set(URL_KEYS.gm, state.filters.labelsMode);
  if (state.filters.yearMin != null && state.filters.yearMin !== state.facets.years.min) {
    u.set(URL_KEYS.y1, state.filters.yearMin);
  }
  if (state.filters.yearMax != null && state.filters.yearMax !== state.facets.years.max) {
    u.set(URL_KEYS.y2, state.filters.yearMax);
  }
  if (state.activeId) u.set(URL_KEYS.p, state.activeId);
  const qs = u.toString();
  const next = qs ? `${window.location.pathname}?${qs}` : window.location.pathname;
  history.replaceState(null, '', next);
}

function decodeUrlState() {
  const u = new URLSearchParams(window.location.search);
  const split = (key) => (u.get(URL_KEYS[key]) || '').split('|').filter(Boolean);
  return {
    query: u.get(URL_KEYS.q) || '',
    scope: u.get(URL_KEYS.scope) || 'gc',
    committees: split('tb'),
    labels: split('g'),
    labelsMode: u.get(URL_KEYS.gm) === 'all' ? 'all' : 'any',
    yearMin: u.get(URL_KEYS.y1) ? parseInt(u.get(URL_KEYS.y1)) : null,
    yearMax: u.get(URL_KEYS.y2) ? parseInt(u.get(URL_KEYS.y2)) : null,
    activeId: u.get(URL_KEYS.p) || null,
  };
}

// Debounced URL update — fires after a burst of state changes.
let urlUpdateTimer = null;
function scheduleUrlUpdate() {
  clearTimeout(urlUpdateTimer);
  urlUpdateTimer = setTimeout(encodeUrlState, 250);
}

// ─────────── Loader ───────────
const loader = $('#loader');
const loaderFill = $('#loader-fill');
const loaderMsg = $('#loader-msg');
function setProgress(pct, msg) {
  loaderFill.style.width = `${Math.min(100, Math.max(0, pct))}%`;
  if (msg) loaderMsg.textContent = msg;
}
function hideLoader() {
  loader.classList.add('hidden');
  setTimeout(() => loader.remove(), 300);
}

// ─────────── Boot ───────────
async function boot() {
  try {
    setProgress(5, 'Fetching manifest…');
    const manifest = await fetchJson(`${DATA_BASE}manifest.json`);
    state.manifest = manifest;
    paintMastFolio(manifest);

    setProgress(15, `Loading ${manifest.counts.documents} documents…`);
    const docs = await fetchJson(`${DATA_BASE}documents.json`);
    docs.forEach(d => state.documents.set(d.docId, d));

    setProgress(30, 'Loading facets…');
    state.facets = await fetchJson(`${DATA_BASE}facets.json`);

    setProgress(45, `Loading ${manifest.counts.paragraphs.toLocaleString()} paragraphs…`);
    state.paragraphs = await fetchJson(`${DATA_BASE}corpus.json`);

    setProgress(85, 'Wiring interface…');
    paintScopeCounts();
    initYearRange();
    applyUrlState(decodeUrlState());     // restore from ?q=…&scope=…&tb=… etc.
    paintCommitteeFilter(state.scope);
    paintLabelFilter();
    syncFiltersToDom();                  // checkboxes, chips and ANY/ALL toggle visuals
    bindUI();

    setProgress(100, 'Ready.');
    setTimeout(hideLoader, 250);

    runSearch();
  } catch (err) {
    loaderMsg.textContent = `Failed to load: ${err.message}`;
    loaderMsg.style.color = 'var(--garnet)';
    console.error(err);
  }
}

async function fetchJson(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url} → ${res.status}`);
  return res.json();
}

// ─────────── Masthead folio ───────────
function paintMastFolio(m) {
  const today = new Date().toLocaleDateString('en-GB', { day: '2-digit', month: 'long', year: 'numeric' }).toUpperCase();
  $('#mast-folio').textContent =
    `VOL. I · NO. 1 · ${today} · ${m.counts.paragraphs.toLocaleString()} ¶ · ${m.counts.documents} DOCUMENTS`;
  $('#foot-version').textContent = `Build ${m.version} · ${m.builtAt.split('T')[0]}`;
}

// ─────────── Scope counts ───────────
function paintScopeCounts() {
  const m = state.manifest.counts;
  $('#count-gc').textContent = m.gcDocuments;
  $('#count-sp').textContent = `${m.spDocuments} · 4 mandates`;
}

// ─────────── State restoration from URL ───────────
function applyUrlState(parsed) {
  // Scope
  const validScope = ['gc', 'sp', 'all'].includes(parsed.scope) ? parsed.scope : 'gc';
  state.scope = validScope;
  $$('.scope-opt').forEach(b => {
    const on = b.dataset.scope === validScope;
    b.classList.toggle('is-active', on);
    b.setAttribute('aria-selected', on ? 'true' : 'false');
  });
  $('#scope-meta').textContent = {
    gc:  'Treaty body output · near-hard-law',
    sp:  'Mandate-holder reports · soft law · preview',
    all: 'Combined view',
  }[validScope];

  // Query
  state.query = parsed.query;
  $('#q').value = parsed.query;

  // Committees & labels — only keep values that exist in current facets
  const validCommittees = new Set(state.facets.committees.map(c => c.value));
  const validLabels = new Set(state.facets.labels.map(l => l.value));
  state.filters.committees = new Set(parsed.committees.filter(c => validCommittees.has(c)));
  state.filters.labels = new Set(parsed.labels.filter(l => validLabels.has(l)));
  state.filters.labelsMode = parsed.labelsMode;

  // Year range
  const { min, max } = state.facets.years;
  state.filters.yearMin = parsed.yearMin != null ? Math.max(min, Math.min(max, parsed.yearMin)) : min;
  state.filters.yearMax = parsed.yearMax != null ? Math.max(min, Math.min(max, parsed.yearMax)) : max;
  if (state.filters.yearMin > state.filters.yearMax) {
    [state.filters.yearMin, state.filters.yearMax] = [state.filters.yearMax, state.filters.yearMin];
  }
  $('#year-min').value = state.filters.yearMin;
  $('#year-max').value = state.filters.yearMax;
  paintYearFill();

  // Active paragraph
  state.activeId = parsed.activeId;
}

function syncFiltersToDom() {
  // Label checkboxes
  $$('#filter-labels input[type=checkbox]').forEach(cb => {
    const labelEl = cb.closest('label');
    const value = labelEl?.querySelector('span')?.textContent;
    cb.checked = value ? state.filters.labels.has(value) : false;
  });
  // ANY / ALL toggle
  $$('#labels-mode .aa-opt').forEach(b => {
    b.classList.toggle('is-active', b.dataset.mode === state.filters.labelsMode);
  });
  // Committee chips already get .on applied during render via paintCommitteeChips
}

// ─────────── Facets / Filters UI ───────────
function paintCommitteeFilter(scope) {
  const tbHost = $('#filter-committees');
  const spHost = $('#filter-mandates');
  const subSection = $('#filter-bodies-sp');
  const sectionLabel = $('#bodies-label');

  const tb = state.facets.committees.filter(c => !isSp(c.value));
  const sp = state.facets.committees.filter(c => isSp(c.value));

  tbHost.innerHTML = '';
  spHost.innerHTML = '';

  if (scope === 'gc') {
    sectionLabel.textContent = 'Treaty bodies';
    subSection.hidden = true;
    paintCommitteeChips(tbHost, tb);
  } else if (scope === 'sp') {
    sectionLabel.textContent = 'Mandates';
    subSection.hidden = true;
    paintCommitteeChips(tbHost, sp);
  } else {
    sectionLabel.textContent = 'Treaty bodies';
    subSection.hidden = false;
    paintCommitteeChips(tbHost, tb);
    paintCommitteeChips(spHost, sp);
  }
}

function paintCommitteeChips(container, items) {
  for (const { value, count } of items) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'chip';
    if (isSp(value)) b.classList.add('sp-chip');
    if (state.filters.committees.has(value)) b.classList.add('on');
    b.dataset.committee = value;
    b.innerHTML = `${escape(value)} <span class="dim">${count.toLocaleString()}</span>`;
    b.addEventListener('click', () => {
      if (state.filters.committees.has(value)) state.filters.committees.delete(value);
      else state.filters.committees.add(value);
      b.classList.toggle('on');
      runSearch();
    });
    container.appendChild(b);
  }
}

function paintLabelFilter() {
  const lblHost = $('#filter-labels');
  lblHost.innerHTML = '';
  for (const { value, count } of state.facets.labels) {
    const id = `lbl-${value.replace(/[^a-z0-9]+/gi, '-').toLowerCase()}`;
    const wrap = document.createElement('label');
    wrap.innerHTML = `
      <input type="checkbox" id="${id}" />
      <span>${escape(value)}</span>
      <span class="count">${count.toLocaleString()}</span>
    `;
    wrap.querySelector('input').addEventListener('change', e => {
      if (e.target.checked) state.filters.labels.add(value);
      else state.filters.labels.delete(value);
      runSearch();
    });
    lblHost.appendChild(wrap);
  }
}

function initYearRange() {
  const { min, max } = state.facets.years;
  state.filters.yearMin = min;
  state.filters.yearMax = max;
  const lo = $('#year-min'), hi = $('#year-max');
  lo.min = hi.min = min;
  lo.max = hi.max = max;
  lo.step = hi.step = 1;
  lo.value = min;
  hi.value = max;
  paintYearFill();
}

// ─────────── UI bindings ───────────
function bindUI() {
  // Search input (debounced)
  let t;
  $('#q').addEventListener('input', e => {
    clearTimeout(t);
    t = setTimeout(() => {
      state.query = e.target.value.trim();
      runSearch();
    }, 180);
  });

  // Suggestions
  $$('.suggest').forEach(b => b.addEventListener('click', () => {
    $('#q').value = b.dataset.q;
    state.query = b.dataset.q;
    runSearch();
  }));

  // Scope toggle — also drops committee selections that don't belong in the new scope
  $$('.scope-opt').forEach(b => b.addEventListener('click', () => {
    $$('.scope-opt').forEach(x => {
      x.classList.remove('is-active');
      x.setAttribute('aria-selected', 'false');
    });
    b.classList.add('is-active');
    b.setAttribute('aria-selected', 'true');
    state.scope = b.dataset.scope;

    // Prune committee filters that no longer belong to this scope
    const valid = scopeCommitteeSet(state.scope);
    for (const c of [...state.filters.committees]) {
      if (!valid.has(c)) state.filters.committees.delete(c);
    }
    paintCommitteeFilter(state.scope);

    const meta = {
      gc:  'Treaty body output · near-hard-law',
      sp:  'Mandate-holder reports · soft law · preview',
      all: 'Combined view',
    }[state.scope];
    $('#scope-meta').textContent = meta;

    if (state.scope === 'sp' && !state.bannerShownForSp) {
      paintScopeBanner();
      $('#scope-banner').hidden = false;
      state.bannerShownForSp = true;
    }
    runSearch();
  }));

  $('#banner-dismiss').addEventListener('click', () => {
    $('#scope-banner').hidden = true;
  });

  // Export menu — wire each format button
  $$('.export-opt').forEach(b => b.addEventListener('click', (e) => {
    e.stopPropagation();
    runExport(b.dataset.format, b);
  }));
  // Close the dropdown when clicking elsewhere
  document.addEventListener('click', (e) => {
    const menu = $('#export-menu');
    if (menu.open && !menu.contains(e.target)) menu.open = false;
  });

  // Copy permanent link to current search
  $('#copy-link').addEventListener('click', async () => {
    encodeUrlState();   // flush pending updates immediately
    const btn = $('#copy-link');
    try {
      await navigator.clipboard.writeText(window.location.href);
      btn.classList.add('is-copied');
      btn.querySelector('.copy-link-label').textContent = 'Link copied ✓';
      setTimeout(() => {
        btn.classList.remove('is-copied');
        btn.querySelector('.copy-link-label').textContent = 'Copy link';
      }, 1500);
    } catch {
      btn.querySelector('.copy-link-label').textContent = 'Press ⌘+C';
    }
  });

  // Dual-range year slider — swap-on-cross strategy
  bindYearSlider();

  // ANY / ALL match-mode toggle for concerned groups
  $$('#labels-mode .aa-opt').forEach(opt => opt.addEventListener('click', () => {
    $$('#labels-mode .aa-opt').forEach(x => x.classList.remove('is-active'));
    opt.classList.add('is-active');
    state.filters.labelsMode = opt.dataset.mode;
    runSearch();
  }));

  // Reset
  $('#reset-filters').addEventListener('click', () => {
    state.filters.committees.clear();
    state.filters.labels.clear();
    state.filters.labelsMode = 'any';
    state.filters.yearMin = state.facets.years.min;
    state.filters.yearMax = state.facets.years.max;
    $$('#filter-committees .chip, #filter-mandates .chip').forEach(c => c.classList.remove('on'));
    $$('#filter-labels input').forEach(i => i.checked = false);
    $$('#labels-mode .aa-opt').forEach(x => x.classList.toggle('is-active', x.dataset.mode === 'any'));
    $('#year-min').value = state.facets.years.min;
    $('#year-max').value = state.facets.years.max;
    paintYearFill();
    runSearch();
  });

  // Theme toggle
  $('#theme-toggle').addEventListener('click', () => {
    const cur = document.documentElement.getAttribute('data-theme');
    document.documentElement.setAttribute('data-theme', cur === 'dark' ? 'light' : 'dark');
  });
}

function scopeCommitteeSet(scope) {
  return new Set(state.facets.committees
    .filter(c => scope === 'all' ? true : scope === 'gc' ? !isSp(c.value) : isSp(c.value))
    .map(c => c.value));
}

// ─────────── Export ───────────
// Exports always reflect the current filtered/searched results, never the whole corpus.

function buildExportRows() {
  return state.results.map(({ p }, idx) => {
    const doc = state.documents.get(p.docId);
    return {
      rank: idx + 1,
      type: p.type,
      doc_id: p.docId,
      doc_name: doc?.name ?? '',
      doc_short_name: doc?.nameShort ?? '',
      signature: doc?.signature ?? '',
      committee: p.committee,
      committees: (p.committees || []).join(' · '),
      year: p.year ?? '',
      adoption_date: doc?.adoptionDate ?? '',
      mandate_holder: doc?.mandate ?? '',
      paragraph_id: p.id,
      paragraph_n: p.n ?? '',
      paragraph_text: p.text,
      labels: (p.labels || []).join('; '),
      link: doc?.link ?? '',
    };
  });
}

function timestampSlug() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}${pad(d.getMonth()+1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}`;
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 1500);
}

function csvEscape(v) {
  const s = String(v ?? '');
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

function exportCsv(rows) {
  if (!rows.length) return;
  const headers = Object.keys(rows[0]);
  const lines = [headers.join(',')];
  for (const r of rows) lines.push(headers.map(h => csvEscape(r[h])).join(','));
  // Prepend BOM so Excel detects UTF-8 correctly when opening directly.
  const blob = new Blob(['﻿', lines.join('\r\n')], { type: 'text/csv;charset=utf-8' });
  downloadBlob(blob, `geneva-reporter-${timestampSlug()}.csv`);
}

function exportJson(rows) {
  const payload = {
    generatedAt: new Date().toISOString(),
    source: 'https://lszoszk.github.io/generalcomments/',
    query: state.query,
    scope: state.scope,
    filters: {
      committees: [...state.filters.committees],
      labels: [...state.filters.labels],
      labelsMode: state.filters.labelsMode,
      yearMin: state.filters.yearMin,
      yearMax: state.filters.yearMax,
    },
    count: rows.length,
    results: rows,
  };
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
  downloadBlob(blob, `geneva-reporter-${timestampSlug()}.json`);
}

// Document-level BibTeX (one entry per document, citing all matching paragraphs as a note).
function exportBibtex(rows) {
  const byDoc = new Map();
  for (const r of rows) {
    if (!byDoc.has(r.doc_id)) byDoc.set(r.doc_id, { doc: r, paragraphs: [] });
    byDoc.get(r.doc_id).paragraphs.push(r.paragraph_n || r.paragraph_id);
  }
  const escBib = (s) => String(s ?? '').replace(/[{}\\]/g, '');
  const entries = [...byDoc.values()].map(({ doc, paragraphs }) => {
    const key = (doc.signature || doc.doc_id).replace(/[^A-Za-z0-9]+/g, '');
    const author = doc.mandate_holder
      ? escBib(doc.mandate_holder)
      : `UN Committee (${escBib(doc.committee)})`;
    return [
      `@misc{${key},`,
      `  author       = {${author}},`,
      `  title        = {${escBib(doc.doc_name)}},`,
      `  number       = {${escBib(doc.signature)}},`,
      `  year         = {${doc.year}},`,
      `  url          = {${doc.link}},`,
      `  note         = {Paragraphs cited: ${paragraphs.join(', ')}}`,
      `}`,
    ].join('\n');
  });
  const blob = new Blob([entries.join('\n\n') + '\n'], { type: 'application/x-bibtex' });
  downloadBlob(blob, `geneva-reporter-${timestampSlug()}.bib`);
}

// SheetJS is large (~600 KB) — load on demand, only when user asks for XLSX.
let sheetJsPromise = null;
function loadSheetJS() {
  if (window.XLSX) return Promise.resolve(window.XLSX);
  if (sheetJsPromise) return sheetJsPromise;
  sheetJsPromise = new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = 'https://cdn.sheetjs.com/xlsx-0.20.3/package/dist/xlsx.full.min.js';
    s.onload = () => resolve(window.XLSX);
    s.onerror = () => reject(new Error('SheetJS failed to load'));
    document.head.appendChild(s);
  });
  return sheetJsPromise;
}

async function exportXlsx(rows, busyButton) {
  const XLSX = await loadSheetJS();
  const meta = [
    ['The Geneva Reporter — search export'],
    ['Generated', new Date().toISOString()],
    ['Source', 'https://lszoszk.github.io/generalcomments/'],
    ['Query', state.query || '(none)'],
    ['Scope', state.scope],
    ['Year range', `${state.filters.yearMin}–${state.filters.yearMax}`],
    ['Committees', [...state.filters.committees].join(', ') || '(any)'],
    ['Concerned groups', `${[...state.filters.labels].join(', ') || '(any)'}  [mode: ${state.filters.labelsMode.toUpperCase()}]`],
    ['Total results', rows.length],
  ];
  const wb = XLSX.utils.book_new();
  XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet(meta), 'Search');
  XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(rows), 'Results');
  XLSX.writeFile(wb, `geneva-reporter-${timestampSlug()}.xlsx`);
  if (busyButton) busyButton.classList.remove('is-busy');
}

async function runExport(format, button) {
  const rows = buildExportRows();
  if (!rows.length) {
    alert('No results to export. Refine your search and try again.');
    return;
  }
  try {
    if (format === 'csv') exportCsv(rows);
    else if (format === 'json') exportJson(rows);
    else if (format === 'bibtex') exportBibtex(rows);
    else if (format === 'xlsx') {
      button?.classList.add('is-busy');
      await exportXlsx(rows, button);
    }
  } catch (e) {
    console.error('Export failed:', e);
    alert(`Export failed: ${e.message}`);
    button?.classList.remove('is-busy');
  } finally {
    $('#export-menu').open = false;
  }
}

// Replace the banner body with the actual mandate breakdown computed from documents.
// Strips out the mandate prefix so 'SR Freedom of Expression' reads as 'Freedom of Expression'.
function paintScopeBanner() {
  const counts = new Map();
  for (const d of state.documents.values()) {
    if (d.type !== 'sp') continue;
    for (const c of d.committees || []) counts.set(c, (counts.get(c) || 0) + 1);
  }
  const cleanName = (name) => name.replace(/^S?SR\s+/, '').replace(/^Freedom of /, 'Freedom of ');
  const breakdown = [...counts.entries()]
    .sort((a, b) => b[1] - a[1])
    .map(([name, n]) => `<strong>${escape(cleanName(name))}</strong> (${n})`)
    .join(' · ');

  const banner = $('#scope-banner');
  banner.innerHTML = `
    <button class="banner-dismiss" id="banner-dismiss" aria-label="Dismiss">×</button>
    <span class="folio">SOFT-LAW PREVIEW</span>Special Procedures are reports by independent UN mandate-holders. The General Comments collection is exhaustive; this is a curated preview of <strong>${counts.size} mandates</strong> that will grow over time.
    <span class="mandate-list">${breakdown || '—'}</span>
  `;
  $('#banner-dismiss').addEventListener('click', () => { banner.hidden = true; });
}

function bindYearSlider() {
  const lo = $('#year-min'), hi = $('#year-max');
  const onInput = (which) => {
    let loV = +lo.value, hiV = +hi.value;
    if (loV > hiV) {
      // Don't let the moving handle cross the other one — clamp instead.
      if (which === 'lo') { loV = hiV; lo.value = loV; }
      else                 { hiV = loV; hi.value = hiV; }
    }
    state.filters.yearMin = loV;
    state.filters.yearMax = hiV;
    paintYearFill();
  };
  lo.addEventListener('input', () => onInput('lo'));
  hi.addEventListener('input', () => onInput('hi'));
  // Only run search when the user releases — keeps drag smooth.
  lo.addEventListener('change', runSearch);
  hi.addEventListener('change', runSearch);
}

function paintYearFill() {
  const { min, max } = state.facets.years;
  const span = max - min || 1;
  const left  = ((state.filters.yearMin - min) / span) * 100;
  const right = ((state.filters.yearMax - min) / span) * 100;
  const fill = $('#year-fill');
  fill.style.left = `${left}%`;
  fill.style.width = `${right - left}%`;
  $('#year-lo').textContent = state.filters.yearMin;
  $('#year-hi').textContent = state.filters.yearMax;
  $('#year-display').textContent = `${state.filters.yearMin} – ${state.filters.yearMax}`;
}

// ─────────── Query parsing ───────────
function parseQuery(raw) {
  if (!raw) return { andTerms: [], orGroups: [] };
  const lower = raw.toLowerCase();
  const phrases = [...lower.matchAll(/"([^"]+)"/g)].map(m => m[1]);
  const without = lower.replace(/"[^"]+"/g, ' ').trim();
  // OR groups: tokens separated by " or "
  const tokens = without.split(/\s+/).filter(Boolean);

  const andTerms = [...phrases];
  const orGroups = [];
  let i = 0;
  while (i < tokens.length) {
    if (i + 2 < tokens.length && tokens[i + 1] === 'or') {
      const group = [tokens[i]];
      while (i + 1 < tokens.length && tokens[i + 1] === 'or') {
        group.push(tokens[i + 2]);
        i += 2;
      }
      orGroups.push(group);
      i += 1;
    } else {
      andTerms.push(tokens[i]);
      i += 1;
    }
  }
  return { andTerms, orGroups };
}

// ─────────── Search ───────────
function runSearch() {
  scheduleUrlUpdate();
  const { andTerms, orGroups } = parseQuery(state.query);
  const f = state.filters;
  const scope = state.scope;

  const matched = [];
  for (const p of state.paragraphs) {
    if (scope === 'gc' && p.type !== 'gc') continue;
    if (scope === 'sp' && p.type !== 'sp') continue;

    if (p.year !== null) {
      if (f.yearMin && p.year < f.yearMin) continue;
      if (f.yearMax && p.year > f.yearMax) continue;
    }

    if (f.committees.size && !p.committees.some(c => f.committees.has(c))) continue;
    if (f.labels.size) {
      const pl = p.labels || [];
      if (f.labelsMode === 'all') {
        // Every selected label must be present on the paragraph
        let allOk = true;
        for (const l of f.labels) { if (!pl.includes(l)) { allOk = false; break; } }
        if (!allOk) continue;
      } else {
        // ANY: at least one selected label is present
        if (!pl.some(l => f.labels.has(l))) continue;
      }
    }

    const text = p.text.toLowerCase();
    let ok = true;
    for (const t of andTerms) {
      if (!text.includes(t)) { ok = false; break; }
    }
    if (!ok) continue;
    for (const grp of orGroups) {
      if (!grp.some(t => text.includes(t))) { ok = false; break; }
    }
    if (!ok) continue;

    // Score: count of total occurrences across all terms, weighted by phrase length
    let score = 0;
    for (const t of [...andTerms, ...orGroups.flat()]) {
      if (!t) continue;
      const occ = countOccurrences(text, t);
      score += occ * (1 + Math.log2(t.length + 1));
    }
    matched.push({ p, score });
  }

  // Sort: by score desc, then by year desc as tiebreak
  matched.sort((a, b) => (b.score - a.score) || ((b.p.year || 0) - (a.p.year || 0)));

  state.results = matched;
  paintResults();
}

function countOccurrences(haystack, needle) {
  if (!needle) return 0;
  let count = 0, idx = 0;
  while ((idx = haystack.indexOf(needle, idx)) !== -1) { count++; idx += needle.length; }
  return count;
}

// ─────────── Render ───────────
function paintResults() {
  const list = $('#result-list');
  list.innerHTML = '';
  const total = state.results.length;
  const docCount = new Set(state.results.map(r => r.p.docId)).size;

  $('#result-count').textContent = `${total.toLocaleString()} ¶`;
  $('#results-title').textContent = total
    ? `${total.toLocaleString()} passages from ${docCount} document${docCount === 1 ? '' : 's'}`
    : 'No matches';
  $('#results-sub').textContent = state.query
    ? `Sorted by relevance to "${state.query}". `
    : 'Refine with the filters on the left.';
  $('#results-sub').appendChild(scopeNotice());

  const view = state.results.slice(0, RESULT_LIMIT);
  const { andTerms, orGroups } = parseQuery(state.query);
  const allTerms = [...andTerms, ...orGroups.flat()].filter(Boolean);

  view.forEach(({ p }, i) => {
    list.appendChild(renderResult(p, i + 1, allTerms));
  });

  $('#result-more').textContent = total > RESULT_LIMIT
    ? `Showing top ${RESULT_LIMIT} of ${total.toLocaleString()}. Refine your filters to narrow down.`
    : '';

  // Auto-show first result in dossier
  if (view.length && !state.activeId) {
    setActive(view[0].p.id);
  } else if (state.activeId && !view.find(r => r.p.id === state.activeId)) {
    setActive(view[0]?.p.id || null);
  } else {
    paintDossier();
  }
}

function scopeNotice() {
  const span = document.createElement('span');
  if (state.scope === 'sp') {
    span.innerHTML = ` <span class="badge badge-preview">PREVIEW</span> · soft-law preview, 4 mandates only.`;
  } else if (state.scope === 'all') {
    span.innerHTML = ` Mixed scope: General Comments + <span class="badge badge-preview">PREVIEW</span> Special Procedures.`;
  }
  return span;
}

function renderResult(p, rank, terms) {
  const doc = state.documents.get(p.docId);
  const li = document.createElement('li');
  li.className = `result fade-up ${p.type}`;
  li.dataset.paraId = p.id;
  if (p.id === state.activeId) li.classList.add('is-active');

  const badge = p.type === 'sp'
    ? '<span class="badge badge-sp">PREVIEW · SP</span>'
    : '<span class="badge badge-gc">GC</span>';

  const labelChips = (p.labels || []).slice(0, 4).map(l => `<span class="chip">${escape(l)}</span>`).join('');
  const committeeChips = p.committees.map(c => `<span class="chip ${isSp(c) ? 'sp-chip' : ''}">${escape(c)}</span>`).join('');

  li.innerHTML = `
    <div class="result-margin">
      <div class="result-rank">№ ${String(rank).padStart(2, '0')}</div>
      ${p.n != null ? `<div class="result-pn">¶${p.n}</div>` : ''}
    </div>
    <div class="result-body">
      <div class="result-headline">
        ${badge}
        <span class="result-doc">${escape(doc?.nameShort || doc?.name || p.docId)}</span>
        <span class="result-spacer"></span>
        <span class="folio">${doc?.year ?? ''}</span>
      </div>
      <p class="result-text">${highlight(p.text, terms)}</p>
      <div class="result-meta">
        ${committeeChips}
        ${labelChips}
      </div>
    </div>
    <div class="result-aside">
      <div class="folio">Source</div>
      <div class="sig">${escape(doc?.signature || '—')}</div>
    </div>
  `;
  li.addEventListener('click', () => setActive(p.id));
  return li;
}

function isSp(committee) {
  return committee.startsWith('SR ') || committee.startsWith('SSR');
}

function setActive(id) {
  state.activeId = id;
  $$('.result').forEach(el => {
    el.classList.toggle('is-active', el.dataset.paraId === id);
  });
  paintDossier();
  scheduleUrlUpdate();
}

function paintDossier() {
  const host = $('#dossier');
  if (!state.activeId) {
    host.innerHTML = `
      <div class="dossier-empty">
        <div class="folio garnet">CASE NOTE</div>
        <p class="serif" style="font-style: italic; color: var(--ink-3);">
          Click a paragraph to see its document context.
        </p>
      </div>`;
    return;
  }
  const para = state.paragraphs.find(p => p.id === state.activeId);
  if (!para) return;
  const doc = state.documents.get(para.docId);
  const isSpDoc = para.type === 'sp';
  const { andTerms, orGroups } = parseQuery(state.query);
  const terms = [...andTerms, ...orGroups.flat()].filter(Boolean);

  host.innerHTML = `
    <div class="folio garnet">${isSpDoc ? 'MANDATE REPORT · PREVIEW' : 'GENERAL COMMENT'}</div>
    <h3 class="dossier-title">${escape(doc?.name || para.docId)}</h3>
    <div class="dossier-sig">${escape(doc?.signature || '')}</div>
    <div class="dossier-grid">
      <div class="dossier-dp"><div class="folio">Adopted</div><div class="v">${escape(doc?.adoptionDate || '—')}</div></div>
      <div class="dossier-dp"><div class="folio">Year</div><div class="v">${doc?.year ?? '—'}</div></div>
      <div class="dossier-dp"><div class="folio">${isSpDoc ? 'Mandate' : 'Committee'}</div><div class="v">${escape(doc?.committees?.join(' · ') || '—')}</div></div>
      <div class="dossier-dp"><div class="folio">Paragraphs</div><div class="v">${doc?.paragraphCount ?? '—'}</div></div>
      ${isSpDoc && doc?.mandate ? `<div class="dossier-dp"><div class="folio">Mandate holder</div><div class="v accent">${escape(doc.mandate)}</div></div>` : ''}
      ${isSpDoc && doc?.presented ? `<div class="dossier-dp"><div class="folio">Presented</div><div class="v">${escape(doc.presented)}</div></div>` : ''}
    </div>
    <blockquote>
      <span class="pn">¶ ${para.n ?? para.idx}</span>
      <p>${highlight(para.text, terms)}</p>
    </blockquote>
    <div class="dossier-actions">
      ${doc?.link ? `<a class="btn btn-garnet" href="${escape(doc.link)}" target="_blank" rel="noopener">Open original</a>` : ''}
      <button class="btn btn-ghost" id="copy-cite">Copy citation</button>
    </div>
  `;

  $('#copy-cite')?.addEventListener('click', () => {
    const cite = `${doc?.signature || ''} — ${doc?.name || ''}, ¶${para.n ?? para.idx} (${doc?.year ?? ''})`;
    navigator.clipboard?.writeText(cite);
    $('#copy-cite').textContent = 'Copied ✓';
    setTimeout(() => { $('#copy-cite').textContent = 'Copy citation'; }, 1200);
  });

  // Mark active in list — using data-para-id is stable across re-renders.
  $$('.result').forEach(el => {
    el.classList.toggle('is-active', el.dataset.paraId === state.activeId);
  });
}

// ─────────── Helpers ───────────
function escape(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
}

function highlight(text, terms) {
  if (!terms || !terms.length) return escape(text);
  const sorted = [...new Set(terms)].sort((a, b) => b.length - a.length);
  const escaped = escape(text);
  const re = new RegExp('(' + sorted.map(t => escapeRe(t)).join('|') + ')', 'gi');
  return escaped.replace(re, '<mark class="hl">$1</mark>');
}

function escapeRe(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// ─────────── Go ───────────
boot();
