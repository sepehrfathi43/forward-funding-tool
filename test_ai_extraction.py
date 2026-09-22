import base64
from copy import deepcopy
import io
import json
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from pypdf import PdfReader,PdfWriter
import ai_extraction as ai
import app


def raw():
    value={k:None for k in app.AI_STATEMENT_SCHEMA['json_schema']['schema']['required']}
    value['transactions']=[]
    return value


class AIExtractionTests(unittest.TestCase):
    def test_parallel_pages_preserve_order_continue_after_failure_and_resume(self):
        cache={};calls=[];barrier=threading.Barrier(2)
        def fetch(n):
            calls.append(n)
            if n<=2:barrier.wait(timeout=2)
            if n==2:raise TimeoutError()
            return {'transactions':[{'description':str(n)}]}
        pages,errors=ai.run_parallel(4,fetch,cache,'case')
        self.assertEqual([n for n,_ in pages],[1,3,4])
        self.assertEqual([e['page'] for e in errors],[2])
        calls=[]
        pages,errors=ai.run_parallel(4,lambda n:(calls.append(n) or raw()),cache,'case')
        self.assertEqual(calls,[2]);self.assertFalse(errors)
        self.assertEqual([n for n,_ in pages],[1,2,3,4])

    def test_auth_failure_stops_unvisited_pages_and_does_not_cache(self):
        class Auth(Exception):status_code=401
        def fail(n):raise Auth('secret must not appear')
        cache={};pages,errors=ai.run_parallel(10,fail,cache,'case')
        self.assertFalse(cache);self.assertFalse(pages)
        self.assertEqual(len(errors),10)
        self.assertNotIn('secret',str(errors))

    def test_pdf_packages_supply_first_previous_and_target(self):
        w=PdfWriter()
        for _ in range(4):w.add_blank_page(width=612,height=792)
        stream=io.BytesIO();w.write(stream)
        packs=ai.page_payloads(stream.getvalue())
        self.assertEqual(packs[3][0],[0,2,3])
        self.assertEqual(len(PdfReader(io.BytesIO(base64.b64decode(packs[3][1]))).pages),3)

    def test_strict_responses_pdf_contract_and_incomplete_output(self):
        client=Mock();client.responses.create.return_value=SimpleNamespace(status='completed',output=[],output_text=json.dumps(raw()))
        content=[{'type':'input_file','filename':'p.pdf','file_data':'data:application/pdf;base64,abc','detail':'high'}]
        self.assertEqual(ai.response_json(client,'gpt-6-astra',content,app.AI_STATEMENT_SCHEMA),raw())
        request=client.responses.create.call_args.kwargs
        self.assertFalse(request['store']);self.assertEqual(request['reasoning'],{'effort':'low'})
        self.assertTrue(request['text']['format']['strict'])
        client.responses.create.return_value=SimpleNamespace(status='incomplete',incomplete_details=SimpleNamespace(reason='max_output_tokens'))
        with self.assertRaisesRegex(ValueError,'output limit'):ai.response_json(client,'gpt-6-astra',content,app.AI_STATEMENT_SCHEMA)

    def test_invalid_rows_are_not_validated(self):
        value=raw();value['transactions']=[dict(description='bad',debit=10,credit=10)]
        with self.assertRaises(ValueError):ai.validate_page(value,app.AI_STATEMENT_SCHEMA)

    def test_output_truncation_retries_once_and_only_caches_complete_page(self):
        writer=PdfWriter();writer.add_blank_page(width=612,height=792)
        stream=io.BytesIO();writer.write(stream)
        client=Mock();client.responses.create.side_effect=[
            SimpleNamespace(status='incomplete',incomplete_details=SimpleNamespace(reason='max_output_tokens')),
            SimpleNamespace(status='completed',output=[],output_text=json.dumps(raw()))]
        cache={}
        pages,errors,key,timing=ai.extract_pages(stream.getvalue(),'gpt-6-astra','unused',app.AI_STATEMENT_SCHEMA,cache,client=client)
        self.assertFalse(errors);self.assertEqual(len(pages),1);self.assertEqual(len(cache),1)
        self.assertEqual([c.kwargs['max_output_tokens'] for c in client.responses.create.call_args_list],[16000,30000])
        client.responses.create.reset_mock()
        ai.extract_pages(stream.getvalue(),'gpt-6-astra','unused',app.AI_STATEMENT_SCHEMA,cache,client=client)
        client.responses.create.assert_not_called()

    def test_native_reconciliation_failure_triggers_recovery_currency_does_not(self):
        result=dict(adapter='rbc',transactions=[{}],issues=['Currency not printed explicitly; verify CAD before underwriting.'])
        self.assertFalse(ai.needs_fallback(result))
        result['issues'].append('Printed debit total does not match extracted rows')
        self.assertTrue(ai.needs_fallback(result))
        self.assertFalse(ai.needs_fallback({'account_statements':[result]}))

    def test_cache_isolation_invalidation_and_bound(self):
        cache={};build=Mock(return_value={'issues':[]})
        first,hit=ai.memoized(cache,'a',build,2);first['issues'].append('manual')
        second,hit=ai.memoized(cache,'a',build,2)
        self.assertTrue(hit);self.assertEqual(second['issues'],[]);self.assertEqual(build.call_count,1)
        ai.memoized(cache,'changed',build,2);ai.memoized(cache,'third',build,2)
        self.assertEqual(len(cache),2);self.assertNotIn('a',cache)

    def test_single_native_reader_preserves_results(self):
        from unittest.mock import patch
        from contextlib import contextmanager
        from pdf_access import open_pdf
        writer=PdfWriter();writer.add_blank_page(width=612,height=792)
        stream=io.BytesIO();writer.write(stream)
        calls=[]
        @contextmanager
        def opened(data):
            calls.append(1)
            with open_pdf(data) as doc:yield doc
        with patch('app.open_pdf',opened):result=app.extract_native(stream.getvalue(),'blank.pdf')
        self.assertEqual(len(calls),1)
        self.assertFalse(result['transactions'])
        self.assertTrue(result['issues'])


if __name__=='__main__':unittest.main()
