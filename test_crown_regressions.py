"""Account continuity, concurrent debts, and conservative revenue decisions."""
import copy
import json
import unittest
from pathlib import Path
import pandas as pd
import app as app
import debt_review as debt
import revenue_tools as revenue


def payments(amounts):
    rows=[]
    for day,values in enumerate(amounts,1):
        for value in values:
            rows.append(dict(id=str(len(rows)),account_id='test:A',date=f'2026-08-{day:02}',
                month='2026-08',description='BIZFUND payment trace '+str(10000000+len(rows)),
                tx_type='debit',amount=float(value),balance=None))
    return pd.DataFrame(rows)


class GeneralRegressionTests(unittest.TestCase):
    def test_concurrent_streams_keep_both_amounts_and_all_source_rows(self):
        frame=payments([[174,192]]*6)
        positions=debt.seed_positions(frame,['2026-08'],app.lender_match)
        self.assertEqual(sorted(positions.payment_amount),[174,192])
        self.assertEqual(positions.frequency.tolist(),['Daily','Daily'])
        self.assertEqual(sum(positions.observed_payments),12)
        self.assertEqual(debt.summary(positions)['suggested_monthly_debt'],7686)
        self.assertEqual(debt.summary(positions)['monthly_debt'],0)
        for pid in positions.position_id:
            positions,_,_=debt.save_position(positions,pid,{'verified':True})
        self.assertEqual(debt.summary(positions)['monthly_debt'],7686)
        self.assertEqual(debt.summary(positions)['mca_positions'],2)

    def test_rate_change_alone_is_not_a_second_contract(self):
        positions=debt.seed_positions(payments([[175]]*6+[[192]]*6),['2026-08'],app.lender_match)
        self.assertEqual(len(positions),1)
        self.assertEqual(positions.iloc[0].payment_amount,192)

    def test_equal_simultaneous_payments_are_not_deduplicated(self):
        positions=debt.seed_positions(payments([[174,174]]*6),['2026-08'],app.lender_match)
        self.assertEqual(len(positions),2)
        self.assertEqual(sum(positions.observed_payments),12)

    def test_reject_one_stream_keeps_other_as_debt(self):
        frame=payments([[174,192]]*6)
        positions=debt.seed_positions(frame,['2026-08'],app.lender_match)
        positions,_,_=debt.save_position(positions,positions.iloc[0].position_id,{'status':'Not debt','verified':True})
        mask=debt.debt_payment_mask(frame,app.lender_match,positions)
        self.assertEqual(frame.loc[mask,'amount'].unique().tolist(),[192])

    def test_generic_ai_receipts_stay_pending_and_manual_decision_still_works(self):
        descriptions=['INTERAC e-Transfer Received','INTERACe-TransferReceived',
                      'INTERAC e-Transfer Received CA123ABC','Mobile Cheque Deposit',
                      'ATM deposit - DA361010','Virement Interac reçu']
        frame=pd.DataFrame([dict(id=str(i),account_id='A',tx_type='credit',amount=100.,
            description=d,category=revenue.UNKNOWN,revenue_status='Review Required',reviewed=False)
            for i,d in enumerate(descriptions)])
        def confident_ai(key,model,prompt,data,schema):
            return {'decisions':[dict(group_id=g['group_id'],decision='True Revenue',confidence=.999,
                evidence='explicit_customer_receipt',reason='Customer payment suggestion')
                for g in json.loads(data)['deposits']]}
        out=revenue.classify_ai(frame,'test','test',confident_ai,{})
        self.assertTrue(out.revenue_status.eq('Review Required').all())
        out,rules,_=revenue.commit_decisions(out,{'0':'True Revenue'},remember=True)
        self.assertEqual(out.iloc[0].revenue_status,'True Revenue')
        self.assertEqual(out.iloc[1].revenue_status,'Review Required')
        self.assertFalse(rules)

    def test_missing_movements_do_not_make_daily_balances_look_verified(self):
        frame=pd.DataFrame([dict(account_id='A',date='2026-08-01',balance=1000)])
        statements=[dict(account_id='A',period_start='2026-08-01',period_end='2026-08-31',opening_balance='0')]
        self.assertIsNone(app.daily_balance_metrics(frame,statements,['2026-08']))

    def test_fee_exception_never_accepts_a_reversed_lease_payment(self):
        for description in ['Funds transfer fee TT KM CAPITAL C','Direct Debit Fees/Dues INFINITY LEASIN REFUND']:
            self.assertIsNone(debt.source_match(dict(tx_type='debit',description=description),app.lender_match))


class CrownStatementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        names=['jxhjDgyLrjvOY7ILYdez','XWSRwYJZQFRJfetivgbH','SrhRDFUAsfGSKgYJmtp2','TSOlTq9NZiozewMKWFX3']
        files=[Path('C:/Users/admin/Downloads')/(n+'.pdf') for n in names]
        if not all(p.exists() for p in files):raise unittest.SkipTest('Private statements are not bundled')
        cls.results=[app.extract_native(p.read_bytes(),p.name) for p in files]
        cls.frame=app.assemble_ledger(cls.results)

    def test_one_account_four_months_all_counts_and_balances(self):
        self.assertEqual({r['account_id'] for r in self.results},{'bmo_business:25501994-956'})
        self.assertEqual(self.results[1]['period_start'],'2026-05-30')
        self.assertEqual(app.offer_months(self.results),['2026-05','2026-06','2026-07','2026-08'])
        self.assertEqual(len(self.frame),653)
        for result in self.results:
            self.assertFalse(result['issues'])
            self.assertEqual(sum(result['statement_counts'].values()),len(result['transactions']))
        self.assertEqual(self.results[2]['excluded_notice_pages'],[8])
        self.assertAlmostEqual(self.frame[self.frame.tx_type.eq('credit')].amount.sum(),159197.87)
        self.assertAlmostEqual(self.frame[self.frame.tx_type.eq('debit')].amount.sum(),153407.58)

    def test_auto_inputs_match_independently_rolled_printed_daily_balances(self):
        daily={}
        for result in self.results:
            checkpoint={t['date']:float(t['balance']) for t in result['transactions']}
            balance=float(result['opening_balance'])
            for day in pd.date_range(result['period_start'],result['period_end']):
                key=day.strftime('%Y-%m-%d');balance=checkpoint.get(key,balance);daily[key]=balance
        auto=app.auto_underwriting_inputs(self.frame,self.results,app.offer_months(self.results))
        self.assertEqual(auto['average_daily_balance'],round(sum(daily.values())/len(daily),2))
        self.assertEqual(auto['average_daily_balance'],1869.90)
        self.assertEqual(auto['negative_days'],0)
        self.assertEqual(auto['intraday_negative_days'],25)
        self.assertGreater(auto['operating_outflows'],0)

    def test_current_debt_streams(self):
        positions=debt.seed_positions(self.frame,app.offer_months(self.results),app.lender_match)
        self.assertEqual(len(positions),3)
        self.assertEqual(sorted(positions[positions.lender.eq('BIZFUND')].payment_amount),[174,192])
        self.assertEqual(positions[positions.lender.eq('GREENBOX')].frequency.tolist(),['Weekly'])
        self.assertEqual(debt.summary(positions)['suggested_monthly_debt'],8941.28)
        self.assertEqual(debt.summary(positions)['unverified'],3)


if __name__=='__main__':unittest.main()
