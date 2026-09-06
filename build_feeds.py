#!/usr/bin/env python3
"""Atom feeds and a changelog page for the UNHRDB corpus.

Every document record carries `firstAddedAt` (the day it entered the
database). This script turns that into current-awareness surfaces:

  docs/feeds/all.xml                 every collection, newest first
  docs/feeds/gc.xml, sp.xml, jur.xml one per collection
  docs/feeds/body-<slug>.xml         one per treaty body (GC + JUR) and per
                                     Special Procedures mandate
  docs/feeds/index.json              the list of feeds with counts
  docs/changelog.html                additions grouped by day, newest first

Feeds carry the latest 100 entries. Run after every corpus change:
    python3 build_feeds.py
"""
from __future__ import annotations

import html
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"
SITE = "https://lszoszk.github.io/generalcomments/"
FEED_LIMIT = 100

LONG = {
    "CCPR": "Human Rights Committee",
    "CESCR": "Committee on Economic, Social and Cultural Rights",
    "CERD": "Committee on the Elimination of Racial Discrimination",
    "CEDAW": "Committee on the Elimination of Discrimination against Women",
    "CAT": "Committee against Torture",
    "CAT-OP": "Subcommittee on Prevention of Torture",
    "CRC": "Committee on the Rights of the Child",
    "CMW": "Committee on Migrant Workers",
    "CRPD": "Committee on the Rights of Persons with Disabilities",
    "CED": "Committee on Enforced Disappearances",
}
KIND = {"gc": "General Comment / Recommendation", "jur": "Treaty-body decision", "sp": "Special Procedures report"}


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")


def title_of(d: dict) -> str:
    if d.get("type") == "jur":
        for key in ("caseNameDisplay", "caseName", "title", "nameShort", "name"):
            v = d.get(key)
            if v and str(v).strip().lower() != "english title":
                return str(v)
        return f"{d.get('signature') or d['docId']}" + (f" · {d['country']}" if d.get("country") else "")
    return d.get("name") or d.get("nameShort") or d["docId"]


def added_on(d: dict) -> str:
    return str(d.get("firstAddedAt") or "")[:10]


def entry_summary(d: dict) -> str:
    bits = [KIND.get(d.get("type"), ""), d.get("signature") or ""]
    com = d.get("committee") or d.get("treaty") or ""
    if com:
        bits.append(LONG.get(com, com))
    if d.get("mandate") and d["mandate"] != "Working Group":
        bits.append(d["mandate"])
    if d.get("country"):
        bits.append(d["country"])
    year = d.get("adoptionYear") or d.get("year")
    if year:
        bits.append(str(year))
    summary = " · ".join(b for b in bits if b)
    if d.get("abstract"):
        summary += " — " + str(d["abstract"])[:400]
    return summary


def doc_url(d: dict) -> str:
    return f"{SITE}#documents/{d['docId']}"


def atom(feed_id: str, title: str, entries: list[dict], updated: str) -> str:
    out = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<feed xmlns="http://www.w3.org/2005/Atom">',
        f"  <title>{html.escape(title)}</title>",
        f'  <link href="{SITE}" />',
        f'  <link rel="self" href="{SITE}feeds/{feed_id}.xml" />',
        f"  <id>{SITE}feeds/{feed_id}</id>",
        f"  <updated>{updated}</updated>",
        "  <author><name>UN Human Rights Database</name></author>",
        "  <subtitle>Documents newly added to the paragraph-level corpus of UN treaty-body general comments, "
        "individual-communication decisions and Special Procedures thematic reports.</subtitle>",
    ]
    for d in entries:
        day = added_on(d) or "1970-01-01"
        out += [
            "  <entry>",
            f"    <title>{html.escape(title_of(d))}</title>",
            f'    <link href="{doc_url(d)}" />',
            f"    <id>{doc_url(d)}</id>",
            f"    <updated>{day}T00:00:00Z</updated>",
            f"    <published>{day}T00:00:00Z</published>",
            f'    <category term="{html.escape(d.get("type") or "")}" />',
            f"    <summary>{html.escape(entry_summary(d))}</summary>",
            "  </entry>",
        ]
    out.append("</feed>")
    return "\n".join(out) + "\n"


def changelog_html(docs: list[dict], feeds: list[dict]) -> str:
    by_day: dict[str, list[dict]] = defaultdict(list)
    for d in docs:
        by_day[added_on(d)].append(d)
    days = sorted((k for k in by_day if k), reverse=True)
    sections = []
    for day in days:
        rows = sorted(by_day[day], key=lambda d: (d.get("type") or "", d.get("signature") or ""))
        items = "".join(
            f'<li><span class="k k-{html.escape(d.get("type") or "")}">{html.escape((d.get("type") or "").upper())}</span> '
            f'<a href="{html.escape(doc_url(d))}">{html.escape(title_of(d))}</a> '
            f'<span class="sig">{html.escape(d.get("signature") or "")}</span></li>'
            for d in rows
        )
        label = datetime.strptime(day, "%Y-%m-%d").strftime("%-d %B %Y")
        sections.append(f'<section><h2 id="d-{day}">{label} <span class="n">{len(rows)}</span></h2><ul>{items}</ul></section>')
    feed_links = " · ".join(f'<a href="feeds/{f["id"]}.xml">{html.escape(f["title"])}</a>' for f in feeds[:4])
    built = datetime.now(timezone.utc).strftime("%-d %B %Y")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>What is new · UN Human Rights Database</title>
