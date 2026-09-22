"""Common evidence and completeness contract for every extraction adapter."""
from copy import deepcopy
from decimal import Decimal
import hashlib
import re

VERSION=1


def normalize_result(result):
    """Preserve source facts; never sort away unexplained balance errors."""
    if 'account_statements' in result:
        for child in result['account_statements']: normalize_result(child)
        return result
    result['schema_version']=VERSION
    for sequence,row in enumerate(result.get('transactions',[]),1):
        row.setdefault('source_sequence',sequence)
        row.setdefault('transaction_date',row.get('date'))
        row.setdefault('posted_date',None)
        row.setdefault('date_basis','posted_date' if row.get('posted_date') else 'statement_date')
        if row.get('posted_date'):
            row['date']=row['posted_date'];row['month']=row['date'][:7]
        row.setdefault('account_id',result.get('account_id'))
        row.setdefault('currency',result.get('currency'))
        row.setdefault('evidence',{'file_sha256':result.get('source_sha256'),'page':row.get('page'),'top':row.get('top')})
    result['extraction_readiness']=('Incomplete or inconsistent' if result.get('issues') or not result.get('transactions') else 'Usable with warnings' if result.get('warnings') or result.get('ai_review_required') else 'Validated figures')
    return result


def normalize_ai(raw):
    out=deepcopy(raw)
    # A withdrawal summary is a magnitude; retain its printed sign in evidence.
    value=out.get('statement_total_debits')
    if value is not None:
        out['printed_statement_total_debits']=value
        out['statement_total_debits']=abs(Decimal(str(value)))
    rows=out.get('transactions') or []
    for row in rows:
        if not row.get('transaction_date'):row['transaction_date']=row.get('date')
        row['date']=row.get('posted_date') or row.get('transaction_date') or row.get('date')
    dates=[r.get('date') for r in rows]
    # Reverse only an explicitly descending date sequence with every balance
    # checkpoint proving the reversal, including within-day source order.
    if len(rows)>1 and all(dates) and dates==sorted(dates,reverse=True) and dates!=sorted(dates):
        candidate=list(reversed(rows));running=out.get('opening_balance');valid=running is not None
        if valid:
            running=Decimal(str(running))
            for row in candidate:
                running+=Decimal(str(row.get('credit') or 0))-Decimal(str(row.get('debit') or 0))
                if row.get('balance') is None or running!=Decimal(str(row['balance'])):valid=False;break
        if valid:
            out['transactions']=candidate;out['source_order']='newest_first'
    for n,row in enumerate(out.get('transactions') or [],1):
        row['source_sequence']=row.get('sequence')
        if out.get('source_order')=='newest_first':row['sequence']=n
    return out


def inspect_document(doc):
    pages=[]
    for number,page in enumerate(doc.pages,1):
        text=page.extract_text() or ''
        pages.append({'page':number,'text_characters':len(text.strip()),'kind':'text' if len(text.strip())>=40 else 'image_or_sparse','width':page.width,'height':page.height})
    return {'page_count':len(pages),'pages':pages}


def run_pages(page_count,fetch,cache,key,progress=None):
    """Session-scoped checkpointing. Failed/refused pages are never cached."""
    result=[]; failures=[]
    for page in range(1,page_count+1):
        token=(VERSION,key,page)
        if progress:progress(page,page_count,token in cache)
        try:
            if token not in cache:
                raw=fetch(page)
                if not isinstance(raw,dict) or not isinstance(raw.get('transactions'),list):raise ValueError('Invalid page structure')
                cache[token]=deepcopy(raw)
            result.append((page,deepcopy(cache[token])))
        except Exception as exc:
            failures.append({'page':page,'error':str(exc)})
            # Stop this document at first failure; retry resumes at this page.
            break
    return result,failures


def merge_pages(pages):
    metadata={};rows=[];issues=[]
    for page,raw in pages:
        for key,value in raw.items():
            if key in ('transactions','source_order'):continue
            if value is None:continue
            if key not in metadata:metadata[key]=value
            elif metadata[key]!=value:
                # Harmless printed formatting differences must not turn a
                # continuing statement into conflicting account evidence.
                left,right=metadata[key],value
                if key=='account_id':
                    left,right=[re.sub(r'[\s-]','',str(v)).upper() for v in (left,right)]
                elif key=='currency':left,right=[str(v).strip().upper() for v in (left,right)]
                elif key=='account_holder':
                    from business_identity import key as holder_key
                    left,right=holder_key(str(left)),holder_key(str(right))
                if left!=right:issues.append(f'Page {page}: conflicting {key}; separate accounts/periods or verify metadata.')
        for item in raw['transactions']:
            item=dict(item);item['page']=page;item['sequence']=len(rows)+1;rows.append(item)
    metadata['transactions']=rows
    return metadata,issues
