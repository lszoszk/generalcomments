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
  paragraphById: new Map(),     // id → paragraph, for O(1) FlexSearch hydration
  documents: new Map(),
  facets: null,
  searchIndex: null,            // FlexSearch.Document instance, populated after boot
  view: 'search',               // 'search' | 'documents' | 'about' — driven by URL hash
  docsScope: 'all',             // documents-view scope: 'all' | 'gc' | 'sp'
  docsFilter: '',               // documents-view free-text filter
  scope: 'gc',         // 'gc' | 'sp' | 'all'
  resultSort: 'relevance',      // 'relevance' | 'date'
  resultGroup: 'paragraphs',    // 'paragraphs' | 'documents'
  collapsedDocGroups: new Set(),
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
const URL_KEYS = { q: 'q', scope: 'scope', tb: 'tb', g: 'g', gm: 'gm', y1: 'y1', y2: 'y2', p: 'p', sort: 'sort', group: 'group' };

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
  if (state.resultSort !== 'relevance') u.set(URL_KEYS.sort, state.resultSort);
  if (state.resultGroup !== 'paragraphs') u.set(URL_KEYS.group, state.resultGroup);
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
    resultSort: u.get(URL_KEYS.sort) || 'relevance',
    resultGroup: u.get(URL_KEYS.group) || 'paragraphs',
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

    // Hydrate id-lookup map for FlexSearch result resolution
    for (const p of state.paragraphs) state.paragraphById.set(p.id, p);

    setProgress(70, 'Building search index…');
    await ensureSearchIndex();           // FlexSearch index — IndexedDB cached if available

    setProgress(90, 'Wiring interface…');
    paintScopeCounts();
    initYearRange();
    applyUrlState(decodeUrlState());     // restore from ?q=…&scope=…&tb=… etc.
    paintCommitteeFilter(state.scope);
    paintLabelFilter();
    syncFiltersToDom();                  // checkboxes, chips and ANY/ALL toggle visuals
    bindUI();
    bindRouter();
    setView(viewFromHash());             // honor the initial hash

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

  // Results controls
  state.resultSort = ['relevance', 'date'].includes(parsed.resultSort) ? parsed.resultSort : 'relevance';
  state.resultGroup = ['paragraphs', 'documents'].includes(parsed.resultGroup) ? parsed.resultGroup : 'paragraphs';
  syncResultsControls();

  // Active paragraph
  state.activeId = parsed.activeId;
}

// ─────────── Hash router (Search / Documents / About) ───────────
const VIEWS = ['search', 'documents', 'about'];

