import unittest
from unittest.mock import patch,MagicMock
import app
import credit_inputs
from streamlit.testing.v1 import AppTest


class CreditInputTests(unittest.TestCase):
    def test_explicit_score_only_and_ambiguity(self):
        for text,expected in [('FICO Score 8 673',673),('FICO Score 8\n673',673),
                              ('FICO Score 8 673 FICO Score 8 688',None),('Account balance 673',None),('FICO Score 8 999',None)]:
            document=MagicMock();document.__enter__.return_value.pages=[MagicMock()]
            document.__enter__.return_value.pages[0].extract_text.return_value=text
            with patch.object(credit_inputs,'open_pdf',return_value=document):
                self.assertEqual(credit_inputs.extract_score(b'fixture'),expected)

    def test_reallocated_points_and_balance_independence(self):
        m=dict(avg=105358.55,trend=-5.857,volatility=13.277,count=45.33,burden=0,concentration=61.73)
        p=dict(adb=-48433.75,negative=184,positions=0,velocity='0 in 90 Days',missed=0,months=600,
               industry='5812 - Eating Places / Restaurants',credit=673,records='Clean',verification='Original PDF')
        result=app.scorecard(m,p)
        self.assertEqual(result['raw'],72)
        self.assertEqual(result['grade'],'B')
        self.assertEqual(result['points']['Revenue'],14)
        p.update(adb=100000,negative=0)
        self.assertEqual(app.scorecard(m,p),result)
        self.assertNotIn('Average daily balance',result['points'])
        self.assertNotIn('Negative days',result['points'])

    def test_autofill_unverified_manual_and_report_replacement(self):
        at=AppTest.from_string('''
import streamlit as st
import credit_inputs
if 'credit_reports' not in st.session_state:
    st.session_state.credit_reports={'applicant':{'profile':{'fico_score':673},'source_sha256':'first','verified':False},'co_applicant':{'profile':{'fico_score':800}}}
if st.button('Replace report'):
    st.session_state.credit_reports['applicant']={'profile':{'fico_score':710},'source_sha256':'second','verified':False}
if st.button('Remove report'):
    st.session_state.credit_reports.pop('applicant',None)
credit_inputs.render_score(st,st.session_state,'case')
''').run()
        self.assertFalse(at.exception)
        self.assertEqual(at.number_input[0].value,673)
        at.number_input[0].set_value(690).run()
        self.assertEqual(at.session_state['underwriting_credit_input']['source'],'manual entry on Underwriting Model')
        at.run();self.assertEqual(at.number_input[0].value,690)
        at.button[0].click().run();self.assertEqual(at.number_input[0].value,710)
        at.button[1].click().run();self.assertIsNone(at.number_input[0].value)
        self.assertFalse(at.exception)

    def test_third_tab_score_reaches_decision_memo(self):
        at=AppTest.from_string('''
import streamlit as st
import app
from test_gap_offers import GapOfferTests
if 'results' not in st.session_state:
    result=GapOfferTests().statement('2026-03',100000)
    result.update(issues=[],status='reconciled_candidate_review_required')
    st.session_state.results=[result]
    st.session_state.ledger=app.assemble_ledger([result])
app.main()
''').run(timeout=45)
        self.assertFalse(at.exception)
        next(n for n in at.tabs[2].number_input if n.label=='Applicant credit score').set_value(673).run()
        for s in at.selectbox:
            if s.label=='Industry':s.select('5812 - Eating Places / Restaurants')
            if s.label=='Public records':s.select('Clean')
            if s.label=='Bank verification':s.select('Original PDF')
        next(n for n in at.number_input if n.label=='Time in business (months)').set_value(120)
        for c in at.checkbox:
            if c.label.startswith(('I compared statement','This is one business','I understand the partial')):c.check()
        next(b for b in at.button if b.label=='Calculate conditional estimated range').click().run(timeout=45)
        self.assertFalse(at.exception)
        memo=at.session_state['underwriting_result']
        self.assertEqual(memo['verified_inputs']['credit'],673)
        self.assertEqual(memo['score']['points']['Credit score'],4)
        self.assertEqual(memo['credit_score_input']['source'],'manual entry on Underwriting Model')
        next(n for n in at.number_input if n.label=='Applicant credit score').set_value(700).run()
        self.assertNotIn('underwriting_result',at.session_state)


if __name__=='__main__':unittest.main()
