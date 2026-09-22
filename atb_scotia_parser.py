"""Local readers for the supplied ATB consolidated and Scotia business PDFs."""
import hashlib
import re
from datetime import date, datetime
from decimal import Decimal

from servus_parser import CURRENCY_ISSUE
from statement_validation import parse_money


def _lines(page):
    grouped = []
    words = page.dedupe_chars().extract_words(x_tolerance=2, y_tolerance=3)
    for word in sorted(words, key=lambda w: (w['top'], w['x0'])):
        if not grouped or abs(grouped[-1][0] - word['top']) > 3:
            grouped.append((word['top'], [word]))
        else:
            grouped[-1][1].append(word)
    return [(y, sorted(ws, key=lambda w: w['x0'])) for y, ws in grouped]


def _money(value):
    return parse_money(value)


def _date(value):
    compact = re.sub(r'\s', '', value)
    return datetime.strptime(compact, '%b%d,%Y' if ',' in compact else '%b%d%Y').date()


def _base(data, filename, adapter):
    return dict(source_file=filename, source_sha256=hashlib.sha256(data).hexdigest(),
                adapter=adapter, extraction_method='native_text', transactions=[],
                issues=[], warnings=[], status='review_required')


def expand_statement_results(results):
    """Expose every account while retaining any document-level incompleteness."""
    expanded = []
    for result in results:
        if 'account_statements' not in result:
            expanded.append(result)
            continue
        expanded.extend(result['account_statements'])
        if result['issues'] or not result['account_statements']:
            blocker = {k: v for k, v in result.items() if k != 'account_statements'}
            blocker.update(transactions=[], status='review_required')
            expanded.append(blocker)
    return expanded


def _finish(result, previous, checks):
    rows = result['transactions']; issues = result['issues']
    sums = {side + 's': sum((Decimal(r['amount']) for r in rows if r['tx_type'] == side), Decimal('0.00'))
            for side in ['debit', 'credit']}
    result.update({k: str(v) for k, v in sums.items()})
    result.update(last_transaction_balance=str(previous) if previous is not None else None,
                  running_balance_checks=checks)
    for field in ['account_id', 'period_start', 'period_end', 'opening_balance', 'closing_balance']:
        if result.get(field) is None: issues.append('Missing ' + field)
    for key, value in sums.items():
        if result.get('statement_totals', {}).get(key) != str(value):
            issues.append('Printed ' + key + ' total mismatch or missing')
        if result.get('statement_counts', {}).get(key) != sum(r['tx_type'] == key[:-1] for r in rows):
            issues.append('Printed ' + key + ' count mismatch or missing')
    opening, closing = result.get('opening_balance'), result.get('closing_balance')
    if opening is not None and closing is not None:
        if Decimal(opening) + sums['credits'] - sums['debits'] != Decimal(closing):
            issues.append('Opening/closing equation mismatch')
        if previous != Decimal(closing): issues.append('Last transaction/closing balance mismatch')
    result['status'] = 'review_required' if issues else 'reconciled_candidate_review_required'


def _append(result, pn, y, day, desc, debit, credit, balance, previous):
    if (debit is None) == (credit is None) or balance is None:
        raise ValueError('Expected one amount and a running balance')
    amount = credit if credit is not None else debit
    if amount <= 0: raise ValueError('Expected a positive transaction amount')
    if not result['period_start'] <= day.isoformat() <= result['period_end']:
        raise ValueError('Transaction date outside the statement period')
    if result['transactions'] and day.isoformat() < result['transactions'][-1]['date']:
        raise ValueError('Transaction dates out of order')
    if previous is None or previous + (credit or 0) - (debit or 0) != balance:
        result['issues'].append(f'Page {pn}, y={y:.2f}: running balance mismatch')
    result['transactions'].append(dict(
        id=f"{result['source_sha256'][:16]}:{pn}:{y:.2f}", account_id=result['account_id'],
        page=pn, top=round(y, 2), date=day.isoformat(), month=day.strftime('%Y-%m'),
        description=desc, amount=str(amount), balance=str(balance),
        tx_type='credit' if credit is not None else 'debit', source_file=result['source_file']))
    return balance


