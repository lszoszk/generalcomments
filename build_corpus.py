#!/usr/bin/env python3
"""
Build a single static corpus from the PythonAnywhere data layout.

Inputs (read-only):
  mysite_pythonanywhere/
    crc_gc_info.json                 # GC document metadata
    specialprocedures_info.json      # SP document metadata
    json_data/*.json                 # GC paragraph files
    json_data_sp/*.json              # SP paragraph files

Outputs (written to ./dist/):
  corpus.json       flat list of paragraphs with embedded metadata
  documents.json    one record per document (metadata only)
  facets.json       pre-aggregated filter facets (committees, labels, years)
  manifest.json     version, build timestamp, sha256 of each output, counts
  build_report.txt  human-readable diagnostics (orphans, mismatches, etc.)

Excluded on purpose:
  json_data_2/      stale duplicate of json_data/
  neurorights/*     separate dataset (Scopus articles), not part of GC/SP corpus

Usage:
  python3 build_corpus.py                                  # writes ./docs/
  python3 build_corpus.py --pretty                         # also writes pretty JSON
  python3 build_corpus.py --out path/                      # custom output dir
  python3 build_corpus.py --src ../GC_Database/mysite_pythonanywhere
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

# --------------------------------------------------------------------------
# Paths — resolved at runtime; defaults assume sibling 'mysite_pythonanywhere/'
# --------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
DEFAULT_SRC = ROOT / "mysite_pythonanywhere"


def resolve_paths(src: Path) -> dict:
    """Return data file paths under the given source dir.
    Some data may be missing (e.g. SP files only exist locally, not in the public repo).
    """
    return {
        "src": src,
        "gc_meta": src / "crc_gc_info.json",
        "sp_meta": src / "specialprocedures_info.json",
        "gc_para": src / "json_data",
        "sp_para": src / "json_data_sp",
    }

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def slugify(value: str, maxlen: int = 64) -> str:
    """ASCII-folded, hyphen-separated, lowercase. Stable across runs."""
    if not value:
        return ""
    norm = unicodedata.normalize("NFKD", value)
    norm = norm.encode("ascii", "ignore").decode("ascii")
    norm = norm.lower()
    norm = re.sub(r"[^a-z0-9]+", "-", norm).strip("-")
    return norm[:maxlen]


def doc_id_for(signature: str, fallback_filename: str, unique_signatures: set[str]) -> str:
    """Prefer signature when globally unique (e.g. 'CRC/C/GC/25' → 'crc-c-gc-25').
    Fall back to filename slug otherwise (e.g. CEDAW GR9–GR13 share signature A/44/38)."""
    if signature and signature in unique_signatures:
        sid = slugify(signature)
        if sid:
            return sid
    base = Path(fallback_filename).stem
    return slugify(base)


def parse_paragraph_number(raw) -> int | None:
    """ID can be int, None, or a string like '1. ' / '12.' / '3a'. Extract leading int."""
    if raw is None:
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        return int(raw) if raw.is_integer() else None
    s = str(raw).strip()
    m = re.match(r"^(\d+)", s)
    return int(m.group(1)) if m else None


def parse_year(meta: dict) -> int | None:
    """SP metadata uses both 'Adoption Year' and 'Adoption year'. GC uses 'Adoption Year'."""
    for key in ("Adoption Year", "Adoption year"):
        v = meta.get(key)
        if v in (None, ""):
            continue
        try:
            return int(v)
        except (TypeError, ValueError):
            # sometimes it's a string like "2021"
            m = re.search(r"\d{4}", str(v))
            if m:
                return int(m.group())
    return None


def split_committees(raw: str) -> list[str]:
    if not raw:
        return []
    return [c.strip() for c in raw.split(",") if c.strip()]


def short_name(meta: dict) -> str:
    return meta.get("Simplified Name") or meta.get("Name") or ""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:16]  # short hash, enough for cache-busting


# --------------------------------------------------------------------------
# Filename → metadata index
# --------------------------------------------------------------------------
def index_metadata(metadata: list[dict]) -> dict[str, dict]:
    """Map basename → metadata. Add a suffix-match fallback for SP weirdness."""
    by_name: dict[str, dict] = {}
    for m in metadata:
        path = m.get("File PATH", "")
        if not path:
            continue
        by_name[os.path.basename(path)] = m
    return by_name


def lookup_metadata(filename: str, by_name: dict[str, dict]) -> dict | None:
    """Try exact match, then suffix match (handles 'SR_belief_A_50_440.json' vs 'A_50_440.json')."""
    if filename in by_name:
        return by_name[filename]
    # suffix fallback: any metadata key that ends with /-joined filename
    for k, v in by_name.items():
        if k.endswith("_" + filename) or k.endswith("/" + filename):
            return v
    return None


# --------------------------------------------------------------------------
# Build pipeline
# --------------------------------------------------------------------------
def collect_documents(
    para_dir: Path,
    metadata: list[dict],
    doc_type: str,
    report: list[str],
) -> tuple[list[dict], list[dict]]:
    """Returns (documents, paragraphs)."""
    by_name = index_metadata(metadata)

    # Pre-scan: which signatures are unique within this dataset?
    # CEDAW GR9-GR13 share signature A/44/38 (bundled session report) — for those we fall back to filename.
    sig_counts: Counter = Counter()
    for fpath in sorted(p for p in para_dir.iterdir() if p.suffix == ".json"):
        m = lookup_metadata(fpath.name, by_name)
        if m:
            sig = (m.get("Signature") or "").strip()
            if sig:
                sig_counts[sig] += 1
    unique_signatures = {sig for sig, n in sig_counts.items() if n == 1}

    # Track which metadata records were matched (for orphan reporting)
    matched_meta_keys: set[str] = set()

    files = sorted(p for p in para_dir.iterdir() if p.suffix == ".json")
    documents: list[dict] = []
    paragraphs: list[dict] = []
    seen_doc_ids: dict[str, str] = {}  # doc_id -> filename, for collision detection

    for fpath in files:
        filename = fpath.name
        meta = lookup_metadata(filename, by_name)
        if not meta:
            report.append(f"[{doc_type}] FILE WITHOUT METADATA: {filename}")
            continue

        # Mark matched
        meta_basename = os.path.basename(meta.get("File PATH", ""))
        matched_meta_keys.add(meta_basename)

        signature = meta.get("Signature", "") or ""
        d_id = doc_id_for(signature, filename, unique_signatures)
        # Final safety net: if even the filename-derived id collides (shouldn't happen),
        # append a deterministic hash of the full filename.
        if d_id in seen_doc_ids and seen_doc_ids[d_id] != filename:
            suffix = hashlib.sha1(filename.encode("utf-8")).hexdigest()[:6]
            d_id = f"{d_id}-{suffix}"
        seen_doc_ids[d_id] = filename

        committees = split_committees(meta.get("Committee", ""))
        year = parse_year(meta)

        doc_record = {
            "docId": d_id,
            "type": doc_type,
            "name": meta.get("Name", "").strip(),
            "nameShort": short_name(meta).strip(),
            "signature": signature.strip(),
            "committee": committees[0] if committees else "",
            "committees": committees,
            "year": year,
            "adoptionDate": meta.get("Adoption Date", "").strip(),
            "link": meta.get("Link", "").strip(),
            "sourceFile": filename,
        }
        if doc_type == "sp":
            doc_record["mandate"] = meta.get("Mandate holder", "").strip()
            doc_record["presented"] = meta.get("Presented", "").strip()

        # Load paragraphs for this document
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                items = json.load(f)
        except Exception as e:
            report.append(f"[{doc_type}] FAILED TO PARSE {filename}: {e}")
            continue

        if not isinstance(items, list):
            report.append(f"[{doc_type}] UNEXPECTED SHAPE in {filename}: not a list")
            continue

        # Position-based paragraph ID guarantees uniqueness even when 'n' repeats
        # (some docs have nested sub-paragraphs sharing the same number).
        idx = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            text = (item.get("Text") or "").strip()
            if not text:
                continue
            idx += 1
            n = parse_paragraph_number(item.get("ID"))
            labels = [l for l in (item.get("Labels") or []) if isinstance(l, str)]

            paragraphs.append({
                "id": f"{d_id}-{idx:04d}",
                "docId": d_id,
                "idx": idx,
                "n": n,
                "text": text,
                "labels": labels,
                "type": doc_type,
                "committee": doc_record["committee"],
                "committees": committees,
                "year": year,
            })
        para_count = idx

        doc_record["paragraphCount"] = para_count
        documents.append(doc_record)

    # Report metadata orphans
    for k in by_name.keys() - matched_meta_keys:
        report.append(f"[{doc_type}] METADATA WITHOUT FILE: {k}")

    return documents, paragraphs


def build_facets(documents: list[dict], paragraphs: list[dict]) -> dict:
    """Pre-aggregate counts for the filter sidebar."""
    committees = Counter()
    labels = Counter()
    years = Counter()
    types = Counter()
    mandates = Counter()

    for p in paragraphs:
        types[p["type"]] += 1
        if p["year"] is not None:
            years[p["year"]] += 1
        for c in p["committees"]:
            committees[c] += 1
        for l in p["labels"]:
            labels[l] += 1

    for d in documents:
        if d.get("mandate"):
            mandates[d["mandate"]] += 1

    year_min = min(years) if years else None
    year_max = max(years) if years else None

    return {
        "committees": [
            {"value": c, "count": n} for c, n in committees.most_common()
        ],
        "labels": [
            {"value": l, "count": n} for l, n in labels.most_common()
        ],
        "types": [
            {"value": t, "count": n} for t, n in types.most_common()
        ],
        "years": {
            "min": year_min,
            "max": year_max,
            "histogram": [
                {"year": y, "count": years[y]} for y in sorted(years)
            ],
        },
        "mandates": [
            {"value": m, "count": n} for m, n in mandates.most_common()
        ],
    }


def write_json(path: Path, data, *, pretty: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        if pretty:
            json.dump(data, f, ensure_ascii=False, indent=2)
        else:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))


# --------------------------------------------------------------------------
# Sitemap
# --------------------------------------------------------------------------
SITE_BASE = "https://lszoszk.github.io/generalcomments"


def write_sitemap(path: Path, documents: list[dict], built_iso: str) -> None:
    """Emit sitemap.xml that points at each document via its first paragraph.

    Each ?p=<docId>-0001 URL is a stable deep link. The SPA loads, sets the
    active paragraph, and updates document.title — so Googlebot (which has
    executed JS since 2019) gets per-document content with a per-document
    title for indexing.
    """
    last = built_iso.split("T")[0]
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
        f"  <url><loc>{SITE_BASE}/</loc><lastmod>{last}</lastmod>"
        f"<changefreq>weekly</changefreq><priority>1.0</priority></url>",
    ]
    # Scope shortcuts so the SP and All-sources views can be discovered.
    for q in ("?scope=sp", "?scope=all"):
        lines.append(
            f"  <url><loc>{SITE_BASE}/{q}</loc><lastmod>{last}</lastmod>"
            f"<changefreq>weekly</changefreq><priority>0.9</priority></url>"
        )
    # One URL per document — anchored to its first paragraph.
    for d in documents:
        if not d.get("paragraphCount"):
            continue
        first_pid = f"{d['docId']}-0001"
        prio = "0.8" if d.get("type") == "gc" else "0.6"
        lines.append(
            f"  <url><loc>{SITE_BASE}/?p={first_pid}</loc>"
            f"<lastmod>{last}</lastmod>"
            f"<changefreq>monthly</changefreq><priority>{prio}</priority></url>"
        )
    lines.append("</urlset>")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description="Build static corpus for the GC database.")
    parser.add_argument("--src", type=Path, default=DEFAULT_SRC, help="Source data directory (default: ./mysite_pythonanywhere).")
    parser.add_argument("--out", type=Path, default=ROOT / "docs", help="Output directory (GitHub Pages serves from docs/ on main).")
    parser.add_argument("--pretty", action="store_true", help="Also emit pretty-printed corpus.")
    args = parser.parse_args()

    paths = resolve_paths(args.src)
    if not paths["gc_meta"].exists():
        print(f"ERROR: GC metadata not found at {paths['gc_meta']}", file=sys.stderr)
        return 1
    sp_available = paths["sp_meta"].exists() and paths["sp_para"].exists()

    print(f"Reading from: {paths['src']}")
    print(f"Writing to:   {args.out}")
    print(f"SP data:      {'present' if sp_available else 'missing — building GC only'}")
    print()

    gc_meta = json.load(open(paths["gc_meta"], encoding="utf-8"))
    sp_meta = json.load(open(paths["sp_meta"], encoding="utf-8")) if sp_available else []

    report: list[str] = []
    gc_docs, gc_paras = collect_documents(paths["gc_para"], gc_meta, "gc", report)
    if sp_available:
        sp_docs, sp_paras = collect_documents(paths["sp_para"], sp_meta, "sp", report)
    else:
        sp_docs, sp_paras = [], []
        report.append("[sp] DATA NOT AVAILABLE in this source — Special Procedures excluded from build.")

    documents = gc_docs + sp_docs
    paragraphs = gc_paras + sp_paras
    facets = build_facets(documents, paragraphs)

    out = args.out
    out.mkdir(parents=True, exist_ok=True)

    write_json(out / "corpus.json", paragraphs)
    write_json(out / "documents.json", documents)
    write_json(out / "facets.json", facets)
    if args.pretty:
        write_json(out / "corpus.pretty.json", paragraphs, pretty=True)
        write_json(out / "documents.pretty.json", documents, pretty=True)
        write_json(out / "facets.pretty.json", facets, pretty=True)

    # Manifest
    build_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    manifest = {
        "version": build_iso.split("T")[0].replace("-", ""),
        "builtAt": build_iso,
        "counts": {
            "documents": len(documents),
            "paragraphs": len(paragraphs),
            "gcDocuments": len(gc_docs),
            "gcParagraphs": len(gc_paras),
            "spDocuments": len(sp_docs),
            "spParagraphs": len(sp_paras),
            "labels": len(facets["labels"]),
            "committees": len(facets["committees"]),
            "yearRange": [facets["years"]["min"], facets["years"]["max"]],
        },
        "files": {
            "corpus.json": {
                "sha": sha256_file(out / "corpus.json"),
                "bytes": (out / "corpus.json").stat().st_size,
            },
            "documents.json": {
                "sha": sha256_file(out / "documents.json"),
                "bytes": (out / "documents.json").stat().st_size,
            },
            "facets.json": {
                "sha": sha256_file(out / "facets.json"),
                "bytes": (out / "facets.json").stat().st_size,
            },
        },
        "schema": {
            "paragraph": ["id", "docId", "idx", "n", "text", "labels", "type", "committee", "committees", "year"],
            "document": ["docId", "type", "name", "nameShort", "signature", "committee", "committees", "year", "adoptionDate", "link", "sourceFile", "paragraphCount", "mandate?", "presented?"],
        },
    }
    write_json(out / "manifest.json", manifest, pretty=True)

    # sitemap.xml — one URL per document for deep indexing
    write_sitemap(out / "sitemap.xml", documents, build_iso)

    # Build report
    report_path = out / "build_report.txt"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(f"Build report - {build_iso}\n")
        f.write("=" * 60 + "\n\n")
        f.write(f"Documents: {manifest['counts']['documents']} ({len(gc_docs)} GC + {len(sp_docs)} SP)\n")
        f.write(f"Paragraphs: {manifest['counts']['paragraphs']} ({len(gc_paras)} GC + {len(sp_paras)} SP)\n")
        f.write(f"Labels: {manifest['counts']['labels']}\n")
        f.write(f"Committees: {manifest['counts']['committees']}\n")
        f.write(f"Year range: {manifest['counts']['yearRange']}\n\n")
        if report:
            f.write(f"Diagnostics ({len(report)} entries):\n")
            f.write("-" * 60 + "\n")
            for line in report:
                f.write(line + "\n")
        else:
            f.write("No diagnostics. Clean build.\n")

    # Console summary
    print(f"Documents:  {len(documents):>6}  ({len(gc_docs)} GC + {len(sp_docs)} SP)")
    print(f"Paragraphs: {len(paragraphs):>6}  ({len(gc_paras)} GC + {len(sp_paras)} SP)")
    print(f"Labels:     {len(facets['labels']):>6}")
    print(f"Committees: {len(facets['committees']):>6}")
    print(f"Years:      {facets['years']['min']} - {facets['years']['max']}")
    print()
    for fname in ("corpus.json", "documents.json", "facets.json", "manifest.json"):
        size = (out / fname).stat().st_size
        print(f"  {fname:<20}  {size/1024:>9.1f} KB")
    if report:
        print(f"\n{len(report)} diagnostics written to {report_path}")
    else:
        print("\nClean build, no diagnostics.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
