#!/usr/bin/env python3
"""
Link validator — HEAD-checks every Link in the GC + SP metadata, updates
`lastVerifiedAt` for successful checks, and writes a status report.

Designed to run both:
  - Locally:           python3 validate_links.py
  - GitHub Actions:    .github/workflows/link-check.yml (weekly cron)

Behaviour:
  • Reads crc_gc_info.json + specialprocedures_info.json.
  • For each unique URL, sends a HEAD request (falls back to GET on 405).
  • Considers status 2xx as OK; anything else as broken.
  • For OK links: bumps `lastVerifiedAt` to today's date in the metadata.
  • For broken links: collects (signature, link, status, reason) and writes
    a JSON report.
  • Optional: if --strict is set, exits 1 when any link is broken (so
    GitHub Actions can fail the workflow).

Outputs:
  link_status.json — full report, committed alongside the dataset:
    {
      "checkedAt":   "2026-04-28T08:00:00Z",
      "totalUnique": 250,
      "okCount":     245,
      "brokenCount": 5,
      "broken": [{ "signature": ..., "link": ..., "status": 403, "reason": "..." }]
    }
"""
from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path

# Default paths — overridden in CLI / GH Actions if needed.
ROOT = Path(__file__).resolve().parent
GC_META = ROOT / 'mysite_pythonanywhere' / 'crc_gc_info.json'
SP_META = ROOT / 'mysite_pythonanywhere' / 'specialprocedures_info.json'
STATUS_OUT = ROOT / 'link_status.json'

# OHCHR's TLS chain is occasionally flaky from Python's stdlib; mirror what
# browsers tolerate. We do NOT skip this for arbitrary hosts — only OHCHR/UN.
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

# UN servers reject Python's default User-Agent + sometimes have TLS chains
# that stdlib doesn't trust. Use a browser-like UA and a relaxed TLS context
# for known UN domains.
USER_AGENT = (
    'Mozilla/5.0 (compatible; GenevaReporter-LinkValidator/1.1; '
    '+https://github.com/lszoszk/generalcomments)'
)

UN_HOSTS = (
    'tbinternet.ohchr.org',
    'docstore.ohchr.org',
    'www.ohchr.org',
    'ohchr.org',
    'undocs.org',
    'docs.un.org',
    'documents.un.org',
    'www.un.org',
    'refworld.org',
    'www.refworld.org',
)


def _is_un(url: str) -> bool:
    return any(h in url for h in UN_HOSTS)


