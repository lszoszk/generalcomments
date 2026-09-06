#!/usr/bin/env python3
"""Build the document-level citation graph of the UNHRDB corpus.

Reads the static frontend data (docs/documents.json, docs/corpus.json, the SP
and JUR shards) and finds, in every paragraph and its footnotes, references
to OTHER documents of the corpus:

  1. UN document symbols ("CCPR/C/GC/34", "A/HRC/63/27", "E/C.12/GC/21",
     "CRC/C/GC/23, CMW/C/GC/4"), resolved through every signature the
     catalogue knows (signature, symbol, ohchrSymbol, alternativeSignatures);
  2. "general comment No. 34" / "general recommendation No. 19", resolved
     against the committee named in the preceding 160 characters, else the
     citing document's own committee (never guessed for SP reports);
  3. "communication No. 2828/2016", resolved within the committee the same
     way (case numbers are only unique per committee).

Writes
  docs/citations/graph.json   every edge {from, to, paragraphs, via[]} — the
                              bulk download for citation-network research
  docs/citations/graph.csv    the same as from,to,paragraphs
  docs/citations/index.json   per-document adjacency for the reader:
                              {docId: {cites: [[to, n, firstPara]], citedBy: […]}}

Usage: python3 build_citation_graph.py [--out docs/citations] [--samples 20]
"""
from __future__ import annotations

import argparse
import csv
import glob
import hashlib
import json
import random
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"

COMMITTEE_NAMES = [
    ("Human Rights Committee", "CCPR"),
    ("Committee on Economic, Social and Cultural Rights", "CESCR"),
    ("Committee on the Elimination of Racial Discrimination", "CERD"),
    ("Committee on the Elimination of Discrimination against Women", "CEDAW"),
    ("Committee against Torture", "CAT"),
    ("Subcommittee on Prevention of Torture", "CAT-OP"),
    ("Committee on the Rights of the Child", "CRC"),
    ("Committee on the Protection of the Rights of All Migrant Workers", "CMW"),
    ("Committee on Migrant Workers", "CMW"),
    ("Committee on the Rights of Persons with Disabilities", "CRPD"),
    ("Committee on Enforced Disappearances", "CED"),
]
COMMITTEE_RE = re.compile(
    "(" + "|".join(re.escape(n) for n, _ in COMMITTEE_NAMES) + r"|\b(?:CCPR|CESCR|CERD|CEDAW|CAT|CRC|CMW|CRPD|CED)\b)",
    re.I,
)
COMMITTEE_CODE = {n.lower(): c for n, c in COMMITTEE_NAMES}

SYMBOL_RE = re.compile(
    r"\b(?:CCPR|CESCR|CERD|CEDAW|CAT|CRC|CMW|CRPD|CED|HRI|E/C\.12|E/CN\.4|A/HRC|A/RES|A/C\.3|A)/[A-Za-z0-9./()\-]*[A-Za-z0-9)]"
)
GC_RE = re.compile(r"\bgeneral\s+(comment|recommendation)s?\s+(?:No\.?\s*)?(\d{1,3})\b", re.I)
COMM_RE = re.compile(r"\bcommunications?\s+No\.?\s*(\d{1,5})\s*/\s*(\d{4})\b", re.I)
LOOKBACK = 160


def norm_symbol(s: str) -> str:
    s = re.sub(r"\s+", "", str(s or "")).upper()
    s = s.rstrip(".,;:)")
    return s


