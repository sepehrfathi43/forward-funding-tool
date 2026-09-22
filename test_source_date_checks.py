import unittest
from unittest.mock import patch,MagicMock
from source_date_checks import verify_source_dates,leading_dates

class SourceDateTests(unittest.TestCase):
    def check(self,extracted,source='Mar14',posted=None):
        r=dict(period_start='2026-02-28',period_end='2026-05-31',issues=[],status='reconciled_candidate_review_required',transactions=[dict(date=extracted,amount='10000.00',balance='10193.56',page=1,posted_date=posted)])
        words=[{'text':v,'x0':i*70,'x1':i*70+60} for i,v in enumerate([source,'Deposit','$10,000.00','10,193.56'])]
        doc=MagicMock();page=MagicMock();page.filter.return_value=page;doc.pages=[page]
        with patch('source_date_checks.pdfplumber.open') as op,patch('source_date_checks._word_lines',return_value=[(100,words)]):
            op.return_value=doc
            return verify_source_dates(r,b'fixture')
    def test_match(self):self.assertEqual(self.check('2026-03-14')['source_date_checks']['verified'],1)
    def test_monotonic_wrong_date_still_fails(self):
        r=self.check('2026-03-07')
        self.assertEqual(r['source_date_checks']['mismatches'],1)
        self.assertEqual(r['status'],'review_required')
        self.assertEqual(r['transactions'][0]['date'],'2026-03-07')
    def test_month_shift(self):self.assertEqual(self.check('2026-04-30','May1')['source_date_checks']['mismatches'],1)
    def test_missing_evidence_not_pass(self):self.assertEqual(self.check('2026-03-14','Transfer')['source_date_checks']['unverified'],1)
    def test_two_dates_require_posted_evidence(self):
        self.assertEqual(self.check('2026-03-14','Mar12 Mar14')['source_date_checks']['unverified'],1)
        self.assertEqual(self.check('2026-03-14','Mar12 Mar14',posted='2026-03-14')['source_date_checks']['verified'],1)
    def test_year_boundary(self):self.assertEqual(leading_dates('Dec31 Purchase','2025-12-01','2026-01-31'),['2025-12-31'])
    def test_repeated_amount_balance_cannot_borrow_another_rows_date(self):
        r=dict(period_start='2025-12-09',period_end='2026-01-09',issues=[],transactions=[
            dict(date='2025-12-24',amount='241.22',balance='-288.64',page=1,top=100),
            dict(date='2025-12-31',amount='241.22',balance='-288.64',page=1,top=150)])
        doc=MagicMock();page=MagicMock();page.filter.return_value=page;doc.pages=[page]
        rows=[(100,[{'text':v} for v in ['Business','PAD','241.22','-288.64']]),
              (150,[{'text':v} for v in ['31','Dec','Transfer','241.22','-288.64']])]
        with patch('source_date_checks._word_lines',return_value=rows):
            verify_source_dates(r,b'fixture',document=doc)
        self.assertEqual(r['source_date_checks'],dict(verified=1,unverified=1,mismatches=0))
    def test_ambiguous_year_not_guessed(self):self.assertEqual(leading_dates('Jan1 Purchase','2025-01-01','2026-12-31'),[])
    def test_index_keeps_ambiguous_matches_and_borrowed_document_open(self):
        r=dict(period_start='2026-03-01',period_end='2026-03-31',issues=[],transactions=[dict(date='2026-03-14',amount='10000.00',balance='10193.56',page=1)])
        words=[{'text':word} for word in ['Mar14','Deposit','10,000.00','10,193.56']]
        doc=MagicMock();page=MagicMock();page.filter.return_value=page;doc.pages=[page]
        with patch('source_date_checks.pdfplumber.open') as opened,patch('source_date_checks._word_lines',return_value=[(100,words),(110,words)]):
            result=verify_source_dates(r,b'fixture',document=doc)
        self.assertEqual(result['source_date_checks']['unverified'],1)
        self.assertEqual(result['source_date_checks']['verified'],0)
        opened.assert_not_called()
        doc.close.assert_not_called()

if __name__=='__main__':unittest.main()
