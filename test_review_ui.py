"""Headless Streamlit interaction tests. Skip when Streamlit is not installed."""
import importlib.util
import unittest
from pathlib import Path

HAS_STREAMLIT = importlib.util.find_spec('streamlit') is not None

@unittest.skipUnless(HAS_STREAMLIT, 'Install requirements.txt for Streamlit UI tests')
class ReviewUITests(unittest.TestCase):
    def harness(self):
        from streamlit.testing.v1 import AppTest
        test = AppTest.from_string('''
import streamlit as st
from test_revenue_review import frame
import revenue_tools as revenue
# AppTest does not provide a data_editor edit API. Inject the editor's returned
# frame explicitly rather than mutating Streamlit's private widget state.
native_editor=st.data_editor
def editor(data, **kwargs):
    result=native_editor(data, **kwargs)
    edits=st.session_state.get('_test_editor_edits',{}).get(kwargs.get('key'),{})
    for position, values in edits.items():
        for column,value in values.items():result.at[result.index[position],column]=value
    return result
from unittest.mock import patch
if 'ledger' not in st.session_state:
    st.session_state.ledger=frame()
    st.session_state.revision=1
    st.session_state.case_reference='test case'
with patch.object(st, 'data_editor', side_effect=editor):
    revenue.render_review_tables(st, st.session_state)
''').run(timeout=30)
        self.assertFalse(test.exception)
        return test

    def test_filtered_group_moves_to_classified_and_keeps_debit(self):
        at=self.harness()
        at.text_input(key='pending_filter_1_description').set_value('Acme').run()
        button=next(b for b in at.button if b.label=='Mark all 3 filtered as True Revenue')
        button.click().run()
        self.assertFalse(at.exception)
        ledger=at.session_state['ledger']
        self.assertEqual(ledger.revenue_status.eq('True Revenue').sum(),3)
        self.assertEqual(ledger.loc[3,'revenue_status'],'Not Applicable')
        self.assertEqual(ledger.loc[4,'revenue_status'],'Review Required')

    def test_selected_row_action_only_changes_selected(self):
        at=self.harness()
        at.session_state['_test_editor_edits']={'pending_editor_1_0':{1:{'Selected':True}}}
        next(b for b in at.button if b.label=='Mark selected as True Revenue').click().run()
        self.assertFalse(at.exception)
        ledger=at.session_state['ledger']
        self.assertEqual(ledger.revenue_status.eq('True Revenue').sum(),1)
        self.assertEqual(ledger.at[1,'revenue_status'],'True Revenue')

    def test_individual_dropdown_updates_queue_and_can_be_reopened(self):
        at=self.harness()
        at.session_state['_test_editor_edits']={'pending_editor_1_0':{0:{'revenue_status':'True Revenue'}}}
        next(b for b in at.button if b.label=='Save individual decisions').click().run()
        self.assertFalse(at.exception)
        self.assertEqual(at.session_state['ledger'].at[0,'revenue_status'],'True Revenue')
        at.session_state['_test_editor_edits']={'classified_editor_1_1':{0:{'revenue_status':'Review Required'}}}
        [b for b in at.button if b.label=='Save individual decisions'][-1].click().run()
        self.assertFalse(at.exception)
        self.assertEqual(at.session_state['ledger'].at[0,'revenue_status'],'Review Required')

    def test_full_application_starts(self):
        from streamlit.testing.v1 import AppTest
        at=AppTest.from_file(str(Path(__file__).with_name('app.py'))).run(timeout=30)
        self.assertFalse(at.exception)
        self.assertEqual([tab.label for tab in at.tabs],['Document Analyzer','Bank Summary','Underwriting Model','Diagnostics'])

    def test_complete_history_populates_model_before_debt_verification(self):
        from streamlit.testing.v1 import AppTest
        at=AppTest.from_string('''
import calendar
import streamlit as st
import app as app
if 'results' not in st.session_state:
    results=[]
    opening=100.
    for month in [5,6,7]:
        period=f'2026-{month:02}'
        rows=[dict(id=period+'c',date=period+'-01',month=period,page=1,
                   description='STRIPE PAYOUT',amount='20000.00',tx_type='credit',balance=str(opening+20000))]
        balance=opening+20000
        for day in range(2,8):
            for amount in [174,192]:
                balance-=amount
                rows.append(dict(id=f'{period}-{day}-{amount}',date=f'{period}-{day:02}',month=period,page=1,
                    description='BIZFUND',amount=str(amount),tx_type='debit',balance=str(balance)))
        results.append(dict(source_file=period+'.csv',account_id='A',currency='CAD',
            period_start=period+'-01',period_end=f'{period}-{calendar.monthrange(2026,month)[1]}',
            opening_balance=str(opening),closing_balance=str(balance),transactions=rows,issues=[],
            status='reconciled_candidate_review_required'))
        opening=balance
    st.session_state.results=results
    st.session_state.ledger=app.assemble_ledger(results)
app.main()
''').run(timeout=30)
        self.assertFalse(at.exception)
        metrics={m.label:m.value for m in at.metric}
        self.assertEqual(metrics['Average monthly reviewed revenue'],'$20,000.00')
        self.assertNotEqual(metrics['Average daily balance'],'Unavailable')
        self.assertEqual(metrics['Verified monthly debt payments'],'Awaiting verification')
        self.assertEqual(metrics['Suggested monthly debt payments'],'$7,686.00')
        self.assertEqual(len(at.session_state['debts']),2)

if __name__=='__main__':unittest.main()
