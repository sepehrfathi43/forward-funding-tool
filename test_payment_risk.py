import unittest
import pandas as pd
from payment_risk import nsf_summary
import app as app

class PaymentRiskTests(unittest.TestCase):
    def test_spelled_out_funds_fees(self):
        frame=pd.DataFrame([dict(date='2026-06-12',tx_type='debit',description=d,amount=48)
                            for d in ['Non Sufficient Funds Fee','Insufficient Funds Charge','Non-Sufficient Funds Fee']])
        risk=nsf_summary(frame)
        self.assertEqual(risk['fee_rows'],3)
        self.assertEqual(risk['fee_amount'],144)
        self.assertEqual(risk['returned_items'],0)
    def test_paid_items_are_separate_from_return_fees(self):
        frame=pd.DataFrame([dict(date='2026-01-16',tx_type='debit',description=d,amount=5)
                            for d in ['NSF PAID FEE','PAYMENT COVERAGE FEE']])
        risk=nsf_summary(frame)
        self.assertEqual(risk['paid_item_fee_amount'],10)
        self.assertEqual(risk['paid_item_fee_rows'],2)
        self.assertEqual(risk['fee_rows'],0)
        self.assertEqual(risk['returned_items'],0)
        frame.loc[2]=['2026-01-17','debit','NSF FEE',45]
        risk=nsf_summary(frame)
        self.assertEqual(risk['fee_rows'],1)
        self.assertEqual(risk['fee_amount'],45)
    def test_partial_month_and_fees_count_separately(self):
        df=pd.DataFrame([
            dict(date='2026-07-03',tx_type='credit',description='Cheque returned NSF',amount=100),
            dict(date='2026-08-18',tx_type='credit',description='Item returned NSF',amount=200),
            dict(date='2026-08-18',tx_type='credit',description='Cheque returned NSF',amount=300),
            dict(date='2026-08-19',tx_type='debit',description='NSF item fee 3 @ $45.00',amount=135),
            dict(date='2026-08-19',tx_type='debit',description='e-Transfer sent',amount=600),
            dict(date='2026-08-19',tx_type='credit',description='EFT DR REVERSAL',amount=50)])
        risk=nsf_summary(df)
        self.assertEqual(risk['returned_items'],3)
        self.assertEqual(risk['affected_dates'],2)
        self.assertEqual(risk['fee_amount'],135)
        self.assertEqual(risk['fee_disclosed_items'],3)
        self.assertEqual(risk['monthly'][-1]['NSF returns'],2)
    def test_actual_august_statement_and_full_batch(self):
        import json
        from pathlib import Path
        p=Path('../work/review_sep14c/native.json')
        if not p.exists():self.skipTest('Private audit fixture not bundled')
        results=json.loads(p.read_text());df=app.assemble_ledger(results)
        auto=app.auto_underwriting_inputs(df,results,app.offer_months(results))
        risk=auto['nsf_summary']
        self.assertEqual(risk['returned_items'],53)
        august=next(m for m in risk['monthly'] if m['Month']=='2026-08')
        self.assertEqual(august['NSF returns'],18)
        self.assertEqual(august['Dates affected'],7)
        self.assertEqual(august['Returned amount'],23927.60)
        self.assertEqual(august['NSF fees'],810)
        self.assertEqual(app.offer_months(results),['2026-02','2026-03','2026-04','2026-05','2026-06','2026-07'])
        self.assertEqual(auto['average_daily_balance'],7443.87)
        self.assertEqual(auto['missed_payments'],53)
    def test_empty(self):
        self.assertEqual(nsf_summary(pd.DataFrame())['returned_items'],0)

if __name__=='__main__':unittest.main()
