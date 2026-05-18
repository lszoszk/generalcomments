#!/usr/bin/env python3
"""Append-only merge of the 50 newly-ingested SR Health documents into the
existing docs/ build artifacts.

A full `build_corpus.py` rebuild is not possible: the source paragraph files
for the GC corpus and the 4 prior SP mandates are not present in this repo
(only the 50 freshly-ingested SR Health files in json_labeled_v2/ are). So we
process ONLY the new files and merge them into the existing corpus.json /
documents.json / facets.json, reusing build_corpus.py's own functions so the
emitted records are byte-identical in schema to a real build.
"""
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
    # 1. Process the 50 new SR Health files via build_corpus's own collector.
    sp_meta = load(SP_META)
    report: list[str] = []
    new_docs, new_paras = bc.collect_documents(SP_PARA_DIR, sp_meta, "sp", report)
    health_docs = [d for d in new_docs if d.get("committee") == "SR Health"]
    print(f"Collected {len(new_docs)} docs / {len(new_paras)} paragraphs "
          f"from {SP_PARA_DIR.name}/  ({len(health_docs)} are SR Health)")
    if len(new_docs) != 50:
        sys.exit(f"ERROR: expected 50 new docs, got {len(new_docs)}")

    # 2. Load existing artifacts.
    corpus = load(DOCS / "corpus.json")        # flat paragraph list
    documents = load(DOCS / "documents.json")  # doc records
    print(f"Existing: {len(documents)} docs / {len(corpus)} paragraphs")

    existing_doc_ids = {d["docId"] for d in documents}
    existing_para_ids = {p["id"] for p in corpus}

    # 3. Collision guard — new docIds / paraIds must not clash.
    clashes = [d["docId"] for d in new_docs if d["docId"] in existing_doc_ids]
    if clashes:
        sys.exit(f"ERROR: docId collision with existing corpus: {clashes}")
    pclashes = [p["id"] for p in new_paras if p["id"] in existing_para_ids]
    if pclashes:
        sys.exit(f"ERROR: paragraph id collision: {pclashes[:5]} ...")

    # 4. Merge.
    documents = documents + new_docs
    corpus = corpus + new_paras
    print(f"Merged:   {len(documents)} docs / {len(corpus)} paragraphs")

    # 5. Rebuild facets from the merged set.
    facets = bc.build_facets(documents, corpus)

    # 6. Write artifacts.
    bc.write_json(DOCS / "corpus.json", corpus)
    bc.write_json(DOCS / "documents.json", documents)
    bc.write_json(DOCS / "facets.json", facets)

    # 7. Refresh manifest.
    build_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    gc_docs = [d for d in documents if d["type"] == "gc"]
    sp_docs = [d for d in documents if d["type"] == "sp"]
    gc_paras = [p for p in corpus if p["type"] == "gc"]
    sp_paras = [p for p in corpus if p["type"] == "sp"]
    manifest = {
        "version": build_iso.split("T")[0].replace("-", ""),
        "builtAt": build_iso,
        "counts": {
            "documents": len(documents),
            "paragraphs": len(corpus),
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
            for fn in ("corpus.json", "documents.json", "facets.json")
        },
        "note": "Incremental append (append_sr_health.py): +50 SR Health docs.",
    }
    bc.write_json(DOCS / "manifest.json", manifest, pretty=True)

    print()
    print(f"Documents:  {len(documents):>6}  ({len(gc_docs)} GC + {len(sp_docs)} SP)")
    print(f"Paragraphs: {len(corpus):>6}  ({len(gc_paras)} GC + {len(sp_paras)} SP)")
    print(f"Committees: {len(facets['committees']):>6}")
    print(f"Years:      {facets['years']['min']} - {facets['years']['max']}")
    for fn in ("corpus.json", "documents.json", "facets.json", "manifest.json"):
        print(f"  {fn:<18} {(DOCS / fn).stat().st_size / 1024:>9.1f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