<link rel="icon" type="image/svg+xml" href="assets/favicon.svg" />
<link rel="alternate" type="application/atom+xml" title="UNHRDB — new documents" href="feeds/all.xml" />
<link rel="stylesheet" href="assets/tokens.css" />
<style>
  body {{ margin: 0; background: var(--paper, #f6f4ee); color: var(--ink, #1f1d1b); font-family: var(--body, "Source Serif 4", Georgia, serif); }}
  main {{ max-width: 860px; margin: 0 auto; padding: 40px 24px 80px; }}
  h1 {{ font-family: var(--display, Spectral, Georgia, serif); font-size: 34px; margin: 0 0 6px; }}
  .lede {{ color: var(--ink-2, #4a4642); margin: 0 0 8px; }}
  .feeds {{ font-size: 14px; color: var(--ink-3, #7a746d); margin-bottom: 32px; }}
  h2 {{ font-family: var(--display, Spectral, Georgia, serif); font-size: 20px; margin: 28px 0 8px; border-bottom: 1px solid var(--rule, #d8d3c8); padding-bottom: 4px; }}
  h2 .n {{ font-family: var(--mono, monospace); font-size: 12px; color: var(--ink-3, #7a746d); margin-left: 8px; }}
  ul {{ list-style: none; padding: 0; margin: 0; }}
  li {{ padding: 5px 0; font-size: 15px; line-height: 1.4; }}
  .k {{ font-family: var(--mono, monospace); font-size: 10px; letter-spacing: .06em; padding: 1px 6px; border-radius: 999px; background: var(--paper-2, #ebe8e0); margin-right: 6px; }}
  .sig {{ font-family: var(--mono, monospace); font-size: 12px; color: var(--ink-3, #7a746d); margin-left: 6px; }}
  a {{ color: var(--garnet, #7a1f2b); text-decoration-thickness: 1px; }}
</style>
</head>
<body>
<main>
<h1>What is new</h1>
<p class="lede">Every document added to the UN Human Rights Database, by the day it entered the corpus. {len(docs):,} documents; last addition {days[0] if days else "—"}; page built {built}.</p>
<p class="feeds">Subscribe: {feed_links} · <a href="feeds/index.json">all feeds</a> · <a href="./">back to the database</a></p>
{"".join(sections)}
</main>
</body>
</html>
"""


def main():
    docs = load(DOCS / "documents.json") + load(DOCS / "jur" / "documents-lite.json")
    docs = [d for d in docs if added_on(d)]
    docs.sort(key=lambda d: (added_on(d), d.get("signature") or ""), reverse=True)
    out = DOCS / "feeds"
    out.mkdir(parents=True, exist_ok=True)
    for stale in out.glob("*.xml"):
        stale.unlink()

    feeds = []

    def emit(feed_id: str, title: str, subset: list[dict]):
        if not subset:
            return
        updated = added_on(subset[0]) + "T00:00:00Z"
        (out / f"{feed_id}.xml").write_text(atom(feed_id, title, subset[:FEED_LIMIT], updated), encoding="utf-8")
        feeds.append({"id": feed_id, "title": title, "documents": len(subset), "latest": added_on(subset[0])})

    emit("all", "UN Human Rights Database — new documents", docs)
    emit("gc", "UNHRDB — new General Comments and Recommendations", [d for d in docs if d.get("type") == "gc"])
    emit("jur", "UNHRDB — new treaty-body decisions", [d for d in docs if d.get("type") == "jur"])
    emit("sp", "UNHRDB — new Special Procedures reports", [d for d in docs if d.get("type") == "sp"])
    bodies = defaultdict(list)
    for d in docs:
        com = d.get("committee") or d.get("treaty")
        if com:
            bodies[com].append(d)
    for com, subset in sorted(bodies.items()):
        emit(f"body-{slug(com)}", f"UNHRDB — {LONG.get(com, com)}", subset)

    (out / "index.json").write_text(json.dumps({"builtAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                                "feeds": feeds}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (DOCS / "changelog.html").write_text(changelog_html(docs, feeds), encoding="utf-8")
    print(f"[feeds] {len(feeds)} feeds · {len(docs)} documents · latest {added_on(docs[0])} · changelog.html written")


if __name__ == "__main__":
    main()
