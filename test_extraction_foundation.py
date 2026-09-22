import unittest
from decimal import Decimal
from extraction_foundation import normalize_ai,normalize_result,run_pages,merge_pages
from statement_validation import validate_statement

class FoundationTests(unittest.TestCase):
    def test_dates_and_signed_totals(self):
        raw={'statement_total_debits':-100,'transactions':[{'sequence':1,'date':'2025-10-01','transaction_date':'2025-10-01','posted_date':'2025-10-03'}]}
        out=normalize_ai(raw)
        self.assertEqual(out['statement_total_debits'],100)
        self.assertEqual(out['printed_statement_total_debits'],-100)
        self.assertEqual(out['transactions'][0]['date'],'2025-10-03')
        self.assertEqual(raw['transactions'][0]['date'],'2025-10-01')
    def test_reverse_requires_balance_proof(self):
        raw={'opening_balance':0,'transactions':[{'sequence':1,'date':'2026-02-02','credit':10,'balance':30},{'sequence':2,'date':'2026-02-01','credit':20,'balance':20}]}
        out=normalize_ai(raw)
        self.assertEqual(out['transactions'][0]['balance'],20)
        raw['transactions'][0]['balance']=31
        self.assertEqual(normalize_ai(raw)['transactions'][0]['balance'],31)
    def test_retry_only_failed_and_unvisited_pages(self):
        cache={};calls=[]
        def fetch(n):
            calls.append(n)
            if n==2:raise TimeoutError('timeout')
            return {'transactions':[]}
        pages,errors=run_pages(3,fetch,cache,'case')
        self.assertEqual(calls,[1,2]);self.assertEqual(errors[0]['page'],2)
        calls.clear()
        pages,errors=run_pages(3,lambda n:(calls.append(n) or {'transactions':[]}),cache,'case')
        self.assertEqual(calls,[2,3]);self.assertFalse(errors)
        run_pages(1,lambda n:(calls.append(n) or {'transactions':[]}),cache,'changed_model')
        self.assertEqual(calls,[2,3,1])
    def test_metadata_conflicts_block(self):
        raw,issues=merge_pages([(1,{'account_id':'a','transactions':[]}),(2,{'account_id':'b','transactions':[]})])
        self.assertTrue(issues)
    def test_metadata_formatting_differences_are_not_account_conflicts(self):
        raw,issues=merge_pages([(1,{'account_id':'123-456','account_holder':'Example Inc.','currency':'CAD','transactions':[]}),
                               (2,{'account_id':'123 456','account_holder':'EXAMPLE INC','currency':'cad','transactions':[]})])
        self.assertFalse(issues)
        self.assertEqual(raw['account_id'],'123-456')
    def test_no_false_healthy_empty_result(self):
        r=normalize_result({'transactions':[],'issues':[]})
        self.assertEqual(r['extraction_readiness'],'Incomplete or inconsistent')
    def test_source_evidence_and_duplicates(self):
        row=dict(id='a',date='2026-01-01',month='2026-01',description='deposit',amount='10.00',tx_type='credit',balance='10.00',page=2)
        r=dict(transactions=[row,dict(row)],period_start='2026-01-01',period_end='2026-01-31',opening_balance='0.00',closing_balance='10.00',issues=[])
        normalize_result(validate_statement(r))
        self.assertTrue(any('duplicated' in i for i in r['issues']))
        self.assertEqual(row['evidence']['page'],2)

if __name__=='__main__':unittest.main()
