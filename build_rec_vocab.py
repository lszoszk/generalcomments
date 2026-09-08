#!/usr/bin/env python3
"""Vocabularies for the Recommendations (UHRI) scope → docs/rec/vocab.json.

The recommendations themselves are never shipped: the browser queries the
uhri-dataset-api on the project VM. What the interface needs before the
first request — the list of issuing mechanisms, States, themes, affected
persons, SDG labels and record types, each with its whole-dataset count,
plus the year histogram — is read once from the UHRI SQLite mirror on the VM
and stored here. Re-run after the UHRI export is refreshed on the server.

    python3 build_rec_vocab.py            # ssh to the VM, rebuild, register in the manifest
    python3 build_rec_vocab.py --from DIR # assemble from rec_*.json files already downloaded
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"
OUT = DOCS / "rec" / "vocab.json"
HOST = "amuvmuser@150.254.115.204"
DB = "~/uhri/data/uhri-export.sqlite3"

QUERIES = {
    "themes": "SELECT value, COUNT(*) AS count FROM record_theme GROUP BY value ORDER BY count DESC",
    "affectedPersons": "SELECT value, COUNT(*) AS count FROM record_affected_person GROUP BY value ORDER BY count DESC",
    "sdgs": "SELECT value, COUNT(*) AS count FROM record_sdg GROUP BY value ORDER BY count DESC",
    "bodies": "SELECT body AS value, COUNT(*) AS count FROM records WHERE body IS NOT NULL AND TRIM(body) <> '' GROUP BY body ORDER BY count DESC",
    "countries": "SELECT value, COUNT(*) AS count FROM record_country GROUP BY value ORDER BY count DESC",
    "types": "SELECT annotation_type AS value, COUNT(*) AS count FROM records GROUP BY annotation_type ORDER BY count DESC",
    "years": "SELECT publication_year AS year, COUNT(*) AS count FROM records WHERE publication_year IS NOT NULL GROUP BY publication_year ORDER BY year",
    "meta": "SELECT COUNT(*) AS total, COUNT(DISTINCT symbol) AS documents, MAX(publication_date) AS last_published FROM records",
}


def fetch_remote() -> dict[str, list]:
    out = {}
    for key, sql in QUERIES.items():
        cmd = ["ssh", "-o", "BatchMode=yes", HOST, f"sqlite3 -readonly -json {DB} \"{sql}\""]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if res.returncode != 0:
            sys.exit(f"[rec-vocab] {key}: ssh/sqlite failed: {res.stderr.strip()}")
        out[key] = json.loads(res.stdout or "[]")
    return out


def load_local(directory: Path) -> dict[str, list]:
    names = {"affectedPersons": "groups"}
    out = {}
    for key in QUERIES:
        f = directory / f"rec_{names.get(key, key)}.json"
        out[key] = json.loads(f.read_text(encoding="utf-8") or "[]")
    return out


def strip_dash(value: str) -> str:
    return str(value or "").lstrip("-").strip()


def assemble(raw: dict[str, list]) -> dict:
    def clean(rows, fold_types=False):
        merged: dict[str, int] = {}
        for r in rows:
            v = strip_dash(r.get("value"))
            if fold_types:
                # UHRI's annotation type column carries a few stray UUIDs and blanks.
                if "recommend" in v.lower():
                    v = "Recommendations"
                elif "observ" in v.lower() or "concern" in v.lower():
                    v = "Concerns/Observations"
                else:
                    v = "Others"
            if not v:
                continue
            merged[v] = merged.get(v, 0) + int(r.get("count") or 0)
        return [{"value": v, "count": c} for v, c in sorted(merged.items(), key=lambda kv: (-kv[1], kv[0]))]

    meta = (raw.get("meta") or [{}])[0]
    years = [{"year": int(r["year"]), "count": int(r["count"])} for r in raw["years"] if r.get("year")]
    return {
        "builtAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "OHCHR Universal Human Rights Index export, uhri-dataset-api mirror on the project server",
        "total": int(meta.get("total") or 0),
        "documents": int(meta.get("documents") or 0),
        "lastPublished": str(meta.get("last_published") or "")[:10],
        "years": {"min": years[0]["year"] if years else None, "max": years[-1]["year"] if years else None, "histogram": years},
        "bodies": clean(raw["bodies"]),
        "countries": clean(raw["countries"]),
        "types": clean(raw["types"], fold_types=True),
        "themes": clean(raw["themes"]),
        "affectedPersons": clean(raw["affectedPersons"]),
        "sdgs": clean(raw["sdgs"]),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="src", help="directory with rec_*.json dumps instead of ssh")
    args = ap.parse_args()
    raw = load_local(Path(args.src)) if args.src else fetch_remote()
    payload = assemble(raw)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    mp = DOCS / "manifest.json"
    text = mp.read_text(encoding="utf-8")
    manifest = json.loads(text)
    manifest.setdefault("files", {})["rec/vocab.json"] = {"sha": hashlib.sha256(OUT.read_bytes()).hexdigest()[:16], "bytes": OUT.stat().st_size}
    mp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + ("\n" if text.endswith("\n") else ""), encoding="utf-8")
    print(f"[rec-vocab] {OUT.relative_to(ROOT)} · {OUT.stat().st_size / 1024:.0f} KB · {payload['total']:,} records · "
          f"{len(payload['bodies'])} mechanisms · {len(payload['countries'])} States · {len(payload['themes'])} themes · "
          f"{len(payload['affectedPersons'])} groups · {len(payload['sdgs'])} SDG labels · newest {payload['lastPublished']}")


if __name__ == "__main__":
    main()
