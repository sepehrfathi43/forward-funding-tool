"""Coordinate-aware reader for CIBC Account Statement PDFs."""
import hashlib
import re
from datetime import date
from decimal import Decimal

from statement_validation import parse_money
from servus_parser import CURRENCY_ISSUE

MONTHS={m:i for i,m in enumerate('Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split(),1)}


def _lines(page):
    words=page.dedupe_chars().extract_words(x_tolerance=2,y_tolerance=3)
    groups=[]
    for word in sorted(words,key=lambda w:(w['top'],w['x0'])):
        if not groups or abs(groups[-1][0]-word['top'])>3:groups.append((word['top'],[word]))
        else:groups[-1][1].append(word)
    return [(y,sorted(ws,key=lambda w:w['x0'])) for y,ws in groups]


def _cell(words,left,right):
    text=' '.join(w['text'] for w in words if left-3<=w['x0']<right-3).strip()
    if not text:return None
    try:return parse_money(text)
    except ValueError:return None


def parse_cibc(pdf_bytes,filename,doc):
    sha=hashlib.sha256(pdf_bytes).hexdigest()
    pages=[p.extract_text(x_tolerance=2) or '' for p in doc.pages]
    first=pages[0]
    result=dict(source_file=filename,source_sha256=sha,adapter='cibc_account_statement',
        extraction_method='native_text',status='review_required',transactions=[],issues=[CURRENCY_ISSUE],
        warnings=['CIBC statements do not print a currency code; confirm CAD before underwriting.',
                  'Printed transaction counts are not provided by this layout; totals and balances are checked.'],
        currency=None,currency_review_required=True)
    period=re.search(r'For\s+([A-Za-z]{3})\s+(\d{1,2})\s+to\s+([A-Za-z]{3})\s+(\d{1,2}),\s*(\d{4})',first,re.I)
    account=re.search(r'Account number\s+(\d{2}-\d+)',first,re.I)
    if not period or not account:
        result['issues'].append('CIBC account number or statement period is missing.')
        return result
    sm,sd,em,ed,year=period.groups();smn,emn=MONTHS[sm.title()],MONTHS[em.title()]
    start=date(int(year),smn,int(sd));end=date(int(year),emn,int(ed))
    account_id='cibc:'+account[1].replace(' ','')
    result.update(account_id=account_id,period_start=start.isoformat(),period_end=end.isoformat())
    opening=closing=previous=None;rows=result['transactions'];expected=None
    for pn,page in enumerate(doc.pages,1):
        line_groups=_lines(doc.pages[pn-1])
        header=next(((y,ws) for y,ws in line_groups if all(x in [w['text'] for w in ws] for x in ['Date','Description','Withdrawals','Deposits','Balance'])),None)
        if header is None:
            # Continuation pages repeat the heading at a lower level; a page
            # without it can still be a statement notice and is not activity.
            continue
        hy,hws=header
        withdrawal=next(w for w in hws if w['text']=='Withdrawals')
        deposit=next(w for w in hws if w['text']=='Deposits')
        balance=next(w for w in hws if w['text']=='Balance')
        desc_min=next(w['x0'] for w in hws if w['text']=='Description')
        wd_x=withdrawal['x0'];dp_x=deposit['x0'];bal_x=balance['x0']
        current_date=None
        for y,ws in line_groups:
            if y<=hy:continue
            raw=' '.join(w['text'] for w in ws)
            compact=re.sub(r'\s+','',raw).lower()
            if 'transactiondetails' in compact and 'continued' not in compact:continue
            date_words=[w['text'] for w in ws if w['x0']<desc_min]
            date_match=re.fullmatch(r'([A-Za-z]{3})\s*(\d{1,2})',' '.join(date_words),re.I)
            desc=' '.join(w['text'] for w in ws if desc_min-2<=w['x0']<wd_x-3).strip()
            wd=_cell(ws,wd_x,dp_x);dp=_cell(ws,dp_x,bal_x);bal=_cell(ws,bal_x,10000)
            if date_match:
                try:tx_day=date(int(year),MONTHS[date_match[1].title()],int(date_match[2]))
                except (KeyError,ValueError):tx_day=None
                if tx_day is None or not start<=tx_day<=end:
                    if 'openingbalance' not in compact and 'balanceforward' not in compact:result['issues'].append(f'Page {pn}: date outside statement period: {raw}')
                    continue
                current_date=tx_day
                if 'openingbalance' in compact:
                    if bal is not None:opening=previous=bal
                    continue
                if 'closingbalance' in compact:
                    if bal is not None:closing=bal
                    continue
                if 'balanceforward' in compact:continue
            # CIBC prints the date only on the first transaction of a day;
            # subsequent same-day rows carry no date and inherit current_date.
            tx_day = tx_day if date_match else current_date
            if (wd is None)==(dp is None) or bal is None or tx_day is None:
                if rows and desc and not any(x in compact for x in ['page','continued','transactiondetails']):
                    rows[-1]['description']+=' '+desc
                continue
            amount=dp if dp is not None else wd
            if amount<=0:result['issues'].append(f'Page {pn}: non-positive transaction amount.');continue
            if previous is not None and previous+(amount if dp is not None else -amount)!=bal:
                result['issues'].append(f'Page {pn}: running balance mismatch at {tx_day.isoformat()}.')
            previous=bal
            rows.append(dict(id=f'{sha[:16]}:{pn}:{y:.2f}',page=pn,top=round(y,2),date=tx_day.isoformat(),
                month=tx_day.strftime('%Y-%m'),description=desc,amount=str(amount),
                tx_type='credit' if dp is not None else 'debit',balance=str(bal),source_file=filename))
    text='\n'.join(pages)
    summary=re.search(r'Withdrawals\s+-\s*([\d,]+\.\d{2}).*?Deposits\s+\+\s*([\d,]+\.\d{2}).*?Closing balance on .*?=\s*(-?\$?[\d,]+\.\d{2})',text,re.S|re.I)
    if summary:
        expected={'debits':parse_money(summary[1]),'credits':parse_money(summary[2])}
        closing=parse_money(summary[3]);result['statement_totals']={k:str(v) for k,v in expected.items()}
    else:result['issues'].append('CIBC printed summary totals not found.')
    debits=sum((Decimal(r['amount']) for r in rows if r['tx_type']=='debit'),Decimal(0));credits=sum((Decimal(r['amount']) for r in rows if r['tx_type']=='credit'),Decimal(0))
    if expected and (expected['debits']!=debits or expected['credits']!=credits):result['issues'].append('CIBC printed total does not match extracted transactions.')
    if opening is None:result['issues'].append('CIBC opening balance missing.')
    if closing is None:result['issues'].append('CIBC closing balance missing.')
    if opening is not None and closing is not None and opening+credits-debits!=closing:result['issues'].append('CIBC opening/closing equation does not reconcile.')
    result.update(opening_balance=str(opening) if opening is not None else None,closing_balance=str(closing) if closing is not None else None,
        last_transaction_balance=str(previous) if previous is not None else None,debits=str(debits),credits=str(credits),
        statement_counts={'debits':None,'credits':None},running_balance_checks=sum(r.get('balance') is not None for r in rows))
    result['status']='review_required' if len(result['issues'])>1 else 'review_required'
    return result
