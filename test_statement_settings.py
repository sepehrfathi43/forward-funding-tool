import unittest
from datetime import date
import statement_settings as settings
from servus_parser import CURRENCY_ISSUE


class StatementSettingsTests(unittest.TestCase):
    def test_default_cad_is_assumption_and_usd_is_preserved(self):
        rows=[{'currency':None,'issues':[CURRENCY_ISSUE]}, {'currency':'USD','issues':[]}]
        out=settings.apply_currency(rows)
        self.assertEqual(out[0]['currency'],'CAD')
        self.assertEqual(out[0]['currency_source'],'case_policy_default_cad')
        self.assertEqual(out[1]['currency'],'USD')
        self.assertIsNone(rows[0]['currency'])
        self.assertIsNone(settings.apply_currency(out,True)[0]['currency'])
        self.assertEqual(settings.apply_currency(out,True,{0:'USD'})[0]['currency'],'USD')

    def test_coverage_requires_source_and_contains_all_rows(self):
        row=dict(id='1',date='2026-03-11',month='2026-03',amount='10',tx_type='credit',description='Receipt',balance='10',page=1)
        result=dict(period_start=None,period_end=None,opening_balance='0',closing_balance='10',transactions=[row],issues=['AI did not identify a complete statement period'])
        self.assertTrue(settings.invalid_period(result))
        out=settings.confirm_period(result,date(2026,3,1),date(2026,3,31),'Original statement period')
        self.assertFalse(settings.invalid_period(out))
        self.assertEqual(out['validation']['errors'],0)
        self.assertIsNone(result['period_start'])
        with self.assertRaises(ValueError):settings.confirm_period(result,date(2026,3,12),date(2026,3,31),'source')
        with self.assertRaises(ValueError):settings.confirm_period(result,date(2026,3,1),date(2026,3,31),'')

    def test_controls_are_on_document_analyzer_and_kpis_on_summary(self):
        from streamlit.testing.v1 import AppTest
        at=AppTest.from_string('''
import streamlit as st,app
from test_partial_integrity import PartialCoverageTests
if 'results' not in st.session_state:
 r=PartialCoverageTests().statement('2026-04-01','2026-04-30',30000)
 r.update(issues=[],status='reconciled_candidate_review_required',currency=None)
 st.session_state.results=[r];st.session_state.ledger=app.assemble_ledger([r])
app.main()
''').run(timeout=30)
        self.assertFalse(at.exception)
        self.assertTrue(any(c.key=='suspect_foreign_currency' for c in at.tabs[0].checkbox))
        self.assertTrue(any(m.label=='Average monthly true revenue' for m in at.tabs[1].metric))
        self.assertTrue(any(m.label=='Debt payments / true revenue' for m in at.tabs[1].metric))
        self.assertEqual(at.session_state['results'][0]['currency'],'CAD')


if __name__=='__main__':unittest.main()
