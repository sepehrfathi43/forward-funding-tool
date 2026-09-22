import unittest
from unittest.mock import patch
from rbc_french_parser import parse_rbc_french
import app as app


class FrenchLedgerTests(unittest.TestCase):
    def test_missing_dates_never_make_cross_file_duplicates(self):
        results=[]
        for name in ['a','b']:
            results.append(dict(source_file=name,source_sha256=name,account_id='A',transactions=[dict(
                id=name,date=None,month=None,description='BMW payment',tx_type='debit',amount='1201.44',balance=None)]))
        frame=app.assemble_ledger(results)
        self.assertEqual(len(frame),2)
        self.assertEqual(frame.attrs['duplicate_rows_removed'],[])

    def test_french_columns_dates_and_opening_year(self):
        class Page:
            height=792; width=612
            def extract_text(self,**kwargs):
                return "Du 21 janvier 2026 au 21 février 2026\nVotre numéro de compte : 00697-5086541\nVotre solde d'ouverture le 21 janvier 2026 2 353,93 $\nTotal des dépôts dans votre compte + 110,00\nTotal des retraits de votre compte - 80,00\nVotre solde de clôture le 21 février 2026 = 2 383,93 $"
        class Doc:pages=[Page()]
        def word(text,x):return dict(text=text,x0=x,upright=True)
        lines=[(100,[word('Date',45),word('Description',90),word('Retraits',336),word('Dépôts',431),word('Solde',563)]),
            (120,[word('23',45),word('janv',60),word('Virement reçu',90),word('110,00',439),word('2 463,93',550)]),
            (140,[word('Virement envoyé',90),word('80,00',352),word('2 383,93',550)]),
            (160,[word('Solde de clôture',90),word('2 383,93',550)])]
        with patch('rbc_french_parser._word_lines',return_value=lines):
            result=parse_rbc_french(b'test','test.pdf',Doc())
        self.assertEqual(result['opening_balance'],'2353.93')
        self.assertEqual([t['date'] for t in result['transactions']],['2026-01-23']*2)
        self.assertEqual([t['tx_type'] for t in result['transactions']],['credit','debit'])
        self.assertFalse(result['issues'])
