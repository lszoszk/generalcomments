/* =========================================================
   UN Human Rights Database · Search app
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
  baseFacets: null,
  searchIndex: null,            // FlexSearch.Document instance, populated after boot
  // v19.11: ternary online status. null = ping not yet returned, true = API
  // reachable, false = unreachable (local fallback engaged for the session).
  apiOnline: null,
  view: 'search',               // 'search' | 'documents' | 'about' — driven by URL hash
  docsScope: 'all',             // documents-view scope: 'all' | 'gc' | 'jur' | 'sp'
  docsFilter: '',               // documents-view free-text filter
  docsActiveDocId: null,        // v17: currently-open document in the reader
  docsActiveParaId: null,       // v17: currently-active ¶ inside the reader (for highlight)
  docsDrawerCollapsed: false,   // v17: right drawer collapsed?
  docsRailCollapsed: new Set(), // v17: collapsed body groups in the rail
  scope: 'gc',         // 'gc' | 'jur' | 'sp' | 'all'
  resultSort: 'relevance',      // 'relevance' | 'date'
  resultGroup: 'paragraphs',    // 'paragraphs' | 'documents'
  searchInFootnotes: true,      // v19.12: include fnText field in FlexSearch query
  collapsedDocGroups: new Set(),
  query: '',
  filters: {
    committees: new Set(),
    labels: new Set(),
    labelsMode: 'any',     // 'any' | 'all' — match-mode for concerned groups
    yearMin: null,
    yearMax: null,
    reportTypes: new Set(),      // SP only — annual / thematic / communications / addendum / country-visit
    countries: new Set(),        // JUR only — state party of the case
    showSuperseded: false,       // hide superseded GCs by default
  },
  results: [],
  activeId: null,
  bannerShownForSp: false,
  bannerShownForJur: false,
  searchRun: 0,
  jur: {
    manifest: null,
    facets: null,
    loaded: false,
    loading: null,
    error: null,
  },
};

const DATA_BASE = './';      // corpus.json etc. live alongside index.html
const JUR_BASE = './jur/';    // jurisprudence pilot: metadata eager, paragraphs lazy

// v19.11: server-side search API is the DEFAULT for jurisprudence and
// scope=all. The local FlexSearch path stays as the offline fallback —
// it kicks in automatically if the boot-time ping fails or any API call
// errors. Opt-out is via `?api=0` in the URL or
// `localStorage.unhrdb_useApi = '0'`. The corpus is now ~125 MB of JUR
// shards plus the FlexSearch build, so downloading + indexing it in
// every browser was a 60-second tax — letting the SQLite FTS5 server
// handle JUR brings first-search latency under 200 ms while the local
// path remains a graceful degradation.
const API_BASE = 'https://150.254.115.204/unhrdb-api';
const API_TIMEOUT_MS = 5_000;     // fail fast if the VM is unreachable
function apiEnabled() {
  try {
    // Explicit per-session opt-out (URL wins over localStorage).
    const urlFlag = new URLSearchParams(location.search).get('api');
    if (urlFlag === '0') return false;
    if (urlFlag === '1') return true;        // legacy explicit-opt-in still honored
    const lsFlag = localStorage.getItem('unhrdb_useApi');
    if (lsFlag === '0') return false;
    // No explicit signal → default ON.
  } catch {}
  return true;
}
function apiActive(scope) {
  // Hybrid mode: only JUR + all routes through the API; GC + SP stay
  // local because their corpora are small and the keystroke-fast
  // in-browser FlexSearch path beats any round-trip. If the API was
  // probed at boot and is unreachable, fall back to local —
  // `state.apiOnline === false` blocks subsequent attempts so a single
  // failure doesn't cause an infinite recursion via runSearch. While
  // the ping is in flight (`state.apiOnline === null`) we OPTIMISTICALLY
  // try the API; runSearchViaApi has its own catch that flips to local
  // and the timeout means we fail fast.
  if (!apiEnabled()) return false;
  if (state.apiOnline === false) return false;
  return scope === 'jur' || scope === 'all';
}
async function apiFetch(path, params) {
  const url = new URL(API_BASE + path);
  for (const [k, v] of Object.entries(params || {})) {
    if (v !== null && v !== undefined && v !== '') url.searchParams.set(k, v);
  }
  // AbortController gives us a hard wall: if the VM is down or behind
  // a captive portal, we want fallback within seconds rather than the
  // browser-default 30+ seconds. AbortSignal.timeout() is widely
  // supported in modern browsers; older Safari needs the manual variant.
  const ac = new AbortController();
  const timer = setTimeout(() => ac.abort(new Error('timeout')), API_TIMEOUT_MS);
  try {
    const res = await fetch(url.toString(), { credentials: 'omit', signal: ac.signal });
    if (!res.ok) throw new Error(`API ${path} → ${res.status}`);
    return await res.json();
  } finally {
    clearTimeout(timer);
  }
}

// Boot-time smoke for the API. v19.11: API is the default for JUR/all,
// so this runs for everyone unless explicitly opted out (?api=0). Logs
// round-trip time + version, stamps a tiny "API · NN ms" badge near
// the result count, and crucially sets state.apiOnline so apiActive()
// can decide between API vs local for subsequent searches.
async function pingApi() {
  if (!apiEnabled()) return;
  const t0 = performance.now();
  try {
    const r = await apiFetch('/api/stats', {});
    const ms = Math.round(performance.now() - t0);
    console.info(`[unhrdb-api] online · ${r.version} · ${r.totalParagraphs.toLocaleString()} ¶ · ${ms} ms`);
    state.apiOnline = true;
    paintApiBadge(true, ms);
  } catch (e) {
    console.warn('[unhrdb-api] unreachable:', e.message);
    state.apiOnline = false;
    paintApiBadge(false);
  }
}
// v19: API-backed runSearch. Maps an /api/search response into the
// same `{p, score}` shape the local renderer expects, hydrates
// state.paragraphById on the fly so the dossier + workspace marks
// keep working, and short-circuits the local FlexSearch + BM25 path.
async function runSearchViaApi(runId) {
  const f = state.filters;
  const scope = state.scope;

  // Build the API param set from current state.
  const params = {
    q: state.query || '',
    scope: scope,
    sort: state.resultSort === 'date'
            ? 'date_desc'
            : 'relevance',
    page: 1,
    // The API caps page_size at 200. That's enough for the first
    // screen + a few infinite-scroll ticks — past 200, follow-up
    // pages are fetched on demand (TODO Sprint-3.1: chain pages on
    // scroll). 200 is also a sensible "you should refine your
    // filters" cliff, mirroring our local RESULT_HARD_CAP behaviour.
    page_size: 200,
  };
  // v19.4: route every chip through `body=` — a server-side union that
  // matches when ANY of d.treaty / d.committee / d.mandate is in the
  // list. The frontend's chip values map cleanly onto those three
  // columns:
  //
  //   "CAT"   → matches d.committee for GC rows
  //   "CRPD"  → matches d.committee (GC) AND d.treaty (JUR) — both
  //             desired, OR'd together
  //   "SR Freedom of Religion or Belief"
  //           → matches d.committee for SP rows (the column there
  //             holds the SR title; d.mandate holds the person name,
  //             which the frontend doesn't expose as a filter)
  //
  // Lumping into committees+treaties+mandates as separate AND'd IN
  // clauses (v19.1) silently dropped every row because no single doc
  // satisfies all three columns at once — JUR mandate is NULL, GC
  // treaty is NULL, etc.
  if (f.committees.size) {
    params.body = [...f.committees].join(',');
  }
  if (f.labels.size) params.labels = [...f.labels].join(',');
  if (f.yearMin && f.yearMin !== state.facets?.years?.min) params.year_from = f.yearMin;
  if (f.yearMax && f.yearMax !== state.facets?.years?.max) params.year_to   = f.yearMax;

  // UI-side loading hint (kept short so the badge keeps reflecting reality).
  paintApiBadge(true, '…');
  const t0 = performance.now();

  let body;
  try {
    body = await apiFetch('/api/search', params);
  } catch (e) {
    if (runId !== state.searchRun) return;
    console.warn('[unhrdb-api] search failed, falling back to local:', e.message);
    paintApiBadge(false);
    state.apiOnline = false;
    // Re-run via the local path so the user gets results either way.
    return runSearch();
  }
  if (runId !== state.searchRun) return;     // user typed again mid-flight

  paintApiBadge(true, Math.round(performance.now() - t0));

  // Hydrate state.paragraphById + state.documents so the dossier and
  // the per-row workspace marks (which look up by para.id) keep
  // working.  Only writes on cache miss.
  const matched = body.hits.map(h => {
    const p = adaptApiHit(h);
    if (!state.paragraphById.has(p.id)) state.paragraphById.set(p.id, p);
    if (!state.documents.has(p.docId)) {
      state.documents.set(p.docId, adaptApiDoc(h));
    }
    return { p, score: h.score ?? 0, snippetHtml: h.snippet };
  });

  state.results = matched;
  // Server returned in the order we asked for — don't re-sort.
  // Keep an "alsoTry" suggestion list for the empty-state painter and
  // the API's true total so the count badge tells the truth even when
  // we only paged in 200 rows.
  state.alsoTry = body.alsoTry || [];
  state.apiTotal = body.total;
  // v19.6 (U2): server-side breakdown over the FULL match-set,
  // not just the first 200-row page slice. paintResultBreakdown reads
  // this when running through the API — without it, the GC/JUR/SP
  // pills under the searchbar showed only what was rendered.
  state.apiBreakdown = body.breakdown || null;
  // v19.2: stash the params + page cursor so the IntersectionObserver
  // can fetch /api/search?page=N+1 when the user scrolls past 200.
  state.apiPage = 1;
  state.apiPageSize = params.page_size;
  state.apiSearchParams = params;
  state.apiHasMore = body.total > matched.length;
  state.apiPageInflight = null;
  paintResults();
  updateDocumentTitle();
}

// v19.2: pull the next /api/search page and append to state.results.
// Returns true when new rows landed, false when the server has nothing
// left or the call failed. Concurrency-safe via state.apiPageInflight —
// a Promise stash prevents two scroll ticks from double-fetching.
async function fetchNextApiPage() {
  if (!state.apiHasMore) return false;
  if (state.apiPageInflight) return state.apiPageInflight;

  const t0 = performance.now();
  paintApiBadge(true, '…');
  const nextPage = (state.apiPage || 1) + 1;
  const params = { ...state.apiSearchParams, page: nextPage };

  state.apiPageInflight = (async () => {
    try {
      const body = await apiFetch('/api/search', params);
      const more = body.hits.map(h => {
        const p = adaptApiHit(h);
        if (!state.paragraphById.has(p.id)) state.paragraphById.set(p.id, p);
        if (!state.documents.has(p.docId)) state.documents.set(p.docId, adaptApiDoc(h));
        return { p, score: h.score ?? 0, snippetHtml: h.snippet };
      });
      state.results.push(...more);
      state.apiPage = nextPage;
      state.apiHasMore = state.results.length < body.total;
      paintApiBadge(true, Math.round(performance.now() - t0));
      return more.length > 0;
    } catch (e) {
      console.warn('[unhrdb-api] fetchNextApiPage failed:', e.message);
      state.apiHasMore = false;
      paintApiBadge(false);
      return false;
    } finally {
      state.apiPageInflight = null;
    }
  })();
  return state.apiPageInflight;
}

// Map one `hits[i]` entry from the API into a paragraph object that
// matches what build_corpus.py emits for the static corpus.json. The
// shape has to satisfy paintDossier + renderResult + workspace marks
// without further conditional logic in those code paths.
function adaptApiHit(h) {
  return {
    id:      h.para_id,
    docId:   h.doc_id,
    idx:     h.idx,
    n:       h.n,
    section: h.section,
    text:    h.text,
    type:    h.type,
    year:    h.year,
    committee:  h.committee || h.mandate || h.treaty,
    committees: [h.committee || h.mandate || h.treaty].filter(Boolean),
    labels:  [],     // API doesn't return per-paragraph labels in the page slice yet
  };
}
function adaptApiDoc(h) {
  return {
    docId:        h.doc_id,
    type:         h.type,
    treaty:       h.treaty,
    committee:    h.committee,
    committees:   [h.committee || h.mandate || h.treaty].filter(Boolean),
    mandate:      h.mandate,
    name:         h.name,
    nameShort:    h.name_short,
    signature:    h.signature,
    country:      h.country,
    outcome:      h.outcome,
    year:         h.year,
    adoptionDate: h.adoption_date,
  };
}

function paintApiBadge(online, ms) {
  const host = $('#result-breakdown');
  if (!host) return;
  let badge = $('#api-badge');
  if (!badge) {
    badge = document.createElement('span');
    badge.id = 'api-badge';
    badge.className = 'rb-pill rb-api';
    host.appendChild(badge);
    host.hidden = false;
  }
  badge.textContent = online ? `API · ${ms} ms` : 'API · offline';
  badge.title = online
    ? `Connected to ${API_BASE}. JUR queries route through the API for instant search. Add ?api=0 to the URL to force local mode.`
    : `${API_BASE} unreachable. Using local FlexSearch (the JUR corpus is ~125 MB; first search may take ~60 s while it indexes).`;
  badge.classList.toggle('rb-api-offline', !online);
}
// First-page render budget. v19.10: trimmed from 50 → 20 because each
// jurisprudence row carries enriched metadata (case name, articles, issues),
// which makes per-row paint heavier. Subsequent pages append on scroll.
const RESULT_FIRST_PAGE = 20;
const RESULT_PAGE_SIZE = 50;       // page size for subsequent appends
const RESULT_HARD_CAP  = 5000;     // safety net so a 26k-paragraph wildcard match doesn't blow up the DOM

// ─────────── URL state ───────────
// Short keys keep shareable URLs human-readable.
const URL_KEYS = { q: 'q', scope: 'scope', tb: 'tb', g: 'g', gm: 'gm', y1: 'y1', y2: 'y2', p: 'p', sort: 'sort', group: 'group', rt: 'rt', sup: 'sup', cy: 'cy', fn: 'fn' };

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
  if (state.filters.reportTypes.size) u.set(URL_KEYS.rt, [...state.filters.reportTypes].join('|'));
  if (state.filters.countries.size) u.set(URL_KEYS.cy, [...state.filters.countries].join('|'));
  if (state.filters.showSuperseded) u.set(URL_KEYS.sup, '1');
  // v19.12: only emit fn=0 when toggle is OFF (default ON keeps URLs short).
  if (state.searchInFootnotes === false) u.set(URL_KEYS.fn, '0');
  if (state.activeId) u.set(URL_KEYS.p, state.activeId);
  const qs = u.toString();
  // v17: preserve the hash — the docs reader relies on "#documents/<docId>"
  // to remember which document is open. Earlier versions silently stripped
  // it which made deep links unsharable.
  const hash = window.location.hash || '';
  const next = (qs ? `${window.location.pathname}?${qs}` : window.location.pathname) + hash;
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
    // resultGroup: leave undefined when no URL key is present so the
    // boot-time auto-default ("documents" on jurisprudence, "paragraphs"
    // elsewhere) wins. An explicit value freezes the user's choice.
    resultGroup: u.get(URL_KEYS.group) || null,
    activeId: u.get(URL_KEYS.p) || null,
    reportTypes: split('rt'),
    countries: split('cy'),
    showSuperseded: u.get(URL_KEYS.sup) === '1',
    // v19.12: omitted/anything-but-'0' = ON (default). 'fn=0' = OFF.
    searchInFootnotes: u.get(URL_KEYS.fn) !== '0',
    searchInFootnotesUrl: u.has(URL_KEYS.fn),     // explicit URL signal
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

// v19.6 (B3): theme preference is restored synchronously, BEFORE
// boot() awaits anything, so users on dark mode don't see a
// light-mode flash while corpus.json downloads.
(function restoreThemePref() {
  try {
    const saved = localStorage.getItem('unhrdb_theme_v1');
    if (saved === 'dark' || saved === 'light') {
      document.documentElement.setAttribute('data-theme', saved);
    }
  } catch {}
})();

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
    state.baseFacets = state.facets;

    setProgress(38, 'Checking jurisprudence preview…');
    await loadJurMetadata();
    state.facets = mergeJurFacets(state.baseFacets);
    paintMastFolio(manifest);

    setProgress(45, `Loading ${manifest.counts.paragraphs.toLocaleString()} paragraphs…`);
    state.paragraphs = await fetchJson(`${DATA_BASE}corpus.json`);
    _flushDfCache();
    _avgDocLen = null;

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
    paintReportTypeFilter();
    paintStatusFilter();
    paintCountryFilter();
    syncReportTypeFilterVisibility();
    syncCountryFilterVisibility();
    syncFiltersToDom();                  // checkboxes, chips and ANY/ALL toggle visuals
    bindUI();
    bindRouter();
    initDossierResizer();                // v15: drag handle + persisted width
    initDossierFontPref();               // v15: restore S/M/L preference
    state.apiPingPromise = pingApi();    // v19.11: stashed so the first JUR runSearch can await it briefly
    paintDiffTray();                     // restore pinned-tray on reload
    paintWorkspaceBadge();
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
  const res = await fetch(url, { cache: 'no-cache' });
  if (!res.ok) throw new Error(`${url} → ${res.status}`);
  return res.json();
}

async function loadJurMetadata() {
  try {
    state.jur.manifest = await fetchJson(`${JUR_BASE}manifest.json`);
    state.jur.facets = await fetchJson(`${JUR_BASE}facets.json`);
    const docs = await fetchJson(`${JUR_BASE}documents.json`);
    docs.forEach(d => state.documents.set(d.docId, normalizeJurDocument(d)));
  } catch (err) {
    state.jur.error = err;
    console.warn('Jurisprudence preview unavailable:', err);
  }
}

// v16: a single source of truth for "what to call this document on a result
// row / dossier folio / workspace row". Folds the body / mandate prefix into
// the title so search results don't all start with the same words.
//
// Format:
//   GC :   "<COMMITTEE> · <nameShort>"            e.g. "CAT · GC1: Implementation of Art. 3…"
//   JUR:   "<TREATY> · <signature> · <country>"   e.g. "CRPD · 103/2022 · Spain"
//   SP :   "<MANDATE> · <nameShort>"              e.g. "Religion · Elimination of all forms… (1995)"
//   else:  fall back to nameShort / name / docId.
function formatDocHeadline(doc, { compact = false } = {}) {
  if (!doc) return '';
  const baseTitle = doc.nameShort || doc.name || doc.docId || '';
  if (doc.type === 'gc') {
    const body = doc.committee || (doc.committees?.[0]) || '';
    return body ? `${body} · ${baseTitle}` : baseTitle;
  }
  if (doc.type === 'jur') {
    const treaty = doc.treaty || doc.committee || '';
    const sig = doc.signature || doc.symbol || '';
    const country = doc.country || '';
    const parts = [treaty, sig, country].filter(Boolean);
    if (compact) return parts.join(' · ');
    // Promote the case title (often "Communication Nº X: outcome") only when
    // we actually have one — otherwise the parts are sufficient.
    const caseTitle = doc.title || doc.name || '';
    return caseTitle && caseTitle !== sig
      ? `${treaty} · ${sig}${country ? ` · ${country}` : ''} — ${caseTitle}`
      : parts.join(' · ');
  }
  if (doc.type === 'sp') {
    const mandate = doc.mandate ? mandateShortLabel(doc.mandate) : '';
    return mandate ? `${mandate} · ${baseTitle}` : baseTitle;
  }
  return baseTitle;
}

// SP mandate names are long ("Special Rapporteur on freedom of religion or
// belief") — for headlines we want a tight 1-3 word label. Heuristic: take
// "Rapporteur on X" → X, otherwise the first significant noun phrase.
function mandateShortLabel(mandate) {
  if (!mandate) return '';
  const m = mandate.match(/Rapporteur on (?:the )?(.+)$/i);
  if (m) {
    const phrase = m[1].replace(/\s+(of|and)\s+/i, ' & ').trim();
    // If it's still too long, keep first 4 words.
    const words = phrase.split(/\s+/);
    return words.length > 4 ? words.slice(0, 4).join(' ') + '…' : phrase;
  }
  // Otherwise take first 3 words.
  const words = mandate.split(/\s+/);
  return words.length > 3 ? words.slice(0, 3).join(' ') + '…' : mandate;
}

function normalizeJurDocument(d) {
  return {
    ...d,
    type: 'jur',
    committee: d.committee || d.treaty,
    committees: d.committees || (d.treaty ? [d.treaty] : []),
    name: d.name || d.title || d.symbol || d.docId,
    nameShort: d.nameShort || d.title || d.symbol || d.docId,
    signature: d.signature || d.symbol || '',
    year: d.year ?? d.adoptionYear ?? d.communicationYear ?? null,
    adoptionDate: d.adoptionDate || '',
  };
}

function jurCommitteeFacets() {
  const treaties = state.jur.facets?.treaties || [];
  const paraTotal = state.jur.manifest?.counts?.paragraphs;
  return treaties.map(item => ({
    value: item.value,
    count: treaties.length === 1 && paraTotal ? paraTotal : item.count,
  }));
}

function jurTreatyLabel({ compact = false } = {}) {
  const treaties = (state.jur.facets?.treaties || []).map(item => item.value).filter(Boolean);
  if (!treaties.length) return compact ? 'preview' : 'jurisprudence';
  if (compact && treaties.length > 1) return `${treaties.length} bodies`;
  if (treaties.length <= 3) return treaties.join(' + ');
  return `${treaties.length} treaty bodies`;
}

function mergeFacetItems(...lists) {
  const byValue = new Map();
  for (const list of lists) {
    for (const item of list || []) {
      byValue.set(item.value, (byValue.get(item.value) || 0) + (item.count || 0));
    }
  }
  return [...byValue.entries()]
    .map(([value, count]) => ({ value, count }))
    .sort((a, b) => (b.count - a.count) || a.value.localeCompare(b.value));
}

function mergeYearFacet(base, jur) {
  if (!jur?.years) return base.years;
  const hist = new Map();
  for (const item of base.years.histogram || []) hist.set(item.year, (hist.get(item.year) || 0) + item.count);
  for (const item of jur.years.histogram || []) hist.set(item.year, (hist.get(item.year) || 0) + item.count);
  return {
    min: Math.min(base.years.min, jur.years.min),
    max: Math.max(base.years.max, jur.years.max),
    histogram: [...hist.entries()].sort((a, b) => a[0] - b[0]).map(([year, count]) => ({ year, count })),
  };
}

function mergeJurFacets(base) {
  if (!base || !state.jur.facets) return base;
  return {
    ...base,
    committees: mergeFacetItems(base.committees, jurCommitteeFacets()),
    labels: mergeFacetItems(base.labels, state.jur.facets.labels),
    years: mergeYearFacet(base, state.jur.facets),
  };
}

// ─────────── Masthead folio ───────────
function paintMastFolio(m) {
  const today = new Date().toLocaleDateString('en-GB', { day: '2-digit', month: 'long', year: 'numeric' }).toUpperCase();
  const jurDocs = state.jur.manifest?.counts?.documents || 0;
  const jurParas = state.jur.manifest?.counts?.paragraphs || 0;
  $('#mast-folio').textContent =
    `VOL. I · NO. 1 · ${today} · ${(m.counts.paragraphs + jurParas).toLocaleString()} ¶ · ${m.counts.documents + jurDocs} DOCUMENTS`;
  $('#foot-version').textContent = `Build ${m.version} · ${m.builtAt.split('T')[0]}`;
  paintFreshnessCard(m);
}

// Freshness card — green/amber/red traffic light on the About tab.
// Reads manifest.builtAt; "amber" after 30 days, "red" after 60. Surfaces
// total paragraph count and the latest GC + JUR + SP build dates. Adapted
// from UHRI's dashboard-methodology.js renderFreshnessCard() pattern but
// driven entirely from our static manifest (no API).
function paintFreshnessCard(m) {
  const card = $('#freshness-card');
  if (!card || !m?.builtAt) return;

  const built = new Date(m.builtAt);
  const ageDays = Math.max(0, Math.round((Date.now() - built.getTime()) / 86_400_000));
  const tone = ageDays < 30 ? 'fresh'
             : ageDays < 60 ? 'aging'
             : 'stale';
  const dateLabel = built.toLocaleDateString('en-GB', { day: '2-digit', month: 'long', year: 'numeric' });

  const jurBuilt = state.jur.manifest?.builtAt
    ? new Date(state.jur.manifest.builtAt).toLocaleDateString('en-GB', { day: '2-digit', month: 'long', year: 'numeric' })
    : null;
  const jurDocs = state.jur.manifest?.counts?.documents || 0;
  const jurParas = state.jur.manifest?.counts?.paragraphs || 0;
  const totalDocs = (m.counts.documents || 0) + jurDocs;
  const totalParas = (m.counts.paragraphs || 0) + jurParas;
  const ageWord = ageDays === 0 ? 'today' : (ageDays === 1 ? 'yesterday' : `${ageDays} days ago`);
  const linksLabel = m.counts.linksVerified
    ? ` · ${m.counts.linksVerified}/${m.counts.linksTotal || m.counts.linksVerified} URLs OK`
    : '';

  card.hidden = false;
  card.className = `freshness-card freshness-${tone}`;
  card.innerHTML = `
    <div class="freshness-dot" aria-hidden="true"></div>
    <div class="freshness-body">
      <div class="folio">Dataset freshness</div>
      <div class="freshness-headline">
        <strong>Built ${ageWord}</strong>
        <span class="freshness-date">· ${escape(dateLabel)}</span>
      </div>
      <div class="freshness-meta">
        ${totalParas.toLocaleString()} paragraphs across ${totalDocs.toLocaleString()} documents${linksLabel}.
        ${jurBuilt ? `Jurisprudence preview shard built ${escape(jurBuilt)}.` : ''}
        Weekly link revalidation runs via
        <a href="https://github.com/lszoszk/generalcomments/blob/main/.github/workflows/link-check.yml"
           target="_blank" rel="noopener">GitHub Actions</a>.
      </div>
    </div>`;
}

// ─────────── Scope counts ───────────
function paintScopeCounts() {
  const m = state.manifest.counts;
  $('#count-gc').textContent = m.gcDocuments;
  $('#count-jur').textContent = state.jur.manifest
    ? `${state.jur.manifest.counts.documents} · ${jurTreatyLabel({ compact: true })}`
    : '—';
  $('#count-sp').textContent = `${m.spDocuments} · 4 mandates`;
}

// ─────────── State restoration from URL ───────────
function applyUrlState(parsed) {
  // Scope
  const validScope = ['gc', 'jur', 'sp', 'all'].includes(parsed.scope) ? parsed.scope : 'gc';
  state.scope = validScope;
  $$('.scope-opt').forEach(b => {
    const on = b.dataset.scope === validScope;
    b.classList.toggle('is-active', on);
    b.setAttribute('aria-selected', on ? 'true' : 'false');
  });
  $('#scope-meta').textContent = {
    gc:  'Treaty body output · near-hard-law',
    jur: `Treaty body jurisprudence · ${jurTreatyLabel()} preview`,
    sp:  'Mandate-holder reports · soft law · preview',
    all: 'Combined view',
  }[validScope];

  // Query
  state.query = parsed.query;
  $('#q').value = parsed.query;
  syncClearChip();

  // Committees & labels — only keep values that exist in current facets
  const validCommittees = new Set(state.facets.committees.map(c => c.value));
  const validLabels = new Set(state.facets.labels.map(l => l.value));
  state.filters.committees = new Set(parsed.committees.filter(c => validCommittees.has(c)));
  state.filters.labels = new Set(parsed.labels.filter(l => validLabels.has(l)));
  state.filters.labelsMode = parsed.labelsMode;

  // Report types and superseded toggle
  const validReportTypes = new Set((state.facets.reportTypes || []).map(r => r.value));
  state.filters.reportTypes = new Set((parsed.reportTypes || []).filter(r => validReportTypes.has(r)));
  state.filters.showSuperseded = !!parsed.showSuperseded;

  // JUR state-party filter — only meaningful when jurisprudence is in scope.
  const jurCountrySet = computeJurCountryFacet().map(c => c.value);
  const validCountries = new Set(jurCountrySet);
  state.filters.countries = new Set((parsed.countries || []).filter(c => validCountries.has(c)));

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
  if (['paragraphs', 'documents', 'bodies'].includes(parsed.resultGroup)) {
    state.resultGroup = parsed.resultGroup;
    state.resultGroupUserSet = true;     // explicit URL choice — keep on scope switch
  } else {
    // v19.10 introduced a JUR-specific default of "documents"; reverted in
    // v19.11.1 because the new shorter result-rendering already addresses
    // the original motivation (overwhelming first-page paint), and the
    // special case made JUR feel inconsistent with GC and SP. Now every
    // scope defaults to "paragraphs" unless the URL specifies otherwise.
    state.resultGroup = 'paragraphs';
  }
  syncResultsControls();

  // v19.12: search-in-footnotes preference. URL > localStorage > default(ON).
  if (parsed.searchInFootnotesUrl) {
    state.searchInFootnotes = parsed.searchInFootnotes;
  } else {
    // localStorage stores the raw string '0' or '1' (no JSON wrapping) so
    // a fresh user with no key reads as `null`, which we treat as ON.
    let ls = null;
    try { ls = localStorage.getItem(_LS.searchInFn); } catch {}
    state.searchInFootnotes = ls !== '0';
  }
  syncFnToggleControl();

  // Active paragraph
  state.activeId = parsed.activeId;
}

// v19.12: keep the operators-row chip's visual state synchronized with
// state.searchInFootnotes. Called whenever the value changes (URL apply,
// click handler, programmatic toggle).
function syncFnToggleControl() {
  const btn = document.getElementById('fn-toggle');
  if (!btn) return;
  const on = state.searchInFootnotes !== false;
  btn.classList.toggle('is-on', on);
  btn.setAttribute('aria-pressed', String(on));
  const mark = btn.querySelector('.op-toggle-mark');
  if (mark) mark.textContent = on ? '✓' : '✗';
  btn.title = on
    ? 'Footnote text is included in search. Click to toggle off and search paragraph bodies only.'
    : 'Search is restricted to paragraph bodies (footnotes excluded). Click to include footnotes.';
}

// ─────────── Hash router (Search / Documents / About) ───────────
const VIEWS = ['search', 'documents', 'about', 'workspace'];

function viewFromHash() {
  const h = window.location.hash.replace(/^#/, '');
  // v17: "#documents/<docId>" → still the documents view; the deep-link
  // segment is stripped here and re-parsed inside paintDocumentsView.
  const root = h.split('/')[0];
  return VIEWS.includes(root) ? root : 'search';
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
  if (view === 'workspace') renderWorkspace();
  // 'about' is static HTML, no paint needed
  // 'search' results are kept in DOM after boot, no need to repaint

  updateDocumentTitle();
}

function bindRouter() {
  window.addEventListener('hashchange', () => setView(viewFromHash()));
}

// ─────────── Documents view (v17 · 3-pane reader: rail · body · drawer) ───────────
//
// Architecture
//  - LEFT RAIL (#docs-rail-list): a filter-aware list of every document,
//    grouped by treaty body / mandate. Click → opens the doc in the body.
//  - CENTRE (#docs-reader-body): full document text. Every paragraph
//    rendered with a sticky ¶ marker that toggles bookmark / activates
//    drawer. Long docs scroll inside the pane.
//  - RIGHT DRAWER (#docs-drawer): outline (jump-to-¶), workspace tools
//    (bookmark / note / pin / cite), document-level export. Collapsible
//    to a 32 px strip via the » button.
//
// URL contract
//   #documents                      → reader empty, rail visible
//   #documents/<docId>              → that doc opened
//   #documents/<docId>?p=<paraId>   → doc opened, scroll to paragraph
function paintDocumentsView() {
  paintDocsRail();
  // If the URL has a doc target, honour it; otherwise render empty state.
  const target = parseDocsHash();
  if (target.docId) {
    openDocReader(target.docId, { paraId: target.paraId, fromUrl: true });
  } else {
    $('#docs-reader-body').innerHTML = `
      <div class="docs-reader-empty">
        <div class="folio garnet">SELECT A DOCUMENT</div>
        <p class="serif" style="font-style: italic; color: var(--ink-3);">
          Pick any document from the rail on the left to read its full text.
          Bookmarks, notes and citations stay attached to specific paragraphs.
        </p>
      </div>`;
    $('#docs-drawer').hidden = true;
  }
}

// Parse "#documents/<docId>" optionally combined with "?p=<paraId>".
function parseDocsHash() {
  const hash = window.location.hash.replace(/^#/, '');                 // "documents/<docId>"
  const m = hash.match(/^documents\/(.+)$/);
  const docId = m ? decodeURIComponent(m[1]) : null;
  const paraId = new URLSearchParams(window.location.search).get('p');
  // Only honour ?p when it actually belongs to the docId we're opening,
  // otherwise ignore (it's probably a search-view share URL).
  const paraOk = docId && paraId && paraId.startsWith(docId + '-');
  return { docId, paraId: paraOk ? paraId : null };
}

function paintDocsRail() {
  const host = $('#docs-rail-list');
  const headTitle = $('#docs-title');
  const headSub = $('#docs-sub');
  if (!host) return;

  const wantScope = state.docsScope;
  const filterText = state.docsFilter.trim().toLowerCase();

  const docs = [...state.documents.values()].filter(d => {
    if (wantScope === 'gc' && d.type !== 'gc') return false;
    if (wantScope === 'jur' && d.type !== 'jur') return false;
    if (wantScope === 'sp' && d.type !== 'sp') return false;
    if (filterText) {
      const haystack = `${d.name} ${d.signature} ${d.year ?? ''} ${d.committee} ${d.mandate ?? ''} ${d.country ?? ''} ${d.outcome ?? ''}`.toLowerCase();
      if (!haystack.includes(filterText)) return false;
    }
    return true;
  });

  const gcDocs = docs.filter(d => d.type === 'gc').length;
  const jurDocs = docs.filter(d => d.type === 'jur').length;
  const spDocs = docs.filter(d => d.type === 'sp').length;
  if (headTitle) headTitle.textContent = `${docs.length.toLocaleString()} document${docs.length === 1 ? '' : 's'}`;
  if (headSub) headSub.innerHTML = `${gcDocs} General Comment${gcDocs === 1 ? '' : 's'} · ${jurDocs} Jurisprudence case${jurDocs === 1 ? '' : 's'} <span class="badge badge-jur">PREVIEW</span> · ${spDocs} Special Procedures report${spDocs === 1 ? '' : 's'} <span class="badge badge-preview">PREVIEW</span>`;

  if (!docs.length) {
    host.innerHTML = '<div class="docs-rail-empty">No documents match the current filter.</div>';
    return;
  }

  // type → committee → docs (newest first)
  const groups = { gc: new Map(), jur: new Map(), sp: new Map() };
  for (const d of docs) {
    const bucket = groups[d.type];
    if (!bucket) continue;
    if (!bucket.has(d.committee)) bucket.set(d.committee, []);
    bucket.get(d.committee).push(d);
  }
  for (const t of ['gc', 'jur', 'sp']) {
    for (const list of groups[t].values()) {
      list.sort((a, b) => (b.year ?? 0) - (a.year ?? 0));
    }
  }
  const sortedCommittees = (bucket) =>
    [...bucket.keys()].sort((a, b) => bucket.get(b).length - bucket.get(a).length || a.localeCompare(b));

  const html = [];
  if (groups.gc.size && (wantScope === 'all' || wantScope === 'gc')) {
    html.push('<div class="docs-rail-section">General Comments</div>');
    for (const c of sortedCommittees(groups.gc)) html.push(renderRailCommittee(c, groups.gc.get(c), 'gc'));
  }
  if (groups.jur.size && (wantScope === 'all' || wantScope === 'jur')) {
    html.push(`<div class="docs-rail-section jur">${escape(jurTreatyLabel())} jurisprudence <span class="badge badge-jur">PREVIEW</span></div>`);
    for (const c of sortedCommittees(groups.jur)) html.push(renderRailCommittee(c, groups.jur.get(c), 'jur'));
  }
  if (groups.sp.size && (wantScope === 'all' || wantScope === 'sp')) {
    html.push('<div class="docs-rail-section sp">Special Procedures <span class="badge badge-preview">PREVIEW</span></div>');
    for (const c of sortedCommittees(groups.sp)) html.push(renderRailCommittee(c, groups.sp.get(c), 'sp'));
  }
  host.innerHTML = html.join('');

  // Click handler — single delegation, no per-row listeners.
  host.querySelectorAll('.docs-rail-row').forEach(a => {
    a.addEventListener('click', (e) => {
      e.preventDefault();
      const docId = a.dataset.docId;
      if (docId) openDocReader(docId);
    });
  });
}

function renderRailCommittee(committee, list, type) {
  const collapseKey = `${type}::${committee}`;
  const open = !state.docsRailCollapsed.has(collapseKey);
  const rows = list.map(d => {
    const isActive = state.docsActiveDocId === d.docId;
    const statusBadge = d.status === 'superseded' ? '<span class="docs-status superseded">superseded</span>'
                      : d.status === 'revised'   ? '<span class="docs-status revised">revised</span>' : '';
    return `
      <a class="docs-rail-row ${type} ${isActive ? 'is-active' : ''}"
         href="#documents/${encodeURIComponent(d.docId)}"
         data-doc-id="${escape(d.docId)}">
        <span class="docs-rail-row-sig mono">${escape(d.signature || d.symbol || '—')}</span>
        <span class="docs-rail-row-title">${escape(d.nameShort || d.name || d.docId)}${statusBadge}</span>
        <span class="docs-rail-row-meta mono">${d.year ?? '—'} · ${d.paragraphCount ?? 0}¶</span>
      </a>`;
  }).join('');
  return `
    <details class="docs-rail-committee ${type}" ${open ? 'open' : ''} data-collapse-key="${escape(collapseKey)}">
      <summary>
        <span class="docs-rail-committee-name">${escape(committee)}</span>
        <span class="docs-rail-committee-count">${list.length}</span>
      </summary>
      <div class="docs-rail-rows">${rows}</div>
    </details>`;
}

// ─── Reader: open a document ─────────────────────────────────────────────
//
// Loads JUR shards on demand, paints the centre body, sets the URL, and
// seeds the right drawer.  Reusable: search-view code can also call this
// when the user wants to "read the whole document".
async function openDocReader(docId, { paraId = null, fromUrl = false } = {}) {
  const doc = state.documents.get(docId);
  if (!doc) {
    console.warn('[openDocReader] unknown docId', docId);
    return;
  }

  // JUR paragraphs live in lazy shards; pull if needed.
  if (doc.type === 'jur' && !state.jur.loaded) {
    try {
      $('#docs-reader-body').innerHTML = '<div class="docs-reader-loading">Loading jurisprudence shard…</div>';
      await loadJurCorpus();
    } catch (e) { console.warn('[jur load failed]', e); }
  }

  state.docsActiveDocId = docId;
  state.docsActiveParaId = paraId;

  // URL: keep the user's deep link alive on reload / share.
  if (!fromUrl) {
    const url = new URL(window.location);
    url.hash = `documents/${encodeURIComponent(docId)}`;
    if (paraId) url.searchParams.set('p', paraId); else url.searchParams.delete('p');
    window.history.replaceState(null, '', url.toString());
  }

  paintDocReaderBody(doc, paraId);
  paintDocDrawer(doc);
  // Keep rail row in sync (highlight new active row).
  paintDocsRail();
  // v19.6 (B1): tab <title> reflects the open doc.
  updateDocumentTitle();
  // Scroll the rail so the active row is visible.
  document.querySelector('.docs-rail-row.is-active')?.scrollIntoView({ block: 'nearest', behavior: 'instant' });
}

function paintDocReaderBody(doc, paraId) {
  const host = $('#docs-reader-body');
  if (!host) return;

  const paragraphs = state.paragraphs.filter(p => p.docId === doc.docId);
  if (!paragraphs.length) {
    host.innerHTML = `
      <div class="docs-reader-empty">
        <div class="folio garnet">DOCUMENT BODY UNAVAILABLE</div>
        <p class="serif">The text for ${escape(doc.nameShort || doc.name || doc.docId)} is not loaded.
        ${doc.type === 'jur' ? 'Try reopening — the jurisprudence shard may not have fetched.' : ''}</p>
      </div>`;
    return;
  }

  const head = `
    <header class="docs-reader-head">
      <div class="folio garnet">${escape(formatDocHeadline(doc, { compact: true }))}</div>
      <h1 class="docs-reader-title">${escape(doc.name || doc.nameShort || doc.docId)}</h1>
      <div class="docs-reader-meta mono">
        ${doc.signature ? `<span>${escape(doc.signature)}</span>` : ''}
        ${doc.adoptionDate ? `<span>${escape(doc.adoptionDate)}</span>` : (doc.year ? `<span>${doc.year}</span>` : '')}
        ${doc.country ? `<span>${escape(doc.country)}</span>` : ''}
        ${doc.committee || doc.treaty ? `<span>${escape(doc.committee || doc.treaty)}</span>` : ''}
        <span>${paragraphs.length} paragraphs</span>
        ${doc.link ? `<a href="${escape(doc.link)}" target="_blank" rel="noopener" class="docs-reader-source">↗ original</a>` : ''}
      </div>
    </header>`;

  const body = paragraphs.map(p => {
    const marker = p.n != null ? `¶${escape(String(p.n))}` : `¶${p.idx}`;
    const isActive = p.id === paraId;
    const isBm = bmHas(p.id);
    const isPin = pinHas(p.id);
    const hasNote = noteHas(p.id);
    const sectionHead = p.section
      ? `<h3 class="docs-reader-section">${escape(p.section)}</h3>`
      : '';
    return `
      ${sectionHead}
      <div class="docs-reader-para ${isActive ? 'is-active' : ''}" id="reader-para-${escape(p.id)}" data-para-id="${escape(p.id)}">
        <div class="docs-reader-para-marker">
          <span class="mono">${marker}</span>
          <button class="docs-para-bm ${isBm ? 'on' : ''}" data-act="bm" title="${isBm ? 'Remove bookmark' : 'Bookmark this paragraph'}">${isBm ? '★' : '☆'}</button>
          <button class="docs-para-pin ${isPin ? 'on' : ''}" data-act="pin" title="${isPin ? 'Unpin' : 'Pin for compare'}">📌</button>
          <button class="docs-para-cite" data-act="cite" title="Cite this paragraph">”</button>
          <button class="docs-para-link" data-act="link" title="Copy permalink to this paragraph">🔗</button>
          <button class="docs-para-flag" data-act="flag" title="Report a problem with this paragraph">⚐</button>
          ${hasNote ? '<span class="docs-para-note-flag" title="You have a note on this paragraph">📝</span>' : ''}
        </div>
        <p class="docs-reader-para-text serif">${renderParagraphHtml(p.text, p.footnotes)}</p>
      </div>`;
  }).join('');

  host.innerHTML = head + `<div class="docs-reader-stream">${body}</div>`;

  // Per-paragraph click handlers (delegated by data-act).
  host.querySelectorAll('.docs-reader-para').forEach(el => {
    const id = el.dataset.paraId;
    el.addEventListener('click', (e) => {
      // Footnote markers: open popover, swallow further handling so the
      // paragraph doesn't re-paint underneath us.
      const fn = e.target.closest('button.fn-marker');
      if (fn) {
        e.stopPropagation();
        e.preventDefault();
        openFnPopover(fn);
        return;
      }
      const btn = e.target.closest('button[data-act]');
      if (btn) {
        e.stopPropagation();
        if (btn.dataset.act === 'bm')  { bmToggle(id); paintWorkspaceBadge(); }
        if (btn.dataset.act === 'pin') { pinToggle(id); paintDiffTray(); }
        if (btn.dataset.act === 'cite') {
          // v19.16: one-click cite using the user's preferred format
          // (set via the docs-drawer <details> Cite menu). Mid-panels
          // never open a chooser — that's the drawer's job.
          const para = state.paragraphById.get(id);
          if (para) copyCiteWithPref(btn, para);
          return;                                  // skip the re-paint
        }
        if (btn.dataset.act === 'flag') {
          // v19.14: open the report modal pre-populated with this
          // paragraph's context so a curator-level reader can flag
          // issues without losing their place in the doc.
          const para = state.paragraphById.get(id);
          openReportModal({ paraId: id, docId: para?.docId });
          return;
        }
        if (btn.dataset.act === 'link') {
          // v19.15: copy a permalink to clipboard.
          const para = state.paragraphById.get(id);
          if (para) copyPermalink(para);
          return;
        }
        // Re-paint just this paragraph row + drawer.
        state.docsActiveParaId = id;
        paintDocReaderBody(doc, id);
        paintDocDrawer(doc);
        return;
      }
      // Plain click → make this the active paragraph (drawer follows).
      state.docsActiveParaId = id;
      paintDocReaderBody(doc, id);
      paintDocDrawer(doc);
      const url = new URL(window.location);
      url.searchParams.set('p', id);
      window.history.replaceState(null, '', url.toString());
    });
  });

  // If we have a target ¶, scroll it into view (centre of the pane).
  if (paraId) {
    const el = host.querySelector(`#reader-para-${CSS.escape(paraId)}`);
    if (el) {
      // Wait one tick so layout is settled before scrolling.
      requestAnimationFrame(() => el.scrollIntoView({ block: 'center', behavior: 'instant' }));
    }
  }
}

function paintDocDrawer(doc) {
  const drawer = $('#docs-drawer');
  const body = $('#docs-drawer-body');
  if (!drawer || !body) return;
  drawer.hidden = false;
  drawer.classList.toggle('is-collapsed', state.docsDrawerCollapsed);

  if (state.docsDrawerCollapsed) {
    body.innerHTML = '';
    return;
  }

  const paraId = state.docsActiveParaId;
  const para = paraId ? state.paragraphById.get(paraId) : null;
  const paragraphs = state.paragraphs.filter(p => p.docId === doc.docId);

  // Outline: any paragraph with a section, or a numbered ¶ as fallback.
  const outline = paragraphs.filter(p => p.section).map(p => ({
    id: p.id, label: p.section, n: p.n,
  }));

  const outlineHtml = outline.length
    ? `<ol class="docs-outline-list">${
        outline.map(o => `
          <li><a class="docs-outline-link" href="#" data-jump="${escape(o.id)}">
            <span class="mono">¶${escape(String(o.n ?? '—'))}</span>
            <span>${escape(o.label)}</span>
          </a></li>`).join('')
      }</ol>`
    : '<p class="serif dim" style="font-size:12px">No headings detected — every paragraph is reachable from the body.</p>';

  // Workspace + cite block (only meaningful when a paragraph is active).
  const wsHtml = para ? `
    <div class="docs-drawer-block">
      <h3 class="folio">Active paragraph</h3>
      <div class="docs-drawer-active mono">${escape(para.id)}${para.n != null ? ` · ¶${escape(String(para.n))}` : ''}</div>
      <div class="docs-drawer-actions">
        <button class="btn btn-ghost" id="dw-bm" type="button">${bmHas(para.id) ? '★ Bookmarked' : '☆ Bookmark'}</button>
      </div>
      <textarea class="docs-drawer-note serif" id="dw-note" rows="3"
                placeholder="Private note — autosaved per paragraph.">${escape(noteGet(para.id) || '')}</textarea>
      <details class="docs-drawer-cite">
        <summary class="btn btn-ghost">”  Cite this paragraph</summary>
        <div class="docs-drawer-cite-pop">
          ${(() => { const pk = getPrefCiteFmt(); return CITE_FORMATS.map(c => `
            <button type="button" class="cite-opt ${c.key === pk ? 'is-default' : ''}" data-cite-key="${c.key}">
              <span class="cite-fmt">${escape(c.fmt)}</span>
              <span class="cite-name">${escape(c.name)}</span>
            </button>`).join(''); })()}
        </div>
      </details>
    </div>` : '<div class="docs-drawer-block"><p class="serif dim" style="font-size:12px">Click any paragraph to bookmark, note, pin or cite it.</p></div>';

  body.innerHTML = `
    <div class="docs-drawer-block">
      <h3 class="folio">Outline</h3>
      ${outlineHtml}
    </div>
    ${wsHtml}
    <div class="docs-drawer-block">
      <h3 class="folio">Open in search</h3>
      <a class="btn btn-ghost" href="?p=${encodeURIComponent(paragraphs[0]?.id || '')}#search">↗ Switch to search view</a>
    </div>`;

  // Collapse button.
  $('#docs-drawer-collapse')?.addEventListener('click', () => {
    state.docsDrawerCollapsed = !state.docsDrawerCollapsed;
    paintDocDrawer(doc);
  });

  // Outline jump links — scroll the centre pane.
  body.querySelectorAll('.docs-outline-link').forEach(a => {
    a.addEventListener('click', (e) => {
      e.preventDefault();
      const id = a.dataset.jump;
      state.docsActiveParaId = id;
      paintDocReaderBody(doc, id);
      paintDocDrawer(doc);
      const url = new URL(window.location);
      url.searchParams.set('p', id);
      window.history.replaceState(null, '', url.toString());
    });
  });

  if (para) {
    $('#dw-bm')?.addEventListener('click', () => { bmToggle(para.id); paintDocReaderBody(doc, para.id); paintDocDrawer(doc); paintWorkspaceBadge(); });
    // v19.15: dw-pin removed — pinning lives on the per-¶ row in the
    // reader body (📌 button next to ☆/cite/flag), so the drawer doesn't
    // duplicate the affordance.

    const noteTa = $('#dw-note');
    if (noteTa) {
      let t;
      const save = () => { noteSet(para.id, noteTa.value); paintWorkspaceBadge(); };
      noteTa.addEventListener('input', () => { clearTimeout(t); t = setTimeout(save, 600); });
      noteTa.addEventListener('blur',  () => { clearTimeout(t); save(); });
    }

    // Cite menu
    body.querySelectorAll('.docs-drawer-cite .cite-opt').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const fmt = CITE_FORMATS.find(f => f.key === btn.dataset.citeKey);
        if (!fmt) return;
        const cite = fmt.build(doc, para);
        try { navigator.clipboard?.writeText(cite); } catch {}
        // v19.16: drawer click persists choice as the one-click default.
        setPrefCiteFmt(fmt.key);
        body.querySelectorAll('.docs-drawer-cite .cite-opt').forEach(b => b.classList.remove('is-default'));
        btn.classList.add('is-default');
        const lbl = btn.querySelector('.cite-fmt');
        const orig = lbl.textContent;
        lbl.textContent = '✓';
        setTimeout(() => { lbl.textContent = orig; }, 1100);
      });
    });
  }
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

  const baseCommittees = state.baseFacets?.committees || state.facets.committees;
  const tb = baseCommittees.filter(c => !isSp(c.value));
  const sp = baseCommittees.filter(c => isSp(c.value));
  const jur = jurCommitteeFacets();

  tbHost.innerHTML = '';
  spHost.innerHTML = '';

  if (scope === 'gc') {
    sectionLabel.textContent = 'Treaty bodies';
    subSection.hidden = true;
    paintCommitteeChips(tbHost, tb);
  } else if (scope === 'jur') {
    sectionLabel.textContent = 'Jurisprudence treaty body';
    subSection.hidden = true;
    paintCommitteeChips(tbHost, jur, 'jur-chip');
  } else if (scope === 'sp') {
    sectionLabel.textContent = 'Mandates';
    subSection.hidden = true;
    paintCommitteeChips(tbHost, sp);
  } else {
    sectionLabel.textContent = 'Treaty bodies';
    subSection.hidden = false;
    paintCommitteeChips(tbHost, mergeFacetItems(tb, jur));
    paintCommitteeChips(spHost, sp);
  }
}

function paintCommitteeChips(container, items, toneClass = '') {
  for (const { value, count } of items) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'chip';
    if (isSp(value)) b.classList.add('sp-chip');
    if (toneClass) b.classList.add(toneClass);
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

// SP report-type filter — small set of values
function paintReportTypeFilter() {
  const host = $('#filter-reporttypes');
  if (!host) return;
  const facet = state.facets.reportTypes || [];
  host.innerHTML = '';
  // Friendly labels
  const niceLabel = {
    'thematic': 'Thematic',
    'annual': 'Annual to UNGA',
    'communications': 'Communications',
    'addendum': 'Addendum',
    'country-visit': 'Country visit',
    'other': 'Other',
  };
  for (const item of facet) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'chip chip-compact';
    b.dataset.value = item.value;
    b.innerHTML = `${escape(niceLabel[item.value] || item.value)} <span class="chip-count">${item.count}</span>`;
    if (state.filters.reportTypes.has(item.value)) b.classList.add('on');
    b.addEventListener('click', () => {
      if (state.filters.reportTypes.has(item.value)) {
        state.filters.reportTypes.delete(item.value);
      } else {
        state.filters.reportTypes.add(item.value);
      }
      paintReportTypeFilter();
      runSearch();
    });
    host.appendChild(b);
  }
}

// Status filter — supersede toggle
function paintStatusFilter() {
  const cb = $('#filter-show-superseded');
  const cnt = $('#filter-superseded-count');
  if (!cb || !state.facets) return;
  const supEntry = (state.facets.statuses || []).find(s => s.value === 'superseded');
  const n = supEntry ? supEntry.count : 0;
  if (cnt) cnt.textContent = n ? `+${n} hidden` : '';
  cb.checked = state.filters.showSuperseded;
  // Bind once — guard via dataset flag
  if (!cb.dataset.bound) {
    cb.dataset.bound = '1';
    cb.addEventListener('change', () => {
      state.filters.showSuperseded = cb.checked;
      paintStatusFilter();
      runSearch();
    });
  }
}

// Show or hide the SP report-type filter based on scope
function syncReportTypeFilterVisibility() {
  const block = $('#filter-block-reporttype');
  if (!block) return;
  block.hidden = !(state.scope === 'sp' || state.scope === 'all');
}

// JUR-only state-party filter. The country list is derived from the loaded
// jurisprudence catalog (state.documents) — we don't ship a precomputed
// facet for it. Only displayed when scope === 'jur'.
function computeJurCountryFacet() {
  const counts = new Map();
  for (const d of state.documents.values()) {
    if (d.type !== 'jur' || !d.country) continue;
    counts.set(d.country, (counts.get(d.country) || 0) + (d.paragraphCount || 1));
  }
  return [...counts.entries()]
    .map(([value, count]) => ({ value, count }))
    .sort((a, b) => (b.count - a.count) || a.value.localeCompare(b.value));
}

function paintCountryFilter() {
  const host = $('#filter-countries');
  const counter = $('#filter-country-count');
  if (!host) return;
  const facet = computeJurCountryFacet();
  if (counter) counter.textContent = facet.length ? `${facet.length} states` : '';
  host.innerHTML = '';
  for (const { value, count } of facet) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'chip chip-compact jur-chip';
    if (state.filters.countries.has(value)) b.classList.add('on');
    b.dataset.country = value;
    b.innerHTML = `${escape(value)} <span class="chip-count">${count.toLocaleString()}</span>`;
    b.addEventListener('click', () => {
      if (state.filters.countries.has(value)) state.filters.countries.delete(value);
      else state.filters.countries.add(value);
      b.classList.toggle('on');
      runSearch();
    });
    host.appendChild(b);
  }
}

// Show the JUR state-party filter only when jurisprudence is in scope.
// We hide it on 'all' too — country values would be meaningless next to
// GC + SP paragraphs that don't carry country.
function syncCountryFilterVisibility() {
  const block = $('#filter-block-country');
  if (!block) return;
  block.hidden = state.scope !== 'jur';
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
  // v19.6 (A2): explicit slider ARIA. Native <input type="range">
  // already has implicit role="slider" + valuemin/max/now derived
  // from min/max/value, but axe-core's aria-required-attr rule wants
  // them spelled out + aria-valuetext to read like "1960" instead of
  // raw "min: 1960; max: 1960" some screen readers concoct.
  syncYearSliderAria(lo, min, max, lo.value);
  syncYearSliderAria(hi, min, max, hi.value);
  paintYearFill();
  paintYearHistogram();
}

function syncYearSliderAria(el, min, max, val) {
  el.setAttribute('aria-valuemin',  String(min));
  el.setAttribute('aria-valuemax',  String(max));
  el.setAttribute('aria-valuenow',  String(val));
  el.setAttribute('aria-valuetext', String(val));
}

// ─────────── UI bindings ───────────
// v18.1: minimum query length before we kick the FlexSearch index. Typing
// 1–3 chars (the JUR scope hits ~40k+ candidates) noticeably stutters on
// older laptops and pegs the main thread; the user sees keystrokes lag.
// 4 chars is the sweet spot — the index returns useful candidates and
// per-key cost stays under one frame.
const MIN_QUERY = 4;

function bindUI() {
  // Search input (debounced)
  let t;
  const qInput = $('#q');
  const qClear = $('#q-clear');
  qInput.addEventListener('input', e => {
    clearTimeout(t);
    syncClearChip();
    const v = e.target.value.trim();
    if (v.length === 0 || v.length >= MIN_QUERY) {
      t = setTimeout(() => {
        state.query = v;
        runSearch();
      }, 180);
    } else {
      // 1–3 chars: don't run the index. Show a tiny inline "keep typing"
      // hint where the result count usually lives so the user understands.
      state.query = v;                        // keep state in sync for URL
      paintShortQueryHint(v);
    }
  });
  qInput.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && qInput.value) {
      e.preventDefault();
      qInput.value = '';
      state.query = '';
      syncClearChip();
      runSearch();
    }
  });
  qClear?.addEventListener('click', () => {
    qInput.value = '';
    state.query = '';
    syncClearChip();
    runSearch();
    qInput.focus();
  });

  // v19.17 (recommendation D): always-accessible search-syntax help.
  // The empty-state card already shows a brief cheatsheet, but only
  // when the query yields 0 hits — useless for the larger UX class
  // of "I'm getting too many results, how do I narrow?". The ? button
  // exposes operators + clickable examples + tips on demand.
  $('#q-help')?.addEventListener('click', (e) => {
    e.stopPropagation();
    const trigger = e.currentTarget;
    if (trigger.getAttribute('aria-expanded') === 'true') {
      closeQueryHelpPopover();
    } else {
      openQueryHelpPopover(trigger);
    }
  });

  // Suggestions
  $$('.suggest').forEach(b => b.addEventListener('click', () => {
    $('#q').value = b.dataset.q;
    state.query = b.dataset.q;
    syncClearChip();
    runSearch();
  }));

  // v19.12: footnote-search toggle in the operators row.
  document.getElementById('fn-toggle')?.addEventListener('click', () => {
    state.searchInFootnotes = !state.searchInFootnotes;
    try { localStorage.setItem(_LS.searchInFn, state.searchInFootnotes ? '1' : '0'); } catch {}
    syncFnToggleControl();
    scheduleUrlUpdate();
    runSearch();
  });

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
    state.resultGroupUserSet = true;     // freeze auto-switch on scope changes
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
    // Country filter is JUR-only — drop the chips when leaving the jur tab
    // so a stale state-party doesn't silently zero out GC/SP results.
    if (state.scope !== 'jur' && state.filters.countries.size) {
      state.filters.countries.clear();
    }
    paintCommitteeFilter(state.scope);
    syncReportTypeFilterVisibility();
    syncCountryFilterVisibility();

    // v19.10: jurisprudence has 3,100+ documents and 111k paragraphs, so
    // the default "Paragraphs" view dumps a wall of weakly-related rows on
    // a cold tab switch. Group by document by default — much more useful,
    // far fewer DOM nodes. The user's explicit choice (clicked the
    // segmented control) wins via state.resultGroupUserSet.
    if (!state.resultGroupUserSet) {
      const targetGroup = state.scope === 'jur' ? 'documents' : 'paragraphs';
      if (state.resultGroup !== targetGroup) {
        state.resultGroup = targetGroup;
        $$('#result-group .result-opt').forEach(x => {
          x.classList.toggle('is-active', x.dataset.group === targetGroup);
          x.setAttribute('aria-pressed', x.dataset.group === targetGroup ? 'true' : 'false');
        });
      }
    }

    const meta = {
      gc:  'Treaty body output · near-hard-law',
      jur: `Treaty body jurisprudence · ${jurTreatyLabel()} preview`,
      sp:  'Mandate-holder reports · soft law · preview',
      all: 'Combined view',
    }[state.scope];
    $('#scope-meta').textContent = meta;

    if (state.scope === 'jur' && !state.bannerShownForJur) {
      paintScopeBanner('jur');
      $('#scope-banner').hidden = false;
      state.bannerShownForJur = true;
    }
    if (state.scope === 'sp' && !state.bannerShownForSp) {
      paintScopeBanner('sp');
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

  // B5 Save search — name it, store URL with name, surface in Workspace
  $('#save-search')?.addEventListener('click', () => {
    encodeUrlState();
    const defaultName = state.query
      ? `"${state.query.slice(0, 40)}${state.query.length > 40 ? '…' : ''}"`
      : `${state.scope.toUpperCase()} search`;
    const name = window.prompt('Name this saved search:', defaultName);
    if (!name) return;
    // Persist the URL with #search so that a direct browser-history visit
    // also lands on the search view (the workspace renderer intercepts the
    // click in-app, but the saved entry should also be a valid bookmark URL).
    ssAdd(name, window.location.pathname + window.location.search + '#search');
    const btn = $('#save-search');
    if (btn) {
      const lbl = btn.querySelector('.copy-link-label');
      if (lbl) {
        const orig = lbl.textContent;
        lbl.textContent = 'Saved ✓';
        setTimeout(() => { lbl.textContent = orig; }, 1500);
      }
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
    state.filters.reportTypes.clear();
    state.filters.countries.clear();
    state.filters.showSuperseded = false;
    state.filters.labelsMode = 'any';
    state.filters.yearMin = state.facets.years.min;
    state.filters.yearMax = state.facets.years.max;
    $$('#filter-committees .chip, #filter-mandates .chip, #filter-countries .chip').forEach(c => c.classList.remove('on'));
    $$('#filter-labels input').forEach(i => i.checked = false);
    $$('#labels-mode .aa-opt').forEach(x => x.classList.toggle('is-active', x.dataset.mode === 'any'));
    $('#year-min').value = state.facets.years.min;
    $('#year-max').value = state.facets.years.max;
    paintYearFill();
    paintReportTypeFilter();
    paintStatusFilter();
    paintCountryFilter();
    runSearch();
  });

  // Theme toggle. v19.6 (B3): persist to localStorage so the
  // preference survives reload. Boot-time restore is in initThemePref()
  // — runs before paintMastFolio so we don't see a light→dark flicker.
  $('#theme-toggle').addEventListener('click', () => {
    const cur = document.documentElement.getAttribute('data-theme');
    const next = cur === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    try { localStorage.setItem(_LS.theme, next); } catch {}
  });

  // Documents view: scope segmented + filter input.
  // v17 — these only re-render the rail; the centre + drawer keep showing
  // the currently-open doc so changing scope/filter doesn't kick the user
  // out of their reading position.
  $$('.docs-scope-opt').forEach(b => b.addEventListener('click', () => {
    $$('.docs-scope-opt').forEach(x => x.classList.remove('is-active'));
    b.classList.add('is-active');
    state.docsScope = b.dataset.docsScope;
    paintDocsRail();
  }));
  let docsFilterTimer;
  $('#docs-filter')?.addEventListener('input', e => {
    clearTimeout(docsFilterTimer);
    docsFilterTimer = setTimeout(() => {
      state.docsFilter = e.target.value;
      paintDocsRail();
    }, 150);
  });

  // v19.3: report-a-problem affordance in the footer + Esc / backdrop close
  // on the modal. The actual submit handler lives in openReportModal()
  // because it needs to know the current paragraph context at click time.
  $('#foot-report')?.addEventListener('click', () => openReportModal());
  $('#report-modal .report-modal-backdrop')?.addEventListener('click', closeReportModal);
  $('#report-modal .report-modal-close')?.addEventListener('click', closeReportModal);
  $('#report-modal .report-cancel')?.addEventListener('click', closeReportModal);
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !$('#report-modal')?.hidden) closeReportModal();
  });
  $('#report-form')?.addEventListener('submit', submitReport);
  $('#report-message')?.addEventListener('input', _updateReportCharcount);
}

function scopeCommitteeSet(scope) {
  const baseCommittees = state.baseFacets?.committees || state.facets.committees;
  if (scope === 'gc') return new Set(baseCommittees.filter(c => !isSp(c.value)).map(c => c.value));
  if (scope === 'jur') return new Set(jurCommitteeFacets().map(c => c.value));
  if (scope === 'sp') return new Set(baseCommittees.filter(c => isSp(c.value)).map(c => c.value));
  return new Set(mergeFacetItems(baseCommittees, jurCommitteeFacets()).map(c => c.value));
}

// ─────────── Export ───────────
// Exports always reflect the current filtered/searched results, never the whole corpus.

function buildExportRows() {
  return state.results.map(({ p }, idx) => {
    const doc = state.documents.get(p.docId);
    const isJur = p.type === 'jur';
    const articleStr = (a) => {
      let s = a.article;
      if (a.paragraph) s += `(${a.paragraph}${a.subparagraph ? ')(' + a.subparagraph : ''})`;
      else if (a.subparagraph) s += `(${a.subparagraph})`;
      return s;
    };
    const articlesParsed = isJur ? [
      ...(doc?.covenantArticlesParsed || []),
      ...(doc?.conventionArticlesParsed || []),
      ...(doc?.optionalProtocolArticlesParsed || []),
    ] : [];
    return {
      rank: idx + 1,
      type: p.type,
      doc_id: p.docId,
      doc_name: doc?.name ?? '',
      doc_short_name: doc?.nameShort ?? '',
      signature: doc?.signature ?? '',
      committee: p.committee || p.treaty || doc?.committee || '',
      committees: (p.committees || []).join(' · '),
      country: p.country || doc?.country || '',
      outcome: p.outcome || doc?.outcome || '',
      section: p.section || '',
      year: p.year ?? '',
      adoption_date: doc?.adoptionDate ?? '',
      communication_date: isJur ? (doc?.communicationDate ?? '') : '',
      mandate_holder: doc?.mandate ?? '',
      paragraph_id: p.id,
      paragraph_n: p.n ?? '',
      paragraph_text: p.text,
      labels: (p.labels || []).join('; '),
      // JUR-only enriched metadata. Non-JUR rows leave these blank so the
      // CSV header is stable across mixed-scope exports.
      case_name: isJur ? (doc?.caseName ?? '') : '',
      case_name_source: isJur ? (doc?.caseNameSource ?? '') : '',
      submitted_by: isJur ? (doc?.submittedByClean || doc?.submittedBy || '') : '',
      representation: isJur ? (doc?.representation ?? '') : '',
      alleged_victims: isJur ? (doc?.allegedVictims ?? '') : '',
      state_party: isJur ? (doc?.stateParty ?? '') : '',
      subject_matter: isJur ? (Array.isArray(doc?.subjectMatter) ? doc.subjectMatter.join('; ') : (doc?.subjectMatter ?? '')) : '',
      substantive_issues: isJur ? ((doc?.substantiveIssues || []).join('; ')) : '',
      procedural_issues: isJur ? ((doc?.proceduralIssues || []).join('; ')) : '',
      articles_invoked: isJur ? articlesParsed.map(articleStr).join('; ') : '',
      articles_invoked_raw: isJur ? [doc?.covenantArticles, doc?.conventionArticles, doc?.optionalProtocolArticles].filter(Boolean).join(' | ') : '',
      metadata_confidence: isJur ? (doc?.metadataConfidence ?? '') : '',
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
    ['UN Human Rights Database — search export'],
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
function paintScopeBanner(scope = 'sp') {
  if (scope === 'jur') {
    const docs = state.jur.manifest?.counts?.documents || 0;
    const paras = state.jur.manifest?.counts?.paragraphs || 0;
    const treatyLabel = jurTreatyLabel();
    const banner = $('#scope-banner');
    banner.innerHTML = `
      <button class="banner-dismiss" id="banner-dismiss" aria-label="Dismiss">×</button>
      <span class="folio">JURISPRUDENCE PREVIEW</span>Treaty Body jurisprudence currently includes ${escape(treatyLabel)}: <strong>${docs} cases</strong> and <strong>${paras.toLocaleString()} paragraphs</strong>. The full corpus stays sharded and can move to the VM/API once the preview UI is settled.
    `;
    $('#banner-dismiss').addEventListener('click', () => { banner.hidden = true; });
    return;
  }

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
  lo.addEventListener('change', () => { runSearch(); paintYearHistogram(); });
  hi.addEventListener('change', () => { runSearch(); paintYearHistogram(); });
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
  // v19.6 (A2): keep aria-valuenow / aria-valuetext in sync with the
  // visual values. Some screen readers cache the initial values and
  // never re-poll, so the explicit attribute write is meaningful.
  const lo = $('#year-min'), hi = $('#year-max');
  if (lo) syncYearSliderAria(lo, min, max, state.filters.yearMin);
  if (hi) syncYearSliderAria(hi, min, max, state.filters.yearMax);
}

// ─────────── Query parsing (boolean) ───────────
//
// Recursive-descent parser for the query language:
//
//   query     := orExpr
//   orExpr    := andExpr ( ('OR' | '|') andExpr )*
//   andExpr   := notExpr ( ('AND' | '&') notExpr )*    ← also implicit AND on whitespace
//   notExpr   := ('NOT' | '-' | '!') term | term
//   term      := '(' orExpr ')' | '"' phrase '"' | bareWord
//
// `bareWord` may end in a single `*` for prefix-matching (FlexSearch handles
// the index lookup; smartSnippet/_findBestCluster mirror the semantics).
//
// Output is an AST consumed by evaluateQuery() — leaf form
//   { kind: 'phrase'|'word', value, prefix?: true }
// internal form
//   { kind: 'and'|'or', items: [...] } | { kind: 'not', item: ... }
//
// Backwards-compat: a query with no operators behaves exactly as before
// (phrases AND'd with bare words, OR groups when "or" appears between terms).
function parseQuery(raw) {
  if (!raw || !raw.trim()) return null;
  const tokens = _tokenizeQuery(raw);
  if (!tokens.length) return null;
  const ctx = { tokens, pos: 0 };
  const ast = _parseOr(ctx);
  return ast;
}

function _tokenizeQuery(raw) {
  // Yield a flat list of: ('AND'|'OR'|'NOT'|'('|')'|{phrase}|{word, prefix?})
  const out = [];
  let i = 0;
  const s = raw;
  while (i < s.length) {
    const c = s[i];
    if (/\s/.test(c)) { i++; continue; }
    if (c === '(') { out.push({ t: '(' }); i++; continue; }
    if (c === ')') { out.push({ t: ')' }); i++; continue; }
    if (c === '"') {
      let j = i + 1;
      while (j < s.length && s[j] !== '"') j++;
      const phrase = s.slice(i + 1, j).trim().toLowerCase();
      if (phrase) out.push({ t: 'phrase', value: phrase });
      i = j + 1;
      continue;
    }
    if (c === '-' || c === '!') {
      // Unary NOT prefix when followed by a term, not a stray operator
      const next = s[i + 1];
      if (next && next !== ' ' && next !== ')' && next !== '-' && next !== '!') {
        out.push({ t: 'NOT' });
        i++;
        continue;
      }
    }
    // Bare word — consume up to whitespace / paren
    let j = i;
    while (j < s.length && !/[\s()]/.test(s[j])) j++;
    const word = s.slice(i, j);
    const lower = word.toLowerCase();
    if (lower === 'and' || lower === '&') {
      out.push({ t: 'AND' });
    } else if (lower === 'or' || lower === '|') {
      out.push({ t: 'OR' });
    } else if (lower === 'not') {
      out.push({ t: 'NOT' });
    } else if (lower) {
      const prefix = lower.endsWith('*') && lower.length > 1;
      out.push({ t: 'word', value: prefix ? lower.slice(0, -1) : lower, prefix });
    }
    i = j;
  }
  return out;
}

function _peek(ctx) { return ctx.tokens[ctx.pos]; }
function _eat(ctx)  { return ctx.tokens[ctx.pos++]; }

function _parseOr(ctx) {
  const items = [_parseAnd(ctx)];
  while (_peek(ctx)?.t === 'OR') { _eat(ctx); items.push(_parseAnd(ctx)); }
  return items.length === 1 ? items[0] : { kind: 'or', items };
}
function _parseAnd(ctx) {
  const items = [_parseNot(ctx)];
  while (_peek(ctx) && _peek(ctx).t !== 'OR' && _peek(ctx).t !== ')') {
    if (_peek(ctx).t === 'AND') _eat(ctx);            // explicit AND
    items.push(_parseNot(ctx));                       // or implicit AND
  }
  // Drop nulls that would crash evaluation (defensive — happens on stray tokens)
  const cleaned = items.filter(Boolean);
  return cleaned.length === 1 ? cleaned[0] : { kind: 'and', items: cleaned };
}
function _parseNot(ctx) {
  if (_peek(ctx)?.t === 'NOT') { _eat(ctx); return { kind: 'not', item: _parseTerm(ctx) }; }
  return _parseTerm(ctx);
}
function _parseTerm(ctx) {
  const tok = _eat(ctx);
  if (!tok) return null;
  if (tok.t === '(') {
    const inner = _parseOr(ctx);
    if (_peek(ctx)?.t === ')') _eat(ctx);
    return inner;
  }
  if (tok.t === 'phrase') return { kind: 'phrase', value: tok.value };
  if (tok.t === 'word')   return { kind: 'word', value: tok.value, prefix: !!tok.prefix };
  // Stray operator at term position — treat as no-op
  return null;
}

// Walk the AST and collect every leaf (used for highlighting + KWIC).
// Skips the children of NOT nodes — those terms must NOT be highlighted.
function leafTermsForHighlight(ast) {
  const out = [];
  const walk = (n, inNot) => {
    if (!n) return;
    if (n.kind === 'word' || n.kind === 'phrase') {
      if (!inNot) out.push(n);
    } else if (n.kind === 'not') {
      walk(n.item, true);
    } else if (n.kind === 'and' || n.kind === 'or') {
      for (const c of n.items) walk(c, inNot);
    }
  };
  walk(ast, false);
  return out;
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
    // v19.8: index `text` (marker-stripped body) AND `fnText` (concatenated
    // footnote bodies). FlexSearch uses BM25-ish scoring; default field
    // weights are equal which matches the user's desired UX (footnote hits
    // should surface, but the renderer downranks them visually with the
    // "match in citation" pill rather than via index weighting).
    document: { id: 'id', index: ['text', 'fnText'] },
    tokenize: 'forward',
    charset: 'latin:simple',
    cache: 100,
  });

  // Try to restore from IndexedDB. v19.8: tests that seed synthetic
  // footnotes via the corpus.json fetch interceptor set
  // `__unhrdbDisableIdxCache` so the cached (pre-seed) index isn't reused.
  // Production paths leave this flag false → caching behaves as before.
  const skipCache = typeof window !== 'undefined' && window.__unhrdbDisableIdxCache === true;
  const cached = !skipCache && sha ? await idbGet(cacheKey) : null;
  if (cached && Array.isArray(cached) && cached.length) {
    try {
      for (const [key, value] of cached) state.searchIndex.import(key, value);
      return;
    } catch (e) {
      console.warn('Index restore failed, rebuilding…', e);
    }
  }

  // Build fresh — feed marker-stripped text to the index so [[fn:N]] tokens
  // never become search hits (only the surrounding prose does).
  const t0 = performance.now();
  for (const p of state.paragraphs) {
    const fnText = (p.footnotes && p.footnotes.length)
      ? p.footnotes.map(f => f.text || '').join(' ')
      : '';
    state.searchIndex.add({
      id: p.id,
      text: stripFnMarkers(p.text),
      fnText,
    });
  }
  console.info(`FlexSearch built in ${(performance.now() - t0).toFixed(0)} ms`);

  // Serialise to IDB after a brief idle (don't block first paint).
  if (sha && !skipCache) {
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
// v19.12: when state.searchInFootnotes is false, restrict the index to the
// `text` field so footnote text never matches. Default behaviour is to
// query both fields (text + fnText) for citation-aware coverage.
function flexSearchIds(query) {
  if (!state.searchIndex || !query) return null;
  const opts = { limit: 5000, suggest: false };
  if (state.searchInFootnotes === false) opts.field = ['text'];
  const hits = state.searchIndex.search(query, opts);
  const ids = new Set();
  for (const field of hits) for (const id of field.result) ids.add(id);
  return ids;
}

// Words too common to use as a phrase narrowing constraint. They appear in
// most paragraphs, so searching for them just saturates the FlexSearch limit
// and then truncation drops legitimate phrase matches from the AND-intersection.
const PHRASE_NARROW_STOPWORDS = new Set([
  'a', 'an', 'the', 'and', 'or', 'but', 'nor', 'so', 'yet',
  'of', 'to', 'in', 'on', 'at', 'by', 'for', 'with', 'from', 'as', 'into',
  'is', 'are', 'was', 'were', 'be', 'been', 'being',
  'has', 'have', 'had', 'do', 'does', 'did',
  'this', 'that', 'these', 'those', 'such',
  'it', 'its', 'their', 'his', 'her', 'they', 'them', 'we', 'us',
  'no', 'not', 'any', 'all',
]);

// ─────────── AST → candidate id evaluation ───────────
// Walks the parsed AST and returns a Set of paragraph ids (or null = unbounded).
// Phrases and prefix wildcards delegate to FlexSearch where possible; phrases
// are re-verified later as substrings (FlexSearch tokenises by word).
function evaluateAstToIds(ast) {
  if (!ast) return null;
  if (ast.kind === 'word') {
    if (ast.prefix) {
      // Prefix wildcard — find every term in the index whose prefix matches.
      // FlexSearch supports `suggest:true` natively but we do a simple
      // bare-word query (the tokenizer's stemming already covers most cases);
      // for explicit prefix, we scan candidate terms client-side.
      return flexSearchPrefixIds(ast.value);
    }
    return flexSearchIds(ast.value);
  }
  if (ast.kind === 'phrase') {
    // Treat each non-stop word as an AND constraint; the substring re-check
    // in runSearch's body filter eliminates word-order false positives.
    //
    // Two narrowing pitfalls we explicitly avoid:
    //
    //   1. STOPWORDS — words like "and", "of", "the" appear in nearly every
    //      paragraph. Searching for them returns the FlexSearch limit (5000)
    //      truncated arbitrarily, so the AND-intersection drops paragraphs
    //      that genuinely contain the phrase. Symptom: `"will and preferences"`
    //      returns 0 matches even though `will and preferences` (no quotes)
    //      finds them. We skip these from index narrowing entirely; the
    //      paragraph-body substring check still enforces the exact phrase.
    //
    //   2. CAP-SATURATED RESULTS — even non-stopwords (e.g. "rights") can
    //      saturate the limit in larger corpora (jurisprudence + SP after
    //      lazy-load). When a word's hits reach the limit we treat it as
    //      "doesn't help narrow" rather than letting truncation eat
    //      legitimate matches.
    const FLEX_LIMIT_WAS = 5000;
    const words = ast.value.split(/\s+/)
      .filter(w => w.length >= 2 && !PHRASE_NARROW_STOPWORDS.has(w));
    let ids = null;
    for (const w of words) {
      const wIds = flexSearchIds(w);
      if (!wIds || wIds.size === 0) continue;
      if (wIds.size >= FLEX_LIMIT_WAS) continue;          // truncated → skip
      ids = ids ? new Set([...ids].filter(id => wIds.has(id))) : wIds;
    }
    return ids;       // null = unconstrained — paragraphMatchesAst still verifies
  }
  if (ast.kind === 'and') {
    let ids = null;
    for (const child of ast.items) {
      // NOT children don't narrow at index time — handled in body filter.
      if (child?.kind === 'not') continue;
      const childIds = evaluateAstToIds(child);
      if (childIds == null) continue;
      ids = ids ? new Set([...ids].filter(id => childIds.has(id))) : childIds;
    }
    return ids;
  }
  if (ast.kind === 'or') {
    const all = new Set();
    for (const child of ast.items) {
      const childIds = evaluateAstToIds(child);
      if (childIds == null) return null;          // unbounded OR can't narrow
      for (const id of childIds) all.add(id);
    }
    return all;
  }
  if (ast.kind === 'not') {
    return null;                                  // NOT alone is unbounded
  }
  return null;
}

// Final per-paragraph match check against the AST. Every leaf does a strict
// substring/regex match — the FlexSearch index does the cheap up-front
// narrowing, but the body filter is what actually verifies a result. The
// strict check is required for correctness inside NOT subtrees: an
// optimistic "accept all word leaves" makes NOT(word) always false, which
// silently breaks queries like `A AND B NOT (C)` even when matches exist.
function paragraphMatchesAst(text, ast) {
  if (!ast) return true;
  if (ast.kind === 'word') {
    if (ast.prefix) {
      const re = new RegExp('\\b' + escapeRegex(ast.value) + '\\w*', 'i');
      return re.test(text);
    }
    return text.includes(ast.value);
  }
  if (ast.kind === 'phrase') {
    return text.includes(ast.value);
  }
  if (ast.kind === 'and') {
    return ast.items.every(c => paragraphMatchesAst(text, c));
  }
  if (ast.kind === 'or') {
    return ast.items.some(c => paragraphMatchesAst(text, c));
  }
  if (ast.kind === 'not') {
    return !paragraphMatchesAst(text, ast.item);
  }
  return true;
}

function escapeRegex(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }

// Prefix-wildcard helper: take every paragraph whose tokenized text contains
// a word starting with `prefix`. Implemented as a substring scan on top of a
// pre-tokenized lower text — simpler than reaching into FlexSearch internals.
function flexSearchPrefixIds(prefix) {
  if (!prefix || prefix.length < 1) return new Set();
  const re = new RegExp('\\b' + escapeRegex(prefix), 'i');
  const ids = new Set();
  for (const p of state.paragraphs) {
    if (re.test(p.text)) ids.add(p.id);
  }
  return ids;
}

// ─────────── Lazy jurisprudence loader ───────────
async function ensureScopeLoaded(scope) {
  if (scope !== 'jur' && scope !== 'all') return;
  if (!state.jur.manifest || state.jur.loaded) return;
  if (!state.jur.loading) {
    state.jur.loading = loadJurCorpus().finally(() => { state.jur.loading = null; });
  }
  return state.jur.loading;
}

async function loadJurCorpus() {
  $('#results-title').textContent = 'Loading jurisprudence preview…';
  $('#results-sub').textContent = 'Fetching jurisprudence case paragraphs.';

  const shardNames = Object.keys(state.jur.manifest.files || {})
    .filter(name => name.startsWith('shards/'))
    .sort();

  const loadedParagraphs = [];
  for (const shardName of shardNames) {
    const shard = await fetchJson(`${JUR_BASE}${shardName}`);
    for (const p of shard.paragraphs || []) {
      const doc = state.documents.get(p.docId);
      loadedParagraphs.push({
        ...p,
        type: 'jur',
        labels: p.labels || [],
        committee: doc?.committee || p.treaty || 'Jurisprudence',
        committees: doc?.committees || (p.treaty ? [p.treaty] : ['Jurisprudence']),
        year: p.year ?? doc?.year ?? null,
        n: p.n ?? p.paragraphId ?? p.idx,
      });
    }
  }

  for (const p of loadedParagraphs) {
    state.paragraphs.push(p);
    state.paragraphById.set(p.id, p);
    state.searchIndex?.add({ id: p.id, text: p.text });
  }

  state.jur.loaded = true;
  state.jur.error = null;
  _flushDfCache();
  _avgDocLen = null;
  paintScopeCounts();
  if (state.view === 'documents') paintDocumentsView();
}

// ─────────── Document-frequency cache (for BM25-lite IDF) ───────────
//
// IDF (inverse document frequency) for a term is log(N / (df + 1)) where
// N is the total paragraph count and df is the number of paragraphs
// containing the term. Computing df naïvely on every keystroke is O(N×|q|),
// so we memoize per term. Cache invalidates when scope changes (the term's
// df differs across GC-only / SP-only / All).
const _dfCache = new Map();   // key: `${scope}|${prefix?'p':'w'}|${value}` → df
function _docFreq(term, scope) {
  const key = `${scope}|${term.prefix ? 'p' : 'w'}|${term.value}`;
  if (_dfCache.has(key)) return _dfCache.get(key);
  let df = 0;
  const matcher = term.prefix
    ? new RegExp('\\b' + escapeRegex(term.value) + '\\w*', 'i')
    : null;
  for (const p of state.paragraphs) {
    if (!paragraphInScope(p, scope)) continue;
    const text = p.text.toLowerCase();
    if (term.prefix ? matcher.test(text) : text.includes(term.value)) df++;
  }
  _dfCache.set(key, df);
  return df;
}
// Stub flushed when corpus reloads (scope-keyed key auto-handles scope flips).
function _flushDfCache() { _dfCache.clear(); }

// BM25-lite parameters. Standard BM25 is k1·(occ·(k1+1))/(occ+k1·(1-b+b·|d|/avgdl))
// — we want the scoring to feel familiar, so we keep classic constants.
const BM25_K1 = 1.5;
const BM25_B  = 0.75;
let _avgDocLen = null;
function _avgDocLength(scope) {
  // Recompute lazily, scope-aware. Cheap (one pass over paragraphs).
  if (_avgDocLen && _avgDocLen.scope === scope) return _avgDocLen.value;
  let total = 0, n = 0;
  for (const p of state.paragraphs) {
    if (!paragraphInScope(p, scope)) continue;
    total += p.text.length;
    n++;
  }
  const value = n ? total / n : 1;
  _avgDocLen = { scope, value };
  return value;
}

function paragraphInScope(p, scope) {
  return scope === 'all' ? true : p.type === scope;
}

// ─────────── Search ───────────
// v18.1: hint shown while the user is still typing the first 1–3 chars.
// We don't yet have a result set; tell them how many more chars to add.
function paintShortQueryHint(v) {
  const count = $('#result-count');
  const title = $('#results-title');
  const sub   = $('#results-sub');
  const list  = $('#result-list');
  const more  = $('#result-more');
  const need = MIN_QUERY - v.length;
  if (count) count.textContent = `${need}+ chars`;
  if (title) title.textContent = `Keep typing — at least ${MIN_QUERY} characters`;
  if (sub)   sub.textContent = `Searching kicks in once your query is at least ${MIN_QUERY} characters long. This keeps the page snappy on the larger jurisprudence index.`;
  if (list)  list.innerHTML = '';
  if (more)  more.textContent = '';
}

async function runSearch() {
  const runId = ++state.searchRun;
  scheduleUrlUpdate();

  // v19.11: if the boot-time ping is still in flight when JUR/all needs
  // to choose between API vs local, give it a brief grace window. This
  // avoids speculatively firing an API search that times out 5 s later
  // when the VM is actually unreachable. We race against a 1.5 s wall
  // so a slow ping doesn't punish the first keystroke either way.
  if (state.apiPingPromise && (state.scope === 'jur' || state.scope === 'all') && state.apiOnline === null) {
    try {
      await Promise.race([
        state.apiPingPromise,
        new Promise((resolve) => setTimeout(resolve, 1500)),
      ]);
    } catch { /* pingApi swallows its own errors */ }
    if (runId !== state.searchRun) return;
  }

  // When the API is active for this scope, bypass local FlexSearch
  // entirely. GC stays local because GC corpus fits in the browser and
  // beats any round-trip; JUR + scope=all ride the SQLite FTS5 server.
  if (apiActive(state.scope)) {
    return runSearchViaApi(runId);
  }

  try {
    await ensureScopeLoaded(state.scope);
    if (runId !== state.searchRun) return;
  } catch (err) {
    $('#results-title').textContent = 'Jurisprudence preview unavailable';
    $('#results-sub').textContent = err.message;
    console.error(err);
    return;
  }

  const ast = parseQuery(state.query);
  const f = state.filters;
  const scope = state.scope;

  // Stage 1 — narrow to candidate ids using the parsed AST. For unbounded
  // ASTs (pure NOT, single OR over wildcards, etc.) we fall back to scanning
  // every paragraph.
  let candidateIds = ast ? evaluateAstToIds(ast) : null;

  // Highlight + scoring tokens come from the AST, skipping NOT branches.
  const highlightTerms = ast ? leafTermsForHighlight(ast) : [];

  // Pre-compute per-term IDF for the current scope. Rare terms (high IDF)
  // contribute much more to the score than common ones — so a paragraph
  // matching "non-refoulement" outranks one matching "the".
  const totalDocs = state.paragraphs.filter(p =>
    paragraphInScope(p, scope)
  ).length;
  const termIdf = new Map();
  for (const term of highlightTerms) {
    if (!term.value) continue;
    const df = _docFreq(term, scope);
    // Smoothed IDF (BM25 default) — keeps the value positive even when df > N/2.
    const idf = Math.log(1 + (totalDocs - df + 0.5) / (df + 0.5));
    termIdf.set(term.value + (term.prefix ? '*' : ''), idf);
  }
  const avgDocLen = _avgDocLength(scope);

  // Stage 2 — apply structural filters + post-AST verification
  const matched = [];
  const iter = candidateIds
    ? [...candidateIds].map(id => state.paragraphById.get(id)).filter(Boolean)
    : state.paragraphs;

  for (const p of iter) {
    if (!paragraphInScope(p, scope)) continue;

    if (p.year !== null) {
      if (f.yearMin && p.year < f.yearMin) continue;
      if (f.yearMax && p.year > f.yearMax) continue;
    }

    if (f.committees.size && !p.committees.some(c => f.committees.has(c))) continue;
    // JUR-only country filter. GC/SP paragraphs lack p.country, so a
    // non-empty country filter naturally narrows the result set to jur.
    if (f.countries.size && (!p.country || !f.countries.has(p.country))) continue;
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

    // Document-level filters (look up the doc record once)
    const doc = state.documents.get(p.docId);
    if (doc) {
      // Hide superseded GCs by default
      if (!f.showSuperseded && doc.status === 'superseded') continue;
      // SP report type filter
      if (f.reportTypes.size && p.type === 'sp') {
        if (!f.reportTypes.has(doc.reportType)) continue;
      }
    }

    const text = p.text.toLowerCase();
    // v19.8: build the AST-verification haystack from BOTH body text and
    // footnote bodies so a query that hits a footnote-only term (e.g. a
    // case citation) survives the substring re-check below. BM25 scoring
    // still uses `text` only, so footnote-only hits stay ranked beneath
    // body hits — and the renderer flags them with the
    // "match in citation" pill.
    const haystack = (p.footnotes && p.footnotes.length)
      ? text + ' ' + p.footnotes.map(f => (f.text || '').toLowerCase()).join(' ')
      : text;

    // AST-level enforcement: catches NOT clauses, phrases that need exact
    // substring, and prefix wildcards. FlexSearch alone can produce
    // stemming-only matches that don't actually contain the term.
    if (ast && !paragraphMatchesAst(haystack, ast)) continue;

    // BM25-lite ranking: rare terms (high IDF) outweigh common ones; long
    // paragraphs are penalised so a 5-occurrence hit in a 200-char doc beats
    // 5 occurrences in a 2000-char doc.  This mirrors how SQLite FTS5's
    // bm25() function ranks the reference app's results without us needing
    // to ship a SQL engine to the browser.
    let score = 0;
    if (highlightTerms.length) {
      const docLen = text.length;
      const lenNorm = (1 - BM25_B) + BM25_B * (docLen / avgDocLen);
      for (const term of highlightTerms) {
        const t = term.value;
        if (!t) continue;
        const idf = termIdf.get(t + (term.prefix ? '*' : '')) || 0;
        if (idf <= 0) continue;
        let occ;
        if (term.prefix) {
          const re = new RegExp('\\b' + escapeRegex(t) + '\\w*', 'gi');
          occ = (text.match(re) || []).length;
        } else {
          occ = countOccurrences(text, t);
        }
        if (!occ) continue;
        // Standard BM25 term contribution
        score += idf * (occ * (BM25_K1 + 1)) / (occ + BM25_K1 * lenNorm);
      }
    }
    if (state.query && score === 0) score = 0.01;  // surface stem-only matches
    matched.push({ p, score });
  }

  state.results = matched;
  state.alsoTry = [];                       // v19: local path doesn't have synonyms
  state.apiTotal = null;                    // local path: state.results.length is the truth
  state.apiBreakdown = null;                // v19.6 (U2): same — count from results
  state.apiHasMore = false;                 // v19.2: no API pagination on the local path
  state.apiPageInflight = null;
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

  // Expand/collapse buttons apply to both 'documents' AND 'bodies' grouping.
  const grouped = (state.resultGroup === 'documents' || state.resultGroup === 'bodies')
                  && state.results.length > 0;
  $('#expand-groups')?.toggleAttribute('disabled', !grouped);
  $('#collapse-groups')?.toggleAttribute('disabled', !grouped);
}

