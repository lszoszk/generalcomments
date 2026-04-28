#!/usr/bin/env python3
"""
Generic Special Procedures mandate ingestion pipeline.

Extends the corpus by adding all annual thematic reports from a single
mandate-holder office (Special Rapporteur / Independent Expert / Working
Group). Reuses the PDF→paragraphs converter from ingest_new_gcs.py and the
labelling patterns from quality_pipeline v6.

Usage:
    python3 ingest_sp_mandate.py --mandate disability       # ingest SR Disability
    python3 ingest_sp_mandate.py --list                     # list configured mandates

Adding a new mandate:
    1. Append a record to MANDATES below with:
        - committee_label   ("SR Disability", "SR Torture", …)
        - mandate_holders   list of (year_max, full_name)
        - reports           list of (year, signature, presented, subject_name)
    2. Run with --mandate <slug>.

The pipeline:
    1. For each report, download the English PDF via OHCHR Download.aspx.
    2. Extract paragraphs using PyMuPDF (same code as for GCs).
    3. Apply SP labelling patterns.
    4. Save labelled JSON in json_labeled_v2/ (corpus build dir).
    5. Append metadata records to specialprocedures_info.json.

Idempotent: skips reports already in the SP metadata. Run repeatedly without
duplication.
"""
from __future__ import annotations

import argparse
import json
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

import fitz  # PyMuPDF — same dependency as ingest_new_gcs.py

ROOT = Path(__file__).resolve().parent
SP_META = ROOT / 'mysite_pythonanywhere' / 'specialprocedures_info.json'
SP_LABELED_DIR = ROOT / 'json_labeled_v2'
PDF_CACHE = ROOT / 'sp_ingest_pdfs'

# Same TLS/UA setup as the link validator. UN servers reject Python's default UA.
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

USER_AGENT = (
    'Mozilla/5.0 (compatible; GenevaReporter-SPIngest/1.0; '
    '+https://github.com/lszoszk/generalcomments)'
)


# ---------------------------------------------------------------------------
# Mandate registry. Add new mandates here.
# ---------------------------------------------------------------------------
MANDATES: dict[str, dict] = {
    'disability': {
        'committee_label': 'SR Disability',
        'full_name': 'Special Rapporteur on the rights of persons with disabilities',
        # (year_max, name) — pick the first row whose year_max >= report year
        'mandate_holders': [
            (2020, 'Catalina Devandas-Aguilar'),
            (2023, 'Gerard Quinn'),
            (9999, 'Heba Hagrass'),
        ],
        # Catalog scraped from OHCHR's "Annual thematic reports" page
        # https://www.ohchr.org/en/special-procedures/sr-disability/annual-thematic-reports
        # (year, signature, presented, subject)
        'reports': [
            (2026, 'A/HRC/61/26', 'HRC 61st session', 'Equal participation of persons with disabilities in political life'),
            (2025, 'A/80/170',     'GA 80th session',  'Care and support for children with disabilities within the family environment and its gendered dimensions'),
            (2025, 'A/HRC/58/56',  'HRC 58th session', 'Thirty years of implementation of the Beijing Declaration and Platform for Action: its potential for women and girls with disabilities'),
            (2024, 'A/79/179',     'GA 79th session',  'Including people with disabilities in the review of the 2030 Agenda for Sustainable Development'),
            (2024, 'A/HRC/55/56',  'HRC 55th session', 'Taking stock of the first 10 years of the mandate and vision of the Special Rapporteur on the rights of persons with disabilities, Heba Hagrass'),
            (2023, 'A/78/174',     'GA 78th session',  'Peacebuilding and the inclusion of persons with disabilities'),
            (2023, 'A/HRC/52/32',  'HRC 52nd session', 'Transformation of services for persons with disabilities'),
            (2022, 'A/77/203',     'GA 77th session',  'Protection of the rights of persons with disabilities in the context of military operations'),
            (2022, 'A/HRC/49/52',  'HRC 49th session', 'Artificial intelligence and the rights of persons with disabilities'),
            (2021, 'A/76/146',     'GA 76th session',  'The rights of persons with disabilities in the context of armed conflict'),
            (2021, 'A/HRC/46/27',  'HRC 46th session', 'Vision report of the Special Rapporteur on the rights of persons with disabilities, Gerard Quinn'),
            (2020, 'A/75/186',     'GA 75th session',  'Disability-inclusive international cooperation'),
            (2020, 'A/HRC/43/41',  'HRC 43rd session', 'The impact of ableism in medical and scientific practice'),
            (2019, 'A/74/186',     'GA 74th session',  'Older persons with disabilities'),
            (2019, 'A/HRC/40/54',  'HRC 40th session', 'Deprivation of liberty of persons with disabilities'),
            (2018, 'A/73/161',     'GA 73rd session',  'Right to health of persons with disabilities'),
            (2018, 'A/HRC/37/56',  'HRC 37th session', 'Legal capacity and supported decision-making'),
            (2017, 'A/72/133',     'GA 72nd session',  'Sexual and reproductive health and rights of girls and young women with disabilities'),
            (2017, 'A/HRC/34/58',  'HRC 34th session', 'Access to rights-based support for persons with disabilities'),
            (2016, 'A/71/314',     'GA 71st session',  'Disability-inclusive policies'),
            (2016, 'A/HRC/31/62',  'HRC 31st session', 'The right of persons with disabilities to participate in decision-making'),
            (2015, 'A/70/297',     'GA 70th session',  'The right of persons with disabilities to social protection'),
            (2015, 'A/HRC/28/58',  'HRC 28th session', 'Vision report of the Special Rapporteur on the rights of persons with disabilities, Catalina Devandas-Aguilar'),
        ],
    },
    # Future mandates go here (SR Torture, SR Health, SR Indigenous, …)
}