def _atb_description(desc):
    # Text-layer spacing only; preserve the original in raw_description.
    for source, replacement in [('LoanDisbursement','Loan Disbursement'),
        ('InterestPayment','Interest Payment'), ('TransferFrom','Transfer From '),
        ('TransferTo','Transfer To '), ('DirectDebit','Direct Debit '),
        ('InvestmentMERCHPAD','Investment MERCH PAD'), ('Fees/DuesINFINITYLEASIN','Fees/Dues INFINITY LEASIN'),
        ('LoansRBCLOANPYMT','Loans RBC LOAN PYMT'), ('BillPayment','Bill Payment '),
        ('INTERACe-TransferReceived','INTERAC e-Transfer Received'),
        ('Interace-TransferReceived','INTERAC e-Transfer Received'),
        ('INTERACe-TransferSent','INTERAC e-Transfer Sent')]:
        desc = desc.replace(source, replacement)
    return desc


def parse_atb(data, filename, doc):
    root = _base(data, filename, 'atb_consolidated'); root['account_statements'] = []
    first = doc.pages[0].extract_text(x_tolerance=2) or ''
    expected_accounts = set(re.findall(r'#(\d{11})', first))
    if 'Deposit Account Statement' in first:
        expected_accounts.update(re.findall(r'(\d{11})\s*Transit\s*#', first))
    currency = 'CAD' if re.search(r'\bCAD\b', first) else None
    active = False; result = None; previous = None; checks = 0; bounds = None
    for pn, page in enumerate(doc.pages, 1):
        page_lines = _lines(page)
        for y, ws in page_lines:
            raw = ' '.join(w['text'] for w in ws); compact = re.sub(r'\s', '', raw)
            account = re.search(r'(\d{11})Transit#(\d{5}-\d{3})', compact)
            if account:
                if result is not None: _finish(result, previous, checks)
                result = _base(data, filename, 'atb_consolidated')
                result.update(account_id='atb:' + account[2] + ':' + account[1],
                              currency=currency, currency_review_required=currency is None,
                              statement_counts={}, statement_totals={})
                if currency is None: result['issues'].append(CURRENCY_ISSUE)
                root['account_statements'].append(result)
                active = False; previous = None; checks = 0; bounds = None
                continue
            if result is None: continue
            opening = re.fullmatch(r'Yourbalanceforwardon([A-Za-z]+\d{1,2},\d{4})(-?\$[\d,.]+)', compact)
            closing = re.fullmatch(r'Yourclosingbalanceon([A-Za-z]+\d{1,2},\d{4})=(-?\$[\d,.]+)', compact)
            total = re.fullmatch(r'(Debits|Credits)toyouraccount\((\d+)items?\)[-+]\$([\d,.]+)', compact)
            if opening:
                result.update(period_start=_date(opening[1]).isoformat(), opening_balance=str(_money(opening[2])))
                previous = _money(opening[2]); continue
            if closing:
                result.update(period_end=_date(closing[1]).isoformat(), closing_balance=str(_money(closing[2]))); continue
            if total:
                key = total[1].lower(); result['statement_counts'][key] = int(total[2])
                result['statement_totals'][key] = str(_money(total[3])); continue
            if compact.startswith('DateDescription') and 'Balance($)' in compact:
                money_headers = [w for w in ws if w['text'].lower().startswith('account(')]
                balance_header = next((w for w in ws if w['text'].startswith('Balance(')), None)
                if len(money_headers) != 2 or balance_header is None:
                    result['issues'].append(f'Page {pn}: incomplete amount headers'); active=False; continue
                desc_start = next(w['x0'] for w in ws if w['text'] == 'Description')
                debit_end, credit_end = [w['x1'] for w in money_headers]
                bounds = (desc_start, money_headers[0]['x0'] - 35, (debit_end+credit_end)/2,
                          (credit_end+balance_header['x1'])/2, next(w['x0'] for w in ws if w['text']=='Date'))
                active = True; continue
            if not active or bounds is None: continue
            desc_start, amount_start, debit_credit, credit_balance, date_start = bounds
            prefix = ''.join(w['text'] for w in ws if date_start-2 <= w['x0'] < desc_start-2)
            dm = re.fullmatch(r'([A-Za-z]{3})(\d{1,2})', prefix)
            desc = ' '.join(w['text'] for w in ws if desc_start-2 <= w['x0'] < amount_start)
            if not dm:
                if result['transactions'] and desc and all(desc_start-2 <= w['x0'] < amount_start for w in ws):
                    result['transactions'][-1]['description'] += ' ' + _atb_description(desc)
                    result['transactions'][-1]['raw_description'] += ' ' + desc
                continue
            try:
                cells = [' '.join(w['text'] for w in ws if w['x0'] >= amount_start and lo <= w['x1'] < hi)
                         for lo, hi in [(amount_start,debit_credit),(debit_credit,credit_balance),(credit_balance,10000)]]
                debit, credit, balance = [_money(c) if c else None for c in cells]
                if re.sub(r'\s', '', desc).lower() == 'balanceforward':
                    if debit is not None or credit is not None or balance != previous:
                        raise ValueError('Balance-forward row disagrees with printed opening')
                    continue
                if re.sub(r'\s', '', desc).lower() == 'closingbalance':
                    if balance != Decimal(result['closing_balance']): raise ValueError('Closing row disagrees with summary')
                    active = False; continue
                end = date.fromisoformat(result['period_end']); month = datetime.strptime(dm[1], '%b').month
                day = date(end.year-(month > end.month), month, int(dm[2]))
                previous = _append(result,pn,y,day,_atb_description(desc),debit,credit,balance,previous)
                result['transactions'][-1]['raw_description'] = desc
                result['transactions'][-1]['source_date_evidence'] = {'printed_date':prefix,'normalized_date':day.isoformat(),'page':pn,'top':round(y,2),'method':'native_date_column'}
                checks += 1
            except (ValueError, KeyError) as exc:
                result['issues'].append(f'Page {pn}, y={y:.2f}: {exc}')
    if result is not None: _finish(result, previous, checks)
    actual_accounts = [r['account_id'].split(':')[-1] for r in root['account_statements']]
    if set(actual_accounts) != expected_accounts or len(actual_accounts) != len(set(actual_accounts)):
        root['issues'].append('Listed ATB accounts do not match extracted account sections; review all accounts.')
    if not actual_accounts: root['issues'].append('No ATB account sections extracted')
    root['exclude_from_ledger'] = bool(root['account_statements'])
    root['status'] = 'review_required' if root['issues'] or any(r['issues'] for r in root['account_statements']) else 'reconciled_candidate_review_required'
    return root