function currentResultGroupDocIds() {
  const view = state.results.slice(0, RESULT_HARD_CAP);
  if (state.resultGroup === 'bodies') {
    // The collapse-set holds bodyKeys for body grouping. Mirror the keying
    // logic in renderBodyGroupedResults so collapse-all hides every header.
    const keys = new Set();
    for (const { p } of view) {
      const doc = state.documents.get(p.docId);
      if (doc?.type === 'sp')      keys.add('sp::' + (doc.mandate || 'unknown mandate'));
      else if (doc?.type === 'jur') keys.add('jur::' + (doc.treaty || doc.committee || 'unknown'));
      else                          keys.add('gc::' + (doc?.committee || doc?.committees?.[0] || 'unknown'));
    }
    return [...keys];
  }
  return [...new Set(view.map(({ p }) => p.docId))];
}

// ─────────── Render (paginated, infinite scroll) ───────────
//
// Pagination model: paintResults() does the first page; an IntersectionObserver
// at the bottom of the list appends subsequent pages as the user scrolls.
// Rendered count is held in `state.renderedCount`. Document grouping mode keeps
// its single-shot render (it's bounded by the unique-doc count which is much
// smaller than the paragraph count).
let _resultObserver = null;

function paintResults() {
  const list = $('#result-list');
  list.innerHTML = '';
  // v19: prefer the API's `total` (server-side count over the full corpus)
  // when it's set; the local `state.results.length` is clipped to the
  // API's 200-row page when running through the API path.
  const renderedTotal = state.results.length;
  const total = state.apiTotal != null ? state.apiTotal : renderedTotal;
  const clippedToApi = state.apiTotal != null && state.apiTotal > renderedTotal;
  const docCount = new Set(state.results.map(r => r.p.docId)).size;
  syncResultsControls();

  $('#result-count').textContent = `${total.toLocaleString()} ¶`;
  $('#results-title').textContent = total
    ? (clippedToApi
        ? `${total.toLocaleString()} passages — showing first ${renderedTotal.toLocaleString()} from ${docCount} document${docCount === 1 ? '' : 's'}`
        : `${total.toLocaleString()} passages from ${docCount} document${docCount === 1 ? '' : 's'}`)
    : 'No matches';
  $('#results-sub').textContent = resultSubtitle();
  $('#results-sub').appendChild(scopeNotice());
  paintResultBreakdown();

  // Empty state — render in place of the list. Provides one of three
  // tailored hints depending on what's narrowing the result set:
  //   (a) the user typed a query that nothing matched
  //   (b) filters are active that may be too narrow
  //   (c) neither — corpus / scope mismatch
  if (total === 0) {
    list.appendChild(_buildEmptyState());
    $('#result-more').textContent = '';
    paintDossier();
    return;
  }

  const ast = parseQuery(state.query);
  const allTerms = ast ? leafTermsForHighlight(ast).map(t => t.value) : [];

  // Tear down any previous observer; render mode may have changed.
  if (_resultObserver) { _resultObserver.disconnect(); _resultObserver = null; }
  state.renderedCount = 0;

  list.classList.toggle('is-grouped', state.resultGroup === 'documents' || state.resultGroup === 'bodies');
  if (state.resultGroup === 'documents') {
    // Document grouping mode renders once: there are far fewer documents than
    // paragraphs (≤359 today) and the per-group expansion is local DOM only.
    const view = state.results.slice(0, RESULT_HARD_CAP);
    renderGroupedResults(list, view, allTerms);
    state.renderedCount = view.length;
    $('#result-more').textContent = total > RESULT_HARD_CAP
      ? moreResultsText(total, view)
      : '';
  } else if (state.resultGroup === 'bodies') {
    // v16: group by treaty body / mandate. Same render budget as 'documents'.
    const view = state.results.slice(0, RESULT_HARD_CAP);
    renderBodyGroupedResults(list, view, allTerms);
    state.renderedCount = view.length;
    $('#result-more').textContent = total > RESULT_HARD_CAP
      ? moreResultsText(total, view)
      : '';
  } else {
    // Paragraph mode: append in pages of RESULT_PAGE_SIZE on scroll.
    appendNextPage(list, allTerms);
    _attachResultSentinel(list, allTerms);
  }

  // Auto-show first result in dossier
  const firstId = state.results[0]?.p.id;
  if (firstId && !state.activeId) {
    setActive(firstId);
  } else if (state.activeId && !state.results.find(r => r.p.id === state.activeId)) {
    setActive(firstId || null);
  } else {
    paintDossier();
  }
}

