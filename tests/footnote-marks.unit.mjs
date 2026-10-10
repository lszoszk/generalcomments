// Unit checks for footnote rendering in docs/assets/app.js (v19.81): PDF
// notes of old UN compilations show their printed mark ("a/"), and notes
// that no legible reference points to are listed under the paragraph.
//
//   node tests/footnote-marks.unit.mjs
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const SRC = readFileSync(new URL('../docs/assets/app.js', import.meta.url), 'utf8');

function lift(name) {
  const m = new RegExp(`^(?:function ${name}\\(|const ${name} = )`, 'm').exec(SRC);
  if (!m) throw new Error(`not found in app.js: ${name}`);
  const eol = SRC.indexOf('\n', m.index);
  if (m[0].startsWith('const') && !SRC.slice(m.index, eol).includes('{')) return SRC.slice(m.index, eol);
  const open = SRC.indexOf('{', SRC.indexOf(m[0].startsWith('const') ? '=' : ')', m.index));
  let depth = 0;
  for (let i = open; i < SRC.length; i++) {
    if (SRC[i] === '{') depth++;
    else if (SRC[i] === '}' && --depth === 0) return SRC.slice(m.index, i + 1);
  }
  throw new Error(`unbalanced: ${name}`);
}

const ctx = { highlight: (t) => t };
vm.createContext(ctx);
vm.runInContext(['escape', 'FN_MARKER_RE', 'stripFnMarkers', '_fnButtonHtml', 'renderUnanchoredNotes', 'renderParagraphHtml']
  .map(lift).join('\n') + '\nthis.api = { renderParagraphHtml, renderUnanchoredNotes };', ctx);
const { renderParagraphHtml, renderUnanchoredNotes } = ctx.api;

let passed = 0;
function test(name, fn) { fn(); passed++; console.log(`ok   ${name}`); }

test('numbered footnotes still show their number', () => {
  const html = renderParagraphHtml('A claim.[[fn:12]]', [{ n: 12, text: 'See general comment No. 16.' }]);
  assert.match(html, /<sup>12<\/sup>/);
  assert.match(html, /data-fn-label="12"/);
});

test('lettered notes show the printed mark', () => {
  const html = renderParagraphHtml("as Victor Jan.[[fn:3]] Amongst", [{ n: 3, text: 'A well-known singer.', mark: 'c/' }]);
  assert.match(html, /<sup>c\/<\/sup>/);
  assert.match(html, /aria-label="Footnote c\/: A well-known singer\."/);
  assert.match(html, /data-fn-n="3"/);
});

test('unanchored notes are listed, anchored ones are not', () => {
  const html = renderUnanchoredNotes([
    { n: 1, text: 'An opposition movement.', mark: 'a/', anchored: false },
    { n: 3, text: 'A well-known singer.', mark: 'c/' },
  ]);
  assert.match(html, /Notes not marked in the text/);
  assert.match(html, /<sup>a\/<\/sup>/);
  assert.doesNotMatch(html, /c\//);
  assert.match(html, /data-fn-flags="unanchored"/);
});

test('no list when every note is anchored', () => {
  assert.equal(renderUnanchoredNotes([{ n: 1, text: 'x' }]), '');
  assert.equal(renderUnanchoredNotes(undefined), '');
});

console.log(`\n${passed} passed`);
