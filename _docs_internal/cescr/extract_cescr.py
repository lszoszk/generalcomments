#!/usr/bin/env python3
"""High-quality extraction of CESCR (Committee on Economic, Social and
Cultural Rights) Optional Protocol jurisprudence from the official UN
docx publications on documents.un.org.

WHAT WE EXTRACT
---------------
For each E/C.12/<sess>/D/<n>/<yr> decision symbol:

  1. The native DOCX from documents.un.org (docx-first per the SP
     footnote work — Word's <w:footnoteReference> gives us exact
     marker positions; PDFs flatten them and pdftotext routinely
     mangles placement).

  2. Per-paragraph rows:
       text           — body text with [[fn:N]] markers in place
       footnotes      — array of {n, text} for fns referenced in this ¶
       n              — paragraph number ("1", "2", …) when present
       section_path   — stack of section headings, e.g.
                        ["Annex", "Views of the Committee …", "Facts
                         and legal issues"]
       style          — Word style name ("SingleTxt", "H1", etc.) for
                        downstream renderer hints

  3. Doc-level metadata harvested from the front matter (the
     unstyled key/value paragraphs UN treaty-body decisions use):
       country, submitted_by, alleged_victims, state_party,
       communication_date, subject_matter, substantive_issues,
       procedural_issues, covenant_articles, op_articles,
       views_adoption_date, outcome.

OUTPUT
------
_docs_internal/cescr/cescr.json — one record per docId:

    {
      "<docId>": {
        "symbol": "E/C.12/55/D/2/2014",
        "metadata": { … },
        "paragraphs": [ {n, text, footnotes, section_path, style}, … ]
      },
      …
    }

USAGE
-----
    python3 _docs_internal/cescr/extract_cescr.py --discover     # one-off
    python3 _docs_internal/cescr/extract_cescr.py                # full run
    python3 _docs_internal/cescr/extract_cescr.py --doc <id>     # single
    python3 _docs_internal/cescr/extract_cescr.py --no-fetch     # cache only
"""
from __future__ import annotations

import argparse
import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

# ───────────────────────────────────────────────────  paths
REPO = Path(__file__).resolve().parent.parent.parent
WORK = REPO / "_docs_internal" / "cescr"
DOCX_DIR = WORK / "docx"
CASE_LIST = WORK / "case_list.json"          # discovery output
OUT_JSON = WORK / "cescr.json"               # extraction output

# ───────────────────────────────────────────────────  http
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

# UN treaty-body docx styles (observed in CESCR decisions):
#   HCh   top-level chapter heading ("Communication No. X/YYYY", "Annex")
#   H1    first-level subheading
#   H23   second/third-level subheading
#   H4    fourth-level subheading
#   SingleTxt   body paragraph
HEADING_STYLES = {"HCh": 0, "H1": 1, "H23": 2, "H4": 3, "Heading1": 1, "Heading2": 2}

# Front-matter labels we collect into doc metadata:
FRONT_MATTER_LABELS = {
    "Subject:": "subject_matter",
    "Substantive issues:": "substantive_issues",
    "Procedural issues:": "procedural_issues",
    "Articles of the Covenant:": "covenant_articles",
    "Article of the Optional Protocol:": "op_articles",
    "Articles of the Optional Protocol:": "op_articles",
    "Submitted by:": "submitted_by",
    "Alleged victim:": "alleged_victims",
    "Alleged victims:": "alleged_victims",
    "State party:": "state_party",
    "Date of communication:": "communication_date",
}


# ─────────────────────────────────────────  symbol → docId helpers
def symbol_to_docid(sym: str) -> str:
    """E/C.12/55/D/2/2014  →  e-c-12-55-d-2-2014"""
    return re.sub(r"[^a-z0-9]+", "-", sym.lower()).strip("-")


