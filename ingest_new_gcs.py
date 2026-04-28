#!/usr/bin/env python3
"""
Ingest new General Comments into the corpus.

Pipeline:
  1. Extract text from PDFs in new_gcs_pdf/
  2. Segment into numbered paragraphs (matching the {ID, Labels, Text} format
     used in json_data/ and json_data_gc_labeled/)
  3. Apply concerned-group labelling patterns (same as quality_pipeline v6)
  4. Write outputs to:
       - mysite_pythonanywhere/json_data/<output>.json    (raw, no labels)
       - json_data_gc_labeled/<output>.json               (with pipeline labels)
  5. Append metadata records to mysite_pythonanywhere/crc_gc_info.json

Usage: python3 ingest_new_gcs.py
"""
import json
import re
from datetime import date
from pathlib import Path
import fitz  # PyMuPDF

ROOT = Path('/Users/lszoszk/Desktop/GC_Database')
PDF_DIR = ROOT / 'new_gcs_pdf'
SRC_JSON_DIR = ROOT / 'mysite_pythonanywhere' / 'json_data'
LABELED_JSON_DIR = ROOT / 'json_data_gc_labeled'
META_FILE = ROOT / 'mysite_pythonanywhere' / 'crc_gc_info.json'

# ---------------------------------------------------------------------------
# Documents to ingest. Each has the OHCHR Download.aspx symbolno (used in the
# Link metadata field) and the output filename in our corpus convention.
# ---------------------------------------------------------------------------
DOCS = [
    {
        'pdf':       'CESCR_GC27.pdf',
        'output':    'Annotated_ESCR-GC27-Environment.json',
        'signature': 'E/C.12/GC/27',
        'committee': 'CESCR',
        'name':      'GC27: Environmental dimension of sustainable development',
        'simplified': 'CESCR GC27: Sustainable development & environment',
        'date':      '26 September 2025',
        'year':      2025,
        'symbolno':  'E%2FC.12%2FGC%2F27',
    },
    {
        'pdf':       'CMW_GC6.pdf',
        'output':    'Annotated_CMW_GC6_GlobalCompact.json',
        'signature': 'CMW/C/GC/6',
        'committee': 'CMW',
        'name':      'GC6: Convergent protection of migrant workers and Global Compact',
        'simplified': 'CMW GC6: Convention & Global Compact',
        'date':      '14 June 2024',
        'year':      2024,
        'symbolno':  'CMW%2FC%2FGC%2F6',
    },
    {
        'pdf':       'CMW_GC7_CERD_GR38.pdf',
        'output':    'Annotated_CMW_GC7_CERD_GR38_Xenophobia.json',
        'signature': 'CMW/C/GC/7–CERD/C/GC/38',
        'committee': 'CMW, CERD',
        'name':      'CMW GC7 / CERD GR38: General guidelines on xenophobia towards migrants',
        'simplified': 'CMW GC7/CERD GR38: Xenophobia (general)',
        'date':      '1 December 2025',
        'year':      2025,
        'symbolno':  'CERD%2FC%2FGC%2F38',
    },
    {
        'pdf':       'CMW_GC8_CERD_GR39.pdf',
        'output':    'Annotated_CMW_GC8_CERD_GR39_XenophobiaThematic.json',
        'signature': 'CMW/C/GC/8–CERD/C/GC/39',
        'committee': 'CMW, CERD',
        'name':      'CMW GC8 / CERD GR39: Thematic guidelines on xenophobia towards migrants',
        'simplified': 'CMW GC8/CERD GR39: Xenophobia (thematic)',
        'date':      '1 December 2025',
        'year':      2025,
        'symbolno':  'CERD%2FC%2FGC%2F39',
    },
    {
        'pdf':       'CEDAW_GC30_Add1.pdf',
        'output':    'Annotated_CEDAW_GR30_Add1_WPS.json',
        'signature': 'CEDAW/C/GC/30/Add.1',
        'committee': 'CEDAW',
        'name':      'GR30 Addendum: Women in conflict prevention/post-conflict — Women, Peace and Security',
        'simplified': 'CEDAW GR30/Add.1: Women, Peace & Security addendum',
        'date':      '18 February 2026',
        'year':      2026,
        'symbolno':  'CEDAW%2FC%2FGC%2F30%2FAdd.1',
    },
]

