import unittest
from pathlib import Path

import app as app


class FlinksParserTests(unittest.TestCase):
    fixture = Path('C:/Users/admin/Downloads/Darren James Gervais - Insights _ Flinks Dashboard.pdf')

    def test_flinks_dashboard_is_reconciled_locally(self):
        if not self.fixture.exists():
            self.skipTest('Private Flinks fixture is not available')
        result = app.extract_native(self.fixture.read_bytes(), self.fixture.name)
        self.assertEqual(result['adapter'], 'flinks_dashboard')
        self.assertEqual(len(result['transactions']), 624)
        self.assertEqual(result['credits'], '372978.57')
        self.assertEqual(result['debits'], '381633.11')
        self.assertEqual(result['opening_balance'], '14850.20')
        self.assertEqual(result['closing_balance'], '6195.66')
        self.assertEqual(result['running_balance_checks'], 623)
        self.assertEqual(result['account_id'], 'flinks:004-26902-5215907')
        self.assertEqual(result['employer_name'], 'fossilenergy')
        self.assertEqual(result['issues'], [app.CURRENCY_ISSUE])
        self.assertEqual(len(app.assemble_ledger([result])), 624)

    def test_statement_handoff_date_is_not_an_overlap(self):
        results = [
            dict(account_id='a', period_start='2026-03-01', period_end='2026-04-30', source_file='march.pdf'),
            dict(account_id='a', period_start='2026-04-30', period_end='2026-05-29', source_file='april.pdf'),
        ]
        self.assertEqual(app.overlap_issues(results), [])
        results[1]['period_start'] = '2026-04-15'
        self.assertTrue(app.overlap_issues(results))


if __name__ == '__main__':
    unittest.main()
