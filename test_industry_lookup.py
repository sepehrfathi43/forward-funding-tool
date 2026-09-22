import unittest,json
from types import SimpleNamespace as NS
from unittest.mock import Mock
import industry_lookup as il
from streamlit.testing.v1 import AppTest

class LookupTests(unittest.TestCase):
 def test_stale_helper_does_not_block_underwriting(self):
  at=AppTest.from_string("""
import app,streamlit as st
from unittest.mock import patch
from test_partial_integrity import PartialCoverageTests
if 'seeded' not in st.session_state:
 r=PartialCoverageTests().statement('2026-04-01','2026-04-30',30000)
 r.update(issues=[],status='reconciled_candidate_review_required',account_holder='Example Restaurant Inc.')
 st.session_state.results=[r];st.session_state.ledger=app.assemble_ledger([r]);st.session_state.seeded=True
 st.session_state.api_key_config='synthetic-test-key'
saved_version=app.industry_lookup.VERSION
del app.industry_lookup.VERSION
try:
 with patch.object(app.industry_lookup,'lookup',side_effect=AssertionError('Stale helper must not run')):
  app.main()
finally:
 app.industry_lookup.VERSION=saved_version
""").run(timeout=30)
  self.assertFalse(at.exception)
  self.assertTrue(any('needs an app restart' in w.value for w in at.warning))
  self.assertTrue(next(b for b in at.button if b.label=='Retry industry web lookup').disabled)
  self.assertIsNone(at.selectbox(key='underwriting_industry').value)
  self.assertTrue(any(b.label=='Calculate conditional estimated range' for b in at.button))
 def test_numbered(self):
  for name in ['1234567 CANADA INC.','CANADA 1234567 INC.','9250-9702 Québec inc.','1234567 Ontario Ltd.','1234567 INC.']:
   self.assertTrue(il.numbered_only(name),name)
   client=Mock();self.assertEqual(il.lookup(name,'test','test',['Manufacturing'],client)['status'],'manual');client.responses.create.assert_not_called()
  for name in ['3M Canada','1234567 Canada Inc. / Acme Recycling','Simcoe Plastics Limited']:
   self.assertTrue(il.eligible_name(name))
 def test_valid_search_and_sources_required(self):
  client=Mock();client.responses.create.return_value=NS(status='completed',output_text=json.dumps(dict(matched_name='Acme Ltd.',confident_match=True,industry='Manufacturing',activity='Makes widgets',reason='Official company website')),output=[NS(type='web_search_call',status='completed'),NS(type='message',content=[NS(annotations=[NS(type='url_citation',url='https://example.com/about',title='About')])])])
  out=il.lookup('Acme Ltd.','test','test',['Manufacturing'],client)
  self.assertEqual(out['status'],'matched');self.assertEqual(len(out['sources']),1)
  self.assertEqual(json.loads(client.responses.create.call_args.kwargs['input']),{'business_name':'Acme Ltd.','public_names':['Acme Ltd.']})
  client.responses.create.return_value.output=[]
  self.assertEqual(il.lookup('Acme Ltd.','test','test',['Manufacturing'],client)['status'],'manual')
 def test_identified_activity_without_scorecard_match_fills_both(self):
  result={'status':'identified_unmapped','industry':None,'industry_label':'Digital publishing and online platforms'}
  ss={};il.apply_result(ss,result)
  self.assertEqual(ss['classification_industry'],result['industry_label'])
  self.assertEqual(ss['underwriting_industry'],result['industry_label'])
  self.assertEqual(il.search_names('SCRIBNIA INC. / SCRIBNIA INC. ARTICLEHUB'),['SCRIBNIA INC.','SCRIBNIA INC. ARTICLEHUB'])
 def test_manual_edits_preserved(self):
  ss={'classification_industry':'Retail','underwriting_industry':None}
  il.apply_result(ss,{'status':'matched','industry':'Manufacturing'})
  self.assertEqual(ss['classification_industry'],'Retail');self.assertEqual(ss['underwriting_industry'],'Manufacturing')
  ss['underwriting_industry']='Construction'
  il.apply_result(ss,{'status':'matched','industry':'Manufacturing'})
  self.assertEqual(ss['underwriting_industry'],'Construction')
 def test_ui_autofill_edit_reset(self):
  at=AppTest.from_string('''
import app,streamlit as st
from unittest.mock import patch
st.session_state.setdefault('api_key_config','synthetic-test-key')
with patch.object(app.industry_lookup,'lookup',return_value={'status':'matched','industry':'8999 - Services, NEC','activity':'Synthetic public evidence','sources':[]}):
 app.main()
''').run(timeout=30)
  at.checkbox(key='auto_case_name').uncheck().run()
  at.text_input(key='case_reference').set_value('Acme Recycling').run()
  self.assertFalse(at.exception)
  self.assertEqual(at.selectbox(key='classification_industry').value,'8999 - Services, NEC')
  self.assertEqual(at.session_state['underwriting_industry'],'8999 - Services, NEC')
  at.selectbox(key='classification_industry').select('Retail').run()
  at.text_input(key='classification_context').set_value('Old case instructions').run()
  at.text_input(key='diagnostic_override_note').set_value('Old reference').run()
  next(b for b in at.button if b.label=='Start new deal / Refresh').click().run()
  self.assertFalse(at.exception)
  for key in ['case_reference','classification_context','diagnostic_override_note']:self.assertEqual(at.text_input(key=key).value,'')
  self.assertEqual(at.selectbox(key='classification_industry').value,'')
  self.assertNotIn('industry_lookup_result',at.session_state)
  self.assertEqual(at.text_input(key='api_key_config').value,'synthetic-test-key')