function viewFromHash() {
  const h = window.location.hash.replace(/^#/, '');
  return VIEWS.includes(h) ? h : 'search';
}

function setView(view) {
  if (!VIEWS.includes(view)) view = 'search';
  state.view = view;
  document.body.dataset.activeView = view;

  // Active link in masthead nav
  $$('.mast-nav a').forEach(a => {
    const target = a.getAttribute('href')?.replace(/^#/, '') || 'search';
    a.classList.toggle('active', target === view);
  });

  // Lazy-paint the view-specific content
  if (view === 'documents') paintDocumentsView();
  // 'about' is static HTML, no paint needed
  // 'search' results are kept in DOM after boot, no need to repaint

  updateDocumentTitle();
}

function bindRouter() {
  window.addEventListener('hashchange', () => setView(viewFromHash()));
}

// ─────────── Documents view ───────────
function paintDocumentsView() {
  const host = $('#docs-body');
  if (!host) return;

  // Group documents by primary committee, scope-filtered
  const wantScope = state.docsScope;
  const filterText = state.docsFilter.trim().toLowerCase();

  const docs = [...state.documents.values()].filter(d => {
    if (wantScope === 'gc' && d.type !== 'gc') return false;
    if (wantScope === 'sp' && d.type !== 'sp') return false;
    if (filterText) {
      const haystack = `${d.name} ${d.signature} ${d.year ?? ''} ${d.committee} ${d.mandate ?? ''}`.toLowerCase();
      if (!haystack.includes(filterText)) return false;
    }
    return true;
  });

  // Header counts
  const gcDocs = docs.filter(d => d.type === 'gc').length;
  const spDocs = docs.filter(d => d.type === 'sp').length;
  $('#docs-title').textContent = `${docs.length.toLocaleString()} document${docs.length === 1 ? '' : 's'}`;
  $('#docs-sub').innerHTML = `${gcDocs} General Comment${gcDocs === 1 ? '' : 's'} · ${spDocs} Special Procedures report${spDocs === 1 ? '' : 's'} <span class="badge badge-preview">PREVIEW</span>`;

  if (!docs.length) {
    host.innerHTML = '<div class="docs-empty">No documents match the current filter.</div>';
    return;
  }

  // Group: type → committee → docs (newest first)
  const groups = { gc: new Map(), sp: new Map() };
  for (const d of docs) {
    const bucket = groups[d.type];
    if (!bucket.has(d.committee)) bucket.set(d.committee, []);
    bucket.get(d.committee).push(d);
  }
  for (const t of ['gc', 'sp']) {
    for (const list of groups[t].values()) {
      list.sort((a, b) => (b.year ?? 0) - (a.year ?? 0));
    }
  }

  const sortedCommittees = (bucket) =>
    [...bucket.keys()].sort((a, b) => bucket.get(b).length - bucket.get(a).length || a.localeCompare(b));

  const html = [];
  if (groups.gc.size && (wantScope === 'all' || wantScope === 'gc')) {
    html.push('<div class="docs-section-head">General Comments · treaty body output</div>');
    for (const c of sortedCommittees(groups.gc)) html.push(renderDocsCommittee(c, groups.gc.get(c), 'gc'));
  }
  if (groups.sp.size && (wantScope === 'all' || wantScope === 'sp')) {
    html.push('<div class="docs-section-head sp-section-head">Special Procedures · mandate-holder reports · preview</div>');
    for (const c of sortedCommittees(groups.sp)) html.push(renderDocsCommittee(c, groups.sp.get(c), 'sp'));
  }
  host.innerHTML = html.join('');
}

function renderDocsCommittee(committee, list, type) {
  const rows = list.map(d => {
    const firstP = `${d.docId}-0001`;
    const statusBadge = d.status === 'superseded'
      ? `<span class="docs-status superseded" title="Superseded by ${escape(d.supersededBy || '—')}">superseded</span>`
      : d.status === 'revised'
      ? `<span class="docs-status revised" title="Revised version">revised</span>`
      : '';
    const abstractAttr = d.abstract ? ` title="${escape(d.abstract)}"` : '';
    return `
      <li>
        <a class="docs-row ${type}" href="?p=${encodeURIComponent(firstP)}#search" data-doc-id="${escape(d.docId)}"${abstractAttr}>
          <span class="sig">${escape(d.signature || '—')}</span>
          <span class="name">${escape(d.nameShort || d.name || d.docId)}${statusBadge}</span>
          <span class="year">${d.year ?? '—'}</span>
          <span class="pcount">${d.paragraphCount ?? 0} ¶</span>
          <span class="arrow">→</span>
        </a>
      </li>`;
  }).join('');
  return `
    <details class="docs-committee ${type}" open>
      <summary>
        <span class="docs-committee-name">${escape(committee)}</span>
        <span class="docs-committee-count">${list.length} document${list.length === 1 ? '' : 's'}</span>
      </summary>
      <ol class="docs-list">${rows}</ol>
    </details>`;
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

  // Result sorting / grouping controls
  $$('#result-sort .result-opt').forEach(b => b.addEventListener('click', () => {
    state.resultSort = b.dataset.sort;
    sortResults();
    paintResults();
    updateDocumentTitle();
    scheduleUrlUpdate();
  }));

  $$('#result-group .result-opt').forEach(b => b.addEventListener('click', () => {
    state.resultGroup = b.dataset.group;
    syncResultsControls();
    paintResults();
    updateDocumentTitle();
    scheduleUrlUpdate();
  }));

  $('#expand-groups').addEventListener('click', () => {
    state.collapsedDocGroups.clear();
    paintResults();
  });

  $('#collapse-groups').addEventListener('click', () => {
    for (const docId of currentResultGroupDocIds()) state.collapsedDocGroups.add(docId);
    paintResults();
  });

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

  // Documents view: scope segmented + filter input
  $$('.docs-scope-opt').forEach(b => b.addEventListener('click', () => {
    $$('.docs-scope-opt').forEach(x => x.classList.remove('is-active'));
    b.classList.add('is-active');
    state.docsScope = b.dataset.docsScope;
    paintDocumentsView();
  }));
  let docsFilterTimer;
  $('#docs-filter')?.addEventListener('input', e => {
    clearTimeout(docsFilterTimer);
    docsFilterTimer = setTimeout(() => {
      state.docsFilter = e.target.value;
      paintDocumentsView();
    }, 150);
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

// ─────────── FlexSearch index ───────────
// Strategy:
//   * Free-text terms are matched through a stemming/full-text FlexSearch index
//     (CDN-loaded, ~28 KB). Catches inflections: 'child' matches 'children'.
//   * Quoted phrases stay strict — substring scan over candidate paragraphs.
//   * The whole index is serialised to IndexedDB keyed by manifest sha so
//     subsequent visits skip the rebuild (~3 s → ~50 ms).

const IDB_NAME = 'gr-cache';
const IDB_STORE = 'flex-index';

let flexSearchPromise = null;
function loadFlexSearch() {
  if (window.FlexSearch) return Promise.resolve(window.FlexSearch);
  if (flexSearchPromise) return flexSearchPromise;
  flexSearchPromise = new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = 'https://cdn.jsdelivr.net/npm/flexsearch@0.7.43/dist/flexsearch.bundle.min.js';
    s.onload = () => resolve(window.FlexSearch);
    s.onerror = () => reject(new Error('FlexSearch failed to load'));
    document.head.appendChild(s);
  });
  return flexSearchPromise;
}

function idbOpen() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(IDB_NAME, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(IDB_STORE);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}
async function idbGet(key) {
  try {
    const db = await idbOpen();
    return await new Promise((resolve, reject) => {
      const tx = db.transaction(IDB_STORE, 'readonly');
      const req = tx.objectStore(IDB_STORE).get(key);
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  } catch { return null; }
}
async function idbPut(key, value) {
  try {
    const db = await idbOpen();
    await new Promise((resolve, reject) => {
      const tx = db.transaction(IDB_STORE, 'readwrite');
      tx.objectStore(IDB_STORE).put(value, key);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  } catch { /* swallow — cache is best-effort */ }
}

async function ensureSearchIndex() {
  const FlexSearch = await loadFlexSearch();
  const sha = state.manifest?.files?.['corpus.json']?.sha;
  const cacheKey = `idx-${sha}`;

  state.searchIndex = new FlexSearch.Document({
    document: { id: 'id', index: ['text'] },
    tokenize: 'forward',
    charset: 'latin:simple',
    cache: 100,
  });

  // Try to restore from IndexedDB
  const cached = sha ? await idbGet(cacheKey) : null;
  if (cached && Array.isArray(cached) && cached.length) {
    try {
      for (const [key, value] of cached) state.searchIndex.import(key, value);
      return;
    } catch (e) {
      console.warn('Index restore failed, rebuilding…', e);
    }
  }

  // Build fresh
  const t0 = performance.now();
  for (const p of state.paragraphs) state.searchIndex.add({ id: p.id, text: p.text });
  console.info(`FlexSearch built in ${(performance.now() - t0).toFixed(0)} ms`);

  // Serialise to IDB after a brief idle (don't block first paint).
  if (sha) {
    setTimeout(async () => {
      try {
        const dump = await dumpIndex();
        if (dump.length) await idbPut(cacheKey, dump);
      } catch (e) { console.warn('Index dump failed:', e); }
    }, 1500);
  }
}

// FlexSearch's export fires its callback per index part — sync or async depending
// on the build. Settle 200 ms after the last call.
function dumpIndex() {
  return new Promise((resolve) => {
    const dump = [];
    let timer = setTimeout(() => resolve(dump), 200);
    state.searchIndex.export((key, value) => {
      dump.push([key, value]);
      clearTimeout(timer);
      timer = setTimeout(() => resolve(dump), 200);
    });
  });
}

// Run one FlexSearch term and return matching paragraph ids.
// Boolean query semantics are composed below so OR always means a true union.
function flexSearchIds(query) {
  if (!state.searchIndex || !query) return null;
  const hits = state.searchIndex.search(query, { limit: 5000, suggest: false });
  const ids = new Set();
  for (const field of hits) for (const id of field.result) ids.add(id);
  return ids;
}

function flexSearchAllIds(terms) {
  const clean = terms.filter(Boolean);
  if (!clean.length) return null;
  let ids = null;
  for (const term of clean) {
    const termIds = flexSearchIds(term);
    if (!termIds) continue;
    ids = ids
      ? new Set([...ids].filter(id => termIds.has(id)))
      : termIds;
  }
  return ids || new Set();
}

function flexSearchAnyIds(terms) {
  const clean = terms.filter(Boolean);
  if (!clean.length) return null;
  const ids = new Set();
  for (const term of clean) {
    const termIds = flexSearchIds(term);
    if (!termIds) continue;
    for (const id of termIds) ids.add(id);
  }
  return ids;
}

// ─────────── Search ───────────
function runSearch() {
  scheduleUrlUpdate();
  const { andTerms, orGroups } = parseQuery(state.query);
  const f = state.filters;
  const scope = state.scope;

  // Quoted phrases (incl. multi-word) stay strict — substring scan.
  // Bare single-word terms benefit from FlexSearch stemming.
  const phrases   = andTerms.filter(t => t.includes(' '));
  const singleAnd = andTerms.filter(t => !t.includes(' '));

  // Stage 1 — narrow by index where possible
  let candidateIds = null;     // null = no constraint
  if (singleAnd.length) {
    candidateIds = flexSearchAllIds(singleAnd);
  }
  for (const grp of orGroups) {
    const orIds = flexSearchAnyIds(grp);
    if (orIds == null) continue;
    candidateIds = candidateIds
      ? new Set([...candidateIds].filter(id => orIds.has(id)))
      : orIds;
  }

  // Stage 2 — apply structural filters and phrase enforcement
  const matched = [];
  const iter = candidateIds
    ? [...candidateIds].map(id => state.paragraphById.get(id)).filter(Boolean)
    : state.paragraphs;

  for (const p of iter) {
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
        let allOk = true;
        for (const l of f.labels) { if (!pl.includes(l)) { allOk = false; break; } }
        if (!allOk) continue;
      } else {
        if (!pl.some(l => f.labels.has(l))) continue;
      }
    }

    const text = p.text.toLowerCase();

    // Enforce quoted phrases as exact substrings (FlexSearch tokenises, doesn't preserve order)
    if (phrases.length) {
      let ok = true;
      for (const ph of phrases) { if (!text.includes(ph)) { ok = false; break; } }
      if (!ok) continue;
    }

    // Score: occurrences in original text, weighted by term length.
    // Stemming-only matches (no exact occurrence) still get baseline 1 to surface them.
    let score = 0;
    for (const t of [...singleAnd, ...phrases, ...orGroups.flat()]) {
      if (!t) continue;
      const occ = countOccurrences(text, t);
      score += occ * (1 + Math.log2(t.length + 1));
    }
    if (state.query && score === 0) score = 1;
    matched.push({ p, score });
  }

  state.results = matched;
  sortResults();
  paintResults();
  updateDocumentTitle();
}

function countOccurrences(haystack, needle) {
  if (!needle) return 0;
  let count = 0, idx = 0;
  while ((idx = haystack.indexOf(needle, idx)) !== -1) { count++; idx += needle.length; }
  return count;
}

function sortResults() {
  const byTextOrder = (a, b) =>
    String(a.p.docId).localeCompare(String(b.p.docId)) || ((a.p.idx || 0) - (b.p.idx || 0));

  if (effectiveResultSort() === 'date') {
    state.results.sort((a, b) =>
      (resultDateValue(b) - resultDateValue(a)) ||
      (b.score - a.score) ||
      byTextOrder(a, b)
    );
    return;
  }

  state.results.sort((a, b) =>
    (b.score - a.score) ||
    (resultDateValue(b) - resultDateValue(a)) ||
    byTextOrder(a, b)
  );
}

function resultDateValue(result) {
  const doc = state.documents.get(result.p.docId);
  const parsed = doc?.adoptionDate ? Date.parse(doc.adoptionDate) : NaN;
  if (!Number.isNaN(parsed)) return parsed;
  const year = result.p.year || doc?.year || 0;
  return year ? Date.UTC(year, 0, 1) : 0;
}

function hasSearchQuery() {
  return state.query.trim().length > 0;
}

function effectiveResultSort() {
  return hasSearchQuery() && state.resultSort === 'relevance' ? 'relevance' : 'date';
}

function shouldShowRelevanceScore() {
  return state.resultGroup === 'documents' && effectiveResultSort() === 'relevance';
}

function syncResultsControls() {
  const activeSort = effectiveResultSort();
  $$('#result-sort .result-opt').forEach(b => {
    const on = b.dataset.sort === activeSort;
    b.classList.toggle('is-active', on);
    b.setAttribute('aria-pressed', on ? 'true' : 'false');
    b.toggleAttribute('disabled', b.dataset.sort === 'relevance' && !hasSearchQuery());
  });

  $$('#result-group .result-opt').forEach(b => {
    const on = b.dataset.group === state.resultGroup;
    b.classList.toggle('is-active', on);
    b.setAttribute('aria-pressed', on ? 'true' : 'false');
  });

  const grouped = state.resultGroup === 'documents' && state.results.length > 0;
  $('#expand-groups')?.toggleAttribute('disabled', !grouped);
  $('#collapse-groups')?.toggleAttribute('disabled', !grouped);
}

function currentResultGroupDocIds() {
  return [...new Set(state.results.slice(0, RESULT_LIMIT).map(({ p }) => p.docId))];
}

// ─────────── Render ───────────
function paintResults() {
  const list = $('#result-list');
  list.innerHTML = '';
  const total = state.results.length;
  const docCount = new Set(state.results.map(r => r.p.docId)).size;
  syncResultsControls();

  $('#result-count').textContent = `${total.toLocaleString()} ¶`;
  $('#results-title').textContent = total
    ? `${total.toLocaleString()} passages from ${docCount} document${docCount === 1 ? '' : 's'}`
    : 'No matches';
  $('#results-sub').textContent = resultSubtitle();
  $('#results-sub').appendChild(scopeNotice());

  const view = state.results.slice(0, RESULT_LIMIT);
  const { andTerms, orGroups } = parseQuery(state.query);
  const allTerms = [...andTerms, ...orGroups.flat()].filter(Boolean);

  list.classList.toggle('is-grouped', state.resultGroup === 'documents');
  if (state.resultGroup === 'documents') {
    renderGroupedResults(list, view, allTerms);
  } else {
    view.forEach(({ p }, i) => {
      list.appendChild(renderResult(p, i + 1, allTerms));
    });
  }

  $('#result-more').textContent = total > RESULT_LIMIT
    ? moreResultsText(total, view)
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

function resultSubtitle() {
  const sortText = effectiveResultSort() === 'date'
    ? hasSearchQuery()
      ? 'Sorted by date, newest first.'
      : 'Showing newest matching paragraphs.'
    : hasSearchQuery()
      ? `Sorted by relevance to "${state.query}".`
      : 'Showing newest matching paragraphs.';
  const groupText = state.resultGroup === 'documents' ? ' Grouped by document.' : ' Paragraph view.';
  return `${sortText}${groupText} `;
}

function moreResultsText(total, view) {
  if (state.resultGroup === 'documents') {
    const docs = new Set(view.map(({ p }) => p.docId)).size;
    return `Showing top ${RESULT_LIMIT} paragraphs grouped into ${docs} document${docs === 1 ? '' : 's'} out of ${total.toLocaleString()} matches. Refine your filters to narrow down.`;
  }
  return `Showing top ${RESULT_LIMIT} of ${total.toLocaleString()}. Refine your filters to narrow down.`;
}

function renderGroupedResults(list, view, terms) {
  const groups = new Map();
  view.forEach((result, idx) => {
    const docId = result.p.docId;
    if (!groups.has(docId)) groups.set(docId, []);
    groups.get(docId).push({ ...result, rank: idx + 1 });
  });

  for (const [docId, rows] of groups) {
    list.appendChild(renderResultGroup(docId, rows, terms));
  }
}

function renderResultGroup(docId, rows, terms) {
  const doc = state.documents.get(docId);
  const li = document.createElement('li');
  li.className = `result-doc-group ${rows[0]?.p.type || ''}`;
  li.dataset.docId = docId;

  const details = document.createElement('details');
  details.className = 'result-doc-details';
  details.open = !state.collapsedDocGroups.has(docId);
  details.addEventListener('toggle', () => {
    if (details.open) state.collapsedDocGroups.delete(docId);
    else state.collapsedDocGroups.add(docId);
  });

  const badge = rows[0]?.p.type === 'sp'
    ? '<span class="badge badge-sp">PREVIEW · SP</span>'
    : '<span class="badge badge-gc">GC</span>';
  const bestScore = Math.max(...rows.map(r => r.score || 0));
  const scoreMeta = shouldShowRelevanceScore() && bestScore > 0
    ? `<span class="relevance-score">relevance ${bestScore.toFixed(1)}</span>`
    : '';

  const summary = document.createElement('summary');
  summary.innerHTML = `
    <div class="result-doc-summary-main">
      ${badge}
      <span class="result-doc-summary-title">${escape(doc?.nameShort || doc?.name || docId)}</span>
    </div>
    <div class="result-doc-summary-meta">
      <span class="folio">${doc?.year ?? ''}</span>
      <span class="sig">${escape(doc?.signature || '—')}</span>
      <span class="match-count">${rows.length} ¶</span>
      ${scoreMeta}
    </div>
  `;

  const nested = document.createElement('ol');
  nested.className = 'result-group-list';
  rows.forEach(({ p, rank }) => nested.appendChild(renderResult(p, rank, terms, { grouped: true })));

  details.appendChild(summary);
  details.appendChild(nested);
  li.appendChild(details);
  return li;
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

function renderResult(p, rank, terms, opts = {}) {
  const doc = state.documents.get(p.docId);
  const li = document.createElement('li');
  li.className = `result fade-up ${p.type}${opts.grouped ? ' is-grouped-result' : ''}`;
  li.dataset.paraId = p.id;
  if (p.id === state.activeId) li.classList.add('is-active');

  const badge = p.type === 'sp'
    ? '<span class="badge badge-sp">PREVIEW · SP</span>'
    : '<span class="badge badge-gc">GC</span>';

  const labelChips = (p.labels || []).slice(0, 4).map(l => `<span class="chip">${escape(l)}</span>`).join('');
  const committeeChips = p.committees.map(c => `<span class="chip ${isSp(c) ? 'sp-chip' : ''}">${escape(c)}</span>`).join('');

  const headline = opts.grouped
    ? `
        ${badge}
        <span class="folio">MATCHED PARAGRAPH</span>
        <span class="result-spacer"></span>
        <span class="folio">${doc?.year ?? ''}</span>
      `
    : `
        ${badge}
        <span class="result-doc">${escape(doc?.nameShort || doc?.name || p.docId)}</span>
        <span class="result-spacer"></span>
        <span class="folio">${doc?.year ?? ''}</span>
      `;

  li.innerHTML = `
    <div class="result-margin">
      <div class="result-rank">№ ${String(rank).padStart(2, '0')}</div>
      ${p.n != null ? `<div class="result-pn">¶${p.n}</div>` : ''}
    </div>
    <div class="result-body">
      <div class="result-headline">
        ${headline}
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
  updateDocumentTitle();
  scheduleUrlUpdate();
}

// Per-URL <title> so deep-linked pages get distinct titles in search results
// and browser history. Without this, Googlebot indexes every ?p=… URL with
// the same homepage title.
const BASE_TITLE = 'The Geneva Reporter · UN Treaty Body General Comments';
function updateDocumentTitle() {
  const para = state.activeId ? state.paragraphById.get(state.activeId) : null;
  if (para) {
    const doc = state.documents.get(para.docId);
    const docTitle = doc?.nameShort || doc?.name || para.docId;
    document.title = `${docTitle} · The Geneva Reporter`;
    return;
  }
  if (state.query) {
    document.title = `${state.query} · The Geneva Reporter`;
    return;
  }
  document.title = BASE_TITLE;
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

  const articlesHtml = doc?.articles?.length
    ? `<div class="dossier-dp"><div class="folio">Articles</div><div class="v">${doc.articles.map(a => `<span class="dossier-chip">${escape(a)}</span>`).join(' ')}</div></div>`
    : '';
  const statusHtml = doc?.status && doc.status !== 'final'
    ? `<div class="dossier-dp"><div class="folio">Status</div><div class="v">${escape(doc.status)}${doc.supersededBy ? ` → ${escape(doc.supersededBy)}` : ''}</div></div>`
    : '';
  const abstractHtml = doc?.abstract
    ? `<div class="dossier-abstract serif"><div class="folio">In a sentence</div><p>${escape(doc.abstract)}</p></div>`
    : '';

  host.innerHTML = `
    <div class="folio garnet">${isSpDoc ? 'MANDATE REPORT · PREVIEW' : 'GENERAL COMMENT'}</div>
    <h3 class="dossier-title">${escape(doc?.name || para.docId)}</h3>
    <div class="dossier-sig">${escape(doc?.signature || '')}</div>
    ${abstractHtml}
    <div class="dossier-grid">
      <div class="dossier-dp"><div class="folio">Adopted</div><div class="v">${escape(doc?.adoptionDate || '—')}</div></div>
      <div class="dossier-dp"><div class="folio">Year</div><div class="v">${doc?.year ?? '—'}</div></div>
      <div class="dossier-dp"><div class="folio">${isSpDoc ? 'Mandate' : 'Committee'}</div><div class="v">${escape(doc?.committees?.join(' · ') || '—')}</div></div>
      <div class="dossier-dp"><div class="folio">Paragraphs</div><div class="v">${doc?.paragraphCount ?? '—'}</div></div>
      ${articlesHtml}
      ${statusHtml}
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
