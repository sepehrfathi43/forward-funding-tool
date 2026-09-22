import unittest
import pandas as pd
import debt_review as debt
import app as app

def ledger():
    return pd.DataFrame([
        dict(account_id='servus:test:chequing:1',date='2026-03-01',month='2026-03',description='Transfer to loan 3',tx_type='debit',amount=632.99,balance=-1000.),
        dict(account_id='servus:test:chequing:1',date='2026-03-02',month='2026-03',description='BDC | 1141968',tx_type='debit',amount=1500.,balance=-2500.),
        dict(account_id='servus:test:chequing:1',date='2026-03-03',month='2026-03',description='Net Banking Scotia Bank - Scotia Line',tx_type='debit',amount=500.,balance=-3000.),
        dict(account_id='servus:test:chequing:1',date='2026-03-04',month='2026-03',description='SUMMIT ACCEPTAN | 1870064',tx_type='debit',amount=1200.,balance=-4200.),
        dict(account_id='servus:test:chequing:1',date='2026-03-31',month='2026-03',description='Debit Interest',tx_type='debit',amount=900.,balance=-5100.)])

class DebtTests(unittest.TestCase):
    def test_statement_aliases_and_card_payments_require_verification(self):
        descriptions=['BUSINESS PAD BANQUE DEVELOPPEMENT DU CANAD',
                      'BUSINESS PAD ACCORD EXPRESS ACCORD SB FINANCE',
                      'TRANSFER TO CR. CARD 20152963 MB-CREDIT CARD/LOC PAY.', 'Loan']
        frame=pd.DataFrame([dict(account_id='a',date='2026-03-01',month='2026-03',
                            tx_type='debit',amount=200,description=d) for d in descriptions])
        positions=debt.seed_positions(frame,['2026-03'],app.lender_match)
        self.assertEqual(set(positions.lender),{'BDC','Accord financing','Credit card / line of credit payment','Unidentified loan payment'})
        self.assertEqual(debt.summary(positions)['unverified'],4)
        self.assertEqual(debt.summary(positions)['monthly_debt'],0)
        self.assertIsNone(debt.source_match(dict(tx_type='debit',description='NSF fee ACCORD EXPRESS'),app.lender_match))
    def test_detected_candidates_are_unverified_and_include_missed_lenders(self):
        positions=debt.seed_positions(ledger(),['2026-03'],app.lender_match)
        self.assertEqual(len(positions),5)
        self.assertEqual(set(positions.lender),{'Bank loan #3','BDC','Scotia Line','Summit Acceptan','Servus credit facility'})
        self.assertEqual(debt.summary(positions)['monthly_debt'],0)
        self.assertTrue(debt.readiness_issues(positions))

    def test_individual_verification_only_counts_that_position(self):
        positions=debt.seed_positions(ledger(),['2026-03'],app.lender_match)
        pid=positions.iloc[0].position_id
        out,_,_=debt.save_position(positions,pid,{'verified':True})
        self.assertEqual(debt.summary(out)['monthly_debt'],632.99)
        self.assertEqual(debt.summary(out)['unverified'],4)
        self.assertEqual(debt.summary(positions)['monthly_debt'],0)

    def test_material_edit_invalidates_mark_and_requires_fresh_verification(self):
        positions=debt.seed_positions(ledger(),['2026-03'],app.lender_match)
        pid=positions.iloc[0].position_id
        out,_,_=debt.save_position(positions,pid,{'verified':True})
        out,_,reset=debt.save_position(out,pid,{'verified':True,'payment_amount':700.})
        self.assertTrue(reset);self.assertEqual(debt.summary(out)['monthly_debt'],0)
        out,_,reset=debt.save_position(out,pid,{'verified':True})
        self.assertFalse(reset);self.assertEqual(debt.summary(out)['monthly_debt'],700.)

    def test_closed_and_not_debt_resolve_without_active_payment(self):
        positions=debt.seed_positions(ledger(),['2026-03'],app.lender_match)
        for i,row in positions.iterrows():
            positions,_,_=debt.save_position(positions,row.position_id,{'verified':True,'status':'Closed' if i%2 else 'Not debt'})
        self.assertFalse(debt.readiness_issues(positions));self.assertEqual(debt.summary(positions)['monthly_debt'],0)

    def test_mca_position_count_uses_only_verified_active_rows(self):
        positions=debt.seed_positions(ledger(),['2026-03'],app.lender_match)
        pid=positions.iloc[3].position_id
        out,_,_=debt.save_position(positions,pid,{'verified':True,'kind':'MCA','frequency':'Weekly','payment_amount':100.})
        self.assertEqual(debt.summary(out)['mca_positions'],1)
        self.assertEqual(debt.summary(out)['monthly_debt'],433.33)

    def test_tampered_checked_row_fails_verification_signature(self):
        positions=debt.seed_positions(ledger(),['2026-03'],app.lender_match)
        out,_,_=debt.save_position(positions,positions.iloc[0].position_id,{'verified':True})
        out.at[0,'payment_amount']=1
        self.assertEqual(debt.summary(out)['monthly_debt'],0)

    def test_legacy_rows_and_manual_new_row_start_unverified(self):
        out=debt.normalize(pd.DataFrame([dict(lender='Lender',kind='MCA',frequency='Monthly',payment_amount=200)]))
        self.assertEqual(debt.summary(out)['unverified'],1)
        added=debt.normalize(pd.concat([out,pd.DataFrame([dict(lender='New',status='Active',frequency='Monthly',payment_amount=0.)])],ignore_index=True))
        self.assertFalse(added.iloc[1].candidate)
        self.assertEqual(added.iloc[1].account_id,'')

    def test_invalid_verified_amount_rejected(self):
        positions=debt.seed_positions(ledger(),['2026-03'],app.lender_match)
        for amount in [-1,float('nan'),float('inf')]:
            with self.assertRaises(ValueError):debt.save_position(positions,positions.iloc[0].position_id,{'verified':True,'payment_amount':amount})

    def test_not_debt_returns_payment_to_operating_outflows(self):
        df=ledger();positions=debt.seed_positions(df,['2026-03'],app.lender_match)
        positions,_,_=debt.save_position(positions,positions.iloc[0].position_id,{'verified':True,'status':'Not debt'})
        auto=app.auto_underwriting_inputs(df,[],['2026-03'],positions)
        self.assertEqual(auto['monthly_debt'],0)
        self.assertEqual(auto['operating_outflows'],632.99)

if __name__=='__main__':unittest.main()
