/* DOM-level harness for annotateTreatyText (v19.67-v19.75).
   Each case is one mocked search hit; the rendered result list is the
   assertion surface — the same path a real API result takes.
   Runs in chunks of 15 because the list appends 20 per page and the reader
   has no loader to call, so a longer suite silently stops asserting. */
import { createRequire } from 'module';
const require = createRequire(import.meta.url);
import { chromium } from '/Users/lszoszk/Desktop/generalcomments-repo/node_modules/playwright/index.mjs';

const CASES = [
  // ── v19.67 ─────────────────────────────────────────────────────────────
  { id:'op-lead',    committee:'CCPR', text:'The communication is inadmissible under the Optional Protocol (article 2) for lack of substantiation.', expect:{'2':'ICCPR-OP1'} },
  { id:'op-tail',    committee:'CCPR', text:'Obligations arise under articles 1 and 5 of the Optional Protocol in every registered case.', expect:{'1':'ICCPR-OP1','5':'ICCPR-OP1'} },
  { id:'op2-lead',   committee:'CCPR', text:'Abolition is required under the Second Optional Protocol (art. 1) without reservation.', expect:{'1':'ICCPR-OP2'} },
  { id:'letters',    committee:'CCPR', text:'As guaranteed by articles 2 (c), 3, 5 (a) and 15 of the Convention on the Elimination of All Forms of Discrimination Against Women, women enjoy equality.', expect:{'2':'CEDAW','3':'CEDAW','5':'CEDAW','15':'CEDAW'} },
  { id:'range-home', committee:'CERD', text:'the rights in arts. 13–14 are protected for everyone', expect:{'13':'CERD','14':'CERD'} },
  { id:'range-tail', committee:'CERD', text:'education under arts. 13–14 of the International Covenant on Economic, Social and Cultural Rights is guaranteed', expect:{'13':'ICESCR','14':'ICESCR'} },
  { id:'constit',    committee:'CCPR', text:'In accordance with the Constitution (art. 41), everyone may acquire property.', expect:{} },
  { id:'asylum-act', committee:'CAT',  text:'Asylum was refused under the Federal Asylum Act (art. 32) by the domestic authorities.', expect:{} },
  { id:'neg-law',    committee:'CCPR', text:'Equality before the law (art. 26) is guaranteed to all persons.', expect:{'26':'ICCPR'} },
  { id:'neg-home',   committee:'CCPR', text:'The State party violated article 7 of the Covenant in this case.', expect:{'7':'ICCPR'} },
  { id:'crc-plain',  committee:'CRC',  text:'The claim is inadmissible under the Optional Protocol (article 7) as submitted.', expect:{} },
  // ── v19.68: bridge / lowercase tail / non-adjacent lead ────────────────
  { id:'bridge-op',     committee:'CCPR', text:'The claim is inadmissible under article 5, paragraph 2 (a), of the Optional Protocol as submitted.', expect:{'5':'ICCPR-OP1'} },
  { id:'bridge-home',   committee:'CCPR', text:'The State party violated article 19, paragraph 3, of the Covenant in this matter.', expect:{'19':'ICCPR'} },
  { id:'lower-tail',    committee:'CCPR', text:'The decision was taken in accordance with the law (article 26 of the decree of 2 November 1945 as amended).', expect:{} },
  { id:'lead-near',     committee:'CCPR', text:'The Korean Constitution contains a provision (article 37, paragraph 2) stipulating that freedoms may be restricted.', expect:{} },
  { id:'lead-near-neg', committee:'CRPD', text:'he has not made a complaint under section 24 of the Anti-Discrimination Act to request special accommodation (art. 13) and never challenged it.', expect:{'13':'CRPD'} },
  // ── v19.69: series propagation (forward, plain-text only) ──────────────
  { id:'series',        committee:'CRPD', text:'it violated the fundamental rights to work and to vocational rehabilitation (arts. 35 and 40 of the Constitution), the inclusion of persons with disabilities (art. 49), access to and retention of public employment (art. 23) and respect for human dignity (art. 10).', expect:{} },
  { id:'series-break',  committee:'CCPR', text:'the detention order (art. 12 of the Criminal Code) was upheld, and the Committee recalls that the Covenant guarantees fair trial (art. 14).', expect:{'14':'ICCPR'} },
  { id:'series-sent',   committee:'CCPR', text:'The appeal cited the ordinance (art. 7 of the Decree). The author further invoked the right to liberty (art. 9).', expect:{'9':'ICCPR'} },
  { id:'series-home',   committee:'CRC',  text:'the general measures of implementation (arts. 4 and 42 of the Convention) and the best interests principle (art. 3) apply.', expect:{'4':'CRC','42':'CRC','3':'CRC'} },
  // ── v19.70: soft-law units, gated on an adjacent instrument name ───────
  { id:'sl-tail-rule',  committee:'CAT',  text:'The Committee recalls that, under rule 44 of the Nelson Mandela Rules, prolonged solitary confinement is prohibited.', expect:{'44':'Mandela Rules'} },
  { id:'sl-principle',  committee:'CCPR', text:'In pursuance of principle 12 of the Body of Principles for the Protection of All Persons under Any Form of Detention or Imprisonment, the arrest must be recorded.', expect:{'12':'Body of Principles'} },
  { id:'sl-neg-rop',    committee:'CAT',  text:'The Committee, pursuant to rule 108, paragraph 1, of its rules of procedure, requested interim measures.', expect:{} },
  { id:'sl-neg-unit',   committee:'CAT',  text:'principle 44 of the Nelson Mandela Rules was invoked by counsel.', expect:{} },
  // ── v19.71-72: Geneva family + phantom guard ───────────────────────────
  { id:'gc-common3',  committee:'CAT',  text:'evidence of its violation of common article 3 of the four Geneva Conventions of 12 August 1949 was presented.', expect:{'3':'Geneva Conventions'} },
  { id:'gc-phantom',  committee:'CCPR', text:'the deportation prohibition in article 47 of the Geneva Conventions is absolute.', expect:{} },
  { id:'gc3-tail',    committee:'CAT',  text:'a violation of article 12 of the Third Geneva Convention was alleged by the author.', expect:{'12':'GC III'} },
  { id:'ap1-tail',    committee:'CCPR', text:'the fundamental guarantees in article 75 of Additional Protocol I bind all parties.', expect:{'75':'AP I'} },
  // ── v19.73: sentence-final period ──────────────────────────────────────
  { id:'eos-home',      committee:'CCPR', text:'The seizure violated article 19 of the Covenant.', expect:{'19':'ICCPR'} },
  { id:'eos-bridge',    committee:'CCPR', text:'The author invokes article 19, paragraph 2, of the Covenant.', expect:{'19':'ICCPR'} },
  // ── v19.74: Special Procedures have no home treaty ─────────────────────
  { id:'sp-named',    committee:'SR Torture', text:'The Special Rapporteur recalls article 75 of Additional Protocol I in this context.', expect:{'75':'AP I'} },
  { id:'sp-udhr',     committee:'WG Arbitrary Detention', text:'as set out in article 9 of the Universal Declaration of Human Rights, no one shall be subjected to arbitrary arrest.', expect:{'9':'UDHR'} },
  { id:'sp-bare-cov', committee:'SR Freedom of Expression', text:'The restriction must satisfy the three-part test in article 19, paragraph 3, of the Covenant.', expect:{} },
  { id:'sp-domestic', committee:'SR Indigenous Peoples', text:'the consultation duty in article 6 of the Constitution was not observed.', expect:{} },
  // ── #24: hipotezy do zmierzenia ─────────────────────────────────────────
  // (a) traktat DOMOWY nazwany pelna nazwa w ogonie
  { id:'H-home-fullname', committee:'CCPR', text:'the facts disclose violations of articles 7 and 10, paragraph 1, of the International Covenant on Civil and Political Rights.', expect:{'7':'ICCPR','10':'ICCPR'} },
  // (b) propagacja WSTECZ: numery przed nazwa instrumentu
  { id:'H-backward',      committee:'CRC',  text:'The Committee finds a violation of articles 1, 2 and 6, read together with article 3 of the Optional Protocol on the sale of children, child prostitution and child pornography.', expect:{'1':'CRC-OPSC','2':'CRC-OPSC','3':'CRC-OPSC','6':'CRC-OPSC'} },
  // (c) trzy protokoly CRC rozpoznawane po tytule
  { id:'H-crc-opsc',      committee:'CRC',  text:'inadmissible under article 7 of the Optional Protocol on the sale of children, child prostitution and child pornography.', expect:{'7':'CRC-OPSC'} },
  { id:'H-crc-opic',      committee:'CRC',  text:'inadmissible under article 7 of the Optional Protocol on a communications procedure.', expect:{'7':'CRC-OPIC'} },
  { id:'H-crc-opac',      committee:'CRC',  text:'a violation of article 4 of the Optional Protocol on the involvement of children in armed conflict was alleged.', expect:{'4':'CRC-OPAC'} },
  // Kontrole negatywne propagacji wstecz — miedzy numerem a nazwa moze byc
  // wylacznie klej listy; czasownik lub druga klauzula musi ja zatrzymac.
  { id:'B-neg-verb',   committee:'CCPR', text:'The Committee examined articles 9 and 14 before turning to the obligations of the Convention on the Rights of the Child.', expect:{'9':'ICCPR','14':'ICCPR'} },
  { id:'B-neg-clause', committee:'CCPR', text:'The author invoked article 9, and the State party replied that the courts applied article 3 of the Convention on the Rights of the Child.', expect:{'9':'ICCPR','3':'CRC'} },
  // Pozytyw: sam klej listy (przecinki, "and", numery) — propagacja dziala.
  { id:'B-glue',       committee:'CCPR', text:'a violation of articles 6, 7 and 9, read together with article 2 of the Convention on the Rights of the Child.', expect:{'6':'CRC','7':'CRC','9':'CRC','2':'CRC'} },
  // ── v19.76: IDP Guiding Principles (bundle-only, unit pass) ────────────
  { id:'idp-tail',  committee:'SR Torture', text:'as set out in principle 6 of the Guiding Principles on Internal Displacement, arbitrary displacement is prohibited.', expect:{'6':'GP Internal Displacement'} },
  { id:'idp-lead',  committee:'CCPR', text:'The Guiding Principles on Internal Displacement (principle 28) place the primary duty on competent authorities.', expect:{'28':'GP Internal Displacement'} },
  // Bez kwalifikatora "the Guiding Principles" nie wybiera miedzy IDP a UNGPs.
  { id:'idp-neg',   committee:'CESCR', text:'the State should follow principle 6 of the Guiding Principles in this respect.', expect:{} },
  // ── v19.77: Bangkok Rules — przyklad wprost z korpusu (CAT, dzieci w wiezieniu)
  { id:'bkk-tail',  committee:'CAT',  text:'The Committee further recalls that, under rule 52 of the Bangkok Rules, decisions as to when a child is to be separated from its mother shall be based on individual assessments.', expect:{'52':'Bangkok Rules'} },
  { id:'bkk-lead',  committee:'CEDAW', text:'The Bangkok Rules (rule 2) require adequate attention to admission procedures for women.', expect:{'2':'Bangkok Rules'} },
  // Regulamin proceduralny komitetu nadal nie moze sie zlinkowac z Bangkok.
  { id:'bkk-neg',   committee:'CAT',  text:'pursuant to rule 52 of its rules of procedure, the Committee requested comments.', expect:{} },
];