// Build a tailored empty-state element. Reads `state.filters` to decide
// which hints to surface and offers one-click recovery actions.
// Show/hide the inline × clear button based on input value.
function syncClearChip() {
  const btn = $('#q-clear');
  const v = $('#q')?.value || '';
  if (btn) btn.hidden = !v;
}

// Render small "GC 4,521 ¶ · SP 1,237 ¶" breakdown pills next to the
// result-count badge. Hidden when the corpus is empty or the scope is
// already filtered to a single type.
function paintResultBreakdown() {
  const wrap  = $('#result-breakdown');
  const gcPill = $('#rb-gc');
  const jurPill = $('#rb-jur');
  const spPill = $('#rb-sp');
  if (!wrap || !gcPill || !jurPill || !spPill) return;
  if (!state.results.length || state.scope !== 'all') {
    wrap.hidden = true;
    return;
  }
  // v19.6 (U2): in API mode, prefer the server-supplied breakdown so
  // the pills reflect the FULL match-set (not just the 200-row page
  // slice that we have rendered). Falls back to a local count for the
  // FlexSearch path.
  let nGc, nJur, nSp;
  if (state.apiBreakdown) {
    nGc  = state.apiBreakdown.gc  || 0;
    nJur = state.apiBreakdown.jur || 0;
    nSp  = state.apiBreakdown.sp  || 0;
  } else {
    nGc = nJur = nSp = 0;
    for (const { p } of state.results) {
      if (p.type === 'gc') nGc++;
      else if (p.type === 'jur') nJur++;
      else if (p.type === 'sp') nSp++;
    }
  }
  wrap.hidden = false;
  gcPill.hidden = nGc === 0;
  jurPill.hidden = nJur === 0;
  spPill.hidden = nSp === 0;
  gcPill.textContent = `GC ${nGc.toLocaleString()} ¶`;
  jurPill.textContent = `JUR ${nJur.toLocaleString()} ¶`;
  spPill.textContent = `SP ${nSp.toLocaleString()} ¶`;
}

