"""Evidence-preserving readers for Neo and Wise exports."""
import re
from datetime import datetime
from decimal import Decimal
from rbc_td_parser import _base, _word_lines, _add_row, _finish
from statement_validation import parse_money, validate_statement


def parse_neo(data, filename, doc):
    r=_base(data,filename,'neo_everyday'); first=doc.pages[0].extract_text() or ''
    period=re.search(r'([A-Z][a-z]{2} \d+, \d{4}) - ([A-Z][a-z]{2} \d+, \d{4})',first)
    if not period: raise ValueError('Neo statement period missing')
    start,end=[datetime.strptime(v,'%b %d, %Y').date() for v in period.groups()]
    account=re.search(r'Neo Everyday\n.*?\b(\d{8,})\b',first,re.S)
    if not account: raise ValueError('Neo account number missing')
    r.update(account_id='neo:'+account[1],currency='CAD' if '$CAD' in first else None,
             account_holder=first.split('Neo Everyday')[0].strip(), period_start=start.isoformat(),period_end=end.isoformat(),extraction_method='native_text')
    totals={}
    for label in ['Opening balance','Total credits','Total debits','Closing balance']:
        m=re.search(re.escape(label)+r'\s+(-?[\d,]+\.\d{2})',first)
        if not m: raise ValueError('Neo missing '+label)
        totals[label]=parse_money(m[1])
    r['printed_summary']={k:str(v) for k,v in totals.items()}
    for pn,page in enumerate(doc.pages[1:],2):
        active=False; previous=None
        for y,words in _word_lines(page):
            raw=' '.join(w['text'] for w in words)
            if 'Description Credits Debits Balance' in raw: active=True;continue
            if raw.startswith('The Neo Everyday account'): active=False
            if not active:continue
            tx=' '.join(w['text'] for w in words if w['x0']<80)
            posted=' '.join(w['text'] for w in words if 80<=w['x0']<135)
            desc=' '.join(w['text'] for w in words if 135<=w['x0']<400)
            if re.fullmatch(r'[A-Z][a-z]{2} \d{1,2}',tx):
                def day(v):
                    month=datetime.strptime(v,'%b %d').month
                    year=start.year+(start.month>end.month and month<start.month)
                    return datetime.strptime(v+' '+str(year),'%b %d %Y').date()
                cells=[' '.join(w['text'] for w in words if a<w['x1']<=b) for a,b in [(400,475),(475,540),(540,700)]]
                credit,debit,balance=[parse_money(c) if c else None for c in cells]
                _add_row(r,filename,pn,y,day(posted),desc,abs(debit) if debit is not None else None,credit,balance)
                previous=r['transactions'][-1]
                previous.update(transaction_date=day(tx).isoformat(),posted_date=day(posted).isoformat(),raw_debit=str(debit) if debit is not None else None,raw_text=raw)
            elif desc and previous:
                previous['description']+=' '+desc
                previous['raw_text']+=' '+raw
    _finish(r,totals['Opening balance'],totals['Closing balance'],{'debits':abs(totals['Total debits']),'credits':totals['Total credits']})
    return validate_statement(r)


def parse_wise(data,filename,doc):
    r=_base(data,filename,'wise_statement'); first=doc.pages[0].extract_text() or ''
    period=re.search(r'(\d+ [A-Za-z]+ \d{4}) \[GMT[^\]]*\] - (\d+ [A-Za-z]+ \d{4})',first)
    account=re.search(r'Account number Institution number\n.*?\n(\d+) \d+',first)
    if not period or not account:raise ValueError('Wise account or period missing')
    start,end=[datetime.strptime(v,'%d %B %Y').date() for v in period.groups()]
    currency=re.search(r'\b([A-Z]{3}) statement\b',first)
    closing=re.search(r'\b[A-Z]{3} on .*?\] (-?[\d,]+\.\d{2}) [A-Z]{3}',first)
    if not currency or not closing:raise ValueError('Wise currency or closing balance missing')
    holder=re.search(r'Account Holder Current\n(.+?) Account number',first)
    r.update(account_id='wise:'+account[1],account_holder=holder[1] if holder else None,currency=currency[1],period_start=start.isoformat(),period_end=end.isoformat(),extraction_method='native_text',source_order='newest_first')
    pending=None
    for pn,page in enumerate(doc.pages,1):
        for y,words in _word_lines(page):
            raw=' '.join(w['text'] for w in words)
            if raw.startswith('Download attachments'):break
            cells=[' '.join(w['text'] for w in words if a<w['x1']<=b) for a,b in [(380,440),(440,510),(510,610)]]
            # A transaction starts with a signed incoming/outgoing cell and balance.
            if cells[2] and (cells[0] or cells[1]):
                try:credit,debit,balance=[parse_money(c) if c else None for c in cells]
                except ValueError:continue
                if pending:r['issues'].append('Wise transaction missing its date/reference')
                pending=dict(page=pn,top=y,desc=' '.join(w['text'] for w in words if w['x0']<380),credit=credit,debit=debit,balance=balance,raw=raw)
                continue
            if pending:
                dt=re.match(r'(\d+ [A-Za-z]+ \d{4}) \|',raw)
                if dt:
                    day=datetime.strptime(dt[1],'%d %B %Y').date()
                    debit=pending['debit'];credit=pending['credit']
                    _add_row(r,filename,pending['page'],pending['top'],day,pending['desc'],abs(debit) if debit is not None else None,credit,pending['balance'])
                    row=r['transactions'][-1];ref=re.search(r'Transaction:\s*(\S+)',raw)
                    row.update(transaction_date=day.isoformat(),posted_date=None,raw_text=pending['raw']+' '+raw,bank_reference=ref[1] if ref else None)
                    pending=None
                elif not raw.startswith(('ref:','Description','Wise Payments','Need help')):
                    pending['desc']+=' '+raw
    if pending:r['issues'].append('Wise final transaction missing date/reference')
    # Reverse the entire source sequence, including each day's sequence.
    r['transactions'].reverse()
    rows=r['transactions']
    opening=None
    if rows:
        firstrow=rows[0];delta=Decimal(firstrow['amount'])*(1 if firstrow['tx_type']=='credit' else -1)
        opening=Decimal(firstrow['balance'])-delta
    _finish(r,opening,parse_money(closing[1]))
    r['statement_totals']={'debits':None,'credits':None}
    r['opening_balance_source']='derived_from_earliest_transaction'
    r['issues'].append('Wise opening balance is derived, not printed; verify complete period coverage and opening balance before underwriting.')
    r['warnings'].append('Wise does not print debit/credit grand totals; every available balance checkpoint is checked.')
    r['status']='review_required'
    return validate_statement(r)
