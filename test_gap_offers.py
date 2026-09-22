import unittest
import calendar
import cashflow
import app as app

class GapOfferTests(unittest.TestCase):
    def statement(self,month,amount,account='A'):
        y,m=map(int,month.split('-'));start=month+'-01';end=f'{month}-{calendar.monthrange(y,m)[1]}'
        return dict(account_id=account,currency='CAD',source_file=account+month,source_sha256=account+month,
                    period_start=start,period_end=end,opening_balance='0.00',closing_balance=str(amount),
                    transactions=[dict(id=account+month,date=start,month=month,amount=str(amount),balance=str(amount),
                    description='MERCHANT SETTLEMENT',tx_type='credit')])
    def test_three_disconnected_months_are_usable(self):
        results=[self.statement(m,a) for m,a in [('2026-01',300),('2026-03',600),('2026-05',900)]]
        months=app.offer_months(results)
        self.assertEqual(months,['2026-01','2026-03','2026-05'])
        self.assertEqual(len(cashflow.coverage_gaps(results)),2)
        df=app.assemble_ledger(results)
        self.assertEqual(app.metrics(df,months,0)['avg'],600)
        self.assertEqual(app.daily_balance_metrics(df,results,months)['average_daily_balance'],600)
    def test_recent_three_month_run_still_preferred(self):
        self.assertEqual(cashflow.available_offer_months(['2025-10','2025-11','2026-06','2026-07','2026-08']),['2026-06','2026-07','2026-08'])
    def test_partial_common_months_are_usable(self):
        results=[self.statement(m,100,a) for a in ['A','B'] for m in ['2026-01','2026-03','2026-05']]
        results[-1]['period_end']='2026-05-20'
        self.assertEqual(app.offer_months(results),['2026-01','2026-03','2026-05'])
    def test_no_invented_months_to_satisfy_minimum(self):
        self.assertEqual(cashflow.available_offer_months(['2026-01','2026-03']),['2026-01','2026-03'])
    def test_opening_balance_tail_does_not_dilute_four_complete_months(self):
        results=[self.statement(m,a) for m,a in [('2026-03',554417.20),('2026-04',483431.45),('2026-05',422695.88),('2026-06',473380.70)]]
        results[0]['period_start']='2026-02-27'
        months=app.offer_months(results)
        self.assertEqual(months,['2026-03','2026-04','2026-05','2026-06'])
        frame=app.assemble_ledger(results)
        figures=app.metrics(frame,months,0,results)
        self.assertAlmostEqual(figures['avg'],483481.3075)
        self.assertAlmostEqual(figures['trend'],-14.6165198338)
        self.assertAlmostEqual(figures['volatility'],9.7171969078)

if __name__=='__main__':unittest.main()