function _buildEmptyState() {
  const f = state.filters;
  const q = state.query.trim();
  const li = document.createElement('li');
  li.className = 'result-empty';

  const hasNarrowingFilters =
    f.committees.size > 0 ||
    f.labels.size > 0 ||
    f.reportTypes.size > 0 ||
    f.countries.size > 0 ||
    (f.yearMin && state.facets && f.yearMin > state.facets.years.min) ||
    (f.yearMax && state.facets && f.yearMax < state.facets.years.max);

  let title, body, actions = '';

  if (q && hasNarrowingFilters) {
    title = `No paragraph matches "${escape(q)}" within the current filters`;
    body = 'Try removing one or two filters, broadening the year range, or relaxing the query operators.';
    actions = `
      <button class="btn btn-ghost" data-empty-action="clear-q">Drop the query</button>
      <button class="btn btn-ghost" data-empty-action="clear-filters">Clear all filters</button>`;
  } else if (q) {
    title = `No paragraph matches "${escape(q)}"`;
    body = 'Check the spelling, try a wildcard like <code>discriminat*</code>, or replace AND with OR for a broader search.';
    actions = `
      <button class="btn btn-ghost" data-empty-action="clear-q">Drop the query</button>`;
  } else if (hasNarrowingFilters) {
    title = 'No paragraphs match these filters';
    body = 'Your filter combination eliminated every paragraph in the corpus. Try removing some constraints.';
    actions = `
      <button class="btn btn-ghost" data-empty-action="clear-filters">Clear all filters</button>`;
  } else {
    title = 'No paragraphs in the corpus for this scope';
    body = 'Switch the scope tab above to General Comments or All sources.';
  }

  // v19: when the API returned synonym hints for a 0-result query,
  // surface them as one-click "did you also try" links. Server already
  // verified the suggested terms hit something useful in the corpus.
  const alsoTry = (state.alsoTry && state.alsoTry.length)
    ? `
      <div class="empty-also-try">
        <div class="folio">Did you also try…</div>
        <div class="empty-also-try-row">
          ${state.alsoTry.map(t => `
            <button class="btn btn-ghost" type="button" data-empty-suggest="${escape(t)}">${escape(t)}</button>
          `).join('')}
        </div>
      </div>` : '';

  li.innerHTML = `
    <div class="empty-card">
      <div class="folio garnet">SEARCH · NO RESULTS</div>
      <h3 class="serif empty-title">${title}</h3>
      <p class="serif empty-sub">${body}</p>
      ${alsoTry}
      <div class="empty-syntax">
        <div class="folio">Search syntax</div>
        <div class="empty-syntax-row">
          <code>"exact phrase"</code>·<code>A AND B</code>·<code>A OR B</code>·<code>NOT term</code>·<code>(grouping)</code>·<code>prefix*</code>
        </div>
      </div>
      ${actions ? `<div class="empty-actions">${actions}</div>` : ''}
    </div>
  `;
  // Wire any synonym-suggestion buttons.
  li.querySelectorAll('[data-empty-suggest]').forEach(btn => {
    btn.addEventListener('click', () => {
      const term = btn.dataset.emptySuggest;
      $('#q').value = term;
      state.query = term;
      runSearch();
    });
  });

  // Wire the recovery buttons (idempotent — buttons may not exist for case (d))
  li.querySelector('[data-empty-action="clear-q"]')?.addEventListener('click', () => {
    state.query = '';
    $('#q').value = '';
    runSearch();
  });
  li.querySelector('[data-empty-action="clear-filters"]')?.addEventListener('click', () => {
    $('#reset-filters')?.click();
  });
  return li;
}

// Append the next page of paragraph results into the list.
// `state.results` may be shorter than the true match-set when running
// against the API (200 rows per fetch); the IntersectionObserver tops
// it up before calling this, so by the time we slice we always have at
// least RESULT_PAGE_SIZE buffered (or are at the very end).
function appendNextPage(list, terms) {
  const total = state.results.length;
  const start = state.renderedCount;
  // First paint uses a smaller batch (RESULT_FIRST_PAGE) so the user sees
  // results sooner; the IntersectionObserver picks up the rest on scroll.
  const pageSize = start === 0 ? RESULT_FIRST_PAGE : RESULT_PAGE_SIZE;
  const end   = Math.min(start + pageSize, total, RESULT_HARD_CAP);
  if (start >= end) return false;
  const frag = document.createDocumentFragment();
  for (let i = start; i < end; i++) {
    const { p, snippetHtml } = state.results[i];
    frag.appendChild(renderResult(p, i + 1, terms, { snippetHtml }));
  }
  // Insert before the sentinel so the sentinel stays at the tail.
  const sentinel = list.querySelector('.result-sentinel');
  if (sentinel) list.insertBefore(frag, sentinel);
  else list.appendChild(frag);
  state.renderedCount = end;
  // Update tail status (showing X of Y, more on scroll, etc.)
  updateResultMore();
  return true;
}

function updateResultMore() {
  // v19.2: the source-of-truth total is state.apiTotal when we're in
  // API-paginated mode, otherwise state.results.length. Keep the
  // "End of results" copy honest in both modes.
  const buffered = state.results.length;
  const total = state.apiTotal != null ? state.apiTotal : buffered;
  const rendered = state.renderedCount;
  const more = $('#result-more');
  if (!more) return;
  if (total === 0) { more.textContent = ''; return; }
  if (rendered >= total) {
    more.textContent = total > 1
      ? `End of results · ${total.toLocaleString()} passages`
      : '';
  } else if (rendered >= RESULT_HARD_CAP) {
    more.textContent = `Showing first ${RESULT_HARD_CAP.toLocaleString()} of ${total.toLocaleString()} passages — refine your filters to narrow down.`;
  } else if (state.apiHasMore && rendered >= buffered) {
    // We've rendered every buffered row and the server has more; the
    // sentinel is about to fetch.
    more.textContent = `Loading next page from server… (${rendered.toLocaleString()} of ${total.toLocaleString()})`;
  } else {
    more.textContent = `Showing ${rendered.toLocaleString()} of ${total.toLocaleString()} passages — keep scrolling for more.`;
  }
}

function _attachResultSentinel(list, terms) {
  // Add a sentinel <li> at the end of the list and observe it.
  const sentinel = document.createElement('li');
  sentinel.className = 'result-sentinel';
  sentinel.innerHTML = '<span class="dot"></span> Loading more…';
  list.appendChild(sentinel);

  if (state.renderedCount >= state.results.length || state.renderedCount >= RESULT_HARD_CAP) {
    sentinel.style.display = 'none';
    return;
  }
  // The result list lives in a `.results` section that has its own
  // overflow-y: auto, so the **section** scrolls, not the window.
  // IntersectionObserver should handle this with a custom root, but
  // Chrome's implementation misses events when a scrollTop=… jump
  // happens inside a custom-root container in some cases. A plain
  // throttled scroll listener does what we need without the corner
  // cases.
  const scrollRoot = _findScrollAncestor(list) || window;
  const isWindow = scrollRoot === window;

  let scheduled = false;
  let teardown = null;
  let inflight = false;

  const tick = async () => {
    scheduled = false;
    if (inflight) return;
    if (sentinel.style.display === 'none') return;

    // Distance from the sentinel's top to the bottom of the scroll-root's
    // viewport. Negative = sentinel below visible area; <= 600 = the
    // 600px pre-load margin we want to honour.
    const rootBottom = isWindow ? window.innerHeight : scrollRoot.getBoundingClientRect().bottom;
    const dist = sentinel.getBoundingClientRect().top - rootBottom;
    if (dist > 600) return;

    inflight = true;
    try {
      // Loop here so that one scroll-to-bottom keeps appending pages
      // until the sentinel finally exits the 600px pre-load zone.
      let safety = 0;
      while (safety++ < 12) {
        if (sentinel.style.display === 'none') return;

        const buffered = state.results.length - state.renderedCount;
        if (state.apiHasMore && buffered <= RESULT_PAGE_SIZE) {
          sentinel.querySelector('.dot')?.classList.add('is-loading');
          await fetchNextApiPage();
          sentinel.querySelector('.dot')?.classList.remove('is-loading');
        }

        const more = appendNextPage(list, terms);
        const exhausted = !more
          || state.renderedCount >= RESULT_HARD_CAP
          || (!state.apiHasMore && state.renderedCount >= state.results.length);
        if (exhausted) {
          sentinel.style.display = 'none';
          teardown?.();
          return;
        }

        // Re-measure: did this batch push the sentinel below the
        // pre-load zone? If so, we're done until the next scroll.
        const newRootBottom = isWindow ? window.innerHeight : scrollRoot.getBoundingClientRect().bottom;
        const newDist = sentinel.getBoundingClientRect().top - newRootBottom;
        if (newDist > 600) break;
      }
    } finally {
      inflight = false;
    }
  };

  const onScroll = () => {
    if (scheduled) return;
    scheduled = true;
    setTimeout(tick, 0);                  // microtask-deferred so we coalesce a burst of events
  };

  scrollRoot.addEventListener('scroll', onScroll, { passive: true });
  // Also handle the "page already short enough that the sentinel is
  // visible at boot" case — fire one tick on mount.
  setTimeout(tick, 0);

  teardown = () => {
    scrollRoot.removeEventListener('scroll', onScroll);
    teardown = null;
  };
  // Stash on the module-level pointer so a fresh paintResults() can
  // tear this down before re-attaching.
  _resultObserver = { disconnect: () => teardown?.() };
}

// Walk up from `el` to the first ancestor whose computed overflow-y is
// auto/scroll AND that actually has scrollable content. Returns null
// (i.e. document viewport root) if nothing matches — that's the right
// fallback for layouts where the window itself scrolls.
function _findScrollAncestor(el) {
  let cur = el?.parentElement;
  while (cur && cur !== document.body) {
    const cs = getComputedStyle(cur);
    if ((cs.overflowY === 'auto' || cs.overflowY === 'scroll') &&
        cur.scrollHeight > cur.clientHeight) {
      return cur;
    }
    cur = cur.parentElement;
  }
  return null;
}

function resultSubtitle() {
  const sortText = effectiveResultSort() === 'date'
    ? hasSearchQuery()
      ? 'Sorted by date, newest first.'
      : 'Showing newest matching paragraphs.'
    : hasSearchQuery()
      ? `Sorted by relevance to "${state.query}".`
      : 'Showing newest matching paragraphs.';
  const groupText = state.resultGroup === 'documents' ? ' Grouped by document.'
                  : state.resultGroup === 'bodies'    ? ' Grouped by treaty body / mandate.'
                  : ' Paragraph view.';
  return `${sortText}${groupText} `;
}

