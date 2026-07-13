#!/usr/bin/env python3
"""Apply the verified General Comment version-relationship audit.

The public documents catalogue is generated from crc_gc_info.json. This script
updates both files so the checked-in build and its source metadata stay in sync.
Every substantive relationship below is based on explicit wording in an
official UN document, not an inference from a similar title or article number.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "mysite_pythonanywhere" / "crc_gc_info.json"
PUBLIC_PATH = ROOT / "docs" / "documents.json"
FACETS_PATH = ROOT / "docs" / "facets.json"
MANIFEST_PATH = ROOT / "docs" / "manifest.json"
VERIFIED_AT = "2026-07-13"


SUPERSESSIONS = {
    "A/53/44": "CAT/C/GC/4",
    "CRC/C/GC/10": "CRC/C/GC/24",
    "HRI/GEN/1/Rev.9 (Vol. I) p. 174": "CCPR/C/21/Rev.1/Add. 13",
    "HRI/GEN/1/Rev.9 (Vol. I) p. 175": "CCPR/C/21/Rev.1/Add. 10",
    "HRI/GEN/1/Rev.9 (Vol. I) p. 176": "CCPR/C/21/Rev.1/Add. 11",
    "HRI/GEN/1/Rev.9 (Vol. I) p.176": "CCPR/C/GC/36",
    "HRI/GEN/1/Rev.9 (Vol. I) p. 178": "HRI/GEN/1/Rev.9 (Vol. I), p. 200",
    "HRI/GEN/1/Rev.9 (Vol. I) p. 179": "CCPR/C/GC/35",
    "HRI/GEN/1/Rev.9 (Vol. I) p. 180": "HRI/GEN/1/Rev.9 (Vol. I), p. 202",
    "HRI/GEN/1/Rev.9 (Vol. I) p. 181": "CCPR/C/GC/34",
    "HRI/GEN/1/Rev.9 (Vol. I) p. 184": "CCPR/C/GC/32",
    "HRI/GEN/1/Rev.9 (Vol. I) p. 188": "CCPR/C/GC/36",
}

# GC2 was superseded by reporting guidelines that are outside this corpus.
EXTERNAL_SOURCES = {
    "CCPR/C/66/GUI/Rev.2": "https://docs.un.org/en/CCPR/C/66/GUI/Rev.2",
}

EXTERNAL_SUPERSESSIONS_BY_FILE = {
    # GC1 and GC2 share the same session-report/page signature, so filename is
    # the only stable record-level key for the formally superseded GC2.
    "Annotated_CCPR_GC2_reporting_guidelines.json": "CCPR/C/66/GUI/Rev.2",
}

VERSIONED_TEXTS = {
    "CRC/C/GC/7/Rev.1": "revised",
    "CEDAW/C/GC/31/Rev.1–CRC/C/GC/18/Rev.1": "revised",
    "CRC/C/GC/9/Corr.1": "corrected",
}

# These are deliberately not supersessions. The official texts say
# "complements and updates" and "Addendum", respectively.
FILE_RELATIONSHIPS = {
    "Annotated_CEDAW_GR19_violence.json": {
        "updatedBy": "CEDAW/C/GC/35",
        "relationshipSource": "https://docs.un.org/en/CEDAW/C/GC/35",
    },
    "Annotated_CEDAW-GR35-GBV.json": {
        "updates": "A/47/38 (general recommendation No. 19)",
    },
    "Annotated_CEDAW-GR30-conflict.json": {
        "supplementedBy": "CEDAW/C/GC/30/Add.1",
        "relationshipSource": "https://docs.un.org/en/CEDAW/C/GC/30/Add.1",
    },
    "Annotated_CEDAW_GR30_Add1_WPS.json": {
        "supplements": "CEDAW/C/GC/30",
    },
}


def basename(record: dict, source: bool) -> str:
    key = "File PATH" if source else "sourceFile"
    return Path(record.get(key, "")).name


def signature(record: dict, source: bool) -> str:
    return str(record.get("Signature" if source else "signature", "")).strip()


def official_link(record: dict, source: bool) -> str:
    return str(record.get("Link" if source else "link", "")).strip()


def scalar_or_list(values: list[str]):
    unique = list(dict.fromkeys(values))
    return unique[0] if len(unique) == 1 else unique


def apply(records: list[dict], *, source: bool) -> int:
    by_signature: dict[str, list[dict]] = {}
    by_file: dict[str, dict] = {}
    for record in records:
        by_signature.setdefault(signature(record, source), []).append(record)
        by_file[basename(record, source)] = record

    changed = 0
    reverse: dict[str, list[str]] = {}
    for old_signature, new_signature in SUPERSESSIONS.items():
        matches = by_signature.get(old_signature, [])
        if len(matches) != 1:
            raise RuntimeError(f"Expected one record for {old_signature!r}, found {len(matches)}")

        replacement_matches = by_signature.get(new_signature, [])
        replacement = replacement_matches[0] if len(replacement_matches) == 1 else None
        source_url = official_link(replacement, source) if replacement else EXTERNAL_SOURCES.get(new_signature, "")
        if not source_url:
            raise RuntimeError(f"No official status source for {old_signature!r} -> {new_signature!r}")

        old = matches[0]
        updates = {
            "status": "superseded",
            "supersededBy": new_signature,
            "statusSource": source_url,
            "statusVerifiedAt": VERIFIED_AT,
        }
        for key, value in updates.items():
            if old.get(key) != value:
                old[key] = value
                changed += 1
        if replacement:
            reverse.setdefault(new_signature, []).append(old_signature)

    for new_signature, old_signatures in reverse.items():
        replacement = by_signature[new_signature][0]
        value = scalar_or_list(old_signatures)
        if replacement.get("supersedes") != value:
            replacement["supersedes"] = value
            changed += 1

    for filename, new_signature in EXTERNAL_SUPERSESSIONS_BY_FILE.items():
        record = by_file.get(filename)
        if not record:
            raise RuntimeError(f"Missing externally superseded record {filename!r}")
        updates = {
            "status": "superseded",
            "supersededBy": new_signature,
            "statusSource": EXTERNAL_SOURCES[new_signature],
            "statusVerifiedAt": VERIFIED_AT,
        }
        for key, value in updates.items():
            if record.get(key) != value:
                record[key] = value
                changed += 1

    for sig, status in VERSIONED_TEXTS.items():
        matches = by_signature.get(sig, [])
        if len(matches) != 1:
            raise RuntimeError(f"Expected one versioned record for {sig!r}, found {len(matches)}")
        record = matches[0]
        updates = {
            "status": status,
            "statusSource": official_link(record, source),
            "statusVerifiedAt": VERIFIED_AT,
        }
        for key, value in updates.items():
            if record.get(key) != value:
                record[key] = value
                changed += 1

    for filename, relationship in FILE_RELATIONSHIPS.items():
        record = by_file.get(filename)
        if not record:
            raise RuntimeError(f"Missing relationship record {filename!r}")
        updates = {**relationship, "relationshipVerifiedAt": VERIFIED_AT}
        for key, value in updates.items():
            if record.get(key) != value:
                record[key] = value
                changed += 1

    return changed


def compact_json_bytes(data) -> bytes:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def update_derived_metadata(
    public_records: list[dict], facets: dict, manifest: dict
) -> tuple[int, int, bytes, bytes]:
    """Keep derived filters and integrity metadata aligned with documents.json."""
    status_counts = Counter(record.get("status") or "final" for record in public_records)
    expected_statuses = [
        {"value": status, "count": count}
        for status, count in status_counts.most_common()
    ]

    facet_changes = 0
    if facets.get("statuses") != expected_statuses:
        facets["statuses"] = expected_statuses
        facet_changes += 1

    public_payload = compact_json_bytes(public_records)
    facets_payload = compact_json_bytes(facets)
    expected_files = {
        "documents.json": {
            "sha": hashlib.sha256(public_payload).hexdigest()[:16],
            "bytes": len(public_payload),
        },
        "facets.json": {
            "sha": hashlib.sha256(facets_payload).hexdigest()[:16],
            "bytes": len(facets_payload),
        },
    }

    manifest_changes = 0
    files = manifest.setdefault("files", {})
    for filename, expected in expected_files.items():
        if files.get(filename) != expected:
            files[filename] = expected
            manifest_changes += 1

    return facet_changes, manifest_changes, public_payload, facets_payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Fail if applying the audit would change files")
    args = parser.parse_args()

    source_records = json.loads(SOURCE_PATH.read_text(encoding="utf-8"))
    public_records = json.loads(PUBLIC_PATH.read_text(encoding="utf-8"))
    facets = json.loads(FACETS_PATH.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    source_changes = apply(source_records, source=True)
    public_changes = apply(public_records, source=False)
    facet_changes, manifest_changes, public_payload, facets_payload = update_derived_metadata(
        public_records, facets, manifest
    )

    if args.check:
        if source_changes or public_changes or facet_changes or manifest_changes:
            print(
                "status audit drift: "
                f"source={source_changes}, public={public_changes}, "
                f"facets={facet_changes}, manifest={manifest_changes}"
            )
            return 1
        print("status audit: source, public, facets, and manifest are in sync")
        return 0

    SOURCE_PATH.write_text(json.dumps(source_records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    PUBLIC_PATH.write_bytes(public_payload)
    FACETS_PATH.write_bytes(facets_payload)
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        "applied status audit: "
        f"source={source_changes}, public={public_changes}, "
        f"facets={facet_changes}, manifest={manifest_changes}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