# ─────────────────────────────────────────  discovery (paginated TBSearch)
def discover_cescr_decisions() -> dict:
    """Iterate every page of the OHCHR Treaty Body Database TBSearch
    for CESCR jurisprudence, collecting symbol → metadata."""
    URL = (
        "https://tbinternet.ohchr.org/_layouts/15/treatybodyexternal/"
        "TBSearch.aspx?Lang=en&TreatyID=9&DocTypeID=17"
    )
    H_FORM = {**HEADERS, "Content-Type": "application/x-www-form-urlencoded"}

    def fetch(form=None):
        if form:
            body = urllib.parse.urlencode(form).encode()
            req = urllib.request.Request(URL, data=body, headers=H_FORM)
        else:
            req = urllib.request.Request(URL, headers=HEADERS)
        with urllib.request.urlopen(req, context=CTX, timeout=20) as r:
            return r.read().decode("utf-8", errors="replace")

    def parse_rows(html):
        out = []
        for tr in re.findall(r"<tr[^>]*>([\s\S]*?)</tr>", html):
            if "E/C.12" not in tr or "Download.aspx" not in tr:
                continue
            cells = re.findall(r"<td[^>]*>([\s\S]*?)</td>", tr)
            if len(cells) < 6:
                continue
            title = re.sub(r"<[^>]+>", "", cells[0]).strip()
            country = re.sub(r"<[^>]+>", "", cells[3]).strip()
            symbols = re.findall(r"E/C\.12/\d+/D/\d+/\d+", cells[4])
            date = re.sub(r"<[^>]+>", "", cells[5]).strip()
            for sym in symbols:
                out.append({
                    "symbol": sym, "title": title,
                    "country": country, "publication_date": date,
                })
        return out

    def hidden_fields(html):
        return dict(re.findall(
            r'<input[^>]+name="(__\w+)"[^>]+value="([^"]*)"', html
        ))

    print("Discovering CESCR decisions via TBSearch.aspx pagination…")
    html = fetch()
    seen: dict = {}
    page = 0
    while True:
        page += 1
        rows = parse_rows(html)
        new = 0
        for row in rows:
            if row["symbol"] not in seen:
                seen[row["symbol"]] = row
                new += 1
        print(f"  page {page:2d}: {len(rows)} rows, {new} new (total {len(seen)})")
        if new == 0 and page > 1:
            break
        if page > 40:
            break
        hidden = hidden_fields(html)
        form = {
            **hidden,
            "__EVENTTARGET": "ctl00$ContentPlaceHolder1$radResultsGrid",
            "__EVENTARGUMENT":
                "FireCommand:ctl00$ContentPlaceHolder1$radResultsGrid$ctl00;"
                "Page;Next",
        }
        try:
            html = fetch(form)
        except Exception as e:
            print(f"  ✗ fetch failed: {e}")
            break
        time.sleep(0.4)
    return seen


# ─────────────────────────────────────────  docx fetch
def fetch_docx(symbol: str, dest: Path, force: bool = False) -> str:
    """Returns 'docx' on PK header, 'doc' if OLE, 'miss' otherwise.
    Mirrors extract_sp_footnotes.fetch_docx with the addition that we
    treat the response as definitive — no further retries."""
    if not force and dest.exists() and dest.stat().st_size > 1024:
        with open(dest, "rb") as fh:
            head = fh.read(8)
        if head[:4] == b"PK\x03\x04":
            return "docx"
        if head[:4] == b"\xd0\xcf\x11\xe0":
            return "doc"
    url = (
        f"https://documents.un.org/api/symbol/access?"
        f"s={urllib.parse.quote(symbol, safe='/')}&l=en&t=docx"
    )
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, context=CTX, timeout=60) as r:
            data = r.read()
    except urllib.error.HTTPError as e:
        if e.code != 404:
            print(f"  ✗ {symbol}: HTTP {e.code}", file=sys.stderr)
        return "miss"
    except Exception as e:
        print(f"  ✗ {symbol}: {type(e).__name__}: {e}", file=sys.stderr)
        return "miss"
    if data[:4] == b"PK\x03\x04":
        dest.write_bytes(data)
        return "docx"
    if data[:4] == b"\xd0\xcf\x11\xe0":
        doc_path = dest.with_suffix(".doc")
        doc_path.write_bytes(data)
        return "doc"
    return "miss"


# ─────────────────────────────────────────  doc → docx via libreoffice
def convert_doc_to_docx(doc_path: Path, docx_path: Path) -> bool:
    """Same approach as extract_sp_footnotes — LibreOffice preserves
    footnotes; macOS textutil drops them."""
    import shutil, subprocess
    soffice = None
    for cand in (
        "/opt/homebrew/bin/soffice",
        "/usr/local/bin/soffice",
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
        "soffice", "libreoffice",
    ):
        if cand.startswith("/") and Path(cand).is_file():
            soffice = cand; break
        if not cand.startswith("/") and shutil.which(cand):
            soffice = shutil.which(cand); break
    if not soffice:
        return False
    try:
        subprocess.run(
            [soffice, "--headless", "--convert-to", "docx",
             "--outdir", str(doc_path.parent), str(doc_path)],
            check=True, capture_output=True, timeout=120,
        )
    except Exception as e:
        print(f"  ✗ soffice: {e}", file=sys.stderr)
        return False
    return docx_path.exists() and docx_path.stat().st_size >= 1024