function moreResultsText(total, view) {
  if (state.resultGroup === 'documents') {
    const docs = new Set(view.map(({ p }) => p.docId)).size;
    return `Showing top ${RESULT_HARD_CAP.toLocaleString()} paragraphs grouped into ${docs} document${docs === 1 ? '' : 's'} out of ${total.toLocaleString()} matches. Refine your filters to narrow down.`;
  }
  return `Showing first ${RESULT_HARD_CAP.toLocaleString()} of ${total.toLocaleString()}. Refine your filters to narrow down.`;
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

// v16: group by treaty body (GC + JUR) or mandate-holder (SP). Two-level
// nesting: body → documents → paragraphs. Reuses the existing per-doc
// group renderer for the inner level.
function renderBodyGroupedResults(list, view, terms) {
  const bodyGroups = new Map();   // bodyKey → { label, type, rows[] }
  view.forEach((result, idx) => {
    const doc = state.documents.get(result.p.docId);
    let bodyKey, label;
    if (doc?.type === 'sp') {
      bodyKey = 'sp::' + (doc.mandate || 'unknown mandate');
      label = doc.mandate || 'Unknown mandate';
    } else if (doc?.type === 'jur') {
      bodyKey = 'jur::' + (doc.treaty || doc.committee || 'unknown');
      label = `${doc.treaty || doc.committee || 'Unknown'} jurisprudence`;
    } else {
      bodyKey = 'gc::' + (doc?.committee || (doc?.committees?.[0]) || 'unknown');
      label = doc?.committee || doc?.committees?.[0] || 'Unknown body';
    }
    if (!bodyGroups.has(bodyKey)) {
      bodyGroups.set(bodyKey, { label, type: doc?.type || 'gc', rows: [] });
    }
    bodyGroups.get(bodyKey).rows.push({ ...result, rank: idx + 1 });
  });

  for (const [bodyKey, group] of bodyGroups) {
    list.appendChild(renderBodyGroup(bodyKey, group, terms));
  }
}

function renderBodyGroup(bodyKey, group, terms) {
  const li = document.createElement('li');
  li.className = `result-body-group ${group.type}`;
  li.dataset.bodyKey = bodyKey;

  const details = document.createElement('details');
  details.className = 'result-body-details';
  details.open = !state.collapsedDocGroups.has(bodyKey);
  details.addEventListener('toggle', () => {
    if (details.open) state.collapsedDocGroups.delete(bodyKey);
    else state.collapsedDocGroups.add(bodyKey);
  });

  const docCount = new Set(group.rows.map(r => r.p.docId)).size;
  const summary = document.createElement('summary');
  summary.innerHTML = `
    <div class="result-body-summary-main">
      ${sourceBadge(group.type)}
      <span class="result-body-summary-title">${escape(group.label)}</span>
    </div>
    <div class="result-body-summary-meta">
      <span class="match-count">${group.rows.length} ¶</span>
      <span class="folio">${docCount} doc${docCount === 1 ? '' : 's'}</span>
    </div>
  `;

  // Inner level: re-use the per-document group renderer.
  const innerList = document.createElement('ol');
  innerList.className = 'result-body-inner';
  const docMap = new Map();
  group.rows.forEach(r => {
    if (!docMap.has(r.p.docId)) docMap.set(r.p.docId, []);
    docMap.get(r.p.docId).push(r);
  });
  for (const [docId, rows] of docMap) {
    innerList.appendChild(renderResultGroup(docId, rows, terms));
  }

  details.appendChild(summary);
  details.appendChild(innerList);
  li.appendChild(details);
  return li;
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

  const badge = sourceBadge(rows[0]?.p.type);
  const bestScore = Math.max(...rows.map(r => r.score || 0));
  const scoreMeta = shouldShowRelevanceScore() && bestScore > 0
    ? `<span class="relevance-score">relevance ${bestScore.toFixed(1)}</span>`
    : '';

  const summary = document.createElement('summary');
  summary.innerHTML = `
    <div class="result-doc-summary-main">
      ${badge}
      <span class="result-doc-summary-title">${escape(formatDocHeadline(doc) || docId)}</span>
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
  if (state.scope === 'jur') {
    span.innerHTML = ` <span class="badge badge-jur">PREVIEW</span> · ${escape(jurTreatyLabel())} jurisprudence preview.`;
  } else if (state.scope === 'sp') {
    span.innerHTML = ` <span class="badge badge-preview">PREVIEW</span> · soft-law preview, 4 mandates only.`;
  } else if (state.scope === 'all') {
    span.innerHTML = ` Mixed scope: General Comments + <span class="badge badge-jur">PREVIEW</span> Jurisprudence + <span class="badge badge-preview">PREVIEW</span> Special Procedures.`;
  }
  return span;
}

function renderResult(p, rank, terms, opts = {}) {
  const doc = state.documents.get(p.docId);
  const li = document.createElement('li');
  li.className = `result fade-up ${p.type}${opts.grouped ? ' is-grouped-result' : ''}`;
  li.dataset.paraId = p.id;
  if (p.id === state.activeId) li.classList.add('is-active');

  const badge = sourceBadge(p.type);

  const labelChips = (p.labels || []).slice(0, 4).map(l => `<span class="chip">${escape(l)}</span>`).join('');
  const committeeChips = p.committees.map(c => `<span class="chip ${isSp(c) ? 'sp-chip' : p.type === 'jur' ? 'jur-chip' : ''}">${escape(c)}</span>`).join('');

  const headline = opts.grouped
    ? `
        ${badge}
        <span class="folio">MATCHED PARAGRAPH</span>
        <span class="result-spacer"></span>
        <span class="folio">${doc?.year ?? ''}</span>
      `
    : `
        ${badge}
        <span class="result-doc">${escape(formatDocHeadline(doc) || p.docId)}</span>
        <span class="result-spacer"></span>
        <span class="folio">${doc?.year ?? ''}</span>
      `;

  // Build a KWIC window when the keyword falls past the visible fold; for
  // short paragraphs and queries with no hits, smartSnippet returns the full
  // text (highlighted) untouched. When the API supplied its own snippet
  // (FTS5's snippet() with <mark> tags), prefer it — the server already
  // chose the best 24-token window around the highest-scoring match.
  // v19.8: smartSnippet receives marker-stripped text so [[fn:N]] tokens
  // never appear in snippets. The full marker text is only used inside the
  // documents reader.
  const bareText = stripFnMarkers(p.text);
  const snippet = opts.snippetHtml
    ? { html: opts.snippetHtml, isKwic: false, fullLen: bareText.length }
    : smartSnippet(bareText, terms);
  const kwicBadge = snippet.isKwic
    ? `<span class="kwic-badge" title="Keyword-in-context · click result to read full paragraph">◎ KWIC · ${snippet.fullLen.toLocaleString()} chars</span>`
    : '';

  // v19.8: detect "match in citation" — query term hit only inside a
  // footnote (visible snippet wouldn't show why). Show a small pill so the
  // user understands the match without opening the doc.
  // v19.12: only flag "match in citation" when the user has footnote-search
  // enabled. With the toggle OFF the index never returns footnote-only hits,
  // and showing the pill would be misleading.
  const matchInFn = state.searchInFootnotes !== false
    && p.footnotes && p.footnotes.length
    && hasFootnoteMatch(p, terms || [])
    && !(terms || []).some(t => bareText.toLowerCase().includes(String(t).toLowerCase()));
  const fnMatchPill = matchInFn
    ? `<span class="match-in-citation" title="Search term matched a footnote citation, not the paragraph body">◇ match in citation</span>`
    : '';

  // Workspace state for this paragraph (B1/B2/B3 indicators)
  const isBookmarked = bmHas(p.id);
  const isPinned = pinHas(p.id);
  const hasNote = noteHas(p.id);

  li.innerHTML = `
    <div class="result-margin">
      <div class="result-rank">№ ${String(rank).padStart(2, '0')}</div>
      ${p.n != null ? `<div class="result-pn">¶${p.n}</div>` : ''}
    </div>
    <div class="result-body">
      <div class="result-headline">
        ${headline}
        ${kwicBadge}
        ${fnMatchPill}
      </div>
      <p class="result-text${snippet.isKwic ? ' is-kwic' : ''}">${snippet.html}</p>
      <div class="result-meta">
        ${committeeChips}
        ${labelChips}
      </div>
    </div>
    <div class="result-aside">
      <div class="folio">Source</div>
      <div class="sig">${
        doc?.link
          ? `<a class="sig-link" href="${escape(doc.link)}" target="_blank" rel="noopener" title="Open original document on un.org" data-no-dossier="1">${escape(doc?.signature || '—')} <span class="sig-arrow" aria-hidden="true">↗</span></a>`
          : escape(doc?.signature || '—')
      }</div>
      <div class="result-marks">
        <button class="ws-mark ws-mark-bm ${isBookmarked ? 'on' : ''}" type="button"
                data-ws="bm" title="${isBookmarked ? 'Bookmarked' : 'Bookmark'}">${isBookmarked ? '★' : '☆'}</button>
        <button class="ws-mark ws-mark-pin ${isPinned ? 'on' : ''}" type="button"
                data-ws="pin" title="${pinHas(p.id) ? 'Pinned for compare' : 'Pin for compare'}">📌</button>
        <button class="ws-mark ws-mark-cite" type="button"
                data-ws="cite" title="Copy citation in your default format (change default in dossier ‟ menu)">”</button>
        ${hasNote ? '<span class="ws-mark ws-mark-note" title="You have a note on this paragraph" aria-hidden="true">📝</span>' : ''}
      </div>
    </div>
  `;
  li.addEventListener('click', (e) => {
    // v19.16: source-symbol link → opens un.org in a new tab, doesn't
    // touch the active paragraph. The browser handles the navigation;
    // we just need to bail before setActive so the dossier doesn't
    // also flip while the user is just chasing a citation.
    if (e.target.closest('.sig-link[data-no-dossier="1"]')) {
      e.stopPropagation();
      return;
    }
    // Workspace marks click: don't open the dossier, just toggle the action
    const wsBtn = e.target.closest('.ws-mark[data-ws]');
    if (wsBtn) {
      e.stopPropagation();
      if (wsBtn.dataset.ws === 'bm') bmToggle(p.id);
      else if (wsBtn.dataset.ws === 'pin') pinToggle(p.id);
      else if (wsBtn.dataset.ws === 'cite') {
        // v19.16: one-click cite — copies in the user's preferred format
        // (default 'unfn', set via the dossier-toolbar / docs-drawer
        // popover). No popover here; mid-panels are for action, not
        // choice. Tooltip on the button reflects the current pref.
        copyCiteWithPref(wsBtn, p);
        return;                                  // don't repaint marks
      }
      // Re-paint just this row's marks instead of the whole list
      const updated = renderResult(p, rank, terms, opts);
      li.replaceWith(updated);
      // Also refresh dossier if it's currently showing this paragraph
      if (state.activeId === p.id) paintDossier();
      return;
    }
    setActive(p.id);
  });
  return li;
}

function isSp(committee) {
  return committee.startsWith('SR ') || committee.startsWith('SSR');
}

function sourceBadge(type) {
  if (type === 'jur') return '<span class="badge badge-jur">PREVIEW · JUR</span>';
  if (type === 'sp') return '<span class="badge badge-sp">PREVIEW · SP</span>';
  return '<span class="badge badge-gc">GC</span>';
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

// After a workspace toggle, repaint the per-result marks (☆/📌/📝)
// so they reflect the new state without re-rendering the whole list.
function refreshResultMarks(paraId) {
  const li = document.querySelector(`.result[data-para-id="${CSS.escape(paraId)}"]`);
  if (!li) return;
  const aside = li.querySelector('.result-marks');
  if (!aside) return;
  const isBM = bmHas(paraId);
  const isPin = pinHas(paraId);
  const hasNote = noteHas(paraId);
  aside.innerHTML = `
    <button class="ws-mark ws-mark-bm ${isBM ? 'on' : ''}" type="button" data-ws="bm" title="${isBM ? 'Bookmarked' : 'Bookmark'}">${isBM ? '★' : '☆'}</button>
    <button class="ws-mark ws-mark-pin ${isPin ? 'on' : ''}" type="button" data-ws="pin" title="${isPin ? 'Pinned for compare' : 'Pin for compare'}">📌</button>
    <button class="ws-mark ws-mark-cite" type="button" data-ws="cite" title="Copy citation in your default format (change default in dossier ‟ menu)">”</button>
    ${hasNote ? '<span class="ws-mark ws-mark-note" title="You have a note on this paragraph" aria-hidden="true">📝</span>' : ''}
  `;
}

// Per-URL <title> so deep-linked pages get distinct titles in search results
// and browser history. Without this, Googlebot indexes every ?p=… URL with
// the same homepage title.
const BASE_TITLE = 'UN Human Rights Database';
function updateDocumentTitle() {
  // v19.6 (B1): when the docs reader is active, the open document's
  // title takes precedence over the search-side activeId. The docs
  // reader has its own active-paragraph state (state.docsActiveDocId
  // / docsActiveParaId) — without this branch, the tab title still
  // shows whatever was last open in the search dossier.
  if (state.view === 'documents' && state.docsActiveDocId) {
    const doc = state.documents.get(state.docsActiveDocId);
    const docTitle = doc?.nameShort || doc?.name || state.docsActiveDocId;
    document.title = `${docTitle} · UN Human Rights Database`;
    return;
  }
  const para = state.activeId ? state.paragraphById.get(state.activeId) : null;
  if (para) {
    const doc = state.documents.get(para.docId);
    const docTitle = doc?.nameShort || doc?.name || para.docId;
    document.title = `${docTitle} · UN Human Rights Database`;
    return;
  }
  if (state.query) {
    document.title = `${state.query} · UN Human Rights Database`;
    return;
  }
  document.title = BASE_TITLE;
}

// v18: brief visual feedback on a toolbar button (replaces the icon with
// a checkmark for ~900 ms). Used after Copy / paragraph-text save.
function flashToolBtn(selector, mark = '✓') {
  const btn = document.querySelector(selector);
  if (!btn) return;
  const icon = btn.querySelector('.dossier-tool-icon');
  const label = btn.querySelector('.dossier-tool-label');
  if (!icon) return;
  const origIcon = icon.textContent;
  const origLabel = label?.textContent;
  icon.textContent = mark;
  if (label) label.textContent = 'Copied';
  btn.classList.add('is-flash');
  setTimeout(() => {
    icon.textContent = origIcon;
    if (label && origLabel != null) label.textContent = origLabel;
    btn.classList.remove('is-flash');
  }, 900);
}

// ─────────── Metadata-quality feedback (jurisprudence) ───────────
// Anonymous, one-click signal so users can flag inaccurate enriched
// metadata (case name, parties, articles, etc.). Posts to /api/feedback
// fire-and-forget; the user's vote is also remembered locally so the
// strip doesn't keep nagging them on a doc they already rated.
function metaVoteGet(docId) {
  return _lsGet(_LS.metaVote, {})[docId] || null;
}
function metaVoteSet(docId, vote) {
  const all = _lsGet(_LS.metaVote, {});
  if (vote == null) delete all[docId];
  else all[docId] = vote;
  _lsSet(_LS.metaVote, all);
}
function renderMetaFeedbackStrip(docId) {
  if (!docId) return '';
  const prior = metaVoteGet(docId);
  if (prior === 'ok') {
    return `
      <div class="meta-feedback" data-doc-id="${escape(docId)}">
        <span class="meta-feedback-thanks">Thanks — you marked this metadata as accurate.</span>
        <button type="button" class="meta-feedback-btn" data-meta-vote="reset"
                title="Undo your vote">undo</button>
      </div>`;
  }
  if (prior === 'bad') {
    return `
      <div class="meta-feedback" data-doc-id="${escape(docId)}">
        <span class="meta-feedback-thanks">Thanks — flagged for review.</span>
        <button type="button" class="meta-feedback-btn" data-meta-vote="add-note"
                title="Add a one-line note describing the issue">add note</button>
        <button type="button" class="meta-feedback-btn" data-meta-vote="reset"
                title="Undo your vote">undo</button>
      </div>`;
  }
  return `
    <div class="meta-feedback" data-doc-id="${escape(docId)}">
      <span class="meta-feedback-prompt">Metadata accurate?</span>
      <button type="button" class="meta-feedback-btn" data-meta-vote="ok"
              aria-label="Looks accurate" title="Anonymous quick vote — no contact info collected">👍 looks right</button>
      <button type="button" class="meta-feedback-btn" data-meta-vote="bad"
              aria-label="Flag inaccuracy" title="Anonymous quick flag — opens an optional note field">👎 flag</button>
    </div>`;
}

async function postMetaVote(docId, vote, note) {
  const body = {
    kind: 'data',
    message: vote === 'ok'
      ? `Metadata confirmed accurate (anonymous quick vote)${note ? ' — ' + note : ''}`
      : `Metadata flagged as inaccurate (anonymous quick vote)${note ? ' — ' + note : ''}`,
    contact: null,
    docId,
    paraId: null,
  };
  try {
    await fetch(`${API_BASE}/api/feedback`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
      // Keep the vote anonymous and unblocking — fire and forget.
      keepalive: true,
    });
  } catch (e) {
    // Server may be unreachable (preview/offline). The local vote is
    // still recorded so the user sees their choice acknowledged.
    console.warn('[meta-vote] post failed:', e?.message || e);
  }
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
  // v19.13: JUR paragraphs come from the API and live ONLY in
  // state.paragraphById (hydrated by runSearchViaApi → adaptApiHit).
  // state.paragraphs is just the local GC corpus, so a `.find()` against
  // it returns nothing for JUR rows and the dossier silently bails —
  // user clicks a JUR result and nothing opens. Look up via the id-map
  // first; fall back to the local array for any code path that wrote
  // there but not into the map.
  const para = state.paragraphById.get(state.activeId)
            || state.paragraphs.find(p => p.id === state.activeId);
  if (!para) return;
  const doc = state.documents.get(para.docId);
  const isSpDoc = para.type === 'sp';
  const isJurDoc = para.type === 'jur';
  const ast = parseQuery(state.query);
  const terms = ast ? leafTermsForHighlight(ast).map(t => t.value) : [];

  // Articles + abstract hidden until manual verification of the v8 metadata
  // pass — see TODO_LATER.md "Articles & abstracts under review". Both fields
  // remain in the metadata; we just don't surface them in the dossier.
  const articlesHtml = '';
  const statusHtml = doc?.status && doc.status !== 'final'
    ? `<div class="dossier-dp"><div class="folio">Status</div><div class="v">${escape(doc.status)}${doc.supersededBy ? ` → ${escape(doc.supersededBy)}` : ''}</div></div>`
    : '';
  const abstractHtml = '';
  // Folio kind — for jurisprudence include the treaty so it reads as
  // "JURISPRUDENCE · CEDAW · PREVIEW" and pin a colourful outcome badge
  // next to it (e.g. " · VIOLATION FOUND ").
  const dossierKind = isJurDoc
    ? `JURISPRUDENCE · ${escape(doc?.treaty || 'TREATY BODY')} · PREVIEW`
    : isSpDoc
      ? 'MANDATE REPORT · PREVIEW'
      : 'GENERAL COMMENT';
  const actorLabel = isJurDoc ? 'Treaty body' : isSpDoc ? 'Mandate' : 'Committee';

  // JUR-only outcome badge — sits inside the folio line so users see the
  // case disposition before the title.
  const outcomeBadge = (isJurDoc && doc?.outcome)
    ? `<span class="outcome-badge outcome-${escape(doc.outcome)}">${escape(formatOutcome(doc.outcome))}</span>`
    : '';

  // JUR-only metadata-confidence pill. We only surface it when confidence
  // is medium or low so users know to double-check against the original
  // PDF. "high" confidence stays silent. The PDF/OCR provenance flag also
  // demotes to medium even if the front-matter parse looked clean.
  const isOcr = doc?.sourceFormat === 'pdf_ocr';
  const conf = isJurDoc ? doc?.metadataConfidence : null;
  const confTone = conf === 'low' || isOcr ? 'low' : (conf === 'medium' ? 'medium' : null);
  const confLabel = confTone === 'low'
    ? (isOcr ? 'OCR · verify' : 'Low confidence · verify')
    : (confTone === 'medium' ? 'Medium confidence' : '');
  const confTitle = confTone === 'low'
    ? 'Metadata extraction confidence is LOW. Verify case name, parties, and articles against the source PDF before citing.'
    : (confTone === 'medium'
        ? 'Metadata extraction confidence is medium. Spot-check fields against the source PDF for sensitive uses.'
        : '');
  const confidencePill = (isJurDoc && confTone)
    ? `<span class="meta-confidence-pill meta-confidence-${confTone}" title="${escape(confTitle)}">${escape(confLabel)}</span>`
    : '';

  // JUR-only Articles cited — chip strip in the grid.
  const articlesCitedHtml = (isJurDoc && Array.isArray(doc?.articlesCited) && doc.articlesCited.length)
    ? `<div class="dossier-dp dossier-dp-wide"><div class="folio">Articles cited</div><div class="v">${
        doc.articlesCited.map(a => `<span class="dossier-chip">${escape(a)}</span>`).join(' ')
      }</div></div>`
    : '';

  // JUR-only Concerned groups (case-level labels) — small chip strip.
  const caseLabelsHtml = (isJurDoc && Array.isArray(doc?.caseLabels) && doc.caseLabels.length)
    ? `<div class="dossier-dp dossier-dp-wide"><div class="folio">Concerned groups</div><div class="v">${
        doc.caseLabels.map(l => `<span class="dossier-chip dossier-chip-soft">${escape(l)}</span>`).join(' ')
      }</div></div>`
    : '';

  // JUR-only enriched front-matter metadata. Sourced from OHCHR raw files
  // and the Minnesota Human Rights Library authority layer. Each row only
  // appears when the field is non-empty in the document.
  const submittedByHtml = (isJurDoc && (doc?.submittedByClean || doc?.submittedBy))
    ? `<div class="dossier-dp dossier-dp-wide"><div class="folio">Submitted by</div><div class="v">${
        escape(doc.submittedByClean || doc.submittedBy)
      }${doc.representation ? ` <span class="dossier-rep">(${escape(doc.representation)})</span>` : ''}</div></div>`
    : '';

  const subjectMatterHtml = (isJurDoc && doc?.subjectMatter)
    ? `<div class="dossier-dp dossier-dp-wide"><div class="folio">Subject matter</div><div class="v">${
        escape(Array.isArray(doc.subjectMatter) ? doc.subjectMatter.join('; ') : doc.subjectMatter)
      }</div></div>`
    : '';

  const substantiveIssuesHtml = (isJurDoc && Array.isArray(doc?.substantiveIssues) && doc.substantiveIssues.length)
    ? `<div class="dossier-dp dossier-dp-wide"><div class="folio">Substantive issues</div><div class="v">${
        doc.substantiveIssues.map(s => `<span class="dossier-chip dossier-chip-soft">${escape(s)}</span>`).join(' ')
      }</div></div>`
    : '';

  const proceduralIssuesHtml = (isJurDoc && Array.isArray(doc?.proceduralIssues) && doc.proceduralIssues.length)
    ? `<div class="dossier-dp dossier-dp-wide"><div class="folio">Procedural issues</div><div class="v">${
        doc.proceduralIssues.map(s => `<span class="dossier-chip dossier-chip-soft">${escape(s)}</span>`).join(' ')
      }</div></div>`
    : '';

  // Articles invoked from the case header (front matter). Distinct from
  // articlesCited (which we extract from the body text). Render as
  // "Art. X(Y)(z)" chips covering covenant, convention, and OP articles.
  const formatArt = (a) => {
    let s = `Art. ${a.article}`;
    if (a.paragraph) s += `(${a.paragraph}${a.subparagraph ? ')(' + a.subparagraph : ''})`;
    else if (a.subparagraph) s += `(${a.subparagraph})`;
    return s;
  };
  const allArticles = [
    ...(doc?.covenantArticlesParsed || []),
    ...(doc?.conventionArticlesParsed || []),
    ...(doc?.optionalProtocolArticlesParsed || []),
  ];
  const articlesInvokedHtml = (isJurDoc && allArticles.length)
    ? `<div class="dossier-dp dossier-dp-wide"><div class="folio">Articles invoked</div><div class="v">${
        allArticles.map(a => `<span class="dossier-chip" title="${escape(a.instrument || '')}">${escape(formatArt(a))}</span>`).join(' ')
      }</div></div>`
    : '';

  // Country first when it's a case (the "where did this happen" anchor),
  // then outcome (already on a badge), then communication / adoption dates.
  // v15: S/M/L font-size controls live in the folio strip alongside the
  // outcome badge. Persisted preference is restored at boot.
  const currentFont = _lsGet(_LS.dossierFont, 'M');
  const fontControls = `
    <div class="dossier-font-controls" role="group" aria-label="Dossier text size">
      ${['S','M','L'].map(k => `
        <button type="button" data-font-key="${k}"
                class="${k === currentFont ? 'is-active' : ''}"
                title="Text size ${k === 'S' ? '— small' : k === 'L' ? '— large' : '— medium (default)'}">${k}</button>
      `).join('')}
    </div>`;

  host.innerHTML = `
    <div class="folio garnet dossier-folio-row">
      <span>${dossierKind}</span>
      ${outcomeBadge}
      ${confidencePill}
      ${fontControls}
    </div>
    <h3 class="dossier-title">${escape(doc?.name || para.docId)}</h3>
    <div class="dossier-sig">${
      doc?.link
        ? `<a class="dossier-sig-link" href="${escape(doc.link)}" target="_blank" rel="noopener" title="Open original document on un.org">${escape(doc?.signature || '—')} <span class="dossier-sig-arrow" aria-hidden="true">↗</span></a>`
        : escape(doc?.signature || '')
    }${
      isJurDoc && doc?.country ? ` · <span class="dossier-country">${escape(doc.country)}</span>` : ''
    }</div>
    ${abstractHtml}
    <div class="dossier-grid">
      ${isJurDoc
        ? `
          <div class="dossier-dp"><div class="folio">Adopted</div><div class="v">${escape(doc?.adoptionDate || '—')}</div></div>
          <div class="dossier-dp"><div class="folio">Communication</div><div class="v">${doc?.communicationYear ?? doc?.year ?? '—'}</div></div>
          <div class="dossier-dp"><div class="folio">Treaty body</div><div class="v">${escape(doc?.committees?.join(' · ') || doc?.treaty || '—')}</div></div>
          <div class="dossier-dp"><div class="folio">Paragraphs</div><div class="v">${doc?.paragraphCount ?? '—'}</div></div>
          ${'' /* v19.15: section moved to a breadcrumb above the quote — see dossier-breadcrumb. */}
          ${submittedByHtml}
          ${subjectMatterHtml}
          ${articlesInvokedHtml}
          ${substantiveIssuesHtml}
          ${proceduralIssuesHtml}
          ${articlesCitedHtml}
          ${caseLabelsHtml}
        `
        : `
          <div class="dossier-dp"><div class="folio">Adopted</div><div class="v">${escape(doc?.adoptionDate || '—')}</div></div>
          <div class="dossier-dp"><div class="folio">Year</div><div class="v">${doc?.year ?? '—'}</div></div>
          <div class="dossier-dp"><div class="folio">${actorLabel}</div><div class="v">${escape(doc?.committees?.join(' · ') || '—')}</div></div>
          <div class="dossier-dp"><div class="folio">Paragraphs</div><div class="v">${doc?.paragraphCount ?? '—'}</div></div>
          ${articlesHtml}
          ${statusHtml}
          ${isSpDoc && doc?.mandate ? `<div class="dossier-dp"><div class="folio">Mandate holder</div><div class="v accent">${escape(doc.mandate)}</div></div>` : ''}
          ${isSpDoc && doc?.presented ? `<div class="dossier-dp"><div class="folio">Presented</div><div class="v">${escape(doc.presented)}</div></div>` : ''}
        `}
    </div>
    ${para.section ? `<div class="dossier-breadcrumb folio" aria-label="Section">${
       String(para.section).split(/\s*[›>/]\s*/).filter(Boolean).map((seg, i, arr) =>
         `<span class="dossier-bc-seg">${escape(seg)}</span>${
           i < arr.length - 1 ? '<span class="dossier-bc-sep">›</span>' : ''
         }`
       ).join('')
     }</div>` : ''}
    <blockquote>
      <span class="pn">¶ ${para.n ?? para.idx}</span>
      <p>${renderParagraphHtml(para.text, para.footnotes, { terms })}</p>
    </blockquote>
    <div class="dossier-toolbar" role="toolbar" aria-label="Paragraph actions">
      <button class="dossier-tool ${bmHas(para.id) ? 'on' : ''}" id="ws-bookmark" type="button"
              title="${bmHas(para.id) ? 'Remove bookmark' : 'Bookmark this paragraph'}"
              aria-label="${bmHas(para.id) ? 'Remove bookmark' : 'Bookmark'}">
        <span class="dossier-tool-icon">${bmHas(para.id) ? '★' : '☆'}</span>
        <span class="dossier-tool-label">${bmHas(para.id) ? 'Saved' : 'Save'}</span>
      </button>
      <button class="dossier-tool" id="ws-copy" type="button"
              title="Copy paragraph text to clipboard"
              aria-label="Copy paragraph text">
        <span class="dossier-tool-icon">📋</span>
        <span class="dossier-tool-label">Copy</span>
      </button>
      <button class="dossier-tool ${noteHas(para.id) ? 'on' : ''}" id="ws-note-toggle" type="button"
              title="${noteHas(para.id) ? 'Edit your private note' : 'Add a private note'}"
              aria-label="${noteHas(para.id) ? 'Edit note' : 'Add note'}"
              aria-expanded="${noteHas(para.id) ? 'true' : 'false'}">
        <span class="dossier-tool-icon">📝</span>
        <span class="dossier-tool-label">Note</span>
      </button>
      <div class="dossier-tool dossier-tool-cite" id="cite-menu">
        <button class="dossier-tool-summary" id="cite-trigger" type="button"
                title="Copy citation in your preferred format"
                aria-haspopup="menu" aria-expanded="false">
          <span class="dossier-tool-icon">”</span>
          <span class="dossier-tool-label">Cite</span>
        </button>
        <div class="cite-pop" id="cite-pop" role="menu" hidden>
          ${(() => { const pk = getPrefCiteFmt(); return CITE_FORMATS.map(c => `
            <button type="button" class="cite-opt ${c.key === pk ? 'is-default' : ''}" data-cite-key="${c.key}" role="menuitem">
              <span class="cite-fmt">${escape(c.fmt)}</span>
              <span class="cite-name">${escape(c.name)}</span>
            </button>`).join(''); })()}
        </div>
      </div>
      <button class="dossier-tool" id="ws-flag" type="button"
              title="Report a problem with this paragraph (typo, wrong footnote, missing label, etc.)"
              aria-label="Report a problem">
        <span class="dossier-tool-icon">⚐</span>
        <span class="dossier-tool-label">Flag</span>
      </button>
      <button class="dossier-tool" id="ws-permalink" type="button"
              title="Copy permalink to this paragraph"
              aria-label="Copy permalink">
        <span class="dossier-tool-icon">🔗</span>
        <span class="dossier-tool-label">Link</span>
      </button>
      <button class="dossier-tool" id="ws-read" type="button"
              title="Open this paragraph in the full document (R)"
              aria-label="Open in document (R)">
        <span class="dossier-tool-icon">📖</span>
        <span class="dossier-tool-label">Read</span>
      </button>
    </div>
    <div class="dossier-note-wrap" id="ws-note-wrap" ${noteHas(para.id) ? '' : 'hidden'}>
      <textarea class="dossier-note serif" id="ws-note"
                placeholder="Private note — autosaved to this browser only."></textarea>
    </div>
    ${'' /* v19.16: standalone .dossier-original block removed — the
            same un.org link is now on the .dossier-sig line right under
            the title (more discoverable, doesn't compete with the note
            editor for vertical space). */}
    ${isJurDoc ? renderMetaFeedbackStrip(doc?.docId) : ''}
  `;

  // v19.12: footnote-marker click → singleton popover (mirrors reader UX).
  // Delegated on the dossier root so we don't rebind per-marker.
  host.querySelectorAll('button.fn-marker').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      e.preventDefault();
      openFnPopover(btn);
    });
  });

  // v19.14: Flag paragraph for triage — opens the report modal
  // pre-populated with this paragraph's full context.
  $('#ws-flag')?.addEventListener('click', () => openReportModal({ paraId: para.id, docId: para.docId }));

  // B1 Bookmark toggle
  $('#ws-bookmark')?.addEventListener('click', () => { bmToggle(para.id); paintDossier(); refreshResultMarks(para.id); });
  // B3 Pin toggle
  // v19.15: ws-pin removed from dossier toolbar — the per-result-row 📌
  // handles this without making the dossier feel cluttered.

  // v18: Copy paragraph text. Strips highlight markup, leaves a clean
  // verbatim paragraph the user can paste into their draft.
  $('#ws-copy')?.addEventListener('click', () => {
    const txt = para.text || '';
    try { navigator.clipboard?.writeText(txt); } catch {}
    flashToolBtn('#ws-copy', '✓');
  });

  // v18: Note toggle — show/hide the textarea below the toolbar.
  // The textarea autosaves whenever it has a value.
  const noteWrap = $('#ws-note-wrap');
  const noteToggle = $('#ws-note-toggle');
  noteToggle?.addEventListener('click', () => {
    const wasHidden = noteWrap.hasAttribute('hidden');
    if (wasHidden) {
      noteWrap.removeAttribute('hidden');
      noteToggle.setAttribute('aria-expanded', 'true');
      $('#ws-note')?.focus();
    } else {
      noteWrap.setAttribute('hidden', '');
      noteToggle.setAttribute('aria-expanded', 'false');
    }
  });
  // B2 Note autosave (debounced on blur + after 600 ms idle)
  const noteTa = $('#ws-note');
  if (noteTa) {
    noteTa.value = noteGet(para.id);
    let t; const save = () => {
      noteSet(para.id, noteTa.value);
      refreshResultMarks(para.id);
      paintWorkspaceBadge();
    };
    noteTa.addEventListener('input', () => { clearTimeout(t); t = setTimeout(save, 600); });
    noteTa.addEventListener('blur', () => { clearTimeout(t); save(); });
  }

  // Metadata-quality feedback handlers (jurisprudence dossier strip).
  const metaStrip = host.querySelector('.meta-feedback');
  if (metaStrip) {
    const stripDocId = metaStrip.dataset.docId;
    metaStrip.addEventListener('click', async (e) => {
      const btn = e.target.closest('[data-meta-vote]');
      if (!btn) return;
      const action = btn.dataset.metaVote;
      if (action === 'reset') {
        metaVoteSet(stripDocId, null);
        paintDossier();
        return;
      }
      if (action === 'add-note') {
        // Reuse the existing report modal so the user can leave a free-text
        // note. Pre-fill kind=data + docId so the report lands in the same
        // bucket as the quick vote.
        openReportModal({ docId: stripDocId });
        const dataKindRadio = $('#report-form input[name="kind"][value="data"]');
        if (dataKindRadio) dataKindRadio.checked = true;
        const messageBox = $('#report-message');
        if (messageBox && !messageBox.value) {
          messageBox.value = 'Metadata issue (case name / parties / articles / state party / dates):\n— ';
          messageBox.focus();
        }
        return;
      }
      if (action === 'ok' || action === 'bad') {
        metaVoteSet(stripDocId, action);
        // Fire-and-forget — no contact field, anonymous.
        postMetaVote(stripDocId, action, null);
        paintDossier();
      }
    });
  }

  // v18: Cite menu — popover toggled by the trigger button. We dropped
  // <details> in favour of explicit aria-expanded so the button can sit
  // inside a flex toolbar without summary's default styling fighting us.
  const citeRoot = $('#cite-menu');
  const citeTrigger = $('#cite-trigger');
  const citePop = $('#cite-pop');
  const closeCite = () => {
    citePop?.setAttribute('hidden', '');
    citeTrigger?.setAttribute('aria-expanded', 'false');
    citeRoot?.classList.remove('is-open');
  };
  const openCite = () => {
    citePop?.removeAttribute('hidden');
    citeTrigger?.setAttribute('aria-expanded', 'true');
    citeRoot?.classList.add('is-open');
  };
  citeTrigger?.addEventListener('click', (e) => {
    e.stopPropagation();
    citePop?.hasAttribute('hidden') ? openCite() : closeCite();
  });
  // Click-outside / Esc to close.
  document.addEventListener('click', (e) => {
    if (!citeRoot?.contains(e.target)) closeCite();
  }, { once: true });
  document.addEventListener('keydown', function escClose(e) {
    if (e.key === 'Escape' && !citePop?.hasAttribute('hidden')) {
      closeCite();
      document.removeEventListener('keydown', escClose);
    }
  });

  // Wire each citation format. Falls back to a one-liner if the user's
  // browser blocks clipboard writes (rare; e.g. file:// without a polyfill).
  $$('#cite-pop .cite-opt').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const key = btn.dataset.citeKey;
      const fmt = CITE_FORMATS.find(f => f.key === key);
      if (!fmt) return;
      const cite = fmt.build(doc, para);
      try { navigator.clipboard?.writeText(cite); } catch {}
      // v19.16: drawer click also persists the choice as the default
      // for one-click cite buttons in the middle panels. Move the ★
      // marker to the just-clicked option so the user sees the change
      // without re-rendering the popover.
      setPrefCiteFmt(fmt.key);
      $$('#cite-pop .cite-opt').forEach(b => b.classList.remove('is-default'));
      btn.classList.add('is-default');
      const label = btn.querySelector('.cite-fmt');
      const original = label.textContent;
      label.textContent = '✓ COPIED';
      setTimeout(() => {
        label.textContent = original;
        closeCite();
      }, 900);
    });
  });

  // v19.15: Read button → open the paragraph in its full document context.
  // Replaces the old `is-reading-mode` overlay (which just hid chrome
  // around the same paragraph the user already had on screen).
  $('#ws-read')?.addEventListener('click', () => openInDocReader(para));
  // v19.15: Permalink button → copy a deep-link to clipboard.
  $('#ws-permalink')?.addEventListener('click', () => copyPermalink(para));

  // v15: S/M/L font-size controls.
  $$('.dossier-font-controls button').forEach(btn => {
    btn.addEventListener('click', () => applyDossierFontPref(btn.dataset.fontKey));
  });

  // Mark active in list — using data-para-id is stable across re-renders.
  $$('.result').forEach(el => {
    el.classList.toggle('is-active', el.dataset.paraId === state.activeId);
  });
}

// ─────────── Citations (A1) ───────────
//
// Five formats, one builder each, all pure functions over a `(doc, para)`
// pair. Adapted from UnitedNations_recommendations/dashboard-reader.js
// `_citeBaseFields` + cite{APA,Chicago,BibTeX,RIS,PlainURL}, schema-mapped
// to our docs/paragraphs:
//   doc.year / doc.adoptionDate            ← date
//   doc.signature / doc.symbol             ← UN doc symbol
//   doc.committee / doc.committees / doc.treaty
//   doc.country (jur only)                  ← country anchor for case-law
//   doc.name / doc.nameShort                ← title
//   para.id / para.n                       ← paragraph identifier
//
// All formats wrap our share URL `?p=<id>` so copy-paste citations remain
// click-through to the exact paragraph.
function _citeBaseFields(doc, para) {
  const year = doc?.year ?? doc?.communicationYear ?? '';
  const date = doc?.adoptionDate || (year ? String(year) : 'n.d.');
  const author = doc?.committees?.length
    ? doc.committees.join(' / ')
    : (doc?.committee || doc?.treaty || 'United Nations');
  const symbol = doc?.signature || doc?.symbol || doc?.docId || '';
  const title = doc?.nameShort || doc?.name || symbol;
  const country = doc?.country || '';
  const paraNum = para?.n ?? para?.idx ?? '';
  const shareUrl = location.origin + location.pathname + '?p=' + encodeURIComponent(para?.id || '');
  return { year, date, author, symbol, title, country, paraNum, shareUrl };
}

// ─────────── Legal citation formats (v19.15) ───────────
//
// Long-form committee names per Bluebook T.10 / OSCOLA-style usage.
const _CITE_LONG_COMMITTEE = {
  CCPR:    'Human Rights Committee',
  CESCR:   'Committee on Economic, Social and Cultural Rights',
  CERD:    'Committee on the Elimination of Racial Discrimination',
  CEDAW:   'Committee on the Elimination of Discrimination against Women',
  CAT:     'Committee against Torture',
  'CAT-OP':'Subcommittee on Prevention of Torture',
  CRC:     'Committee on the Rights of the Child',
  CMW:     'Committee on Migrant Workers',
  CRPD:    'Committee on the Rights of Persons with Disabilities',
  CED:     'Committee on Enforced Disappearances',
};
function _committeeLong(doc) {
  const c = doc?.committee || (doc?.committees && doc.committees[0]) || 'CCPR';
  return _CITE_LONG_COMMITTEE[c] || c;
}
function _gcLongRef(doc) {
  const ish = (doc?.committee === 'CEDAW' || doc?.committee === 'CERD');
  const kind = ish ? 'General Recommendation' : 'General Comment';
  const m = /(?:GC|GR)\s*(\d+)/i.exec(doc?.nameShort || '')
        || /(?:gc|gr)-?(\d+)/i.exec(doc?.docId || '');
  if (m) return `${kind} No. ${m[1]}`;
  return doc?.signature || '';
}

// (1) UN treaty-body footnote — what every IL paper actually uses.
// "Human Rights Committee, General Comment No. 32, ¶ 33, U.N. Doc. CCPR/C/GC/32 (2007)."
function _citeUnFootnote(doc, para) {
  const f = _citeBaseFields(doc, para);
  const long = _committeeLong(doc);
  const gc = _gcLongRef(doc);
  const para_ = f.paraNum !== '' ? `, ¶ ${f.paraNum}` : '';
  const ref = gc ? `${long}, ${gc}${para_}` : `${long}${para_}`;
  const symbol = f.symbol ? `, U.N. Doc. ${f.symbol}` : '';
  const yr = f.year ? ` (${f.year})` : '';
  return `${ref}${symbol}${yr}.`;
}

// (2) OSCOLA — Oxford Standard for Citation of Legal Authorities.
// "UNHRC, General Comment 32: Article 14 (23 August 2007) UN Doc CCPR/C/GC/32, para 33."
function _citeOSCOLA(doc, para) {
  const f = _citeBaseFields(doc, para);
  const c = doc?.committee || 'UN';
  const short = c === 'CCPR' ? 'UNHRC' : c;
  const gcRaw = _gcLongRef(doc);
  // OSCOLA strips "No." → "General Comment 32"
  const gc = gcRaw.replace(/^General (Comment|Recommendation) No\.\s*/, 'General $1 ');
  const title = doc?.nameShort && doc.nameShort.includes(':')
    ? doc.nameShort.split(':').slice(1).join(':').trim()
    : '';
  const titlePart = title ? `: ${title}` : '';
  const ref = gc ? `${gc}${titlePart}` : (doc?.name || f.symbol);
  const dateStr = doc?.adoptionDate || f.year || '';
  const datePart = dateStr ? ` (${dateStr})` : '';
  const docPart = f.symbol ? ` UN Doc ${f.symbol}` : '';
  const para_ = f.paraNum !== '' ? `, para ${f.paraNum}` : '';
  return `${short}, ${ref}${datePart}${docPart}${para_}.`;
}

// (3) Bluebook — US legal citation, T.16 style for treaty-body GCs.
// "U.N. Hum. Rts. Comm., Gen. Cmt. No. 32, ¶ 33, U.N. Doc. CCPR/C/GC/32 (2007)."
const _CITE_BLUEBOOK_SHORT = {
  CCPR:    'U.N. Hum. Rts. Comm.',
  CESCR:   'Comm. on Econ., Soc. & Cultural Rts.',
  CERD:    'Comm. on the Elimination of Racial Discrimination',
  CEDAW:   'Comm. on the Elimination of Discrimination Against Women',
  CAT:     'Comm. Against Torture',
  'CAT-OP':'Subcomm. on Prevention of Torture',
  CRC:     'Comm. on the Rights of the Child',
  CMW:     'Comm. on Migrant Workers',
  CRPD:    'Comm. on the Rights of Persons with Disabilities',
  CED:     'Comm. on Enforced Disappearances',
};
function _citeBluebook(doc, para) {
  const f = _citeBaseFields(doc, para);
  const c = doc?.committee || 'CCPR';
  const short = _CITE_BLUEBOOK_SHORT[c] || c;
  const ish = (c === 'CEDAW' || c === 'CERD');
  const m = /(?:GC|GR)\s*(\d+)/i.exec(doc?.nameShort || '')
        || /(?:gc|gr)-?(\d+)/i.exec(doc?.docId || '');
  const ref = m
    ? `${ish ? 'Gen. Recommendation' : 'Gen. Cmt.'} No. ${m[1]}`
    : f.title;
  const para_ = f.paraNum !== '' ? `, ¶ ${f.paraNum}` : '';
  const symbol = f.symbol ? `, U.N. Doc. ${f.symbol}` : '';
  const yr = f.year ? ` (${f.year})` : '';
  return `${short}, ${ref}${para_}${symbol}${yr}.`;
}

// (4) McGill — Canadian Guide to Uniform Legal Citation, 9th ed.
// "UNHR Committee, General Comment No 32 (23 August 2007), UN Doc CCPR/C/GC/32 at para 33."
function _citeMcGill(doc, para) {
  const f = _citeBaseFields(doc, para);
  const long = _committeeLong(doc).replace('Human Rights Committee', 'UNHR Committee');
  // McGill: drop the period after No (Canadian style).
  const gc = (_gcLongRef(doc) || '').replace(/^General (Comment|Recommendation) No\./, 'General $1 No');
  const dateStr = doc?.adoptionDate || f.year || '';
  const datePart = dateStr ? ` (${dateStr})` : '';
  const docPart = f.symbol ? `, UN Doc ${f.symbol}` : '';
  const para_ = f.paraNum !== '' ? ` at para ${f.paraNum}` : '';
  return `${long}, ${gc}${datePart}${docPart}${para_}.`;
}

function _citeAPA(doc, para) {
  const f = _citeBaseFields(doc, para);
  return `${f.author}. (${f.year || 'n.d.'}). ${f.title}${f.country ? ' — ' + f.country : ''} (UN Doc. ${f.symbol})${f.paraNum !== '' ? ', ¶ ' + f.paraNum : ''}. UN Human Rights Database. ${f.shareUrl}`;
}
function _citeChicago(doc, para) {
  const f = _citeBaseFields(doc, para);
  return `${f.author}, "${f.title}${f.country ? ', ' + f.country : ''}," UN Doc. ${f.symbol}${f.paraNum !== '' ? ', ¶ ' + f.paraNum : ''} (${f.date}), UN Human Rights Database, ${f.shareUrl}.`;
}
function _citeBibTeX(doc, para) {
  const f = _citeBaseFields(doc, para);
  const slug = (doc?.docId || f.symbol).replace(/[^A-Za-z0-9]/g, '').slice(0, 18);
  const key = `UNHR_${slug}${f.paraNum !== '' ? '_p' + String(f.paraNum).replace(/\./g, '') : ''}`;
  const esc = s => String(s || '').replace(/[{}%&#_$]/g, '\\$&');
  return `@misc{${key},
  author       = {${esc(f.author)}},
  title        = {${esc(f.title)}},
  year         = {${esc(f.year || 'n.d.')}},
  howpublished = {UN Doc. ${esc(f.symbol)}${f.paraNum !== '' ? ', \\P\\,' + f.paraNum : ''}},
  ${f.country ? `addendum     = {${esc(f.country)}},\n  ` : ''}url          = {${f.shareUrl}},
  note         = {UN Human Rights Database — paragraph-level corpus},
}`;
}
function _citeRIS(doc, para) {
  const f = _citeBaseFields(doc, para);
  return [
    'TY  - GEN',
    'AU  - ' + f.author,
    'PY  - ' + (f.year || 'n.d.'),
    'TI  - ' + f.title,
    'PB  - UN Human Rights Database',
    'ID  - ' + f.symbol + (f.paraNum !== '' ? ' ¶' + f.paraNum : ''),
    f.country ? 'CY  - ' + f.country : '',
    'UR  - ' + f.shareUrl,
    'N1  - Paragraph-level extract' + (f.paraNum !== '' ? ', ¶ ' + f.paraNum : ''),
    'ER  - ',
  ].filter(Boolean).join('\n');
}
function _citePlainURL(doc, para) {
  return _citeBaseFields(doc, para).shareUrl;
}

const CITE_FORMATS = [
  // v19.15: legal-citation formats first — what HR lawyers actually
  // paste into briefs. Default order surfaces the UN treaty-body
  // footnote (the dominant IL convention) at the top.
  { key: 'unfn',    name: 'UN treaty-body footnote', fmt: 'UN', build: _citeUnFootnote },
  { key: 'oscola',  name: 'OSCOLA (UK / Commonwealth)', fmt: 'OSCOLA', build: _citeOSCOLA },
  { key: 'bluebook',name: 'Bluebook (US)', fmt: 'BLUEBOOK', build: _citeBluebook },
  { key: 'mcgill',  name: 'McGill (Canada)', fmt: 'MCGILL', build: _citeMcGill },
  // Academic + tooling formats kept for cross-discipline use.
  { key: 'apa',     name: 'APA (7th ed.)',  fmt: 'APA',     build: _citeAPA },
  { key: 'chicago', name: 'Chicago notes',  fmt: 'CHICAGO', build: _citeChicago },
  { key: 'bibtex',  name: 'BibTeX',          fmt: '.BIB',    build: _citeBibTeX },
  { key: 'ris',     name: 'RIS / EndNote',   fmt: '.RIS',    build: _citeRIS },
  { key: 'url',     name: 'Plain URL',       fmt: 'LINK',    build: _citePlainURL },
];

// v19.16: user-preferred cite format. Drawer popovers (search-dossier
// toolbar + docs-drawer <details>) write this every time a format is
// clicked. Mid-panel buttons (result rows, docs-reader paragraph rows)
// read it for one-click cite — no popover.
const DEFAULT_CITE_FMT = 'unfn';
function getPrefCiteFmt() {
  const k = _lsGet(_LS.prefCiteFmt, DEFAULT_CITE_FMT);
  return CITE_FORMATS.some(f => f.key === k) ? k : DEFAULT_CITE_FMT;
}
function setPrefCiteFmt(key) {
  if (CITE_FORMATS.some(f => f.key === key)) _lsSet(_LS.prefCiteFmt, key);
}
// One-click: build + copy the citation in the user's preferred format,
// flash the anchor button, and toast the format name so the user sees
// what just landed on the clipboard. Returns the format object on
// success (handy for tests / keyboard handlers).
function copyCiteWithPref(anchorEl, para) {
  const doc = state.documents.get(para.docId);
  const key = getPrefCiteFmt();
  const fmt = CITE_FORMATS.find(f => f.key === key) || CITE_FORMATS[0];
  const cite = fmt.build(doc, para);
  try { navigator.clipboard?.writeText(cite); } catch {}
  // Visual feedback on the button. We add `is-flash` for ~700 ms, same
  // class the dossier Copy button uses, so the same CSS rule covers it.
  if (anchorEl) {
    anchorEl.classList.add('is-flash');
    setTimeout(() => anchorEl.classList.remove('is-flash'), 700);
  }
  showFeedbackToast({ ok: true, _msg: `${fmt.name} copied`, _mark: '”' });
  return fmt;
}

// v18.2: shared inline cite popover. Anchors next to whatever button
// triggered it (a result-row mark, a docs-reader paragraph row, or
// the dossier toolbar). Only one open at a time — clicking elsewhere
// or pressing Esc closes it.
//
// v19.16: middle-panel buttons (result rows, docs-reader rows) no
// longer call this — they use copyCiteWithPref() instead. The
// drawer chooser still uses this code path so users can pick a
// format AND set it as default in one click.
let _inlineCiteCleanup = null;
function openInlineCitePopover(anchorEl, para) {
  closeInlineCitePopover();
  const doc = state.documents.get(para.docId);
  const pop = document.createElement('div');
  pop.className = 'inline-cite-pop';
  pop.setAttribute('role', 'menu');
  const prefKey = getPrefCiteFmt();
  pop.innerHTML = CITE_FORMATS.map(c => `
    <button type="button" class="cite-opt ${c.key === prefKey ? 'is-default' : ''}" data-cite-key="${c.key}" role="menuitem">
      <span class="cite-fmt">${escape(c.fmt)}</span>
      <span class="cite-name">${escape(c.name)}</span>
    </button>
  `).join('');

  // Position: right-edge-aligned, dropping below the anchor by 6 px.
  document.body.appendChild(pop);
  const r = anchorEl.getBoundingClientRect();
  const popW = pop.offsetWidth;
  const x = Math.max(8, Math.min(window.innerWidth - popW - 8, r.right - popW));
  pop.style.top  = `${window.scrollY + r.bottom + 6}px`;
  pop.style.left = `${x}px`;

  // Wire each format. After click → write to clipboard, persist as the
  // user's default for one-click cite, flash, close.
  pop.querySelectorAll('.cite-opt').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const fmt = CITE_FORMATS.find(f => f.key === btn.dataset.citeKey);
      if (!fmt) return;
      const cite = fmt.build(doc, para);
      try { navigator.clipboard?.writeText(cite); } catch {}
      setPrefCiteFmt(fmt.key);                     // remember as default
      const lbl = btn.querySelector('.cite-fmt');
      const orig = lbl.textContent;
      lbl.textContent = '✓ COPIED';
      setTimeout(closeInlineCitePopover, 700);
    });
  });

  // Click-outside / Esc close.
  const onDoc = (e) => { if (!pop.contains(e.target) && e.target !== anchorEl) closeInlineCitePopover(); };
  const onEsc = (e) => { if (e.key === 'Escape') closeInlineCitePopover(); };
  setTimeout(() => {                              // attach on next tick so the
    document.addEventListener('click', onDoc);    // current click doesn't fire it
    document.addEventListener('keydown', onEsc);
  }, 0);
  _inlineCiteCleanup = () => {
    pop.remove();
    document.removeEventListener('click', onDoc);
    document.removeEventListener('keydown', onEsc);
    _inlineCiteCleanup = null;
  };
}
function closeInlineCitePopover() {
  if (_inlineCiteCleanup) _inlineCiteCleanup();
}

// v19.17 (recommendation D): singleton search-syntax popover anchored
// to the ? button next to #q. Same lifecycle as the cite popover —
// click-outside / Esc / re-click on the trigger closes it. Examples
// are clickable: filling them into #q runs the search via the same
// debounced path the .suggest buttons already use.
let _queryHelpCleanup = null;
const _QUERY_HELP_OPS = [
  { op: '"exact phrase"',     desc: 'Match the words verbatim and in order. Stays literal — no stemming.' },
  { op: 'A B',                desc: 'Implicit AND on whitespace — both terms must appear.' },
  { op: 'A AND B',            desc: 'Both terms must appear (explicit form).' },
  { op: 'A OR B',             desc: 'Either term qualifies.' },
  { op: 'NOT term · -term',   desc: 'Exclude paragraphs containing the term. Both forms work.' },
  { op: '( … )',              desc: 'Group with parentheses to override default precedence (AND binds tighter than OR).' },
  { op: 'prefix*',            desc: 'Trailing asterisk matches any continuation: discriminat* hits discrimination, discriminate, discriminatory.' },
];
const _QUERY_HELP_EXAMPLES = [
  '"best interests of the child"',
  'trafficking AND children NOT (sexual)',
  'surveillance OR interception',
  'discriminat*',
  '(women OR girls) AND violence',
];
function openQueryHelpPopover(triggerEl) {
  closeQueryHelpPopover();
  const pop = document.createElement('div');
  pop.className = 'q-help-pop';
  pop.setAttribute('role', 'dialog');
  pop.setAttribute('aria-label', 'Search syntax');
  pop.innerHTML = `
    <h4>Operators</h4>
    <dl>
      ${_QUERY_HELP_OPS.map(o => `
        <dt>${escape(o.op)}</dt>
        <dd>${escape(o.desc)}</dd>
      `).join('')}
    </dl>
    <h4>Try</h4>
    <div class="q-help-examples">
      ${_QUERY_HELP_EXAMPLES.map(q => `
        <button type="button" class="q-help-example" data-q="${escape(q)}">${escape(q)}</button>
      `).join('')}
    </div>
    <h4>Tip</h4>
    <p class="q-help-tip">
      Quoted phrases stay literal — <code>"AI"</code> matches only AI, not aid.
      Bare words stem on the server (<code>women</code> matches women / womens),
      so <code>women NOT girl</code> excludes girl/girls/girlfriend in one shot.
    </p>
  `;
  document.body.appendChild(pop);

  // Position: align right edge to the trigger. Prefer dropping BELOW —
  // the search bar lives near the viewport top, so above-the-input
  // almost always clips against page chrome. Only flip above when the
  // space there is genuinely larger. Either way, cap the popover's
  // height to whatever fits and let it scroll internally — that way
  // the user can always read the whole content even on short windows.
  const SAFE_GAP = 12;
  const r = triggerEl.getBoundingClientRect();
  const popW = pop.offsetWidth;
  const maxBelow = window.innerHeight - r.bottom - SAFE_GAP;
  const maxAbove = r.top - SAFE_GAP;
  const below = maxBelow >= 240 || maxBelow >= maxAbove;
  const maxH = Math.max(160, below ? maxBelow : maxAbove);
  pop.style.maxHeight = `${maxH}px`;
  pop.style.overflowY = 'auto';
  const popH = Math.min(pop.offsetHeight, maxH);
  const x = Math.max(8, Math.min(window.innerWidth - popW - 8, r.right - popW));
  const y = below
    ? window.scrollY + r.bottom + 6
    : window.scrollY + r.top - popH - 6;
  pop.style.left = `${x}px`;
  pop.style.top  = `${y}px`;

  triggerEl.setAttribute('aria-expanded', 'true');

  // Examples → fill #q + dispatch input so the existing debounced
  // handler kicks off the search. Same path as .suggest buttons.
  pop.querySelectorAll('.q-help-example').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const q = btn.dataset.q;
      const qInput = $('#q');
      if (qInput) {
        qInput.value = q;
        qInput.dispatchEvent(new Event('input', { bubbles: true }));
      }
      closeQueryHelpPopover();
    });
  });

  const onDoc = (e) => {
    if (!pop.contains(e.target) && e.target !== triggerEl) closeQueryHelpPopover();
  };
  const onEsc = (e) => { if (e.key === 'Escape') closeQueryHelpPopover(); };
  setTimeout(() => {
    document.addEventListener('click', onDoc);
    document.addEventListener('keydown', onEsc);
  }, 0);
  _queryHelpCleanup = () => {
    pop.remove();
    triggerEl.setAttribute('aria-expanded', 'false');
    document.removeEventListener('click', onDoc);
    document.removeEventListener('keydown', onEsc);
    _queryHelpCleanup = null;
  };
}
function closeQueryHelpPopover() {
  if (_queryHelpCleanup) _queryHelpCleanup();
}

// ─────────── Read → Open in document (v19.15) ───────────
//
// Replaces the v16 reading-mode overlay. Lawyers reading a paragraph in
// the dossier almost always need to verify the surrounding context —
// what comes before/after, what section heading it sits under, whether
// adjacent paragraphs caveat or strengthen the position. Toggling a
// styling class never gave them that. Now Read navigates to the full
// document with the paragraph centered + highlighted (uses the existing
// `#documents/<docId>?p=<paraId>` deep-link path that R4 verifies).
function openInDocReader(para) {
  if (!para) return;
  const u = new URL(window.location);
  u.searchParams.set('p', para.id);
  // Clear search-only params that don't apply to the documents view.
  // Keep `q` so back-navigation restores the result list cleanly.
  u.hash = `#documents/${para.docId}`;
  window.location.assign(u.toString());
}

// v19.15: copy a stable deep-link to the active paragraph. Uses
// query-param `?p=<paraId>` which the boot path resolves to
// `state.activeId` and scrolls to. Not view-bound — works whether
// the recipient lands in search or documents.
function copyPermalink(para) {
  if (!para) return;
  const u = new URL(window.location);
  u.searchParams.set('p', para.id);
  u.hash = u.hash.startsWith('#documents/') ? u.hash : '';
  navigator.clipboard?.writeText(u.toString())
    .then(() => showFeedbackToast({ ok: true, _msg: 'Permalink copied', _mark: '🔗' }))
    .catch(() => showFeedbackToast({ ok: true, _msg: 'Copy failed — select the URL manually', _mark: '⚠' }));
}

// Bind R globally — only when the user isn't typing. Esc no longer
// has a reading-mode handler (the overlay is gone) but other UI
// elements still own the Escape semantics they always did.
document.addEventListener('keydown', (e) => {
  const tag = (e.target?.tagName || '').toLowerCase();
  const inEditable = tag === 'input' || tag === 'textarea' || e.target?.isContentEditable;
  if (e.key !== 'r' && e.key !== 'R') return;
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  if (inEditable) return;
  // Resolve the active paragraph the same way the dossier does.
  const id = state.activeId || state.docsActiveParaId;
  const para = id ? state.paragraphById.get(id) : null;
  if (!para) return;
  e.preventDefault();
  openInDocReader(para);
});

// ─────────── Command palette ⌘K (A2) ───────────
//
// Self-contained palette — opens with ⌘K / Ctrl+K, fuzzy-searches every
// document + label + committee + mandate + scope + theme. Pure local; no
// API calls (we already have state.documents, state.facets in memory).
//
// Adapted in spirit from UnitedNations_recommendations/cmdk.js but
// rewritten against our state shape. Item kinds:
//
//   doc           open a document (filter scope + activate first paragraph)
//   label         toggle a concerned-group filter
//   committee     toggle a committee/treaty body filter
//   mandate       toggle an SP mandate filter
//   scope         switch scope tab (gc / jur / sp / all)
//   reportType    toggle an SP report-type filter
//   action        misc: theme toggle, reset filters, reading mode, view nav
//
// Up/Down to navigate, Enter to fire, Esc to close. Click works the same.

let _cmdkOpen = false;
let _cmdkFocusIdx = 0;
let _cmdkItems = [];

function cmdkBuildItems() {
  const items = [];

  // 1. Quick actions (always at top)
  items.push({ kind: 'action', label: 'Toggle dark mode', sub: 'Light ↔ dark theme', icon: '◐',
               run: () => $('#theme-toggle')?.click() });
  items.push({ kind: 'action', label: 'Open in full document', sub: 'Press R · jumps to the active paragraph in context', icon: '📖',
               run: () => {
                 const id = state.activeId || state.docsActiveParaId;
                 const para = id ? state.paragraphById.get(id) : null;
                 if (para) openInDocReader(para);
               } });
  items.push({ kind: 'action', label: 'Reset all filters', sub: 'Clear committees, labels, year range…', icon: '⌫',
               run: () => $('#reset-filters')?.click() });
  items.push({ kind: 'action', label: 'About', sub: 'Methodology, citation, contact', icon: 'ⓘ',
               run: () => { window.location.hash = 'about'; } });
  items.push({ kind: 'action', label: 'Documents', sub: 'Browse the document index', icon: '☰',
               run: () => { window.location.hash = 'documents'; } });

  // 2. Scope flips
  for (const [key, label, sub] of [
    ['gc',  'Scope · General Comments', 'Treaty body interpretive output'],
    ['jur', 'Scope · Jurisprudence',    `${jurTreatyLabel()} case-law preview`],
    ['sp',  'Scope · Special Procedures', 'Mandate-holder reports preview'],
    ['all', 'Scope · All sources',      'Combined view'],
  ]) {
    items.push({
      kind: 'scope', label, sub, icon: '⇄',
      run: () => {
        const tab = document.querySelector(`.scope-opt[data-scope="${key}"]`);
        tab?.click();
        window.location.hash = 'search';
      },
    });
  }

  // 3. Documents — every GC / SP / JUR record currently in state
  for (const doc of state.documents.values()) {
    const symbol = doc.signature || doc.symbol || doc.docId;
    const subBits = [doc.committee || doc.treaty || ''];
    if (doc.year) subBits.push(String(doc.year));
    if (doc.country) subBits.push(doc.country);
    if (doc.outcome && doc.outcome !== 'final') subBits.push(formatOutcome(doc.outcome));
    items.push({
      kind: 'doc', kindLabel: (doc.type || 'doc').toUpperCase(),
      label: doc.nameShort || doc.name || symbol,
      sub: `${symbol} · ${subBits.filter(Boolean).join(' · ')}`,
      icon: '📄',
      searchKey: `${symbol} ${doc.name || ''} ${doc.country || ''} ${doc.committee || ''}`.toLowerCase(),
      run: () => {
        // Activate the first paragraph of this doc — equivalent to clicking
        // the corresponding row in the Documents view.  Routes through the
        // single jump helper so it handles JUR shard load + scope flip + the
        // explicit setView call (replaceState alone never triggered it).
        jumpToParagraph(`${doc.docId}-0001`);
      },
    });
  }

  // 4. Concerned-group labels
  for (const lbl of (state.facets?.labels || [])) {
    items.push({
      kind: 'label', kindLabel: 'LABEL',
      label: lbl.value, sub: `${lbl.count.toLocaleString()} paragraphs`, icon: '🏷',
      run: () => {
        if (state.filters.labels.has(lbl.value)) state.filters.labels.delete(lbl.value);
        else state.filters.labels.add(lbl.value);
        syncFiltersToDom();
        runSearch();
        window.location.hash = 'search';
      },
    });
  }

  // 5. Committees / treaty bodies
  for (const c of (state.facets?.committees || [])) {
    items.push({
      kind: 'committee', kindLabel: 'COMMITTEE',
      label: c.value, sub: `${c.count.toLocaleString()} paragraphs`, icon: '⚖',
      run: () => {
        if (state.filters.committees.has(c.value)) state.filters.committees.delete(c.value);
        else state.filters.committees.add(c.value);
        paintCommitteeFilter(state.scope);
        runSearch();
        window.location.hash = 'search';
      },
    });
  }

  // 6. SP mandates
  for (const m of (state.facets?.mandates || [])) {
    items.push({
      kind: 'mandate', kindLabel: 'MANDATE',
      label: m.value, sub: `${m.count.toLocaleString()} reports`, icon: '⚒',
      run: () => {
        if (state.filters.committees.has(m.value)) state.filters.committees.delete(m.value);
        else state.filters.committees.add(m.value);
        paintCommitteeFilter(state.scope);
        runSearch();
        window.location.hash = 'search';
      },
    });
  }

  return items;
}

function cmdkOpen() {
  if (_cmdkOpen) return;
  _cmdkOpen = true;
  _cmdkFocusIdx = 0;
  _cmdkItems = cmdkBuildItems();

  const root = document.createElement('div');
  root.className = 'cmdk-root open';
  root.id = '__cmdk_root';
  root.innerHTML = `
    <div class="cmdk-backdrop"></div>
    <div class="cmdk-card" role="dialog" aria-label="Command palette">
      <div class="cmdk-input-row">
        <span class="cmdk-prompt">›</span>
        <input id="__cmdk_input" type="search" placeholder="Search documents, labels, committees, actions…"
               autocomplete="off" autocorrect="off" autocapitalize="off" spellcheck="false">
        <span class="cmdk-esc">esc</span>
      </div>
      <div class="cmdk-results" id="__cmdk_results" role="listbox"></div>
      <div class="cmdk-foot folio">
        ↑↓ navigate · ↩ select · Esc dismiss
      </div>
    </div>`;
  document.body.appendChild(root);

  const input = $('#__cmdk_input');
  input?.focus();

  cmdkRender('');

  input?.addEventListener('input', (e) => cmdkRender(e.target.value));
  root.querySelector('.cmdk-backdrop')?.addEventListener('click', cmdkClose);
}

function cmdkClose() {
  _cmdkOpen = false;
  document.getElementById('__cmdk_root')?.remove();
}

function cmdkRender(query) {
  const q = (query || '').trim().toLowerCase();
  const list = $('#__cmdk_results');
  if (!list) return;

  // Score-and-rank items by simple substring proximity. Cheap, no
  // dependencies — for our scale (~600 items max) this is plenty.
  const scored = [];
  for (const it of _cmdkItems) {
    if (!q) { scored.push({ it, score: 1 }); continue; }
    const hay = (it.searchKey || (it.label + ' ' + (it.sub || ''))).toLowerCase();
    if (!hay.includes(q)) continue;
    // Prefer items where the query matches near the start of the label.
    const labelHit = it.label.toLowerCase().indexOf(q);
    const score = labelHit >= 0 ? 100 - labelHit : 50;
    scored.push({ it, score });
  }
  scored.sort((a, b) => b.score - a.score);
  const top = scored.slice(0, 60);

  if (!top.length) {
    list.innerHTML = `<div class="cmdk-empty">No matches for "${escape(q)}".</div>`;
    return;
  }
  _cmdkFocusIdx = Math.min(_cmdkFocusIdx, top.length - 1);
  list.innerHTML = top.map((s, i) => `
    <div class="cmdk-item ${i === _cmdkFocusIdx ? 'focus' : ''}" data-cmdk-i="${i}">
      <span class="cmdk-kind">${escape(s.it.kindLabel || s.it.kind)}</span>
      <span class="cmdk-label">
        <span class="cmdk-icon">${s.it.icon || ''}</span>
        <span>${escape(s.it.label)}</span>
        ${s.it.sub ? `<span class="cmdk-sub">${escape(s.it.sub)}</span>` : ''}
      </span>
      <span class="cmdk-enter">↩</span>
    </div>`).join('');

  list.querySelectorAll('.cmdk-item').forEach(el => {
    el.addEventListener('click', () => {
      const idx = parseInt(el.dataset.cmdkI, 10);
      const sel = top[idx];
      if (sel?.it?.run) {
        cmdkClose();
        sel.it.run();
      }
    });
    el.addEventListener('mouseenter', () => {
      _cmdkFocusIdx = parseInt(el.dataset.cmdkI, 10);
      list.querySelectorAll('.cmdk-item').forEach(x => x.classList.toggle('focus',
        parseInt(x.dataset.cmdkI, 10) === _cmdkFocusIdx));
    });
  });
}

document.addEventListener('keydown', (e) => {
  // Toggle the palette
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault();
    if (_cmdkOpen) cmdkClose();
    else cmdkOpen();
    return;
  }
  if (!_cmdkOpen) return;
  if (e.key === 'Escape') { e.preventDefault(); cmdkClose(); return; }
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp' || e.key === 'Enter') {
    e.preventDefault();
    const list = $('#__cmdk_results');
    const items = list?.querySelectorAll('.cmdk-item') || [];
    if (!items.length) return;
    if (e.key === 'ArrowDown') {
      _cmdkFocusIdx = (_cmdkFocusIdx + 1) % items.length;
    } else if (e.key === 'ArrowUp') {
      _cmdkFocusIdx = (_cmdkFocusIdx - 1 + items.length) % items.length;
    } else if (e.key === 'Enter') {
      items[_cmdkFocusIdx]?.click();
      return;
    }
    items.forEach((el, i) => el.classList.toggle('focus', i === _cmdkFocusIdx));
    items[_cmdkFocusIdx]?.scrollIntoView({ block: 'nearest' });
  }
});

