"""Currency-aware reporting and evidence-based matching of internal FX transfers."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import re
import pandas as pd
import business_identity


def match_internal_transfers(frame):
    out = frame.copy()
    if out.empty: return out
    out['internal_transfer'] = False
    out['transfer_match'] = ''
    groups = {}
    for idx, row in out.iterrows():
        match = re.search(r'\bFX\s+TFR\s+C#\s*(\d+)\b', str(row.description), re.I)
        if match and row.get('date'):
            groups.setdefault((row['date'], match.group(1)), []).append(idx)
    for (day, reference), indices in groups.items():
        credits = [i for i in indices if out.at[i, 'tx_type'] == 'credit']
        debits = [i for i in indices if out.at[i, 'tx_type'] == 'debit']
        # Require a unique pair in two identified accounts; ambiguous matches
        # remain untouched. FX legs need not have the same numerical amount.
        if len(credits) != 1 or len(debits) != 1: continue
        c, d = credits[0], debits[0]
        if not out.at[c, 'account_id'] or not out.at[d, 'account_id']: continue
        if out.at[c, 'account_id'] == out.at[d, 'account_id']: continue
        if out.at[c, 'currency'] == out.at[d, 'currency'] and out.at[c, 'amount'] != out.at[d, 'amount']: continue
        for i in (c, d):
            out.at[i, 'internal_transfer'] = True
            out.at[i, 'transfer_match'] = f'{day} FX {reference}'
            out.at[i, 'category'] = 'Non-Revenue - Own-Account / Internal Transfer'
            out.at[i, 'classification_source'] = 'matched_accounts'
            out.at[i, 'classification_reason'] = 'Matching FX reference and date in another uploaded account.'
        out.at[c, 'revenue_status'] = 'Non-Revenue'
        out.at[c, 'reviewed'] = True
    # Vancity prints reciprocal own-account references with a bank prefix 10.
    # Require both legs, equal amounts, same date/currency and unique pairing.
    refs = {}
    for i, row in out.iterrows():
        account = str(row.get('account_id', ''))
        if account.startswith('bmo_business:'):
            m=re.search(r'^Transfer,\s*(\d{4})-(\d{4})-(\d{3})\b',str(row.description),re.I)
            if m:refs[i]='bmo_business:'+m[1]+m[2]+'-'+m[3]
            continue
        if account.startswith('scotia:'):
            m=re.search(r'^TRANSFER\s+(TO|FROM)\s+(\d{5})\s+(\d{5})\s+(\d{2})\b',str(row.description),re.I)
            if m and row.tx_type==('debit' if m[1].upper()=='TO' else 'credit'):refs[i]='scotia:'+m[2]+m[3]+m[4]
            continue
        if not account.startswith('vancity:'): continue
        compact = re.sub(r'\s', '', str(row.description)).upper()
        m = re.search(r'FUNDSTRANSFER-ONLINE(TO|FROM)#(\d+)', compact)
        if m and m[2].startswith('10'):
            expected = 'debit' if m[1] == 'TO' else 'credit'
            if row.tx_type == expected: refs[i] = 'vancity:' + m[2][2:]
    pairs = {}
    for c, target in refs.items():
        if out.at[c, 'tx_type'] != 'credit': continue
        matches = [d for d, back in refs.items() if out.at[d, 'tx_type'] == 'debit'
                   and out.at[d, 'account_id'] == target and back == out.at[c, 'account_id']
                   and target != back and out.at[c, 'date'] == out.at[d, 'date']
                   and out.at[c, 'amount'] == out.at[d, 'amount']
                   and out.at[c, 'currency'] == out.at[d, 'currency']]
        if len(matches) == 1: pairs[c] = matches[0]
    for c, d in pairs.items():
        if list(pairs.values()).count(d) != 1: continue
        if str(out.at[c,'account_id']).startswith(('bmo_business:','scotia:')):
            # A shared case can contain different legal entities. Only match
            # reciprocal transfers within one identified holder and currency.
            ch=out.loc[c].get('account_holder');dh=out.loc[d].get('account_holder')
            currency=out.at[c,'currency']
            if not isinstance(ch,str) or not isinstance(dh,str) or not ch.strip() or business_identity.key(ch)!=business_identity.key(dh):continue
            if not isinstance(currency,str) or currency in ('','Unknown'):continue
        for i in (c, d):
            out.at[i, 'internal_transfer'] = True
            out.at[i, 'transfer_match'] = f'{str(out.at[c,"account_id"]).split(":")[0]} {out.at[c, "date"]} {c}:{d}'
            out.at[i, 'category'] = 'Non-Revenue - Own-Account / Internal Transfer'
            out.at[i, 'classification_source'] = 'matched_accounts'
            out.at[i, 'classification_reason'] = 'Reciprocal uploaded account references, date, currency and amount match.'
        out.at[c, 'revenue_status'] = 'Non-Revenue'
        out.at[c, 'reviewed'] = True
    return out


def currency_totals(frame):
    if frame.empty: return ''
    currencies = frame.get('currency', pd.Series('CAD', index=frame.index)).fillna('Unknown')
    return ' | '.join(f'{code} {amount:,.2f}' for code, amount in frame.groupby(currencies).amount.sum().items())


def reporting_view(frame, results, rates):
    """Create a CAD reporting copy; preserve originals and do not guess rates.

    Rates are constant reporting assumptions, not transaction execution rates.
    No rounding is applied to individual legs, preserving balance equations.
    """
    converted = deepcopy(results)
    out = frame.copy()
    required = {r.get('currency') for r in results if not r.get('exclude_from_ledger')}
    if not out.empty:
        required.update(out.get('currency', pd.Series('CAD', index=out.index)).unique())
    checked = {'CAD': Decimal(1)}
    for code in required:
        if not code or code == 'Unknown': raise ValueError('Verify the statement currency before converting amounts.')
        if code == 'CAD': continue
        try: rate = Decimal(str(rates[code]))
        except (KeyError, ValueError, TypeError, InvalidOperation): raise ValueError(f'A verified CAD reporting rate is required for {code or "unknown currency"}.')
        if not rate.is_finite() or rate <= 0: raise ValueError(f'A positive CAD reporting rate is required for {code}.')
        checked[code] = rate
    if not out.empty:
        if 'currency' not in out: out['currency'] = 'CAD'
        out['original_currency'] = out.currency
        out['original_amount'] = out.amount
        for col in ('amount', 'balance'):
            if col in out:
                out[col] = [float(Decimal(str(v))*checked[c]) if pd.notna(v) else None for v,c in zip(out[col],out.currency)]
        out['currency'] = 'CAD'
    for r in converted:
        if r.get('exclude_from_ledger'): continue
        rate = checked[r.get('currency')]
        r['original_currency'] = r.get('currency')
        r['original_opening_balance'] = r.get('opening_balance')
        r['reporting_rate'] = str(rate)
        r['currency'] = 'CAD'
        for field in ('opening_balance','closing_balance','last_transaction_balance','debits','credits'):
            if r.get(field) is not None: r[field] = str(Decimal(str(r[field]))*rate)
        for t in r.get('transactions', []):
            for field in ('amount','balance'):
                if t.get(field) is not None: t[field] = str(Decimal(str(t[field]))*rate)
        for field in ('debits','credits'):
            if r.get('statement_totals',{}).get(field) is not None:
                r['statement_totals'][field] = str(Decimal(str(r['statement_totals'][field]))*rate)
    return out, converted
