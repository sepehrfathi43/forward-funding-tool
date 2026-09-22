"""Coordinate-based Vancity business reader; reconcile each daily banking account."""
import re
from datetime import datetime
from rbc_td_parser import _base, _word_lines, _add_row, _finish
from statement_validation import MONEY_TOKEN, parse_money, validate_statement
from servus_parser import CURRENCY_ISSUE


def parse_vancity(data, filename, doc):
    root = _base(data, filename, 'vancity_business')
    root.update(account_statements=[], exclude_from_ledger=True)
    first = doc.pages[0].extract_text() or ''
    compact = re.sub(r'\s', '', first)
    period = re.search(r'STATEMENTPERIOD:(\d{2}[A-Z]{3}\d{4})to(\d{2}[A-Z]{3}\d{4})', compact)
    if not period:
        root['issues'].append('Vancity statement period missing'); return root
    start, end = [datetime.strptime(s, '%d%b%Y').date() for s in period.groups()]
    summary = re.split(r'TOTAL\s*NUMBER\s*OF\s*CHEQUES', first)[0]
    headers = list(re.finditer(r'INDEPENDENT\s*BUSINESS\s*ACCOUNT\s*#(\d+)', summary))
    accounts = {}; totals = {}
    for i, header in enumerate(headers):
        block = summary[header.end():headers[i+1].start() if i+1 < len(headers) else len(summary)]
        values = [parse_money(m.group()) for m in MONEY_TOKEN.finditer(block)]
        if len(values) != 4:
            root['issues'].append('Could not read four summary amounts for account ' + header[1]); continue
        number = header[1]
        r = _base(data, filename, 'vancity_business')
        r.update(account_id='vancity:'+number, period_start=start.isoformat(), period_end=end.isoformat(),
                 currency=None, currency_review_required=True, extraction_method='native_text')
        r['issues'].append(CURRENCY_ISSUE)
        accounts[number] = r; totals[number] = values
        root['account_statements'].append(r)
    if not accounts:
        root['issues'].append('No daily banking account summaries found'); return root
    current = None; bounds = None; pending = None; seen = set()
    for pn, page in enumerate(doc.pages, 1):
        bounds = None
        for y, words in _word_lines(page):
            raw = ' '.join(w['text'] for w in words)
            compact = re.sub(r'\s', '', raw)
            header = re.search(r'INDEPENDENTBUSINESSACCOUNT#(\d+)', compact)
            if header:
                if pending and current:
                    current['issues'].append('Incomplete transaction before account heading')
                if pn > 1 and header[1] not in accounts:
                    root['issues'].append('Activity account absent from parsed summary: '+header[1])
                current = accounts.get(header[1]); bounds = None; pending = None
                continue
            if compact == 'INVESTMENTS':
                if current:
                    current['warnings'].append('Statement also contains investments; investment activity is excluded from the daily banking ledger.')
                current = None; bounds = None; pending = None; continue
            labels = {w['text'].upper(): w['x0'] for w in words}
            if current is not None and {'DATE','DESCRIPTION','WITHDRAWALS','DEPOSITS','BALANCE'} <= labels.keys():
                bounds = (labels['DESCRIPTION']-3, labels['WITHDRAWALS']-10, labels['DEPOSITS']-10, labels['BALANCE']-10)
                seen.add(current['account_id']); continue
            if current is None or bounds is None: continue
            descx, dx, cx, bx = bounds
            daytext = ''.join(w['text'] for w in words if w['x0'] < descx)
            match = re.fullmatch(r'(\d{2})([A-Z]{3})', daytext)
            desc = ' '.join(w['text'] for w in words if descx <= w['x0'] < dx)
            if match:
                if pending: current['issues'].append('Incomplete transaction before page '+str(pn))
                year = start.year + (start.month > end.month and datetime.strptime(match[2], '%b').month < start.month)
                day = datetime.strptime(match[1]+match[2]+str(year), '%d%b%Y').date()
                pending = [pn, y, day, desc]
            elif pending:
                pending[3] += ' '+desc
            else: continue
            cells = [' '.join(w['text'] for w in words if left <= w['x0'] < right) for left, right in [(dx,cx),(cx,bx),(bx,1000)]]
            if not any(cells): continue
            try:
                debit, credit, balance = [parse_money(c) if c else None for c in cells]
                if debit is None and credit is None:
                    if 'INTEREST RATE CHANGE' not in pending[3]:
                        current['issues'].append('Unrecognized balance-only activity on page '+str(pn))
                else:
                    _add_row(current, filename, *pending[:3], pending[3], debit, credit, balance)
                pending = None
            except ValueError:
                current['issues'].append('Unusable amount cell on page '+str(pn)); pending = None
    if pending: current['issues'].append('Incomplete final transaction')
    for number, r in accounts.items():
        opening, debit, credit, closing = totals[number]
        if r['account_id'] not in seen: r['issues'].append('Account activity section missing')
        _finish(r, opening, closing, {'debits':debit, 'credits':credit})
        validate_statement(r)
    root['status'] = 'review_required' if root['issues'] or any(r['issues'] for r in accounts.values()) else 'reconciled_candidate_review_required'
    return root
