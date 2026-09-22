"""Real Streamlit form interactions for individual debt verification."""
import importlib.util
import unittest

HAS_STREAMLIT = importlib.util.find_spec('streamlit') is not None


@unittest.skipUnless(HAS_STREAMLIT, 'Install requirements.txt for Streamlit UI tests')
class DebtUITests(unittest.TestCase):
    def harness(self):
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_string('''
import streamlit as st
import debt_review as debt
import app as app
from test_debt_review import ledger
debt.render(st, st.session_state, ledger(), ['2026-03'], app.lender_match)
''').run(timeout=30)
        self.assertFalse(at.exception)
        return at

    def save(self, at, index=0):
        [b for b in at.button if b.label == 'Save this position'][index].click().run(timeout=30)
        self.assertFalse(at.exception)

    def test_one_checkmark_does_not_verify_other_positions(self):
        import debt_review as debt
        at = self.harness()
        self.assertEqual(len(at.checkbox), 5)
        self.assertTrue(all(not c.value for c in at.checkbox))
        at.checkbox[0].check()
        self.save(at)
        totals = debt.summary(at.session_state['debts'])
        self.assertEqual(totals['active_positions'], 1)
        self.assertEqual(totals['unverified'], 4)
        self.assertEqual(totals['monthly_debt'], 632.99)
        self.assertTrue(at.checkbox[0].value)
        self.assertTrue(all(not c.value for c in list(at.checkbox)[1:]))
        self.assertEqual(len(at.session_state['debt_audit']), 1)

    def test_changing_verified_payment_clears_checkmark(self):
        import debt_review as debt
        at = self.harness()
        at.checkbox[0].check()
        self.save(at)
        at.session_state['underwriting_result'] = {'previous': True}
        at.number_input[0].set_value(700.)
        self.save(at)
        self.assertFalse(at.checkbox[0].value)
        self.assertEqual(debt.summary(at.session_state['debts'])['monthly_debt'], 0.)
        self.assertNotIn('underwriting_result', at.session_state)
        at.checkbox[0].check()
        self.save(at)
        self.assertEqual(debt.summary(at.session_state['debts'])['monthly_debt'], 700.)

    def test_resolve_unknown_candidate_as_not_debt(self):
        import debt_review as debt
        at = self.harness()
        statuses = [s for s in at.selectbox if s.label == 'Status']
        statuses[3].set_value('Not debt')
        at.checkbox[3].check()
        self.save(at, 3)
        self.assertTrue(at.checkbox[3].value)
        self.assertEqual(debt.summary(at.session_state['debts'])['unverified'], 4)
        self.assertEqual(debt.summary(at.session_state['debts'])['monthly_debt'], 0.)

    def test_new_position_requires_its_own_confirmation(self):
        at = self.harness()
        next(b for b in at.button if b.label == 'Add another debt position').click().run(timeout=30)
        self.assertFalse(at.exception)
        self.assertEqual(len(at.checkbox), 6)
        self.assertFalse(at.checkbox[-1].value)
        at.checkbox[-1].check()
        self.save(at, 5)
        self.assertTrue(at.error)
        self.assertIn('Lender is required', at.error[0].value)


if __name__ == '__main__':
    unittest.main()
