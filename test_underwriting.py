"""Run: python test_underwriting.py. Sample-PDF tests use optional local paths."""
import io
import json
import unittest
import types
from decimal import Decimal
from pathlib import Path
import pandas as pd
import app as app


def csv_data(**changes):
    row=dict(account_id='TEST',currency='CAD',period_start='2026-01-01',period_end='2026-01-31',opening_balance='100.00',closing_balance='125.00',expected_debits='0.00',expected_credits='25.00',date='2026-01-02',description='Customer payment',debit='',credit='25.00',balance='125.00')
    row.update(changes)
    return pd.DataFrame([row]).to_csv(index=False).encode()


def synthetic_pdf():
    """A real page for the page-wise extraction path; model calls stay mocked."""
    from reportlab.pdfgen.canvas import Canvas
    buffer = io.BytesIO()
    canvas = Canvas(buffer)
    canvas.drawString(60, 740, '2026-01-02 Customer payment 25.00 125.00')
    canvas.save()
    return buffer.getvalue()

class RegressionTests(unittest.TestCase):
    def test_money_locales(self):
        for text,expected in [('1 234,56','1234.56'),('(1,234.56)','-1234.56'),('4.00-','-4.00'),('-$25.00','-25.00')]:self.assertEqual(app.money(text),Decimal(expected))
    def test_text_quality(self):
        self.assertEqual(app.text_quality(''),'no_text')
        self.assertEqual(app.text_quality('(cid:35)'),'garbled')
        self.assertEqual(app.text_quality('abcd\x01\x02'),'garbled')
    def test_valid_csv(self):
        r=app.parse_verified_csv(csv_data(),'a.csv')
        self.assertFalse(r['issues']);self.assertEqual(r['credits'],'25.00')
    def test_csv_bad_balance_blocks(self):
        r=app.parse_verified_csv(csv_data(balance='126.00'),'a.csv')
        self.assertEqual(r['status'],'review_required')
    def test_csv_bad_independent_total_blocks(self):
        r=app.parse_verified_csv(csv_data(expected_credits='30.00'),'a.csv')
        self.assertEqual(r['status'],'review_required')
    def test_csv_bad_date_rejected(self):
        with self.assertRaises(ValueError):app.parse_verified_csv(csv_data(date='2026-02-01'),'a.csv')
    def test_csv_ambiguous_amount_rejected(self):
        with self.assertRaises(ValueError):app.parse_verified_csv(csv_data(debit='5.00'),'a.csv')
    def test_csv_currency_preserved_and_unsupported_rejected(self):
        self.assertEqual(app.parse_verified_csv(csv_data(currency='USD'),'a.csv')['currency'],'USD')
        with self.assertRaises(ValueError):app.parse_verified_csv(csv_data(currency='XYZ'),'a.csv')
    def test_credit_only_revenue(self):
        df=pd.DataFrame([dict(tx_type='debit',reviewed=True,category='True Revenue - POS / Processor'),dict(tx_type='credit',reviewed=False,category='True Revenue - POS / Processor'),dict(tx_type='credit',reviewed=True,category='True Revenue - POS / Processor')])
        self.assertEqual(app.credit_revenue(df).tolist(),[False,False,True])
    def test_processor_reversal_precedence(self):
        self.assertIn('NSF',app.suggested_category('STRIPE NSF RETURNED ITEM','credit'))
        self.assertEqual(app.suggested_category('STRIPE','debit'),'Operating / Other Debit')

    def test_revenue_decisions_auto_flag_clear_deposits_only(self):
        results=[dict(source_file='test.pdf',account_id='A',transactions=[
            dict(id='1',date='2026-01-01',month='2026-01',description='STRIPE PAYOUT',amount='100.00',tx_type='credit',balance='100.00'),
            dict(id='2',date='2026-01-02',month='2026-01',description='ONLINE TRANSFER',amount='50.00',tx_type='credit',balance='150.00'),
            dict(id='3',date='2026-01-03',month='2026-01',description='RENT',amount='25.00',tx_type='debit',balance='125.00')])]
        ledger=app.assemble_ledger(results)
        self.assertEqual(ledger.loc[0,'revenue_status'],'True Revenue')
        self.assertTrue(bool(ledger.loc[0,'reviewed']))
        self.assertEqual(ledger.loc[1,'revenue_status'],'Non-Revenue')
        self.assertTrue(bool(ledger.loc[1,'reviewed']))
        self.assertEqual(ledger.loc[2,'revenue_status'],'Not Applicable')
        self.assertEqual(app.credit_revenue(ledger).tolist(),[True,False,False])

    def test_transaction_filters_apply_to_any_column(self):
        frame=pd.DataFrame([{'id':'a','description':'Stripe payout','amount':100},{'id':'b','description':'Customer payment','amount':200}])
        filtered=app.filter_transactions(frame,{'description':'stripe'})
        self.assertEqual(filtered.id.tolist(),['a'])
        self.assertEqual(app.filter_transactions(frame,{'amount':'200'}).id.tolist(),['b'])

    def test_auto_underwriting_inputs_and_program_cap(self):
        frame=pd.DataFrame([
            dict(month='2026-01',date='2026-01-01',balance=1000.,tx_type='credit',description='STRIPE PAYOUT',amount=20000.,revenue_status='True Revenue',reviewed=True),
            dict(month='2026-01',date='2026-01-02',balance=-100.,tx_type='debit',description='NSF FEE',amount=50.,revenue_status='Not Applicable',reviewed=True),
            dict(month='2026-01',date='2026-01-03',balance=500.,tx_type='debit',description='FORWARD FUNDING',amount=1000.,revenue_status='Not Applicable',reviewed=True)])
        auto=app.auto_underwriting_inputs(frame,[],['2026-01'])
        self.assertEqual(auto['repayment_factor'],1.46)
        self.assertEqual(auto['negative_days'],1)
        self.assertEqual(auto['velocity'],'1 in 90 Days')
        self.assertEqual(app.program_max_advance(100000.,dict(advance=.7,max_burden=.15),5000.,20000.,0.,6,1.46),70000)
    def test_full_months_and_overlap(self):
        results=[dict(account_id='a',period_start='2026-01-01',period_end='2026-03-31',source_file='a')]
        self.assertEqual(app.full_months(results),['2026-01','2026-02','2026-03'])
        results.append(dict(account_id='b',period_start='2026-01-15',period_end='2026-03-31',source_file='b'))
        self.assertEqual(app.full_months(results),['2026-02','2026-03'])
        results.append(dict(account_id='a',period_start='2026-03-01',period_end='2026-03-31',source_file='c'))
        self.assertTrue(app.overlap_issues(results))
    def test_zero_revenue_month_counted(self):
        df=pd.DataFrame([dict(month='2026-01',tx_type='credit',reviewed=True,category='True Revenue - POS / Processor',amount=30000.,payer_or_source='one')])
        m=app.metrics(df,['2026-01','2026-02','2026-03'],0)
        self.assertEqual(m['avg'],10000.)
    def test_max_score(self):
        m=dict(avg=200000.,trend=20.,volatility=5.,count=50,burden=0.,concentration=10.)
        p=dict(operating_outflows=100000.,monthly_debt=0.,adb=25000.,positions=0,velocity='0 in 90 Days',missed=0,negative=0,months=100,industry='8011 - Offices & Clinics of Doctors of Medicine',credit=800,records='Clean',verification='Bank Connect')
        s=app.scorecard(m,p)
        self.assertEqual(s['raw'],100);self.assertEqual(s['score'],100);self.assertEqual(s['grade'],'A+')
    def test_payment_capacity_does_not_cap_revenue_estimate(self):
        result=app.offer_scenario(100000,dict(max_burden=.18,advance=1.),18000,10000,0,6,1.3,100000)
        self.assertEqual(result['amount'],100000)
    def test_operating_expenses_do_not_cap(self):
        result=app.offer_scenario(100000,dict(max_burden=.18,advance=1.),0,97000,0,6,1.3,100000)
        self.assertAlmostEqual(result['amount'],100000)
        self.assertAlmostEqual(result['monthly_payment'],100000*1.3/6)
    def test_native_samples(self):
        samples=[(Path('C:/Users/admin/Downloads/bank_statement_1 (4).pdf'),104,'120210.00','120472.99'),(Path('C:/Users/admin/Desktop/National Bank/aJrwlZUqrlOkhtl59Goa.pdf'),65,'35190.54','34113.61'),(Path('C:/Users/admin/Desktop/National Bank/JG0FNO5pR8Wdzl84W80p.pdf'),57,'21231.25','24071.60')]
        if not all(p.exists() for p,*_ in samples):self.skipTest('Private PDF fixtures are not bundled')
        for path,count,credit,debit in samples:
            with self.subTest(file=path.name):
                r=app.extract_native(path.read_bytes(),path.name)
                self.assertEqual(len(r['transactions']),count);self.assertEqual(r['credits'],credit);self.assertEqual(r['debits'],debit);self.assertFalse(r['issues']);self.assertTrue(r['account_id'])
                df=app.assemble_ledger([r]);self.assertEqual(len(df),count)
                self.assertFalse(app.credit_revenue(df).any())

    def test_french_bmo_samples(self):
        samples=[
            (Path('C:/Users/admin/Downloads/0FlnMY68i5rnDIlS8RQH.pdf'),146,'88893.37','86041.67',77,69),
            (Path('C:/Users/admin/Downloads/XZvNiM1dpNNSg6MaLhp1.pdf'),226,'152816.49','159910.28',153,73),
            (Path('C:/Users/admin/Downloads/GNrIZCeXHiC38vmLyNBJ.pdf'),234,'133290.67','153545.03',195,39),
        ]
        if not all(p.exists() for p,*_ in samples):self.skipTest('Private French PDF fixtures are not bundled')
        for path,count,debit,credit,debit_count,credit_count in samples:
            with self.subTest(file=path.name):
                result=app.extract_native(path.read_bytes(),path.name)
                self.assertEqual(result['adapter'],'bmo_business_french')
                self.assertEqual(result['status'],'reconciled_candidate_review_required')
                self.assertEqual(len(result['transactions']),count)
                self.assertEqual(result['debits'],debit);self.assertEqual(result['credits'],credit)
                self.assertEqual(result['statement_counts'],{'debits':debit_count,'credits':credit_count})
                self.assertFalse(result['issues'])
    def test_unsupported_native_blocks(self):
        path=Path('C:/Users/admin/Downloads/laurentian-bank.pdf')
        if not path.exists():self.skipTest('Private fixture not bundled')
        r=app.extract_native(path.read_bytes(),path.name)
        self.assertEqual(r['status'],'review_required');self.assertFalse(r['transactions'])

    def test_ai_pdf_fallback_reconciles_candidate_ledger(self):
        payload={
            'account_id':'AI-TEST-001','account_holder':None,'currency':'CAD',
            'period_start':'2026-01-01','period_end':'2026-01-31',
            'opening_balance':100.00,'closing_balance':125.00,
            'statement_total_debits':0.00,'statement_total_credits':25.00,
            'statement_debit_count':0,'statement_credit_count':1,
            'transactions':[{'sequence':1,'page':1,'date':'2026-01-02','description':'Customer payment','debit':None,'credit':25.00,'balance':125.00}]
        }
        class FakeCompletions:
            def create(self, **kwargs):
                self.kwargs=kwargs
                return types.SimpleNamespace(status='completed',output_text=json.dumps(payload),output=[])
        fake_completions=FakeCompletions()
        fake_openai=types.ModuleType('openai')
        fake_openai.OpenAI=lambda **kwargs:types.SimpleNamespace(responses=fake_completions,close=lambda:None)
        previous=__import__('sys').modules.get('openai')
        __import__('sys').modules['openai']=fake_openai
        try:
            result=app.ai_extract_statement(synthetic_pdf(), 'unsupported.pdf', 'sk-test', 'gpt-4o')
        finally:
            if previous is None: __import__('sys').modules.pop('openai',None)
            else: __import__('sys').modules['openai']=previous
        self.assertEqual(result['status'],'ai_reconciled_candidate_review_required')
        self.assertEqual(result['adapter'],'openai_pdf_fallback')
        self.assertEqual(len(result['transactions']),1)
        self.assertEqual(result['credits'],'25.00')
        self.assertTrue(result['ai_review_required'])
        sent=fake_completions.kwargs['input'][0]['content'][0]
        self.assertEqual(sent['type'],'input_file')
        self.assertEqual(result['completed_pages'],[1])
        self.assertEqual(result['extraction_method'],'openai_pdf_pages')
        self.assertEqual(fake_completions.kwargs['max_output_tokens'],16000)

    def test_ai_pdf_fallback_blocks_bad_reconciliation(self):
        payload={
            'account_id':'AI-TEST-001','account_holder':None,'currency':'CAD','period_start':'2026-01-01','period_end':'2026-01-31',
            'opening_balance':100.00,'closing_balance':125.00,'statement_total_debits':0.00,'statement_total_credits':30.00,
            'statement_debit_count':0,'statement_credit_count':1,
            'transactions':[{'sequence':1,'page':1,'date':'2026-01-02','description':'Customer payment','debit':None,'credit':25.00,'balance':125.00}]
        }
        class FakeCompletions:
            def create(self, **kwargs):
                return types.SimpleNamespace(status='completed',output_text=json.dumps(payload),output=[])
        fake_openai=types.ModuleType('openai')
        fake_openai.OpenAI=lambda **kwargs:types.SimpleNamespace(responses=FakeCompletions(),close=lambda:None)
        previous=__import__('sys').modules.get('openai');__import__('sys').modules['openai']=fake_openai
        try: result=app.ai_extract_statement(synthetic_pdf(),'unsupported.pdf','sk-test','test-model')
        finally:
            if previous is None: __import__('sys').modules.pop('openai',None)
            else: __import__('sys').modules['openai']=previous
        self.assertEqual(result['status'],'review_required')
        self.assertTrue(any('total' in issue.lower() for issue in result['issues']))

    def test_pagewise_ai_suggests_amount_but_preserves_source(self):
        raw={
            'account_id':'AI-TEST-002','currency':'CAD','period_start':'2026.01.01','period_end':'2026.01.31',
            'opening_balance':100.00,'closing_balance':125.00,
            'statement_total_debits':0.00,'statement_total_credits':25.00,
            'statement_debit_count':0,'statement_credit_count':1,
            # The model read 35.00, but the model-read balances could also be wrong.
            # Preserve the original amount and flag the discrepancy.
            'transactions':[{'sequence':1,'page':1,'date':'2026.01.02','description':'Customer payment','debit':None,'credit':35.00,'balance':125.00}]
        }
        result=app._validate_ai_statement_raw(raw,b'%PDF-test','scanned.pdf','gpt-4o')
        self.assertEqual(result['status'],'review_required')
        self.assertEqual(result['credits'],'35.00')
        self.assertEqual(result['transactions'][0]['amount'],'35.00')
        self.assertEqual(len(result['suggested_balance_repairs']),1)

if __name__=='__main__':unittest.main(verbosity=2)
