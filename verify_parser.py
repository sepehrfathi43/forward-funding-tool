"""Regression checks against the three supplied PDFs; no source files are modified.
Run: python verify_parser.py --downloads PATH --national PATH
"""
import argparse
from collections import Counter
from pathlib import Path
from statement_parser import extract

ap=argparse.ArgumentParser()
ap.add_argument('--downloads',type=Path,required=True)
ap.add_argument('--national',type=Path,required=True)
a=ap.parse_args()
cases=[(a.downloads/'bank_statement_1 (4).pdf',104,'120472.99','120210.00'),(a.national/'aJrwlZUqrlOkhtl59Goa.pdf',65,'34113.61','35190.54'),(a.national/'JG0FNO5pR8Wdzl84W80p.pdf',57,'24071.60','21231.25')]
for path,count,debits,credits in cases:
    r=extract(path)
    assert not r['issues'],r['issues']
    assert len(r['transactions'])==count
    assert r['debits']==debits and r['credits']==credits
    assert r['running_balance_checks']==count
    assert len({t['id'] for t in r['transactions']})==count
    assert all(t['date'] and t['month'] and t['description'] for t in r['transactions'])
    if count==104:
        repeats=Counter((t['date'],t['amount'],t['description'],t['tx_type']) for t in r['transactions'])
        assert any(n>1 for n in repeats.values()),'Legitimate repeated transactions disappeared'
    print(f'PASS {path.name}: {count} rows; printed totals and every running balance match')
r=extract(a.downloads/'laurentian-bank.pdf')
assert r['status']=='review_required' and not r['transactions'] and r['issues']
print('PASS unsupported layout returns review-required without transactions')
