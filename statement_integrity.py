"""Explainable document screening, not document authentication or fraud proof."""
import hashlib
import io
import re
from datetime import timedelta

import pdfplumber
from pdf_access import open_pdf
from statement_validation import decimal_value, iso_day

VERSION = 1
LIMITATION = ('Screening cannot establish authenticity or detect every alteration. '
              'Editing software, revisions and annotations can have legitimate causes; '
              'reconciliation failures can also be extraction errors. Verify flags against bank originals.')


def inspect_pdf(data, filename):
    report = dict(version=VERSION, source_file=filename,
                  source_sha256=hashlib.sha256(data).hexdigest(), flags=[], limitation=LIMITATION)
    def flag(code, evidence, page=None):
        report['flags'].append(dict(code=code, evidence=evidence, page=page))
    # Raw syntax is only a weak signal; do not claim signature validation.
    if len(re.findall(rb'%%EOF', data)) > 1 and re.search(rb'/Prev\s+\d+', data):
        flag('PDF_REVISIONS', 'Multiple PDF revisions detected; signing or legitimate saving can also cause this.')
    try:
        with open_pdf(data) as doc:
            if getattr(doc, 'reader_recovery', None):
                flag('PDF_READER_RECOVERY', 'The primary reader failed; pages were recovered in memory using an independent PDF reader. This alone is not an alteration signal.')
                report['reader_recovery'] = doc.reader_recovery
            report['page_count'] = len(doc.pages)
            report['metadata'] = {k: str(v) for k, v in doc.metadata.items()
                                  if k in ('Creator', 'Producer', 'CreationDate', 'ModDate')}
            editor = ' '.join(str(doc.metadata.get(k, '')) for k in ('Creator', 'Producer'))
            if re.search(r'photoshop|illustrator|\bgimp\b|canva|\bword\b|libreoffice|\bfoxit\b|\bacrobat\b', editor, re.I):
                flag('EDITING_SOFTWARE', 'PDF metadata names editing software: ' + editor[:300])
            for number, page in enumerate(doc.pages, 1):
                annotations = [a for a in (page.annots or [])
                               if str(a.get('data', {}).get('Subtype', '')) not in ("/'Link'", '/Link')]
                if annotations:
                    flag('ANNOTATIONS', f'{len(annotations)} non-link annotations or form fields; inspect overlays.', number)
                positions = {}
                for char in page.chars:
                    if not str(char.get('text', '')).isdigit():
                        continue
                    key = (round(char['x0'], 1), round(char['top'], 1), round(char['x1'], 1))
                    positions.setdefault(key, set()).add(char['text'])
                if any(len(chars) > 1 for chars in positions.values()):
                    flag('OVERLAPPING_DIGITS', 'Different digits occupy the same position in the text layer.', number)
                if not (page.extract_text() or '').strip():
                    flag('NO_TEXT_LAYER', 'No readable text layer; automated text integrity checks are limited.', number)
            report['status'] = 'review_required' if report['flags'] else 'no_signals_detected'
    except Exception as exc:
        flag('SCREENING_UNAVAILABLE', 'Document screening failed: ' + type(exc).__name__)
        report['status'] = 'unavailable'
    return report


def statement_flags(results):
    """Financial consistency evidence kept separate from PDF editing signals."""
    flags = []
    for result in results:
        if result.get('exclude_from_ledger'):
            continue
        for issue in result.get('issues', []):
            if re.search(r'mismatch|does not|inconsistent|duplicat|outside|conflict', issue, re.I):
                flags.append(dict(source_file=result.get('source_file'), code='FINANCIAL_INCONSISTENCY', evidence=issue))
    ordered = sorted((r for r in results if not r.get('exclude_from_ledger')),
                     key=lambda r: (str(r.get('account_id')), str(r.get('period_start'))))
    for previous, current in zip(ordered, ordered[1:]):
        if not previous.get('account_id') or previous.get('account_id') != current.get('account_id'):
            continue
        if not previous.get('currency') or previous.get('currency') != current.get('currency'):
            continue
        try:
            # Same-date handoffs have bank-specific semantics; only test next-day boundaries.
            if iso_day(previous.get('period_end')) + timedelta(days=1) != iso_day(current.get('period_start')):
                continue
            close = decimal_value(previous.get('closing_balance'))
            opening = decimal_value(current.get('opening_balance'))
            if close != opening:
                flags.append(dict(source_file=current.get('source_file'), code='BALANCE_CONTINUITY',
                                  evidence=f'Previous closing {close} differs from next opening {opening}; previous file: {previous.get("source_file")}'))
        except (ValueError, TypeError):
            continue
    return flags