# ─────────────────────────────────────────  OOXML walk
_LO_FN_PREFIX = re.compile(r"^\?\s*")
_WS = re.compile(r"\s+")


def _para_style(p) -> str | None:
    pPr = p.find(f"{W}pPr")
    if pPr is None:
        return None
    ps = pPr.find(f"{W}pStyle")
    return ps.get(f"{W}val") if ps is not None else None


def _para_text_with_fn_placeholders(p):
    """Concatenate <w:t> text and emit `§§FN§§<wid>§§` for each
    <w:footnoteReference>. Returns (rendered_text, [wids in order])."""
    chunks, fn_ids = [], []
    for elem in p.iter():
        tag = elem.tag
        if tag == f"{W}t":
            if elem.text:
                chunks.append(elem.text)
        elif tag == f"{W}footnoteReference":
            wid = elem.get(f"{W}id")
            chunks.append(f"§§FN§§{wid}§§")
            fn_ids.append(wid)
        elif tag in (f"{W}br", f"{W}cr"):
            chunks.append(" ")
        elif tag == f"{W}tab":
            chunks.append(" ")
    text = "".join(chunks).strip()
    return text, fn_ids


def _collect_footnote_bodies(zf: zipfile.ZipFile) -> dict[str, str]:
    try:
        tree = ET.parse(zf.open("word/footnotes.xml"))
    except KeyError:
        return {}
    bodies: dict[str, str] = {}
    for fn in tree.iter(f"{W}footnote"):
        if fn.get(f"{W}type"):
            continue
        wid = fn.get(f"{W}id")
        text = "".join(t.text or "" for t in fn.iter(f"{W}t")).strip()
        text = _LO_FN_PREFIX.sub("", text)
        text = _WS.sub(" ", text).strip()
        if text:
            bodies[wid] = text
    return bodies


# UN Views use both flat "1." and nested "1.2" / "2.1" numbering.
# Capture multi-level numbers; trailing period optional (Word renders
# nested as "1.2" without final period, top-level as "1.").
_NUM_PREFIX = re.compile(r"^\s*(\d+(?:\.\d+)*)\.?\s+")
# Block-form: "Subject:" alone on a line (Views docs).
_LABEL_RE = re.compile(r"^([A-Z][^:]{2,40}):\s*$")
# Inline-form: "Communication submitted by: N.E.H.E.F." on one line
# (Discontinuance / Inadmissibility decisions). The label whitelist
# is fixed because we only want known front-matter keys.
_INLINE_LABEL_RE = re.compile(
    r"^(Subject(?:\s+matter)?|Substantive issues?|Procedural issues?|"
    r"Articles? of the (?:Covenant|Optional Protocol)|"
    r"Submitted by|Communication submitted by|"
    r"Alleged victims?|State party|Date of communication):\s+(.+?)\s*$"
)
# When we recognize an inline label, normalize it to match block-form keys.
_INLINE_LABEL_NORMALIZE = {
    "Communication submitted by": "Submitted by",
    "Subject matter": "Subject",
    "Substantive issue": "Substantive issues",
    "Procedural issue": "Procedural issues",
    "Articles of the Covenant": "Articles of the Covenant:",
    "Article of the Covenant": "Articles of the Covenant:",
    "Articles of the Optional Protocol": "Article of the Optional Protocol:",
    "Article of the Optional Protocol": "Article of the Optional Protocol:",
}


