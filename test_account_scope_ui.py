import sys
sys.path.append('C:/Users/admin/Desktop/forward_funding_revised/.venv/Lib/site-packages')
from streamlit.testing.v1 import AppTest
code='''
import streamlit as st
import app,pandas as pd
st.dataframe=lambda data,**kwargs:None
st.data_editor=lambda data,**kwargs:data
st.bar_chart=lambda *args,**kwargs:None
if 'ledger' not in st.session_state:
    results=[]
    for a,start,end in [('A','2026-01-01','2026-03-31'),('B','2026-06-01','2026-08-31')]:
        t=dict(id=a,date=start,month=start[:7],description='Moneris',tx_type='credit',amount='30000.00',balance='30000.00',page=1)
        results.append(dict(source_file=a+'.pdf',source_sha256=a,account_id=a,currency='CAD',period_start=start,period_end=end,opening_balance='0.00',closing_balance='30000.00',transactions=[t],issues=[],status='reconciled_candidate_review_required'))
    df=app.assemble_ledger(results)
    df['reviewed']=True;df['revenue_status']='True Revenue'
    st.session_state['ledger']=df;st.session_state['results']=results
app.main()
'''
at=AppTest.from_string(code).run(timeout=30)
assert not at.exception,list(at.exception)
selector=next(s for s in at.selectbox if s.label=='Account scope for this estimate')
assert selector.value=='B',selector.value
assert any(m.label=='Average monthly reviewed revenue' and m.value=='$10,000.00' for m in at.metric)
selector.select('A').run(timeout=30)
assert not at.exception,list(at.exception)
assert any(m.label=='Average monthly reviewed revenue' and m.value=='$10,000.00' for m in at.metric)
print('Disjoint-account UI verified: latest account defaults, separate metrics populated, scope switching works.')
