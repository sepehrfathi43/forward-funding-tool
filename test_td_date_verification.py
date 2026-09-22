import sys, unittest
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
import app
from pathlib import Path

class TDDateVerificationTests(unittest.TestCase):
    def test_readable_td_files_have_verified_dates(self):
        files=["UfI5jdojNTZDuy5zE0T1.pdf","M9f4oT8aptwZ7cJJXhwz.pdf","jAs3ZkQICUfPzKtx6ssS.pdf","cyTiKdWLGjZUA9FcJCKl.pdf","lrTMYN2MrZ4eQwteV7YF.pdf"]
        root=Path("C:/Users/admin/Downloads")
        for name in files:
            with self.subTest(name=name):
                result=app.extract_native((root/name).read_bytes(),name)
                self.assertEqual(result["adapter"],"td_business")
                self.assertEqual(result["account_statements"] if "account_statements" in result else [],[])
                self.assertEqual(result.get("source_date_checks",{}).get("unverified",0),0)
                self.assertEqual(result.get("source_date_checks",{}).get("mismatches",0),0)

if __name__=="__main__": unittest.main()
