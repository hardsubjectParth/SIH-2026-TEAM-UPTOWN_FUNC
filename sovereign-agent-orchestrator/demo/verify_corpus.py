#!/usr/bin/env python3
"""Checks that the generated corpus can still prove what it claims to prove.

A synthetic corpus degrades quietly. Edit a document to read better and the
serial that was supposed to be vision-only leaks into a text file; shorten a
section and a text page drops under the 200-character floor and gets routed to
the vision model; rename a file and an eval case starts scoring a miss that has
nothing to do with retrieval quality. In every case the demo still runs and the
numbers still look fine, while the thing being demonstrated has quietly stopped
being demonstrated.

Each check below is one of those failure modes, asserted against the real
predicates in app/rag/service.py and app/access.py rather than against a copy of
their logic. Runs offline in under a second; no API and no model required.

    python demo/verify_corpus.py --corpus demo/corpus
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.access import resolve_upload_tier  # noqa: E402
from app.rag.service import RagService  # noqa: E402

BOOKKEEPING = {'manifest.json', 'eval_cases.json', 'uploaded.json'}
IMAGE_SUFFIXES = {'.png', '.jpg', '.jpeg', '.tiff', '.bmp'}

# The ideal reading of each vision-only image: what a working vision model
# should return. The heuristics are asserted against these, not against whatever
# a model happened to produce on the day.
IDEAL_READINGS = {
    'nameplate_p204b.png': 'KAVERI PUMPS LTD\nBFP P-204B\nSN 744DC0\n3300V  6.6A',
    'valve_tag_hv1127.png': 'HV-1127\nCL300 WCB',
}

# file -> (pages that must have no text layer, total pages). None means "must
# have a usable text layer on every page".
PDF_SHAPE = {
    'sop_pump_changeover.pdf': None,
    'supplier_bulletin_2026_09.pdf': None,
    'incident_memo_u3_trip.pdf': None,
    'scanned_inspection_report.pdf': ([1, 2, 3], 3),
    'mixed_manual_extract.pdf': ([4], 4),
}

# Every text document must run to more than one page: a single-page corpus reads as
# a toy, and the multi-page case is also where the pagination bug lived -- filling
# pages and spilling left a two-line final page under the 200-character floor, which
# sent a perfectly good text layer to the vision model.
MIN_PAGES = {
    'sop_pump_changeover.pdf': 2,
    'supplier_bulletin_2026_09.pdf': 2,
    'incident_memo_u3_trip.pdf': 2,
    'scanned_inspection_report.pdf': 3,
    'mixed_manual_extract.pdf': 4,
}


class Checks:
    def __init__(self):
        self.failures: list[str] = []

    def check(self, ok: bool, label: str, detail: str = ''):
        print(f'  {"PASS" if ok else "FAIL"}  {label}' + (f'  -- {detail}' if detail else ''))
        if not ok:
            self.failures.append(label)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--corpus', default='demo/corpus')
    args = parser.parse_args()

    corpus = Path(args.corpus)
    if not (corpus / 'manifest.json').exists():
        raise SystemExit(f'No manifest in {corpus}. Run: python demo/generate_corpus.py --out {corpus}')

    manifest = json.loads((corpus / 'manifest.json').read_text())
    cases = json.loads((corpus / 'eval_cases.json').read_text())
    documents = {d['file']: d for d in manifest['documents']}
    ground_truth = manifest['ground_truth']
    checks = Checks()
    # extract() needs no instance state, so an uninitialised object is enough to
    # reach it without standing up a database connection.
    service = RagService.__new__(RagService)

    print('Corpus contents')
    on_disk = {p.name for p in corpus.iterdir() if p.name not in BOOKKEEPING}
    checks.check(not (set(documents) - on_disk), 'every manifest document exists on disk',
                 ', '.join(sorted(set(documents) - on_disk)))
    checks.check(not (on_disk - set(documents)), 'every file on disk is in the manifest',
                 ', '.join(sorted(on_disk - set(documents))))
    unknown = [name for case in cases for name in case['expected_files'] if name not in documents]
    checks.check(not unknown, 'every eval case names a real document', ', '.join(sorted(set(unknown))))

    print('\nVision-only ground truth (the fact must not be reachable as text)')
    for key in ('nameplate_serial', 'valve_tag'):
        secret = ground_truth[key]
        leaks = []
        for name in sorted(documents):
            path = corpus / name
            if path.suffix.lower() in IMAGE_SUFFIXES:
                continue  # the image is where the fact is meant to live
            try:
                text = RagService.extract(service, path) or ''
            except Exception as exc:  # a corpus file the extractor cannot read is itself a failure
                checks.check(False, f'extract() succeeds on {name}', str(exc))
                continue
            if secret.lower() in text.lower():
                leaks.append(name)
        checks.check(not leaks, f'{key} ({secret}) appears in no extractable text', ', '.join(leaks))

    print('\nOCR heuristics on the ideal readings')
    for name, reading in IDEAL_READINGS.items():
        kept = not RagService._vision_failed(reading)
        checks.check(kept, f'{name}: a correct vision reading is kept')
    tag = IDEAL_READINGS['valve_tag_hv1127.png']
    checks.check(RagService._ocr_is_unusable(tag),
                 'valve_tag_hv1127.png: the reading really is under the Tesseract floor',
                 'otherwise it no longer exercises the short-reading fix')

    print('\nImage routing (does Tesseract hand the page to the vision model?)')
    for name, document in sorted(documents.items()):
        if Path(name).suffix.lower() not in IMAGE_SUFFIXES:
            continue
        # This is the check that a flat, clean render of a nameplate silently
        # fails: Tesseract reads it perfectly, _ocr_is_unusable returns False,
        # the vision model is never called, and a demo built on "this proves
        # vision ran" proves nothing. Assert the routing rather than assume it.
        tesseract = RagService.extract(service, corpus / name) or ''
        routed_to_vision = RagService._ocr_is_unusable(tesseract)
        expects_vision = document['extraction_path'].startswith('vision')
        sample = tesseract.strip().replace('\n', ' ')[:38]
        # State the route asserted, not a fixed claim: two documents in this corpus
        # are recorded as staying on Tesseract, and printing "reaches the vision
        # model" against them would make the verifier itself misleading.
        route = 'reaches the vision model' if expects_vision else 'stays on Tesseract, as recorded'
        checks.check(routed_to_vision == expects_vision,
                     f'{name}: {route}',
                     f'tesseract got {len(tesseract.strip())} chars: {sample!r}')

    print('\nPDF page structure')
    for name, expected in PDF_SHAPE.items():
        scanned, count = RagService._pdf_pages_without_text(corpus / name)
        if expected is None:
            checks.check(not scanned, f'{name}: every page has a usable text layer',
                         f'thin pages: {scanned}' if scanned else f'{count} pages')
        else:
            want_pages, want_count = expected
            checks.check((scanned, count) == (want_pages, want_count),
                         f'{name}: scanned pages {want_pages} of {want_count}',
                         f'got {scanned} of {count}')
        checks.check(count >= MIN_PAGES[name], f'{name}: at least {MIN_PAGES[name]} pages', f'has {count}')

    print('\nUpload scope resolves to the intended tier')
    for name, document in sorted(documents.items()):
        try:
            tier = resolve_upload_tier(document['upload_as'], document['scope'])
        except Exception as exc:  # an invalid scope is a 422 at upload time
            checks.check(False, f'{name}: {document["upload_as"]} + {document["scope"]}', str(exc))
            continue
        checks.check(tier == document['tier'],
                     f'{name}: {document["upload_as"]} + {document["scope"]} -> {document["tier"]}',
                     f'resolves to {tier}' if tier != document['tier'] else '')

    print()
    if checks.failures:
        print(f'{len(checks.failures)} check(s) failed. The corpus no longer proves what it claims.')
        return 1
    print(f'All checks passed: {len(documents)} documents, {len(cases)} eval cases.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
