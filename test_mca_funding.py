import unittest
import pandas as pd
import app
import business_identity
import mca_funding
from payment_risk import nsf_summary


class FundingReviewTests(unittest.TestCase):
    def row(self, kind, amount, date='2026-03-01', description='GREENBOX', account='a', currency='CAD'):
        return dict(tx_type=kind,amount=amount,date=date,description=description,account_id=account,currency=currency,id=f'{kind}-{amount}-{date}')

    def table(self, rows):
        return mca_funding.funding_table(pd.DataFrame(rows),app.lender_match)

    def test_completed_and_remaining(self):
        rows=[self.row('credit',1000),self.row('debit',1460,'2026-03-02')]
        result=self.table(rows).iloc[0]
        self.assertEqual(result['Estimated total repayment'],1460)
        self.assertEqual(result['Estimated remaining'],0)
        self.assertIn('Expected completed',result['Completion estimate'])
        rows[1]['amount']=460
        self.assertEqual(self.table(rows).iloc[0]['Estimated remaining'],1000)

    def test_missing_advance_and_multiple_contracts(self):
        result=self.table([self.row('debit',100)]).iloc[0]
        self.assertIsNone(result['Funding amount'])
        self.assertIn('Unknown',result['Completion estimate'])
        result=self.table([self.row('credit',1000),self.row('credit',500,'2026-03-02'),self.row('debit',3000,'2026-03-03')])
        self.assertTrue(result['Estimated remaining'].isna().all())
        self.assertTrue(result['Completion estimate'].str.startswith('Unknown').all())

    def test_returns_fees_and_before_funding(self):
        rows=[self.row('credit',1000),self.row('debit',1460,'2026-03-02'),
              self.row('credit',1460,'2026-03-03','Cheque Returned NSF'),
              self.row('debit',48,'2026-03-03','GREENBOX NSF FEE'),
              self.row('debit',500,'2026-02-20')]
        result=self.table(rows).iloc[0]
        self.assertEqual(result['Observed payment debits'],1460)
        self.assertIn('Unknown',result['Completion estimate'])

    def test_separate_accounts_currencies(self):
        rows=[self.row('credit',1000),self.row('debit',1500,account='b'),self.row('debit',1500,currency='USD')]
        result=self.table(rows)
        self.assertEqual(len(result),3)
        self.assertEqual(result.iloc[0]['Observed payment debits'],0)

    def test_trade_name_and_returned_item_fee(self):
        text='JANE DOE\nMALACHITE MUSIC EVENTS Forquestionsaboutyour\nTransactiondetails\nBusinessname:\nJANEDOE\nOperatingas:\nMALACHITEMUSICEVENTS\nFeb02 Deposit 100'
        self.assertEqual(business_identity.header_names(text),['JANE DOE','MALACHITE MUSIC EVENTS'])
        result=nsf_summary(pd.DataFrame([self.row('debit',48,description='ReturnedItemFee'),self.row('credit',48.4,description='ChequeReturned NSF')]))
        self.assertEqual(result['fee_amount'],48)
        self.assertEqual(result['returned_items'],1)

    def test_table_visible_in_bank_summary(self):
        from streamlit.testing.v1 import AppTest
        at=AppTest.from_string('''
import streamlit as st,pandas as pd,app,mca_funding
df=pd.DataFrame([dict(date='2026-03-01',tx_type='credit',amount=1000,description='GREENBOX',account_id='a',currency='CAD',id='1')])
mca_funding.render(st,df,app.lender_match)
''').run()
        self.assertFalse(at.exception)
        self.assertEqual(at.dataframe[0].value.iloc[0]['Funding amount'],1000)


if __name__=='__main__':unittest.main()
