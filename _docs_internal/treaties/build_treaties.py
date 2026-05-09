"""Parse user-supplied OHCHR treaty HTML files (saved manually from
ohchr.org because Cloudflare blocks automated fetches) and produce
one JSON file per instrument under this directory.

OHCHR templates the same structure across all 18 instruments: a TOC
of article links at the top, then a preamble, then the substantive
articles. The TOC creates a duplicate "Article N" mention for every
article — short fragment, no body. We resolve this by, for each
article number, keeping the LONGEST body block found in the document.

Output schema:
    {
      "abbr": "ICCPR",
      "name_full": "International Covenant on Civil and Political Rights",
      "term": "Covenant" | "Convention" | "Optional Protocol",
      "committee_codes": ["CCPR"],
      "year": 1966,
      "source_file": "international-covenant-civil-and-political-rights.html",
      "articles": [
        {"number": "1", "paragraphs": [{"num": "1", "text": "..."}, ...]}
      ]
    }
"""
from __future__ import annotations
import html as html_lib
import json
import re
import sys
from pathlib import Path

OUT_DIR = Path(__file__).parent
DOWNLOAD_DIR = Path("/Users/lszoszk/Downloads")

# (abbr, filename, name_full, term, committees, year)
INSTRUMENTS = [
    ("ICCPR", "international-covenant-civil-and-political-rights.html",
     "International Covenant on Civil and Political Rights",
     "Covenant", ["CCPR"], 1966),
    ("ICESCR", "international-covenant-economic-social-and-cultural-rights.html",
     "International Covenant on Economic, Social and Cultural Rights",
     "Covenant", ["CESCR"], 1966),
    ("CRC", "convention-rights-child.html",
     "Convention on the Rights of the Child",
     "Convention", ["CRC"], 1989),
    ("CEDAW", "convention-elimination-all-forms-discrimination-against-women.html",
     "Convention on the Elimination of All Forms of Discrimination Against Women",
     "Convention", ["CEDAW"], 1979),
    ("CRPD", "convention-rights-persons-disabilities.html",
     "Convention on the Rights of Persons with Disabilities",
     "Convention", ["CRPD"], 2006),
    ("CAT", "convention-against-torture-and-other-cruel-inhuman-or-degrading.html",
     "Convention against Torture and Other Cruel, Inhuman or Degrading Treatment or Punishment",
     "Convention", ["CAT"], 1984),
    ("CERD", "international-convention-elimination-all-forms-racial.html",
     "International Convention on the Elimination of All Forms of Racial Discrimination",
     "Convention", ["CERD"], 1965),
    ("CMW", "international-convention-protection-rights-all-migrant-workers.html",
     "International Convention on the Protection of the Rights of All Migrant Workers and Members of Their Families",
     "Convention", ["CMW"], 1990),
    ("CED", "international-convention-protection-all-persons-enforced.html",
     "International Convention for the Protection of All Persons from Enforced Disappearance",
     "Convention", ["CED"], 2006),
    ("ICCPR-OP1", "optional-protocol-international-covenant-civil-and-political.html",
     "Optional Protocol to the International Covenant on Civil and Political Rights",
     "Optional Protocol", ["CCPR"], 1966),
    ("ICCPR-OP2", "second-optional-protocol-international-covenant-civil-and",
     "Second Optional Protocol to the International Covenant on Civil and Political Rights, aiming at the abolition of the death penalty",
     "Optional Protocol", ["CCPR"], 1989),
    ("ICESCR-OP", "optional-protocol-international-covenant-economic-social-and.html",
     "Optional Protocol to the International Covenant on Economic, Social and Cultural Rights",
     "Optional Protocol", ["CESCR"], 2008),
    ("CRC-OPSC", "optional-protocol-convention-rights-child-sale-children-child.html",
     "Optional Protocol to the Convention on the Rights of the Child on the sale of children, child prostitution and child pornography",
     "Optional Protocol", ["CRC"], 2000),
    ("CRC-OPAC", "optional-protocol-convention-rights-child-involvement-children.html",
     "Optional Protocol to the Convention on the Rights of the Child on the involvement of children in armed conflict",
     "Optional Protocol", ["CRC"], 2000),
    ("CRC-OPIC", "optional-protocol-convention-rights-child-communications.html",
     "Optional Protocol to the Convention on the Rights of the Child on a communications procedure",
     "Optional Protocol", ["CRC"], 2011),
    ("CEDAW-OP", "optional-protocol-convention-elimination-all-forms.html",
     "Optional Protocol to the Convention on the Elimination of All Forms of Discrimination Against Women",
     "Optional Protocol", ["CEDAW"], 1999),
    ("CRPD-OP", "optional-protocol-convention-rights-persons-disabilities.html",
     "Optional Protocol to the Convention on the Rights of Persons with Disabilities",
     "Optional Protocol", ["CRPD"], 2006),
    ("OPCAT", "optional-protocol-convention-against-torture-and-other-cruel.html",
     "Optional Protocol to the Convention against Torture and Other Cruel, Inhuman or Degrading Treatment or Punishment",
     "Optional Protocol", ["CAT", "CAT-OP"], 2002),
]


