"""Observed MCA advances and repayment estimates, never automatic discharge evidence."""
from decimal import Decimal, ROUND_HALF_UP
import re
import pandas as pd
import debt_review

FACTOR = Decimal('1.46')


def money(value):
    return Decimal(str(value)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)


def funding_table(frame, lender_match):
    if frame.empty:
        return pd.DataFrame()
    groups = {}
    returns = []
    for row in frame.to_dict('records'):
        text = debt_review.normalized_description(row.get('description', ''))
        compact = re.sub(r'[^A-Z0-9]', '', text)
        row = dict(row, date=pd.Timestamp(row['date']).date().isoformat())
        if row['tx_type'] == 'credit' and re.search(r'RETURN|REVERS|REFUND|RETOUR|REJET', compact):
            returns.append(row)
            continue
        match = (debt_review.source_match(row, lender_match) if row['tx_type'] == 'debit'
                 else lender_match(row.get('description', '')))
        if not match or match[0] not in ('Premium', 'Standard'):
            continue
        key = (str(row.get('account_id', '')), str(row.get('currency', 'Unknown')), match[1])
        group = groups.setdefault(key, {'credit': [], 'debit': []})
        group[row['tx_type']].append(row)
    output = []
    for (account, currency, lender), group in groups.items():
        advances = sorted(group['credit'], key=lambda r: r['date'])
        payments = group['debit']
        # A generic returned cheque can invalidate an apparent lender payment,
        # but cannot identify which contract. Surface uncertainty, never count
        # a possibly returned debit as proof of completed repayment.
        possible_returns = [r for r in returns if str(r.get('account_id','')) == account
            and str(r.get('currency','Unknown')) == currency
            and any(money(r['amount']) == money(p['amount'])
                    and 0 <= (pd.Timestamp(r['date'])-pd.Timestamp(p['date'])).days <= 7 for p in payments)]
        for advance in advances or [None]:
            eligible = [p for p in payments if advance is None or p['date'] >= advance['date']]
            ambiguous = len(advances) > 1 or bool(possible_returns) or currency == 'Unknown'
            total = sum((money(p['amount']) for p in eligible), Decimal('0'))
            principal = money(advance['amount']) if advance else None
            target = money(principal * FACTOR) if principal is not None else None
            remaining = max(Decimal('0'), target-total) if target is not None and not ambiguous else None
            if advance is None:
                status = 'Unknown — funding deposit not supplied'
            elif ambiguous:
                status = 'Unknown — contract / returned-payment review required'
            elif total >= target:
                status = 'Expected completed — verify with lender'
            else:
                status = 'Not demonstrated complete in supplied statements'
            output.append({'Lender':lender, 'Account':account, 'Currency':currency,
                'Funding date':advance['date'] if advance else None,
                'Funding amount':float(principal) if principal is not None else None,
                'Factor':float(FACTOR), 'Estimated total repayment':float(target) if target is not None else None,
                'Observed payment debits':float(total), 'Payment count':len(eligible),
                'Estimated remaining':float(remaining) if remaining is not None else None,
                'Last payment':max((p['date'] for p in eligible), default=None),
                'Completion estimate':status,
                'Review note':('Multiple advances: payments are lender totals, not allocated to each advance. ' if len(advances)>1 else '')
                    + ('Potential returned payments: debit totals may overstate completed payments. ' if possible_returns else '')
                    + '1.46 applied to deposited amount; fees, prior advances, refinancing and omitted statements can change the result.',
                'Funding source':advance.get('source_file','') if advance else '',
                'Funding transaction':str(advance.get('id','')) if advance else '',
                'Payment transactions':', '.join(str(p.get('id','')) for p in eligible)})
    return pd.DataFrame(output)


def render(st, frame, lender_match):
    st.subheader('MCA cash injections and estimated repayment')
    table = funding_table(frame, lender_match)
    st.caption('Estimated repayment = funding deposit × 1.46. Only observed payments are counted. These estimates do not automatically close verified debt positions; missing deposits or ambiguous contracts remain unknown.')
    if table.empty:
        st.info('No recognized MCA funding deposits or payments found in the supplied statements.')
    else:
        st.dataframe(table.drop(columns=['Funding transaction','Payment transactions']), hide_index=True, width='stretch')
        st.download_button('Download MCA funding and repayment evidence',table.to_csv(index=False),'mca_funding_review.csv','text/csv')
