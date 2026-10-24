"""Extract article bodies from Resource_File PDFs; leave original PDFs intact.

Install: python -m pip install -r scripts/requirements.txt
Run from any directory: python path/to/scripts/pdf_to_text.py
Wikipedia reference/end-matter starts at References or External links; everything
from the first such standalone heading onward is excluded. Image captions and
tables can retain PDF reading-order limitations. Scanned PDFs require OCR first.
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import re
import sys
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '.python-packages'))
try:
    from pypdf import PdfReader
except ImportError:
    raise SystemExit('Install dependency: python -m pip install -r scripts/requirements.txt')


def normalize(line: str) -> str:
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFC', line).replace('\u00ad', '')).strip()


def margin_key(line: str) -> str:
    line = normalize(line).casefold()
    # Normalize varying page counters without conflating numbered body text.
    return re.sub(r'\bpage\s+\d+(?:\s+of\s+\d+)?', 'page #', line)


def clean_pages(pages: list[str]) -> tuple[str, int, str]:
    """Remove recurring margin lines, page numbers, citations, and end matter."""
    lines_by_page = [page.splitlines() for page in pages]
    occurrences: Counter[str] = Counter()
    for lines in lines_by_page:
        nonempty = [line for line in lines if line.strip()]
        occurrences.update(set(margin_key(line) for line in nonempty[:2] + nonempty[-2:]))
    recurring = {key for key, count in occurrences.items()
                 if len(pages) >= 3 and count >= max(3, (len(pages) + 1) // 2)}
    result = []
    removed = 0
    cutoff = 'none'
    for lines in lines_by_page:
        nonempty_indices = [i for i, line in enumerate(lines) if line.strip()]
        margins = set(nonempty_indices[:2] + nonempty_indices[-2:])
        for i, raw in enumerate(lines):
            line = normalize(raw)
            if re.fullmatch(r'(?:\d+[.\s]+)?(?:References|External links)', line, re.I):
                cutoff = line
                break
            if i in margins and (margin_key(line) in recurring or
                    re.fullmatch(r'(?:Page\s+)?\d+(?:\s+(?:of|/)\s+\d+)?', line, re.I)):
                removed += 1
                continue
            if line.startswith('Retrieved from "https://en.wikipedia.org/'):
                continue
            # Numeric Wikipedia citation markers no longer have a reference list.
            line = re.sub(r'\[\d+(?:\s*[,\u2013-]\s*\d+)*\]', '', line)
            result.append(line)
        if cutoff != 'none':
            break
        result.append('')
    text = '\n'.join(result)
    text = re.sub(r'\n{3,}', '\n\n', text).strip() + '\n'
    return text, removed, cutoff


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'Resource_File' / 'sample, gk info')
    parser.add_argument('--output', type=Path, default=ROOT / 'Resource_File' / 'sample, gk info' / 'raw_text')
    args = parser.parse_args()
    folders = [args.output, ROOT / 'Resource_File' / 'sample, gk info' / 'extracted_knowledge',
               ROOT / 'Resource_File' / 'cache', ROOT / 'scripts', ROOT / 'backend', ROOT / 'frontend']
    for folder in folders:
        created = not folder.exists()
        folder.mkdir(parents=True, exist_ok=True)
        print(f'{"Created" if created else "Exists"}: {folder.relative_to(ROOT) if folder.is_relative_to(ROOT) else folder}')
    pdfs = sorted(p for p in args.source.iterdir() if p.is_file() and p.suffix.lower() == '.pdf')
    if not pdfs:
        print(f'No PDFs found in {args.source}', file=sys.stderr)
        return 1
    failures = 0
    for pdf in pdfs:
        try:
            reader = PdfReader(pdf)
            pages = [page.extract_text(extraction_mode='layout') or '' for page in reader.pages]
            if any(not page.strip() for page in pages):
                raise ValueError('One or more pages have no extractable text; OCR may be required')
            text, removed, cutoff = clean_pages(pages)
            if not text.strip():
                raise ValueError('No article text remained after cleaning')
            output = args.output / (pdf.stem + '.txt')
            output.write_text(text, encoding='utf-8')
            print(f'Wrote {output.name}: {len(reader.pages)} pages, {len(text):,} characters; '
                  f'{removed} margin lines removed; end-matter cutoff: {cutoff}')
        except Exception as exc:
            failures += 1
            print(f'FAILED {pdf.name}: {exc}', file=sys.stderr)
    print(f'Summary: {len(pdfs) - failures}/{len(pdfs)} articles converted; {failures} failures. Source PDFs unchanged.')
    return int(bool(failures))


if __name__ == '__main__':
    raise SystemExit(main())
