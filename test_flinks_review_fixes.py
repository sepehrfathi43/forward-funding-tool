import unittest
import pandas as pd
import payment_risk, revenue_tools, ai_extraction, balance_review


class FlinksReviewFixes(unittest.TestCase):
    def test_returns_are_not_assumed_nsf_and_charges_not_double_counted(self):
        frame=pd.DataFrame([
            dict(date='2026-03-12',tx_type='credit',description='Returned Item Credit',amount=465.78,account_id='a'),
            dict(date='2026-03-12',tx_type='credit',description='Returned Item Credit',amount=50,account_id='a'),
            dict(date='2026-03-12',tx_type='debit',description='Transaction Service Charge',amount=50,account_id='a'),
            dict(date='2026-03-12',tx_type='debit',description='Transaction Service Charge',amount=75,account_id='b'),
            dict(date='2026-03-12',tx_type='credit',description='Direct Payment Return SHOP',amount=20,account_id='a')])
        result=payment_risk.nsf_summary(frame)
        self.assertEqual(result['returned_items'],2)
        self.assertEqual(result['unspecified_return_items'],2)
        self.assertEqual(result['associated_service_charges'],50)
        self.assertEqual(result['fee_amount'],0)

    def test_sweeps_excluded_without_ai_but_generic_transfers_preserved(self):
        for text in ['Transfer In DEMAND SWEEP','Transfer In COVER ACCT','Int Adjustment']:
            self.assertTrue(revenue_tools.exclusion(text))
        for text in ['eTransfer','Preauthorized Credit 9462-5183 QUEBE','Transfer In Customer receipt']:
            self.assertIsNone(revenue_tools.exclusion(text))

    def test_local_retry_keeps_other_pages(self):
        r={'transactions':[{'page':23},{'page':24},{'page':24}],
           'issues':['AI transaction 2: balance checkpoint does not reconcile with intervening transactions','Shared validation: row 3 (page 24) balance mismatch: calculated 10, printed 20']}
        self.assertEqual(ai_extraction.retry_pages_for_result(r,list(range(1,34)),[]),[23,24])
        self.assertEqual(ai_extraction.retry_pages_for_result({'issues':['AI debit total does not match printed statement total']},[1,2],[]),[1,2])

    def test_source_correction_is_audited_and_revalidated(self):
        row=dict(id='one',date='2026-03-11',month='2026-03',page=24,description='Customer EFT',amount='406.80',tx_type='credit',balance='739.95')
        result=dict(source_file='example.pdf',transactions=[row],period_start='2026-03-01',period_end='2026-03-31',opening_balance='324.15',closing_balance='730.95',issues=['AI transaction 1: balance checkpoint does not reconcile with intervening transactions','Currency not printed explicitly'])
        updated,frame,audit=balance_review.correct([result],pd.DataFrame([row]),'one','730.95','PDF page 24 checked')
        self.assertEqual(row['balance'],'739.95')
        self.assertEqual(updated[0]['validation']['errors'],0)
        self.assertEqual(updated[0]['issues'],['Currency not printed explicitly'])
        self.assertEqual(audit['before'],'739.95')
        self.assertEqual(frame.iloc[0]['balance'],730.95)
        with self.assertRaises(ValueError):balance_review.correct([result],frame,'one','730.95','')

    def test_correction_ui(self):
        from streamlit.testing.v1 import AppTest
        at=AppTest.from_string('''
import streamlit as st,pandas as pd,balance_review
if 'ledger' not in st.session_state:
 row=dict(id='one',date='2026-03-11',month='2026-03',page=24,description='Customer EFT',amount='406.80',tx_type='credit',balance='739.95')
 st.session_state.ledger=pd.DataFrame([row])
 st.session_state.results=[dict(transactions=[row],period_start='2026-03-01',period_end='2026-03-31',opening_balance='324.15',closing_balance='730.95',issues=[])]
balance_review.render(st,st.session_state)
''').run()
        at.selectbox(key='balance_correction_id').select('one')
        at.text_input(key='balance_correction_value').set_value('730.95')
        at.text_input(key='balance_correction_reference').set_value('Page 24')
        at.checkbox(key='balance_correction_verified').check().run()
        next(b for b in at.button if b.label=='Apply verified balance correction').click().run()
        self.assertFalse(at.exception)
        self.assertEqual(at.session_state['ledger'].iloc[0]['balance'],730.95)


if __name__=='__main__':unittest.main()
