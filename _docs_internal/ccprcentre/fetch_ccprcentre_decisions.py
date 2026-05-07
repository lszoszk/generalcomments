#!/usr/bin/env python3
"""Fetch CCPR Centre jurisprudence metadata for QC against our JUR corpus.

The CCPR Centre database exposes metadata in two places:

* /database-decisions?page_num=N listing pages: case name, symbol, date,
  articles, keywords, document links, outcome.
* /decision/<id> detail pages: communication number, submission/adoption
  dates, and template-specific article/issue/full-text sections.

This scraper keeps both views, then adds conservative normalised fields useful
for matching against docs/jur/documents.json later. It does not download the
decision documents themselves; it records their URLs and language labels.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import hashlib
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://ccprcentre.org"
LISTING_URL = f"{BASE_URL}/database-decisions"
USER_AGENT = (
    "UN Human Rights Database research crawler "
    "(metadata QA; contact via https://github.com/lszoszk/generalcomments)"
)
LANG_LABELS = {
    "en": "en",
    "eng": "en",
    "english": "en",
    "fr": "fr",
    "fra": "fr",
    "french": "fr",
    "es": "es",
    "sp": "es",
    "spa": "es",
    "spanish": "es",
    "ru": "ru",
    "rus": "ru",
    "russian": "ru",
    "ar": "ar",
    "arabic": "ar",
    "zh": "zh",
    "chi": "zh",
    "chinese": "zh",
}
OUTCOME_MAP = {
    "merits - violation": "merits_violation",
    "merits - no violation": "merits_no_violation",
    "inadmissible": "inadmissible",
    "discontinuance": "discontinuance",
    "discontinued": "discontinuance",
    "admissible": "admissible",
}
NO_VALUE = {
    "",
    "no articles",
    "no keywords",
    "no documents",
}


def clean_text(value: str | None) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", value.replace("\xa0", " ")).strip()


def clean_item(value: str | None) -> str:
    value = clean_text(value)
    value = re.sub(r"\s*,\s*$", "", value)
    return value.strip()


def iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def normalize_date(value: str | None) -> str | None:
    value = clean_text(value)
    if not value:
        return None
    value = value.replace("/", "-").replace(".", "-")
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", value)
    if not m:
        return None
    y, mo, d = (int(x) for x in m.groups())
    try:
        return dt.date(y, mo, d).isoformat()
    except ValueError:
        return None


def normalize_outcome(value: str | None) -> str | None:
    value = clean_text(value)
    return OUTCOME_MAP.get(value.lower()) or (re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_") if value else None)


def normalize_case_name(value: str | None) -> str:
    value = clean_text(value)
    value = re.sub(r"\s+v\.\s*", " v. ", value, flags=re.I)
    value = re.sub(r"\s+v\s+", " v. ", value, flags=re.I)
    value = value.replace(" v.", " v.")
    return value


def respondent_from_case_name(value: str | None) -> str | None:
    value = normalize_case_name(value)
    m = re.search(r"\bv\.?\s*(.+)$", value, flags=re.I)
    if not m:
        return None
    state = clean_text(m.group(1))
    state = re.sub(r"\s*\([^)]*session[^)]*\)\s*$", "", state, flags=re.I)
    return state or None


def communication_numbers(symbol: str | None) -> list[str]:
    symbol = clean_text(symbol)
    if not symbol:
        return []
    # Handles "4483/2023", "324:1988", and grouped strings such as
    # "1461,1462,1476&1477/2006" by keeping the raw atomic forms visible.
    out: list[str] = []
    for token in re.findall(r"\d{1,5}(?::|/)\d{4}", symbol):
        out.append(token.replace(":", "/"))
    if out:
        return sorted(set(out), key=out.index)
    m = re.search(r"/D/([^,\s]+)", symbol, flags=re.I)
    return [m.group(1).replace(":", "/")] if m else []


def article_number(value: str) -> str | None:
    m = re.search(r"Article\s+(.+)$", value, flags=re.I)
    return clean_item(m.group(1)) if m else None


def parse_article_items(items: list[str]) -> list[dict[str, str]]:
    parsed = []
    for item in items:
        number = article_number(item)
        parsed.append({"raw": item, "article": number or item})
    return parsed


def split_cell_items(cell) -> list[str]:
    if cell is None:
        return []
    values: list[str] = []
    nodes = cell.find_all(["p", "li", "span"])
    if not nodes:
        nodes = [cell]
    for node in nodes:
        text = clean_item(node.get_text(" ", strip=True))
        if not text or text.lower() in NO_VALUE:
            continue
        # CCPR Centre often renders one <p> per item, but some cells collapse
        # comma-separated values into one text node. Split only on comma+space;
        # keep article subparagraphs like "14.3 (b)" intact.
        parts = [clean_item(p) for p in re.split(r",\s+(?=(?:Article\b|[A-Z]))", text)]
        values.extend([p for p in parts if p and p.lower() not in NO_VALUE])
    return sorted(set(values), key=values.index)


def url_ext(url: str) -> str | None:
    path = urlparse(url).path
    m = re.search(r"\.([A-Za-z0-9]{2,5})$", path)
    return m.group(1).lower() if m else None


def link_language(label: str, url: str) -> str | None:
    tokens = re.findall(r"[A-Za-z]+", label)
    for token in reversed(tokens):
        lang = LANG_LABELS.get(token.lower())
        if lang:
            return lang
    path = urlparse(url).path.lower()
    for token, lang in LANG_LABELS.items():
        if re.search(rf"[_\-.]({re.escape(token)})[_\-.]", path):
            return lang
    return None


def parse_links(container, *, kind: str | None = None, source: str) -> list[dict[str, Any]]:
    links = []
    if container is None:
        return links
    for a in container.find_all("a", href=True):
        href = urljoin(BASE_URL, a["href"])
        label = clean_text(a.get_text(" ", strip=True)).replace("link ", "").strip()
        if not label:
            label = clean_text(a.get("title")) or href
        links.append(
            {
                "kind": kind or infer_document_kind(container.get_text(" ", strip=True)),
                "label": label,
                "language": link_language(label, href),
                "url": href,
                "extension": url_ext(href),
                "source": source,
            }
        )
    return links


def infer_document_kind(text: str) -> str | None:
    text_l = clean_text(text).lower()
    if "case-law brief" in text_l or "case law brief" in text_l:
        return "Case-law brief"
    if "full case" in text_l or "full text" in text_l:
        return "Full case"
    if "digest" in text_l:
        return "Case digest"
    return None


def dedupe_links(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[tuple[str, str | None], dict[str, Any]] = {}
    for group in groups:
        for link in group:
            key = (link.get("url") or "", link.get("language"))
            if not key[0]:
                continue
            if key in seen:
                sources = set(str(seen[key].get("source", "")).split("+"))
                sources.add(str(link.get("source", "")))
                seen[key]["source"] = "+".join(sorted(s for s in sources if s))
                if not seen[key].get("kind") and link.get("kind"):
                    seen[key]["kind"] = link["kind"]
            else:
                seen[key] = dict(link)
    return list(seen.values())


def fetch(url: str, *, timeout: int = 30, retries: int = 3, pause: float = 0.2) -> str:
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            response = requests.get(url, headers=headers, timeout=timeout)
            response.raise_for_status()
            return response.text
        except Exception as exc:  # pragma: no cover - exercised by live network
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(pause * (attempt + 1))
    raise RuntimeError(f"Failed to fetch {url}: {last_error}")


def parse_listing_page(html: str, page_num: int) -> tuple[list[dict[str, Any]], str | None]:
    soup = BeautifulSoup(html, "html.parser")
    last_update = None
    update_node = soup.find(string=re.compile(r"Last update:", re.I))
    if update_node:
        last_update = clean_text(update_node).replace("Last update:", "").strip()

    table = soup.select_one("table.decisions_table")
    if table is None:
        return [], last_update
    rows = table.find_all("tr", recursive=False)
    records: list[dict[str, Any]] = []
    seq = 0
    i = 0
    while i < len(rows):
        row = rows[i]
        if "country-heading" not in (row.get("class") or []):
            i += 1
            continue
        seq += 1
        data_row = rows[i + 2] if i + 2 < len(rows) else None
        header_tds = row.find_all("td", recursive=False)
        data_tds = data_row.find_all("td", recursive=False) if data_row else []

        title_node = row.select_one(".board-name")
        title = normalize_case_name(title_node.get_text(" ", strip=True) if title_node else "")
        decision_link = title_node.find_parent("a") if title_node else None
        decision_url = urljoin(BASE_URL, decision_link["href"]) if decision_link and decision_link.get("href") else None
        ccprcentre_id = None
        if decision_url:
            m = re.search(r"/decision/(\d+)", decision_url)
            ccprcentre_id = m.group(1) if m else None

        symbol = None
        if len(header_tds) >= 2:
            lines = [clean_text(s) for s in header_tds[1].stripped_strings]
            symbol_candidates = [line for line in lines if line and line != title]
            symbol = symbol_candidates[-1] if symbol_candidates else None

        country_code = None
        flag = row.select_one(".flag-icon-background")
        if flag:
            for cls in flag.get("class") or []:
                m = re.match(r"flag-icon-([a-z]{2})$", cls)
                if m:
                    country_code = m.group(1).upper()
                    break

        date_raw = clean_text(header_tds[2].get_text(" ", strip=True)) if len(header_tds) >= 3 else None
        articles = split_cell_items(data_tds[0]) if len(data_tds) >= 1 else []
        keywords = split_cell_items(data_tds[1]) if len(data_tds) >= 2 else []
        documents = parse_links(data_tds[2], source="listing") if len(data_tds) >= 3 else []
        outcome_raw = clean_text(data_tds[3].get_text(" ", strip=True)) if len(data_tds) >= 4 else None

        flags = []
        if not title:
            flags.append("missing_case_name")
        if not symbol:
            flags.append("missing_symbol")
        if not documents:
            flags.append("missing_document_link")
        if not outcome_raw:
            flags.append("missing_outcome")

        records.append(
            {
                "ccprcentre_id": ccprcentre_id,
                "ccprcentre_url": decision_url,
                "source_page": page_num,
                "source_page_url": f"{LISTING_URL}?page_num={page_num}",
                "source_page_sequence": seq,
                "case_name": title,
                "respondent_state_from_title": respondent_from_case_name(title),
                "country_code": country_code,
                "symbol": symbol,
                "communication_numbers": communication_numbers(symbol),
                "listing_date_raw": date_raw,
                "decision_date": normalize_date(date_raw),
                "articles": parse_article_items(articles),
                "keywords": keywords,
                "documents": documents,
                "outcome_raw": outcome_raw,
                "outcome": normalize_outcome(outcome_raw),
                "detail": None,
                "quality_flags": flags,
            }
        )
        i += 3
    return records, last_update


def parse_new_detail(soup: BeautifulSoup) -> dict[str, Any]:
    title = normalize_case_name(soup.select_one(".specific-decision-title h1").get_text(" ", strip=True))
    desc = soup.select_one(".specific-decision-title-desc")
    desc_lines = [clean_text(s) for s in desc.stripped_strings] if desc else []
    symbol = next((line for line in desc_lines if line.startswith("CCPR/")), None)
    submission_date = None
    adopted_date = None
    comm_label = None
    comm_number = None
    for idx, line in enumerate(desc_lines):
        if line.lower() == "communication" and idx + 1 < len(desc_lines):
            comm_label = desc_lines[idx]
            comm_number = desc_lines[idx + 1].replace("No.", "").strip()
        elif line.lower().startswith("submission:"):
            submission_date = normalize_date(line.split(":", 1)[1])
        elif line.lower().startswith("view adopted:"):
            adopted_date = normalize_date(line.split(":", 1)[1])

    sections: dict[str, Any] = {}
    for block in soup.select(".col.s12.m12.l12"):
        strong = block.find("strong")
        if not strong:
            continue
        label = clean_text(strong.get_text(" ", strip=True))
        if not label:
            continue
        if label.lower() in {"full text", "full case"}:
            sections[label] = parse_links(block, kind="Full case", source="detail")
        else:
            items = [clean_item(li.get_text(" ", strip=True)) for li in block.find_all("li")]
            sections[label] = [item for item in items if item]

    return {
        "template": "new_digest",
        "case_name": title,
        "symbol": symbol,
        "communication_label": comm_label,
        "communication_number": comm_number,
        "submission_date": submission_date,
        "view_adopted_date": adopted_date,
        "decision_year_date": None,
        "sections": sections,
    }


def parse_legacy_detail(soup: BeautifulSoup) -> dict[str, Any]:
    table = soup.select_one("#single_decision")
    title_node = table.find_previous("h2") if table else None
    title = normalize_case_name(title_node.get_text(" ", strip=True) if title_node else "")
    symbol = None
    decision_date = None
    sections: dict[str, Any] = {}
    if table:
        text = table.get_text("\n", strip=True)
        m = re.search(r"Reference:\s*\n?\s*([A-Z]+/[^\n]+)", text)
        if m:
            symbol = clean_text(m.group(1))
        m = re.search(r"Decision Year:\s*\n?\s*([0-9./-]{8,10})", text)
        if m:
            decision_date = normalize_date(m.group(1))
        for row in table.find_all("tr"):
            row_text = clean_text(row.get_text(" ", strip=True))
            if "Related Articles:" in row_text:
                items = [clean_item(span.get_text(" ", strip=True)) for span in row.select(".order")]
                sections["Relevant Articles"] = [item for item in items if item]
            elif "Keywords:" in row_text:
                items = [clean_item(span.get_text(" ", strip=True)) for span in row.select(".order")]
                sections["Keywords"] = [item for item in items if item]
            elif "Full Case:" in row_text or "Full Text:" in row_text:
                sections["Full Text"] = parse_links(row, kind="Full case", source="detail")

    return {
        "template": "legacy_table",
        "case_name": title,
        "symbol": symbol,
        "communication_label": None,
        "communication_number": None,
        "submission_date": None,
        "view_adopted_date": None,
        "decision_year_date": decision_date,
        "sections": sections,
    }


def parse_detail_page(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    if soup.select_one(".specific-decision-title"):
        return parse_new_detail(soup)
    if soup.select_one("#single_decision"):
        return parse_legacy_detail(soup)
    return {"template": "unknown", "sections": {}}


def enrich_with_detail(record: dict[str, Any]) -> dict[str, Any]:
    if not record.get("ccprcentre_url"):
        record["quality_flags"].append("missing_detail_url")
        return record
    try:
        html = fetch(record["ccprcentre_url"])
        detail = parse_detail_page(html)
        record["detail"] = detail
        detail_links: list[dict[str, Any]] = []
        for value in (detail.get("sections") or {}).values():
            if isinstance(value, list) and value and isinstance(value[0], dict):
                detail_links.extend(value)
        record["documents"] = dedupe_links(record.get("documents", []), detail_links)
        flags = record["quality_flags"]
        if detail.get("template") == "unknown":
            flags.append("detail_template_unknown")
        if detail.get("case_name") and normalize_case_name(detail["case_name"]) != normalize_case_name(record.get("case_name")):
            flags.append("listing_detail_case_name_diff")
        if detail.get("symbol") and record.get("symbol") and clean_text(detail["symbol"]) != clean_text(record["symbol"]):
            flags.append("listing_detail_symbol_diff")
        detail_date = detail.get("view_adopted_date") or detail.get("decision_year_date")
        if detail_date and record.get("decision_date") and detail_date != record["decision_date"]:
            flags.append("listing_detail_decision_date_diff")
        if not record["documents"]:
            flags.append("missing_document_link_after_detail")
    except Exception as exc:  # pragma: no cover - exercised by live network
        record["detail"] = {"error": str(exc)}
        record["quality_flags"].append("detail_fetch_error")
    return record


def discover_page_count(first_html: str, fallback: int) -> int:
    pages = [int(x) for x in re.findall(r"page_num=(\d+)", first_html)]
    return max(pages) if pages else fallback


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pages", type=int, default=18, help="Number of listing pages to crawl (default: 18).")
    parser.add_argument("--discover-pages", action="store_true", help="Use max page_num links from page 1 if present.")
    parser.add_argument("--workers", type=int, default=6, help="Concurrent detail page workers.")
    parser.add_argument("--no-detail", action="store_true", help="Only fetch listing pages.")
    parser.add_argument(
        "--from-listing",
        help="Read an existing listing-only JSON and only enrich its records with detail pages.",
    )
    parser.add_argument(
        "--out",
        default="_docs_internal/ccprcentre/ccprcentre_decisions.json",
        help="Output JSON path.",
    )
    args = parser.parse_args(argv)

    started = iso_now()
    if args.from_listing:
        listing = json.loads(Path(args.from_listing).read_text(encoding="utf-8"))
        records = listing.get("records", [])
        meta = listing.get("metadata", {})
        last_update = meta.get("last_update_text")
        page_errors = list(meta.get("page_errors") or [])
        html_hashes = dict(meta.get("listing_html_sha256_by_page") or {})
        page_count = len(meta.get("pages_requested") or []) or args.pages
        print(f"loaded listing: {len(records)} records from {args.from_listing}", file=sys.stderr)
    else:
        first_html = fetch(f"{LISTING_URL}?page_num=1")
        page_count = discover_page_count(first_html, args.pages) if args.discover_pages else args.pages

        records = []
        last_update = None
        page_errors = []
        html_hashes = {"1": sha256_text(first_html)}
        for page_num in range(1, page_count + 1):
            try:
                html = first_html if page_num == 1 else fetch(f"{LISTING_URL}?page_num={page_num}")
                html_hashes[str(page_num)] = sha256_text(html)
                page_records, page_last_update = parse_listing_page(html, page_num)
                if page_last_update:
                    last_update = page_last_update
                records.extend(page_records)
                print(f"page {page_num:02d}: {len(page_records)} records", file=sys.stderr)
            except Exception as exc:
                page_errors.append({"page": page_num, "error": str(exc)})

    if not args.no_detail:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            future_map = {pool.submit(enrich_with_detail, dict(record)): idx for idx, record in enumerate(records)}
            enriched: list[dict[str, Any] | None] = [None] * len(records)
            done_count = 0
            for future in concurrent.futures.as_completed(future_map):
                idx = future_map[future]
                enriched[idx] = future.result()
                done_count += 1
                if done_count % 50 == 0 or done_count == len(records):
                    print(f"details: {done_count}/{len(records)}", file=sys.stderr)
            records = [r for r in enriched if r is not None]

    flag_counts = Counter(flag for record in records for flag in record.get("quality_flags", []))
    outcome_counts = Counter(record.get("outcome") or "unknown" for record in records)
    document_ext_counts = Counter(
        link.get("extension") or "unknown"
        for record in records
        for link in record.get("documents", [])
    )
    detail_template_counts = Counter(
        (record.get("detail") or {}).get("template") or "not_fetched"
        for record in records
    )

    out = {
        "metadata": {
            "schema": "ccprcentre-decisions-v1",
            "source": "CCPR Centre — Database and Case Law Briefs",
            "source_url": LISTING_URL,
            "last_update_text": last_update,
            "crawled_at": started,
            "completed_at": iso_now(),
            "pages_requested": list(range(1, page_count + 1)),
            "records": len(records),
            "detail_pages_fetched": 0 if args.no_detail else len(records),
            "page_errors": page_errors,
            "listing_html_sha256_by_page": html_hashes,
            "counts": {
                "outcomes": dict(sorted(outcome_counts.items())),
                "detail_templates": dict(sorted(detail_template_counts.items())),
                "quality_flags": dict(sorted(flag_counts.items())),
                "document_extensions": dict(sorted(document_ext_counts.items())),
            },
        },
        "records": records,
    }
    write_json(Path(args.out), out)
    print(f"wrote {args.out} ({len(records)} records)", file=sys.stderr)
    return 0 if not page_errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
