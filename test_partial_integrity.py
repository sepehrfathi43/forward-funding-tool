import io
import unittest

import app
import cashflow
import statement_integrity
import test_gap_offers


class PartialCoverageTests(unittest.TestCase):
    def statement(self, start, end, amount=15000, opening='100.00', account='A'):
        result = test_gap_offers.GapOfferTests().statement(start[:7], amount, account)
        result.update(period_start=start, period_end=end, opening_balance=opening,
                      closing_balance=str(float(opening) + amount))
        result['transactions'][0].update(date=start, balance=result['closing_balance'])
        return result

    def test_partial_month_estimates_without_inventing_observed_revenue(self):
        results = [self.statement('2026-04-16', '2026-04-30')]
        frame = app.assemble_ledger(results)
        months = app.offer_months(results)
        self.assertEqual(months, ['2026-04'])
        metrics = app.metrics(frame, months, 1000, results)
        self.assertEqual(metrics['observed_monthly']['2026-04'], 15000)
        self.assertEqual(metrics['avg'], 30000)
        self.assertIsNone(metrics['trend'])
        auto = app.auto_underwriting_inputs(frame, results, months)
        self.assertEqual(auto['average_daily_balance'], 15100)
        self.assertEqual(auto['negative_days'], 0)
        self.assertEqual(cashflow.daily_balances(frame, results, months)['covered_days'], 15)

    def test_internal_gap_never_carries_balance_across_unknown_days(self):
        results = [self.statement('2026-04-01', '2026-04-05', 100, '0.00'),
                   self.statement('2026-04-21', '2026-04-25', 200, '0.00')]
        results[1]['transactions'][0]['id'] = 'second'
        frame = app.assemble_ledger(results)
        daily = cashflow.daily_balances(frame, results, ['2026-04'])
        self.assertEqual(daily['covered_days'], 10)
        self.assertEqual(daily['average_daily_balance'], 150)
        self.assertEqual(app.metrics(frame, ['2026-04'], 0, results)['avg'], 900)

    def test_common_dates_filter_revenue_and_daily_balances(self):
        results = [self.statement('2026-04-01', '2026-04-30', 100, account='A'),
                   self.statement('2026-04-16', '2026-04-30', 200, account='B')]
        frame = app.assemble_ledger(results)
        metrics = app.metrics(frame, ['2026-04'], 0, results)
        self.assertEqual(metrics['observed_monthly']['2026-04'], 200)
        self.assertEqual(metrics['avg'], 400)
        self.assertEqual(cashflow.daily_balances(frame, results, ['2026-04'])['average_daily_balance'], 500)

    def test_expenses_use_same_exposure_as_revenue(self):
        result = self.statement('2026-04-16', '2026-04-30')
        result['transactions'].append(dict(id='rent', date='2026-04-17', month='2026-04',
            tx_type='debit', description='RENT', amount='3000.00', balance='12100.00'))
        frame = app.assemble_ledger([result])
        auto = app.auto_underwriting_inputs(frame, [result], ['2026-04'])
        self.assertEqual(auto['operating_outflows'], 6000)

    def test_leap_year_and_excluded_accounts(self):
        results = [self.statement('2024-02-01', '2024-02-29')]
        results.append(dict(exclude_from_ledger=True, account_id='other'))
        self.assertEqual(cashflow.coverage_summary(results)[0]['covered_days'], 29)
        self.assertEqual(app.full_months(results), ['2024-02'])

    def test_disjoint_accounts_do_not_create_consolidated_estimate(self):
        results = [self.statement('2026-04-01', '2026-04-10', account='A'),
                   self.statement('2026-04-20', '2026-04-30', account='B')]
        self.assertEqual(app.offer_months(results), [])


class IntegrityTests(unittest.TestCase):
    def test_real_generated_pdf_metadata_and_overlapping_digits(self):
        from reportlab.pdfgen.canvas import Canvas
        buffer = io.BytesIO()
        canvas = Canvas(buffer)
        canvas.setCreator('Adobe Photoshop')
        canvas.drawString(100, 100, '1')
        canvas.drawString(100, 100, '9')
        canvas.save()
        report = statement_integrity.inspect_pdf(buffer.getvalue(), 'test.pdf')
        codes = {f['code'] for f in report['flags']}
        self.assertIn('EDITING_SOFTWARE', codes)
        self.assertIn('OVERLAPPING_DIGITS', codes)
        self.assertEqual(report['status'], 'review_required')
        self.assertEqual(len(report['source_sha256']), 64)

    def test_normal_pdf_not_authenticated(self):
        from reportlab.pdfgen.canvas import Canvas
        buffer = io.BytesIO()
        canvas = Canvas(buffer)
        canvas.drawString(100, 100, 'Example bank statement 123')
        canvas.save()
        report = statement_integrity.inspect_pdf(buffer.getvalue(), 'test.pdf')
        self.assertEqual(report['status'], 'no_signals_detected')
        self.assertIn('cannot establish authenticity', report['limitation'])

    def test_unreadable_pdf_is_not_clean(self):
        self.assertEqual(statement_integrity.inspect_pdf(b'broken', 'test.pdf')['status'], 'unavailable')

    def test_revision_signal_is_explicitly_weak(self):
        report = statement_integrity.inspect_pdf(b'%%EOF /Prev 12 %%EOF', 'test.pdf')
        self.assertIn('PDF_REVISIONS', {f['code'] for f in report['flags']})

    def test_continuity_is_checked_only_for_adjacent_same_currency_accounts(self):
        results = [dict(account_id='A', currency='CAD', period_start='2026-01-01',
                        period_end='2026-01-31', closing_balance='100.00', source_file='a'),
                   dict(account_id='A', currency='CAD', period_start='2026-02-01',
                        period_end='2026-02-28', opening_balance='200.00', source_file='b')]
        self.assertEqual(statement_integrity.statement_flags(results)[0]['code'], 'BALANCE_CONTINUITY')
        results[1]['period_start'] = '2026-02-02'
        self.assertEqual(statement_integrity.statement_flags(results), [])


if __name__ == '__main__':
    unittest.main()
