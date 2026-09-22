"""NSF evidence across all supplied dates, including partial statement months."""
import re
import pandas as pd


def nsf_summary(frame):
    result={'returned_items':0,'affected_dates':0,'returned_amount':0.0,'fee_amount':0.0,
            'fee_disclosed_items':0,'fee_rows':0,'paid_item_fee_rows':0,'paid_item_fee_amount':0.0,
            'period_start':None,'period_end':None,'monthly':[],
            'unspecified_return_items':0,'associated_service_charges':0.0}
    if frame.empty:return result
    dates=pd.to_datetime(frame['date'],errors='coerce')
    valid=dates.notna()
    if valid.any():
        result['period_start']=dates[valid].min().date().isoformat()
        result['period_end']=dates[valid].max().date().isoformat()
    text=frame.description.fillna('').astype(str).str.upper()
    compact=text.str.replace(r'[^A-Z0-9]','',regex=True)
    # Match returned transactions, not fees, bank notices or ordinary transfers.
    returned=frame.tx_type.eq('credit') & compact.str.contains(r'(?:RETURNEDNSF|NSFRETURN|INSUFFICIENTFUNDS|RETOURNE?NSF)',regex=True)
    unspecified=frame.tx_type.eq('credit') & compact.eq('RETURNEDITEMCREDIT') & ~returned
    returned=returned | unspecified
    paid=frame.tx_type.eq('debit') & compact.isin(['NSFPAIDFEE','PAYMENTCOVERAGEFEE'])
    fees=frame.tx_type.eq('debit') & ~paid & text.str.contains(r'\bNSF\b|\b(?:NON[ -]*SUFFICIENT|INSUFFICIENT)\s+FUNDS\b',regex=True) & text.str.contains(r'FEE|CHARGE|FRAIS',regex=True)
    fees=fees | (frame.tx_type.eq('debit') & compact.str.contains(r'RETURNEDITEMFEE',regex=True))
    amounts=pd.to_numeric(frame.amount,errors='coerce').fillna(0)
    # A same-day service charge is supporting evidence, not an explicit NSF fee.
    associated=pd.Series(False,index=frame.index)
    for idx in frame.index[unspecified]:
        same_account=(frame.account_id.eq(frame.at[idx,'account_id']) if 'account_id' in frame else pd.Series(False,index=frame.index))
        associated |= same_account & dates.eq(dates.loc[idx]) & frame.tx_type.eq('debit') & compact.eq('TRANSACTIONSERVICECHARGE')
    result.update(unspecified_return_items=int(unspecified.sum()),associated_service_charges=round(float(amounts[associated].sum()),2))
    result.update(returned_items=int(returned.sum()),affected_dates=int(dates[returned].nunique()),
                  returned_amount=round(float(amounts[returned].sum()),2),fee_amount=round(float(amounts[fees].sum()),2),fee_rows=int(fees.sum()),
                  paid_item_fee_rows=int(paid.sum()),paid_item_fee_amount=round(float(amounts[paid].sum()),2))
    for label in text[fees]:
        match=re.search(r'\b(\d+)\s*@',label)
        if match:result['fee_disclosed_items']+=int(match.group(1))
    for month in sorted(dates[returned|fees|paid].dropna().dt.strftime('%Y-%m').unique()):
        mask=dates.dt.strftime('%Y-%m').eq(month)
        result['monthly'].append({'Month':month,'NSF returns':int((returned&mask).sum()),
            'Dates affected':int(dates[returned&mask].nunique()),'Returned amount':round(float(amounts[returned&mask].sum()),2),
            'NSF fees':round(float(amounts[fees&mask].sum()),2),
            'Paid-item / coverage fees':round(float(amounts[paid&mask].sum()),2)})
    return result
