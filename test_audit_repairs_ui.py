import unittest
from streamlit.testing.v1 import AppTest


class AuditRepairUI(unittest.TestCase):
    def test_unknown_currency_is_not_offered_an_fx_rate(self):
        at=AppTest.from_string('''
import streamlit as st
import app
from test_gap_offers import GapOfferTests
if 'ledger' not in st.session_state:
    r=GapOfferTests().statement('2026-03',30000)
    r.update(currency=None,status='review_required',issues=['Currency not printed explicitly; verify CAD before underwriting.'])
    st.session_state.results=[r]
    st.session_state.ledger=app.assemble_ledger([r])
app.main()
''').run(timeout=45)
        self.assertFalse(at.exception)
        self.assertFalse(any('CAD per 1 Unknown' in n.label for n in at.number_input))
        self.assertTrue(any('currencies are unidentified' in w.value for w in at.warning))

    def test_negative_cashflow_still_shows_revenue_range(self):
        at=AppTest.from_string('''
import streamlit as st
import app
from test_gap_offers import GapOfferTests
if 'ledger' not in st.session_state:
    r=GapOfferTests().statement('2026-03',30000)
    r['transactions'].append(dict(id='expense',date='2026-03-02',month='2026-03',amount='40000',balance='-10000',description='Rent and supplies',tx_type='debit'))
    r.update(closing_balance='-10000',status='reconciled_candidate_review_required',issues=[])
    st.session_state.results=[r]
    st.session_state.ledger=app.assemble_ledger([r])
app.main()
''').run(timeout=45)
        self.assertFalse(at.exception)
        for s in at.selectbox:
            if s.label=='Industry':s.select('8011 - Offices & Clinics of Doctors of Medicine')
            if s.label=='Public records':s.select('Clean')
            if s.label=='Bank verification':s.select('Original PDF')
        next(n for n in at.number_input if n.label=='Time in business (months)').set_value(100)
        for c in at.checkbox:
            if c.label.startswith(('I compared statement','This is one business','I understand the partial')):c.check()
        next(b for b in at.button if b.label=='Calculate conditional estimated range').click().run(timeout=45)
        self.assertFalse(at.exception)
        self.assertFalse(at.error, [e.value for e in at.error]+[m.value for m in at.markdown])
        result=at.session_state['underwriting_result']
        self.assertGreater(result['base']['amount'],0)
        self.assertLess(result['recommendation']['low_amount'],result['recommendation']['median_amount'])
        self.assertLess(result['recommendation']['median_amount'],result['recommendation']['high_amount'])
        self.assertEqual(result['base']['funding_position'],1)
        self.assertEqual(result['base']['capacity_breakdown']['cashflow_capacity'],-10000)
        self.assertTrue(any('Observed cash flow is negative' in w.value for w in at.warning))
