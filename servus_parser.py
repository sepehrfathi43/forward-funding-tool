"""Native reader for the supplied Servus All in One / Business Plan 150 statements."""
import hashlib
import io
import re
from datetime import datetime, date
from decimal import Decimal
import pdfplumber
from statement_validation import parse_money, MONEY_PATTERN

CURRENCY_ISSUE = 'Currency not printed explicitly; verify CAD before underwriting.'
MONEY = MONEY_PATTERN

def money(text):
    return parse_money(text)

def parse_servus(pdf_bytes, filename, doc):
    sha = hashlib.sha256(pdf_bytes).hexdigest()
    pages = [page.extract_text(x_tolerance=2) or '' for page in doc.pages]
    text = '\n'.join(pages)
    issues = []
    result = dict(source_file=filename, source_sha256=sha, adapter='servus_business_150',
                  extraction_method='native_text', status='review_required', transactions=[], issues=issues,
                  statement_counts={'debits': None, 'credits': None}, warnings=[
                      'Printed transaction counts are not provided by this layout; totals and every running balance are checked.'])
    period = re.search(r'For the period ending ([A-Za-z]+ \d{1,2}, \d{4})', pages[0])
    member = re.search(r'Member Number:\s*(\d+)', pages[0])
    accounts = set(re.findall(r'Business Plan 150 #(\d+)', text))
    other_sections = {name for name, _ in re.findall(r'^(.+?) #(\d+)(?: \(continued\))?$', text, re.M)
                      if name not in {'Business Plan 150', 'Servus Rewards', 'Loan'}}
    if other_sections: issues.append('Additional account sections need extraction/review: ' + ', '.join(sorted(other_sections)))
    for rewards in re.findall(r'Servus Rewards #0\n(.*?)(?=Business Plan|\Z)', text, re.S):
        amounts=re.search(r'Total (' + MONEY + ') (' + MONEY + ')', rewards)
        if not amounts or any(money(amounts[i]) != 0 for i in [1,2]):
            issues.append('Nonzero or unreadable Servus Rewards activity requires separate review.')
    if not period or not member or len(accounts) != 1:
        issues.append('Servus account or period is ambiguous; this adapter requires one Business Plan 150 account.')
        return result
    end = datetime.strptime(period[1], '%B %d, %Y').date(); start = date(end.year, end.month, 1)
    account = next(iter(accounts))
    currency = 'CAD' if re.search(r'\bCAD\b|Canadian dollars', text, re.I) else None
    if re.search(r'\bUSD\b|US dollars', text, re.I): currency = 'USD'
    if currency is None: issues.append(CURRENCY_ISSUE)
    elif currency != 'CAD': issues.append('Only CAD is supported for underwriting.')
    result.update(account_id=f'servus:{member[1]}:chequing:{account}', currency=currency,
                  currency_review_required=currency is None, period_start=start.isoformat(), period_end=end.isoformat())
    opening = closing = previous = totals = None
    active = False; finished = False; rows = result['transactions']
    for pn, page_text in enumerate(pages, 1):
        if not page_text.strip(): issues.append(f'Page {pn}: no text; inspect page contents.')
        for line in page_text.splitlines():
            if line.startswith(f'Business Plan 150 #{account}'):
                if finished: issues.append(f'Page {pn}: duplicate account section after totals.')
                active = True; continue
            if not active: continue
            if re.match(r'(?:LOANS|Loan #|MEMBERSHIP SUMMARY|Servus Rewards|.* #\d+(?: \(continued\))?)$', line):
                issues.append(f'Page {pn}: another section began before the account totals.'); active = False; continue
            match = re.fullmatch(r'Total (' + MONEY + r') (' + MONEY + r')', line)
            if match:
                totals = (abs(money(match[1])), money(match[2])); active = False; finished = True; continue
            match = re.fullmatch(r'([A-Za-z]{3} \d{2}) (Opening|Closing) Balance (' + MONEY + r')', line)
            if match:
                if match[2] == 'Opening':
                    if opening is not None: issues.append('Duplicate opening balance.')
                    opening = previous = money(match[3])
                else: closing = money(match[3])
                continue
            match = re.fullmatch(r'([A-Za-z]{3} \d{2}) (.*?) (' + MONEY + r') (' + MONEY + r')', line)
            if match:
                tx_date = datetime.strptime(match[1] + ' ' + str(end.year), '%b %d %Y').date()
                amount, balance = money(match[3]), money(match[4])
                if not start <= tx_date <= end: issues.append(f'Page {pn}: transaction outside statement period.')
                if rows and tx_date.isoformat() < rows[-1]['date']: issues.append(f'Page {pn}: transaction dates out of order.')
                if previous is not None and previous + amount != balance:
                    issues.append(f'Page {pn}, transaction {len(rows)+1}: running balance mismatch.')
                if amount == 0: issues.append(f'Page {pn}: zero transaction needs review.')
                rows.append(dict(id=f'{sha[:16]}:servus:{len(rows)+1}', page=pn, top=None,
                    date=tx_date.isoformat(), month=tx_date.strftime('%Y-%m'), description=match[2],
                    amount=str(abs(amount)), tx_type='credit' if amount > 0 else 'debit',
                    balance=str(balance), source_file=filename))
                previous = balance
            elif re.match(r'[A-Za-z]{3} \d{2} ', line):
                issues.append(f'Page {pn}: unparsed transaction: {line}')
            elif rows and rows[-1]['page'] == pn and not re.search(
                    r'^(Date Description|Toll free|Member Number|For the period|Credit Limit|Opening Interest|Frequency|Next Payment|PAGE)', line):
                if line.strip(): rows[-1]['description'] += ' ' + line.strip()
    debit = sum((Decimal(r['amount']) for r in rows if r['tx_type'] == 'debit'), Decimal(0))
    credit = sum((Decimal(r['amount']) for r in rows if r['tx_type'] == 'credit'), Decimal(0))
    if opening is None or closing is None or not rows: issues.append('Opening, closing, or transaction data missing.')
    if totals is None: issues.append('Independent statement totals missing.')
    elif totals != (debit, credit): issues.append('Statement debit or credit total mismatch.')
    if closing != previous: issues.append('Last transaction balance does not match closing balance.')
    if opening is not None and closing is not None and opening + credit - debit != closing:
        issues.append('Opening/closing balance equation does not reconcile.')
    # Preserve loan evidence separately; its transfer already appears among account debits.
    loan_sections = re.findall(r'Loan #(\d+)\n(.*?)(?=Loan #|MEMBERSHIP SUMMARY|\Z)', text, re.S)
    loans = []
    for loan_no, section in loan_sections:
        payment = re.search(r'Monthly Regular Payment Amount\(\$\)\s*(' + MONEY + ')', section)
        loans.append({'loan_number': loan_no, 'monthly_payment': str(abs(money(payment[1]))) if payment else None})
    limit = re.search(r'Credit Limit \(\$\)\s*(' + MONEY + ')', text)
    result.update(opening_balance=str(opening) if opening is not None else None,
        closing_balance=str(closing) if closing is not None else None,
        last_transaction_balance=str(previous) if previous is not None else None,
        debits=str(debit), credits=str(credit), running_balance_checks=len(rows),
        statement_totals={'debits': str(totals[0]), 'credits': str(totals[1])} if totals else {},
        extracted_counts={'debits': sum(r['tx_type']=='debit' for r in rows), 'credits': sum(r['tx_type']=='credit' for r in rows)},
        credit_limit=str(money(limit[1])) if limit else None, disclosed_loans=loans)
    result['status'] = 'review_required' if issues else 'reconciled_candidate_review_required'
    return result

def confirm_cad(results, verified):
    """Explicit source verification resolves only the missing-currency issue."""
    import copy
    updated = copy.deepcopy(results)
    for result in updated:
        if not result.get('currency_review_required'): continue
        result['currency'] = 'CAD' if verified else None
        result['currency_source'] = 'underwriter_confirmation' if verified else 'not_printed'
        result['issues'] = [i for i in result.get('issues', []) if i != CURRENCY_ISSUE]
        if not verified: result['issues'].append(CURRENCY_ISSUE)
        result['status'] = ('review_required' if result['issues'] else
                            'ai_reconciled_candidate_review_required' if result.get('ai_review_required') else
                            'reconciled_candidate_review_required')
    return updated