const b = await chromium.launch({ args: ['--disable-web-security'] });
const p = await (await b.newContext({ viewport:{width:1440,height:900}, ignoreHTTPSErrors: true })).newPage();
let CURRENT = [];
await p.route(/150\.254\.115\.204\/unhrdb-api\/api\/search/, route => route.fulfill({
  status: 200, headers: {'content-type':'application/json','access-control-allow-origin':'*'},
  body: JSON.stringify({ query:'harness', scope:'all', total:CURRENT.length, breakdown:{gc:CURRENT.length,jur:0,sp:0}, page:1, page_size:50,
    hits: CURRENT.map((c,i) => ({ rowid:i+1, para_id:'case-'+c.id, doc_id:'doc-'+c.id, idx:i, n:String(i),
      section:null, text:c.text, type:'gc', treaty:c.committee, committee:c.committee, mandate:null,
      country:null, year:2020, adoption_date:'2020-01-01', signature:'TEST/'+c.id, outcome:null,
      name:'Case '+c.id, name_short:c.id, snippet:c.text.slice(0,80), score:-10-i })) }),
}));
await p.route(/150\.254\.115\.204\/unhrdb-api\/api\/stats/, route => route.fulfill({
  status: 200, headers: {'content-type':'application/json','access-control-allow-origin':'*'},
  body: JSON.stringify({version:'test', totalParagraphs:1, manifest:{counts:{paragraphs:1}}}),
}));
await p.route(/150\.254\.115\.204\/ask-api\/api\/treaties/, route => route.fulfill({
  status: 200, headers: {'content-type':'application/json','access-control-allow-origin':'*'},
  body: require('fs').readFileSync(process.env.BUNDLE || '/tmp/treaties-bundle.json', 'utf8'),
}));

