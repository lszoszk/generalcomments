#!/usr/bin/env python3
"""Append-only merge of newly-ingested Special Procedures documents into the
existing docs/ build artifacts.

A full `build_corpus.py` rebuild is not possible: the source paragraph files
for the GC corpus and the older SP mandates are not present in this repo
(only the freshly-ingested SP files in json_labeled_v2/ are). So we process
the json_labeled_v2/ files, keep only the ones whose docId is NOT already in
docs/documents.json, and merge those into corpus.json / documents.json /
facets.json — reusing build_corpus.py's own functions so the emitted records
are byte-identical in schema to a real build.

Idempotent: re-running after a merge is a no-op (every docId already present).

Usage:
    python3 append_sp_docs.py            # dry-run (reports what would merge)
    python3 append_sp_docs.py --apply    # write the artifacts
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import build_corpus as bc

REPO = Path(__file__).resolve().parent
DOCS = REPO / "docs"
SP_META = REPO / "mysite_pythonanywhere" / "specialprocedures_info.json"
SP_PARA_DIR = REPO / "json_labeled_v2"


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true",
                    help="Write the merged artifacts back to docs/.")
    args = ap.parse_args()

    # 1. Process every file in json_labeled_v2/ via build_corpus's collector.
    sp_meta = load(SP_META)
    report: list[str] = []
    all_docs, all_paras = bc.collect_documents(SP_PARA_DIR, sp_meta, "sp", report)

    # 2. Load existing artifacts. v19.60: SP paragraphs live in their
    #    own sp-corpus.json (split out of corpus.json — corpus.json is
    #    GC-only now). New SP docs append there; GC corpus is untouched.
    gc_corpus = load(DOCS / "corpus.json")     # GC paragraphs only
    sp_corpus = load(DOCS / "sp-corpus.json")  # SP paragraphs
    documents = load(DOCS / "documents.json")  # doc records (GC+SP+JUR)
    existing_doc_ids = {d["docId"] for d in documents}

    # 3. Keep only docs not already merged.
    new_docs = [d for d in all_docs if d["docId"] not in existing_doc_ids]
    new_doc_ids = {d["docId"] for d in new_docs}
    new_paras = [p for p in all_paras if p["docId"] in new_doc_ids]

    from collections import Counter
    by_committee = Counter(d.get("committee", "?") for d in new_docs)
    print(f"json_labeled_v2/: {len(all_docs)} docs total")
    print(f"already merged:   {len(all_docs) - len(new_docs)} docs")
    print(f"NEW to merge:     {len(new_docs)} docs / {len(new_paras)} paragraphs")
    for com, n in by_committee.most_common():
        print(f"  {com}: {n}")
    if not new_docs:
        print("\nNothing to merge — corpus is already up to date.")
        return 0

    # 4. Collision guard on paragraph ids.
    existing_para_ids = {p["id"] for p in gc_corpus} | {p["id"] for p in sp_corpus}
    pclashes = [p["id"] for p in new_paras if p["id"] in existing_para_ids]
    if pclashes:
        sys.exit(f"ERROR: paragraph id collision: {pclashes[:5]} …")

    if not args.apply:
        print("\nDry-run — re-run with --apply to write docs/.")
        return 0

    # 5. Merge SP into sp-corpus.json; rebuild facets over GC + SP.
    documents = documents + new_docs
    sp_corpus = sp_corpus + new_paras
    facets = bc.build_facets(documents, gc_corpus + sp_corpus)
    bc.write_json(DOCS / "sp-corpus.json", sp_corpus)
    bc.write_json(DOCS / "documents.json", documents)
    bc.write_json(DOCS / "facets.json", facets)

    # 6. Refresh manifest.
    build_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    gc_docs = [d for d in documents if d["type"] == "gc"]
    sp_docs = [d for d in documents if d["type"] == "sp"]
    gc_paras = gc_corpus
    sp_paras = sp_corpus
    manifest = {
        "version": build_iso.split("T")[0].replace("-", ""),
        "builtAt": build_iso,
        "counts": {
            "documents": len(documents),
            "paragraphs": len(gc_paras) + len(sp_paras),
            "gcDocuments": len(gc_docs),
            "gcParagraphs": len(gc_paras),
            "spDocuments": len(sp_docs),
            "spParagraphs": len(sp_paras),
            "labels": len(facets["labels"]),
            "committees": len(facets["committees"]),
            "yearRange": [facets["years"]["min"], facets["years"]["max"]],
        },
        "files": {
            fn: {
                "sha": bc.sha256_file(DOCS / fn),
                "bytes": (DOCS / fn).stat().st_size,
            }
            for fn in ("corpus.json", "sp-corpus.json", "documents.json", "facets.json")
        },
        "note": f"Incremental append (append_sp_docs.py): +{len(new_docs)} SP docs.",
    }
    bc.write_json(DOCS / "manifest.json", manifest, pretty=True)

    print()
    print(f"Documents:  {len(documents):>6}  ({len(gc_docs)} GC + {len(sp_docs)} SP)")
    print(f"Paragraphs: {len(gc_paras) + len(sp_paras):>6}  ({len(gc_paras)} GC + {len(sp_paras)} SP)")
    print(f"Committees: {len(facets['committees']):>6}")
    print(f"  ✅ wrote sp-corpus.json / documents.json / facets.json / manifest.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