// ─────────── Workspace storage layer (Tier B) ───────────
//
// All four Tier-B features (bookmarks · notes · saved searches · diff
// pins) persist to localStorage. Single shared layer for read/write with
// graceful fallback when storage is denied (private browsing, quota, etc.).
//
// Keys:
//   unhrdb_bookmarks_v1   → array of {paraId, docId, addedAt}
//   unhrdb_notes_v1       → object { paraId: noteText, ... }
//   unhrdb_pins_v1        → array of {paraId, docId, addedAt}, max 2 (FIFO)
//   unhrdb_searches_v1    → array of {name, url, savedAt}
const _LS = {
  bm:    'unhrdb_bookmarks_v1',
  notes: 'unhrdb_notes_v1',
  pins:  'unhrdb_pins_v1',
  ss:    'unhrdb_searches_v1',
  dossierWidth: 'unhrdb_dossier_width_v1',  // v15: user-resized dossier (px, integer)
  dossierFont:  'unhrdb_dossier_font_v1',   // v15: 'S' | 'M' | 'L'
  theme:        'unhrdb_theme_v1',          // v19.6: 'light' | 'dark'
  metaVote:     'unhrdb_meta_vote_v1',      // v19.10: docId → 'ok' | 'bad'
  searchInFn:   'unhrdb_search_in_fn_v1',   // v19.12: '1' | '0' (default '1')
  feedbackDraft:'unhrdb_feedback_draft_v1', // v19.14: {paraId, kind, message, contact, ts}
  prefCiteFmt:  'unhrdb_pref_cite_fmt_v1',  // v19.16: cite-format key for one-click cite
};
function _lsGet(key, fallback) {
  try { return JSON.parse(localStorage.getItem(key) || JSON.stringify(fallback)); }
  catch { return fallback; }
}
function _lsSet(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); return true; }
  catch { return false; }
}