# ---------------------------------------------------------------------------
# SP labelling patterns. Same set as quality_pipeline v6, applied to each
# extracted paragraph.
# ---------------------------------------------------------------------------
LABEL_PATTERNS = [
    ('Children', [
        r'\bchild(?:ren)?\b', r'\bjuvenile\b', r'\binfant\b', r'\bnewborn\b',
        r'\bminors?\b', r'\bunder.?18\b', r'\bpediatric\b',
        r'\bchild marriage\b', r'\bchild\s+labor(?:ur)?\b', r'\bchild soldier\b',
    ]),
    ('Women/girls', [
        r'\bwom(?:an|en)\b', r'\bgirls?\b', r'\bfemale\b', r'\bmaternal\b',
        r'\bpregnan', r'\bmaternity\b', r'\bmothers?\b', r'\bwidow\b',
        r'\bgender.based violence\b', r'\bgender equality\b',
        r'\bFGM\b', r'\bfemale genital\b', r'\bsexual and reproductive\b',
        r'\bdomestic violence\b', r'\btraffick(?:ing|ed)', r'\bsexual exploit',
    ]),
    ('Persons with disabilities', [
        r'\bdisabilit(?:y|ies)\b', r'\bhandicap\b', r'\bimpairment\b',
        r'\bmental(?:ly)?\s+(?:ill\b|disorder\b|illness\b|health condition)',
        r'\bpsychiatric\b', r'\bcognitive disab\b', r'\bintellectual disab\b',
        r'\breason(?:able)? accommodat', r'\bdeaf(?:ness)?\b',
        r'\bblind(?:ness)?\b', r'\bwheelchair\b', r'\bmental health\b',
    ]),
    ('Migrants', [
        r'\bmigrant\b', r'\bimmigrant\b', r'\blabou?r migration\b',
        r'\bforeign worker\b', r'\bremittance\b',
        r'\bundocumented (?:person|worker|migrant)\b', r'\birregular migra\b',
        r'\bxenophobia\b',
    ]),
    ('Indigenous peoples', [
        r'\bindigenous (?:people|communit|right|land|culture|knowledge|group|person|woman|child)\b',
        r'\btribal (?:people|communit|right|land)\b',
        r'\bfree,?\s*prior\s*and\s*informed\s*consent\b', r'\bFPIC\b',
    ]),
    ('Persons deprived of their liberty', [
        r'\bprison(?:ers?|s)\b', r'\bdetain(?:ee|ment|ed\s+person)\b',
        r'\bincarcerat', r'\bimprison', r'\bjail(?:ed)?\b', r'\bremand(?:ed)?\b',
        r'\bconvict(?:ed|s)\b', r'\bplaces of detention\b',
        r'\bpersons? deprived of (?:their|his|her) liberty\b',
    ]),
    ('Refugees & asylum-seekers', [
        r'\brefugee\b', r'\basylum.seeker\b', r'\basylum seeker\b',
        r'\bnon-refoulement\b', r'\bpersecution\b',
    ]),
    ('Adolescents', [
        r'\badolescent\b', r'\bteen(?:ager)?\b',
        r'\byoung people\b', r'\byoung person\b',
    ]),
    ('Persons living in rural/remote areas', [
        r'\brural\s+(?:area|community|population|household|region|setting|dweller)\b',
        r'\bremote\s+area\b',
    ]),
    ('Persons affected by armed conflict', [
        r'\barmed conflict\b', r'\bwar crime\b', r'\boccupied territory\b',
        r'\bhumanitarian law\b', r'\bIHL\b', r'\bhostilities\b',
        r'\bcombatant\b', r'\bforced displacement\b', r'\bpost.conflict\b',
    ]),
    ('Persons living in poverty', [
        r'\bpovert', r'\bindigent\b', r'\bextreme poverty\b',
        r'\bimpoverish', r'\bdestitut',
        r'\bpoor\s+(?:people|persons|communities|families)\b',
    ]),
    ('Internally displaced persons', [
        r'\bIDPs?\b', r'\binternally displaced\b', r'\binternal displacement\b',
        r'\bforced eviction\b',
    ]),
    ('Persons in street situations', [
        r'\bstreet\s+(?:child|person|people|youth)\b', r'\bhomeless(?:ness)?\b',
    ]),
    ('Children in alternative care', [
        r'\bfoster\s+(?:care|child|parent)\b', r'\borphan',
        r'\bchildren? in (?:alternative|substitute) care\b',
    ]),
    ('Non-citizens and stateless', [
        r'\bstateless(?:ness)?\b', r'\bnon.citizen\b', r'\bnon.nationals?\b',
    ]),
    ('Persons living with HIV/AIDS', [
        r'\bHIV\b', r'\bAIDS\b', r'\bantiretroviral\b',
    ]),
    ('LGBTI+', [
        r'\bLGBT(?:I|Q)?\+?\b', r'\bsexual orientation\b', r'\bgender identity\b',
        r'\bhomosexual(?:ity)?\b', r'\bbisexual\b', r'\btransgender\b',
        r'\bintersex\b', r'\bsame.sex\b',
    ]),
    ('Roma, Gypsies, Sinti and Travellers', [
        r'\bRoma\b', r'\bGyps(?:y|ies)\b', r'\bSinti\b',
    ]),
    ('Persons affected by natural disasters', [
        r'\bnatural disaster\b', r'\bdisaster\s*(?:risk|relief|response|recovery)\b',
        r'\bearthquake\b', r'\bflood(?:ing)?\b', r'\bcyclone\b', r'\bdrought\b',
        r'\bclimate change\b',
    ]),
]
COMPILED_LABELS = [(label, [re.compile(p, re.IGNORECASE) for p in pats])
                   for label, pats in LABEL_PATTERNS]


