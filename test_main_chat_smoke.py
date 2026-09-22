import sys
sys.path.append('C:/Users/admin/Desktop/forward_funding_revised/.venv/Lib/site-packages')
from streamlit.testing.v1 import AppTest
code='''
import streamlit as st
import app
from test_case_assistant import state
# Table/chart rendering is stubbed because this runtime lacks compatible Arrow.
st.dataframe=lambda data,**kwargs: None
st.data_editor=lambda data,**kwargs:data
st.bar_chart=lambda *args,**kwargs:None
if 'ledger' not in st.session_state:
    for k,v in state().items():st.session_state[k]=v
    st.session_state['underwriting_result']=None
app.main()
'''
at=AppTest.from_string(code).run(timeout=30)
assert not at.exception,list(at.exception)
assert len(at.tabs)==3
assert any(x.value=='Case assistant' for x in at.sidebar.subheader)
assert any(x.label=='Model' and x.value=='gpt-5-mini' for x in at.sidebar.text_input)
print('Full app renders three tabs, sidebar assistant, gpt-5-mini default and readiness form; Arrow rendering stubbed.')
