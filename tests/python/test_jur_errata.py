"""Regression tests for the UNHRDB jurisprudence errata (vclt-interpreter
docs/UNHRDB_ERRATA.md, 6 October 2026).

Fixtures are the official texts of the documents named in the errata (UN
ODS / OHCHR) and, for CCPR/C/52/D/453/1991, the page text our Tesseract run
produced, with the TSV leak in it.

    python3 -m pytest tests/python
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import build_jurisprudence_shards as shards  # noqa: E402
import clean_extract  # noqa: E402
import ingest_jurisprudence as ij  # noqa: E402
import ocr_jurisprudence as ocr  # noqa: E402

FIX = Path(__file__).resolve().parent / 'fixtures' / 'jur_errata'
TSV_RESIDUE = re.compile(r'(?:\b\d+[\t ]+){8,}-?\d+\.\d{3,6}\b')


def ids(paragraphs):
    return [p['ID'] for p in paragraphs]


def main_ids(paragraphs):
    return [p['ID'].rstrip('.') for p in paragraphs if not p.get('Namespace')]


def text(paragraphs, pid):
    hits = [p['Text'] for p in paragraphs if p['ID'] == pid]
    assert hits, f'no paragraph {pid}'
    return hits[0]


def assert_continuous(labels):
    """Main-body labels run 1 / 1.1 ... without gaps, repeats or strays."""
    major, minor = 0, 0
    for lab in labels:
        a, _, b = lab.partition('.')
        a = int(a)
        if not b:
            assert a == major + 1, f'{lab} after {major}.{minor}'
            major, minor = a, 0
        else:
            b = int(b)
            assert (a == major and b == minor + 1) or (a == major + 1 and b == 1), f'{lab} after {major}.{minor}'
            major, minor = a, b


@pytest.fixture(scope='module')
def toonen():
    return ij.extract_pdf_paragraphs(FIX / 'CCPR_C_50_D_488_1992_E.pdf')


@pytest.fixture(scope='module')
def estrella():
    return ij.extract_pdf_paragraphs(FIX / 'CCPR_C_18_D_74_1980_E.pdf')


@pytest.fixture(scope='module')
def coeriel():
    pages = [p.read_text() for p in sorted((FIX / 'coeriel_ocr').glob('page-*.txt'))]
    return ij._parse_pdf_text_pages(pages)


# --- A: missing and truncated text ----------------------------------------

def test_toonen_has_every_paragraph(toonen):  # A1, C1
    labels = main_ids(toonen)
    assert labels[0] == '1'
    assert_continuous(labels)
    assert labels[-1] == '12'
    for lab in ('5.1', '6.4', '6.8', '6.12', '7.2', '7.7', '8.2'):
        assert lab in labels


def test_toonen_finding_on_article_17_is_complete(toonen):  # A1, A2
    assert text(toonen, '8.2.').startswith('Inasmuch as article 17 is concerned, it is undisputed')
    p86 = text(toonen, '8.6.')
    assert 'these provisions are not currently enforced' in p86
    assert p86.endswith("arbitrarily interfere with Mr. Toonen's right under article 17, paragraph 1.")


def test_toonen_truncated_paragraphs_are_whole(toonen):  # A3
    assert 'his private life and his liberty are threatened' in text(toonen, '2.3.')
    assert 'privacy' in text(toonen, '3.1.')


def test_estrella_has_every_paragraph(estrella):  # A6
    labels = main_ids(estrella)
    assert_continuous(labels)
    for lab in ('1.3', '1.6', '1.8', '1.14', '4.4', '8.5'):
        assert lab in labels
    assert 'subjected to continued ill-treatment' not in text(estrella, '8.4.')
    assert text(estrella, '8.5.').startswith('At Libertad prison')


def test_estrella_9_2_runs_over_the_page_break(estrella):  # A6
    p92 = text(estrella, '9.2.')
    assert '-158-' not in p92
    assert p92.endswith('compatible with article 17 read in conjunction with article 10 (1) of the Covenant.')


def test_coeriel_paragraphs_are_not_merged(coeriel):  # A4
    labels = main_ids(coeriel)
    assert_continuous(labels)
    for lab in ('2.3', '2.4', '3', '4.1'):
        assert lab in labels
    assert len(text(coeriel, '2.2.')) < 1500
    assert text(coeriel, '3.').startswith('The authors claim that the refusal')


def test_coeriel_article_number_is_not_a_paragraph(coeriel):  # A5
    assert '17' not in main_ids(coeriel)
    p102 = text(coeriel, '10.2.')
    assert 'in contravention of article 17. The question arises' in p102


def test_cat_891_docx_keeps_2_6():  # merged DOCX paragraphs (corpus scan)
    ps = ij.extract_docx_paragraphs(FIX / 'CAT_C_74_D_891_2018_E.docx')
    assert '2.6.' in ids(ps)
    assert not text(ps, '2.5.').endswith('2.6.')


# --- B: garbage in text -----------------------------------------------------

def test_coeriel_has_no_tsv_residue(coeriel):  # B1
    for p in coeriel:
        assert not TSV_RESIDUE.search(p['Text']), (p['ID'], p['Text'][:120])


def test_tsv_repair_restores_line_breaks():  # B1, A4 (unit)
    leaked = ('the Guidelines5\t1\t1\t1\t21\t2\t942\t1663\t92\t37\t96.24\tfor'
              '4\t1\t1\t1\t22\t0\t10\t50\t500\t30\t-1\t'
              '5\t1\t1\t1\t22\t1\t10\t50\t50\t30\t96.2\t2.3'
              '5\t1\t1\t1\t22\t2\t70\t50\t50\t30\t96.2\tThe authors')
    assert ij._strip_tesseract_tsv_leaks(leaked) == 'the Guidelines for\n2.3 The authors'


def test_tesseract_tsv_parser_ignores_quotes(monkeypatch):  # B1 root cause
    rows = [
        'level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext',
        '5\t1\t1\t1\t1\t1\t10\t10\t50\t30\t96.1\tthe',
        '5\t1\t1\t1\t1\t2\t70\t10\t50\t30\t96.1\t"Guidelines',
        '5\t1\t1\t1\t1\t3\t130\t10\t50\t30\t96.1\tfor',
        '5\t1\t1\t1\t2\t1\t10\t50\t50\t30\t96.2\t2.3',
        '5\t1\t1\t1\t2\t2\t70\t50\t50\t30\t96.2\tsurnames"',
    ]

    class Proc:
        stdout = '\n'.join(rows) + '\n'

    monkeypatch.setattr(ocr, 'require_tool', lambda name: name)
    monkeypatch.setattr(ocr.subprocess, 'run', lambda *a, **k: Proc())
    cand = ocr.tesseract_tsv(Path('page.png'), psm=6, profile='t', preprocess='none')
    assert cand.text == 'the "Guidelines for\n2.3 surnames"'
    assert cand.word_count == 5


def test_ocr_corrections_keep_plural_authors():  # B3
    fixed, _ = ocr.apply_safe_corrections("The authors of the communication; the authors' request")
    assert fixed == "The authors of the communication; the authors' request"


def test_old_author_s_rewrite_is_undone_where_unambiguous(coeriel):  # B3
    assert text(coeriel, '1.').startswith('The authors of the communication are A.R. Coeriel')
    assert not any(re.search(r"author's['’]", p['Text']) for p in coeriel)


def test_headings_are_not_glued_to_paragraphs(toonen):  # B4
    assert text(toonen, '1.').endswith('International Covenant on Civil and Political Rights.')
    assert text(toonen, '5.2.').endswith('articles 17 and 26 of the Covenant.')
    assert not text(toonen, '7.11.').endswith('Examination of the merits:')


def test_endnotes_are_not_glued_to_the_last_paragraph(toonen, estrella):  # B5
    assert 'APPENDIX' not in text(toonen, '12.')
    assert 'Notes' not in text(estrella, '11.')
    assert not any('Dudgeon v. United Kingdom' in p['Text'] for p in toonen)


# --- C: labels and structure ------------------------------------------------

def test_article_list_in_front_matter_is_not_a_paragraph():  # C1 (PDF)
    # "Articles of the Convention: 2, 10, 11, 12, 13 and 14" read as para. "2,".
    ps = ij.extract_pdf_paragraphs(FIX / 'CAT_C_68_D_852_2017_E.pdf')
    assert ids(ps)[0] == '1.'
    assert text(ps, '1.').startswith('The complainant is Paul Zentveld')
    assert_continuous(main_ids(ps))


def test_session_date_is_not_a_paragraph():  # C1 (DOCX)
    ps = ij.extract_docx_paragraphs(FIX / 'CCPR_C_82_D_903_1999_E.docx')
    assert ids(ps)[0] == '1.1.'
    assert '18.' not in ids(ps)
    assert_continuous(main_ids(ps))


def test_coeriel_opinions_are_namespaced(coeriel):  # C2
    assert main_ids(coeriel).count('1') == 1
    namespaces = {p.get('Namespace') for p in coeriel if p.get('Namespace')}
    assert namespaces == {'OP1', 'OP2'}
    ando = [p for p in coeriel if p.get('Namespace') == 'OP1']
    assert 'Ando' in ando[0]['Section']


def test_toonen_opinion_is_unnumbered(toonen):  # C3
    opinion = [p['ID'] for p in toonen if p.get('Namespace') == 'OP1']
    assert opinion == [f'OP1-U{i}.' for i in range(1, 9)]


def test_lula_opinions_get_separate_namespaces():  # C2 (DOCX, joint opinion)
    ps = ij.extract_docx_paragraphs(FIX / 'CCPR_C_134_D_2841_2016_E.docx')
    by_ns = {}
    for p in ps:
        if p.get('Namespace'):
            by_ns.setdefault(p['Namespace'], []).append(p['ID'])
    assert sorted(by_ns) == ['OP1', 'OP2']
    for ns, labels in by_ns.items():
        assert len(labels) == len(set(labels)), ns


# --- D: metadata --------------------------------------------------------------

def load_paragraphs(name):
    return json.loads((FIX / f'{name}.paragraphs.json').read_text())


@pytest.mark.parametrize('name, expected', [
    ('ccpr-c-130-d-2674-2015', 'inadmissible'),       # D1, K.J. v. Lithuania
    ('ccpr-c-137-d-3662-2019', 'inadmissible'),       # D2, G.A.P. v. Romania
    ('ccpr-c-143-d-3054-2017', 'violation_found'),    # D4, Tolmachev
])
def test_outcome_from_operative_paragraph(name, expected):
    result = ij.classify_outcome(load_paragraphs(name), 'COMMUNICATION NO. 0/0: DECISION/VIEWS')
    assert result['outcome'] == expected


def test_outcome_van_hulst_is_no_violation():  # D3
    ps = ij.extract_docx_paragraphs(FIX / 'CCPR_C_82_D_903_1999_E.docx')
    result = ij.classify_outcome(ps, 'Communication No 903/1999')
    assert result['outcome'] == 'merits_no_violation'
    assert '7.11.' in result['operative_ids']


def test_outcome_estrella_is_violation(estrella):  # D5
    assert ij.classify_outcome(estrella, '')['outcome'] == 'violation_found'


def test_tolmachev_flags_partial_inadmissibility():  # D4
    result = ij.classify_outcome(load_paragraphs('ccpr-c-143-d-3054-2017'), '')
    assert 'partial_inadmissibility' in result['flags']


@pytest.mark.parametrize('raw, iso', [
    ('06 Apr 2018', '2018-04-06'),
    ('17 March 2025', '2025-03-17'),
    ('1 November 2004', '2004-11-01'),
    ('2004-11-01', '2004-11-01'),
    ('~5 JUly', None),
    ('under article 5,', None),
])
def test_iso_dates(raw, iso):  # D7
    assert shards.iso_date(raw) == iso


def test_iso_dates_prefer_the_juris_decision_date():  # D7
    doc = {'jurisDecisionDate': '19 Oct 2020', 'adoptionDate': '19 October 2020', 'submittedDate': '06 Apr 2018'}
    assert shards.iso_dates(doc) == {'adoptionDateIso': '2020-10-19', 'submittedDateIso': '2018-04-06'}


# --- E: footnotes ---------------------------------------------------------------

def footnotes(paragraphs):
    return {f['n']: f['text'] for p in paragraphs for f in p.get('Footnotes', [])}


def markers(paragraphs):
    return [m for p in paragraphs for m in re.findall(r'\[\[fn:([^\]]+)\]\]', p['Text'])]


def test_sudalenko_footnotes_use_printed_numbers():  # E1
    ps = ij.extract_docx_paragraphs(FIX / 'CCPR_C_139_D_2929_2017_E.docx')
    assert markers(ps) == [str(i) for i in range(1, 13)]
    fns = footnotes(ps)
    assert sorted(fns) == list(range(1, 13))
    # Printed footnote 8 cites general comment No. 16 (official PDF).
    assert fns[8].startswith('See the Committee’s general comment No. 16')


def test_lula_footnotes_use_printed_numbers():  # E1
    ps = ij.extract_docx_paragraphs(FIX / 'CCPR_C_134_D_2841_2016_E.docx')
    fns = footnotes(ps)
    assert fns[1] == 'Then rule 97.'
    assert max(fns) == 120
    assert '*' not in markers(ps)


def test_footnote_labels_skip_title_page_marks():  # E1 (unit)
    labels = ij._docx_footnote_labels(FIX / 'CCPR_C_139_D_2929_2017_E.docx')
    assert [labels[i] for i in (1, 2, 3)] == [None, None, None]
    assert [labels[i] for i in range(11, 16)] == ['8', '9', '10', '11', '12']


# --- No regressions -------------------------------------------------------------

def test_modern_pdf_is_unchanged_apart_from_headings():
    ps = ij.extract_pdf_paragraphs(FIX / 'CCPR_C_131_D_3163_2018_E.pdf')
    assert_continuous(main_ids(ps))
    assert main_ids(ps)[-1] == '10'
    assert not text(ps, '3.5.').endswith('admissibility and the merits')


def test_gc_sp_page_cleaning_is_unchanged():
    """GC/SP callers do not pass keep_body_in_margins and keep the old cut."""
    with fitz.open(FIX / 'CCPR_C_50_D_488_1992_E.pdf') as doc:
        page = doc[4]
        assert '5.1 During its forty-sixth session' not in clean_extract._clean_page_text(page)
        assert '5.1 During its forty-sixth session' in clean_extract._clean_page_text(page, keep_body_in_margins=True)


# --- Found while testing the redirect map on the local sources -------------------

def ocr_pages(doc_id):
    return [p.read_text() for p in sorted((FIX / f'ocr_{doc_id}').glob('page-*.txt'))]


def test_running_header_does_not_close_a_paragraph():
    # "CCPR/C/50/D/428/1990 / Annex / English / Page 4" at the top of a page.
    ps = ij._parse_pdf_text_pages(ocr_pages('ccpr-c-50-d-428-1990'))
    assert_continuous(main_ids(ps))
    assert text(ps, '5.2.').startswith('The Committee decides to base its Views on the following facts')


def test_appendix_opinion_is_kept():
    ps = ij._parse_pdf_text_pages(ocr_pages('ccpr-c-38-d-275-1988'))
    assert text(ps, '6.').endswith('to the author through her counsel.')
    appendix = [p for p in ps if p.get('Namespace')]
    assert appendix and appendix[0]['Text'].startswith("I concur in the views expressed in the Committee's decision")


def test_garbled_marker_after_heading_is_kept_and_named():
    # "10.% The Human Rights Committee has considered ..."
    ps = ij._parse_pdf_text_pages(ocr_pages('ccpr-c-55-d-519-1992'))
    assert_continuous(main_ids(ps))
    p10 = [p for p in ps if p['ID'] == '10.'][0]
    assert p10['Text'].startswith('The Human Rights Committee has considered the present communication')
    assert p10['IdCorrection'] == 'sequence_garbled_marker'


def test_ocr_page_number_does_not_hide_the_next_paragraph():
    # Page 8 ends "... legal aid system." then "~92-"; para. 14 opens page 9.
    ps = ij._parse_pdf_text_pages(ocr_pages('ccpr-c-39-d-250-1987'))
    assert text(ps, '14.').startswith('The Committee wouid wish to receive information')
    assert '~92-' not in text(ps, '12.2.')