# ---------------------------------------------------------------------------
# OHCHR download — same flow as ingest_new_gcs.py
# ---------------------------------------------------------------------------
def fetch_url(url: str, timeout: float = 30.0) -> bytes:
    req = urllib.request.Request(url, headers={
        'User-Agent': USER_AGENT, 'Accept': '*/*'})
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as resp:
        return resp.read()


def discover_pdf_url(signature: str) -> str | None:
    """Find a working PDF URL for a UN document signature.

    Strategy (first hit wins):
      1. daccess-ods.un.org/access.nsf/Get?Open&DS={SIG}&Lang=E
         — the Official Document System; returns the actual PDF for most
         A/, A/HRC/, E/CN.4/ signatures going back ~25 years.
      2. OHCHR Download.aspx (treaty-body-only; useful for joint GCs).
      3. None — caller logs and skips.
    """
    # 1. ODS — primary route for SR/SP reports.
    ods_url = f'https://daccess-ods.un.org/access.nsf/Get?Open&DS={signature}&Lang=E'

    # 2. OHCHR (treaty body) Download.aspx — used by ingest_new_gcs.py for GCs.
    enc = urllib.parse.quote(signature, safe='')
    ohchr_url = (
        'https://tbinternet.ohchr.org/_layouts/15/treatybodyexternal/'
        f'Download.aspx?symbolno={enc}&Lang=en'
    )

    # Try ODS first — quick HEAD-style check by reading the first ~1KB to
    # confirm it's a PDF. We can't HEAD because daccess-ods follows redirects.
    try:
        req = urllib.request.Request(ods_url, headers={'User-Agent': USER_AGENT})
        with urllib.request.urlopen(req, timeout=20, context=SSL_CTX) as resp:
            head = resp.read(8)
            if head.startswith(b'%PDF'):
                return ods_url
    except Exception:
        pass

    # Fall back to OHCHR landing page (only useful for treaty body docs).
    try:
        html = fetch_url(ohchr_url).decode('utf-8', errors='replace')
        m = re.search(
            r'title="English[^"]*pdf"[^>]*href="(https://docstore[^"]+)"',
            html,
        )
        if m:
            return m.group(1).replace('&amp;', '&')
    except Exception:
        pass

    return None


