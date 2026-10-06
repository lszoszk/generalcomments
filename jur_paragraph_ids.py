"""Label-based jurisprudence paragraph ids and the old -> new redirect map.

Paragraph ids used to be positional, ``{docId}-{idx:04d}``, so recovering
one missing paragraph renumbered every paragraph after it and broke saved
citations. They are now built from the printed label:

    ccpr-c-50-d-488-1992:8.2       paragraph 8.2
    ccpr-c-50-d-488-1992:OP1-U3    third unnumbered paragraph of opinion 1
    ccpr-c-134-d-2841-2016:2.1~2   second paragraph labelled 2.1
    cat-c-14-d-6-1990:u7           seventh record without a label

The colon never occurs in a docId or a label, so everything before the first
colon is the docId. GC and SP ids are unchanged.

When a rebuild changes a document's paragraphs, ``align`` matches the
previous build's paragraphs to the new ones by text, and ``merge_redirects``
folds the result into the cumulative map (docs/jur/paragraph-redirects.json):
every id ever published resolves in one hop to a live id, or to None when
the old record was not a paragraph of the decision (a session date read as
"para. 25", say). Matches the text cannot settle go to a review queue;
reviewed decisions come back through ``apply_decisions``.
"""
from __future__ import annotations

import re
from collections import Counter
from difflib import SequenceMatcher

SEP = ':'

# A passage counts as found in a new paragraph when this share of its words
# appears there in order.
CONTAINED = 0.8
# Below this nothing in the new build resembles the old paragraph.
RESEMBLES = 0.5
# Old records shorter than this (in words) that vanish are scraps (a stray
# page header); any longer removal is reviewed.
SUBSTANTIVE_WORDS = 12
# Words at the start of an old paragraph that identify where it began.
LEAD_WORDS = 8
# A rebuilt document that keeps less than this share of its old words lost
# text in extraction; its ids are left alone and the document is reported.
KEPT_WORDS = 0.6


def label_ids(doc_id: str, labels: list[str | None]) -> list[str]:
    """Paragraph ids for one document, in order, from the printed labels."""
    seen: Counter = Counter()
    unlabelled = 0
    out = []
    for raw in labels:
        label = re.sub(r'\s+', '', str(raw or '')).replace(SEP, '-').rstrip('.')
        if not label:
            unlabelled += 1
            label = f'u{unlabelled}'
        seen[label] += 1
        if seen[label] > 1:
            label = f'{label}~{seen[label]}'
        out.append(f'{doc_id}{SEP}{label}')
    return out


def doc_id_of(para_id: str) -> str | None:
    """The docId of a label-based id; None for a positional one."""
    return para_id.split(SEP, 1)[0] if SEP in para_id else None


def _tokens(text: str) -> list[str]:
    text = re.sub(r'\[\[fn:[^\]]*\]\]', ' ', text or '')
    return re.sub(r'[^0-9a-z]+', ' ', text.lower()).split()


def _overlap(a: list[str], b: list[str]) -> tuple[int, bool]:
    """Words of a found in b in order, and whether b holds a's opening words."""
    sm = SequenceMatcher(None, a, b, autojunk=False)
    blocks = sm.get_matching_blocks()
    matched = sum(bl.size for bl in blocks)
    lead = min(LEAD_WORDS, len(a))
    starts = any(bl.a == 0 and bl.size >= lead for bl in blocks) if lead else False
    return matched, starts


