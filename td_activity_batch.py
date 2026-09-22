"""Reconcile paginated EasyWeb exports before consolidating overlapping windows."""
import copy
import hashlib
import json
from decimal import Decimal
from collections import defaultdict
from statement_validation import validate_statement


def consolidate_td_activity(results):
    groups=defaultdict(list)
    untouched=[]
    for r in results:
        if r.get('adapter')=='td_activity' and r.get('transactions') and r.get('search_start'):
            key=(r['account_id'],r['search_start'],r['search_end'],json.dumps(r.get('statement_totals'),sort_keys=True))
            groups[key].append(r)
        else:untouched.append(r)
    windows=[]
    for key,parts in groups.items():
        merged=copy.deepcopy(parts[0])
        rows=sorted([t for p in parts for t in p['transactions']],key=lambda t:t['date'])
        # Sort files by their chronological interval, retaining same-day source order.
        rows=[t for p in sorted(parts,key=lambda p:p['period_start']) for t in p['transactions']]
        issues=[]
        for p in parts:
            for issue in p.get('issues',[]):
                if issue.startswith(('Printed debit total','Printed credit total')) or issue in (
                    'Shared validation: debits total does not match the statement',
                    'Shared validation: credits total does not match the statement'):
                    continue
                issues.append(issue)
        merged.update(transactions=rows,issues=list(dict.fromkeys(issues)),
            source_file=' + '.join(p['source_file'] for p in parts),
            source_files=[p['source_file'] for p in parts],
            source_sha256=hashlib.sha256(''.join(p['source_sha256'] for p in parts).encode()).hexdigest(),
            period_start=min(p['period_start'] for p in parts),period_end=max(p['period_end'] for p in parts),
            opening_balance=min(parts,key=lambda p:p['period_start'])['opening_balance'],
            closing_balance=max(parts,key=lambda p:p['period_end'])['closing_balance'],
            last_transaction_balance=rows[-1]['balance'],
            status='reconciled_candidate_review_required' if not issues else 'review_required')
        for side in ('debit','credit'):
            merged[side+'s']=str(sum((Decimal(t['amount']) for t in rows if t['tx_type']==side),Decimal(0)))
        merged=validate_statement(merged)
        if merged['issues']:
            merged['issues'].append('EasyWeb search totals require all matching export pages; re-export the full history if totals or balances do not reconcile.')
        windows.append(merged)
    # Overlapping exports may be consolidated only if every window reconciles
    # and their full shared-date activity agrees, including repeated transactions.
    accounts=defaultdict(list)
    for w in windows:accounts[w['account_id']].append(w)
    for account,ws in accounts.items():
        ws.sort(key=lambda w:w['period_start'])
        if len(ws)==1 or any(w['issues'] for w in ws):
            untouched.extend(ws);continue
        from collections import Counter
        def fingerprint(t):return (t['date'],t['description'],t['tx_type'],str(Decimal(t['amount'])),t.get('balance'))
        combined=copy.deepcopy(ws[0]);rows=list(combined['transactions']);good=True
        for nxt in ws[1:]:
            start=max(combined['period_start'],nxt['period_start']);end=min(combined['period_end'],nxt['period_end'])
            if start>end:
                good=False;break
            old=Counter(fingerprint(t) for t in rows if start<=t['date']<=end)
            new=Counter(fingerprint(t) for t in nxt['transactions'] if start<=t['date']<=end)
            if old!=new:
                good=False;break
            rows.extend(t for t in nxt['transactions'] if t['date']>combined['period_end'])
            combined['period_end']=max(combined['period_end'],nxt['period_end'])
            combined['closing_balance']=rows[-1]['balance']
            combined['last_transaction_balance']=rows[-1]['balance']
        if not good:
            untouched.extend(ws);continue
        combined['transactions']=rows
        combined['source_files']=[n for w in ws for n in w['source_files']]
        combined['source_file']=' + '.join(combined['source_files'])
        combined['source_sha256']=hashlib.sha256(''.join(w['source_sha256'] for w in ws).encode()).hexdigest()
        combined['reconciled_source_windows']=[{k:w.get(k) for k in ('source_files','period_start','period_end','statement_totals','debits','credits')} for w in ws]
        combined['statement_totals']={side+'s':str(sum((Decimal(t['amount']) for t in rows if t['tx_type']==side),Decimal(0))) for side in ('debit','credit')}
        combined.update(combined['statement_totals'])
        combined['warnings'].append('Combined totals are derived after exact overlap removal; each source window was checked against its printed totals first.')
        untouched.append(validate_statement(combined))
    return untouched
