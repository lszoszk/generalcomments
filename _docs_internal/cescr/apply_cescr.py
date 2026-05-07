#!/usr/bin/env python3
"""Stitch extracted CESCR data (cescr.json) into docs/jur/* artefacts.

Inputs
------
_docs_internal/cescr/cescr.json  — output of extract_cescr.py.
_docs_internal/cescr/case_list.json — discovery metadata (title, country, date).
docs/jur/documents.json     — full jurisprudence catalog (will be edited in place).
docs/jur/documents-lite.json— compact subset for catalog rail.
docs/jur/facets.json        — pre-computed filter chips.
docs/jur/manifest.json      — version + sha + byte counts.
docs/jur/shards/            — paragraph payloads, lazy-loaded by docId.

Outputs
-------
docs/jur/shards/jur_CESCR.json — new shard with all CESCR ¶ rows.
docs/jur/documents.json       — appended with CESCR docs.
docs/jur/documents-lite.json  — appended with CESCR lite rows.
docs/jur/facets.json          — refreshed (treaties += CESCR, countries union, …).
docs/jur/manifest.json        — re-stamped.

Schema mirroring
----------------
We mirror the field shape used by existing CRPD/CEDAW jurdocs. CCPR
docs additionally carry juris.ohchr.org metadata (jurisAuthor, …) we
don't have for CESCR — those fields are simply omitted on CESCR rows.

Usage
-----
    python3 _docs_internal/cescr/apply_cescr.py            # dry-run
    python3 _docs_internal/cescr/apply_cescr.py --apply    # write
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import quote

REPO = Path(__file__).resolve().parent.parent.parent
WORK = REPO / "_docs_internal" / "cescr"
JUR_DIR = REPO / "docs" / "jur"
SHARDS_DIR = JUR_DIR / "shards"

CESCR_JSON = WORK / "cescr.json"
DOCS_FULL = JUR_DIR / "documents.json"
DOCS_LITE = JUR_DIR / "documents-lite.json"
FACETS = JUR_DIR / "facets.json"
MANIFEST = JUR_DIR / "manifest.json"
NEW_SHARD = SHARDS_DIR / "jur_CESCR.json"

SHARD_ID = "jur_CESCR"
TODAY = dt.date.today().isoformat()


# ─────────────────────────────────────────  helpers
def sha16(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()[:16]


def write_json(path: Path, data, *, compact=True) -> None:
    sep = (",", ":") if compact else (", ", ": ")
    indent = None if compact else 2
    path.write_text(
        json.dumps(data, ensure_ascii=False, separators=sep, indent=indent) + "\n"
    )


def parse_iso_date(raw: str | None) -> str | None:
    """Best-effort parse of UN date strings like '17 June 2015',
    '28 January 2014 (initial submission)' → 'YYYY-MM-DD'."""
    if not raw:
        return None
    raw = raw.strip()
    # Strip parens annotations
    raw = re.sub(r"\([^)]*\)", "", raw).strip()
    # "DD Month YYYY"
    m = re.search(r"(\d{1,2})\s+([A-Z][a-z]+)\s+(\d{4})", raw)
    if m:
        try:
            return dt.datetime.strptime(
                f"{m.group(1)} {m.group(2)} {m.group(3)}", "%d %B %Y"
            ).date().isoformat()
        except Exception:
            pass
    # "DD Mon YYYY"
    m = re.search(r"(\d{1,2})\s+([A-Z][a-z]{2})\s+(\d{4})", raw)
    if m:
        try:
            return dt.datetime.strptime(
                f"{m.group(1)} {m.group(2)} {m.group(3)}", "%d %b %Y"
            ).date().isoformat()
        except Exception:
            pass
    return None


# ISO-3166 mapping for the countries CESCR has dealt with.
COUNTRY_CODES = {
    "Spain": "ES", "Italy": "IT", "France": "FR", "Ecuador": "EC",
    "Portugal": "PT", "Finland": "FI", "Uruguay": "UY",
    "Venezuela (Bolivarian Republic of)": "VE", "Belgium": "BE",
    "Argentina": "AR", "Luxembourg": "LU",
}


def classify_outcome(title: str) -> str:
    t = title.lower()
    if "discontinuance" in t or "discontinued" in t:
        return "discontinued"
    if "inadmissibility" in t or "inadmissible" in t:
        return "inadmissible"
    if "views" in t:
        return "views"
    return "other"


def extract_case_name(record: dict) -> str:
    """Build a 'X v. Country' style display name from front-matter +
    discovery title. Fallback to docId."""
    md = record.get("metadata") or {}
    discovery = record.get("discovery") or {}
    submitted = (md.get("submitted_by") or "").strip()
    state = (md.get("state_party") or "").strip() or discovery.get("country", "")
    # Strip "(represented by …)" tail
    submitted_clean = re.sub(r"\s*\(represented[^)]*\)\s*$", "", submitted).strip()
    if submitted_clean and state:
        return f"{submitted_clean} v. {state}"
    if discovery.get("title"):
        return discovery["title"]
    return record["symbol"]


def parse_articles(raw: str | None, instrument: str) -> list[dict]:
    """Lightweight parser for '2, paragraph 1; 11, paragraph 1' style
    article strings → structured list. Mirrors the CCPR shape but with
    instrument='ICESCR' / 'OP-ICESCR'."""
    if not raw:
        return []
    parts = [p.strip() for p in raw.split(";") if p.strip()]
    out = []
    for p in parts:
        m = re.match(
            r"(\d+)(?:,\s*paragraph\s+(\d+)(?:\s*\(([a-z])\))?)?(?:.*)?", p
        )
        if not m:
            continue
        out.append({
            "instrument": instrument,
            "article": m.group(1),
            **({"paragraph": m.group(2)} if m.group(2) else {}),
            **({"subparagraph": m.group(3)} if m.group(3) else {}),
            "raw": p,
        })
    return out


def articles_cited_short(raw: str | None) -> list[str]:
    """'2, paragraph 1; 11, paragraph 1' → ['Art. 2(1)', 'Art. 11(1)']."""
    if not raw:
        return []
    out = []
    for p in raw.split(";"):
        m = re.match(r"\s*(\d+)(?:,\s*paragraph\s+(\d+))?", p)
        if not m:
            continue
        if m.group(2):
            out.append(f"Art. {m.group(1)}({m.group(2)})")
        else:
            out.append(f"Art. {m.group(1)}")
    return out


# ─────────────────────────────────────────  build per-doc rows
def build_doc_entry(doc_id: str, record: dict) -> tuple[dict, dict]:
    """Returns (full_doc, lite_doc) in the shapes used by docs/jur/
    documents.json and documents-lite.json."""
    md = record.get("metadata") or {}
    discovery = record.get("discovery") or {}
    paragraphs = record.get("paragraphs") or []
    symbol = record["symbol"]

    country = discovery.get("country") or md.get("state_party") or ""
    country_code = COUNTRY_CODES.get(country)
    case_name = extract_case_name(record)
    case_name_display = re.sub(r" v\. ", " v. ", case_name)
    title = case_name

    publication_date = discovery.get("publication_date") or ""
    adoption_iso = parse_iso_date(publication_date)
    communication_iso = parse_iso_date(md.get("communication_date"))
    sym_match = re.match(r"E/C\.12/(\d+)/D/(\d+)/(\d+)", symbol)
    session_no = sym_match.group(1) if sym_match else None
    comm_no = sym_match.group(2) if sym_match else None
    comm_year = sym_match.group(3) if sym_match else None

    outcome = classify_outcome(discovery.get("title", ""))
    word_count = sum(len(re.findall(r"\w+", p.get("text", ""))) for p in paragraphs)
    case_labels: list[str] = []  # CESCR doesn't ship label tags

    download_link = (
        f"https://tbinternet.ohchr.org/_layouts/15/treatybodyexternal/"
        f"Download.aspx?symbolno={quote(symbol, safe='')}&Lang=en"
    )

    full = {
        "docId": doc_id,
        "type": "jur",
        "treaty": "CESCR",
        "committee": "CESCR",
        "committees": ["CESCR"],
        "signature": symbol,
        "symbol": symbol,
        "title": title,
        "name": case_name,
        "nameShort": case_name,
        "caseName": case_name,
        "caseNameDisplay": case_name_display,
        "caseNameSource": "front_matter" if md.get("submitted_by") else "discovery",
        "caseNameConfidence": "medium",
        "originalName": discovery.get("title", ""),
        "originalTitle": discovery.get("title", ""),
        "country": country,
        "countryCode": country_code,
        "stateParty": md.get("state_party", country) or country,
        "submittedBy": md.get("submitted_by"),
        "submittedByClean": (
            re.sub(r"\s*\(represented[^)]*\)\s*$", "", md.get("submitted_by") or "")
            .strip() or None
        ),
        "representation": (
            (m.group(1)
             if (m := re.search(r"\(represented (?:by\s+)?([^)]+)\)",
                                md.get("submitted_by") or "")) else None)
        ),
        "allegedVictims": md.get("alleged_victims"),
        "communicationDate": md.get("communication_date"),
        "communicationNumbers": [f"{comm_no}/{comm_year}"] if comm_no else [],
        "communicationYear": int(comm_year) if comm_year else None,
        "year": int(comm_year) if comm_year else None,
        "adoptionDate": adoption_iso,
        "adoptionYear": int(adoption_iso[:4]) if adoption_iso else None,
        "subjectMatter": md.get("subject_matter") or [],
        "substantiveIssues": md.get("substantive_issues") or [],
        "proceduralIssues": md.get("procedural_issues") or [],
        "covenantArticles": md.get("covenant_articles"),
        "covenantArticlesParsed": parse_articles(md.get("covenant_articles"), "ICESCR"),
        "optionalProtocolArticles": md.get("op_articles"),
        "optionalProtocolArticlesParsed": parse_articles(md.get("op_articles"), "OP-ICESCR"),
        "articlesCited": articles_cited_short(md.get("covenant_articles")),
        "rightsKeywords": [],
        "caseLabels": case_labels,
        "labelCount": len(case_labels),
        "outcome": outcome,
        "outcomeDetailed": outcome,
        "languages": ["en"],
        "link": download_link,
        "sourceFile": f"_docs_internal/cescr/docx/{doc_id}.docx",
        "sourceFormat": "docx",
        "shardId": SHARD_ID,
        "paragraphCount": len(paragraphs),
        "wordCount": word_count,
        "metadataConfidence": "high" if md.get("submitted_by") else "low",
        "firstAddedAt": TODAY,
        "lastVerifiedAt": TODAY,
        "_session": session_no,
    }
    # Drop None/empty for cleanliness
    full = {k: v for k, v in full.items() if v not in (None, "")}

    # documents-lite is a stripped subset
    lite_keys = (
        "docId type treaty committee committees signature symbol "
        "title name nameShort caseName caseNameDisplay caseNameSource "
        "caseNameConfidence country countryCode stateParty submittedBy "
        "submittedByClean representation allegedVictims communicationDate "
        "communicationNumbers communicationYear year adoptionDate "
        "adoptionYear subjectMatter substantiveIssues proceduralIssues "
        "covenantArticles optionalProtocolArticles articlesCited "
        "rightsKeywords caseLabels labelCount outcome outcomeDetailed "
        "languages link sourceFile sourceFormat shardId paragraphCount "
        "wordCount metadataConfidence firstAddedAt lastVerifiedAt"
    ).split()
    lite = {k: full[k] for k in lite_keys if k in full}
    return full, lite


def build_paragraph_rows(doc_id: str, record: dict, country: str | None,
                         outcome: str, year: int | None) -> list[dict]:
    """Mirror the existing JUR paragraph schema (CRPD shape):
       {id, docId, idx, n, paragraphId, text, footnotes, section,
        sectionInherited, labels, sourceFormat, type, treaty, country,
        year, outcome}"""
    rows = []
    last_section: str | None = None
    for i, p in enumerate(record.get("paragraphs") or [], start=1):
        # Use deepest level of section_path as `section`.  Existing CRPD
        # rows have a single string; we keep the convention.
        sec = (p.get("section_path") or [None])[-1] if p.get("section_path") else None
        section_inherited = (sec is not None) and (sec == last_section)
        if sec:
            last_section = sec
        rows.append({
            "id": f"{doc_id}-{i:04d}",
            "docId": doc_id,
            "idx": i,
            "n": p.get("n"),
            "paragraphId": (p.get("n") + ".") if p.get("n") else None,
            "text": p.get("text"),
            "footnotes": p.get("footnotes") or [],
            "section": sec,
            "sectionInherited": section_inherited,
            "labels": [],
            "sourceFormat": "docx",
            "type": "jur",
            "treaty": "CESCR",
            "country": country,
            "year": year,
            "outcome": outcome,
        })
    return rows


# ─────────────────────────────────────────  driver
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true",
                    help="Write changes to docs/jur/.")
    args = ap.parse_args()

    if not CESCR_JSON.exists():
        print(f"  ✗ {CESCR_JSON.relative_to(REPO)} not found — "
              f"run extract_cescr.py first.", file=sys.stderr)
        return 1

    print(f"Stitching CESCR jurisprudence from {CESCR_JSON.relative_to(REPO)}")
    print(f"  mode: {'APPLY' if args.apply else 'dry-run'}")
    print()

    cescr = json.loads(CESCR_JSON.read_text())
    docs_full = json.loads(DOCS_FULL.read_text())
    docs_lite = json.loads(DOCS_LITE.read_text())
    facets = json.loads(FACETS.read_text())

    # Drop any stale CESCR rows from earlier runs (idempotency).
    docs_full = [d for d in docs_full if d.get("treaty") != "CESCR"]
    docs_lite = [d for d in docs_lite if d.get("treaty") != "CESCR"]

    # Build the new shard + documents entries.
    shard_doc_ids: list[str] = []
    shard_paragraphs: list[dict] = []
    n_docs = n_paras = 0

    for doc_id, record in sorted(cescr.items()):
        full_entry, lite_entry = build_doc_entry(doc_id, record)
        country = full_entry.get("country") or None
        outcome = full_entry.get("outcome", "other")
        year = full_entry.get("year")
        rows = build_paragraph_rows(doc_id, record, country, outcome, year)
        if not rows:
            continue
        docs_full.append(full_entry)
        docs_lite.append(lite_entry)
        shard_doc_ids.append(doc_id)
        shard_paragraphs.extend(rows)
        n_docs += 1
        n_paras += len(rows)

    shard = {
        "shardId": SHARD_ID,
        "builtAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "documentCount": n_docs,
        "paragraphCount": n_paras,
        "documents": shard_doc_ids,
        "paragraphs": shard_paragraphs,
    }

    # facets.json schema is `[{value, count}]` per facet, where count
    # is doc-count for treaties/countries/countryCodes and ¶-count for
    # outcomes/labels/formats. Recomputing all facets is risky and
    # outside this change's scope — we only ADD CESCR to existing
    # facets so the new docs remain filterable. Numeric counts for
    # other treaties stay as-is (they reflect the original build).
    def _bump(facet_list, value, delta_count):
        """Add or increment {value, count} in a facet list."""
        for entry in facet_list:
            if entry.get("value") == value:
                entry["count"] = entry.get("count", 0) + delta_count
                return
        facet_list.append({"value": value, "count": delta_count})

    cescr_full = [d for d in docs_full if d.get("treaty") == "CESCR"]
    n_cescr_paras = sum(d.get("paragraphCount", 0) for d in cescr_full)
    # Treaties: count documents
    facets.setdefault("treaties", [])
    _bump(facets["treaties"], "CESCR", len(cescr_full))
    # Countries / countryCodes: doc counts
    facets.setdefault("countries", [])
    facets.setdefault("countryCodes", [])
    from collections import Counter
    country_delta = Counter(d.get("country") for d in cescr_full
                            if d.get("country"))
    code_delta = Counter(d.get("countryCode") for d in cescr_full
                         if d.get("countryCode"))
    for c, n in country_delta.items():
        _bump(facets["countries"], c, n)
    for c, n in code_delta.items():
        _bump(facets["countryCodes"], c, n)
    # Outcomes: ¶ counts (matches original convention)
    facets.setdefault("outcomes", [])
    facets.setdefault("outcomesDetailed", [])
    outcome_delta = Counter()
    detailed_delta = Counter()
    for p in shard_paragraphs:
        outcome_delta[p.get("outcome", "other")] += 1
        detailed_delta[p.get("outcome", "other")] += 1
    for o, n in outcome_delta.items():
        _bump(facets["outcomes"], o, n)
    for o, n in detailed_delta.items():
        _bump(facets["outcomesDetailed"], o, n)
    # Formats: ¶ counts
    facets.setdefault("formats", [])
    _bump(facets["formats"], "docx", n_cescr_paras)
    # Years: nested {min, max, histogram: [{year, count}]} structure.
    year_delta = Counter()
    for p in shard_paragraphs:
        if p.get("year"):
            year_delta[p["year"]] += 1
    if year_delta:
        years_facet = facets.setdefault(
            "years", {"min": 9999, "max": 0, "histogram": []}
        )
        hist = years_facet.setdefault("histogram", [])
        for y, n in year_delta.items():
            for entry in hist:
                if entry.get("year") == y:
                    entry["count"] = entry.get("count", 0) + n
                    break
            else:
                hist.append({"year": y, "count": n})
        hist.sort(key=lambda e: e.get("year") or 0)
        years_facet["min"] = min(years_facet.get("min", 9999),
                                 min(year_delta))
        years_facet["max"] = max(years_facet.get("max", 0),
                                 max(year_delta))
    # Sort each facet by count desc, value asc as tiebreaker
    for k, lst in facets.items():
        if isinstance(lst, list) and lst and isinstance(lst[0], dict):
            lst.sort(key=lambda e: (-e.get("count", 0), str(e.get("value", ""))))
    new_facets = facets

    # Update manifest.
    manifest = json.loads(MANIFEST.read_text())
    manifest["builtAt"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    cur_paragraphs = manifest.get("counts", {}).get("paragraphs", 0)
    cur_shards = manifest.get("counts", {}).get("shards", 0)
    new_shard_existed = SHARD_ID in {
        k.replace("shards/", "").replace(".json", "")
        for k in (manifest.get("files") or {})
        if k.startswith("shards/")
    }
    treaties_in_facets = sorted({e["value"] for e in facets.get("treaties", [])})
    manifest["counts"] = {
        **manifest.get("counts", {}),
        "documents": len(docs_full),
        "paragraphs": cur_paragraphs + n_paras,
        "shards": cur_shards + (0 if new_shard_existed else 1),
        "treaties": len(treaties_in_facets),
    }

    print(f"  CESCR docs to add:  {n_docs:,}")
    print(f"  CESCR paragraphs:   {n_paras:,}")
    print(f"  Total docs after:   {len(docs_full):,}")
    print(f"  Treaties → {treaties_in_facets}")
    print(f"  Countries (CESCR additions): "
          f"{sorted({d['country'] for d in docs_lite if d.get('treaty') == 'CESCR' and d.get('country')})}")
    print()

    if not args.apply:
        print("  Re-run with --apply to write the changes.")
        return 0

    # Write artefacts.
    SHARDS_DIR.mkdir(parents=True, exist_ok=True)
    write_json(NEW_SHARD, shard, compact=True)
    write_json(DOCS_FULL, docs_full, compact=True)
    write_json(DOCS_LITE, docs_lite, compact=True)
    write_json(FACETS, new_facets, compact=False)

    # Refresh manifest's files block by re-hashing the changed files.
    files = manifest.get("files") or {}
    for path, key in (
        (DOCS_FULL, "documents.json"),
        (DOCS_LITE, "documents-lite.json"),
        (FACETS, "facets.json"),
        (NEW_SHARD, f"shards/{SHARD_ID}.json"),
    ):
        b = path.read_bytes()
        entry = {"sha": sha16(b), "bytes": len(b)}
        # Per-shard entries also carry document/paragraph counts.
        if key.startswith("shards/"):
            entry["documents"] = n_docs
            entry["paragraphs"] = n_paras
        files[key] = entry
    # Re-derive paragraph + shard counts from the file table to stay
    # consistent (sum across all shards we know about).
    all_para = 0
    n_shards = 0
    for k, info in files.items():
        if k.startswith("shards/"):
            n_shards += 1
            all_para += info.get("paragraphs", 0)
    manifest["counts"]["paragraphs"] = all_para
    manifest["counts"]["shards"] = n_shards
    manifest["files"] = files
    write_json(MANIFEST, manifest, compact=False)

    print(f"\n  ✅ wrote {NEW_SHARD.relative_to(REPO)}  "
          f"({len(NEW_SHARD.read_bytes()):,} bytes)")
    print(f"  ✅ updated docs/jur/{{documents,documents-lite,facets,manifest}}.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
