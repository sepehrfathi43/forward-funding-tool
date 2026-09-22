import unittest
from funding_engine import funding_limit, term_bounds, estimate_range


class FundingEngineTests(unittest.TestCase):
    def test_cap_and_payment_use_same_rounded_principal(self):
        result = funding_limit(100000, dict(advance=.7, max_burden=.15), 5000, 20000, 0, 6, 1.46)
        self.assertEqual(result['amount'], 70000)
        self.assertAlmostEqual(result['monthly_payment'],70000*1.46/6)
        self.assertEqual(result['binding_constraints'], ['revenue_multiple'])

    def test_invalid_inputs_rejected(self):
        values = dict(revenue=100000, score=dict(advance=.7, max_burden=.15),
                      existing_debt=0, operating_outflows=0, reserve=0, term=6, factor=1.46)
        for name, value in [('revenue', float('nan')), ('term', 0), ('factor', 0),
                            ('existing_debt', -1), ('cap', float('inf')), ('term', 1.5)]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                funding_limit(**{**values, name: value})

    def test_zero_cashflow_and_product_cap(self):
        score = dict(advance=1, max_burden=.2)
        self.assertEqual(funding_limit(100, score, 0, 101, 0, 6, 1.4)['amount'], 100)
        self.assertEqual(funding_limit(100, score, 0, 0, 0, 6, 1.4, 12)['amount'], 12)

    def test_zero_offer_exposes_cashflow_and_burden_constraints(self):
        result=funding_limit(44872.19,dict(advance=.7,max_burden=.15),0,52684.10,0,6,1.46)
        self.assertEqual(result['amount'],31410.53)
        self.assertEqual(result['capacity_breakdown']['cashflow_capacity'],-7811.91)
        self.assertGreater(result['capacity_breakdown']['burden_capacity'],0)

    def test_terms_and_range(self):
        for position,bounds in [(1,(5,8)),(2,(3,6)),(3,(3,5)),(4,(3,4)),(7,(3,4))]:
            self.assertEqual(term_bounds(position),bounds)
            score=dict(advance=.7,max_burden=.15,funding_position=position)
            for term in bounds:
                self.assertEqual(funding_limit(100000,score,90000,200000,0,term,1.46)['amount'],70000)
            for term in [bounds[0]-1,bounds[1]+1]:
                with self.assertRaises(ValueError):funding_limit(100000,score,0,0,0,term,1.46)
        self.assertEqual(estimate_range(70000),dict(low_amount=59500.,median_amount=64750.,high_amount=70000.,recommended_amount=64750.))
        self.assertEqual(estimate_range(0)['median_amount'],0)
