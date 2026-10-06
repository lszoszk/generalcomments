#!/usr/bin/env python3
"""Prerender one static HTML page per UNHRDB document (optionally a Markdown twin).

The app is a single page: every document lives behind JavaScript and a
canonical link that points to the home page, so search engines index one page
and AI crawlers (which do not run JavaScript) see none of the 323,065
paragraphs. This script writes, for every document,

    <out>/d/<docId>/index.html   full text with ¶ anchors (#p12), footnotes,
                                 headings, metadata, JSON-LD, cites / cited by
    <out>/d/<docId>.md           (with --markdown) the same text as Markdown

plus <out>/d/index.html (the collection index that links them all) and
<out>/sitemap-docs.xml. Pages are plain HTML with one shared stylesheet and
no JavaScript; each links to the paragraph in the app.

    python3 build_static_pages.py --out /tmp/unhrdb-static            # all
    python3 build_static_pages.py --out /tmp/x --doc a-hrc-58-58 --doc ccpr-c-gc-36
"""
from __future__ import annotations

import argparse
import glob
import gzip
import html
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"
SITE = "https://lszoszk.github.io/generalcomments/"
DOI = "https://doi.org/10.5281/zenodo.10495719"
MARKER = re.compile(r"\[\[fn:(\d+)\]\]")

COLLECTION = {
    "gc": ("General Comments and Recommendations", "General Comment or Recommendation of a UN treaty body: the committee's authoritative interpretation of its treaty."),
    "jur": ("Treaty-body jurisprudence", "Decision of a UN treaty body on an individual communication: the treaty applied to one case."),
    "sp": ("Special Procedures reports", "Thematic report of a UN Special Procedures mandate: the independent expert opinion of a mandate-holder (soft law)."),
}


def esc(s) -> str:
    return html.escape(str(s or ""), quote=True)


def load_corpus():
    docs = {d["docId"]: d for d in json.load(open(DOCS / "documents.json"))}
    for d in json.load(open(DOCS / "jur" / "documents-lite.json")):
        docs.setdefault(d["docId"], d)
    paras = defaultdict(list)
    for p in json.load(open(DOCS / "corpus.json")):
        paras[p["docId"]].append(p)
    for f in sorted(glob.glob(str(DOCS / "sp" / "shards" / "*.json"))):
        for p in json.load(open(f)):
            paras[p["docId"]].append(p)
    for f in sorted(glob.glob(str(DOCS / "jur" / "shards" / "*.json"))):
        shard = json.load(open(f))           # {shardId, documents: [docId…], paragraphs: [...]}
        for p in shard.get("paragraphs") or []:
            paras[p["docId"]].append(p)
    for ps in paras.values():
        ps.sort(key=lambda p: p.get("idx", 0))
    cites = json.load(open(DOCS / "citations" / "index.json"))
    return docs, paras, cites


def para_label(p) -> str:
    """The paragraph number as printed (jurisprudence ids can be 4.2, OP1-3…)."""
    for k in ("paragraphId", "n"):
        v = p.get(k)
        if v not in (None, "", 0):
            return str(v)
    return str(p.get("idx"))


def anchor(p) -> str:
    return "p" + re.sub(r"[^0-9A-Za-z.-]+", "-", para_label(p))


def text_html(p) -> tuple[str, list]:
    """Paragraph text with footnote markers as links; returns (html, notes used)."""
    notes = {int(f["n"]): f.get("resolvedText") or f.get("text") or "" for f in (p.get("footnotes") or []) if isinstance(f, dict) and "n" in f}
    used = []
    out, last = [], 0
    t = str(p.get("text") or "")
    a = anchor(p)
    for m in MARKER.finditer(t):
        out.append(esc(t[last:m.start()]))
        n = int(m.group(1))
        if n in notes:
            out.append(f'<sup class="fn"><a href="#{a}-fn{n}" id="{a}-r{n}">{n}</a></sup>')
            used.append((n, notes[n]))
        last = m.end()
    out.append(esc(t[last:]))
    body = "".join(out).replace("\n", "<br>")
    # the number printed beside the paragraph is not repeated at its start
    body = re.sub(rf"^{re.escape(para_label(p).rstrip('.'))}\.\s+", "", body)
    return body, used


def doc_meta(d):
    kind = d.get("type", "gc")
    symbol = d.get("signature") or d.get("symbol") or d["docId"]
    name = d.get("name") or d.get("title") or symbol
    date = d.get("adoptionDate") or (str(d.get("year")) if d.get("year") else "")
    body = d.get("committee") or d.get("treaty") or ""
    return kind, symbol, name, date, body