def extract_doc(docx_path: Path) -> dict:
    """Return per-doc record with metadata + paragraphs."""
    with zipfile.ZipFile(docx_path) as zf:
        bodies = _collect_footnote_bodies(zf)
        # Document-wide sequential N for footnotes
        wid_to_n: dict[str, int] = {}
        seq = 0
        tree = ET.parse(zf.open("word/document.xml"))
        for p in tree.iter(f"{W}p"):
            for elem in p.iter():
                if elem.tag == f"{W}footnoteReference":
                    wid = elem.get(f"{W}id")
                    if wid not in wid_to_n and wid in bodies:
                        seq += 1
                        wid_to_n[wid] = seq

        # Walk paragraphs, building section stack + paragraph rows.
        #
        # Front-matter ingestion: UN treaty-body decisions sandwich
        # unstyled (no pStyle) "Label:" / "Value" paragraph pairs in
        # TWO blocks — one before "Annex" listing the issues + articles,
        # and a second after the "Communication No. X" heading listing
        # case parties (Submitted by / Alleged victim / State party /
        # Date of communication). We collect both.
        #
        # An unstyled paragraph matching ^Label:$ becomes pending_label;
        # the next unstyled, non-Label: paragraph is the value. Body
        # paragraphs (SingleTxt / numbered) clear the pending state.
        section_stack: list[tuple[int, str]] = []
        paragraphs: list[dict] = []
        metadata: dict = {}
        pending_label: str | None = None
        body_started = False

        for raw_p in tree.iter(f"{W}p"):
            style = _para_style(raw_p)
            text, fn_ids = _para_text_with_fn_placeholders(raw_p)
            if not text:
                continue
            text = _WS.sub(" ", text).strip()

            # Heading paragraphs update the stack and emit no body row.
            if style in HEADING_STYLES:
                depth = HEADING_STYLES[style]
                while section_stack and section_stack[-1][0] >= depth:
                    section_stack.pop()
                section_stack.append((depth, text))
                pending_label = None
                continue

            # Front-matter label / value pairs.
            # Block form (separate lines) only fires for unstyled ¶s.
            if style is None or style == "":
                m = _LABEL_RE.match(text)
                if m:
                    pending_label = m.group(1).strip() + ":"
                    continue
                if pending_label is not None:
                    metadata.setdefault(pending_label, []).append(text)
                    pending_label = None
                    continue
                # Unstyled non-label and no pending label — pre-body
                # chrome ("Committee on …", "Annex"). Skip.
                if not body_started:
                    continue
            # Inline form ("Submitted by: <name>") fires regardless of
            # style — Discontinuance decisions emit it as SingleTxt.
            m_inline = _INLINE_LABEL_RE.match(text)
            if m_inline:
                label_raw = m_inline.group(1).strip()
                value = m_inline.group(2).strip()
                # Normalize key to match Views-doc form
                key = _INLINE_LABEL_NORMALIZE.get(label_raw, label_raw)
                if not key.endswith(":"):
                    key = key + ":"
                metadata.setdefault(key, []).append(value)
                continue

            # Body paragraph (SingleTxt, or post-body unstyled).
            inline = text
            seen_fns: list[int] = []
            for wid in fn_ids:
                n = wid_to_n.get(wid)
                if n is None:
                    inline = inline.replace(f"§§FN§§{wid}§§", "", 1)
                    continue
                inline = inline.replace(f"§§FN§§{wid}§§", f"[[fn:{n}]]", 1)
                seen_fns.append(n)
            n_match = _NUM_PREFIX.match(inline)
            n_val: str | None = n_match.group(1) if n_match else None
            if n_val is not None:
                body_started = True
            # Emit ALL SingleTxt (and post-body unstyled) as body rows.
            # Including the chrome ("The Committee on …, Meeting on …")
            # is the right call — for Views docs it preserves the
            # adoption framing the reader expects, and for Discontinuance
            # / Inadmissibility decisions (no numbered ¶s at all) it's
            # the only substantive text the doc carries.
            pending_label = None
            section_path = [s for _, s in section_stack]
            paragraphs.append({
                "n": n_val,
                "idx": len(paragraphs) + 1,
                "text": inline,
                "footnotes": [
                    {"n": k, "text": bodies[wid]}
                    for wid, k in sorted(wid_to_n.items(), key=lambda kv: kv[1])
                    if k in seen_fns
                ],
                "section_path": section_path,
                "style": style or "SingleTxt",
            })

    # Coerce front-matter into a tidier metadata dict
    def _flatten(label, key, multi=False):
        vals = metadata.get(label, [])
        if not vals:
            return None
        return vals if multi else " ".join(vals).strip()

    clean_meta = {}
    label_keys = {
        "Subject:": ("subject_matter", True),
        "Substantive issues:": ("substantive_issues", True),
        "Procedural issues:": ("procedural_issues", True),
        "Articles of the Covenant:": ("covenant_articles", False),
        "Article of the Optional Protocol:": ("op_articles", False),
        "Articles of the Optional Protocol:": ("op_articles", False),
        "Submitted by:": ("submitted_by", False),
        "Alleged victim:": ("alleged_victims", False),
        "Alleged victims:": ("alleged_victims", False),
        "State party:": ("state_party", False),
        "Date of communication:": ("communication_date", False),
    }
    for label, (key, multi) in label_keys.items():
        v = _flatten(label, key, multi=multi)
        if v is not None:
            clean_meta[key] = v

    return {
        "paragraphs": paragraphs,
        "metadata": clean_meta,
        "footnote_total": len(wid_to_n),
    }


