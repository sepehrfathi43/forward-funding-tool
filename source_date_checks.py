"""Independent text-row date checks. Unmatched evidence never means verified."""
import io,re
from contextlib import nullcontext
from datetime import date,datetime
from decimal import Decimal
import pdfplumber
from pdf_access import open_pdf
from statement_validation import MONEY_TOKEN,parse_money
from rbc_td_parser import _word_lines


def leading_dates(text,start,end):
    dates=[];remaining=text.strip()
    for _ in range(2):
        m=re.match(r'([A-Za-z]{3})\s*(\d{1,2})(?=\s|$)',remaining)
        n=re.match(r'(\d{1,2})\s*([A-Za-z]{3})(?=\s|$)',remaining)
        iso=re.match(r'(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?=\s|$)',remaining)
        try:
            if iso:day=date(*map(int,iso.groups()));matched=iso
            elif m or n:
                matched=m or n
                month=datetime.strptime(m[1] if m else n[2],'%b').month
                number=int(m[2] if m else n[1])
                if not start or not end:break
                possibilities=[date(year,month,number) for year in range(int(start[:4]),int(end[:4])+1)]
                possibilities=[d for d in possibilities if start<=d.isoformat()<=end]
                if len(possibilities)!=1:break
                day=possibilities[0]
            else:break
            dates.append(day.isoformat());remaining=remaining[matched.end():].strip()
        except ValueError:break
    return dates


def verify_source_dates(result,pdf_bytes,document=None):
    records=result.get('account_statements',[result])
    with (nullcontext(document) if document is not None else open_pdf(pdf_bytes)) as doc:
        page_rows={}
        for number,page in enumerate(doc.pages,1):
            # Ignore rotated print identifiers outside the visible table.
            clean=page.filter(lambda c:c.get('object_type')!='char' or c.get('upright',True))
            index={}
            for top,words in _word_lines(clean):
                values=[]
                for word in words:
                    if MONEY_TOKEN.fullmatch(word['text']):
                        try:values.append(parse_money(word['text']))
                        except ValueError:pass
                if len(values)>=2:
                    index.setdefault((abs(values[-2]),values[-1]),[]).append((top,' '.join(w['text'] for w in words)))
            page_rows[number]=index
        for r in records:
            verified=0;unresolved=0;errors=[]
            for row in r.get('transactions',[]):
                native_evidence = row.get('source_date_evidence') or {}
                if native_evidence.get('method') == 'native_td_date_column' and native_evidence.get('normalized_date') == row.get('date'):
                    row['date_verification'] = {
                        'status': 'verified', 'source_date': row.get('date'),
                        'extracted_date': row.get('date'), 'page': row.get('page'),
                        'top': row.get('top'), 'method': 'native_date_column'
                    }
                    verified += 1
                    continue
                candidates=[]
                try:amount=abs(Decimal(str(row['amount'])));balance=Decimal(str(row['balance']))
                except Exception:
                    row['date_verification']={'status':'unverified','reason':'No running balance to identify source row'};unresolved+=1;continue
                for top,text in page_rows.get(row.get('page'),{}).get((amount,balance),[]):
                    # Repeated amounts AND balances occur after returns. Match the
                    # physical row before looking for a printed date; a blank date
                    # must never borrow evidence from a different transaction.
                    if row.get('top') is not None and abs(float(row['top'])-top)>3:
                        continue
                    dates=leading_dates(text,r.get('period_start'),r.get('period_end'))
                    if dates:candidates.append((top,text,dates))
                if len(candidates)!=1:
                    row['date_verification']={'status':'unverified','reason':'No unique dated text row matched by page, amount and balance'};unresolved+=1;continue
                top,text,dates=candidates[0]
                # Two dates are only resolved when the parser retained both fields.
                if len(dates)>1 and not row.get('posted_date'):
                    row['date_verification']={'status':'unverified','reason':'Source has multiple date columns','source_dates':dates};unresolved+=1;continue
                expected=dates[-1] if row.get('posted_date') else dates[0]
                matches=row.get('date')==expected
                row['date_verification']={'status':'verified' if matches else 'mismatch','source_date':expected,'extracted_date':row.get('date'),'page':row.get('page'),'top':round(top,2),'source_text':text}
                if matches:verified+=1
                else:
                    errors.append(f"Source date mismatch: page {row.get('page')}, amount {amount}: extracted {row.get('date')}, printed {expected}")
            r['source_date_checks']={'verified':verified,'unverified':unresolved,'mismatches':len(errors)}
            r['issues']=[i for i in r.get('issues',[]) if not i.startswith('Source date mismatch:')]+errors
            if errors:r['status']='review_required'
    if 'account_statements' in result and any(r.get('issues') for r in records):result['status']='review_required'
    return result
