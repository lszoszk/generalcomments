#!/usr/bin/env python3
"""Build the v2 Hugging Face dataset from the curated docs/corpus.json.

Reads the live UNHRD corpus (the same data the dashboard serves), filters
to GC paragraphs only, and writes parquet files compatible with the
huggingface/datasets loader.

Output layout (matches the existing HF dataset structure):

    out/
      data/train-00000-of-00001.parquet   # one row per paragraph
      document_index.parquet              # one row per document
      dataset_metadata.json               # build summary

Run:

    python3 build_hf_dataset.py \\
        --corpus ../docs/corpus.json \\
        --documents ../docs/documents.json \\
        --out ../docs_v2/hf

v2 (vs. the old HF package) adds: footnotes (with cross-reference
annotations), section path, isPreamble flag, footnotesVerified +
footnotesSource provenance, alternativeIds for joint-comment URLs.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


# Footnote sub-schema — every paragraph carries 0..N footnotes; each fn
# is a small struct.  The cross-reference annotation fields (isIbid,
# isCrossRef, isSelfRef, resolvedText, referencesNote, referencesPara)
# are present only on the ~285 fns where the resolver could trace them.
FOOTNOTE_TYPE = pa.struct([
    pa.field("n", pa.int32()),
    pa.field("text", pa.string()),
    pa.field("is_ibid", pa.bool_()),
    pa.field("is_cross_ref", pa.bool_()),
    pa.field("is_self_ref", pa.bool_()),
    pa.field("references_note", pa.int32()),
    pa.field("references_para", pa.int32()),
    pa.field("resolved_text", pa.string()),
])

PARQUET_SCHEMA = pa.schema([
    # Identity
    pa.field("row_id", pa.string()),
    pa.field("paragraph_id", pa.string()),       # corpus id (e.g. "crc-c-gc-25-0042")
    pa.field("document_id", pa.string()),
    pa.field("source_file", pa.string()),

    # Document metadata (denormalised onto every row for analytics use)
    pa.field("document_title", pa.string()),
    pa.field("document_title_short", pa.string()),
    pa.field("signature", pa.string()),
    pa.field("ohchr_symbol", pa.string()),
    pa.field("source_url", pa.string()),
    pa.field("adoption_date", pa.string()),
    pa.field("adoption_year", pa.int32()),
    pa.field("committee", pa.string()),
    pa.field("committees", pa.list_(pa.string())),
    pa.field("is_joint_document", pa.bool_()),
    pa.field("alternative_ids", pa.list_(pa.string())),
    pa.field("articles", pa.list_(pa.string())),
    pa.field("languages_available", pa.list_(pa.string())),
    pa.field("status", pa.string()),
    pa.field("first_added_at", pa.string()),
    pa.field("last_verified_at", pa.string()),
    pa.field("footnotes_verified", pa.bool_()),
    pa.field("footnotes_source", pa.string()),

    # Paragraph fields
    pa.field("segment_position", pa.int32()),
    pa.field("paragraph_number", pa.int32()),
    pa.field("text", pa.string()),
    pa.field("text_length_chars", pa.int32()),
    pa.field("text_length_words", pa.int32()),
    pa.field("labels", pa.list_(pa.string())),
    pa.field("label_count", pa.int32()),
    pa.field("has_labels", pa.bool_()),

    # v2 enrichment
    pa.field("section", pa.list_(pa.string())),
    pa.field("is_preamble", pa.bool_()),
    pa.field("preamble_source", pa.string()),
    pa.field("footnotes", pa.list_(FOOTNOTE_TYPE)),
    pa.field("footnote_count", pa.int32()),
])

DOC_INDEX_SCHEMA = pa.schema([
    pa.field("document_id", pa.string()),
    pa.field("document_title", pa.string()),
    pa.field("document_title_short", pa.string()),
    pa.field("signature", pa.string()),
    pa.field("ohchr_symbol", pa.string()),
    pa.field("source_url", pa.string()),
    pa.field("adoption_date", pa.string()),
    pa.field("adoption_year", pa.int32()),
    pa.field("committee", pa.string()),
    pa.field("committees", pa.list_(pa.string())),
    pa.field("is_joint_document", pa.bool_()),
    pa.field("articles", pa.list_(pa.string())),
    pa.field("languages_available", pa.list_(pa.string())),
    pa.field("status", pa.string()),
    pa.field("first_added_at", pa.string()),
    pa.field("last_verified_at", pa.string()),
    pa.field("paragraph_count", pa.int32()),
    pa.field("preamble_count", pa.int32()),
    pa.field("footnote_count", pa.int32()),
    pa.field("footnotes_verified", pa.bool_()),
    pa.field("footnotes_source", pa.string()),
    pa.field("word_count", pa.int32()),
    pa.field("label_count", pa.int32()),
    pa.field("alternative_ids", pa.list_(pa.string())),
    pa.field("abstract", pa.string()),
])


def _norm_fn(fn):
    """Normalise a footnote entry to the parquet struct shape."""
    return {
        "n": int(fn.get("n", 0)) if fn.get("n") is not None else None,
        "text": fn.get("text") or "",
        "is_ibid": bool(fn.get("isIbid", False)),
        "is_cross_ref": bool(fn.get("isCrossRef", False)),
        "is_self_ref": bool(fn.get("isSelfRef", False)),
        "references_note": int(fn["referencesNote"]) if fn.get("referencesNote") is not None else None,
        "references_para": int(fn["referencesPara"]) if fn.get("referencesPara") is not None else None,
        "resolved_text": fn.get("resolvedText") or "",
    }


def _para_row(p, doc):
    """Map one corpus paragraph + its document onto the parquet schema."""
    section = p.get("section")
    if isinstance(section, str):
        section = [section]
    elif not isinstance(section, list):
        section = []

    fns = p.get("footnotes") or []
    fn_rows = [_norm_fn(f) for f in fns]

    text = p.get("text") or ""
    return {
        "row_id": f"{p.get('docId','')}::{p.get('idx', p.get('n', 0))}",
        "paragraph_id": p.get("id"),
        "document_id": p.get("docId"),
        "source_file": doc.get("sourceFile") if doc else None,

        "document_title": (doc.get("name") if doc else None),
        "document_title_short": (doc.get("nameShort") if doc else None),
        "signature": (doc.get("signature") if doc else None),
        "ohchr_symbol": (doc.get("ohchrSymbol") if doc else None),
        "source_url": (doc.get("link") if doc else None),
        "adoption_date": (doc.get("adoptionDate") if doc else None),
        "adoption_year": (int(doc["year"]) if doc and doc.get("year") is not None else None),
        "committee": p.get("committee"),
        "committees": p.get("committees") or [],
        "is_joint_document": bool(len(p.get("committees") or []) > 1),
        "alternative_ids": (doc.get("alternativeIds") if doc else None) or [],
        "articles": (doc.get("articles") if doc else None) or [],
        "languages_available": (doc.get("languagesAvailable") if doc else None) or [],
        "status": (doc.get("status") if doc else None),
        "first_added_at": (doc.get("firstAddedAt") if doc else None),
        "last_verified_at": (doc.get("lastVerifiedAt") if doc else None),
        "footnotes_verified": bool(doc.get("footnotesVerified")) if doc else False,
        "footnotes_source": (doc.get("footnotesSource") if doc else None),

        "segment_position": int(p.get("idx", p.get("n", 0))),
        "paragraph_number": int(p.get("n", 0)) if p.get("n") is not None else None,
        "text": text,
        "text_length_chars": len(text),
        "text_length_words": len(text.split()),
        "labels": p.get("labels") or [],
        "label_count": len(p.get("labels") or []),
        "has_labels": bool(p.get("labels")),

        "section": section,
        "is_preamble": bool(p.get("isPreamble")),
        "preamble_source": p.get("preambleSource"),
        "footnotes": fn_rows,
        "footnote_count": len(fn_rows),
    }


def _doc_index_row(doc, paras_for_doc):
    """One row per document — denormalised counts + metadata."""
    pre = sum(1 for p in paras_for_doc if p.get("isPreamble"))
    fn_count = sum(len(p.get("footnotes") or []) for p in paras_for_doc)

    return {
        "document_id": doc.get("docId"),
        "document_title": doc.get("name"),
        "document_title_short": doc.get("nameShort"),
        "signature": doc.get("signature"),
        "ohchr_symbol": doc.get("ohchrSymbol"),
        "source_url": doc.get("link"),
        "adoption_date": doc.get("adoptionDate"),
        "adoption_year": int(doc["year"]) if doc.get("year") is not None else None,
        "committee": doc.get("committee"),
        "committees": doc.get("committees") or [],
        "is_joint_document": bool(len(doc.get("committees") or []) > 1),
        "articles": doc.get("articles") or [],
        "languages_available": doc.get("languagesAvailable") or [],
        "status": doc.get("status"),
        "first_added_at": doc.get("firstAddedAt"),
        "last_verified_at": doc.get("lastVerifiedAt"),
        "paragraph_count": int(doc.get("paragraphCount") or len(paras_for_doc)),
        "preamble_count": pre,
        "footnote_count": fn_count,
        "footnotes_verified": bool(doc.get("footnotesVerified")),
        "footnotes_source": doc.get("footnotesSource"),
        "word_count": int(doc.get("wordCount") or 0),
        "label_count": int(doc.get("labelCount") or 0),
        "alternative_ids": doc.get("alternativeIds") or [],
        "abstract": doc.get("abstract"),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--corpus", required=True, type=Path)
    ap.add_argument("--documents", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    print(f"[hf-build] reading corpus  : {args.corpus}")
    corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
    print(f"[hf-build] reading documents: {args.documents}")
    docs = json.loads(args.documents.read_text(encoding="utf-8"))

    gc_docs = [d for d in docs if d.get("type", "gc") == "gc"]
    gc_paras = [p for p in corpus if p.get("type", "gc") == "gc"]
    docs_by_id = {d["docId"]: d for d in gc_docs}

    # Sort paragraphs by docId then idx — stable parquet output
    gc_paras.sort(key=lambda p: (p.get("docId", ""), int(p.get("idx", 0))))

    print(f"[hf-build] {len(gc_docs)} GC documents")
    print(f"[hf-build] {len(gc_paras)} GC paragraphs")

    # Build paragraph rows
    rows = [_para_row(p, docs_by_id.get(p.get("docId"))) for p in gc_paras]

    # Build document index rows
    paras_by_doc = {}
    for p in gc_paras:
        paras_by_doc.setdefault(p["docId"], []).append(p)
    doc_rows = [_doc_index_row(d, paras_by_doc.get(d["docId"], [])) for d in gc_docs]

    # Write parquet files
    out = args.out
    (out / "data").mkdir(parents=True, exist_ok=True)
    train_path = out / "data" / "train-00000-of-00001.parquet"
    table = pa.Table.from_pylist(rows, schema=PARQUET_SCHEMA)
    pq.write_table(table, train_path, compression="zstd")
    print(f"[hf-build] wrote {train_path} ({train_path.stat().st_size/1024/1024:.1f} MB, {len(rows)} rows)")

    doc_path = out / "document_index.parquet"
    doc_table = pa.Table.from_pylist(doc_rows, schema=DOC_INDEX_SCHEMA)
    pq.write_table(doc_table, doc_path, compression="zstd")
    print(f"[hf-build] wrote {doc_path} ({doc_path.stat().st_size/1024:.1f} KB, {len(doc_rows)} rows)")

    # Build summary
    label_counts = Counter()
    for p in gc_paras:
        for l in (p.get("labels") or []):
            label_counts[l] += 1
    fn_total = sum(len(p.get("footnotes") or []) for p in gc_paras)
    fn_xref = sum(
        1
        for p in gc_paras
        for f in (p.get("footnotes") or [])
        if f.get("isIbid") or f.get("isCrossRef") or f.get("isSelfRef")
    )
    preamble_total = sum(1 for p in gc_paras if p.get("isPreamble"))

    summary = {
        "build_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "version": "v2",
        "source": "UNHRD docs/corpus.json (v19.43)",
        "documents": {
            "total": len(gc_docs),
            "footnotes_verified": sum(1 for d in gc_docs if d.get("footnotesVerified")),
            "with_alternative_ids": sum(1 for d in gc_docs if d.get("alternativeIds")),
        },
        "paragraphs": {
            "total": len(gc_paras),
            "with_labels": sum(1 for p in gc_paras if p.get("labels")),
            "with_section": sum(1 for p in gc_paras if p.get("section")),
            "preamble": preamble_total,
        },
        "footnotes": {
            "total": fn_total,
            "cross_reference_resolved": fn_xref,
        },
        "labels": dict(label_counts.most_common()),
    }
    (out / "dataset_metadata.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[hf-build] wrote {out / 'dataset_metadata.json'}")
    print(f"[hf-build] summary:\n{json.dumps(summary['documents'], indent=2)}")
    print(f"          paragraphs: {json.dumps(summary['paragraphs'], indent=2)}")
    print(f"          footnotes : {json.dumps(summary['footnotes'], indent=2)}")


if __name__ == "__main__":
    main()
