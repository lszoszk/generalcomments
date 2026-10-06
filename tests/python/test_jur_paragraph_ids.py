"""Label-based paragraph ids and the old -> new redirect map."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import jur_paragraph_ids as pids  # noqa: E402

DOC = 'ccpr-c-50-d-488-1992'


def paras(*pairs):
    return [{'id': i, 'text': t} for i, t in pairs]


def test_label_ids():
    ids = pids.label_ids(DOC, ['1', '2.1', None, '2.1', 'OP1-U1', '8.2.', None])
    assert ids == [f'{DOC}:1', f'{DOC}:2.1', f'{DOC}:u1', f'{DOC}:2.1~2', f'{DOC}:OP1-U1', f'{DOC}:8.2', f'{DOC}:u2']
    assert pids.doc_id_of(f'{DOC}:2.1~2') == DOC
    assert pids.doc_id_of(f'{DOC}-0005') is None


def test_renamed_only_maps_by_position():
    old = paras((f'{DOC}-0001', 'The author is Mr. Toonen.'), (f'{DOC}-0002', 'He claims a violation.'))
    new = paras((f'{DOC}:1', 'The author is Mr. Toonen.'), (f'{DOC}:2.1', 'He claims a violation.'))
    assert pids.align(old, new) == ({f'{DOC}-0001': f'{DOC}:1', f'{DOC}-0002': f'{DOC}:2.1'}, [])


SESSION = 'December 1991 Date of decision on admissibility 5 November 1992 The Human Rights Committee meeting on 31 March 1994'
P81 = 'The Committee is called upon to determine whether Mr. Toonen has been the victim of an unlawful or arbitrary interference with his privacy contrary to article 17'
P82 = 'Inasmuch as article 17 is concerned it is undisputed that adult consensual sexual activity in private is covered by the concept of privacy'
P83 = 'The prohibition against private homosexual behaviour is provided for by law namely Sections 122 and 123 of the Tasmanian Criminal Code'


def test_recovered_paragraph_and_dropped_header_record():
    # Toonen: a session date published as "para. 25", and para. 8.2 missing.
    old = paras((f'{DOC}:25', SESSION), (f'{DOC}:8.1', P81), (f'{DOC}:8.3', P83))
    new = paras((f'{DOC}:8.1', P81), (f'{DOC}:8.2', P82), (f'{DOC}:8.3', P83))
    redirects, review = pids.align(old, new)
    assert redirects == {f'{DOC}:25': None}   # 8.1 and 8.3 keep their ids
    assert [r['reason'] for r in review] == ['removed']   # someone confirms the removal


def test_split_record_points_at_its_first_paragraph():
    # Coeriel: published 2.2 held 2.2-4.1.
    old = paras((f'{DOC}:2.2', ' '.join([P81, P82, P83])))
    new = paras((f'{DOC}:2.1', 'Something else entirely about the facts of the case and the author.'),
                (f'{DOC}:2.2', P81), (f'{DOC}:2.3', P82), (f'{DOC}:3', P83))
    redirects, review = pids.align(old, new)
    assert redirects == {}  # 2.2 still names the passage it starts with
    old = paras((f'{DOC}:G1', ' '.join([P81, P82, P83])))
    redirects, review = pids.align(old, new)
    assert redirects == {f'{DOC}:G1': f'{DOC}:2.2'} and review == []


def test_relabelled_paragraph_is_redirected():
    old = paras((f'{DOC}:OP1-26', P82))
    new = paras((f'{DOC}:OP1-U4', P81 + ' ' + P82))
    assert pids.align(old, new) == ({f'{DOC}:OP1-26': f'{DOC}:OP1-U4'}, [])


def test_lost_substantive_paragraph_goes_to_review():
    old = paras((f'{DOC}:8.1', P81), (f'{DOC}:8.2', P82), (f'{DOC}:8.3', P83))
    new = paras((f'{DOC}:8.1', P81), (f'{DOC}:8.3', P83))
    redirects, review = pids.align(old, new)
    assert redirects == {f'{DOC}:8.2': None}
    assert [r['oldId'] for r in review] == [f'{DOC}:8.2']


def test_extraction_failure_redirects_nothing():
    old = paras((f'{DOC}:8.1', P81), (f'{DOC}:8.2', P82), (f'{DOC}:8.3', P83))
    redirects, review = pids.align(old, paras((f'{DOC}:1', 'Annex English Page 1')))
    assert redirects == {}
    assert review[0]['reason'] == 'document_regression'


def test_merge_chains_and_revives():
    existing = {f'{DOC}-0001': f'{DOC}:G1', f'{DOC}-0002': f'{DOC}:25'}
    update = {f'{DOC}:G1': f'{DOC}:2.2', f'{DOC}:25': None}
    live = {f'{DOC}:2.2', f'{DOC}:8.2'}
    merged, dangling = pids.merge_redirects(existing, update, live, {DOC})
    assert merged == {f'{DOC}-0001': f'{DOC}:2.2', f'{DOC}-0002': None, f'{DOC}:G1': f'{DOC}:2.2', f'{DOC}:25': None}
    assert dangling == []
    # An id that becomes live again is no longer redirected.
    merged, _ = pids.merge_redirects(merged, {}, live | {f'{DOC}:25'}, {DOC})
    assert f'{DOC}:25' not in merged
    assert pids.legacy_index(merged)[f'{DOC}:2.2'] == [f'{DOC}-0001', f'{DOC}:G1']


def test_reviewed_decisions_override():
    assert pids.apply_decisions({'a': 'b', 'c': None}, {'c': 'd', 'x': 'y'}) == {'a': 'b', 'c': 'd'}