def html_to_text(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw)
    text = html_lib.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


ARTICLE_RE = re.compile(r"\bArticle\s+(\d{1,3})(?:\s*\.|\s|$)", re.IGNORECASE)
NOISE_PATTERNS = [
    re.compile(r"PART\s+[IVXLCDM]+\b", re.IGNORECASE),
    re.compile(r"PART\s+\d+\b", re.IGNORECASE),
    re.compile(r"\bChapter\s+[IVXLCDM]+\b", re.IGNORECASE),
]


def clean_body(body: str) -> str:
    for pat in NOISE_PATTERNS:
        body = pat.sub("", body)
    return re.sub(r"\s+", " ", body).strip()


# OHCHR HTML uses "1 . " (space before dot) inside <p> blocks; some
# other treaties use "1." (no space). Accept either.
PARA_NUM_RE = re.compile(r"(?:^|\s)(\d{1,2})\s*\.\s+")


def split_paragraphs(body: str) -> list[dict]:
    body = body.strip()
    body = re.sub(r"\b(?:DONE\s+at|IN\s+WITNESS\s+WHEREOF|Done\s+at)\b.*$", "",
                  body, flags=re.IGNORECASE).strip()
    matches = list(PARA_NUM_RE.finditer(body))
    if not matches or matches[0].start() > 30:
        return [{"num": None, "text": body}]
    paragraphs = []
    seen_num = set()
    for i, m in enumerate(matches):
        num = m.group(1)
        if num in seen_num:
            continue
        seen_num.add(num)
        para_start = m.end()
        para_end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        para_text = body[para_start:para_end].strip()
        if para_text:
            paragraphs.append({"num": num, "text": para_text})
    return paragraphs


def parse_articles(text: str) -> list[dict]:
    """For each article number, keep the LONGEST body fragment.

    OHCHR pages list articles twice — once in a TOC (no body) and once
    in the substantive section (full body). The "longest body" rule
    selects the substantive one without needing a hardcoded TOC marker.
    Article numbers cited inside another article's body produce only
    short fragments before the next "Article N" boundary, which lose
    to the substantive entry.
    """
    matches = list(ARTICLE_RE.finditer(text))
    if not matches:
        return []
    longest: dict[str, str] = {}
    for i, m in enumerate(matches):
        num = m.group(1)
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = clean_body(text[body_start:body_end])
        if len(body) < 30:
            continue
        if num not in longest or len(body) > len(longest[num]):
            longest[num] = body
    articles = []
    for num in sorted(longest.keys(), key=lambda x: int(x)):
        articles.append({
            "number": num,
            "paragraphs": split_paragraphs(longest[num]),
        })
    return articles


def build_one(abbr: str, filename: str, name_full: str, term: str,
              committees: list[str], year: int) -> dict:
    src = DOWNLOAD_DIR / filename
    raw = src.read_text(encoding="utf-8", errors="replace")
    text = html_to_text(raw)
    articles = parse_articles(text)
    return {
        "abbr": abbr,
        "name_full": name_full,
        "term": term,
        "committee_codes": committees,
        "year": year,
        "source_file": filename,
        "articles": articles,
    }


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    results = []
    for inst in INSTRUMENTS:
        abbr, filename = inst[0], inst[1]
        try:
            data = build_one(*inst)
            n_arts = len(data["articles"])
            n_paras = sum(len(a["paragraphs"]) for a in data["articles"])
            (OUT_DIR / f"{abbr.lower()}.json").write_text(
                json.dumps(data, indent=2, ensure_ascii=False)
            )
            results.append((abbr, n_arts, n_paras, "OK"))
        except FileNotFoundError as e:
            results.append((abbr, 0, 0, f"missing file: {filename}"))
        except Exception as e:
            results.append((abbr, 0, 0, f"FAIL: {e}"))

    print(f"  {'abbr':12} {'arts':>5} {'paras':>6}  status")
    print(f"  {'-'*12} {'-'*5} {'-'*6}  {'-'*40}")
    for abbr, n_arts, n_paras, status in results:
        print(f"  {abbr:12} {n_arts:>5} {n_paras:>6}  {status}")

    total_size = sum(p.stat().st_size for p in OUT_DIR.glob("*.json"))
    ok_count = sum(1 for _, _, _, s in results if s == "OK")
    print(f"\n  {ok_count}/{len(results)} treaties OK · bundle {total_size//1024} KB")


if __name__ == "__main__":
    main()
