#!/usr/bin/env python3
"""
OCR pipeline for scanned OHCHR jurisprudence PDFs.

The pipeline is deliberately conservative:
  1. Build a queue of English PDF cases that are missing from the extracted
     jurisprudence catalog and have no embedded text.
  2. Render each PDF page at high resolution.
  3. Run two Tesseract profiles per page and keep the higher-confidence result.
  4. Store page-level OCR text plus confidence diagnostics.
  5. Optionally ingest only documents that pass the quality gate.

Usage:
    python3 ocr_jurisprudence.py plan --treaty CCPR
    python3 ocr_jurisprudence.py run --treaty CCPR --limit 5
    python3 ocr_jurisprudence.py audit --treaty CCPR
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import fitz
from PIL import Image, ImageOps


ROOT = Path(__file__).resolve().parent
JURIS_SRC = Path('/Users/lszoszk/Desktop/AI/HURIDOCS/App/output/ohchr_jurisprudence')
CATALOG = JURIS_SRC / 'catalog.jsonl'
MANIFEST = JURIS_SRC / 'download_manifest.jsonl'
INFO = ROOT / 'mysite_pythonanywhere' / 'jurisprudence_info.json'
OCR_ROOT = ROOT / 'ocr_jurisprudence'

DEFAULT_DPI = 400
DEFAULT_MIN_MEAN_CONF = 70.0
DEFAULT_MAX_LOW_CONF_RATIO = 0.35


def slug(symbol: str) -> str:
    s = symbol.lower().strip()
    s = re.sub(r'[/\.\\:]+', '-', s)
    s = re.sub(r'[^a-z0-9-]', '-', s)
    return re.sub(r'-+', '-', s).strip('-')


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def read_info_symbols() -> set[str]:
    if not INFO.exists():
        return set()
    return {row.get('symbol', '') for row in json.loads(INFO.read_text())}


def manifest_file_path(entry: dict) -> Path | None:
    rel = (entry.get('file_path') or '').strip()
    if not rel:
        return None
    p = Path(rel)
    if p.is_absolute():
        return p
    parts = p.parts
    if len(parts) >= 2 and parts[0] == 'output' and parts[1] == 'ohchr_jurisprudence':
        return JURIS_SRC / Path(*parts[2:])
    return JURIS_SRC / p


def best_english_pdf(entries: list[dict]) -> dict | None:
    candidates = []
    for entry in entries:
        if entry.get('language') != 'en':
            continue
        if (entry.get('format') or '').lower() != 'pdf':
            continue
        path = manifest_file_path(entry)
        if path and path.exists() and path.stat().st_size > 0:
            candidates.append(entry)
    if not candidates:
        return None
    candidates.sort(key=lambda e: -(manifest_file_path(e).stat().st_size if manifest_file_path(e) else 0))
    return candidates[0]


def native_text_stats(path: Path) -> dict:
    try:
        doc = fitz.open(path)
    except Exception as exc:
        return {'pages': 0, 'nativeChars': -1, 'error': str(exc)}
    try:
        page_chars = [len(page.get_text().strip()) for page in doc]
        return {
            'pages': doc.page_count,
            'nativeChars': sum(page_chars),
            'maxPageChars': max(page_chars) if page_chars else 0,
        }
    finally:
        doc.close()


def load_manifest_index() -> dict[str, list[dict]]:
    by_symbol: dict[str, list[dict]] = {}
    for entry in read_jsonl(MANIFEST):
        sym = entry.get('symbol', '').strip()
        if sym:
            by_symbol.setdefault(sym, []).append(entry)
    return by_symbol


def build_queue(treaty: str, *, max_native_chars: int = 50) -> list[dict]:
    catalog = read_jsonl(CATALOG)
    manifest = load_manifest_index()
    extracted = read_info_symbols()
    rows = []
    for rec in catalog:
        if (rec.get('treaty') or '').upper() != treaty.upper():
            continue
        sym = (rec.get('symbol_no') or '').strip()
        if not sym or sym in extracted:
            continue
        if not sym.upper().startswith(f'{treaty.upper()}/'):
            continue
        chosen = best_english_pdf(manifest.get(sym, []))
        if not chosen:
            continue
        path = manifest_file_path(chosen)
        stats = native_text_stats(path)
        if stats.get('nativeChars', 0) > max_native_chars:
            continue
        rows.append({
            'symbol': sym,
            'docId': slug(sym),
            'treaty': treaty.upper(),
            'title': rec.get('title', '').strip(),
            'country': rec.get('country', '').strip(),
            'submittedDate': rec.get('submitted_date', '').strip(),
            'downloadPageUrl': rec.get('download_page_url', '').strip(),
            'pdfPath': str(path),
            'pdfBytes': path.stat().st_size,
            'pages': stats.get('pages', 0),
            'nativeChars': stats.get('nativeChars', 0),
            'reason': 'scanned_pdf_no_embedded_text',
        })
    rows.sort(key=lambda r: (r.get('pages') or 0, r['symbol']))
    return rows


def write_queue(treaty: str, rows: list[dict]) -> Path:
    path = OCR_ROOT / f'queue_{treaty.lower()}.jsonl'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows) + ('\n' if rows else ''))
    return path


def read_queue(treaty: str) -> list[dict]:
    path = OCR_ROOT / f'queue_{treaty.lower()}.jsonl'
    if not path.exists():
        return build_queue(treaty)
    return read_jsonl(path)


def require_tool(name: str) -> str:
    exe = shutil.which(name)
    if not exe:
        raise RuntimeError(f'{name} is required but was not found on PATH')
    return exe


def render_pages(pdf_path: Path, out_dir: Path, *, dpi: int) -> list[Path]:
    pdftoppm = require_tool('pdftoppm')
    prefix = out_dir / 'page'
    subprocess.run(
        [pdftoppm, '-r', str(dpi), '-png', str(pdf_path), str(prefix)],
        check=True,
        capture_output=True,
        text=True,
    )
    return sorted(out_dir.glob('page-*.png'))


def preprocess_image(path: Path) -> Path:
    out = path.with_name(f'{path.stem}.prep.png')
    with Image.open(path) as img:
        gray = ImageOps.grayscale(img)
        gray = ImageOps.autocontrast(gray)
        # Keep antialiasing: hard thresholding damaged old typewriter scans in
        # tests. Tesseract handles high-resolution grayscale more reliably.
        gray.save(out)
    return out


@dataclass
class OcrCandidate:
    profile: str
    psm: int
    text: str
    mean_conf: float
    low_conf_ratio: float
    word_count: int
    char_count: int


def tesseract_tsv(image: Path, *, psm: int, profile: str) -> OcrCandidate:
    tesseract = require_tool('tesseract')
    proc = subprocess.run(
        [
            tesseract, str(image), 'stdout',
            '-l', 'eng',
            '--oem', '1',
            '--psm', str(psm),
            '-c', 'preserve_interword_spaces=1',
            'tsv',
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    lines: dict[tuple[int, int, int], list[tuple[int, str]]] = {}
    confs = []
    words = 0
    reader = csv.DictReader(proc.stdout.splitlines(), delimiter='\t')
    for row in reader:
        txt = (row.get('text') or '').strip()
        if not txt:
            continue
        try:
            conf = float(row.get('conf') or -1)
        except ValueError:
            conf = -1
        if conf >= 0:
            confs.append(conf)
        words += 1
        key = (
            int(row.get('block_num') or 0),
            int(row.get('par_num') or 0),
            int(row.get('line_num') or 0),
        )
        lines.setdefault(key, []).append((int(row.get('word_num') or 0), txt))
    text_lines = []
    for key in sorted(lines):
        text_lines.append(' '.join(w for _, w in sorted(lines[key])))
    text = '\n'.join(text_lines).strip()
    mean_conf = sum(confs) / len(confs) if confs else 0.0
    low_conf = sum(1 for c in confs if c < 55)
    low_conf_ratio = low_conf / len(confs) if confs else 1.0
    return OcrCandidate(
        profile=profile,
        psm=psm,
        text=text,
        mean_conf=mean_conf,
        low_conf_ratio=low_conf_ratio,
        word_count=words,
        char_count=len(text),
    )


def choose_best(candidates: list[OcrCandidate]) -> OcrCandidate:
    def score(c: OcrCandidate) -> float:
        # Confidence is primary; enough text is the secondary signal. The log
        # avoids selecting a verbose garbage output over a clean shorter page.
        return c.mean_conf - (c.low_conf_ratio * 20) + min(math.log1p(c.char_count), 9)
    return max(candidates, key=score)


def quality_status(
    pages: list[dict],
    *,
    min_mean_conf: float,
    max_low_conf_ratio: float,
) -> tuple[str, list[str]]:
    warnings = []
    if not pages:
        return 'fail', ['no OCR pages']
    all_words = sum(p['wordCount'] for p in pages)
    all_chars = sum(p['charCount'] for p in pages)
    weighted_conf = (
        sum(p['meanConf'] * max(p['wordCount'], 1) for p in pages)
        / sum(max(p['wordCount'], 1) for p in pages)
    )
    low_ratio = (
        sum(p['lowConfRatio'] * max(p['wordCount'], 1) for p in pages)
        / sum(max(p['wordCount'], 1) for p in pages)
    )
    if weighted_conf < min_mean_conf:
        warnings.append(f'mean confidence {weighted_conf:.1f} < {min_mean_conf:.1f}')
    if low_ratio > max_low_conf_ratio:
        warnings.append(f'low-confidence ratio {low_ratio:.2f} > {max_low_conf_ratio:.2f}')
    if all_words < 80:
        warnings.append(f'low word count {all_words}')
    joined = '\n'.join(p.get('text', '') for p in pages).lower()
    if 'communication' not in joined and 'human rights committee' not in joined:
        warnings.append('missing expected HRC/communication language')
    if all_chars < 500:
        warnings.append(f'low character count {all_chars}')
    if weighted_conf < 55 or all_chars < 250:
        return 'fail', warnings
    if warnings:
        return 'review', warnings
    return 'pass', []


def ocr_one(row: dict, *, dpi: int, min_mean_conf: float, max_low_conf_ratio: float, force: bool) -> dict:
    pdf_path = Path(row['pdfPath'])
    doc_id = row['docId']
    out_dir = OCR_ROOT / row['treaty'].lower() / doc_id
    manifest_path = out_dir / 'ocr.json'
    if manifest_path.exists() and not force:
        return json.loads(manifest_path.read_text())

    out_dir.mkdir(parents=True, exist_ok=True)
    page_records = []
    with tempfile.TemporaryDirectory(prefix='jur_ocr_') as tmp:
        tmp_dir = Path(tmp)
        rendered = render_pages(pdf_path, tmp_dir, dpi=dpi)
        for idx, image_path in enumerate(rendered, 1):
            prepped = preprocess_image(image_path)
            candidates = [
                tesseract_tsv(prepped, psm=3, profile='auto_layout'),
                tesseract_tsv(prepped, psm=6, profile='single_block'),
            ]
            best = choose_best(candidates)
            page_txt = out_dir / f'page-{idx:03d}.txt'
            page_txt.write_text(best.text + '\n', encoding='utf-8')
            page_records.append({
                'page': idx,
                'profile': best.profile,
                'psm': best.psm,
                'meanConf': round(best.mean_conf, 2),
                'lowConfRatio': round(best.low_conf_ratio, 4),
                'wordCount': best.word_count,
                'charCount': best.char_count,
                'textPath': page_txt.name,
                'text': best.text,
                'alternatives': [
                    {
                        'profile': c.profile,
                        'psm': c.psm,
                        'meanConf': round(c.mean_conf, 2),
                        'lowConfRatio': round(c.low_conf_ratio, 4),
                        'wordCount': c.word_count,
                        'charCount': c.char_count,
                    }
                    for c in candidates
                ],
            })

    document_text = '\n\n'.join(p['text'] for p in page_records if p.get('text')).strip()
    (out_dir / 'document.txt').write_text(document_text + '\n', encoding='utf-8')
    status, warnings = quality_status(
        page_records,
        min_mean_conf=min_mean_conf,
        max_low_conf_ratio=max_low_conf_ratio,
    )
    payload = {
        **row,
        'ocrStatus': status,
        'warnings': warnings,
        'dpi': dpi,
        'pageCount': len(page_records),
        'wordCount': sum(p['wordCount'] for p in page_records),
        'charCount': sum(p['charCount'] for p in page_records),
        'meanConf': round(
            sum(p['meanConf'] * max(p['wordCount'], 1) for p in page_records)
            / sum(max(p['wordCount'], 1) for p in page_records),
            2,
        ) if page_records else 0,
        'lowConfRatio': round(
            sum(p['lowConfRatio'] * max(p['wordCount'], 1) for p in page_records)
            / sum(max(p['wordCount'], 1) for p in page_records),
            4,
        ) if page_records else 1,
        'textPath': 'document.txt',
        'pages': [
            {k: v for k, v in p.items() if k != 'text'}
            for p in page_records
        ],
    }
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return payload


def cmd_plan(args: argparse.Namespace) -> int:
    rows = build_queue(args.treaty, max_native_chars=args.max_native_chars)
    path = write_queue(args.treaty, rows)
    total_pages = sum(r.get('pages') or 0 for r in rows)
    print(f'OCR queue: {len(rows)} documents, {total_pages} pages')
    print(f'Wrote: {path}')
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    rows = read_queue(args.treaty)
    if args.status:
        done = {p.parent.name: json.loads(p.read_text()).get('ocrStatus') for p in (OCR_ROOT / args.treaty.lower()).glob('*/ocr.json')}
        rows = [r for r in rows if done.get(r['docId']) == args.status]
    if args.limit:
        rows = rows[:args.limit]
    print(f'OCR run: {len(rows)} documents')
    counts: dict[str, int] = {}
    for i, row in enumerate(rows, 1):
        result = ocr_one(
            row,
            dpi=args.dpi,
            min_mean_conf=args.min_mean_conf,
            max_low_conf_ratio=args.max_low_conf_ratio,
            force=args.force,
        )
        counts[result['ocrStatus']] = counts.get(result['ocrStatus'], 0) + 1
        print(
            f'[{i:4d}/{len(rows)}] {result["ocrStatus"]:6s} '
            f'{result["symbol"]} conf={result["meanConf"]:.1f} '
            f'words={result["wordCount"]} pages={result["pageCount"]}'
        )
    print('Summary:', counts)
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    base = OCR_ROOT / args.treaty.lower()
    records = [json.loads(p.read_text()) for p in sorted(base.glob('*/ocr.json'))]
    if not records:
        print(f'No OCR records under {base}')
        return 1
    counts: dict[str, int] = {}
    for rec in records:
        counts[rec['ocrStatus']] = counts.get(rec['ocrStatus'], 0) + 1
    report = {
        'treaty': args.treaty.upper(),
        'documents': len(records),
        'counts': counts,
        'meanConfidence': round(sum(r.get('meanConf', 0) for r in records) / len(records), 2),
        'review': [
            {
                'symbol': r['symbol'],
                'status': r['ocrStatus'],
                'meanConf': r.get('meanConf'),
                'lowConfRatio': r.get('lowConfRatio'),
                'wordCount': r.get('wordCount'),
                'warnings': r.get('warnings', []),
            }
            for r in records
            if r.get('ocrStatus') != 'pass'
        ],
    }
    out = OCR_ROOT / f'audit_{args.treaty.lower()}.json'
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'review'}, ensure_ascii=False, indent=2))
    print(f'Review queue: {len(report["review"])}')
    print(f'Wrote: {out}')
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest='cmd', required=True)

    plan = sub.add_parser('plan', help='Build OCR queue from missing scanned PDFs')
    plan.add_argument('--treaty', default='CCPR')
    plan.add_argument('--max-native-chars', type=int, default=50)
    plan.set_defaults(func=cmd_plan)

    run = sub.add_parser('run', help='Run OCR for queued documents')
    run.add_argument('--treaty', default='CCPR')
    run.add_argument('--dpi', type=int, default=DEFAULT_DPI)
    run.add_argument('--limit', type=int)
    run.add_argument('--force', action='store_true')
    run.add_argument('--status', choices=['pass', 'review', 'fail'], help='Re-run only documents with a previous status')
    run.add_argument('--min-mean-conf', type=float, default=DEFAULT_MIN_MEAN_CONF)
    run.add_argument('--max-low-conf-ratio', type=float, default=DEFAULT_MAX_LOW_CONF_RATIO)
    run.set_defaults(func=cmd_run)

    audit = sub.add_parser('audit', help='Summarise OCR results and write review queue')
    audit.add_argument('--treaty', default='CCPR')
    audit.set_defaults(func=cmd_audit)

    args = ap.parse_args()
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
