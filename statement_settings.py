"""Case-level currency assumptions and explicit source coverage confirmation."""
from copy import deepcopy
from datetime import date, datetime, timezone
import re
from servus_parser import CURRENCY_ISSUE


def apply_currency(results, suspect=False, overrides=None):
    out=deepcopy(results)
    for index,r in enumerate(out):
        explicit=r.get('currency')
        assumed=r.get('currency_source')=='case_policy_default_cad'
        choice=(overrides or {}).get(index)
        if choice:
            r.update(currency=choice,currency_source='underwriter_confirmation',currency_review_required=False)
        elif (not explicit or explicit=='Unknown' or assumed):
            r.update(currency=None if suspect else 'CAD',currency_source='not_printed' if suspect else 'case_policy_default_cad',currency_review_required=suspect)
        if r.get('currency') in ('CAD','USD'):
            r['issues']=[i for i in r.get('issues',[]) if i!=CURRENCY_ISSUE]
        elif CURRENCY_ISSUE not in r.get('issues',[]):r.setdefault('issues',[]).append(CURRENCY_ISSUE)
    return out


def invalid_period(result):
    try:return date.fromisoformat(result['period_start'])>date.fromisoformat(result['period_end'])
    except (KeyError,TypeError,ValueError):return True


def confirm_period(result,start,end,reference):
    if start>end or (end-start).days>3660:raise ValueError('Enter a valid coverage period of no more than ten years.')
    if not reference.strip():raise ValueError('A source reference is required.')
    dates=[date.fromisoformat(r['date']) for r in result.get('transactions',[]) if r.get('date')]
    if any(d<start or d>end for d in dates):raise ValueError('Coverage must include all transaction dates in this statement.')
    out=deepcopy(result)
    out['coverage_confirmation']={'before':[result.get('period_start'),result.get('period_end')],
        'after':[start.isoformat(),end.isoformat()],'reference':reference,'timestamp':datetime.now(timezone.utc).isoformat()}
    out.update(period_start=start.isoformat(),period_end=end.isoformat())
    out['issues']=[i for i in out.get('issues',[]) if i not in ('AI did not identify a complete statement period','AI statement period is reversed','Shared validation: invalid or missing statement period')]
    from statement_validation import validate_statement
    return validate_statement(out)


def render(st,ss):
    results=ss.get('results',[])
    if not results:return
    suspected=any(r.get('currency')=='USD' or re.search(r'\bUSD\b|U\.S\. dollars|US dollars',str(r.get('currency_evidence','')),re.I) for r in results)
    suspect=st.checkbox('Statements may be in USD or another currency',value=suspected,key='suspect_foreign_currency')
    overrides={}
    if suspect:
        st.info('Check the source currency for each statement. USD is converted using the reporting rate in the sidebar.')
        for index,r in enumerate(results):
            value=st.selectbox('Verified currency — '+r.get('source_file',str(index)),['Not confirmed','CAD','USD'],index=0,key=f'currency_choice_{ss.get("revision",0)}_{index}')
            if value!='Not confirmed':overrides[index]=value
    else:st.caption('Currency policy: unspecified currency defaults to CAD. Explicitly identified foreign currencies are preserved. Enable the checkbox above if you suspect USD.')
    updated=apply_currency(results,suspect,overrides)
    if updated!=results:ss['results']=updated;ss.pop('underwriting_result',None);ss.pop('diagnostic_override',None)
    ledger=ss.get('ledger')
    if ledger is not None and not ledger.empty:
        lookup={(r.get('source_sha256'),r.get('account_id')):r.get('currency') for r in updated}
        ss['ledger']['currency']=[lookup.get((row.get('statement_sha256'),row.get('account_id')),row.get('currency')) for row in ledger.to_dict('records')]
    for index,r in enumerate(updated):
        if not invalid_period(r):continue
        with st.expander('Confirm missing statement coverage — '+r.get('source_file',str(index)),expanded=True):
            st.warning('Transaction dates were extracted, but statement coverage is missing or invalid. Confirm the actual period from the source; first/last activity alone does not prove coverage.')
            dates=sorted(row['date'] for row in r.get('transactions',[]) if row.get('date'))
            prefix=f'coverage_{ss.get("revision",0)}_{index}'
            start=st.date_input('Verified coverage start',value=date.fromisoformat(dates[0]) if dates else None,key=prefix+'_start')
            end=st.date_input('Verified coverage end',value=date.fromisoformat(dates[-1]) if dates else None,key=prefix+'_end')
            note=st.text_input('Coverage evidence / source reference',key=prefix+'_note')
            checked=st.checkbox('I verified this complete coverage period against the source',key=prefix+'_checked')
            if st.button('Apply verified coverage',key=prefix+'_apply',disabled=not(checked and start and end and note.strip())):
                try:corrected=confirm_period(r,start,end,note)
                except ValueError as exc:st.error(str(exc));continue
                ss['results'][index]=corrected
                ss.setdefault('decision_audit',[]).append({'action':'coverage_confirmation',**corrected['coverage_confirmation']})
                ss.pop('underwriting_result',None);ss.pop('diagnostic_override',None);st.rerun()
