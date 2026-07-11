#!/usr/bin/env python3
"""In-place, id-stable cleaner for two Special-Procedures reader artifacts.

The SP corpus was extracted with the old plain-text PyMuPDF path (not the
layout-aware clean_extract.py), so two classes of junk landed inside the
paragraph `text` field of docs/sp/shards/*.json and surfaced in the reader:

  1. Running page-footers glued mid-sentence — the document's OWN symbol next
     to its page marker and/or UN job number, e.g. "A/74/277 5/27 19-13343"
     or "A/63/313 08-46771". We target the doc's OWN signature (from
     documents.json) adjacent to a page (N/NN) and/or job number
     ((GE.)NN-NNNNN), so a citation to ANOTHER document (e.g. "CEDAW/C/GC/33",
     "A/HRC/5/1/Add.1") is never touched. Footnote-separator underscore runs
     (______) are dropped too.

  2. Collapsed bullet lists — "Definitions • item1 • item2 …" on one line —
     each bullet moved onto its own line with a "\\n• " prefix. The reader
     renders these via `white-space: pre-line` on .docs-reader-para-text.

id-stable: only the `text` string is rewritten. Paragraph id/idx/n, counts,
[[fn:N]] markers and every enrichment (section/footnotes/citedArticles/labels)
are preserved, so bookmarks, citations and section ranges stay valid.
Idempotent. Merged section headings / inline clause numbering (artifact class
#3) are NOT handled — the only signal (decimal "x.y") is indistinguishable from
flattened footnote reference numbers, so splitting mechanically corrupts more
than it fixes.

append_sp_docs.py imports clean_shards_inplace() to re-run this after every
merge; run standalone to (re)clean or audit:
    python3 clean_sp_reader_artifacts.py            # dry-run (audit)
    python3 clean_sp_reader_artifacts.py --apply    # write shards + refresh manifest
"""
from __future__ import annotations
import argparse, hashlib, json, re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent

JOBNUM = r'(?:GE\.)?\d{2}-\d{4,5}'
PAGE   = r'\d+/\d+'
UNDERSCORE_RE = re.compile(r'_{6,}')
BULLET_RE     = re.compile(r'\s*•\s*')


def _load_signatures(docs_dir: Path) -> dict:
    docs = json.load(open(docs_dir / "documents.json"))
    return {d["docId"]: (d.get("signature") or d.get("symbol") or "")
            for d in docs if d.get("type") == "sp"}


def _footer_re_for(sig: str):
    """Strip this doc's OWN running-footer only: the own symbol adjacent to a
    page marker and/or job number (never a bare symbol, so a legitimate in-text
    self-reference without page furniture survives)."""
    if not sig:
        return None
    S = re.escape(sig)
    return re.compile(
        r'(?:' + S + r'\s+(?:' + PAGE + r'\s+)?' + JOBNUM + r')'   # SYM [PAGE] JOB
        r'|(?:' + JOBNUM + r'\s+(?:' + PAGE + r'\s+)?' + S + r')'  # JOB [PAGE] SYM
        r'|(?:' + S + r'\s+' + PAGE + r'(?=\s|$))'                 # SYM PAGE
        r'|(?:' + PAGE + r'\s+' + S + r'(?=\s|$))'                 # PAGE SYM
    )


def clean_text(t: str, footer_re) -> tuple[str, list]:
    """Return (cleaned_text, removed_footer_runs). id-agnostic; pure string op."""
    removed = []
    t = UNDERSCORE_RE.sub(' ', t)
    if footer_re is not None:
        t = footer_re.sub(lambda m: (removed.append(m.group(0).strip()) or ' '), t)
    if '•' in t:
        t = BULLET_RE.sub('\n• ', t).lstrip('\n')
    t = re.sub(r'[ \t]{2,}', ' ', t)
    t = re.sub(r' *\n *', '\n', t).strip()
    return t, removed


def clean_shards_inplace(docs_dir: Path, apply: bool = True, verbose: bool = True) -> dict:
    """Clean every SP shard under docs_dir/sp/shards in place (or dry-run).
    Returns a summary dict. Refreshes docs_dir/sp/manifest.json sha/bytes when
    applying (paragraph/document counts are unchanged — text-only edit)."""
    shards_dir = docs_dir / "sp" / "shards"
    manifest_p = docs_dir / "sp" / "manifest.json"
    sigs = _load_signatures(docs_dir)
    footer_cache: dict = {}
    total = changed = footer_hits = bullet_hits = 0
    removed_counter: Counter = Counter()
    changed_shards: dict = {}

    for path in sorted(shards_dir.glob("sp_*.json")):
        data = json.load(open(path))
        nch = 0
        for p in data:
            total += 1
            old = p.get("text") or ""
            did = p.get("docId")
            if did not in footer_cache:
                footer_cache[did] = _footer_re_for(sigs.get(did, ""))
            new, removed = clean_text(old, footer_cache[did])
            if removed:
                footer_hits += len(removed)
                removed_counter.update(removed)
            if "•" in old:
                bullet_hits += 1
            if new != old:
                p["text"] = new
                nch += 1
                changed += 1
        if nch:
            changed_shards[path] = data

    summary = {"total": total, "changed": changed, "footer_runs": footer_hits,
               "distinct_footers": len(removed_counter), "bullet_paras": bullet_hits,
               "shards_touched": len(changed_shards)}

    if apply and changed_shards:
        for path, data in changed_shards.items():
            path.write_text(json.dumps(data, ensure_ascii=False))
        man = json.load(open(manifest_p))
        files = man.get("files", {})
        for path in sorted(shards_dir.glob("sp_*.json")):
            raw = path.read_bytes()
            arr = json.loads(raw)
            files[f"shards/{path.name}"] = {
                "sha": hashlib.sha256(raw).hexdigest()[:16], "bytes": len(raw),
                "documents": len({p.get("docId") for p in arr}), "paragraphs": len(arr)}
        man["files"] = files
        if "builtAt" in man:
            man["builtAt"] = datetime.now(timezone.utc).isoformat()
        manifest_p.write_text(json.dumps(man, ensure_ascii=False, indent=2))

    if verbose:
        tag = "cleaned" if (apply and changed_shards) else ("would clean" if changed_shards else "clean")
        print(f"  [sp-artifacts] {tag}: {changed} paras "
              f"({footer_hits} footer runs, {bullet_hits} bullet paras) in "
              f"{len(changed_shards)} shards" + ("" if apply else " (dry-run)"))
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write shards + refresh manifest (default: dry-run audit)")
    args = ap.parse_args()
    docs = REPO / "docs"
    summary = clean_shards_inplace(docs, apply=args.apply, verbose=False)
    print(f"{'APPLY' if args.apply else 'DRY-RUN'}: {summary['total']} paras | "
          f"{summary['changed']} changed | {summary['footer_runs']} footer-runs "
          f"({summary['distinct_footers']} distinct) | {summary['bullet_paras']} bullet paras "
          f"| {summary['shards_touched']} shards")
    if not args.apply:
        print("Re-run with --apply to write shards + refresh manifest.")


if __name__ == "__main__":
    main()