let fails = 0;
const fmt = o => Object.keys(o).length ? Object.entries(o).map(([a,t])=>`${a}:${t}`).join(',') : '(plain)';
for (let start = 0; start < CASES.length; start += 15) {
  CURRENT = CASES.slice(start, start + 15);
  await p.goto('http://localhost:8788/index.html?api=1&scope=all&q=harness&n=' + start, { waitUntil: 'commit' });
  await p.waitForFunction(n => document.querySelectorAll('#result-list li').length >= n, CURRENT.length, {timeout: 60000});
  await p.waitForTimeout(2500);
  const res = await p.evaluate((cases) => cases.map(c => {
    // Match on the case id, not a text prefix: two cases can share their first
    // 40 characters ("…of the Optional Protocol on the sale…" vs "…on a
    // communications procedure"), and a prefix match then silently reads the
    // wrong row and blames the code.
    // Match the id with its delimiters, not a text prefix: two cases can share
    // their first 40 characters ("…Optional Protocol on the sale…" vs "…on a
    // communications procedure"), and a prefix match then silently reads the
    // wrong row and blames the code. The delimiters also keep "series" from
    // matching "series-break".
    const li = Array.from(document.querySelectorAll('#result-list li'))
      .find(x => (x.textContent || '').replace(/\s+/g, ' ').includes('· ' + c.id + ' '));
    if (!li) return { id: c.id, error: 'hit not rendered' };
    const got = {};
    li.querySelectorAll('.treaty-article-ref').forEach(b => { got[b.dataset.article] = b.dataset.treaty; });
    return { id: c.id, got };
  }), CURRENT);
  for (const [i, r] of res.entries()) {
    const c = CURRENT[i];
    const ok = r.error ? false
      : JSON.stringify(Object.entries(c.expect).sort()) === JSON.stringify(Object.entries(r.got).sort());
    if (!ok) fails++;
    console.log(`${ok?'✓':'✗'} ${r.id.padEnd(14)} want=${fmt(c.expect)}  got=${r.error || fmt(r.got)}`);
  }
}
console.log(fails ? `\nFAILS: ${fails}/${CASES.length}` : `\nALL PASS (${CASES.length})`);
await b.close();
process.exit(fails ? 1 : 0);
