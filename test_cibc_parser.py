"""Regression coverage for the coordinate-aware CIBC account statement reader."""
import unittest
from pathlib import Path

import app as app
from servus_parser import confirm_cad


class CIBCStatementTests(unittest.TestCase):
    names = [
        'Y7uQfLgzOUzAAjkPYKrm.pdf', 'k7kags73at2fJp4KQghf.pdf',
        '4UlDqCGH3qLQrOzVJGli.pdf', 'kbzjihYQC1qSbxPaMoJD.pdf',
        'mSZw4a4SmGkgUmSI3NuX.pdf', '2nh5Ob1MAG2GqmIrht0o.pdf',
    ]

    @classmethod
    def setUpClass(cls):
        files = [Path('C:/Users/admin/Downloads') / name for name in cls.names]
        if not all(path.exists() for path in files):
            raise unittest.SkipTest('Private CIBC statements are not available')
        cls.results = [app.extract_native(path.read_bytes(), path.name) for path in files]

    def test_all_six_periods_reconcile_to_printed_totals(self):
        expected = {
            'Y7uQfLgzOUzAAjkPYKrm.pdf': (40, '8419.00', '22891.86'),
            'k7kags73at2fJp4KQghf.pdf': (67, '32593.16', '17615.44'),
            '4UlDqCGH3qLQrOzVJGli.pdf': (74, '19300.82', '21654.52'),
            'kbzjihYQC1qSbxPaMoJD.pdf': (104, '22184.86', '20471.26'),
            'mSZw4a4SmGkgUmSI3NuX.pdf': (63, '15461.25', '14480.36'),
            '2nh5Ob1MAG2GqmIrht0o.pdf': (50, '15926.64', '19187.87'),
        }
        for result in self.results:
            rows, debits, credits = expected[result['source_file']]
            self.assertEqual(result['adapter'], 'cibc_account_statement')
            self.assertEqual(result['account_id'], 'cibc:40-61411')
            self.assertEqual(len(result['transactions']), rows)
            self.assertEqual(result['debits'], debits)
            self.assertEqual(result['credits'], credits)
            self.assertEqual(result['issues'], [
                'Currency not printed explicitly; verify CAD before underwriting.'
            ])

    def test_confirmed_currency_unlocks_consolidated_underwriting_period(self):
        confirmed = confirm_cad(self.results, True)
        self.assertEqual(app.full_months(confirmed), [
            '2026-03', '2026-04', '2026-05', '2026-06', '2026-07', '2026-08'
        ])
        ledger = app.assemble_ledger(confirmed)
        self.assertEqual(len(ledger), 398)
        self.assertAlmostEqual(ledger[ledger.tx_type.eq('credit')].amount.sum(), 116301.31)
        self.assertAlmostEqual(ledger[ledger.tx_type.eq('debit')].amount.sum(), 113885.73)
        self.assertTrue(all(result['status'] == 'reconciled_candidate_review_required' for result in confirmed))


if __name__ == '__main__':
    unittest.main()