def oscola(d, kind, symbol, name, date, body) -> str:
    """Citation stem in the form the app's OSCOLA export uses: a Special
    Procedures report is cited by the organ it went to (from the symbol), never
    by the mandate or its holder."""
    if kind == "sp":
        organ = "UNHRC" if symbol.startswith("A/HRC/") else "UNGA" if symbol.startswith("A/") else "UNCHR" if symbol.startswith("E/CN.4/") else body
        return f"{organ} ‘{name}’ ({date}) UN Doc {symbol}"
    if kind == "jur":
        return f"{name} ({body}, {date}) UN Doc {symbol}"
    return f"{body} ‘{name}’ ({date}) UN Doc {symbol}"


def provenance(d) -> str:
    """The reader's text-quality banner, for Special Procedures reports whose
    text does not come from the Word file on UN Documents."""
    if d.get("type") != "sp" or d.get("textSource") == "documents.un.org docx":
        return ""
    if d.get("textSource") == "documents.un.org pdf (layout)":
        msg = ("From PDF: no Word file exists for this report, so its text was re-cut from the PDF layout. "
               "In such reports about one paragraph in nine may still show a slip, often OCR in older scans.")
    else:
        msg = ("PDF, unreviewed: this report still carries its original PDF extraction. About one paragraph "
               "in six may be cut short or have a heading or footnote run into it.")
    return f'<aside class="note warn">{esc(msg)} We are working on it; check quotations against the official text.</aside>'


def json_ld(d, url, n_paras):
    kind, symbol, name, date, body = doc_meta(d)
    t = "Report" if kind == "sp" else "CreativeWork"
    genre = {"gc": "General Comment / General Recommendation", "jur": "Treaty-body decision on an individual communication", "sp": "Special Procedures thematic report"}[kind]
    ld = {
        "@context": "https://schema.org",
        "@type": t,
        "@id": url,
        "url": url,
        "name": name,
        "identifier": symbol,
        "genre": genre,
        "inLanguage": "en",
        "author": {"@type": "Organization", "name": body} if body else None,
        "datePublished": str(d.get("year") or ""),
        "sameAs": d.get("link"),
        "isPartOf": {"@type": "Dataset", "@id": SITE + "#dataset", "name": "UN Human Rights Database (UNHRDB)", "identifier": DOI},
        "numberOfItems": n_paras,
    }
    return json.dumps({k: v for k, v in ld.items() if v}, ensure_ascii=False)


def render(d, ps, cites, docs) -> tuple[str, str]:
    kind, symbol, name, date, body = doc_meta(d)
    url = f"{SITE}d/{d['docId']}/"
    coll, character = COLLECTION.get(kind, COLLECTION["gc"])
    first = next((MARKER.sub("", p["text"]) for p in ps if len(p.get("text", "")) > 80), "")
    desc = f"{symbol} · {body} · {date}. " + re.sub(r"\s+", " ", first)[:220]
    app = f"{SITE}?p={ps[0]['id']}" if ps else SITE
    sub = []
    if kind == "sp" and d.get("mandate"):
        sub.append(f"Mandate-holder: {esc(d['mandate'])}")
    if kind == "jur" and d.get("country"):
        sub.append(f"State party: {esc(d['country'])}")
    if kind == "jur" and d.get("outcome"):
        sub.append(f"Outcome: {esc(str(d['outcome']).replace('_', ' '))}")

    # body
    rows, prev = [], []
    toc = []
    md = [f"# {name}", "", f"{symbol} · {body} · {date}", "", f"Source: {d.get('link') or ''} · UNHRDB: {url}", "", f"> {character}", ""]
    for p in ps:
        sec = p.get("section") or []
        if isinstance(sec, str):
            sec = [sec]
        common = 0
        while common < min(len(sec), len(prev)) and sec[common] == prev[common]:
            common += 1
        for depth in range(common, len(sec)):
            hid = "s-" + re.sub(r"[^0-9a-z]+", "-", sec[depth].lower()).strip("-")[:60]
            rows.append(f'<h{min(depth + 2, 5)} id="{esc(hid)}">{esc(sec[depth])}</h{min(depth + 2, 5)}>')
            toc.append((depth, sec[depth], hid))
            md += ["#" * min(depth + 2, 5) + " " + sec[depth], ""]
        prev = sec
        a = anchor(p)
        label = para_label(p)
        txt, used = text_html(p)
        notes = "".join(f'<li id="{a}-fn{n}" value="{n}">{esc(t)} <a href="#{a}-r{n}" aria-label="back">↩</a></li>' for n, t in used)
        rows.append(
            f'<section class="para" id="{esc(a)}"><a class="pn" href="#{esc(a)}" title="Link to this paragraph">¶{esc(label)}</a>'
            f'<div class="pt"><p>{txt}</p>{f"<ol class=notes>{notes}</ol>" if notes else ""}</div></section>')
        plain = MARKER.sub(lambda m: f"[^{m.group(1)}]", p.get("text") or "")
        md.append(f"**¶{label}** {plain}")
        for n, t in used:
            md.append(f"[^{n}]: {t}")
        md.append("")

    c = cites.get(d["docId"]) or {}

    def cite_list(items):
        lis = []
        for other, count, *_ in items[:40]:
            o = docs.get(other)
            if not o:
                continue
            lis.append(f'<li><a href="../{esc(other)}/">{esc(o.get("signature") or o.get("symbol") or other)}</a> {esc(o.get("nameShort") or o.get("name") or "")}</li>')
        return "".join(lis)

    cited_by, cites_out = cite_list(c.get("citedBy") or []), cite_list(c.get("cites") or [])
    toc_html = "".join(f'<li class="d{dep}"><a href="#{esc(h)}">{esc(t)}</a></li>' for dep, t, h in toc)
    citation = esc(oscola(d, kind, symbol, name, date, body))
    page = f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(symbol)} — {esc(d.get('nameShort') or name)} · UNHRDB</title>