# ---------------------------------------------------------------------------
# PDF → paragraphs (same as ingest_new_gcs.py)
# ---------------------------------------------------------------------------
def extract_paragraphs(pdf_path: Path) -> list[dict]:
    doc = fitz.open(pdf_path)
    pages_text = [page.get_text("text") for page in doc]
    full = "\n".join(pages_text)
    doc.close()

    lines = full.split('\n')
    skip_pat = re.compile(
        r'^\s*(GE\.\d+|[A-Z]+/[A-Z]+/[A-Z0-9]+/\d+|page \d+|\d+\s*$)\s*$')
    clean = [ln for ln in lines if not skip_pat.match(ln.strip())]
    text = '\n'.join(clean)

    text = re.sub(r'-\n', '', text)
    text = re.sub(r'(?<=[a-z,])\n(?=[a-z(])', ' ', text)
    text = re.sub(r'[ \t]+', ' ', text)

    para_split = re.split(r'(?m)^\s*(\d{1,3})\.\s+', text)
    paragraphs = []
    if len(para_split) >= 3:
        for i in range(1, len(para_split) - 1, 2):
            num = para_split[i]
            body = para_split[i + 1].strip()
            if len(body) < 30:
                continue
            body = re.sub(r'\s+', ' ', body).strip()
            paragraphs.append({'ID': f'{num}.', 'Labels': [], 'Text': body})
    else:
        for i, chunk in enumerate(re.split(r'\n\s*\n', text), 1):
            chunk = chunk.strip()
            if len(chunk) > 50:
                paragraphs.append({
                    'ID': f'{i}.', 'Labels': [],
                    'Text': re.sub(r'\s+', ' ', chunk),
                })
    return paragraphs


def label_paragraph(text: str) -> list[str]:
    found = []
    for label, pats in COMPILED_LABELS:
        if any(p.search(text) for p in pats):
            found.append(label)
    return sorted(set(found))


# ---------------------------------------------------------------------------
# Mandate-holder + report-type derivation
# ---------------------------------------------------------------------------
def holder_for_year(holders: list[tuple[int, str]], year: int) -> str:
    for y_max, name in holders:
        if year <= y_max:
            return name
    return holders[-1][1]


def parse_sessions(sig: str) -> tuple[int | None, int | None]:
    m = re.match(r'^A/HRC/(\d+)/', sig)
    if m:
        return int(m.group(1)), None
    m = re.match(r'^A/(\d{2,3})/', sig)
    if m and not sig.startswith('A/HRC/'):
        return None, int(m.group(1))
    return None, None


def safe_filename(s: str) -> str:
    s = re.sub(r'[/\\:.\s]+', '_', s)
    s = re.sub(r'[^A-Za-z0-9_-]', '', s)
    return s


