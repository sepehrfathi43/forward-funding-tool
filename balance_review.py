"""Explicit source-verified balance corrections with immutable audit evidence."""
from copy import deepcopy
from datetime import datetime, timezone
from statement_validation import decimal_value, validate_statement


def correct(results, ledger, transaction_id, value, reference):
    if not reference.strip():raise ValueError('Source reference is required.')
    amount=decimal_value(str(value))
    updated=deepcopy(results);frame=ledger.copy(deep=True)
    matches=[(result,row) for result in updated for row in result.get('transactions',[]) if row.get('id')==transaction_id]
    if len(matches)!=1 or int(frame.id.eq(transaction_id).sum())!=1:raise ValueError('Choose a unique transaction in the current case.')
    result,row=matches[0]
    audit={'transaction_id':transaction_id,'file':result.get('source_file'),'page':row.get('page'),
           'field':'balance','before':row.get('balance'),'after':str(amount),'reference':reference.strip(),
           'timestamp':datetime.now(timezone.utc).isoformat(),'source':'underwriter_verified_source'}
    row.setdefault('original_extracted_balance',row.get('balance'));row['balance']=str(amount)
    # Shared validation recomputes every checkpoint, replacing stale AI
    # checkpoint messages without waiving other date, total or source issues.
    result['issues']=[i for i in result.get('issues',[]) if not (i.startswith('AI transaction ') and 'balance checkpoint does not reconcile' in i)]
    result['suggested_balance_repairs']=[]
    result['status']='review_required'
    validate_statement(result)
    result.setdefault('source_corrections',[]).append(audit)
    frame.loc[frame.id.eq(transaction_id),'balance']=float(amount)
    return updated,frame,audit


def render(st,ss):
    ledger=ss.get('ledger')
    if ledger is None or ledger.empty:return
    with st.expander('Correct an extracted balance against the source PDF'):
        st.caption('Use only after checking the original page. Original values and your source reference are retained in the audit. This does not override other diagnostics.')
        rows=ledger.to_dict('records');labels={r['id']:f"{r.get('source_file','')} · page {r.get('page')} · {r['date']} · {r['description']} · balance {r.get('balance')}" for r in rows}
        selected=st.selectbox('Transaction to correct',list(labels),index=None,format_func=lambda key:labels[key],key='balance_correction_id')
        value=st.text_input('Correct balance printed on the PDF',key='balance_correction_value')
        reference=st.text_input('Source page and verification note',key='balance_correction_reference')
        verified=st.checkbox('I checked this balance against the original PDF',key='balance_correction_verified')
        if st.button('Apply verified balance correction',disabled=not(selected and value.strip() and reference.strip() and verified)):
            try:results,frame,audit=correct(ss['results'],ledger,selected,value,reference)
            except ValueError as exc:st.error(str(exc));return
            ss['results']=results;ss['ledger']=frame
            ss.setdefault('decision_audit',[]).append(audit)
            ss.pop('underwriting_result',None);ss.pop('diagnostic_override',None)
            st.rerun()
