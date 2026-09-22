import copy
import unittest
import pandas as pd
import case_assistant as chat
import debt_review
import app


def ledger():
    return pd.DataFrame([
        dict(id='c1',date='2026-07-01',month='2026-07',account_id='A',currency='CAD',tx_type='credit',amount=10000.,balance=10000.,description='Moneris settlement',category='Review Required',revenue_status='Review Required',reviewed=False,internal_transfer=False,payer_or_source='Moneris'),
        dict(id='c2',date='2026-07-02',month='2026-07',account_id='A',currency='CAD',tx_type='credit',amount=2000.,balance=12000.,description='Internal transfer',category='Non-Revenue',revenue_status='Non-Revenue',reviewed=True,internal_transfer=True,payer_or_source='Internal'),
        dict(id='d1',date='2026-07-03',month='2026-07',account_id='A',currency='CAD',tx_type='debit',amount=200.,balance=11800.,description='Equipment installment',category='Operating / Other Debit',revenue_status='Not Applicable',reviewed=True,internal_transfer=False,payer_or_source='Equipment')])


def response():
    return dict(message='Proposed changes for your review.',revenue_actions=[],debt_actions=[],settings={k:None for k in chat.LIMITS})


def state():return dict(case_reference='A',ledger=ledger(),debts=debt_review.empty(),deal_settings={},underwriting_result={'old':True})
def proposal(ss,r):return dict(fingerprint=chat.fingerprint(ss),response=r,allowed_ids=ss['ledger'].id.tolist(),prompt='Apply my requested changes')

class AssistantTests(unittest.TestCase):
    def test_preview_then_apply_and_invalidate_offer(self):
        ss=state();r=response();r['revenue_actions']=[dict(transaction_ids=['c1'],status='True Revenue',reason='Verified receipts')]
        p=proposal(ss,r);chat.stage(ss,p,ss['ledger'])
        self.assertEqual(ss['ledger'].iloc[0].revenue_status,'Review Required')
        chat.apply(ss,p,ss['ledger'])
        self.assertEqual(ss['ledger'].iloc[0].revenue_status,'True Revenue')
        self.assertNotIn('underwriting_result',ss)
        self.assertEqual(len(ss['chat_audit']),1)
        with self.assertRaises(ValueError):chat.apply(ss,p,ss['ledger'])
    def test_stale_case_rejected(self):
        ss=state();p=proposal(ss,response());ss['case_reference']='another business'
        with self.assertRaises(ValueError):chat.stage(ss,p,ss['ledger'])
    def test_wrong_row_or_debit_or_transfer_cannot_be_revenue(self):
        for txid in ['missing','d1','c2']:
            ss=state();r=response();r['revenue_actions']=[dict(transaction_ids=[txid],status='True Revenue',reason='x')]
            with self.assertRaises(ValueError):chat.apply(ss,proposal(ss,r),ss['ledger'])
            self.assertEqual(ss['ledger'].iloc[0].revenue_status,'Review Required')
    def test_numeric_bounds_and_atomic_changes(self):
        for bad in [-1,9999,float('nan'),True]:
            ss=state();r=response();r['settings']['credit_score']=bad
            with self.assertRaises(ValueError):chat.stage(ss,proposal(ss,r),ss['ledger'])
            self.assertEqual(ss['deal_settings'],{})
    def test_credit_and_terms_reach_calculations(self):
        ss=state();r=response();r['settings'].update(credit_score=710,repayment_factor=1.42,repayment_term=8,advance_pct_revenue=60)
        chat.apply(ss,proposal(ss,r),ss['ledger'])
        auto=app.auto_underwriting_inputs(ss['ledger'],[],['2026-07'],deal_settings=ss['deal_settings'])
        self.assertEqual((auto['credit_score'],auto['repayment_term'],auto['repayment_factor']),(710,8,1.42))
        self.assertEqual(chat.cap_for_settings(10000,10000,8,1.42,ss['deal_settings']),6000)
        self.assertEqual(chat.cap_for_settings(4000,10000,8,1.42,ss['deal_settings']),4000)
    def test_payment_percent_cap(self):
        self.assertEqual(chat.cap_for_settings(100000,10000,6,1.5,{'payment_pct_revenue':10}),100000)
    def test_new_debt_is_unverified_and_excluded_from_operating(self):
        ss=state();r=response();r['debt_actions']=[dict(transaction_ids=['d1'],lender='EquipmentCo',kind='Other debt',reason='Installment evidence')]
        chat.apply(ss,proposal(ss,r),ss['ledger'])
        self.assertFalse(ss['debts'].iloc[0].verified)
        self.assertTrue(debt_review.readiness_issues(ss['debts']))
        self.assertTrue(debt_review.debt_payment_mask(ss['ledger'],app.lender_match,ss['debts']).iloc[2])
        with self.assertRaises(ValueError):chat.stage(ss,proposal(ss,r),ss['ledger'])
    def test_outside_filter_rejected(self):
        ss=state();r=response();r['revenue_actions']=[dict(transaction_ids=['c1'],status='True Revenue',reason='x')]
        p=proposal(ss,r);p['allowed_ids']=[]
        with self.assertRaises(ValueError):chat.stage(ss,p,ss['ledger'])

    def test_batch_validation_is_atomic(self):
        ss=state();r=response()
        r['revenue_actions']=[dict(transaction_ids=['c1'],status='True Revenue',reason='x')]
        r['debt_actions']=[dict(transaction_ids=['missing'],lender='X',kind='MCA',reason='x')]
        with self.assertRaises(ValueError):chat.apply(ss,proposal(ss,r),ss['ledger'])
        self.assertEqual(ss['ledger'].iloc[0].revenue_status,'Review Required')
        self.assertIn('underwriting_result',ss)
    def test_foreign_currency_debt_waits_for_conversion(self):
        ss=state();r=response();r['debt_actions']=[dict(transaction_ids=['d1'],lender='X',kind='MCA',reason='x')]
        foreign=ss['ledger'].copy();foreign['currency']='USD'
        with self.assertRaises(ValueError):chat.stage(ss,proposal(ss,r),foreign)

if __name__=='__main__':unittest.main()
