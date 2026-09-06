#!/usr/bin/env python3
"""Nearest-neighbour "related paragraphs" for the General Comments corpus.

Uses the BGE-large (1024-dim) paragraph vectors built for the Ask/RAG work
(`gc_vectors_local.json.gz`, rows of {paraId, vector}) and writes, for every
GC paragraph that has a vector and still exists in docs/corpus.json, the five
most similar paragraphs FROM OTHER DOCUMENTS (cosine similarity), so a reader
of CRC GC 25 ¶ 76 sees where CRC GC 20 or CCPR GC 16 say the same thing.

Only the General Comments have vectors today; the file says so in its header
and the UI labels the panel accordingly.

Usage: python3 build_related.py [--vectors PATH] [--k 5] [--min-score 0.55]
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"
DEFAULT_VECTORS = Path("/Users/lszoszk/Desktop/gc-rag-local-share/out/gc_vectors_local.json.gz")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vectors", default=str(DEFAULT_VECTORS))
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--min-score", type=float, default=0.55)
    args = ap.parse_args()

    corpus = json.load(open(DOCS / "corpus.json", encoding="utf-8"))
    paras = corpus if isinstance(corpus, list) else corpus["paragraphs"]
    live = {p["id"]: p for p in paras}
    doc_of = {pid: pid.rsplit("-", 1)[0] for pid in live}

    with gzip.open(args.vectors, "rt", encoding="utf-8") as fh:
        blob = json.load(fh)
    rows = [r for r in blob["rows"] if r["paraId"] in live]
    ids = [r["paraId"] for r in rows]
    X = np.asarray([r["vector"] for r in rows], dtype=np.float32)
    X /= np.linalg.norm(X, axis=1, keepdims=True) + 1e-9
    print(f"[related] vectors {len(blob['rows'])} · matching live paragraphs {len(ids)} / {len(live)} "
          f"({100 * len(ids) / len(live):.1f}% coverage) · model {blob.get('model')}")

    docs = np.asarray([doc_of[i] for i in ids])
    out = {}
    B = 512
    for s in range(0, len(ids), B):
        sims = X[s:s + B] @ X.T                                   # (B, N)
        same_doc = docs[s:s + B][:, None] == docs[None, :]
        sims[same_doc] = -1.0                                     # other documents only
        top = np.argpartition(-sims, args.k, axis=1)[:, :args.k]
        for i, row in enumerate(top):
            pid = ids[s + i]
            cand = sorted(((ids[j], float(sims[i, j])) for j in row), key=lambda t: -t[1])
            keep = [[j, round(sc, 3)] for j, sc in cand if sc >= args.min_score]
            if keep:
                out[pid] = keep
    payload = {
        "version": datetime.now(timezone.utc).strftime("%Y%m%d"),
        "builtAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scope": "gc",
        "model": blob.get("model"),
        "k": args.k,
        "minScore": args.min_score,
        "method": "cosine similarity of BGE-large paragraph embeddings; neighbours from other documents only",
        "counts": {"paragraphsWithVectors": len(ids), "paragraphsInCorpus": len(live), "paragraphsWithRelated": len(out)},
        "related": out,
    }
    dest = DOCS / "related"
    dest.mkdir(parents=True, exist_ok=True)
    f = dest / "gc.json"
    f.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    mp = DOCS / "manifest.json"
    raw = mp.read_text(encoding="utf-8")
    manifest = json.loads(raw)
    manifest.setdefault("files", {})["related/gc.json"] = {"sha": hashlib.sha256(f.read_bytes()).hexdigest()[:16], "bytes": f.stat().st_size}
    mp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + ("\n" if raw.endswith("\n") else ""), encoding="utf-8")
    print(f"[related] wrote {f.relative_to(ROOT)} · {f.stat().st_size / 1024:.0f} KB · {len(out)} paragraphs with related · manifest registered")
    # A few samples for a sanity read.
    import random
    random.seed(3)
    for pid in random.sample(list(out), 3):
        print(f"   {pid}: {live[pid]['text'][:90]!r}")
        for j, sc in out[pid][:2]:
            print(f"      {sc:.2f} {j}: {live[j]['text'][:90]!r}")


if __name__ == "__main__":
    main()
