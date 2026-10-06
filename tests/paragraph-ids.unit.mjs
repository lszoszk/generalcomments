// Unit checks for the paragraph-id helpers in docs/assets/app.js (v19.80:
// JUR ids moved from positional "<docId>-NNNN" to "<docId>:<label>").
// app.js is a browser script, so the pure helpers are lifted out of its text
// and run in a vm context with a stub `state`, API and localStorage.
//
//   node tests/paragraph-ids.unit.mjs
//
// Not a Playwright spec (the name does not match *.spec.*), no dependencies.
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const SRC = readFileSync(new URL('../docs/assets/app.js', import.meta.url), 'utf8');

// Source of a top-level `function name(` / `const name =` declaration, cut at
// its matching closing brace (the helpers have no braces inside strings).
function lift(name) {
  const m = new RegExp(`^(?:async function ${name}\\(|function ${name}\\(|const ${name} = )`, 'm').exec(SRC);
  if (!m) throw new Error(`not found in app.js: ${name}`);
  const eol = SRC.indexOf('\n', m.index);
  if (m[0].startsWith('const') && !SRC.slice(m.index, eol).includes('{')) return SRC.slice(m.index, eol);
  const open = SRC.indexOf('{', SRC.indexOf(m[0].startsWith('const') ? '=' : ')', m.index));
  let depth = 0;
  for (let i = open; i < SRC.length; i++) {
    if (SRC[i] === '{') depth++;
    else if (SRC[i] === '}' && --depth === 0) {
      let end = i + 1;
      if (SRC[end] === ';') end++;
      return SRC.slice(m.index, end);
    }
  }
  throw new Error(`unbalanced: ${name}`);
}

const store = new Map();
const ctx = {
  state: { paragraphById: new Map(), documents: new Map(), paraIdAlias: new Map(), apiOnline: true, paragraphs: [] },
  localStorage: {
    getItem: k => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
  },
  apiOn: true,
  fetches: [],
  apiReplies: {},          // id → body | Error
  paintWorkspaceBadge() {},
};
vm.createContext(ctx);
vm.runInContext(`
  function apiEnabled() { return apiOn; }
  async function apiFetch(path) {
    fetches.push(path);
    const id = decodeURIComponent(path.replace('/api/paragraph/', ''));
    const r = apiReplies[id];
    if (r && !r.para_id) throw r;          // an Error from the outer realm
    if (!r) { const e = new Error('Unknown'); e.status = 404; e.detail = 'Unknown para_id'; e.payload = { detail: 'Unknown para_id' }; throw e; }
    return r;
  }
  function adaptApiHit(h) { return { id: h.para_id, docId: h.doc_id, text: h.text, _apiOnly: true }; }
  ${['_LS', '_lsGet', '_lsSet', 'documentIdForParagraphId', '_paraIdInDoc', '_registerLegacyParaIds',
     '_paraIdResolving', 'resolveParagraphId', '_docIdFromParaId', '_canonParaId', '_wsMigrateParaIds']
    .map(lift).join('\n')}
  globalThis.api = { documentIdForParagraphId, _paraIdInDoc, _registerLegacyParaIds, resolveParagraphId,
                     _docIdFromParaId, _canonParaId, _wsMigrateParaIds, _LS };
`, ctx);
const { api, state } = ctx;

const JUR = 'ccpr-c-50-d-488-1992';
const SURVIVOR = 'ccpr-c-133-d-2904-2907-2016';
const MERGED = 'ccpr-c-133-d-2904-2016-2907-2016';
state.documents.set(JUR, { docId: JUR, type: 'jur' });
state.documents.set(SURVIVOR, { docId: SURVIVOR, type: 'jur', alternativeIds: [MERGED] });
state.documents.set('crpd-c-gc-6', { docId: 'crpd-c-gc-6', type: 'gc' });
state.documents.set('crpd-c-gc-6-extra', { docId: 'crpd-c-gc-6-extra', type: 'gc' });

let passed = 0;
async function t(name, fn) {
  try { await fn(); passed++; console.log(`ok   ${name}`); }
  catch (e) { console.log(`FAIL ${name}\n     ${e.message}`); process.exitCode = 1; }
}

