import sys,unittest
sys.path.append('C:/Users/admin/Desktop/forward_funding_revised/.venv/Lib/site-packages')
from streamlit.testing.v1 import AppTest
code='''
import streamlit as st
import case_assistant as chat
# Test chat controls with JSON standing in for Arrow-backed tables in this runtime.
st.dataframe=lambda data,**kwargs:st.json(data.to_dict(orient='records'))
from test_case_assistant import state,response
if 'ledger' not in st.session_state:
    for k,v in state().items():st.session_state[k]=v
def fake(*args):
    r=response();r['revenue_actions']=[dict(transaction_ids=['c1'],status='True Revenue',reason='Verified settlement')];return r
chat.render_popup(st,st.session_state,'test-key','mock',fake,st.session_state.ledger,{'business':'test'})
'''
at=AppTest.from_string(code).run(timeout=30)
assert not at.exception,list(at.exception)
assert len(at.get('popover'))==1
at.chat_input[0].set_value('Classify Moneris deposits as true revenue').run(timeout=30)
assert not at.exception,list(at.exception)
assert at.session_state['ledger'].iloc[0].revenue_status=='Review Required'
next(b for b in at.button if b.label=='Apply proposed changes').click().run(timeout=30)
assert not at.exception,list(at.exception)
assert at.session_state['ledger'].iloc[0].revenue_status=='True Revenue'
assert len(at.session_state['chat_audit'])==1
print('Chat UI: proposal, approval, case mutation, and audit passed with mocked API.')