<meta name="description" content="{esc(desc)}">
<link rel="canonical" href="{url}">
<meta property="og:type" content="article"><meta property="og:title" content="{esc(symbol)} — {esc(name)}">
<meta property="og:url" content="{url}"><meta property="og:site_name" content="UN Human Rights Database (UNHRDB)">
<link rel="stylesheet" href="../static.css">
<script>/* cookie-free page counter (GoatCounter); not for Do-Not-Track or automation */
if(navigator.doNotTrack!=="1"&&window.doNotTrack!=="1"&&!navigator.webdriver&&location.hostname.indexOf("github.io")>-1){{var g=document.createElement("script");g.async=true;g.src="https://gc.zgo.at/count.js";g.dataset.goatcounter="https://lszoszk.goatcounter.com/count";document.head.appendChild(g)}}</script>
<script type="application/ld+json">{json_ld(d, url, len(ps))}</script>
</head><body>
<header class="top"><a class="brand" href="{SITE}">UNHRDB</a> <span class="crumbs">› <a href="../#{kind}">{esc(coll)}</a> › {esc(body)}</span></header>
<main>
<p class="sym">{esc(symbol)}</p>
<h1>{esc(name)}</h1>
<p class="meta">{esc(body)} · {esc(date)}{' · ' + ' · '.join(sub) if sub else ''} · {len(ps)} paragraphs</p>
<p class="actions"><a href="{esc(app)}">Search and read in the UNHRDB app</a> · <a href="{esc(d.get('link') or '')}">Official text (UN Documents)</a></p>
<aside class="note">{esc(character)} Cite as: {citation}, para [n].</aside>
{provenance(d)}
{f'<nav class="toc"><h2>Contents</h2><ol>{toc_html}</ol></nav>' if toc else ''}
<article>
{''.join(rows)}
</article>
{f'<section class="links"><h2>Cited in UNHRDB by</h2><ul>{cited_by}</ul></section>' if cited_by else ''}
{f'<section class="links"><h2>Cites</h2><ul>{cites_out}</ul></section>' if cites_out else ''}
</main>
<footer>Text: United Nations, reproduced from {esc(symbol)} as published; check the official text before relying on it. Database: Szoszkiewicz &amp; Kowalska, <a href="{DOI}">UNHRDB — UN Human Rights Database</a> (Zenodo), CC BY-NC-SA 4.0. Page views are counted with cookie-free <a href="https://www.goatcounter.com/">GoatCounter</a>.</footer>
</body></html>
"""
    return page, "\n".join(md) + "\n"


CSS = """:root{--ink:#1d1b18;--ink2:#5a554d;--paper:#faf7f2;--rule:#e2dccf;--accent:#8a2131}
@media (prefers-color-scheme:dark){:root{--ink:#ece6da;--ink2:#a8a092;--paper:#1b1916;--rule:#3a352d;--accent:#e08a96}}
body{margin:0;background:var(--paper);color:var(--ink);font:17px/1.65 "Source Serif 4",Georgia,serif}
a{color:var(--accent)}
.top{padding:12px 20px;border-bottom:1px solid var(--rule);font:13px/1.4 ui-monospace,Menlo,monospace}
.brand{font-weight:700;text-decoration:none}
main{max-width:760px;margin:0 auto;padding:24px 20px 60px}
.sym{font:13px ui-monospace,Menlo,monospace;color:var(--ink2);margin:0}
h1{font-size:28px;line-height:1.25;margin:.2em 0 .3em}
.meta,.actions{color:var(--ink2);font-size:14px;margin:.3em 0}
.note.warn{border-left-color:#b7791f}
.note{border-left:3px solid var(--accent);padding:8px 12px;margin:16px 0;font-size:14px;color:var(--ink2);background:rgba(0,0,0,.03)}
.toc{font-size:14px;border:1px solid var(--rule);padding:8px 16px;margin:16px 0}.toc ol{list-style:none;padding:0}.toc .d1{padding-left:1em}.toc .d2{padding-left:2em}.toc .d3{padding-left:3em}
h2,h3,h4,h5{font-family:ui-monospace,Menlo,monospace;font-size:13px;letter-spacing:.06em;text-transform:uppercase;color:var(--accent);margin:2em 0 .6em}
h3,h4,h5{text-transform:none;letter-spacing:0;font-size:14px}
.para{display:grid;grid-template-columns:52px 1fr;gap:8px;margin:0 0 1em}
.pn{font:13px ui-monospace,Menlo,monospace;color:var(--ink2);text-decoration:none;padding-top:4px}
.pt p{margin:0}.fn a{text-decoration:none;font-size:.75em}
.notes{font-size:13px;color:var(--ink2);margin:.4em 0 0;padding-left:1.4em}
.links{font-size:14px}.links ul{padding-left:1.2em}
footer{max-width:760px;margin:0 auto;padding:20px;border-top:1px solid var(--rule);font-size:12px;color:var(--ink2)}
@media (max-width:600px){.para{grid-template-columns:1fr}.pn{padding:0}}
"""


def index_page(docs, have):
    groups = defaultdict(lambda: defaultdict(list))
    for doc_id in have:
        d = docs[doc_id]
        kind, symbol, name, date, body = doc_meta(d)
        groups[kind][body].append((d.get("year") or 0, symbol, d.get("nameShort") or name, doc_id))
    parts = []
    for kind in ("gc", "jur", "sp"):
        if kind not in groups:
            continue
        parts.append(f'<h2 id="{kind}">{esc(COLLECTION[kind][0])}</h2>')
        for body in sorted(groups[kind]):
            items = sorted(groups[kind][body], reverse=True)
            lis = "".join(f'<li><a href="{esc(i)}/">{esc(s)}</a> {esc(n)} ({y})</li>' for y, s, n, i in items)
            parts.append(f"<h3>{esc(body)} ({len(items)})</h3><ul>{lis}</ul>")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>All documents · UN Human Rights Database (UNHRDB)</title>
<meta name="description" content="Every document in the UN Human Rights Database: Treaty Body General Comments, treaty-body decisions and Special Procedures reports, each with its full paragraph-level text.">
<link rel="canonical" href="{SITE}d/"><link rel="stylesheet" href="static.css"></head><body>
<header class="top"><a class="brand" href="{SITE}">UNHRDB</a> › All documents</header><main><h1>All documents</h1>{''.join(parts)}</main></body></html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--doc", action="append")
    ap.add_argument("--markdown", action="store_true", help="also write a .md twin per document")
    args = ap.parse_args()
    out = Path(args.out) / "d"
    out.mkdir(parents=True, exist_ok=True)
    docs, paras, cites = load_corpus()
    targets = args.doc or [d for d in docs if paras.get(d)]
    sizes = {"html": 0, "md": 0, "html_gz": 0}
    for doc_id in targets:
        page, md = render(docs[doc_id], paras[doc_id], cites, docs)
        (out / doc_id).mkdir(exist_ok=True)
        (out / doc_id / "index.html").write_text(page, encoding="utf-8")
        if args.markdown:
            (out / f"{doc_id}.md").write_text(md, encoding="utf-8")
        sizes["html"] += len(page.encode())
        sizes["md"] += len(md.encode())
        sizes["html_gz"] += len(gzip.compress(page.encode(), 6))
    (out / "static.css").write_text(CSS, encoding="utf-8")
    (out / "index.html").write_text(index_page(docs, targets), encoding="utf-8")
    sm = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    sm += [f"  <url><loc>{SITE}d/{i}/</loc></url>" for i in targets]
    sm.append("</urlset>")
    (Path(args.out) / "sitemap-docs.xml").write_text("\n".join(sm) + "\n", encoding="utf-8")
    mb = lambda b: f"{b / 1e6:.1f} MB"
    print(f"{len(targets)} documents · HTML {mb(sizes['html'])} (gzip {mb(sizes['html_gz'])})"
          + (f" · Markdown {mb(sizes['md'])}" if args.markdown else ""))
    if not args.doc and len(targets) != sum(1 for d in docs if paras.get(d)):
        raise SystemExit("not every document with paragraphs got a page")


if __name__ == "__main__":
    main()