// ─────────── B1 Bookmarks ───────────
function bmList() { return _lsGet(_LS.bm, []); }
function bmHas(paraId) { return bmList().some(b => b.paraId === paraId); }
function bmToggle(paraId) {
  const list = bmList();
  const idx = list.findIndex(b => b.paraId === paraId);
  if (idx >= 0) list.splice(idx, 1);
  else {
    const para = state.paragraphById.get(paraId);
    if (!para) return;
    list.push({ paraId, docId: para.docId, addedAt: Date.now() });
  }
  _lsSet(_LS.bm, list);
  paintWorkspaceBadge();
  return bmHas(paraId);
}

// ─────────── B2 Notes ───────────
function noteGet(paraId) { return _lsGet(_LS.notes, {})[paraId] || ''; }
function noteSet(paraId, text) {
  const all = _lsGet(_LS.notes, {});
  if (!text || !text.trim()) delete all[paraId];
  else all[paraId] = text;
  _lsSet(_LS.notes, all);
  paintWorkspaceBadge();
}
function noteHas(paraId) { return !!noteGet(paraId); }

// ─────────── B3 Diff / Compare pins (max 2, FIFO eviction) ───────────
function pinList() { return _lsGet(_LS.pins, []); }
function pinHas(paraId) { return pinList().some(p => p.paraId === paraId); }
function pinToggle(paraId) {
  const list = pinList();
  const idx = list.findIndex(p => p.paraId === paraId);
  if (idx >= 0) list.splice(idx, 1);
  else {
    const para = state.paragraphById.get(paraId);
    if (!para) return;
    if (list.length >= 2) list.shift();           // FIFO when full
    list.push({ paraId, docId: para.docId, addedAt: Date.now() });
  }
  _lsSet(_LS.pins, list);
  paintDiffTray();
  paintWorkspaceBadge();
  return pinHas(paraId);
}

// ─────────── B5 Saved searches ───────────
function ssList() { return _lsGet(_LS.ss, []); }
function ssAdd(name, url) {
  if (!name?.trim()) return;
  const list = ssList();
  list.push({ name: name.trim(), url, savedAt: Date.now() });
  _lsSet(_LS.ss, list);
  paintWorkspaceBadge();
}
function ssRemove(idx) {
  const list = ssList();
  list.splice(idx, 1);
  _lsSet(_LS.ss, list);
  paintWorkspaceBadge();
}

// ─────────── Diff tray (B3 visual) ───────────
//
// Bottom-right tray that shows up whenever 1+ pin exists. Click → opens
// a side-by-side comparison modal. Empty when 0 pins (hidden).
function paintDiffTray() {
  const tray = $('#diff-tray');
  if (!tray) return;
  const pins = pinList();
  if (!pins.length) { tray.hidden = true; tray.innerHTML = ''; return; }
  tray.hidden = false;
  tray.innerHTML = `
    <div class="diff-tray-head">
      <span class="folio">PINNED · ${pins.length}/2</span>
      <button class="diff-clear" type="button" title="Clear all pins">×</button>
    </div>
    <ol class="diff-tray-list">
      ${pins.map((p, i) => {
        const para = state.paragraphById.get(p.paraId);
        const doc = para && state.documents.get(para.docId);
        const sig = doc?.signature || doc?.symbol || p.paraId;
        return `<li class="diff-tray-item">
          <span class="diff-tray-num">${String.fromCharCode(65 + i)}</span>
          <span class="diff-tray-sig">${escape(sig)}</span>
          ${para ? `<span class="diff-tray-pn">¶${escape(String(para.n ?? para.idx))}</span>` : ''}
          <button class="diff-tray-pop" type="button" data-pin-idx="${i}" title="Remove">−</button>
        </li>`;
      }).join('')}
    </ol>
    <div class="diff-tray-foot">
      ${pins.length === 2
        ? `<button class="btn btn-garnet diff-open" type="button">Compare ⇆</button>`
        : `<span class="folio dim">Pin one more to compare</span>`}
    </div>`;
  tray.querySelector('.diff-clear')?.addEventListener('click', () => {
    _lsSet(_LS.pins, []);
    paintDiffTray();
    paintWorkspaceBadge();
  });
  tray.querySelectorAll('.diff-tray-pop').forEach(b => {
    b.addEventListener('click', () => {
      const i = parseInt(b.dataset.pinIdx, 10);
      const list = pinList();
      list.splice(i, 1);
      _lsSet(_LS.pins, list);
      paintDiffTray();
      paintWorkspaceBadge();
    });
  });
  tray.querySelector('.diff-open')?.addEventListener('click', openDiffModal);
}

function openDiffModal() {
  const modal = $('#diff-modal');
  const pins = pinList();
  if (!modal || pins.length < 2) return;
  const ast = parseQuery(state.query);
  const terms = ast ? leafTermsForHighlight(ast).map(t => t.value) : [];

  const renderPane = (pin, idx) => {
    const para = state.paragraphById.get(pin.paraId);
    const doc  = para && state.documents.get(para.docId);
    if (!para) {
      return `<div class="diff-pane">
        <div class="folio">PIN ${String.fromCharCode(65 + idx)}</div>
        <p class="serif" style="color:var(--ink-3); font-style:italic">
          The pinned paragraph is no longer in the loaded corpus
          (the jurisprudence shard may not have been loaded yet — try
          opening the Jurisprudence scope first).
        </p>
      </div>`;
    }
    const outcome = (para.type === 'jur' && doc?.outcome)
      ? `<span class="outcome-badge outcome-${escape(doc.outcome)}">${escape(formatOutcome(doc.outcome))}</span>`
      : '';
    return `<div class="diff-pane">
      <div class="diff-pane-head">
        <span class="folio">PIN ${String.fromCharCode(65 + idx)}</span>
        ${outcome}
      </div>
      <h4 class="diff-pane-title">${escape(doc?.nameShort || doc?.name || para.docId)}</h4>
      <div class="diff-pane-meta">
        <span class="mono">${escape(doc?.signature || '')}</span>
        ${doc?.country ? `<span class="diff-pane-country">${escape(doc.country)}</span>` : ''}
        ${doc?.year ? `<span>${doc.year}</span>` : ''}
        <span class="diff-pane-pn">¶ ${escape(String(para.n ?? para.idx))}</span>
      </div>
      <p class="diff-pane-text">${highlight(para.text, terms)}</p>
    </div>`;
  };

  modal.hidden = false;
  modal.innerHTML = `
    <div class="diff-modal-backdrop"></div>
    <div class="diff-modal-card" role="dialog" aria-label="Compare paragraphs">
      <div class="diff-modal-head">
        <span class="folio garnet">SIDE-BY-SIDE COMPARISON</span>
        <button class="diff-modal-close" type="button" aria-label="Close">×</button>
      </div>
      <div class="diff-modal-grid">
        ${renderPane(pins[0], 0)}
        ${renderPane(pins[1], 1)}
      </div>
      <div class="diff-modal-foot folio">
        Pinned paragraphs · cleared from this view via the tray.
      </div>
    </div>`;
  modal.querySelector('.diff-modal-backdrop')?.addEventListener('click', closeDiffModal);
  modal.querySelector('.diff-modal-close')?.addEventListener('click', closeDiffModal);
}
function closeDiffModal() {
  const modal = $('#diff-modal');
  if (modal) { modal.hidden = true; modal.innerHTML = ''; }
}

// ─────────── v19.3: Report-a-problem modal ───────────
//
// Posts to /api/feedback (the unhrdb-api endpoint that lands feedback
// in /home/amuvmuser/unhrdb/feedback/feedback.jsonl on the VM). The
// endpoint is rate-limited to 5/hour/IP server-side; we don't need a
// client-side limit. When a paragraph is currently active in the
// dossier or the docs reader, we offer to attach paraId + docId as
// context — the user can untick to send a generic report instead.
function openReportModal({ paraId = null, docId = null } = {}) {
  const modal = $('#report-modal');
  if (!modal) return;

  // Resolve the active paragraph if not explicitly passed.
  const id = paraId || state.docsActiveParaId || state.activeId;
  const p  = id ? state.paragraphById.get(id) : null;
  const d  = p?.docId ? state.documents.get(p.docId) : (docId ? state.documents.get(docId) : null);

  const ctx = $('#report-context');
  const detail = $('#report-context-detail');
  if (id && p) {
    detail.textContent = `${id}${p.n != null ? ` · ¶${p.n}` : ''}${d?.signature ? `  ·  ${d.signature}` : ''}`;
    ctx.hidden = false;
    modal.dataset.paraId   = id;
    modal.dataset.docId    = p.docId || docId || '';
    modal.dataset.signature = d?.signature || '';
  } else {
    ctx.hidden = true;
    delete modal.dataset.paraId;
    delete modal.dataset.docId;
    delete modal.dataset.signature;
  }

  // Restore a draft if the user previously hit Submit and the API was
  // down — keeps them from losing what they typed.
  const draft = _lsGet(_LS.feedbackDraft, null);
  if (draft && draft.paraId === id) {
    const radio = $(`#report-form input[name="kind"][value="${draft.kind}"]`);
    if (radio) radio.checked = true;
    $('#report-message').value = draft.message || '';
    $('#report-contact').value = draft.contact || '';
  } else {
    $('#report-message').value = '';
    // Don't clobber email — users tend to re-use it.
  }
  $('#report-status').hidden = true;
  $('#report-status').textContent = '';
  $('#report-submit').disabled = false;
  _updateReportCharcount();

  modal.hidden = false;
  setTimeout(() => $('#report-message')?.focus(), 50);
}

function _updateReportCharcount() {
  const counter = $('#report-charcount');
  const ta = $('#report-message');
  if (counter && ta) counter.textContent = `${ta.value.length} / 280`;
}

function closeReportModal() {
  const modal = $('#report-modal');
  if (modal) modal.hidden = true;
}

async function submitReport(ev) {
  ev.preventDefault();
  const modal = $('#report-modal');
  const submitBtn = $('#report-submit');
  const status = $('#report-status');

  const kind = $('#report-form input[name="kind"]:checked')?.value || 'other';
  const message = $('#report-message').value.trim();
  const contact = $('#report-contact').value.trim();
  const paraId = modal.dataset.paraId || null;
  const docId  = modal.dataset.docId  || null;
  const signature = modal.dataset.signature || null;
  const para = paraId ? state.paragraphById.get(paraId) : null;
  const excerpt = para ? (para.text || '').replace(/\[\[fn:\d+\]\]/g, '').slice(0, 280) : null;

  // Auto-captured page context — what view, what URL, what query.
  const body = {
    kind,
    message: message || null,
    contact: contact || null,
    paraId, docId, signature,
    view:    state.view || 'search',
    url:     window.location.href.slice(0, 500),
    query:   state.query || null,
    scope:   state.scope || null,
    excerpt: excerpt,
  };

  // Persist a draft so a network failure doesn't lose the user's text.
  _lsSet(_LS.feedbackDraft, { paraId, kind, message, contact, ts: Date.now() });

  submitBtn.disabled = true;
  status.hidden = false;
  status.className = 'report-status is-pending';
  status.textContent = 'Submitting…';

  try {
    const res = await fetch(`${API_BASE}/api/feedback`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      let detail = 'Submit failed (' + res.status + ').';
      if (res.status === 429) detail = 'Too many reports from your IP — try again in an hour.';
      else if (res.status === 422) detail = 'Server rejected the report — comment may be too long.';
      throw new Error(detail);
    }
    const reply = await res.json().catch(() => ({}));
    // Success: clear the draft, close modal, show toast.
    try { localStorage.removeItem(_LS.feedbackDraft); } catch {}
    closeReportModal();
    showFeedbackToast(reply);
  } catch (e) {
    status.className = 'report-status is-err';
    status.textContent = (e.message || 'Submit failed.') + ' Your text is kept locally — retry when you have signal.';
    submitBtn.disabled = false;
  }
}

// v19.14: lightweight toast notifying the user that their report
// landed, with a deep link to the GitHub issue when the backend
// surfaces one. Auto-dismisses after 6s, manually closeable.
// Renders a small toast bottom-right. Used by feedback submit (with
// optional GitHub-issue link) AND by lightweight per-action confirmations
// (permalink copied, etc.) — pass `_msg` to override the default text +
// `_mark` to override the icon.
function showFeedbackToast(reply) {
  let toast = document.getElementById('feedback-toast');
  if (!toast) {
    toast = document.createElement('div');
    toast.id = 'feedback-toast';
    toast.className = 'feedback-toast';
    toast.setAttribute('role', 'status');
    toast.setAttribute('aria-live', 'polite');
    document.body.appendChild(toast);
  }
  const issueLink = reply && reply.issueUrl
    ? ` · <a href="${escape(reply.issueUrl)}" target="_blank" rel="noopener">issue #${escape(String(reply.issueNumber))}</a>`
    : '';
  const msg = reply && reply._msg
    ? escape(reply._msg)
    : `Thanks — report filed${issueLink}.`;
  const mark = reply && reply._mark ? escape(reply._mark) : '⚐';
  toast.innerHTML = `
    <span class="feedback-toast-mark">${mark}</span>
    <span class="feedback-toast-msg">${msg}</span>
    <button type="button" class="feedback-toast-close" aria-label="Dismiss">×</button>
  `;
  toast.classList.add('is-shown');
  toast.querySelector('.feedback-toast-close')?.addEventListener('click', () => {
    toast.classList.remove('is-shown');
  }, { once: true });
  setTimeout(() => toast.classList.remove('is-shown'), 4000);
}

