#!/usr/bin/env python3
"""Split the Special Procedures paragraph corpus into per-committee shards.

The monolithic ``docs/sp-corpus.json`` outgrew GitHub's 100 MB single-file
limit as more thematic mandates were ingested. Mirroring the jurisprudence
layout (``docs/jur/shards/``), SP paragraphs now live in

    docs/sp/shards/sp_<Committee>.json   one flat JSON array per committee
    docs/sp/manifest.json                shard catalogue (sha, bytes, counts)

Each SP doc record in ``documents.json`` carries a ``shardId`` (e.g.
``sp_SR_Food``) so the document reader can lazy-load only the shard it needs
instead of the whole corpus. SP *search* still runs through the API; these
shards feed only the reader, exactly as the old sp-corpus.json did.

Run standalone for the one-time migration off sp-corpus.json:
    python3 build_sp_shards.py            # dry-run
    python3 build_sp_shards.py --apply    # write shards, stamp shardId, drop monolith

append_sp_docs.py imports write_sp_shards() to re-shard after each merge.
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import build_corpus as bc

REPO = Path(__file__).resolve().parent
DOCS = REPO / "docs"


def committee_to_shard_id(committee: str) -> str:
    """'SR Water and Sanitation' -> 'sp_SR_Water_and_Sanitation'."""
    return "sp_" + re.sub(r"[^0-9A-Za-z]+", "_", committee).strip("_")


def write_sp_shards(documents: list, sp_paras: list, docs_dir: Path) -> dict:
    """Rebuild every SP shard from scratch, stamp shardId on SP doc records,
    and write docs/sp/manifest.json. Mutates ``documents`` in place (adds
    shardId to each SP doc). Returns a summary dict.

    Always does a full rebuild from the supplied paragraphs, so renamed or
    removed committees never leave stale shard files behind.
    """
    shards_dir = docs_dir / "sp" / "shards"
    shards_dir.mkdir(parents=True, exist_ok=True)

    # doc_id -> committee, for the SP docs only.
    docid2com = {d["docId"]: d["committee"]
                 for d in documents if d.get("type") == "sp"}

    # Stamp shardId on every SP doc record.
    docs_per_shard: dict[str, int] = {}
    for d in documents:
        if d.get("type") == "sp":
            sid = committee_to_shard_id(d["committee"])
            d["shardId"] = sid
            docs_per_shard[sid] = docs_per_shard.get(sid, 0) + 1

    # Group paragraphs into shards by their doc's committee.
    shard_paras: dict[str, list] = {}
    orphans = []
    for p in sp_paras:
        com = docid2com.get(p["docId"])
        if com is None:
            orphans.append(p["docId"])
            continue
        sid = committee_to_shard_id(com)
        shard_paras.setdefault(sid, []).append(p)
    if orphans:
        raise SystemExit(
            f"ERROR: {len(orphans)} SP paragraphs reference docIds absent from "
            f"documents.json, e.g. {sorted(set(orphans))[:5]}")

    # Clean slate: drop any pre-existing sp_*.json so removed committees don't
    # leave orphan shards, then write the fresh set.
    for stale in shards_dir.glob("sp_*.json"):
        stale.unlink()
    files = {}
    for sid in sorted(shard_paras):
        path = shards_dir / f"{sid}.json"
        bc.write_json(path, shard_paras[sid])               # compact flat array
        files[f"shards/{sid}.json"] = {
            "sha": bc.sha256_file(path),
            "bytes": path.stat().st_size,
            "documents": docs_per_shard.get(sid, 0),
            "paragraphs": len(shard_paras[sid]),
        }

    build_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    manifest = {
        "version": build_iso.split("T")[0].replace("-", ""),
        "builtAt": build_iso,
        "counts": {
            "documents": sum(docs_per_shard.values()),
            "paragraphs": len(sp_paras),
            "shards": len(shard_paras),
            "committees": len(shard_paras),
        },
        "files": files,
        "note": "Per-committee SP paragraph shards (build_sp_shards.py).",
    }
    bc.write_json(docs_dir / "sp" / "manifest.json", manifest, pretty=True)
    return {"shards": len(shard_paras), "paragraphs": len(sp_paras),
            "documents": sum(docs_per_shard.values())}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true",
                    help="Write shards, stamp shardId, and remove sp-corpus.json.")
    args = ap.parse_args()

    documents = json.loads((DOCS / "documents.json").read_text(encoding="utf-8"))
    monolith = DOCS / "sp-corpus.json"
    if not monolith.exists():
        sys.exit("sp-corpus.json not found — nothing to migrate.")
    sp_paras = json.loads(monolith.read_text(encoding="utf-8"))

    n_sp_docs = sum(1 for d in documents if d.get("type") == "sp")
    print(f"SP docs in documents.json: {n_sp_docs}")
    print(f"SP paragraphs in sp-corpus.json: {len(sp_paras)}")
    coms = sorted({d["committee"] for d in documents if d.get("type") == "sp"})
    print(f"committees -> shards: {len(coms)}")
    for c in coms:
        print(f"  {c}  ->  {committee_to_shard_id(c)}")

    if not args.apply:
        print("\nDry-run — re-run with --apply to write shards + drop the monolith.")
        return 0

    summary = write_sp_shards(documents, sp_paras, DOCS)
    # documents.json uses the committed convention: single-line, DEFAULT
    # (spaced) separators — NOT bc.write_json's compact form.
    (DOCS / "documents.json").write_text(
        json.dumps(documents, ensure_ascii=False), encoding="utf-8")
    monolith.unlink()
    print(f"\n✅ wrote {summary['shards']} shards / {summary['paragraphs']} paragraphs "
          f"to docs/sp/shards/, stamped shardId on {summary['documents']} SP docs, "
          f"removed sp-corpus.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