class UnmappedIndustryUI(unittest.TestCase):
 def test_unmapped_researched_label_is_visible_in_both_tabs(self):
  at=AppTest.from_string("""
import app,streamlit as st
from unittest.mock import patch
from test_partial_integrity import PartialCoverageTests
if 'seeded' not in st.session_state:
 r=PartialCoverageTests().statement('2026-04-01','2026-04-30',30000)
 r.update(issues=[],status='reconciled_candidate_review_required',account_holder='Example Publishing Inc.')
 st.session_state.results=[r];st.session_state.ledger=app.assemble_ledger([r]);st.session_state.seeded=True
 st.session_state.api_key_config='synthetic-test-key'
with patch.object(app.industry_lookup,'lookup',return_value={'status':'identified_unmapped','industry':None,'industry_label':'Digital publishing','activity':'Publishes digital content','sources':[]}):
 app.main()
""").run(timeout=30)
  self.assertFalse(at.exception)
  self.assertEqual(at.selectbox(key='classification_industry').value,'Digital publishing')
  self.assertEqual(at.selectbox(key='underwriting_industry').value,'Digital publishing')
  self.assertIsNone(at.selectbox(key='industry_score_category').value)

class ResetUnderwriting(unittest.TestCase):
 def test_all_previous_deal_inputs_clear(self):
  at=AppTest.from_string("""
import app,streamlit as st
from test_partial_integrity import PartialCoverageTests
if 'seeded' not in st.session_state and not st.session_state.get('deal_epoch'):
 r=PartialCoverageTests().statement('2026-04-01','2026-04-30',30000)
 r.update(issues=[],status='reconciled_candidate_review_required')
 st.session_state.results=[r];st.session_state.ledger=app.assemble_ledger([r]);st.session_state.seeded=True
app.main()
""").run(timeout=30)
  self.assertFalse(at.exception)
  at.selectbox(key='underwriting_industry').select('8999 - Services, NEC')
  at.number_input(key='months_business').set_value(99)
  at.selectbox(key='public_records').select('Clean')
  at.selectbox(key='bank_verification').select('Original PDF')
  next(b for b in at.button if b.label=='Calculate conditional estimated range').click().run()
  at.text_input(key='chat_filter').set_value('Old customer').run()
  next(b for b in at.button if b.label=='Start new deal / Refresh').click().run()
  self.assertFalse(at.exception)
  self.assertNotIn('ledger',at.session_state)
  self.assertEqual(at.session_state['chat_filter'],'')
  for key in ['underwriting_industry','months_business','public_records','bank_verification']:self.assertIsNone(at.session_state[key])

if __name__=='__main__':unittest.main()