def parse_scotia(data, filename, doc):
    result = _base(data, filename, 'scotia_business')
    first = doc.pages[0].extract_text(x_tolerance=2) or ''
    match = re.search(r'Business Account\s+(\d{5}\s+\d{5}\s+\d{2})\s+([A-Za-z]+\s+\d+\s+\d{4})\s+([A-Za-z]+\s+\d+\s+\d{4})', first)
    if not match:
        result['issues'].append('Scotia account/statement period not found'); return result
    currency = 'CAD' if re.search(r'\bCAD\b', first) else None
    result.update(account_id='scotia:'+re.sub(r'\s','',match[1]), currency=currency,
                  currency_review_required=currency is None, period_start=_date(match[2]).isoformat(),
                  period_end=_date(match[3]).isoformat())
    if currency is None: result['issues'].append(CURRENCY_ISSUE)
    # Only the account summary above the transaction table is statement-wide.
    # A repeated summary below the table can be a page subtotal.
    summary_header=first.split('Account Details:',1)[0]
    summaries = re.findall(r'^\s*(\d+)\s+\$([\d,.]+)\s+(\d+)\s+\$([\d,.]+)\s*$', summary_header, re.M)
    if summaries:
        nd, vd, nc, vc = summaries[0]
        result.update(statement_counts={'debits':int(nd),'credits':int(nc)},
                      statement_totals={'debits':str(_money(vd)),'credits':str(_money(vc))})
        if any(summary != summaries[0] for summary in summaries): result['issues'].append('Conflicting printed Scotia summaries')
    previous = None; checks = 0
    for pn, page in enumerate(doc.pages, 1):
        active=False; bounds=None; header_found=False
        for y, ws in _lines(page):
            raw=' '.join(w['text'] for w in ws)
            if 'Withdrawals/Debits' in raw and 'Deposits/Credits' in raw and 'Description' in raw:
                desc_start=next(w['x0'] for w in ws if w['text']=='Description')
                debit_start=next(w['x0'] for w in ws if w['text']=='Withdrawals/Debits')
                credit_start=next(w['x0'] for w in ws if w['text']=='Deposits/Credits')
                balance_start=next(w['x0'] for w in ws if w['text']=='Balance')
                bounds=(desc_start,debit_start-10,credit_start-10,balance_start-10)
                active=True; header_found=True; continue
            if 'No. of Debits' in raw: active=False
            if not active or bounds is None: continue
            ds, da, dc, cb = bounds
            prefix=''.join(w['text'] for w in ws if w['x0']<ds-2)
            desc=' '.join(w['text'] for w in ws if ds-2<=w['x0']<da)
            if not re.fullmatch(r'\d{2}/\d{2}/\d{4}',prefix):
                if result['transactions'] and desc and all(ds-2<=w['x0']<da for w in ws):
                    result['transactions'][-1]['description']+=' '+desc
                continue
            try:
                cells=[' '.join(w['text'] for w in ws if lo<=w['x1']<hi) for lo,hi in [(da,dc),(dc,cb),(cb,10000)]]
                debit,credit,balance=[_money(c) if c else None for c in cells]
                if desc == 'BALANCE FORWARD':
                    if debit is not None or credit is not None or balance is None: raise ValueError('Invalid balance-forward row')
                    if previous is not None and previous != balance: raise ValueError('Balance-forward continuity mismatch')
                    if result.get('opening_balance') is None: result['opening_balance']=str(balance)
                    previous=balance; continue
                day=datetime.strptime(prefix,'%m/%d/%Y').date()
                previous=_append(result,pn,y,day,desc,debit,credit,balance,previous); checks+=1
            except ValueError as exc: result['issues'].append(f'Page {pn}, y={y:.2f}: {exc}')
        page_text=page.extract_text(x_tolerance=2) or ''
        supplement = ('Deposit Interest' in page_text and 'Calculated Interest' in page_text and result['account_id'].split(':',1)[1] in re.sub(r'\s','',page_text))
        footer_only = ('GST Registration' in page_text and not re.search(r'\d{2}/\d{2}/\d{4}', page_text) and 'Account Details' not in page_text and 'Total Amount - Debits' not in page_text and not re.search(r'\d+[.,]\d{2}\b',page_text))
        if supplement and 'Currency: CAD' in page_text:
            result['currency']='CAD'; result['currency_review_required']=False
            result['issues']=[i for i in result['issues'] if i != CURRENCY_ISSUE]
        if not header_found and not supplement and not footer_only and not ('Service Charge' in page_text and 'Total Service Charges' in page_text):
            result['issues'].append(f'Page {pn}: unidentified page without transaction table')
    result['closing_balance']=str(previous) if previous is not None else None
    result['closing_balance_source']='last printed transaction balance; checked against opening and printed totals'
    _finish(result,previous,checks)
    return result


def activity_screen_blocker(data, filename):
    result=_base(data,filename,'scotia_activity_screen')
    result.update(document_type='partial_activity_screen',exclude_from_ledger=True,
        issues=['This is a partial online activity screen, not a complete bank statement. '
                'Balances are clipped and rows may repeat a statement. Upload the full official statement for this period.'])
    return result
