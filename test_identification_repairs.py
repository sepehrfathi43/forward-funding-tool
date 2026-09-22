import unittest
from pathlib import Path
import app
import business_identity
import pandas as pd
import currency_reporting
from streamlit.testing.v1 import AppTest


class IdentificationRepairs(unittest.TestCase):
    def test_rbc_header_excludes_corporate_transaction_counterparties(self):
        text='FOCUSED FORWARD INC.\nAccount Activity Details\n12 Nov e-Transfer received SPOKES ALLIANCE INC\nPrairie Rail Solutions Ltd.'
        self.assertEqual(business_identity.header_names(text),['FOCUSED FORWARD INC.'])
        self.assertEqual(business_identity.header_names('MAVIN COFFEE CORP\nAccount Details:'),['MAVIN COFFEE CORP'])
    def test_numbered_and_named_headers_not_transaction_counterparties(self):
        text='12474816CANADAINC.\n1234567 ONTARIO INC.\n9250-9702 QUÉBEC INC.\nExample Services Ltd.\nAccount Details:\n9999999 CANADA INC.'
        self.assertEqual(business_identity.header_names(text),['12474816 CANADA INC.','1234567 ONTARIO INC.','9250-9702 QUÉBEC INC.','Example Services Ltd.'])
        self.assertEqual(len(business_identity.distinct(['9250-9702 QUÉBEC INC.','92509702 Quebec Inc'])),1)

    def test_combined_case_name_and_batch_survive_reruns(self):
        ss={'case_reference':'old','rules_case':'old','processed_batch':app.statement_batch('old',[]),
            'results':[{'account_holder':'12474816 CANADA INC.'},{'account_holder':'12828383 CANADA INC.'}],
            'ledger':'preserved'}
        app.sync_statement_case(ss,[])
        self.assertEqual(ss['case_reference'],'12474816 CANADA INC. / 12828383 CANADA INC.')
        self.assertEqual(ss['ledger'],'preserved')
        self.assertEqual(ss['processed_batch'],app.statement_batch(ss['case_reference'],[]))
        app.sync_statement_case(ss,[])
        self.assertEqual(len(ss['case_name_audit']),1)
        ss['auto_case_name']=False;ss['case_reference']='manual';app.sync_statement_case(ss,[])
        self.assertEqual(ss['case_reference'],'manual')

    def test_branch_deposits_require_review_without_proven_transfer(self):
        for text in ['Deposit at, BR. 2069','Deposit at, BR. 2429']:
            self.assertTrue(app.suggested_category(text,'credit').startswith('Review Required'))
        self.assertTrue(app.suggested_category('ONLINE TRANSFER','credit').startswith('Non-Revenue'))
        self.assertTrue(app.suggested_category('MERCHANT GROWTH','credit').startswith('Non-Revenue'))

    def test_reciprocal_transfers_require_same_holder_currency_and_unique_pair(self):
        for bank,credit_account,debit_account,credit_desc,debit_desc in [
            ('BMO','bmo_business:23771990-331','bmo_business:23778951-431','Transfer, 2377-8951-431 3587','Transfer, 2377-1990-331 3587'),
            ('Scotia','scotia:239520308811','scotia:239520386316','TRANSFER FROM 23952 03863 16','TRANSFER TO 23952 03088 11')]:
            rows=[dict(account_id=a,account_holder='1234567 CANADA INC.',date='2026-05-04',currency='CAD',
                       tx_type=t,description=d,amount=500.,reviewed=False,revenue_status='Review Required')
                  for a,t,d in [(credit_account,'credit',credit_desc),(debit_account,'debit',debit_desc)]]
            frame=pd.DataFrame(rows)
            self.assertEqual(currency_reporting.match_internal_transfers(frame).internal_transfer.sum(),2,bank)
            other=frame.copy();other.loc[1,'account_holder']='7654321 CANADA INC.'
            self.assertFalse(currency_reporting.match_internal_transfers(other).internal_transfer.any())
            unknown=frame.copy();unknown['currency']=None
            self.assertFalse(currency_reporting.match_internal_transfers(unknown).internal_transfer.any())
            duplicate=pd.concat([frame,frame.iloc[[0]]],ignore_index=True)
            self.assertFalse(currency_reporting.match_internal_transfers(duplicate).internal_transfer.any())

    def test_combined_name_visible_with_multi_entity_warning(self):
        at=AppTest.from_string('''
import streamlit as st
import app
from test_gap_offers import GapOfferTests
if 'results' not in st.session_state:
    results=[]
    for account,name in [('A','12474816 CANADA INC.'),('B','12828383 CANADA INC.')]:
        r=GapOfferTests().statement('2026-04',50000,account)
        r.update(account_holder=name,issues=[],status='reconciled_candidate_review_required')
        results.append(r)
    st.session_state.results=results
    st.session_state.ledger=app.assemble_ledger(results)
app.main()
''').run(timeout=45)
        self.assertFalse(at.exception)
        self.assertEqual(at.session_state['case_reference'],'12474816 CANADA INC. / 12828383 CANADA INC.')
        self.assertTrue(any('Different account holders' in w.value for w in at.warning))
        at.run(timeout=45);self.assertFalse(at.exception)


if __name__=='__main__':unittest.main()
