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
    yearMin: null,
    yearMax: null,
  },
  results: [],
  activeId: null,
  bannerShownForSp: false,
};

const DATA_BASE = './';      // corpus.json etc. live alongside index.html
const RESULT_LIMIT = 200;    // render cap; "more" hint shown when hit

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
    paintFilters();
    initYearRange();
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

// ─────────── Facets / Filters UI ───────────
function paintFilters() {
  const cont = $('#filter-committees');
  cont.innerHTML = '';
  for (const { value, count } of state.facets.committees) {
    const b = document.createElement('button');
    b.className = 'chip';
    if (value.startsWith('SR ') || value.startsWith('SSR')) b.classList.add('sp-chip');
    b.dataset.committee = value;
    b.innerHTML = `${value} <span class="dim">${count.toLocaleString()}</span>`;
    b.addEventListener('click', () => {
      if (state.filters.committees.has(value)) state.filters.committees.delete(value);
      else state.filters.committees.add(value);
      b.classList.toggle('on');
      runSearch();
    });
    cont.appendChild(b);
  }

  const lblHost = $('#filter-labels');
  lblHost.innerHTML = '';
  for (const { value, count } of state.facets.labels) {
    const id = `lbl-${value.replace(/[^a-z0-9]+/gi, '-').toLowerCase()}`;
    const wrap = document.createElement('label');
    wrap.innerHTML = `
      <input type="checkbox" id="${id}" />
      <span>${value}</span>
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
  $('#year-lo').textContent = min;
  $('#year-hi').textContent = max;
  $('#year-fill').style.width = '100%';
  $('#year-min').value = min;
  $('#year-max').value = max;
  $('#year-min').min = min;
  $('#year-min').max = max;
  $('#year-max').min = min;
  $('#year-max').max = max;
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

  // Scope toggle
  $$('.scope-opt').forEach(b => b.addEventListener('click', () => {
    $$('.scope-opt').forEach(x => {
      x.classList.remove('is-active');
      x.setAttribute('aria-selected', 'false');
    });
    b.classList.add('is-active');
    b.setAttribute('aria-selected', 'true');
    state.scope = b.dataset.scope;

    const meta = {
      gc:  'Treaty body output · near-hard-law',
      sp:  'Mandate-holder reports · soft law · preview',
      all: 'Combined view',
    }[state.scope];
    $('#scope-meta').textContent = meta;

    if (state.scope === 'sp' && !state.bannerShownForSp) {
      $('#scope-banner').hidden = false;
      state.bannerShownForSp = true;
    }
    runSearch();
  }));

  $('#banner-dismiss').addEventListener('click', () => {
    $('#scope-banner').hidden = true;
  });

  // Year inputs
  $('#year-min').addEventListener('change', e => {
    state.filters.yearMin = parseInt(e.target.value) || state.facets.years.min;
    paintYearFill();
    runSearch();
  });
  $('#year-max').addEventListener('change', e => {
    state.filters.yearMax = parseInt(e.target.value) || state.facets.years.max;
    paintYearFill();
    runSearch();
  });

  // Reset
  $('#reset-filters').addEventListener('click', () => {
    state.filters.committees.clear();
    state.filters.labels.clear();
    state.filters.yearMin = state.facets.years.min;
    state.filters.yearMax = state.facets.years.max;
    $$('#filter-committees .chip').forEach(c => c.classList.remove('on'));
    $$('#filter-labels input').forEach(i => i.checked = false);
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

function paintYearFill() {
  const { min, max } = state.facets.years;
  const span = max - min || 1;
  const left = ((state.filters.yearMin - min) / span) * 100;
  const right = ((state.filters.yearMax - min) / span) * 100;
  $('#year-fill').style.marginLeft = `${left}%`;
  $('#year-fill').style.width = `${right - left}%`;
  $('#year-lo').textContent = state.filters.yearMin;
  $('#year-hi').textContent = state.filters.yearMax;
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
    if (f.labels.size && !(p.labels && p.labels.some(l => f.labels.has(l)))) continue;

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
  $$('.result').forEach(el => el.classList.remove('is-active'));
  paintDossier();
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

  // mark active in list
  $$('.result').forEach(el => el.classList.remove('is-active'));
  const activeEl = $$('.result').find((el, idx) => state.results[idx]?.p.id === state.activeId);
  activeEl?.classList.add('is-active');
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