# ---------------------------------------------------------------------------
# Concerned-group labelling patterns (v6 set, matching quality_pipeline.py)
# ---------------------------------------------------------------------------
PATTERNS = [
    ("Children", [
        r'\bchild(?:ren)?\b', r'\bjuvenile\b', r'\binfant\b', r'\bnewborn\b',
        r'\bminors?\b', r'\bunder.?18\b', r'\bpediatric\b', r'\bneonatal\b',
        r'\bunaccompanied minor\b', r'\bjuvenile justice\b', r'\bjuvenile offend',
        r'\bchild\s+labor(?:ur)?\b', r'\bchildren? in conflict with the law\b',
        r'\bchildren?\s+in\s+(?:detention|prison|custody)\b',
        r'\bchild marriage\b', r'\bearly marriage\b', r'\bage of criminal responsibility\b',
        r'\bbest interests? of the (?:child|student)\b',
    ]),
    ("Women/girls", [
        r'\bwom(?:an|en)\b', r'\bgirls?\b', r'\bfemale\b', r'\bmaternal\b',
        r'\bpregnant\b', r'\bpregnancy\b', r'\bmaternity\b', r'\bmothers?\b',
        r'\bgender.based violence\b', r'\bwife\b', r'\bwidow\b', r'\bgender equality\b',
        r'\bFGM\b', r'\bfemale genital\b',
        r'\bviolence against women\b', r'\bsex workers?\b',
        r'\bsexual and reproductive health\b', r'\breproductive rights\b',
        r'\bdomestic violence\b', r'\bintimate partner violence\b',
        r'\bhuman trafficking\b', r'\btraffick(?:ing|ed)', r'\bsexual exploit',
        r'\bsexual and reproductive freedom\b',
    ]),
    ("Persons with disabilities", [
        r'\bdisabilit(?:y|ies)\b', r'\bhandicap\b', r'\bimpairment\b',
        r'\bmental(?:ly)?\s+(?:ill\b|disorder\b|illness\b|health condition)',
        r'\bpsychiatric\b', r'\bcognitive disab\b', r'\bintellectual disab\b',
        r'\breason(?:able)? accommodat', r'\bdeaf(?:ness)?\b',
        r'\bblind(?:ness)?\b', r'\bwheelchair\b', r'\bmental health\b',
    ]),
    ("Migrants", [
        r'\bmigrant\b', r'\bimmigrant\b', r'\blabou?r migration\b',
        r'\bwork(?:ing)? permit\b', r'\bforeign worker\b',
        r'\bremittance\b', r'\bundocumented (?:person|worker|migrant)\b',
        r'\birregular migra\b', r'\bimmigration\b', r'\bxenophobia\b',
    ]),
    ("Indigenous peoples", [
        r'\bindigenous (?:people|communit|right|land|culture|knowledge|group|person|woman|child)\b',
        r'\btribal (?:people|communit|right|land)\b',
        r'\bfree,?\s*prior\s*and\s*informed\s*consent\b', r'\bFPIC\b',
        r'\btraditional\s+(?:knowledge|land|territory|communit)\b',
    ]),
    ("Persons deprived of their liberty", [
        r'\bprison(?:ers?|s)\b', r'\bdetain(?:ee|ment|ed\s+person)\b',
        r'\bincarcerat', r'\bimprison', r'\bjail(?:ed)?\b', r'\bpenitentiar\b',
        r'\bremand(?:ed)?\b', r'\bconvict(?:ed|s)\b', r'\bprobation\b',
        r'\bparole\b', r'\bpretrial detent', r'\bplaces of detention\b',
        r'\bpersons? deprived of (?:their|his|her) liberty\b',
    ]),
    ("Refugees & asylum-seekers", [
        r'\brefugee\b', r'\basylum.seeker\b', r'\basylum seeker\b',
        r'\bnon-refoulement\b', r'\bpersecution\b', r'\brefugee camp\b',
    ]),
    ("Adolescents", [
        r'\badolescent\b', r'\bteen(?:ager)?\b',
        r'\byoung people\b', r'\byoung person\b',
    ]),
    ("Persons living in rural/remote areas", [
        r'\brural\s+(?:area|community|population|household|region|setting|dweller)\b',
        r'\brural population\b',
        r'\bremote\s+area\b', r'\burban.rural\b',
    ]),
    ("Persons affected by armed conflict", [
        r'\barmed conflict\b', r'\bwar crime\b', r'\boccupied territory\b',
        r'\bhumanitarian law\b', r'\bIHL\b', r'\bhostilities\b',
        r'\bcombatant\b', r'\bforced displacement\b', r'\bwar.affected\b',
        r'\bconflict.affected\b', r'\bpost.conflict\b',
    ]),
    ("Persons living in poverty", [
        r'\bpovert', r'\bindigent\b', r'\bextreme poverty\b',
        r'\bimpoverish', r'\bdestitut', r'\binsufficient means\b',
        r'\beconomically disadvantaged\b',
        r'\bdisadvantaged groups?\b', r'\bdisadvantaged populations?\b',
        r'\bdisadvantaged communities?\b',
        r'\blow.income (?:famil|household|communit|person|group)\b',
        r'\bpoor\s+(?:people|persons|communities|families|household|country|countries)\b',
    ]),
    ("Internally displaced persons", [
        r'\bIDPs?\b', r'\binternally displaced\b', r'\binternal displacement\b',
        r'\bforced eviction\b',
    ]),
    ("Persons in street situations", [
        r'\bstreet\s+(?:child|person|people|youth)\b',
        r'\bhomeless(?:ness)?\b',
    ]),
    ("Children in alternative care", [
        r'\bfoster\s+(?:care|child|parent)\b', r'\borphan',
        r'\bchildren? in (?:alternative|substitute) care\b',
        r'\bchildren? without parental care\b',
    ]),
    ("Non-citizens and stateless", [
        r'\bstateless(?:ness)?\b', r'\bapatrid\b',
        r'\bnon.citizen\b', r'\bnon.nationals?\b',
    ]),
    ("Persons living with HIV/AIDS", [
        r'\bHIV\b', r'\bAIDS\b', r'\bHIV/AIDS\b', r'\bantiretroviral\b',
    ]),
    ("LGBTI+", [
        r'\bLGBT(?:I|Q)?\+?\b', r'\bsexual orientation\b', r'\bgender identity\b',
        r'\bhomosexual(?:ity)?\b', r'\bbisexual\b', r'\btransgender\b',
        r'\bintersex\b', r'\bsame.sex\b',
    ]),
    ("Roma, Gypsies, Sinti and Travellers", [
        r'\bRoma\b', r'\bGyps(?:y|ies)\b', r'\bSinti\b',
        r'\bTravellers? community\b',
    ]),
    ("Persons affected by natural disasters", [
        r'\bnatural disaster\b', r'\bdisaster\s*(?:risk|relief|response|recovery)\b',
        r'\bearthquake\b', r'\bflood(?:ing)?\b', r'\btsunami\b',
        r'\bcyclone\b', r'\bdrought\b', r'\bhurricane\b', r'\bclimate change\b',
    ]),
]
COMPILED = [(label, [re.compile(p, re.IGNORECASE) for p in pats]) for label, pats in PATTERNS]


