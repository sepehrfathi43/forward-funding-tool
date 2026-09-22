import unittest,json
import pandas as pd
from unittest.mock import Mock
import app,revenue_tools as rev
from streamlit.testing.v1 import AppTest

class Changes(unittest.TestCase):
 def test_cashflow_scale(self):
  for margin,points in [(-11,0),(-10,1),(-5,2),(-.01,2),(0,4),(3,5),(5,6),(10,7)]:
   self.assertEqual(app.cashflow_points(100,100-margin,0)['points'],points)
  self.assertEqual(app.cashflow_points(100,None,0)['points'],0)
 def test_context_and_exclusions(self):
  rows=[]
  for i,(desc,kind,internal) in enumerate([('E-TRANSFER ***ABC','credit',False),('E-TRANSFER loan','credit',False),('E-TRANSFER refund','credit',False),('E-TRANSFER ***XYZ','credit',True),('SEND E-TFR','debit',False),('ACCT BAL REBATE','credit',False)]):
   rows.append(dict(id=str(i),account_id='a',description=desc,tx_type=kind,amount=100,revenue_status='Review Required',reviewed=False,category=rev.UNKNOWN,internal_transfer=internal))
  result=rev.apply_business_context(pd.DataFrame(rows),'Plastic recycling','Manufacturing',True)
  self.assertEqual(result.iloc[0].revenue_status,'True Revenue')
  for i in [1,2,5]:self.assertEqual(result.iloc[i].revenue_status,'Non-Revenue')
  for i in [3,4]:self.assertNotEqual(result.iloc[i].revenue_status,'True Revenue')
  self.assertEqual(rev.apply_business_context(result,include_etransfers=False).iloc[0].revenue_status,'Review Required')
 def test_ai_context_payload(self):
  df=pd.DataFrame([dict(id='a',account_id='a',description='Acme Manufacturing AP',tx_type='credit',amount=123,currency='CAD',date='2026-01-01',revenue_status='Review Required',reviewed=False,category=rev.UNKNOWN)])
  calls=[]
  def ai(key,model,prompt,payload,schema):
   body=json.loads(payload);calls.append(body)
   return {'decisions':[dict(group_id=body['deposits'][0]['group_id'],decision='True Revenue',confidence=.98,evidence='contextual_customer_receipt',reason='Named B2B receipt consistent with manufacturing.') ]}
  cache={}
  out=rev.classify_ai(df,'synthetic','test',ai,cache,'Recycling','Manufacturing')
  self.assertEqual(out.iloc[0].revenue_status,'True Revenue')
  self.assertEqual(calls[0]['industry'],'Manufacturing')
  rev.classify_ai(df,'synthetic','test',ai,cache,'Recycling','Retail')
  self.assertEqual(len(calls),2)
 def test_reset_button(self):
  at=AppTest.from_file('app.py').run(timeout=30)
  self.assertFalse(at.exception)
  self.assertIn('Diagnostics',[t.label for t in at.tabs])
  at.text_input(key='api_key_config').set_value('synthetic-test-key').run()
  at.session_state['payer_rules']={'old':'value'}
  at.session_state['diagnostic_override']={'signature':'old'}
  at.session_state['chat_messages']=[{'role':'user','content':'old'}]
  next(b for b in at.button if b.label=='Start new deal / Refresh').click().run(timeout=30)
  self.assertFalse(at.exception)
  self.assertEqual(at.text_input(key='api_key_config').value,'synthetic-test-key')
  self.assertEqual(at.session_state['deal_epoch'],1)
  self.assertEqual(at.session_state['payer_rules'],{})
  self.assertNotIn('diagnostic_override',at.session_state)

class OverrideUI(unittest.TestCase):
 def test_override_memo_and_expiry(self):
  at=AppTest.from_string("""
import streamlit as st
import app
from test_partial_integrity import PartialCoverageTests
if 'initialized' not in st.session_state:
 r=PartialCoverageTests().statement('2026-04-01','2026-04-30',30000)
 r.update(issues=['Synthetic reconciliation warning'],status='review_required')
 st.session_state.results=[r]
 st.session_state.ledger=app.assemble_ledger([r])
 st.session_state.initialized=True
app.main()
""").run(timeout=40)
  self.assertFalse(at.exception)
  self.assertTrue(any('Synthetic reconciliation warning' in x.value for x in at.info))
  next(b for b in at.button if b.label=='Override all diagnostic review flags').click().run(timeout=40)
  self.assertFalse(at.exception)
  self.assertFalse(any('Outstanding review: Synthetic' in x.value for x in at.info))
  for select in at.selectbox:
   if select.label=='Industry':select.select('8011 - Offices & Clinics of Doctors of Medicine')
   if select.label=='Public records':select.select('Clean')
   if select.label=='Bank verification':select.select('Original PDF')
  next(n for n in at.number_input if n.label=='Time in business (months)').set_value(100)
  next(c for c in at.checkbox if c.label.startswith('This is one business')).check()
  next(b for b in at.button if b.label=='Calculate conditional estimated range').click().run(timeout=40)
  self.assertFalse(at.exception)
  self.assertIn('underwriting_result',at.session_state,[(x.type,getattr(x,'value',None)) for name in ('info','error','markdown','warning') for x in getattr(at,name)])
  memo=at.session_state['underwriting_result']
  self.assertTrue(memo['diagnostic_override'])
  self.assertEqual(memo['score']['score'],memo['score']['raw'])
  at.session_state['results'][0]['issues'].append('New evidence')
  at.run(timeout=40)
  self.assertTrue(any('previous override is no longer active' in x.value for x in at.info))
  self.assertFalse(any(x.label=='Calculated program maximum advance' for x in at.metric))

if __name__=='__main__':unittest.main()
