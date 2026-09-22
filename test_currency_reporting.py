import unittest
from decimal import Decimal
import pandas as pd
from currency_reporting import match_internal_transfers, reporting_view, currency_totals
from statement_validation import parse_money, MONEY_TOKEN
from rbc_td_parser import _td_balance_cell
import app as app
import revenue_tools as revenue

class CurrencyTests(unittest.TestCase):
    def frame(self):
        return pd.DataFrame([
            dict(id='d',account_id='a',currency='CAD',date='2026-04-01',month='2026-04',description='FX TFR C#00442770886',amount=22804.03,tx_type='debit',balance=None,category='',reviewed=True,revenue_status='Not Applicable'),
            dict(id='c',account_id='b',currency='USD',date='2026-04-01',month='2026-04',description='FX TFR C#00442770886',amount=16300.,tx_type='credit',balance=None,category='',reviewed=False,revenue_status='Review Required')])
    def test_overdraft(self):
        for value in ['15.49OD','15.49 OD']:
            self.assertTrue(MONEY_TOKEN.fullmatch(value))
            self.assertEqual(parse_money(value),Decimal('-15.49'))
    def test_overlapping_footer(self):
        class Page: pass
        page=Page();page.chars=[]
        for text,y,size in [('1,938.75',605.877,.24),('No. Amount',606.4665,9.5)]:
            page.chars += [dict(text=c,x0=470+i*6,top=y,size=size) for i,c in enumerate(text)]
        self.assertEqual(_td_balance_cell(page,606,468.5),Decimal('1938.75'))
    def test_unique_pair_and_bulk_override(self):
        frame=match_internal_transfers(self.frame())
        self.assertEqual(frame.internal_transfer.sum(),2)
        self.assertEqual(frame.loc[1,'revenue_status'],'Non-Revenue')
        updated,_,events=revenue.commit_decisions(frame,{'c':'True Revenue'})
        self.assertEqual(updated.loc[1,'revenue_status'],'Non-Revenue')
        self.assertEqual(events[0]['decision'],'Non-Revenue')
        self.assertFalse(app.credit_revenue(updated).any())
    def test_ambiguous_or_other_day_not_matched(self):
        frame=self.frame();frame.loc[1,'date']='2026-04-02'
        self.assertFalse(match_internal_transfers(frame).internal_transfer.any())
        frame=self.frame();frame=pd.concat([frame,frame.iloc[[1]]],ignore_index=True)
        self.assertFalse(match_internal_transfers(frame).internal_transfer.any())
    def test_rate_required_and_originals_preserved(self):
        frame=self.frame()
        with self.assertRaises(ValueError):reporting_view(frame,[],{})
        with self.assertRaises(ValueError):reporting_view(frame,[],{'USD':0})
        out,_=reporting_view(frame,[],{'USD':1.4})
        self.assertAlmostEqual(out.loc[1,'amount'],22820.)
        self.assertEqual(frame.loc[1,'amount'],16300.)
        self.assertEqual(out.loc[1,'original_currency'],'USD')
        self.assertIn('USD 16,300.00',currency_totals(frame))
    def test_transfers_excluded_from_operating_but_not_balance(self):
        frame=match_internal_transfers(self.frame())
        out,rs=reporting_view(frame,[],{'USD':1.4})
        auto=app.auto_underwriting_inputs(out,rs,['2026-04'])
        self.assertEqual(auto['operating_outflows'],0)
        self.assertEqual(len(out),2)

    def test_daily_rollforward_converts_after_native_currency_arithmetic(self):
        frame=self.frame()
        results=[dict(account_id='a',currency='CAD',period_start='2026-04-01',period_end='2026-04-30',opening_balance='30000.00'),
                 dict(account_id='b',currency='USD',period_start='2026-04-01',period_end='2026-04-30',opening_balance='-10.00')]
        out,rs=reporting_view(frame,results,{'USD':1.40001})
        daily=app.daily_balance_metrics(out,rs,['2026-04'])
        self.assertIsNotNone(daily)
        self.assertAlmostEqual(daily['average_daily_balance'],7195.97+16290*1.40001)
        self.assertEqual(daily['negative_days'],0)
        self.assertEqual(results[1]['opening_balance'],'-10.00')

if __name__=='__main__':unittest.main()
