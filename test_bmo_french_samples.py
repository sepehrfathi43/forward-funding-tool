"""Regression coverage for the supplied six-month BMO French statement set."""
import unittest
from pathlib import Path

import app as app


class BmoFrenchSampleTests(unittest.TestCase):
    root = Path('C:/Users/admin/Downloads')
    samples = [
        ('11NPovH6e1ahZuTqSca7.pdf', '76240.89', '76961.45', '168', '2026-02-28', '2026-03-31'),
        ('z2XbZWyIsPj58MnwjC7W.pdf', '100582.52', '102627.34', '151', '2026-04-01', '2026-04-30'),
        ('bDIzsPVV2USdIxiKaBX6.pdf', '27795.86', '46245.80', '110', '2026-05-01', '2026-05-29'),
        ('ne13GIX5rI3tzUSl1tDa.pdf', '83411.72', '62747.42', '148', '2026-05-30', '2026-06-30'),
        ('MNQGKiyKyVWpfXjSg2lh.pdf', '120074.40', '127487.15', '219', '2026-07-01', '2026-07-31'),
        ('FjCoN6L2P48988wXeALv (1).pdf', '51414.46', '52890.54', '135', '2026-08-01', '2026-08-31'),
    ]

    def test_all_supplied_bmo_statements_reconcile(self):
        missing = [name for name, *_ in self.samples if not (self.root / name).exists()]
        if missing:
            self.skipTest('Private BMO samples are not available: ' + ', '.join(missing))
        results = []
        for name, debits, credits, rows, period_start, period_end in self.samples:
            result = app.extract_native((self.root / name).read_bytes(), name)
            self.assertEqual(result['adapter'], 'bmo_business_french', name)
            self.assertEqual(result['status'], 'reconciled_candidate_review_required', name)
            self.assertEqual(result['issues'], [], name)
            self.assertEqual(result['debits'], debits, name)
            self.assertEqual(result['credits'], credits, name)
            self.assertEqual(str(len(result['transactions'])), rows, name)
            self.assertEqual(result['period_start'], period_start, name)
            self.assertEqual(result['period_end'], period_end, name)
            results.append(result)
        self.assertEqual(app.full_months(results), ['2026-03', '2026-04', '2026-05', '2026-06', '2026-07', '2026-08'])


if __name__ == '__main__':
    unittest.main()