def extract_paragraphs(pdf_path: Path) -> list[dict]:
    """Extract numbered paragraphs from a UN treaty body GC PDF.

    Strategy:
      - Read full text of PDF page by page (PyMuPDF)
      - Concatenate, then split on numbered paragraph markers like `1.` `12.` `25.`
        at the start of a logical paragraph.
      - Heuristic: paragraphs are normally introduced as `\n<num>.<space>` or `<num>. `
        following a previous one.
      - Skip the cover page (logo, document symbol, distribution).
      - Drop footers (running document signatures like `E/C.12/GC/27` repeated on each page).
    """
    doc = fitz.open(pdf_path)
    pages_text = []
    for page in doc:
        pages_text.append(page.get_text("text"))
    full = "\n".join(pages_text)
    doc.close()

    # Strip running headers/footers: lines that look like UN doc symbols
    lines = full.split('\n')
    clean = []
    skip_pat = re.compile(r'^\s*(GE\.\d+|[A-Z]+/[A-Z]+/[A-Z0-9]+/\d+|page \d+|\d+\s*$)\s*$')
    for ln in lines:
        if skip_pat.match(ln.strip()):
            continue
        clean.append(ln)
    text = '\n'.join(clean)

    # Repair hyphenated line breaks and join soft-wrapped lines
    text = re.sub(r'-\n', '', text)            # hyphen-newline -> nothing
    text = re.sub(r'(?<=[a-z,])\n(?=[a-z(])', ' ', text)  # mid-sentence wraps
    # Normalize whitespace
    text = re.sub(r'[ \t]+', ' ', text)

    # Split on paragraph numbers at start of line: `1.` `2.` ... up to ~120
    # Allowed: optional whitespace then 1-3 digit + period + space
    para_split = re.split(r'(?m)^\s*(\d{1,3})\.\s+', text)

    paragraphs = []
    # para_split alternates: [pre, num, body, num, body, ...]
    if len(para_split) >= 3:
        # Discard everything before first numbered paragraph
        for i in range(1, len(para_split) - 1, 2):
            num = para_split[i]
            body = para_split[i + 1].strip()
            # Stop if body is empty or extremely short (likely TOC artefact)
            if len(body) < 30:
                continue
            # Trim trailing artefacts (annex labels, etc.)
            body = re.sub(r'\s+', ' ', body).strip()
            paragraphs.append({
                'ID': f'{num}.',
                'Labels': [],
                'Text': body,
            })
    else:
        # Fallback: split on double newlines
        for i, chunk in enumerate(re.split(r'\n\s*\n', text), 1):
            chunk = chunk.strip()
            if len(chunk) > 50:
                paragraphs.append({
                    'ID': f'{i}.',
                    'Labels': [],
                    'Text': re.sub(r'\s+', ' ', chunk),
                })
    return paragraphs


