"""PDF footnotes and endnotes become paragraph footnotes, as on the DOCX route."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import ingest_jurisprudence as ij  # noqa: E402

FIX = Path(__file__).resolve().parent / 'fixtures' / 'jur_errata'


def notes(paragraphs):
    """{(paragraph, n): normalised text} for every footnote."""
    return {(p['ID'], f['n']): re.sub(r'[^a-z0-9]', '', f['text'].lower())
            for p in paragraphs for f in p.get('Footnotes', [])}


def assert_markers_have_notes(paragraphs):
    for p in paragraphs:
        own = {f['n'] for f in p.get('Footnotes', [])}
        for m in re.findall(r'\[\[fn:(\d+)\]\]', p['Text']):
            assert int(m) in own, (p['ID'], m)
        assert '[[ref:' not in p['Text']


def ocr(doc_id):
    return ij._parse_pdf_text_pages([p.read_text() for p in sorted((FIX / f'ocr_{doc_id}').glob('page-*.txt'))])


@pytest.mark.parametrize('stem', [
    'CCPR_C_139_D_2929_2017_E',   # footnote rule drawn as a graphic, title-page */**/*** notes
    'CCPR_C_131_D_3163_2018_E',   # numbering restarts in each annexed opinion
    'CCPR_C_82_D_903_1999_E',     # older Word export: body-size notes, small number
])
def test_pdf_footnotes_match_the_docx(stem):
    pdf = ij.extract_pdf_paragraphs(FIX / f'{stem}.pdf')
    docx = ij.extract_docx_paragraphs(FIX / f'{stem}.docx')
    assert notes(pdf) == notes(docx)
    assert notes(pdf)
    assert_markers_have_notes(pdf)


def test_numbered_endnotes_with_parenthesised_references():
    ps = ij.extract_pdf_paragraphs(FIX / 'CCPR_C_50_D_488_1992_E.pdf')   # Toonen, notes after "-*-"
    fn = {f['n']: (p['ID'], f['text']) for p in ps for f in p.get('Footnotes', [])}
    assert fn[1] == ('7.5.', fn[1][1]) and fn[1][1].startswith('Dudgeon v. United Kingdom')
    assert fn[4][0] == '8.3.' and fn[4][1].startswith('Document CCPR/C/21/Rev.1')
    assert 'Rights.[[fn:1]]' in [p for p in ps if p['ID'] == '7.5.'][0]['Text']
    # The title-page "*/ Made public by decision ..." note belongs to no paragraph.
    assert not any('Made public' in f['text'] for p in ps for f in p.get('Footnotes', []))
    assert_markers_have_notes(ps)


def test_endnotes_over_a_page_break_and_spaced_references():
    ps = ij.extract_pdf_paragraphs(FIX / 'CAT_C_27_D_162_2000_E.pdf')
    assert [p['ID'] for p in ps][-1] == '7.4.'          # notes 4-11 are not paragraphs
    fns = [f for p in ps for f in p.get('Footnotes', [])]
    assert sorted(f['n'] for f in fns) == list(range(1, 12))
    assert sum(f.get('anchored', True) for f in fns) >= 9
    assert 'abuses.[[fn:1]]' in [p for p in ps if p['ID'] == '2.9.'][0]['Text']
    assert_markers_have_notes(ps)


def test_garbled_ocr_marks():
    ps = ij.extract_pdf_paragraphs(FIX / 'CCPR_C_18_D_74_1980_E.pdf')    # Estrella: "!I", "BI", "£/"
    fns = [f for p in ps for f in p.get('Footnotes', [])]
    assert [f['mark'] for f in sorted(fns, key=lambda f: f['n'])] == ['a/', 'b/', 'c/']
    c = [(p['ID'], f) for p in ps for f in p.get('Footnotes', []) if f['mark'] == 'c/'][0]
    assert c[0] == '1.6.' and c[1]['text'].startswith('A well-known Chilean singer')
    assert_markers_have_notes(ps)


def test_lettered_endnotes_and_the_opinion_after_them():
    ps = ocr('ccpr-c-39-d-295-1988')
    linked = {f['mark']: p['ID'] for p in ps for f in p.get('Footnotes', [])}
    assert linked == {'a/': '4.1.', 'b/': '6.3.'}
    opinion = [p for p in ps if p.get('Namespace')]
    assert opinion and opinion[0]['Text'].startswith('We share the view expressed by the majority')
    assert_markers_have_notes(ps)


def test_page_foot_notes_and_the_page_after_them():
    ps = ocr('ccpr-c-37-d-369-1989')
    placed = {f['n']: (p['ID'], f.get('anchored', True)) for p in ps for f in p.get('Footnotes', [])}
    # Note b/ is cited nowhere legible: it stays with the decision, not the opinion.
    assert placed == {1: ('3.2.', True), 2: ('4.', False)}
    assert any(p['Text'].startswith('As emphasised by the Committee') for p in ps)


def test_translated_opinion_is_kept_with_its_notes():
    # "Annex I [Original: Spanish]" heads an English translation.
    ps = ij.extract_pdf_paragraphs(FIX / 'CCPR_C_144_D_2982_2017_E.pdf')
    assert {p.get('Namespace') for p in ps} >= {'OP1', 'OP2'}
    fns = [f for p in ps for f in p.get('Footnotes', [])]
    assert len(fns) == 16 and all(f.get('anchored', True) for f in fns)
    docx = ij.extract_docx_paragraphs(FIX / 'CAT_C_66_D_776_2016_E.docx')
    assert any(p['ID'].startswith('OP1-') for p in docx)


def test_provision_numbers_are_not_note_references():
    paras = [{'ID': '1.', 'Text': 'Under article 14, paragraph (1) and the author.(1) It was so.'}]
    out = ij._attach_notes(paras, [{'mark': '1', 'text': 'A note.', 'style': 'number', 'kind': 'end'}])
    assert out[0]['Text'] == 'Under article 14, paragraph (1) and the author.[[fn:1]] It was so.'


def test_marks_that_restart_pair_up_in_order():
    paras = [{'ID': '1.', 'Text': 'First claim, a/ second claim b/'}, {'ID': '2.', 'Text': 'Later claim, a/ end.'}]
    page_notes = [{'mark': 'a', 'text': 'Note one.', 'style': 'letter'}, {'mark': 'b', 'text': 'Note two.', 'style': 'letter'},
                  {'mark': 'a', 'text': 'Note three.', 'style': 'letter'}]
    out = ij._attach_notes(paras, page_notes)
    assert out[0]['Footnotes'] == [{'n': 1, 'text': 'Note one.', 'mark': 'a/'}, {'n': 2, 'text': 'Note two.', 'mark': 'b/'}]
    assert out[1]['Footnotes'] == [{'n': 3, 'text': 'Note three.', 'mark': 'a/'}]
    assert out[1]['Text'] == 'Later claim,[[fn:3]] end.'
