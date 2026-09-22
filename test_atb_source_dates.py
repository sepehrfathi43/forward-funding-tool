"""Independent ATB source-date regression; private PDFs are not bundled."""
import os,re,unittest
from pathlib import Path
from decimal import Decimal
from datetime import datetime
import pdfplumber
import app
from servus_parser import CURRENCY_ISSUE

NAMES=['hwLj3HszfTE67GmwG8t5','qYwo1GragEhegT3QZEML','qlsE0jU6l7yA1nIb8bzA','pNVPJQLu1rslyGjqEW4S','D06S1Luxt8OLhwqTQ8gE','viB08AzNxxWAprTgIifY']
class ATBDateTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('FF_STATEMENT_FIXTURES'),'Set FF_STATEMENT_FIXTURES for private source tests')
    def test_all_source_rows(self):
        count=0
        for name in NAMES:
            with self.subTest(file=name):
                p=Path(os.environ['FF_STATEMENT_FIXTURES'])/(name+'.pdf')
                root=app.extract_native(p.read_bytes(),p.name)
                self.assertTrue(root['exclude_from_ledger']);self.assertFalse(root['issues'])
                r=root['account_statements'][0]
                self.assertEqual(r['issues'],[CURRENCY_ISSUE])
                expected=[]
                with pdfplumber.open(p) as doc:
                    for pn,page in enumerate(doc.pages,1):
                        for line in (page.extract_text() or '').splitlines():
                            m=re.match(r'([A-Z][a-z]{2})(\d{1,2}) (.*?) \$([\d,]+\.\d{2}) (-?[\d,]+\.\d{2})$',line)
                            if m:
                                expected.append((datetime.strptime(m[1]+m[2]+'2026','%b%d%Y').date().isoformat(),Decimal(m[4].replace(',','')),Decimal(m[5].replace(',','')),pn))
                actual=[(t['date'],Decimal(t['amount']),Decimal(t['balance']),t['page']) for t in r['transactions']]
                self.assertEqual(actual,expected)
                self.assertEqual(r['source_date_checks'],{'verified':len(actual),'unverified':0,'mismatches':0})
                count+=len(actual)
        self.assertEqual(count,262)

if __name__=='__main__':unittest.main()