def check_url(url: str, timeout: float = 15.0) -> tuple[int, str]:
    """Returns (status_code, reason). status_code 0 means a network error."""
    if not url or not url.startswith('http'):
        return (-1, 'invalid url')

    headers = {'User-Agent': USER_AGENT, 'Accept': '*/*'}
    ctx = SSL_CTX if _is_un(url) else None

    for method in ('HEAD', 'GET'):
        try:
            req = urllib.request.Request(url, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                return (resp.status, 'ok')
        except urllib.error.HTTPError as e:
            # Some servers don't support HEAD; retry with GET.
            if method == 'HEAD' and e.code in (403, 405, 501):
                continue
            return (e.code, e.reason or 'HTTPError')
        except urllib.error.URLError as e:
            return (0, f'URLError: {e.reason}')
        except Exception as e:
            return (0, f'{type(e).__name__}: {str(e)[:80]}')
    return (0, 'unreachable')


def collect_records() -> list[dict]:
    """Load both metadata files and tag each record with its source for write-back."""
    out = []
    for src_file in (GC_META, SP_META):
        if src_file.exists():
            try:
                data = json.loads(src_file.read_text())
                for r in data:
                    r['_src_file'] = str(src_file)
                    out.append(r)
            except Exception as e:
                print(f'WARNING: failed to parse {src_file}: {e}', file=sys.stderr)
    return out


def write_back(records: list[dict]) -> None:
    """Persist the per-record updates back to their source files."""
    by_file: dict[str, list[dict]] = {}
    for r in records:
        f = r.pop('_src_file', None)
        if f:
            by_file.setdefault(f, []).append(r)
    for f, rs in by_file.items():
        Path(f).write_text(json.dumps(rs, ensure_ascii=False, indent=2))


def run(args) -> int:
    today = date.today().isoformat()
    started = datetime.now(timezone.utc).isoformat()

    records = collect_records()
    if not records:
        print('No metadata records found.', file=sys.stderr)
        return 1

    # Build URL → list of records sharing that URL.
    by_url: dict[str, list[dict]] = {}
    for r in records:
        link = (r.get('Link') or '').strip()
        if link:
            by_url.setdefault(link, []).append(r)

    total = len(by_url)
    print(f'Validating {total} unique URLs across {len(records)} records '
          f'(workers={args.workers}, timeout={args.timeout}s)...')

    results: dict[str, tuple[int, str]] = {}
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(check_url, url, args.timeout): url for url in by_url}
        for i, fut in enumerate(as_completed(futures), 1):
            url = futures[fut]
            try:
                results[url] = fut.result()
            except Exception as e:
                results[url] = (0, f'unexpected: {e}')
            if i % 25 == 0 or i == total:
                elapsed = time.time() - t0
                ok = sum(1 for s, _ in results.values() if 200 <= s < 300)
                print(f'  [{i}/{total}] checked · ok={ok} · {elapsed:.0f}s elapsed')

    # Serial re-check pass for anything that came back non-2xx. The
    # parallel pass hits some UN hosts (notably undocs.org) hard enough
    # that they throttle the runner IP — the requests come back as
    # status 0 (connection reset / timeout), NOT genuine link rot. A
    # single-threaded re-check with a longer timeout and a polite delay
    # recovers those false positives; anything that fails the slow pass
    # too is reported broken. Without this, the weekly CI run flags
    # ~30 working SP-report links every time it runs from GitHub
    # Actions (local runs from a residential IP see 360/360).
    recheck = [u for u, (s, _) in results.items() if not (200 <= s < 300)]
    if recheck:
        slow_timeout = max(args.timeout * 2, 40.0)
        print(f'\n  Re-checking {len(recheck)} non-2xx URL(s) serially '
              f'(timeout={slow_timeout:.0f}s)...')
        recovered = 0
        for j, url in enumerate(recheck, 1):
            status, reason = check_url(url, slow_timeout)
            results[url] = (status, reason)
            if 200 <= status < 300:
                recovered += 1
            time.sleep(1.0)   # be polite — throttle was the problem
            if j % 10 == 0 or j == len(recheck):
                print(f'    [{j}/{len(recheck)}] re-checked · recovered={recovered}')
        print(f'  Re-check recovered {recovered}/{len(recheck)} '
              f'(transient throttle/timeout, not link rot).')

    # Build the report
    broken: list[dict] = []
    n_ok = 0
    for url, (status, reason) in results.items():
        if 200 <= status < 300:
            n_ok += 1
            # Bump lastVerifiedAt for every record sharing this URL
            for r in by_url[url]:
                r['lastVerifiedAt'] = today
        else:
            for r in by_url[url]:
                broken.append({
                    'signature': r.get('Signature', ''),
                    'docName':   r.get('Name', '')[:120],
                    'committee': r.get('Committee', ''),
                    'link':      url,
                    'status':    status,
                    'reason':    reason,
                })

    report = {
        'schemaVersion': 1,
        'checkedAt':   started,
        'finishedAt':  datetime.now(timezone.utc).isoformat(),
        'totalUnique': total,
        'totalRecords': len(records),
        'okCount':     n_ok,
        'brokenCount': len(broken),
        'broken':      broken,
    }
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2))

    # Persist lastVerifiedAt updates
    if not args.dry_run:
        write_back(records)

    print()
    print(f'Result: {n_ok}/{total} OK · {len(broken)} broken')
    print(f'Status report: {args.out}')
    if broken[:5]:
        print('First broken links:')
        for b in broken[:5]:
            print(f'  [{b["status"]}] {b["signature"]:30s} → {b["link"][:80]}')

    if args.strict and len(broken) > 0:
        return 1
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', default=str(STATUS_OUT),
                    help='Status report output path (default: link_status.json)')
    ap.add_argument('--workers', type=int, default=8,
                    help='Concurrent HTTP workers (default: 8)')
    ap.add_argument('--timeout', type=float, default=15.0,
                    help='Per-request timeout in seconds (default: 15)')
    ap.add_argument('--dry-run', action='store_true',
                    help="Don't persist lastVerifiedAt updates back to metadata files")
    ap.add_argument('--strict', action='store_true',
                    help='Exit 1 if any link is broken (for CI use)')
    args = ap.parse_args()

    return run(args)


if __name__ == '__main__':
    sys.exit(main())
