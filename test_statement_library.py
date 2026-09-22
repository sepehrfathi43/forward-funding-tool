"""Opt-in private statement regression library. No bank PDFs ship in the ZIP."""
import os,json,hashlib,unittest
from pathlib import Path
import app

class StatementRegressionTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('FF_STATEMENT_FIXTURES'),'Set FF_STATEMENT_FIXTURES to your source PDF directory')
    def test_known_statements(self):
        root=Path(os.environ['FF_STATEMENT_FIXTURES'])
        manifest=json.loads(Path(__file__).with_name('statement_regression_manifest.json').read_text())
        for expected in manifest:
            with self.subTest(file=expected['filename']):
                data=(root/expected['filename']).read_bytes()
                self.assertEqual(hashlib.sha256(data).hexdigest(),expected['sha256'])
                r=app.extract_native(data,expected['filename'])
                self.assertEqual(r['adapter'],expected['adapter'])
                self.assertEqual(len(r['transactions']),expected['rows'])
                for key in ['debits','credits','opening_balance','closing_balance']:self.assertEqual(r[key],expected[key])
                issues=r['issues']
                self.assertEqual(len(issues),len(expected['expected_issue_prefixes']))
                for issue,prefix in zip(issues,expected['expected_issue_prefixes']):self.assertTrue(issue.startswith(prefix))

if __name__=='__main__':unittest.main()
