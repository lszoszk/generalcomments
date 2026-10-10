#!/usr/bin/env python3
"""Ask Jev (TypeSafe) to settle the paragraph redirects the text alignment could not.

Input is the review queue build_jurisprudence_shards.py writes (--review-out):
old paragraphs whose new home is uncertain, each with up to four candidate
new paragraphs. Jev picks one candidate or "none" and returns a calibrated
probability. Picks at p >= --accept go into the decisions file, which the
next build reads with --decisions; the rest stay for a person, with Jev's
pick as a suggestion. Every answer is logged with its probabilities.

Documents whose rebuild lost most of their text (reason document_regression)
are not asked: that is an extraction failure to fix, not a match to make.

Sends the paragraph text (public UN decisions) to api.typesafe.ai. Uses the
Jev client and key of the travaux project (pipeline/jev.py, travaux/.env).

    python3 scripts/jev_redirect_review.py --review jur_paragraph_redirect_review.json \\
        --decisions jur_paragraph_redirect_decisions.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ACCEPT = 0.9  # as the travaux pipeline accepts Jev's speaker picks
BATCH = 8
LETTERS = 'ABCD'

INSTRUCTIONS = (
    "Consider only item {key} in the state. A citation points at the old paragraph of a UN treaty-body "
    "decision. The decision was extracted again from its source, so paragraphs may now be renumbered, "
    "split, merged or dropped, and the old text may carry OCR noise, a heading glued to its end, endnotes, "
    "or front matter (session dates, lists of articles). Which new paragraph holds the passage the old "
    "paragraph begins with, i.e. where a reader following the citation should land? Answer 'none' if the "
    "old paragraph was front matter, an endnote or page debris, or if its passage is in none of them."
)


def load_jev(client_dir: Path):
    sys.path.insert(0, str(client_dir))
    import jev  # noqa: E402  (travaux/pipeline/jev.py)
    return jev


def item_state(item: dict) -> dict:
    return {
        'document': item['docId'],
        'old_paragraph': {'id': item['oldId'].split(':', 1)[-1], 'text': item['oldText']},
        'new_paragraphs': {LETTERS[i]: {'id': c['id'].split(':', 1)[-1], 'text': c.get('text', '')}
                           for i, c in enumerate(item['candidates'][:len(LETTERS)])},
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--review', type=Path, required=True)
    ap.add_argument('--decisions', type=Path, required=True, help='Write {oldId: newId or null} here')
    ap.add_argument('--log', type=Path, help='Every answer with probabilities (default: DECISIONS.log.json)')
    ap.add_argument('--accept', type=float, default=ACCEPT)
    ap.add_argument('--jev-client', type=Path, default=Path('/Users/lszoszk/Desktop/AI/travaux/pipeline'))
    ap.add_argument('--limit', type=int)
    ap.add_argument('--dry-run', action='store_true', help='Print the first request and stop')
    args = ap.parse_args()

    items = [r for r in json.loads(args.review.read_text())
             if r.get('reason') != 'document_regression' and r.get('candidates')]
    if args.limit:
        items = items[:args.limit]
    jev = load_jev(args.jev_client)

    decisions = json.loads(args.decisions.read_text()) if args.decisions.exists() else {}
    log = []
    for start in range(0, len(items), BATCH):
        chunk = items[start:start + BATCH]
        keys = [f'I{start + j}' for j in range(len(chunk))]
        state = {'items': {k: item_state(it) for k, it in zip(keys, chunk)}}
        questions = {}
        for k, it in zip(keys, chunk):
            options = {LETTERS[i]: f"new paragraph {LETTERS[i]} of item {k}"
                       for i in range(min(len(it['candidates']), len(LETTERS)))}
            options['none'] = 'none of them: the old passage is not in the new build'
            questions[k] = jev.choice(INSTRUCTIONS.format(key=k), options)
        if args.dry_run:
            print(json.dumps({'state': state, 'questions': questions}, ensure_ascii=False, indent=1)[:4000])
            return 0
        answers = jev.ask(state, questions, task='unhrdb_redirect_review')
        for k, it in zip(keys, chunk):
            a = answers.get(k) or {}
            pick = a.get('choice')
            probs = a.get('probabilities') or {}
            p = probs.get(pick) or 0.0
            target = None if pick == 'none' else (
                it['candidates'][LETTERS.index(pick)]['id'] if pick in LETTERS[:len(it['candidates'])] else '?')
            accepted = target != '?' and p >= args.accept
            if accepted:
                decisions[it['oldId']] = target
            log.append({'oldId': it['oldId'], 'provisional': it['provisional'], 'reason': it['reason'],
                        'jev': target, 'p': round(p, 3), 'probabilities': probs, 'accepted': accepted})
        print(f'{min(start + BATCH, len(items))}/{len(items)} asked', file=sys.stderr)

    args.decisions.write_text(json.dumps(decisions, ensure_ascii=False, indent=1))
    log_path = args.log or args.decisions.with_suffix('.log.json')
    log_path.write_text(json.dumps(log, ensure_ascii=False, indent=1))
    accepted = [x for x in log if x['accepted']]
    print(f'{len(log)} asked; {len(accepted)} accepted at p >= {args.accept} '
          f'({sum(x["jev"] != x["provisional"] for x in accepted)} differ from the provisional match); '
          f'{len(log) - len(accepted)} left for review -> {log_path}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
