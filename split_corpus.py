#!/usr/bin/env python3
"""One-time split of docs/corpus.json into a GC-only corpus + a separate
Special Procedures corpus.

WHY
---
corpus.json is downloaded, parsed AND indexed (FlexSearch) at every cold
boot. As SP mandates were ingested it grew 25 → 48 MB and the cold-boot
index build hit ~7 s. SP search is now served by the API (which holds
the whole GC+SP+JUR corpus), so the SP paragraphs no longer need to ship
in the eagerly-indexed corpus.json.

After this split:
  docs/corpus.json      GC paragraphs only  (~6 MB) — eager load + index
  docs/sp-corpus.json   SP paragraphs       (~40 MB) — lazy, reader-only,
                        NOT indexed (SP search routes through the API)
  docs/documents.json   unchanged — all GC + SP + JUR doc metadata
  docs/facets.json      recomputed over GC + SP (the catalogue rail
                        still shows SP committee counts)

Idempotent: if corpus.json already holds only GC paragraphs the SP side
is rebuilt from sp-corpus.json so the script can be re-run safely.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import build_corpus as bc

REPO = Path(__file__).resolve().parent
DOCS = REPO / "docs"


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def main():
    corpus = load(DOCS / "corpus.json")
    sp_existing = []
    sp_path = DOCS / "sp-corpus.json"
    if sp_path.exists():
        sp_existing = load(sp_path)

    # Partition by type. Any SP paragraphs still in corpus.json move out;
    # merge with whatever sp-corpus.json already holds (dedup on id).
    gc = [p for p in corpus if p.get("type") == "gc"]
    sp_from_corpus = [p for p in corpus if p.get("type") == "sp"]
    by_id = {p["id"]: p for p in sp_existing}
    for p in sp_from_corpus:
        by_id[p["id"]] = p
    sp = list(by_id.values())

    documents = load(DOCS / "documents.json")
    print(f"corpus.json in:   {len(corpus)} paragraphs")
    print(f"  → GC corpus.json:   {len(gc)} paragraphs")
    print(f"  → sp-corpus.json:   {len(sp)} paragraphs")

    bc.write_json(DOCS / "corpus.json", gc)
    bc.write_json(DOCS / "sp-corpus.json", sp)

    # Facets are computed over the whole catalogue (GC + SP) so the
    # documents-tab rail keeps its SP committee counts.
    facets = bc.build_facets(documents, gc + sp)
    bc.write_json(DOCS / "facets.json", facets)

    # Manifest: corpus.json (GC) is the index-cache key; sp-corpus.json
    # is tracked so the lazy loader can cache-bust on change.
    build_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    gc_docs = [d for d in documents if d["type"] == "gc"]
    sp_docs = [d for d in documents if d["type"] == "sp"]
    manifest = {
        "version": build_iso.split("T")[0].replace("-", ""),
        "builtAt": build_iso,
        "counts": {
            "documents": len(documents),
            "paragraphs": len(gc) + len(sp),
            "gcDocuments": len(gc_docs),
            "gcParagraphs": len(gc),
            "spDocuments": len(sp_docs),
            "spParagraphs": len(sp),
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
        "note": "corpus.json split: GC indexed locally, SP served by the API.",
    }
    bc.write_json(DOCS / "manifest.json", manifest, pretty=True)

    print()
    print(f"corpus.json     {(DOCS/'corpus.json').stat().st_size/1024/1024:>6.1f} MB  ({len(gc)} ¶)")
    print(f"sp-corpus.json  {(DOCS/'sp-corpus.json').stat().st_size/1024/1024:>6.1f} MB  ({len(sp)} ¶)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