# ---------------------------------------------------------------------------
# Main ingestion driver
# ---------------------------------------------------------------------------
def ingest(mandate_slug: str, *, force: bool = False, limit: int | None = None) -> dict:
    if mandate_slug not in MANDATES:
        raise SystemExit(f'Unknown mandate: {mandate_slug!r}. '
                         f'Available: {sorted(MANDATES)}')
    cfg = MANDATES[mandate_slug]
    PDF_CACHE.mkdir(parents=True, exist_ok=True)
    SP_LABELED_DIR.mkdir(parents=True, exist_ok=True)

    sp_meta = json.loads(SP_META.read_text())
    existing_sigs = {r.get('Signature', '').strip() for r in sp_meta}

    today = date.today().isoformat()
    new_records = []
    skipped = []
    failed = []

    reports = cfg['reports'][:limit] if limit else cfg['reports']

    for year, sig, presented, subject in reports:
        if sig in existing_sigs and not force:
            skipped.append((sig, 'already in metadata'))
            continue

        print(f'\n[{sig}] ({year}) {subject[:60]}…')
        holder = holder_for_year(cfg['mandate_holders'], year)
        hrc, ga = parse_sessions(sig)

        # 1. Discover PDF URL
        pdf_url = discover_pdf_url(sig)
        if not pdf_url:
            print('  ✗ could not resolve PDF URL')
            failed.append((sig, 'no PDF URL'))
            continue

        # 2. Download
        pdf_path = PDF_CACHE / f'{safe_filename(sig)}.pdf'
        if not pdf_path.exists() or force:
            try:
                pdf_bytes = fetch_url(pdf_url, timeout=45)
            except Exception as e:
                print(f'  ✗ download failed: {e}')
                failed.append((sig, f'download error: {e}'))
                continue
            if not pdf_bytes.startswith(b'%PDF'):
                print(f'  ✗ not a PDF (got {len(pdf_bytes)}b)')
                failed.append((sig, 'not a PDF'))
                continue
            pdf_path.write_bytes(pdf_bytes)
        time.sleep(0.4)  # courtesy throttle

        # 3. Extract paragraphs
        try:
            paras = extract_paragraphs(pdf_path)
        except Exception as e:
            print(f'  ✗ paragraph extraction failed: {e}')
            failed.append((sig, f'extraction: {e}'))
            continue
        if not paras:
            print('  ✗ no paragraphs extracted')
            failed.append((sig, 'no paragraphs'))
            continue

        # 4. Apply labels
        labeled = []
        n_lbl = 0
        for p in paras:
            labels = label_paragraph(p['Text'])
            if labels:
                n_lbl += 1
            labeled.append({**p, 'Labels': labels})
        print(f'  ✓ {len(paras):3d} paragraphs ({n_lbl} labelled)')

        # 5. Write paragraph file
        out_filename = f"{cfg['committee_label'].replace(' ', '_')}_{safe_filename(sig)}.json"
        (SP_LABELED_DIR / out_filename).write_text(
            json.dumps(labeled, ensure_ascii=False, indent=2))

        # 6. Build metadata record
        rec = {
            'File PATH': f'/home/lszoszk/mysite/json_data_sp/{out_filename}',
            'Name': subject,
            'Simplified Name': subject[:90],
            'Signature': sig,
            'Adoption Date': str(year),
            'Adoption Year': year,
            'Committee': cfg['committee_label'],
            'Mandate holder': holder,
            'Presented': presented,
            'Link': f'https://docs.un.org/en/{sig}',
            'reportType': 'thematic',
            'paragraphCount': len(labeled),
            'wordCount': sum(len(p['Text'].split()) for p in labeled),
            'labelCount': sum(len(p['Labels']) for p in labeled),
            'firstAddedAt': today,
            'lastVerifiedAt': today,
            'languagesAvailable': ['en'],
        }
        if hrc is not None:
            rec['hrcSession'] = hrc
        if ga is not None:
            rec['gaSession'] = ga
        new_records.append(rec)

    # Append metadata
    if new_records:
        sp_meta.extend(new_records)
        SP_META.write_text(json.dumps(sp_meta, ensure_ascii=False, indent=2))

    return {
        'mandate': mandate_slug,
        'requested': len(reports),
        'ingested': len(new_records),
        'skipped': skipped,
        'failed': failed,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--mandate', help='Mandate slug to ingest (e.g. "disability")')
    ap.add_argument('--list', action='store_true', help='List configured mandates')
    ap.add_argument('--force', action='store_true', help='Re-download and re-ingest even if signature exists')
    ap.add_argument('--limit', type=int, default=None, help='Limit number of reports (for testing)')
    args = ap.parse_args()

    if args.list:
        for slug, cfg in MANDATES.items():
            print(f'  {slug:20s} {cfg["full_name"]} — {len(cfg["reports"])} reports')
        return 0

    if not args.mandate:
        ap.print_help()
        return 1

    result = ingest(args.mandate, force=args.force, limit=args.limit)
    print(f'\n=== {result["mandate"]} ingestion summary ===')
    print(f'  Requested:  {result["requested"]}')
    print(f'  Ingested:   {result["ingested"]}')
    print(f'  Skipped:    {len(result["skipped"])}')
    print(f'  Failed:     {len(result["failed"])}')
    if result['failed']:
        print('\nFailures:')
        for sig, why in result['failed']:
            print(f'  {sig}: {why}')
    return 0 if not result['failed'] else 1


if __name__ == '__main__':
    sys.exit(main())