def load_json(path: Path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def build_lookups(docs: list[dict]):
    by_sig: dict[str, str] = {}
    ambiguous: set[str] = set()

    def add(sig, doc_id):
        n = norm_symbol(sig)
        if not n:
            return
        if n in by_sig and by_sig[n] != doc_id:
            ambiguous.add(n)
            return
        by_sig[n] = doc_id

    for d in docs:
        for key in ("signature", "symbol", "ohchrSymbol"):
            if d.get(key):
                add(d[key], d["docId"])
        for alt in d.get("alternativeSignatures") or []:
            add(alt, d["docId"])
        # Joint signatures ("CRC/C/GC/23, CMW/C/GC/4" / "CEDAW/C/GC/31/Rev.1–CRC/C/GC/18/Rev.1")
        sig = d.get("signature") or ""
        for part in re.split(r"\s*[,–—]\s*", sig):
            if part and part != sig:
                add(part, d["docId"])
    for n in ambiguous:
        by_sig.pop(n, None)
    # Aliases without a /Rev.N or /Corr.N tail, when that leaves one candidate.
    tails = defaultdict(set)
    for n, doc_id in list(by_sig.items()):
        base = re.sub(r"/(REV|CORR)\.\d+$", "", n)
        if base != n:
            tails[base].add(doc_id)
    for base, ids in tails.items():
        if base not in by_sig and len(ids) == 1:
            by_sig[base] = next(iter(ids))

    gc_by_num: dict[tuple[str, int], str] = {}
    gc_dupes: set[tuple[str, int]] = set()
    for d in docs:
        if d.get("type") != "gc":
            continue
        committees = d.get("committees") or ([d["committee"]] if d.get("committee") else [])
        short = d.get("nameShort") or ""
        nums = [int(x) for x in re.findall(r"\bG[CR]\s?(\d{1,3})\b", short)]
        if not nums:
            m = re.search(r"general\s+(?:comment|recommendation)\s+No\.?\s*(\d{1,3})", d.get("name") or "", re.I)
            nums = [int(m.group(1))] if m else []
        for com, num in zip(committees, nums):
            key = (com, num)
            if key in gc_by_num and gc_by_num[key] != d["docId"]:
                gc_dupes.add(key)
            else:
                gc_by_num[key] = d["docId"]
    for key in gc_dupes:
        gc_by_num.pop(key, None)

    comm_by_num: dict[tuple[str, str], str] = {}
    comm_dupes: set[tuple[str, str]] = set()
    for d in docs:
        if d.get("type") != "jur":
            continue
        com = d.get("committee") or d.get("treaty")
        numbers = set()
        for key in ("communicationNumbers", "jurisCommunicationNumbers"):
            for v in d.get(key) or []:
                m = re.search(r"(\d{1,5})\s*/\s*(\d{4})", str(v))
                if m:
                    numbers.add(f"{m.group(1)}/{m.group(2)}")
        m = re.search(r"/D/([\d\-&,\s]+)/(\d{4})", d.get("signature") or "")
        if m:
            for n in re.findall(r"\d+", m.group(1)):
                numbers.add(f"{n}/{m.group(2)}")
        for n in numbers:
            key = (com, n)
            if key in comm_by_num and comm_by_num[key] != d["docId"]:
                comm_dupes.add(key)
            else:
                comm_by_num[key] = d["docId"]
    for key in comm_dupes:
        comm_by_num.pop(key, None)
    return by_sig, gc_by_num, comm_by_num


def committee_in_context(text: str, end: int) -> str | None:
    window = text[max(0, end - LOOKBACK):end]
    last = None
    for m in COMMITTEE_RE.finditer(window):
        last = m.group(1)
    if not last:
        return None
    return COMMITTEE_CODE.get(last.lower(), last.upper())


def iter_paragraphs():
    corpus = load_json(DOCS / "corpus.json")
    for p in (corpus if isinstance(corpus, list) else corpus["paragraphs"]):
        yield "gc", p
    for path in sorted(glob.glob(str(DOCS / "sp" / "shards" / "*.json"))):
        for p in load_json(Path(path)):
            yield "sp", p
    for path in sorted(glob.glob(str(DOCS / "jur" / "shards" / "*.json"))):
        shard = load_json(Path(path))
        for p in shard.get("paragraphs", []):
            yield "jur", p


def paragraph_text(p: dict) -> str:
    parts = [p.get("text") or ""]
    for f in p.get("footnotes") or []:
        if isinstance(f, dict):
            parts.append(f.get("text") or "")
        elif isinstance(f, str):
            parts.append(f)
    return "\n".join(parts)


def find_references(text: str, citing_doc: dict, lookups) -> list[tuple[str, str, str]]:
    """Return (target docId, method, snippet) for every reference found."""
    by_sig, gc_by_num, comm_by_num = lookups
    found = []
    own_committee = citing_doc.get("committee") if citing_doc.get("type") in ("gc", "jur") else None
    for m in SYMBOL_RE.finditer(text):
        n = norm_symbol(m.group(0))
        target = by_sig.get(n)
        if not target:
            # "CCPR/C/GC/34," style tails and page refs like "CRC/C/GC/25, para. 3"
            n2 = re.sub(r"[.,;:)]+$", "", n)
            target = by_sig.get(n2)
        if target:
            found.append((target, "symbol", text[max(0, m.start() - 60):m.end() + 20]))
    for m in GC_RE.finditer(text):
        kind = m.group(1).lower()
        num = int(m.group(2))
        com = committee_in_context(text, m.start()) or own_committee
        if not com:
            continue
        # "general recommendation" belongs to CEDAW/CERD; "general comment" to the rest
        target = gc_by_num.get((com, num))
        if target:
            found.append((target, f"gc-{kind}", text[max(0, m.start() - 80):m.end() + 20]))
    for m in COMM_RE.finditer(text):
        num = f"{m.group(1)}/{m.group(2)}"
        com = committee_in_context(text, m.start()) or own_committee
        if not com:
            continue
        target = comm_by_num.get((com, num))
        if target:
            found.append((target, "communication", text[max(0, m.start() - 80):m.end() + 20]))
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(DOCS / "citations"))
    ap.add_argument("--samples", type=int, default=20)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    docs = load_json(DOCS / "documents.json") + load_json(DOCS / "jur" / "documents-lite.json")
    by_id = {d["docId"]: d for d in docs}
    alt_of = {}
    for d in docs:
        for a in d.get("alternativeIds") or []:
            alt_of[a] = d["docId"]
    lookups = build_lookups(docs)
    print(f"[graph] {len(docs)} documents · {len(lookups[0])} symbol aliases · "
          f"{len(lookups[1])} GC numbers · {len(lookups[2])} communication numbers")

    edges: dict[tuple[str, str], dict] = {}
    methods = Counter()
    samples = []
    n_paras = 0
    citing_paras = set()
    for _, p in iter_paragraphs():
        n_paras += 1
        doc_id = p.get("docId") or re.sub(r"-\d{4}$", "", p["id"])
        doc = by_id.get(doc_id)
        if not doc:
            continue
        text = paragraph_text(p)
        if "/" not in text and "No" not in text and "no." not in text:
            continue
        seen_here = set()
        for target, method, snippet in find_references(text, doc, lookups):
            target = alt_of.get(target, target)
            if target == doc_id or target in (doc.get("alternativeIds") or []):
                continue
            key = (doc_id, target)
            e = edges.setdefault(key, {"paragraphs": 0, "via": []})
            if target not in seen_here:
                seen_here.add(target)
                e["paragraphs"] += 1
                if len(e["via"]) < 5:
                    e["via"].append(p["id"])
                citing_paras.add(p["id"])
                methods[method] += 1
                samples.append((doc_id, target, method, snippet.replace("\n", " ")))

    cited_by = defaultdict(list)
    cites = defaultdict(list)
    for (src, dst), e in edges.items():
        cites[src].append([dst, e["paragraphs"], e["via"][0]])
        cited_by[dst].append([src, e["paragraphs"], e["via"][0]])
    for m in (cites, cited_by):
        for k in m:
            m[k].sort(key=lambda r: (-r[1], r[0]))

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    built = datetime.now(timezone.utc).isoformat(timespec="seconds")
    version = datetime.now(timezone.utc).strftime("%Y%m%d")
    graph = {
        "version": version,
        "builtAt": built,
        "method": ("Document-level references found in paragraph bodies and footnotes: UN symbols resolved "
                   "against the catalogue; 'general comment/recommendation No. N' and 'communication No. N/YYYY' "
                   "resolved within the committee named in the preceding text, else the citing document's own "
                   "committee (never guessed for Special Procedures reports). Self-references dropped. "
                   "'paragraphs' counts citing paragraphs; 'via' lists up to five of them."),
        "counts": {
            "documents": len(by_id),
            "documentsCiting": len(cites),
            "documentsCited": len(cited_by),
            "edges": len(edges),
            "citingParagraphs": len(citing_paras),
            "paragraphsScanned": n_paras,
        },
        "edges": [{"from": s, "to": t, "paragraphs": e["paragraphs"], "via": e["via"]}
                  for (s, t), e in sorted(edges.items(), key=lambda kv: (-kv[1]["paragraphs"], kv[0]))],
    }
    (out / "graph.json").write_text(json.dumps(graph, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    with open(out / "graph.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["from", "to", "paragraphs"])
        for e in graph["edges"]:
            w.writerow([e["from"], e["to"], e["paragraphs"]])
    index = {"version": version, "builtAt": built,
             "docs": {d: {"cites": cites.get(d, []), "citedBy": cited_by.get(d, [])}
                      for d in sorted(set(cites) | set(cited_by))}}
    (out / "index.json").write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    for name in ("graph.json", "graph.csv", "index.json"):
        f = out / name
        print(f"[graph] wrote {f.relative_to(ROOT)} · {f.stat().st_size / 1024:.0f} KB · "
              f"sha256 {hashlib.sha256(f.read_bytes()).hexdigest()[:16]}")
    # Register the files in docs/manifest.json so the frontend can cache-bust
    # them by hash (same 16-hex convention as corpus/documents/facets).
    manifest_path = DOCS / "manifest.json"
    if manifest_path.exists() and out == DOCS / "citations":
        raw = manifest_path.read_text(encoding="utf-8")
        manifest = json.loads(raw)
        for name in ("graph.json", "index.json"):
            f = out / name
            manifest.setdefault("files", {})[f"citations/{name}"] = {
                "sha": hashlib.sha256(f.read_bytes()).hexdigest()[:16],
                "bytes": f.stat().st_size,
            }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + ("\n" if raw.endswith("\n") else ""), encoding="utf-8")
        print("[graph] docs/manifest.json: citations/* registered")
    c = graph["counts"]
    print(f"[graph] edges {c['edges']} · citing docs {c['documentsCiting']} · cited docs {c['documentsCited']} · "
          f"citing paragraphs {c['citingParagraphs']} · methods {dict(methods)}")
    top = sorted(cited_by.items(), key=lambda kv: -sum(r[1] for r in kv[1]))[:10]
    print("[graph] most cited:")
    for d, rows in top:
        doc = by_id[d]
        print(f"   {sum(r[1] for r in rows):5d} ¶ from {len(rows):4d} docs · {doc.get('signature')} · {(doc.get('nameShort') or doc.get('name') or '')[:60]}")
    if args.samples:
        random.seed(args.seed)
        print(f"[graph] {args.samples} random samples (from → to · method · context):")
        for src, dst, method, snippet in random.sample(samples, min(args.samples, len(samples))):
            print(f"   {src} → {dst} · {method}\n      …{snippet[:170]}…")


if __name__ == "__main__":
    main()