// ─────────── B4 Year histogram ───────────
//
// Inline SVG chart. Reads facets.years.histogram. Click a bar to set
// yearMin/yearMax to that single year; shift-click extends a range.
function paintYearHistogram() {
  const host = $('#year-histogram');
  if (!host) return;
  const hist = state.facets?.years?.histogram || [];
  if (!hist.length) { host.innerHTML = ''; return; }

  const yMin = state.facets.years.min;
  const yMax = state.facets.years.max;
  const maxCount = Math.max(1, ...hist.map(b => b.count));
  const W = 240, H = 36;
  const barW = (W - (hist.length - 1) * 1) / hist.length;

  // Detect which bars fall inside the current filter range
  const inRange = (year) =>
    (state.filters.yearMin == null || year >= state.filters.yearMin) &&
    (state.filters.yearMax == null || year <= state.filters.yearMax);

  const bars = hist.map((b, i) => {
    const h = (b.count / maxCount) * H;
    const x = i * (barW + 1);
    const y = H - h;
    const cls = inRange(b.year) ? 'in-range' : 'out-range';
    return `<rect class="yh-bar ${cls}"
      data-year="${b.year}" data-count="${b.count}"
      x="${x.toFixed(1)}" y="${y.toFixed(1)}"
      width="${barW.toFixed(1)}" height="${h.toFixed(1)}">
      <title>${b.year} · ${b.count.toLocaleString()} paragraphs</title>
    </rect>`;
  }).join('');

  host.innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" class="yh-svg" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Year histogram">
      ${bars}
    </svg>
    <div class="yh-axis"><span>${yMin}</span><span>${yMax}</span></div>`;

  host.querySelectorAll('.yh-bar').forEach(b => {
    b.addEventListener('click', (e) => {
      const y = parseInt(b.dataset.year, 10);
      if (e.shiftKey && state.filters.yearMin != null) {
        // shift-click extends the range
        state.filters.yearMin = Math.min(state.filters.yearMin, y);
        state.filters.yearMax = Math.max(state.filters.yearMax, y);
      } else {
        state.filters.yearMin = y;
        state.filters.yearMax = y;
      }
      $('#year-min').value = state.filters.yearMin;
      $('#year-max').value = state.filters.yearMax;
      paintYearFill();
      paintYearHistogram();
      runSearch();
    });
  });
}

// ─────────── Workspace view + nav badge ───────────
function paintWorkspaceBadge() {
  const badge = $('#workspace-badge');
  if (!badge) return;
  const total = bmList().length + Object.keys(_lsGet(_LS.notes, {})).length
              + ssList().length + pinList().length;
  if (total === 0) { badge.hidden = true; badge.textContent = ''; return; }
  badge.hidden = false;
  badge.textContent = String(total);
}

function renderWorkspace() {
  const host = $('#workspace-body');
  if (!host) return;
  const bms = bmList();
  const notes = _lsGet(_LS.notes, {});
  const noteIds = Object.keys(notes);
  const pins = pinList();
  const ss = ssList();

  const totalItems = bms.length + noteIds.length + pins.length + ss.length;
  const exportBar = totalItems > 0 ? `
    <div class="ws-export-bar">
      <span class="dim mono">${totalItems} item${totalItems === 1 ? '' : 's'} in your workspace</span>
      <div class="ws-export-actions">
        <button class="btn btn-ghost" id="ws-export-md" type="button" title="Download a Markdown file with every bookmark, note, pin, and saved search">⬇ Markdown</button>
        <button class="btn btn-ghost" id="ws-export-json" type="button" title="Download a JSON backup of the entire workspace">⬇ JSON</button>
      </div>
    </div>` : '';

  host.innerHTML = `
    ${exportBar}
    <div class="ws-block">
      <h3 class="folio">★ Bookmarks <span class="dim">(${bms.length})</span></h3>
      ${bms.length === 0
        ? '<p class="serif dim">Click ☆ on any paragraph to bookmark it. Bookmarks live only in this browser.</p>'
        : `<ol class="ws-list">${bms.slice().reverse().map(b => _wsRowFor(b.paraId, 'bm')).join('')}</ol>`}
    </div>
    <div class="ws-block">
      <h3 class="folio">📝 Notes <span class="dim">(${noteIds.length})</span></h3>
      ${noteIds.length === 0
        ? '<p class="serif dim">Open a paragraph in the dossier and write a note — autosaved per paragraph.</p>'
        : `<ol class="ws-list">${noteIds.map(id => _wsRowFor(id, 'note')).join('')}</ol>`}
    </div>
    <div class="ws-block">
      <h3 class="folio">📌 Pinned for compare <span class="dim">(${pins.length}/2)</span></h3>
      ${pins.length === 0
        ? '<p class="serif dim">Pin two paragraphs and use the tray bottom-right to compare them side-by-side.</p>'
        : `<ol class="ws-list">${pins.map(p => _wsRowFor(p.paraId, 'pin')).join('')}</ol>`}
      ${pins.length === 2 ? '<button class="btn btn-garnet" id="ws-open-diff">Open comparison ⇆</button>' : ''}
    </div>
    <div class="ws-block">
      <h3 class="folio">💾 Saved searches <span class="dim">(${ss.length})</span></h3>
      ${ss.length === 0
        ? '<p class="serif dim">Save the current query + filter combination from the searchbar.</p>'
        : `<ol class="ws-list ws-searches">${ss.slice().reverse().map((s, i) => `
            <li class="ws-row">
              <a class="ws-search-link" href="${escape(s.url)}">${escape(s.name)}</a>
              <span class="mono dim">${new Date(s.savedAt).toLocaleDateString('en-GB')}</span>
              <button class="ws-row-del" type="button" data-ss-idx="${ss.length - 1 - i}" title="Remove">×</button>
            </li>`).join('')}
          </ol>`}
    </div>`;

  host.querySelectorAll('.ws-row-del[data-ss-idx]').forEach(b => {
    b.addEventListener('click', () => { ssRemove(parseInt(b.dataset.ssIdx, 10)); renderWorkspace(); });
  });
  host.querySelectorAll('.ws-row-del[data-bm-id]').forEach(b => {
    b.addEventListener('click', () => { bmToggle(b.dataset.bmId); renderWorkspace(); });
  });
  host.querySelectorAll('.ws-row-del[data-note-id]').forEach(b => {
    b.addEventListener('click', () => { noteSet(b.dataset.noteId, ''); renderWorkspace(); });
  });
  host.querySelectorAll('.ws-row-del[data-pin-id]').forEach(b => {
    b.addEventListener('click', () => { pinToggle(b.dataset.pinId); renderWorkspace(); });
  });
  $('#ws-open-diff')?.addEventListener('click', openDiffModal);

  // v15: every workspace row carries an inline note editor. Autosave on
  // input (debounced 600 ms) + on blur. Removing the last character clears
  // the note from storage so it stops appearing in the Notes section.
  host.querySelectorAll('.ws-row-note').forEach(ta => {
    let t;
    const id = ta.dataset.noteFor;
    const save = () => {
      noteSet(id, ta.value);
      paintWorkspaceBadge();
      // No re-render — that would steal focus mid-typing.
    };
    ta.addEventListener('input', () => { clearTimeout(t); t = setTimeout(save, 600); });
    ta.addEventListener('blur',  () => { clearTimeout(t); save(); });
  });

  // v15: workspace export. Markdown is human-readable; JSON is a full
  // backup the user can re-import (we'll add import in a later release).
  $('#ws-export-md')?.addEventListener('click', () => exportWorkspace('md'));
  $('#ws-export-json')?.addEventListener('click', () => exportWorkspace('json'));

  host.querySelectorAll('.ws-jump').forEach(a => {
    a.addEventListener('click', (e) => {
      e.preventDefault();
      jumpToParagraph(a.dataset.paraId);
    });
  });
  // Saved-search links — same problem as ws-jump (the saved URL has no hash,
  // so a normal anchor click leaves the user in the workspace view). Intercept
  // and route through the single navigation helper.
  host.querySelectorAll('.ws-search-link').forEach(a => {
    a.addEventListener('click', (e) => {
      e.preventDefault();
      navigateToSearchUrl(a.getAttribute('href') || '');
    });
  });
}

// Extract a docId from a paragraph id of the form "<docId>-NNNN".  Used when
// the paragraph isn't yet in state.paragraphById (e.g. a workspace bookmark
// for a JUR case opened on a fresh page load before the JUR shard fetched).
function _docIdFromParaId(paraId) {
  if (!paraId) return null;
  const m = String(paraId).match(/^(.+)-\d{4,}$/);
  return m ? m[1] : null;
}

// Unified jump-to-paragraph used by Workspace + cmdk + future entry points.
// Keys handled in one place:
//   - paragraph might live in a lazy shard (JUR) → load on demand
//   - scope might be on a different tab (gc/jur/sp) → switch
//   - URL needs ?p=<id>#search and the view must actually flip to 'search'
//     (replaceState alone does NOT fire hashchange, so setView never ran in v14).
async function jumpToParagraph(paraId) {
  if (!paraId) return;

  // Identify the target document, even if the paragraph itself isn't loaded
  let doc = state.documents.get(_docIdFromParaId(paraId) || '');
  const targetType = doc?.type || 'gc';
  const targetScope = targetType === 'jur' ? 'jur'
                    : targetType === 'sp'  ? 'sp'
                    : 'gc';

  // Pull the JUR shard if needed; the bookmark will only resolve once the
  // paragraph is in state.paragraphById.
  if (targetScope === 'jur' && !state.jur.loaded) {
    try { await loadJurCorpus(); } catch (e) { console.warn('[jur load failed]', e); }
  }

  // Switch scope tab if we're not already on a compatible one.  "All sources"
  // is fine for any target — leave it alone if it's already active.
  if (state.scope !== targetScope && state.scope !== 'all') {
    document.querySelector(`.scope-opt[data-scope="${targetScope}"]`)?.click();
  }

  // Set the URL (preserve other query params), flip the view.
  const url = new URL(window.location);
  url.searchParams.set('p', paraId);
  url.hash = 'search';
  window.history.replaceState(null, '', url.toString());
  state.activeId = paraId;
  setView('search');                              // explicit — replaceState doesn't fire hashchange
  runSearch();
}

// Saved-search anchor → navigate as if the user typed the saved URL,
// without leaving the workspace via a full page reload.
function navigateToSearchUrl(href) {
  if (!href) return;
  // If href is an absolute URL on the same origin, keep only the path/search/hash.
  let path = href;
  try {
    const u = new URL(href, window.location.href);
    path = u.pathname + u.search + (u.hash || '#search');
  } catch {
    if (!href.includes('#')) path = href + '#search';
  }
  window.history.replaceState(null, '', path);
  applyUrlState(decodeUrlState());
  setView('search');
  runSearch();
}

function _wsRowFor(paraId, kind) {
  const para = state.paragraphById.get(paraId);
  // Documents are loaded eagerly (Tier-1 jur docs included), so we can show
  // the case symbol + title even when the paragraph itself is from a shard
  // that hasn't been fetched yet.
  const docId = para?.docId || _docIdFromParaId(paraId);
  const doc = state.documents.get(docId || '');
  const sig = doc?.signature || doc?.symbol || paraId;
  const where = doc?.country ? ` · ${escape(doc.country)}` : '';

  // v15: snippets are full-text by default. Long ones (≥320 chars) get a
  // "Show less" toggle (`<details>`) so the workspace stays scannable.
  const fullText = para?.text || '';
  const longText = fullText.length >= 320;
  const snippetHtml = para
    ? (longText
        ? `<details class="ws-snippet-fold" open><summary class="ws-snippet-toggle dim">Collapse</summary><p class="ws-row-snippet serif">${escape(fullText)}</p></details>`
        : `<p class="ws-row-snippet serif">${escape(fullText)}</p>`)
    : `<p class="ws-row-snippet serif"><em>(paragraph body will load when you open this scope — click ${escape(sig)} to navigate)</em></p>`;

  const dataAttr = kind === 'bm' ? `data-bm-id="${escape(paraId)}"`
                 : kind === 'note' ? `data-note-id="${escape(paraId)}"`
                 : kind === 'pin' ? `data-pin-id="${escape(paraId)}"` : '';

  // v15: every row gets an editable note. Lets users add/edit notes directly
  // from the workspace without having to navigate to the dossier first.
  const existingNote = _lsGet(_LS.notes, {})[paraId] || '';
  const noteEditor = `<textarea class="ws-row-note serif" data-note-for="${escape(paraId)}"
                              placeholder="Add a private note — autosaved to this browser."
                              rows="2">${escape(existingNote)}</textarea>`;

  return `<li class="ws-row" data-para-id="${escape(paraId)}">
    <div class="ws-row-meta">
      <a class="ws-jump mono" href="#search" data-para-id="${escape(paraId)}">${escape(sig)}</a>
      ${para?.n != null ? `<span class="dim mono">¶${escape(String(para.n))}</span>` : ''}
      <span class="dim">${escape(doc?.nameShort || doc?.name || '')}${where}</span>
    </div>
    ${snippetHtml}
    ${noteEditor}
    <button class="ws-row-del" type="button" ${dataAttr} title="Remove">×</button>
  </li>`;
}

// v15: export the entire personal workspace (bookmarks + notes + pins + saved
// searches) as either Markdown (human-readable, drop into Obsidian/Word/etc.)
// or JSON (full structured backup).  Both formats include the source signature
// + paragraph number + full body text where the paragraph is currently loaded.
function exportWorkspace(fmt) {
  const bms = bmList();
  const notes = _lsGet(_LS.notes, {});
  const pins = pinList();
  const ss = ssList();
  const stamp = new Date().toISOString().slice(0, 10);

  // Build a unified record per paragraph id so the user gets ONE block per
  // paragraph in markdown, with [bookmark][note][pinned] tags.
  const ids = new Set([
    ...bms.map(b => b.paraId),
    ...Object.keys(notes),
    ...pins.map(p => p.paraId),
  ]);
  const rows = [...ids].map(id => {
    const para = state.paragraphById.get(id);
    const doc = state.documents.get(para?.docId || _docIdFromParaId(id) || '');
    return {
      paraId: id,
      sig:    doc?.signature || doc?.symbol || id,
      title:  doc?.name || doc?.nameShort || '',
      country: doc?.country || null,
      year:   doc?.year || null,
      paragraphN: para?.n ?? null,
      text:   para?.text || null,
      labels: para?.labels || [],
      sourceLink: doc?.link || null,
      bookmarked: bms.some(b => b.paraId === id),
      pinned:     pins.some(p => p.paraId === id),
      note:       notes[id] || null,
    };
  });

  let blob, filename, mime;
  if (fmt === 'json') {
    const payload = {
      schemaVersion: 1,
      exportedAt: new Date().toISOString(),
      source: 'UN Human Rights Database (Geneva Reporter)',
      counts: { bookmarks: bms.length, notes: Object.keys(notes).length, pins: pins.length, savedSearches: ss.length },
      paragraphs: rows,
      savedSearches: ss,
    };
    blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
    filename = `unhrdb-workspace-${stamp}.json`;
    mime = 'application/json';
  } else {
    const lines = [];
    lines.push(`# UN Human Rights Database — Workspace export`);
    lines.push('');
    lines.push(`*Exported on ${new Date().toLocaleString('en-GB')}*`);
    lines.push('');
    lines.push(`- ${bms.length} bookmark${bms.length === 1 ? '' : 's'}`);
    lines.push(`- ${Object.keys(notes).length} note${Object.keys(notes).length === 1 ? '' : 's'}`);
    lines.push(`- ${pins.length} pinned for compare`);
    lines.push(`- ${ss.length} saved search${ss.length === 1 ? '' : 'es'}`);
    lines.push('');
    if (rows.length) {
      lines.push('## Paragraphs');
      lines.push('');
      for (const r of rows) {
        const tags = [
          r.bookmarked ? '★ bookmarked' : null,
          r.pinned ? '📌 pinned' : null,
          r.note ? '📝 note' : null,
        ].filter(Boolean).join(' · ');
        lines.push(`### ${r.sig}${r.paragraphN != null ? ` ¶${r.paragraphN}` : ''}`);
        if (r.title)  lines.push(`*${r.title}*${r.country ? ` — ${r.country}` : ''}${r.year ? ` (${r.year})` : ''}`);
        if (tags)     lines.push(`<small>${tags}</small>`);
        lines.push('');
        if (r.text)   lines.push(`> ${r.text.replace(/\n+/g, ' ')}`);
        else          lines.push(`> *(paragraph body not yet loaded — open ${r.sig} in the app to fetch)*`);
        if (r.note) {
          lines.push('');
          lines.push(`**Note:** ${r.note}`);
        }
        if (r.sourceLink) {
          lines.push('');
          lines.push(`[Open original document](${r.sourceLink})`);
        }
        lines.push('');
        lines.push('---');
        lines.push('');
      }
    }
    if (ss.length) {
      lines.push('## Saved searches');
      lines.push('');
      for (const s of ss) {
        const url = (location.origin || '') + (s.url.startsWith('/') ? s.url : '/' + s.url);
        lines.push(`- **${s.name}** — [reopen](${url}) *(saved ${new Date(s.savedAt).toLocaleDateString('en-GB')})*`);
      }
      lines.push('');
    }
    blob = new Blob([lines.join('\n')], { type: 'text/markdown' });
    filename = `unhrdb-workspace-${stamp}.md`;
    mime = 'text/markdown';
  }

  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 100);
}

// v15: dossier resize handle. The user drags the slim gutter between the
// results column and the dossier; we update --col-dossier live and persist
// the px width to localStorage on mouseup. Double-click resets to 440 px.
const _DOSSIER_DEFAULT = 440;
const _DOSSIER_MIN = 280;
const _DOSSIER_MAX = 900;

function initDossierResizer() {
  const handle = document.getElementById('dossier-resizer');
  if (!handle) return;

  // Restore saved width
  const saved = parseInt(_lsGet(_LS.dossierWidth, _DOSSIER_DEFAULT), 10);
  if (!Number.isNaN(saved)) {
    document.documentElement.style.setProperty('--col-dossier', clampDossier(saved) + 'px');
  }

  // Drag-to-resize. Pointer events handle mouse + touch + pen with one path.
  let dragging = false;
  const onMove = (ev) => {
    if (!dragging) return;
    const x = ev.clientX ?? (ev.touches && ev.touches[0]?.clientX);
    if (x == null) return;
    const newW = clampDossier(window.innerWidth - x);
    document.documentElement.style.setProperty('--col-dossier', newW + 'px');
  };
  const onUp = () => {
    if (!dragging) return;
    dragging = false;
    handle.classList.remove('is-dragging');
    document.body.classList.remove('is-resizing-dossier');
    const cur = getComputedStyle(document.documentElement).getPropertyValue('--col-dossier').trim();
    const px  = parseInt(cur, 10);
    if (!Number.isNaN(px)) _lsSet(_LS.dossierWidth, px);
    window.removeEventListener('pointermove', onMove);
    window.removeEventListener('pointerup', onUp);
  };
  handle.addEventListener('pointerdown', (ev) => {
    ev.preventDefault();
    dragging = true;
    handle.classList.add('is-dragging');
    document.body.classList.add('is-resizing-dossier');
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
  });

  // Double-click to reset.
  handle.addEventListener('dblclick', () => {
    document.documentElement.style.setProperty('--col-dossier', _DOSSIER_DEFAULT + 'px');
    _lsSet(_LS.dossierWidth, _DOSSIER_DEFAULT);
  });

  // Keyboard: ←/→ nudge by 16 px when handle has focus.
  handle.addEventListener('keydown', (ev) => {
    if (ev.key !== 'ArrowLeft' && ev.key !== 'ArrowRight') return;
    ev.preventDefault();
    const cur = parseInt(getComputedStyle(document.documentElement).getPropertyValue('--col-dossier'), 10) || _DOSSIER_DEFAULT;
    const next = clampDossier(cur + (ev.key === 'ArrowLeft' ? 16 : -16));
    document.documentElement.style.setProperty('--col-dossier', next + 'px');
    _lsSet(_LS.dossierWidth, next);
  });
}

function clampDossier(px) {
  return Math.max(_DOSSIER_MIN, Math.min(_DOSSIER_MAX, Math.round(px)));
}

// v15: dossier font-size preference. 'S' / 'M' / 'L' map to multipliers
// 0.9 / 1 / 1.15 applied via the --dossier-font CSS variable.
const _DOSSIER_FONT_SCALE = { S: 0.9, M: 1, L: 1.15 };
function applyDossierFontPref(letter) {
  const m = _DOSSIER_FONT_SCALE[letter] || 1;
  document.documentElement.style.setProperty('--dossier-font', String(m));
  _lsSet(_LS.dossierFont, letter);
  // Visual sync if the dossier is on screen.
  document.querySelectorAll('.dossier-font-controls button').forEach(b => {
    b.classList.toggle('is-active', b.dataset.fontKey === letter);
  });
}
function initDossierFontPref() {
  const saved = _lsGet(_LS.dossierFont, 'M');
  applyDossierFontPref(saved);
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

// ─────────── Footnote helpers (v19.8) ───────────
//
// Convention: paragraph.text may contain marker tokens of the form `[[fn:N]]`
// where N matches an entry in paragraph.footnotes (an array of {n, text}).
// Paragraphs that lack footnotes never carry markers, so existing 7,103¶
// render exactly as before.
//
// stripFnMarkers(text)              → text with [[fn:N]] removed (search/snippets)
// renderParagraphHtml(text, fns)    → escaped HTML with marker tokens replaced
//                                     by clickable <button> anchors. The button
//                                     carries data-fn-n + data-fn-text so a
//                                     single delegated handler can drive the
//                                     popover anywhere we render paragraphs.
//
const FN_MARKER_RE = /\[\[fn:(\d+)\]\]/g;
function stripFnMarkers(text) {
  return String(text || '').replace(FN_MARKER_RE, '');
}
function renderParagraphHtml(text, footnotes, opts = {}) {
  const t = String(text || '');
  const terms = opts.terms || null;
  const noMarkers = opts.noMarkers === true;

  // Fast paths -------------------------------------------------------------
  if (!FN_MARKER_RE.test(t)) {
    FN_MARKER_RE.lastIndex = 0;
    return terms ? highlight(t, terms) : escape(t);
  }
  FN_MARKER_RE.lastIndex = 0;
  if (noMarkers) {
    const bare = stripFnMarkers(t);
    return terms ? highlight(bare, terms) : escape(bare);
  }

  // Build a quick lookup: marker N → footnote text.
  const byN = new Map();
  if (Array.isArray(footnotes)) {
    for (const f of footnotes) {
      if (f && f.n != null) byN.set(Number(f.n), String(f.text || ''));
    }
  }

  // Tokenise around markers so we can highlight the prose chunks while
  // keeping marker buttons un-highlighted.
  let html = '';
  let last = 0;
  let m;
  FN_MARKER_RE.lastIndex = 0;
  while ((m = FN_MARKER_RE.exec(t)) !== null) {
    const before = t.slice(last, m.index);
    html += terms ? highlight(before, terms) : escape(before);
    const n = Number(m[1]);
    const fnText = byN.get(n) || '';
    html += '<button type="button" class="fn-marker" '
          + `data-fn-n="${n}" `
          + `data-fn-text="${escape(fnText)}" `
          + `aria-label="Footnote ${n}: ${escape(fnText.slice(0, 80))}${fnText.length > 80 ? '…' : ''}" `
          + `aria-expanded="false">`
          + `<sup>${n}</sup>`
          + '</button>';
    last = m.index + m[0].length;
  }
  const tail = t.slice(last);
  html += terms ? highlight(tail, terms) : escape(tail);
  return html;
}

// Returns true if any of `terms` (case-insensitive substring) appears in any
// of the paragraph's footnote bodies. Used to flag "match in citation" pills
// in the search results when the visible snippet itself doesn't contain the
// term (i.e. FlexSearch hit was scored from the fnText field only).
function hasFootnoteMatch(paragraph, terms) {
  if (!paragraph || !paragraph.footnotes || !paragraph.footnotes.length) return false;
  if (!terms || !terms.length) return false;
  const probes = terms.map(t => String(t || '').toLowerCase()).filter(Boolean);
  if (!probes.length) return false;
  for (const f of paragraph.footnotes) {
    const ft = String(f.text || '').toLowerCase();
    if (probes.some(p => ft.includes(p))) return true;
  }
  return false;
}

// ─────────── Footnote popover (singleton) ───────────
//
// One popover element appended to <body>, positioned anchored to the clicked
// marker. Closes on Escape, click-outside, scroll. ARIA: role=tooltip;
// trigger gets aria-expanded toggling.
let _fnPopover = null;
let _fnPopoverTrigger = null;
function _ensureFnPopover() {
  if (_fnPopover) return _fnPopover;
  const el = document.createElement('div');
  el.className = 'fn-popover';
  el.setAttribute('role', 'tooltip');
  el.hidden = true;
  el.innerHTML = `
    <div class="fn-popover-head">
      <span class="folio">FOOTNOTE</span>
      <span class="fn-popover-n mono"></span>
      <button class="fn-popover-close" type="button" aria-label="Close footnote">×</button>
    </div>
    <div class="fn-popover-body serif"></div>`;
  document.body.appendChild(el);
  el.querySelector('.fn-popover-close').addEventListener('click', closeFnPopover);
  _fnPopover = el;
  return el;
}
function openFnPopover(triggerBtn) {
  if (!triggerBtn) return;
  if (_fnPopoverTrigger === triggerBtn) { closeFnPopover(); return; }
  closeFnPopover();
  const n = triggerBtn.dataset.fnN || '';
  const text = triggerBtn.dataset.fnText || '';
  const pop = _ensureFnPopover();
  pop.querySelector('.fn-popover-n').textContent = '¹ '.replace('¹', '') + n;
  pop.querySelector('.fn-popover-body').textContent = text;
  pop.hidden = false;
  triggerBtn.setAttribute('aria-expanded', 'true');
  _fnPopoverTrigger = triggerBtn;
  _positionFnPopover(triggerBtn, pop);
  // Bind close handlers (idempotent — using bound singleton listeners).
  document.addEventListener('keydown', _fnPopoverKey, true);
  document.addEventListener('click', _fnPopoverDocClick, true);
  window.addEventListener('scroll', closeFnPopover, true);
  window.addEventListener('resize', closeFnPopover, true);
}
function closeFnPopover() {
  if (!_fnPopover) return;
  _fnPopover.hidden = true;
  if (_fnPopoverTrigger) {
    _fnPopoverTrigger.setAttribute('aria-expanded', 'false');
    _fnPopoverTrigger = null;
  }
  document.removeEventListener('keydown', _fnPopoverKey, true);
  document.removeEventListener('click', _fnPopoverDocClick, true);
  window.removeEventListener('scroll', closeFnPopover, true);
  window.removeEventListener('resize', closeFnPopover, true);
}
function _fnPopoverKey(e) {
  if (e.key === 'Escape') {
    if (_fnPopoverTrigger) _fnPopoverTrigger.focus();
    closeFnPopover();
  }
}
function _fnPopoverDocClick(e) {
  if (!_fnPopover) return;
  if (e.target === _fnPopoverTrigger) return;
  if (_fnPopover.contains(e.target)) return;
  if (e.target.closest && e.target.closest('.fn-marker')) return;
  closeFnPopover();
}
function _positionFnPopover(trigger, pop) {
  const r = trigger.getBoundingClientRect();
  // Show popover hidden at top-left first to measure its size.
  pop.style.left = '0px';
  pop.style.top = '0px';
  const pr = pop.getBoundingClientRect();
  const margin = 8;
  // Default: below + slightly right of trigger; flip up if it would overflow.
  let top = r.bottom + window.scrollY + margin;
  let left = r.left + window.scrollX;
  if (left + pr.width > window.scrollX + window.innerWidth - margin) {
    left = window.scrollX + window.innerWidth - pr.width - margin;
  }
  if (left < window.scrollX + margin) left = window.scrollX + margin;
  if (top + pr.height > window.scrollY + window.innerHeight - margin) {
    top = r.top + window.scrollY - pr.height - margin;
  }
  pop.style.left = left + 'px';
  pop.style.top = top + 'px';
}

function escapeRe(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function formatOutcome(value) {
  return String(value || '')
    .split('_')
    .filter(Boolean)
    .map(part => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

// ─────────── KWIC (keyword-in-context) snippets ───────────
//
// Adapted from UnitedNations_recommendations/dashboard-search.js (smartSnippet
// + _findBestCluster). For long paragraphs whose first match falls past the
// fade-out fold (~400 chars), we build a 1–2-sentence window centred on the
// best cluster of query terms — so the user can see WHY the paragraph matched
// without expanding it.
//
// Returns { html, isKwic, fullLen }.
const KWIC_PRE_CHARS  = 140;
const KWIC_POST_CHARS = 240;
const KWIC_FADE_FOLD  = 400;

function smartSnippet(text, terms) {
  const t = String(text || '');
  const fullLen = t.length;
  const cleanTerms = (terms || []).filter(Boolean);
  if (!cleanTerms.length || fullLen <= 500) {
    return { html: highlight(t, cleanTerms), isKwic: false, fullLen };
  }
  const idx = _findBestCluster(t, cleanTerms);
  if (idx < 0 || idx < KWIC_FADE_FOLD) {
    return { html: highlight(t, cleanTerms), isKwic: false, fullLen };
  }
  // Anchor a window roughly one sentence before + one after the cluster.
  let start = Math.max(0, idx - KWIC_PRE_CHARS);
  let end   = Math.min(fullLen, idx + KWIC_POST_CHARS);
  while (start > 0 && !/[.\n;:]/.test(t[start - 1])) start--;
  while (start < idx && /\s/.test(t[start])) start++;
  while (end < fullLen && !/[.\n]/.test(t[end])) end++;
  if (end < fullLen) end++;
  const snippet = t.slice(start, end);
  const prefix = start > 0 ? '… ' : '';
  const suffix = end < fullLen ? ' …' : '';
  return {
    html: prefix + highlight(snippet, cleanTerms) + suffix,
    isKwic: true,
    fullLen,
  };
}

function _findBestCluster(text, terms) {
  if (!terms.length) return -1;
  const lower = text.toLowerCase();
  const hits = [];
  for (const t of terms) {
    const probe = String(t).toLowerCase();
    if (!probe || probe.length < 2) continue;
    let i = 0;
    while ((i = lower.indexOf(probe, i)) !== -1) {
      hits.push(i);
      i += probe.length;
    }
  }
  if (!hits.length) return -1;
  hits.sort((a, b) => a - b);
  // Find tightest window of ≤200 chars containing the most hits; centre on it.
  let best = { count: 1, start: hits[0] };
  for (let i = 0; i < hits.length; i++) {
    let j = i;
    while (j + 1 < hits.length && hits[j + 1] - hits[i] <= 200) j++;
    const count = j - i + 1;
    if (count > best.count) best = { count, start: hits[i] };
  }
  return best.start;
}

// ─────────── Go ───────────
boot();
