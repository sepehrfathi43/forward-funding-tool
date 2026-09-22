import unittest
from td_activity_batch import consolidate_td_activity
from statement_validation import validate_statement


def part(name,start,end,opening,rows,total):
    tx=[dict(id=name+str(i),date=d,month=d[:7],description=desc,tx_type='credit',amount=str(amount),balance=str(balance),source_file=name) for i,(d,desc,amount,balance) in enumerate(rows)]
    return validate_statement(dict(source_file=name,source_sha256=name,adapter='td_activity',account_id='td:A',currency='CAD',search_start='2026-01-01',search_end='2026-03-31',period_start=start,period_end=end,opening_balance=str(opening),closing_balance=tx[-1]['balance'],last_transaction_balance=tx[-1]['balance'],transactions=tx,issues=[],warnings=[],status='reconciled_candidate_review_required',statement_totals={'debits':'0','credits':str(total)}))

class BatchTests(unittest.TestCase):
    def test_complementary_exports_reconcile_together(self):
        a=part('a','2026-01-02','2026-01-02',0,[('2026-01-02','A',10,10)],30)
        b=part('b','2026-01-03','2026-01-03',10,[('2026-01-03','B',20,30)],30)
        r=consolidate_td_activity([a,b])[0]
        self.assertFalse(r['issues']);self.assertEqual(len(r['transactions']),2)
    def test_missing_export_stays_blocked(self):
        a=part('a','2026-01-02','2026-01-02',0,[('2026-01-02','A',10,10)],30)
        self.assertTrue(consolidate_td_activity([a])[0]['issues'])
    def test_balance_error_is_never_cleared(self):
        a=part('a','2026-01-02','2026-01-02',0,[('2026-01-02','A',10,11)],10)
        self.assertTrue(consolidate_td_activity([a])[0]['issues'])
    def test_identical_overlap_is_counted_once(self):
        a=part('a','2026-01-02','2026-01-03',0,[('2026-01-02','A',10,10),('2026-01-03','B',20,30)],30)
        b=part('b','2026-01-03','2026-01-04',10,[('2026-01-03','B',20,30),('2026-01-04','C',40,70)],60)
        b['search_start']='2026-01-03'
        r=consolidate_td_activity([a,b])[0]
        self.assertFalse(r['issues']);self.assertEqual(len(r['transactions']),3)
    def test_disagreeing_overlap_is_not_merged(self):
        a=part('a','2026-01-02','2026-01-03',0,[('2026-01-02','A',10,10),('2026-01-03','B',20,30)],30)
        b=part('b','2026-01-03','2026-01-04',10,[('2026-01-03','X',20,30),('2026-01-04','C',40,70)],60)
        b['search_start']='2026-01-03'
        self.assertEqual(len(consolidate_td_activity([a,b])),2)