await t('_docIdFromParaId: label ids split on the first colon', () => {
  assert.equal(api._docIdFromParaId(`${JUR}:8.2`), JUR);
  assert.equal(api._docIdFromParaId(`${JUR}:OP1-U3`), JUR);
  assert.equal(api._docIdFromParaId(`${JUR}:A1-2`), JUR);
  assert.equal(api._docIdFromParaId(`${JUR}:2.1~2`), JUR);
  assert.equal(api._docIdFromParaId(`${JUR}:u3`), JUR);
});
await t('_docIdFromParaId: positional GC / SP / legacy JUR ids', () => {
  assert.equal(api._docIdFromParaId(`${JUR}-0005`), JUR);
  assert.equal(api._docIdFromParaId('crpd-c-gc-6-0001'), 'crpd-c-gc-6');
  assert.equal(api._docIdFromParaId('a-hrc-58-58-0008'), 'a-hrc-58-58');
  assert.equal(api._docIdFromParaId('no-number'), null);
  assert.equal(api._docIdFromParaId(''), null);
});
await t('documentIdForParagraphId: new, legacy, GC and alternativeIds', () => {
  assert.equal(api.documentIdForParagraphId(`${JUR}:8.2`), JUR);
  assert.equal(api.documentIdForParagraphId(`${JUR}:OP1-U3`), JUR);
  assert.equal(api.documentIdForParagraphId(`${JUR}-0005`), JUR);
  assert.equal(api.documentIdForParagraphId('crpd-c-gc-6-0024'), 'crpd-c-gc-6');
  assert.equal(api.documentIdForParagraphId('crpd-c-gc-6-extra-0002'), 'crpd-c-gc-6-extra');
  assert.equal(api.documentIdForParagraphId(`${MERGED}-0005`), SURVIVOR);
  assert.equal(api.documentIdForParagraphId(`${MERGED}:2.3`), SURVIVOR);
  assert.equal(api.documentIdForParagraphId('unknown-doc:8.2'), null);
  assert.equal(api.documentIdForParagraphId(null), null);
});
await t('_paraIdInDoc: accepts both separators', () => {
  assert.ok(api._paraIdInDoc(`${JUR}:8.2`, JUR));
  assert.ok(api._paraIdInDoc(`${JUR}-0005`, JUR));
  assert.ok(!api._paraIdInDoc(`${JUR}:8.2`, 'ccpr-c-50-d-48'));
  assert.ok(!api._paraIdInDoc('crpd-c-gc-6-0001', JUR));
  assert.ok(!api._paraIdInDoc(null, JUR));
});

// Legacy index, as _ingestJurShardData builds it from shard legacyIds.
const shard = [
  { id: `${JUR}:8.2`, docId: JUR, legacyIds: [`${JUR}-0005`] },
  { id: `${JUR}:2.1~2`, docId: JUR, legacyIds: [`${JUR}-0003`, `${JUR}:2.1`] },
  { id: `${JUR}:u1`, docId: JUR },
];
for (const p of shard) { api._registerLegacyParaIds(p); state.paragraphById.set(p.id, p); }

