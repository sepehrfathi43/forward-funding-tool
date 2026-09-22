"""Conservative extraction prototype for the supplied BMO and National Bank layouts.
Not a universal parser or underwriting decision engine. Unsupported files fail closed.
Usage: python statement_parser.py input.pdf --output ledger.json
Requires pdfplumber. Amounts serialize as decimal strings; preserves repeated rows.
"""
import argparse
from datetime import date
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import unicodedata
import pdfplumber
from statement_validation import parse_money, validate_statement

MONTHS = {m: i for i,m in enumerate('Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split(),1)}

def money(value):
    return parse_money(value)


def norm(s):
    return ''.join(c for c in unicodedata.normalize('NFKD',s) if not unicodedata.combining(c)).lower()

def lines(page):
    result=[]
    for w in sorted(page.dedupe_chars().extract_words(x_tolerance=2,y_tolerance=3),key=lambda w:(w['top'],w['x0'])):
        if not result or abs(result[-1][0]-w['top'])>3: result.append((w['top'],[w]))
        else: result[-1][1].append(w)
    return [(y,sorted(ws,key=lambda w:w['x0'])) for y,ws in result]

def extract(path):
    return validate_statement(_extract(path))


def _extract(path):
    path=Path(path);sha=hashlib.sha256(path.read_bytes()).hexdigest()
    result={'source_file':path.name,'source_sha256':sha,'status':'review_required','adapter':None,'transactions':[],'issues':[]}
    issues=result['issues'];tx=result['transactions'];opening=None;closing=None;previous=None;checks=0
    with pdfplumber.open(path) as doc:
        first=doc.pages[0].extract_text(x_tolerance=2) or ''
        if 'bmo.com' in first.lower() and 'Business Banking statement' in first:
            kind='bmo_business';match=re.search(r'period ending\s+(\w+)\s+(\d+),\s+(\d{4})',first,re.I)
            if not match: issues.append('Statement period not found');return result
            mon,day,year=match.groups();end=date(int(year),MONTHS[mon[:3].title()],int(day));start=date(end.year,end.month,1)
        elif 'MM JJ' in first and 'Période du' in first:
            kind='national_french';match=re.search(r'Période du (\d{2})-(\d{2})-(\d{4}) au (\d{2})-(\d{2})-(\d{4})',first)
            if not match: issues.append('Statement period not found');return result
            a,b,c,d,e,f=map(int,match.groups());start=date(c,b,a);end=date(f,e,d)
        else:
            issues.append('Unsupported layout or unusable text; use another adapter/OCR and review');return result
        result.update(adapter=kind,period_start=start.isoformat(),period_end=end.isoformat())
        for pn,page in enumerate(doc.pages,1):
            page_lines=lines(page);header=None
            for y,ws in page_lines:
                text=' '.join(w['text'] for w in ws);n=norm(text)
                if ('description' in n and ('balance' in n or 'solde' in n)):
                    header=(y,ws);break
            if header is None:
                # BMO appended notices are explicitly excluded, not treated as transactions.
                if kind=='national_french':issues.append(f'Page {pn}: transaction header missing')
                continue
            hy,hws=header
            if kind=='national_french':
                debit=next((w for w in hws if norm(w['text'])=='debit'),None)
                credit=next((w for w in hws if norm(w['text'])=='credit'),None)
                balance=next((w for w in hws if norm(w['text'])=='solde'),None)
                if not all([debit,credit,balance]):issues.append(f'Page {pn}: incomplete headers');continue
                dc=(debit['x0']+credit['x0'])/2+8;cb=(credit['x0']+balance['x0'])/2+8
                desc_min=next(w['x0'] for w in hws if norm(w['text'])=='description');desc_max=debit['x0']-40
            else:
                # Right-aligned amount columns anchored to the two labels above the Date header.
                labels=[w for y,ws in page_lines if hy-16<y<hy for w in ws]
                debit=next((w for w in labels if 'debited' in norm(w['text'])),None)
                credit=next((w for w in labels if 'credited' in norm(w['text'])),None)
                balance=next((w for w in hws if 'balance' in norm(w['text'])),None)
                if not all([debit,credit,balance]):issues.append(f'Page {pn}: incomplete headers');continue
                dc=(debit['x1']+credit['x1'])/2;cb=(credit['x1']+balance['x1'])/2
                desc_min=next(w['x0'] for w in hws if norm(w['text'])=='description');desc_max=debit['x0']-15
            for y,ws in page_lines:
                if y<=hy:continue
                raw=' '.join(w['text'] for w in ws);n=norm(raw)
                if any(k in n.replace(' ','') for k in ['facturationdetaillee','closingtotals','beneficialowners']):break
                prefix=' '.join(w['text'] for w in ws if w['x0']<desc_min-2)
                dm=re.fullmatch(r'(\d{2})\s+(\d{2})',prefix) if kind=='national_french' else re.fullmatch(r'([A-Za-z]{3})\s*(\d{1,2})',prefix)
                desc=' '.join(w['text'] for w in ws if desc_min-2<=w['x0']<desc_max)
                if not dm:
                    if tx and tx[-1]['page']==pn and desc and all(desc_min-2<=w['x0']<desc_max for w in ws):
                        tx[-1]['description']+=' '+desc
                    continue
                mm,dd=dm.groups();month=int(mm) if kind=='national_french' else MONTHS.get(mm.title())
                if month is None:issues.append(f'Page {pn}: invalid month');continue
                candidates=[]
                for yr in range(start.year-1,end.year+1):
                    try:candidates.append(date(yr,month,int(dd)))
                    except ValueError:pass
                is_open='openingbalance' in n.replace(' ','') or 'solde precedent' in n
                is_close='closingbalance' in n.replace(' ','')
                valid=[d for d in candidates if start<=d<=end]
                if not valid and not is_open:issues.append(f'Page {pn}, y={y:.1f}: date outside statement');continue
                cells=[' '.join(w['text'] for w in ws if lo<=w['x1']<hi) for lo,hi in [(desc_max,dc),(dc,cb),(cb,10000)]]
                try: deb,cred,bal=[money(c) if c else None for c in cells]
                except ValueError as e:issues.append(f'Page {pn}, y={y:.1f}: {e}');continue
                if is_open:
                    if opening is None:opening=bal;previous=bal
                    continue
                if is_close:closing=bal;continue
                if (deb is None)==(cred is None) or bal is None:
                    issues.append(f'Page {pn}, y={y:.1f}: expected one amount and a balance');continue
                amount=cred if cred is not None else deb
                if amount<=0:issues.append(f'Page {pn}: nonpositive transaction needs review');continue
                signed=amount if cred is not None else -amount
                if previous is not None:
                    checks+=1
                    if previous+signed!=bal:issues.append(f'Page {pn}, y={y:.1f}: running balance mismatch')
                previous=bal
                tx.append({'id':f'{sha[:16]}:{pn}:{y:.2f}','page':pn,'top':round(y,2),'date':valid[0].isoformat(),'month':valid[0].strftime('%Y-%m'),'description':desc,'amount':str(amount),'tx_type':'credit' if cred is not None else 'debit','balance':str(bal),'source_file':path.name})
        credits=sum((Decimal(t['amount']) for t in tx if t['tx_type']=='credit'),Decimal(0));debits=sum((Decimal(t['amount']) for t in tx if t['tx_type']=='debit'),Decimal(0))
        result.update(opening_balance=str(opening) if opening is not None else None,closing_balance=str(closing) if closing is not None else None,last_transaction_balance=str(previous) if previous is not None else None,credits=str(credits),debits=str(debits),running_balance_checks=checks)
        if opening is None:issues.append('Opening balance missing')
        if not tx:issues.append('No transactions extracted')
        if closing is not None and opening is not None and opening+credits-debits!=closing:issues.append('Closing balance mismatch')
        # These checks are evidence, not a completeness or authenticity certification.
        expected=None
        if kind=='bmo_business':
            for line in first.splitlines():
                values=re.findall(r'-?\d[\d,]*\.\d{2}',line)
                if '#' in line and len(values)==4:
                    op,deb,cred,cl=map(money,values);expected={'debits':deb,'credits':cred}
                    result['closing_balance']=str(cl)
                    if opening!=op or previous!=cl:issues.append('Summary opening/closing mismatch')
                    break
        else:
            last=doc.pages[-1].extract_text(x_tolerance=2) or ''
            m=re.search(r'TRANSACTIONS\s+DÉBIT\s+(\d+)\s+([\d ]+,\d{2})\s+CRÉDIT\s+(\d+)\s+([\d ]+,\d{2})',last)
            if m:
                nd,vd,nc,vc=m.groups();expected={'debits':money(vd),'credits':money(vc)}
                if sum(t['tx_type']=='debit' for t in tx)!=int(nd) or sum(t['tx_type']=='credit' for t in tx)!=int(nc):issues.append('Summary transaction count mismatch')
        if expected is None:issues.append('Independent summary totals not found')
        else:
            result['statement_totals']={k:str(v) for k,v in expected.items()}
            if expected['debits']!=debits or expected['credits']!=credits:issues.append('Statement total mismatch')
        result['status']='reconciled_candidate_review_required' if not issues else 'review_required' 
    return result

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('pdf');ap.add_argument('--output',required=True);args=ap.parse_args()
    Path(args.output).write_text(json.dumps(extract(args.pdf),indent=2,ensure_ascii=False),encoding='utf-8')

