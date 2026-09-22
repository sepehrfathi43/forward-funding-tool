import json
import unittest
from pathlib import Path
from unittest.mock import Mock
import pandas as pd
import app as app
import revenue_tools as rev
from servus_parser import confirm_cad, CURRENCY_ISSUE

def frame():
    rows=[]
    for txid, account, desc, kind, amount in [
        ('a','A','Acme Property | 123','credit',100),('b','A','Acme Property | 123','credit',200),
        ('c','B','Acme Property | 123','credit',300),('d','A','Rent','debit',50),
        ('e','A','Business Deposit','credit',1000),('f','A','Business Deposit','credit',1000),
        ('g','A','Stripe refund','credit',25)]:
        rows.append(dict(id=txid,account_id=account,description=desc,tx_type=kind,amount=float(amount),
            revenue_status='Not Applicable' if kind=='debit' else 'Review Required',category=rev.UNKNOWN,
            reviewed=kind=='debit',date='2026-01-01',month='2026-01',balance=100.,page=1))
    return rev.ensure_columns(pd.DataFrame(rows))

class ReviewTests(unittest.TestCase):
    def test_named_square_settlement_is_not_an_own_account_transfer(self):
        desc='TRANSFER FROM 01030 12 Square Canada 603122608453 PAYMENT'
        self.assertTrue(app.suggested_category(desc,'credit').startswith('True Revenue'))
        for other in ['TRANSFER FROM 01030 12',desc+' REFUND',desc+' SQUARE CAPITAL']:
            self.assertTrue(app.suggested_category(other,'credit').startswith('Non-Revenue'))
        self.assertFalse(app.suggested_category(desc,'debit').startswith('True Revenue'))
    def test_daily_balance_includes_quiet_calendar_days(self):
        df=pd.DataFrame([dict(account_id='a',date='2026-01-02',balance=1000.,amount=900.,tx_type='credit')])
        results=[dict(account_id='a',period_start='2026-01-01',period_end='2026-01-31',opening_balance='100.00')]
        result=app.daily_balance_metrics(df,results,['2026-01'])
        self.assertAlmostEqual(result['average_daily_balance'],30100/31)
        self.assertEqual(result['negative_days'],0)

    def test_bulk_only_selected_ids_and_never_debits(self):
        df=frame();out,rules,events=rev.commit_decisions(df,{'b':'True Revenue'})
        self.assertEqual(out.revenue_status.tolist(),['Review Required','True Revenue','Review Required','Not Applicable','Review Required','Review Required','Review Required'])
        self.assertEqual(len(events),1)
        with self.assertRaises(ValueError):rev.commit_decisions(df,{'a':'True Revenue','d':'True Revenue'})
        self.assertEqual(df.at[0,'revenue_status'],'Review Required')

    def test_remembered_rule_scoped_to_account_and_not_generic(self):
        out,rules,_=rev.commit_decisions(frame(),{'a':'True Revenue','e':'True Revenue'},remember=True)
        self.assertEqual(out.at[1,'revenue_status'],'True Revenue')
        self.assertEqual(out.at[2,'revenue_status'],'Review Required')
        self.assertEqual(out.at[5,'revenue_status'],'Review Required')
        self.assertEqual(len(rules),1)

    def test_human_decisions_survive_rules_and_ai(self):
        df,_,_=rev.commit_decisions(frame(),{'a':'Non-Revenue'})
        out=rev.apply_rules(df,{rev.rule_key('A','Acme Property | 123'):'True Revenue'})
        self.assertEqual(out.at[0,'revenue_status'],'Non-Revenue')

    def test_contrary_human_decision_removes_remembered_rule(self):
        df,rules,_=rev.commit_decisions(frame(),{'a':'True Revenue'},remember=True)
        _,rules,_=rev.commit_decisions(df,{'b':'Non-Revenue'},rules)
        self.assertFalse(rules)

    def test_return_and_financing_precede_processor(self):
        for desc in ['STRIPE CAPITAL','STRIPE REFUND','Moneris CHARGEBACK','VIREMENT ENTRE COMPTES']:
            self.assertTrue(app.suggested_category(desc,'credit').startswith('Non-Revenue'))
        self.assertIn('Refund',app.suggested_category('AFT Return NSF','credit'))

    def test_merchant_deposit_needs_matching_account_and_fee_reference(self):
        df=frame().iloc[:2].copy();df['account_id']='servus:test:chequing:1'
        df.loc[0,['description','tx_type']]=['DP123 | 99','credit']
        df.loc[1,['description','tx_type']]=['MRCH123 | 99','debit']
        self.assertEqual(rev.classify_local(df).at[0,'revenue_status'],'True Revenue')
        df.at[1,'account_id']='another'
        self.assertEqual(rev.classify_local(df).at[0,'revenue_status'],'Review Required')

    def test_ai_low_confidence_generic_and_duplicate_output_blocked(self):
        def call(key,model,prompt,payload,schema):
            groups=json.loads(payload)['deposits']
            return {'decisions':[dict(group_id=g['group_id'],decision='True Revenue',confidence=.99 if g['description']=='Business Deposit' else .6,
                                     evidence='explicit_customer_receipt',reason='test suggestion') for g in groups]}
        cache={};mock=Mock(side_effect=call)
        out=rev.classify_ai(frame(),'test','model',mock,cache)
        self.assertEqual(out.at[4,'revenue_status'],'Review Required')
        self.assertEqual(out.at[0,'revenue_status'],'Review Required')
        rev.classify_ai(frame(),'test','model',mock,cache)
        self.assertEqual(mock.call_count,1)
        rev.classify_ai(frame(),'test','model',mock,cache,context='changed business activity')
        self.assertEqual(mock.call_count,2)
        bad=Mock(return_value={'decisions':[]})
        with self.assertRaises(ValueError):rev.classify_ai(frame(),'test','model',bad,{})

    def test_ai_high_confidence_explicit_receipt_applied(self):
        df=frame().iloc[[0]].copy();df.at[0,'description']='Customer invoice payment #45'
        def call(k,m,p,payload,s):
            group=json.loads(payload)['deposits'][0]
            return {'decisions':[dict(group_id=group['group_id'],decision='True Revenue',confidence=.97,
                                     evidence='explicit_customer_receipt',reason='Invoice payment is explicit.') ]}
        out=rev.classify_ai(df,'test','model',call,{})
        self.assertEqual(out.at[0,'revenue_status'],'True Revenue')
        self.assertEqual(out.at[0,'classification_source'],'openai')

    def test_missing_printed_counts_warn_but_actual_mismatch_blocks(self):
        raw=dict(account_id='A',currency='CAD',period_start='2026-01-01',period_end='2026-01-31',
                 opening_balance=0,closing_balance=25,statement_total_debits=0,statement_total_credits=25,
                 transactions=[dict(sequence=1,page=1,date='2026-01-02',description='Receipt',credit=25,debit=None,balance=25)])
        result=app._validate_ai_statement_raw(raw,b'test','test.pdf','test')
        self.assertFalse(result['issues']);self.assertTrue(result['warnings'])
        raw['statement_credit_count']=2
        self.assertTrue(app._validate_ai_statement_raw(raw,b'test','test.pdf','test')['issues'])

    def test_currency_confirmation_does_not_clear_other_issues(self):
        original=[dict(currency_review_required=True,issues=[CURRENCY_ISSUE,'Balance mismatch'],currency=None)]
        out=confirm_cad(original,True)
        self.assertEqual(out[0]['issues'],['Balance mismatch'])
        self.assertEqual(out[0]['status'],'review_required')
        self.assertIsNone(original[0]['currency'])
        self.assertIn(CURRENCY_ISSUE,confirm_cad(out,False)[0]['issues'])

    def test_servus_six_supplied_statements(self):
        samples=[('e4ITG66DGZ0uuJr6j7oh',133,'132463.62'),('Nz8SIKFho7xth0MHuTMA',134,'212390.18'),
                 ('I4DzjvGrJJfGBJT7rYti',108,'108768.54'),('iTz4yz8ph3Le2wScdTEf',159,'224836.01'),
                 ('EkaMDUVdxdeODZSDKCeH',141,'172300.21'),('xYuKwRkgbZPkflxYJvRY',131,'160224.48')]
        base=Path('C:/Users/admin/Downloads')
        if not all((base/(n+'.pdf')).exists() for n,_,_ in samples):self.skipTest('Private fixtures not bundled')
        for name,count,credits in samples:
            with self.subTest(file=name):
                p=base/(name+'.pdf');r=app.extract_native(p.read_bytes(),p.name)
                self.assertEqual(len(r['transactions']),count);self.assertEqual(r['credits'],credits)
                self.assertEqual(r['issues'],[CURRENCY_ISSUE])
                self.assertTrue(r['account_id'].endswith(':chequing:1'))
                self.assertEqual(r['disclosed_loans'][0]['monthly_payment'],'632.99')
                self.assertFalse(confirm_cad([r],True)[0]['issues'])
                if name.startswith('xYu'):
                    self.assertEqual(r['transactions'][62]['balance'],'-127080.05')
                    self.assertEqual(r['transactions'][63]['balance'],'-126645.35')
                    self.assertEqual(r['transactions'][62]['page'],3)

if __name__=='__main__':unittest.main()