await t('_registerLegacyParaIds: positional and earlier-label ids index to the new id', () => {
  assert.equal(state.paraIdAlias.get(`${JUR}-0005`), `${JUR}:8.2`);
  assert.equal(state.paraIdAlias.get(`${JUR}-0003`), `${JUR}:2.1~2`);
  assert.equal(state.paraIdAlias.get(`${JUR}:2.1`), `${JUR}:2.1~2`);
  assert.equal(api._registerLegacyParaIds({ id: 'x' }), 0);
});
await t('resolveParagraphId: loaded, legacy-indexed and GC ids need no API call', async () => {
  ctx.fetches.length = 0;
  assert.equal(await api.resolveParagraphId(`${JUR}:8.2`), `${JUR}:8.2`);
  assert.equal(await api.resolveParagraphId(`${JUR}-0005`), `${JUR}:8.2`);
  assert.equal(await api.resolveParagraphId(`${JUR}:2.1`), `${JUR}:2.1~2`);
  assert.equal(await api.resolveParagraphId('crpd-c-gc-6-0099'), 'crpd-c-gc-6-0099');
  assert.equal(ctx.fetches.length, 0);
});
await t('resolveParagraphId: API redirect, cached and coalesced', async () => {
  ctx.fetches.length = 0;
  ctx.apiReplies[`${JUR}-0009`] = { para_id: `${JUR}:9.1`, doc_id: JUR, text: 'x', redirected_from: `${JUR}-0009` };
  const [a, b] = await Promise.all([api.resolveParagraphId(`${JUR}-0009`), api.resolveParagraphId(`${JUR}-0009`)]);
  assert.equal(a, `${JUR}:9.1`);
  assert.equal(b, `${JUR}:9.1`);
  assert.equal(await api.resolveParagraphId(`${JUR}-0009`), `${JUR}:9.1`);
  assert.deepEqual(ctx.fetches, [`/api/paragraph/${encodeURIComponent(`${JUR}-0009`)}`]);
  assert.equal(state.paragraphById.get(`${JUR}:9.1`)?._apiOnly, true);
});
await t('resolveParagraphId: removed record → null (top-level or detail payload)', async () => {
  const top = Object.assign(new Error('gone'), { status: 404, detail: 'removed', payload: { detail: 'removed', doc_id: JUR, removed: true } });
  const nested = Object.assign(new Error('gone'), { status: 404, detail: { doc_id: JUR, removed: true }, payload: { detail: { doc_id: JUR, removed: true } } });
  ctx.apiReplies[`${JUR}-0040`] = top;
  ctx.apiReplies[`${JUR}-0041`] = nested;
  assert.equal(await api.resolveParagraphId(`${JUR}-0040`), null);
  assert.equal(await api.resolveParagraphId(`${JUR}-0041`), null);
});
await t('resolveParagraphId: unknown id kept; network error kept and retried', async () => {
  assert.equal(await api.resolveParagraphId(`${JUR}-0077`), `${JUR}-0077`);
  assert.equal(state.paraIdAlias.get(`${JUR}-0077`), `${JUR}-0077`);
  ctx.apiReplies[`${JUR}-0078`] = Object.assign(new Error('timeout'), { status: undefined });
  assert.equal(await api.resolveParagraphId(`${JUR}-0078`), `${JUR}-0078`);
  assert.ok(!state.paraIdAlias.has(`${JUR}-0078`));
});
await t('resolveParagraphId: API off → id unchanged, no fetch, not cached', async () => {
  ctx.apiOn = false; ctx.fetches.length = 0;
  assert.equal(await api.resolveParagraphId(`${JUR}-0080`), `${JUR}-0080`);
  assert.equal(ctx.fetches.length, 0);
  assert.ok(!state.paraIdAlias.has(`${JUR}-0080`));
  ctx.apiOn = true;
});
await t('_wsMigrateParaIds: bookmarks / notes / pins move, nothing is dropped', () => {
  const { _LS } = api;
  store.set(_LS.bm, JSON.stringify([
    { paraId: `${JUR}-0005`, docId: JUR, addedAt: 1 },
    { paraId: `${JUR}:8.2`, docId: JUR, addedAt: 2 },     // saved again under the new id
    { paraId: `${JUR}-0040`, docId: JUR, addedAt: 3 },    // removed record: kept as is
    { paraId: `${JUR}-0080`, docId: JUR, addedAt: 4 },    // unresolved: kept as is
    { paraId: 'crpd-c-gc-6-0001', docId: 'crpd-c-gc-6', addedAt: 5 },
  ]));
  store.set(_LS.notes, JSON.stringify({ [`${JUR}-0003`]: 'old note', [`${JUR}:2.1`]: 'label note', 'crpd-c-gc-6-0001': 'gc' }));
  store.set(_LS.pins, JSON.stringify([{ paraId: `${JUR}-0009`, docId: JUR, addedAt: 1 }]));
  assert.equal(api._wsMigrateParaIds(), true);
  const bm = JSON.parse(store.get(_LS.bm)).map(b => b.paraId);
  assert.deepEqual(bm, [`${JUR}:8.2`, `${JUR}-0040`, `${JUR}-0080`, 'crpd-c-gc-6-0001']);
  const notes = JSON.parse(store.get(_LS.notes));
  assert.equal(notes[`${JUR}:2.1~2`], 'old note\n\nlabel note');
  assert.equal(notes['crpd-c-gc-6-0001'], 'gc');
  assert.ok(!(`${JUR}-0003` in notes));
  assert.deepEqual(JSON.parse(store.get(_LS.pins)).map(p => p.paraId), [`${JUR}:9.1`]);
  assert.equal(api._wsMigrateParaIds(), false);          // idempotent
});
await t('_canonParaId: maps known old ids only', () => {
  assert.equal(api._canonParaId(`${JUR}-0005`), `${JUR}:8.2`);
  assert.equal(api._canonParaId(`${JUR}-0040`), `${JUR}-0040`);   // removed → unchanged
  assert.equal(api._canonParaId('crpd-c-gc-6-0001'), 'crpd-c-gc-6-0001');
});

console.log(`\n${passed} passed${process.exitCode ? ', some FAILED' : ''}`);
