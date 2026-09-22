"""Focused checks for the cross-format validation and cash-flow layer."""
import unittest
from decimal import Decimal
from pathlib import Path
import pandas as pd

import cashflow
import debt_review
import app as app
from statement_validation import parse_money, validate_statement


class SharedValidationTests(unittest.TestCase):
    def test_money_signs_and_locales_are_preserved(self):
        cases = {
            "(1,234.56)": Decimal("-1234.56"),
            "1 234,56-": Decimal("-1234.56"),
            "2,000 DR": Decimal("-2000.00"),
            "$3,800": Decimal("3800.00"),
            "20": Decimal("20.00"),
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(parse_money(source), expected)
        with self.assertRaises(ValueError):
            parse_money("12.3.4")

    def test_shared_validator_rejects_bad_dates_without_repairing_rows(self):
        result = {
            "period_start": "2026-01-01", "period_end": "2026-01-31",
            "opening_balance": "100.00", "closing_balance": "110.00",
            "statement_totals": {"debits": "0.00", "credits": "10.00"},
            "statement_counts": {"debits": 0, "credits": 1},
            "transactions": [{"id": "x", "page": 1, "date": "2026-01-32",
                "month": "2026-01", "description": "Payment", "amount": "10.00",
                "tx_type": "credit", "balance": "110.00"}],
            "issues": [], "status": "reconciled_candidate_review_required",
        }
        validate_statement(result)
        self.assertEqual(result["transactions"][0]["date"], "2026-01-32")
        self.assertEqual(result["status"], "review_required")
        self.assertTrue(result["validation"]["errors"])

    def test_latest_offer_months_stop_at_a_gap(self):
        self.assertEqual(cashflow.latest_consecutive_months(
            ["2025-12", "2026-01", "2026-02", "2026-05", "2026-06"]),
            ["2026-05", "2026-06"])

    def test_debt_split_is_unverified_and_keeps_evidence(self):
        frame = pd.DataFrame([{
            "position_id": "p", "verified": False, "lender": "Test",
            "kind": "MCA", "status": "Active", "frequency": "Weekly",
            "payment_amount": 250., "account_id": "A", "reference": "one",
            "candidate": True, "evidence": [{"date": "2026-01-01", "amount": "250.00"}],
        }])
        out = debt_review.split_position(frame, "p")
        self.assertEqual(len(out), 2)
        self.assertTrue((out.verified == False).all())
        self.assertEqual(len(out.iloc[1].evidence), 1)
        self.assertEqual(float(out.iloc[1].payment_amount), 0.)

    def test_rbc_fixture_has_no_date_or_reconciliation_errors(self):
        paths = [Path("C:/Users/admin/Downloads") / name for name in (
            "OUNRhaClHxMivy0Pgygl.pdf", "xMT6sIKJ6EA4LpGicSas.pdf",
            "TL0rk9gaVyr3SneaeYJr.pdf", "0sQBLbCZGi5RfAQsMzMM.pdf",
            "HZp6nUShQH8mlbbjTtuT.pdf", "zugydZ2LydS1nS02H5Z6.pdf")]
        if not all(path.exists() for path in paths):
            self.skipTest("Private RBC fixtures not bundled")
        expected = [(206, "50176.55", "50105.07"), (300, "122793.31", "140268.85"),
                    (235, "94148.21", "76574.70"), (301, "105249.16", "100030.18"),
                    (268, "119181.11", "117227.45"), (361, "130708.00", "136022.43")]
        for path, (count, debits, credits) in zip(paths, expected):
            result = app.extract_native(path.read_bytes(), path.name)
            with self.subTest(file=path.name):
                self.assertEqual(len(result["transactions"]), count)
                self.assertEqual((result["debits"], result["credits"]), (debits, credits))
                self.assertFalse(result["issues"])


if __name__ == "__main__":
    unittest.main()
