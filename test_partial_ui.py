import unittest
from streamlit.testing.v1 import AppTest


class PartialUITests(unittest.TestCase):
    def test_partial_estimate_acknowledgment_integrity_review_and_memo(self):
        at = AppTest.from_string('''
import streamlit as st
import app
from test_partial_integrity import PartialCoverageTests
if 'ledger' not in st.session_state:
    result=PartialCoverageTests().statement('2026-04-16','2026-04-30',30000)
    result.update(issues=[],status='reconciled_candidate_review_required')
    st.session_state.results=[result]
    st.session_state.ledger=app.assemble_ledger([result])
    st.session_state.integrity_reports=[{'source_file':'sample.pdf','flags':[{'code':'PDF_REVISIONS','evidence':'Synthetic review signal'}]}]
app.main()
''').run(timeout=45)
        self.assertFalse(at.exception)
        self.assertTrue(any(m.label == 'Estimated monthly reviewed revenue' and m.value == '$60,000.00' for m in at.metric))
        for select in at.selectbox:
            if select.label == 'Industry':select.select('8011 - Offices & Clinics of Doctors of Medicine')
            if select.label == 'Public records':select.select('Clean')
            if select.label == 'Bank verification':select.select('Original PDF')
        next(n for n in at.number_input if n.label == 'Time in business (months)').set_value(100)
        for checkbox in at.checkbox:
            if checkbox.label.startswith(('I compared statement', 'This is one business')):
                checkbox.check()
        submit = lambda: next(b for b in at.button if b.label == 'Calculate conditional estimated range')
        submit().click().run(timeout=45)
        self.assertFalse(at.exception)
        self.assertTrue(any('Review required' in e.value for e in at.error))
        for checkbox in at.checkbox:
            if checkbox.label.startswith(('I understand the partial', 'I reviewed the integrity')):
                checkbox.check()
        next(t for t in at.text_input if t.label == 'Integrity review evidence / bank reference').set_value('Synthetic independent bank confirmation')
        submit().click().run(timeout=45)
        self.assertFalse(at.exception)
        memo = at.session_state['underwriting_result']
        self.assertEqual(memo['complete_months'], [])
        self.assertEqual(memo['coverage'][0]['covered_days'], 15)
        self.assertTrue(memo['coverage_warnings'])
        self.assertEqual(memo['integrity_flags'][0]['code'], 'PDF_REVISIONS')
        self.assertEqual(memo['status'], 'conditional_human_review')
        self.assertGreater(memo['base']['amount'], 0)
        self.assertIn('policy_version', memo['base'])