def label_paragraph(text: str) -> list[str]:
    found = []
    for label, pats in COMPILED:
        for p in pats:
            if p.search(text):
                found.append(label)
                break
    return sorted(set(found))


def main():
    SRC_JSON_DIR.mkdir(parents=True, exist_ok=True)
    LABELED_JSON_DIR.mkdir(parents=True, exist_ok=True)

    new_meta_records = []
    print(f'Ingesting {len(DOCS)} new GCs...\n')

    for d in DOCS:
        pdf_path = PDF_DIR / d['pdf']
        if not pdf_path.exists():
            print(f"  ❌ Missing PDF: {pdf_path}")
            continue
        paragraphs = extract_paragraphs(pdf_path)
        if not paragraphs:
            print(f"  ⚠️  No paragraphs extracted from {pdf_path}")
            continue

        # Apply labels
        labeled_paras = []
        for p in paragraphs:
            labels = label_paragraph(p['Text'])
            labeled_paras.append({**p, 'Labels': labels})

        # Save raw (no labels) and labeled versions
        raw = [{'ID': p['ID'], 'Labels': [], 'Text': p['Text']} for p in paragraphs]
        (SRC_JSON_DIR / d['output']).write_text(json.dumps(raw, ensure_ascii=False, indent=2))
        (LABELED_JSON_DIR / d['output']).write_text(json.dumps(labeled_paras, ensure_ascii=False, indent=2))

        n_lbl = sum(1 for p in labeled_paras if p['Labels'])
        print(f"  ✓ {d['signature']:<30s} {len(paragraphs):3d} paragraphs ({n_lbl} labelled)  → {d['output']}")

        # Build metadata record
        new_meta_records.append({
            'File PATH': f"/home/lszoszk/mysite/json_data/{d['output']}",
            'Name': d['name'],
            'Simplified Name': d['simplified'],
            'Signature': d['signature'],
            'Adoption Date': d['date'],
            'Adoption Year': d['year'],
            'Committee': d['committee'],
            'Link': f"https://tbinternet.ohchr.org/_layouts/15/treatybodyexternal/Download.aspx?symbolno={d['symbolno']}&Lang=en",
        })

    # Append to metadata file
    meta = json.loads(META_FILE.read_text())
    meta.extend(new_meta_records)

    # Also fix CED/C/GC/1 year (was 2003, actually 2023)
    for r in meta:
        if r.get('Signature') == 'CED/C/GC/1':
            if r.get('Adoption Year') in (2003, '2003'):
                print(f"  🔧 Fixing CED/C/GC/1 year: 2003 → 2023")
                r['Adoption Year'] = 2023

    META_FILE.write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    print(f"\n✓ Metadata updated: {len(new_meta_records)} new records appended (total: {len(meta)})")


if __name__ == '__main__':
    main()