def align(old: list[dict], new: list[dict]) -> tuple[dict[str, str | None], list[dict]]:
    """Match one document's previous paragraphs to its new ones.

    ``old`` and ``new`` are lists of {id, text}. Returns ({old id: new id or
    None} for every old id that is not itself a live id of the same
    passage, [review items]). A review item holds the old paragraph, the
    provisional answer and the candidates with their scores. When the new
    build lost much of the document's text, nothing is redirected and the
    one review item says so: that is an extraction failure, not a removal.
    """
    new_ids = {p['id'] for p in new}
    old_tok = [_tokens(p['text']) for p in old]
    new_tok = [_tokens(p['text']) for p in new]

    # Same paragraphs in the same order: only the ids changed (the move from
    # positional to label ids, or a relabelling).
    if old_tok == new_tok:
        return {o['id']: n['id'] for o, n in zip(old, new) if o['id'] != n['id']}, []

    old_words = [w for t in old_tok for w in t]
    new_words = set(w for t in new_tok for w in t)
    if old_words and sum(w in new_words for w in old_words) / len(old_words) < KEPT_WORDS:
        return {}, [{
            'oldId': None,
            'reason': 'document_regression',
            'detail': f'{len(old)} old paragraphs, {len(new)} new; most of the old text is missing',
        }]

    by_id = {p['id']: i for i, p in enumerate(new)}
    new_sets = [set(t) for t in new_tok]
    redirects: dict[str, str | None] = {}
    review: list[dict] = []
    for o, ot in zip(old, old_tok):
        j = by_id.get(o['id'])
        if j is not None and ot and new_tok[j]:
            matched, starts = _overlap(ot, new_tok[j])
            if matched / len(ot) >= RESEMBLES or (starts and matched / len(new_tok[j]) >= CONTAINED):
                # The id still names the same passage, or the passage the old
                # record began with when it was several run together.
                continue
        if not ot:
            redirects[o['id']] = None
            continue
        oset = set(ot)
        # Relative overlap, so a short paragraph split off the old one ranks too.
        shortlist = sorted(range(len(new)), key=lambda k: -max(
            len(oset & new_sets[k]) / len(oset), len(oset & new_sets[k]) / max(1, len(new_sets[k]))))[:6]
        cands = []
        for k in shortlist:
            if not new_tok[k]:
                continue
            matched, starts = _overlap(ot, new_tok[k])
            cands.append({
                'id': new[k]['id'],
                'containsOld': round(matched / len(ot), 3),   # the old passage is inside it
                'insideOld': round(matched / len(new_tok[k]), 3),  # it is a piece of the old passage
                'startsOld': starts,
            })
        merged = [c for c in cands if c['containsOld'] >= CONTAINED]
        split = [c for c in cands if c['insideOld'] >= CONTAINED and c['startsOld']]
        if merged:
            merged.sort(key=lambda c: (-c['containsOld'], -c['insideOld']))
            best = merged[0]
            # Two new paragraphs that both hold the passage (repeated boilerplate).
            confident = len(merged) == 1 or merged[1]['containsOld'] < best['containsOld'] - 0.1
            reason = 'contained'
        elif split:
            # The old record was several paragraphs run together; it began with this one.
            best, confident, reason = split[0], len(split) == 1, 'split'
        else:
            scored = sorted(cands, key=lambda c: -max(c['containsOld'], c['insideOld']))
            best = scored[0] if scored and max(scored[0]['containsOld'], scored[0]['insideOld']) >= RESEMBLES else None
            confident = best is None and len(ot) < SUBSTANTIVE_WORDS
            reason = 'resembles' if best else 'removed'
        target = best['id'] if best else None
        redirects[o['id']] = target
        if not confident:
            review.append({
                'oldId': o['id'],
                'oldText': o['text'][:600],
                'provisional': target,
                'reason': reason,
                'candidates': sorted(cands, key=lambda c: -max(c['containsOld'], c['insideOld']))[:4],
            })
    return redirects, review


def apply_decisions(redirects: dict, decisions: dict) -> dict:
    """Overlay reviewed answers ({old id: new id or None}) on provisional ones."""
    out = dict(redirects)
    for old_id, target in decisions.items():
        if old_id in out:
            out[old_id] = target
    return out


def merge_redirects(existing: dict, update: dict, live_ids: set[str], built_docs: set[str]) -> tuple[dict, list[str]]:
    """Fold this build's redirects into the cumulative map.

    Every target is chased to a live id (a -> b, b -> c gives a -> c). An id
    that is live again stops being redirected. Targets inside the rebuilt
    documents that are neither live nor redirected are reported (dangling).
    """
    merged = {**existing, **update}
    out, dangling = {}, []
    for old_id in merged:
        if old_id in live_ids:
            continue
        target, hops = merged[old_id], 0
        while target is not None and target not in live_ids and target in merged and hops < 50:
            target, hops = merged[target], hops + 1
        if target is not None and target not in live_ids and _doc(target) in built_docs:
            dangling.append(old_id)
        out[old_id] = target
    return out, dangling


def _doc(para_id: str) -> str:
    return doc_id_of(para_id) or re.sub(r'-\d{4}$', '', para_id)


def legacy_index(redirects: dict) -> dict[str, list[str]]:
    """{live id: [old ids that resolve to it]} for the shards' legacyIds."""
    index: dict[str, list[str]] = {}
    for old_id, target in redirects.items():
        if target is not None:
            index.setdefault(target, []).append(old_id)
    for ids in index.values():
        ids.sort()
    return index
