import unittest
from unittest.mock import patch
from types import SimpleNamespace
import pandas as pd
from vancity_parser import parse_vancity
from currency_reporting import match_internal_transfers
from servus_parser import CURRENCY_ISSUE


class VancityTests(unittest.TestCase):
    def parse(self, missing=False):
        summary = 'STATEMENT PERIOD: 01 AUG 2026 to 31 AUG 2026\nINDEPENDENT BUSINESS ACCOUNT #123\n0.00 10.00 20.00 10.00\nTOTAL NUMBER OF CHEQUES'
        def line(y, *cells):
            return y, [dict(x0=x,text=t) for x,t in cells]
        lines = [line(10,(105,'INDEPENDENT BUSINESS ACCOUNT #123')),
                 line(20,(70,'DATE'),(105,'DESCRIPTION'),(380,'WITHDRAWALS'),(464,'DEPOSITS'),(533,'BALANCE')),
                 line(30,(70,'01AUG'),(105,'CHEQUE DEPOSIT-BRANCH'),(470,'20.00'),(540,'20.00'))]
        if not missing:
            lines += [line(40,(70,'02AUG'),(105,'CHEQUE DEPOSIT-BRANCH'),(410,'10.00'),(540,'10.00'))]
        lines += [line(50,(70,'02AUG'),(105,'INTEREST RATE CHANGE (INTEREST RATE CHANGE TO 0)'),(540,'10.00')),
                  line(60,(105,'INVESTMENTS')),
                  line(70,(70,'03AUG'),(105,'TERM DEPOSIT TRANSFER-CREDIT'),(470,'1000.00'),(540,'1000.00'))]
        doc = SimpleNamespace(pages=[SimpleNamespace(extract_text=lambda:summary)])
        with patch('vancity_parser._word_lines',return_value=lines):
            return parse_vancity(b'test','test.pdf',doc)

    def test_columns_metadata_and_investments(self):
        root=self.parse(); r=root['account_statements'][0]
        self.assertTrue(root['exclude_from_ledger'])
        self.assertEqual([t['tx_type'] for t in r['transactions']],['credit','debit'])
        self.assertEqual(r['issues'],[CURRENCY_ISSUE])
        self.assertTrue(r['warnings'])

    def test_missing_row_not_accepted(self):
        r=self.parse(missing=True)['account_statements'][0]
        self.assertTrue(any('does not match' in i for i in r['issues']))
        self.assertEqual(r['status'],'review_required')

    def test_reciprocal_transfer_and_ambiguity(self):
        rows=[dict(account_id='vancity:123',description='FUNDS TRANSFER-ONLINE TO #10456 ($20.00)',tx_type='debit'),
              dict(account_id='vancity:456',description='FUNDS TRANSFER-ONLINE FROM #10123 ($20.00)',tx_type='credit')]
        f=pd.DataFrame([dict(r,date='2026-08-01',currency='CAD',amount=20.0) for r in rows])
        self.assertEqual(match_internal_transfers(f).internal_transfer.sum(),2)
        ambiguous=pd.concat([f,f.iloc[[1]]],ignore_index=True)
        self.assertFalse(match_internal_transfers(ambiguous).internal_transfer.any())
        f.loc[1,'amount']=21
        self.assertFalse(match_internal_transfers(f).internal_transfer.any())

if __name__=='__main__':unittest.main()
