"""Deterministic policy capacity calculation shared by future API and UI."""
from decimal import Decimal, ROUND_FLOOR

POLICY_VERSION = 'revenue-position-2026-09-v3'


def term_bounds(position):
    if isinstance(position,bool) or not isinstance(position,int) or position<1:
        raise ValueError('Funding position must be a positive whole number')
    return (5,8) if position==1 else (3,6) if position==2 else (3,5) if position==3 else (3,4)


def estimate_range(upper, reduction=15):
    upper=Decimal(str(upper)); reduction=Decimal(str(reduction))
    if not upper.is_finite() or upper<0 or not reduction.is_finite() or not 0<=reduction<=100:
        raise ValueError('Invalid estimate range')
    high=upper.quantize(Decimal('.01'),rounding=ROUND_FLOOR)
    low=(high*(1-reduction/100)).quantize(Decimal('.01'),rounding=ROUND_FLOOR)
    median=((low+high)/2).quantize(Decimal('.01'),rounding=ROUND_FLOOR)
    return dict(low_amount=float(low),median_amount=float(median),high_amount=float(high),recommended_amount=float(median))


def funding_limit(revenue, score, existing_debt, operating_outflows, reserve, term, factor, cap=None):
    def number(value, name):
        try:
            result = Decimal(str(value))
        except Exception as exc:
            raise ValueError(f'{name} must be a finite nonnegative number') from exc
        if isinstance(value, bool) or not result.is_finite() or result < 0:
            raise ValueError(f'{name} must be a finite nonnegative number')
        return result
    revenue = number(revenue, 'revenue')
    debt = number(existing_debt, 'existing_debt')
    expenses = number(operating_outflows, 'operating_outflows')
    reserve = number(reserve, 'reserve')
    term = number(term, 'term')
    factor = number(factor, 'factor')
    if term <= 0 or term != term.to_integral_value() or factor < 1:
        raise ValueError('term must be a positive whole month count and factor must be at least one')
    position=score.get('funding_position',1)
    minimum,maximum=term_bounds(position)
    if not minimum<=term<=maximum:
        raise ValueError(f'Position {position} requires a term of {minimum}–{maximum} months')
    multiple = number(score['advance'], 'advance')
    burden = number(score['max_burden'], 'max_burden')
    if burden > 1:
        raise ValueError('max_burden must be between zero and one')
    burden_capacity = revenue * burden - debt
    cashflow_capacity = revenue - expenses - debt - reserve
    available = max(Decimal(0), min(burden_capacity, cashflow_capacity))
    # Cash flow and burden remain review diagnostics, not principal caps.
    limits = {'revenue_multiple': revenue * multiple}
    if cap is not None:
        limits['product_cap'] = number(cap, 'cap')
    amount = min(limits.values()).quantize(Decimal('.01'), rounding=ROUND_FLOOR)
    return dict(amount=float(amount), monthly_capacity=float(available),
                funding_position=position,term_months=int(term),term_minimum=minimum,term_maximum=maximum,
                estimation_basis='average_true_monthly_revenue',
                capacity_breakdown={'monthly_revenue':float(revenue),'operating_outflows':float(expenses),
                    'existing_debt':float(debt),'reserve':float(reserve),
                    'cashflow_capacity':float(cashflow_capacity),'burden_capacity':float(burden_capacity)},
                monthly_payment=float(amount * factor / term), policy_version=POLICY_VERSION,
                binding_constraints=[k for k, v in limits.items() if v == min(limits.values())],
                limits={k: str(v.quantize(Decimal('.01'), rounding=ROUND_FLOOR)) for k, v in limits.items()})