# ─────────────────────────────────────────  driver
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--discover", action="store_true",
                    help="(re-)scrape the canonical case list from OHCHR.")
    ap.add_argument("--doc", help="Process only this docId.")
    ap.add_argument("--no-fetch", action="store_true",
                    help="Use cached docx files only.")
    ap.add_argument("--force", action="store_true",
                    help="Re-download even if cached.")
    ap.add_argument("--limit", type=int, help="Stop after N decisions.")
    args = ap.parse_args()

    DOCX_DIR.mkdir(parents=True, exist_ok=True)

    if args.discover or not CASE_LIST.exists():
        cases = discover_cescr_decisions()
        CASE_LIST.write_text(
            json.dumps(cases, ensure_ascii=False, indent=2) + "\n"
        )
        print(f"  ✅ wrote {CASE_LIST.relative_to(REPO)} ({len(cases)} cases)")
        if args.discover:
            return 0

    cases = json.loads(CASE_LIST.read_text())
    if args.doc:
        cases = {sym: meta for sym, meta in cases.items()
                 if symbol_to_docid(sym) == args.doc}

    out: dict = {}
    if OUT_JSON.exists():
        try:
            out = json.loads(OUT_JSON.read_text())
        except Exception:
            out = {}

    n_ok = n_no_docx = n_fail = 0
    for i, (symbol, case_meta) in enumerate(sorted(cases.items()), start=1):
        if args.limit and i > args.limit:
            break
        doc_id = symbol_to_docid(symbol)
        docx_path = DOCX_DIR / f"{doc_id}.docx"

        kind = "miss"
        if not args.no_fetch:
            kind = fetch_docx(symbol, docx_path, force=args.force)
            time.sleep(0.3)
        else:
            if docx_path.exists():
                with open(docx_path, "rb") as fh:
                    if fh.read(4) == b"PK\x03\x04":
                        kind = "docx"
            elif (DOCX_DIR / f"{doc_id}.doc").exists():
                kind = "doc"

        if kind == "doc":
            doc_path = DOCX_DIR / f"{doc_id}.doc"
            if not docx_path.exists() or args.force:
                if not convert_doc_to_docx(doc_path, docx_path):
                    n_no_docx += 1
                    print(f"  [{i:3d}/{len(cases)}] {doc_id:30s}  ✗ doc→docx failed")
                    continue
        elif kind != "docx":
            n_no_docx += 1
            print(f"  [{i:3d}/{len(cases)}] {doc_id:30s}  no docx ({kind})")
            continue

        try:
            result = extract_doc(docx_path)
        except Exception as e:
            n_fail += 1
            print(f"  [{i:3d}/{len(cases)}] {doc_id:30s}  ✗ extract: {e}",
                  file=sys.stderr)
            continue

        # Combine extraction with discovery metadata
        out[doc_id] = {
            "symbol": symbol,
            "discovery": case_meta,
            "metadata": result["metadata"],
            "paragraphs": result["paragraphs"],
            "footnote_total": result["footnote_total"],
        }
        n_ok += 1
        n_fn = result["footnote_total"]
        n_p = len(result["paragraphs"])
        n_meta = len(result["metadata"])
        print(f"  [{i:3d}/{len(cases)}] {doc_id:30s}  "
              f"¶={n_p:3d}  fn={n_fn:3d}  meta={n_meta}")

    print()
    print(f"  ok:               {n_ok:3d}")
    print(f"  no docx:          {n_no_docx:3d}")
    print(f"  extract failed:   {n_fail:3d}")

    OUT_JSON.write_text(
        json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n"
    )
    print(f"\n  ✅ wrote {OUT_JSON.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
