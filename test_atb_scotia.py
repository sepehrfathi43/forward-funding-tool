"""Offline reconciliation and coverage tests for the supplied Farmline files."""
import copy
import unittest
from decimal import Decimal
from pathlib import Path

import app as app
import debt_review
from atb_scotia_parser import expand_statement_results


class AtbScotiaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        names=['zcCPRmpL.pdf','7QVDkiBe.pdf','uoNj3nwK.pdf','sJE5OBvk.pdf','Fu2pxEO8.pdf']
        root=Path('C:/Users/admin/Downloads')
        if not all((root/name).exists() for name in names):
            raise unittest.SkipTest('Private ATB/Scotia fixtures are not included')
        cls.documents=[app.extract_native((root/name).read_bytes(),name) for name in names]
        cls.results=expand_statement_results(cls.documents)

    def test_every_account_and_printed_cent_recovered(self):
        expected=[('zcCPRmpL.pdf','13412.71','12823.00',25),('zcCPRmpL.pdf','0.00','0.04',1),
                  ('7QVDkiBe.pdf','20.00','3800.00',2),('uoNj3nwK.pdf','11863.27','12685.00',25),
                  ('uoNj3nwK.pdf','0.00','0.04',1),('sJE5OBvk.pdf','7335.00','8057.50',5)]
        for r,(name,debits,credits,count) in zip(self.results,expected):
            self.assertEqual(r['source_file'],name)
            self.assertEqual((r['debits'],r['credits'],len(r['transactions'])),(debits,credits,count))
            self.assertEqual(r['running_balance_checks'],count)
            self.assertEqual([i for i in r['issues'] if i != app.CURRENCY_ISSUE],[])
        self.assertEqual(len(self.results),7)

    def test_scotia_balance_forward_and_fee_page_not_transactions(self):
        for r in [self.results[2],self.results[5]]:
            self.assertFalse(any('BALANCE FORWARD' in t['description'] for t in r['transactions']))
            self.assertEqual(sum(t['description']=='SERVICE CHARGE' for t in r['transactions']),1)
        self.assertIn('FREE INTERAC E-TRANSFER',self.results[2]['transactions'][0]['description'])

    def test_activity_screen_kept_as_blocker_but_never_double_counted(self):
        screen=self.results[-1]
        self.assertEqual(screen['adapter'],'scotia_activity_screen')
        self.assertTrue(screen['issues']); self.assertTrue(screen['exclude_from_ledger'])
        ledger=app.assemble_ledger(self.documents)
        self.assertEqual(len(ledger),59)
        self.assertTrue(ledger.id.is_unique)
        self.assertEqual(ledger.tx_type.eq('credit').sum(),22)
        self.assertAlmostEqual(ledger.loc[ledger.tx_type.eq('credit'),'amount'].sum(),37365.58)
        self.assertAlmostEqual(ledger.loc[ledger.tx_type.eq('debit'),'amount'].sum(),32630.98)
        # Distinct repeated receipts are preserved within the actual statements.
        self.assertEqual(ledger.loc[ledger.tx_type.eq('credit') & ledger.amount.eq(4357.5)].shape[0],5)

    def test_currency_confirmation_clears_only_currency(self):
        confirmed=app.confirm_cad(self.results,True)
        self.assertTrue(all(r['status']=='reconciled_candidate_review_required' for r in confirmed[:-1]))
        self.assertEqual(confirmed[-1]['status'],'review_required')

    def test_coverage_explains_no_common_full_months(self):
        self.assertEqual(app.full_months(self.documents),[])
        self.assertEqual(app.overlap_issues(self.documents),[])
        coverage=app.account_coverage(self.documents)
        self.assertEqual([r['Complete calendar months'] for r in coverage],['2025-05','2025-05','2025-06'])

    def test_named_loan_and_lease_payments_require_individual_verification(self):
        ledger=app.assemble_ledger(self.documents)
        debts=debt_review.seed_positions(ledger,[],app.lender_match)
        self.assertTrue({'RBC loan','Infinity lease','MERCHANT GROWTH'}.issubset(set(debts.lender)))
        self.assertFalse(debts.verified.any())
        self.assertEqual(debt_review.summary(debts)['monthly_debt'],0)

    def test_consolidated_document_blocker_survives_account_expansion(self):
        result=copy.deepcopy(self.documents[0]); result['issues'].append('Missing third account')
        expanded=expand_statement_results([result])
        self.assertEqual(len(expanded),3)
        self.assertIn('Missing third account',expanded[-1]['issues'])
        self.assertEqual(len(app.assemble_ledger([result])),26)

    def test_explicit_non_revenue_recognized_and_generic_receipts_stay_pending(self):
        ledger=app.assemble_ledger(self.documents)
        credit=ledger[ledger.tx_type.eq('credit')]
        interest=credit[credit.description.eq('Interest Payment')]
        self.assertEqual(len(interest),2)
        self.assertTrue(interest.revenue_status.eq('Non-Revenue').all())
        for pattern in ['Loan Disbursement','Transfer From']:
            rows=credit[credit.description.str.contains(pattern,regex=False)]
            self.assertGreater(len(rows),0)
            self.assertTrue(rows.revenue_status.eq('Non-Revenue').all())
        receipts=credit[credit.description.str.contains('INTERAC e-Transfer Received',regex=False)]
        self.assertGreater(len(receipts),0)
        self.assertTrue(receipts.revenue_status.eq('Review Required').all())


if __name__=='__main__':unittest.main()
