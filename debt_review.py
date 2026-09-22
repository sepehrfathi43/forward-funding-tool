"""Candidate debt positions, individual verification and current obligation totals."""
import hashlib
import json
import math
import re
import uuid
import unicodedata
from collections import Counter
from statistics import median
from datetime import date, timedelta, datetime, timezone
from decimal import Decimal
import pandas as pd

MULTIPLIERS = {'Daily': 21, '2-3x Weekly': 9, 'Weekly': 52/12, 'Bi-Weekly': 26/12, 'Monthly': 1}
STATUSES = ['Active', 'Closed', 'Not debt']
FIELDS = ['lender','kind','status','frequency','payment_amount','account_id','reference']
DEBT_LOGIC_VERSION = 4


def normalized_description(value):
    text = ''.join(c for c in unicodedata.normalize('NFKD', str(value)) if not unicodedata.combining(c))
    return re.sub(r'[^A-Z0-9]+', ' ', text.upper()).strip()


def extra_lender_match(description):
    text = normalized_description(description)
    if re.search(r'\bBANQUE (?:DE )?DEVELOPPEMENT DU CANAD(?:A)?\b',text):return 'Bank','BDC'
    if re.search(r'\bACCORD (?:EXPRESS|SB FINANCE)\b',text):return 'Unconfirmed','Accord financing'
    if re.search(r'\b2\s*M\s*7\s*FINANCIAL\s*SOL(?:UTIONS)?\b', text): return 'Standard', '2M7'
    if re.search(r'\b(?:VLFC\s*)?ECONOLEASE\b', text): return 'Unconfirmed', 'Econolease'
    return None

def empty():
    return pd.DataFrame(columns=['position_id','verified',*FIELDS,'notes','candidate','group_key','observed_total',
                                 'observed_payments','last_seen','verified_signature','verified_at'])

def signature(row):
    # Pandas may turn an unset type into NaN when assembling mixed rows.
    # Treat those missing values identically across save and rerender.
    values={k:None if pd.isna(row.get(k)) else row.get(k) for k in FIELDS}
    value=values.get('payment_amount')
    try:values['payment_amount']=str(Decimal(str(value)).quantize(Decimal('.01')))
    except Exception:values['payment_amount']=None
    return hashlib.sha256(json.dumps(values,sort_keys=True,default=str).encode()).hexdigest()

def is_verified(row):
    return row.get('verified') is True and row.get('verified_signature')==signature(row)

def source_match(row, lender_match):
    """These are candidates, not assertions that the named creditor is still owed."""
    if row.get('tx_type')!='debit':return None
    text=normalized_description(row.get('description',''))
    # A lender name in a bank fee/reversal is not a repayment or a contract.
    if re.search(r'\b(NSF|RETURNED|REVERSAL|REVERSED|REFUND|CANCELLED|CANCELED|RETOUR|REJETE)\b',text):return None
    # This direct-debit bank category labels lease installments as Fees/Dues.
    fee_text=re.sub(r'^DIRECT DEBIT FEES DUES (?=INFINITY LEASIN)', '', text)
    if re.search(r'\b(FEE|FEES|FRAIS)\b',fee_text):return None
    if re.search(r'\bJIM\s*PATTISON\s*LS\b',text):return 'Unconfirmed','Jim Pattison lease'
    if (match:=extra_lender_match(text)):return match
    if re.search(r'\bMBFS(?:\s+AUTO)?\b', text):return 'Bank','MBFS Auto'
    if re.search(r'\bRBC\s*LOAN\s*PYMT\b',text):return 'Bank','RBC loan'
    if re.search(r'\bINFINITY\s*LEASIN(?:G)?\b',text):return 'Unconfirmed','Infinity lease'
    if str(row.get('account_id','')).startswith('servus:') and text.strip()=='DEBIT INTEREST':
        return 'Bank','Servus credit facility'
    if re.search(r'SCOTIA BANK\s+SCOTIA LINE',text):return 'Bank','Scotia Line'
    if re.search(r'\bSUMMIT ACCEPTAN(?:CE)?\b',text):return 'Unconfirmed','Summit Acceptan'
    if re.search(r'\bLOAN\s+PAYMENT\b', text):return 'Unconfirmed','Unidentified loan payment'
    if text=='LOAN':return 'Unconfirmed','Unidentified loan payment'
    if re.search(r'\b(?:TRANSFER TO CR CARD|(?:CREDIT|CRD) CARD LOC (?:PAY|PAYMENT))\b',text):
        return 'Unconfirmed','Credit card / line of credit payment'
    if re.search(r'\b(?:LEASE PAYMENT|PAIEMENT (?:DE )?PRET)\b', text):return 'Unconfirmed','Unidentified loan or lease payment'
    return lender_match(str(row.get('description','')))

def group_key(row, match):
    text=normalized_description(row.get('description',''))
    # Retain labelled contract identifiers. Unlabelled payment trace numbers
    # change each day and cannot establish a separate debt position.
    contract=re.search(r'\b(?:CONTRACT|CONTRAT|LOAN|PRET|LEASE)\s+(?:(?:NO|NUMBER|NUMERO)\s+)?([A-Z]*\d[A-Z0-9]*)\b',text)
    reference=contract.group(0) if contract else ''
    if match[1].startswith('Unidentified'):
        reference=re.sub(r'\b\d{8,}\b','',text).strip()
    return json.dumps([str(row.get('account_id','')),match[1],reference])


def payment_pattern(rows):
    """Suggest a recent observed installment and cadence; never verify it."""
    dated=[]
    for row in rows:
        try: day=date.fromisoformat(str(row.get('date')))
        except (ValueError,TypeError): continue
        dated.append((day,Decimal(str(row.get('amount')))))
    if not dated:
        return 'Monthly',float(rows[-1].get('amount',0)),''
    dated.sort(key=lambda r:r[0]); latest=dated[-1][0]
    recent=[r for r in dated if r[0]>=latest-timedelta(days=44)]
    # Use the latest six observations for a changing installment amount.
    amounts=Counter(v for _,v in recent[-6:]); common,n=amounts.most_common(1)[0]
    installment=common if n>=max(2,len(recent[-6:])*.6) else dated[-1][1]
    days=sorted({d for d,_ in recent})
    gaps=[(b-a).days for a,b in zip(days,days[1:])]
    frequency='Monthly'
    if len(days)>=6 and median(gaps)<=2 and sum(g<=4 for g in gaps)/len(gaps)>=.8: frequency='Daily'
    elif len(gaps)>=2 and sum(6<=g<=8 for g in gaps)/len(gaps)>=.6: frequency='Weekly'
    elif len(gaps)>=2 and sum(12<=g<=16 for g in gaps)/len(gaps)>=.6: frequency='Bi-Weekly'
    elif len(gaps)>=3 and 2<=median(gaps)<=4: frequency='2-3x Weekly'
    note='Suggested from recent observed payments; confirm the current contract amount and frequency.'
    if frequency=='Monthly' and not (gaps and 26<=median(gaps)<=35):
        # Insufficient cadence evidence should require a frequency selection.
        frequency=None if len(days)>1 else 'Monthly'
        note='Cadence is not established; verify the current installment and payment frequency.'
    return frequency,float(installment),note


def payment_streams(rows):
    """Separate sustained simultaneous payments without inventing contracts.

    A changing amount on successive days is one stream. Several payments on
    at least three of the latest six payment dates support separate candidates.
    Work backwards, matching amounts before changes; retained source rows let
    the underwriter review the inferred historical assignment.
    """
    days={}
    for row in rows:
        try:day=date.fromisoformat(str(row.get('date')))
        except (ValueError,TypeError):return [rows]
        days.setdefault(day,[]).append(row)
    latest=sorted(days)[-6:]
    count,frequency=Counter(len(days[d]) for d in latest).most_common(1)[0]
    if count<2 or frequency<3 or frequency<len(latest)*.6:return [rows]
    streams=[[] for _ in range(count)]
    anchors=[Decimal(str(r['amount'])) for r in sorted(days[latest[-1]],key=lambda r:Decimal(str(r['amount'])))]
    if len(anchors)!=count:
        anchor_day=next(d for d in reversed(latest) if len(days[d])==count)
        anchors=[Decimal(str(r['amount'])) for r in sorted(days[anchor_day],key=lambda r:Decimal(str(r['amount'])))]
    for day in sorted(days,reverse=True):
        remaining=list(days[day]);available=set(range(count))
        while remaining:
            # Preserve extra historical payments too; never discard an outlier.
            slots=available or set(range(count))
            _,slot,index=min((abs(Decimal(str(r['amount']))-anchors[s]),s,i)
                             for s in slots for i,r in enumerate(remaining))
            row=remaining.pop(index);streams[slot].append(row)
            anchors[slot]=Decimal(str(row['amount']));available.discard(slot)
    return [sorted(stream,key=lambda r:r['date']) for stream in streams]

def seed_positions(df, months, lender_match):
    groups={}
    if df.empty:return empty()
    # Retain candidates from all uploaded activity, even outside the offer-month window.
    for _,tx in df.iterrows():
        match=source_match(tx,lender_match)
        if not match:continue
        key=group_key(tx,match)
        group=groups.setdefault(key,{'match':match,'rows':[]})
        group['rows'].append(tx)
    expanded={}
    for key,group in groups.items():
        streams=payment_streams(group['rows'])
        for i,rows in enumerate(streams):
            stream_key=json.dumps(json.loads(key)+['payment_stream',i+1]) if len(streams)>1 else key
            expanded[stream_key]={'match':group['match'],'rows':rows,'base_key':key,
                                  'stream_number':i+1 if len(streams)>1 else None}
    positions=[]
    for key,group in expanded.items():
        rows=group['rows'];tier,lender=group['match']
        total=sum(Decimal(str(t.amount)) for t in rows)
        frequency,payment,note=payment_pattern(rows)
        if lender=='Credit card / line of credit payment':
            frequency=None
            note='Voluntary card/LOC transfers do not establish the contractual minimum or cadence. Identify each facility, split if needed, and verify the required payment before confirming.'
        if group['stream_number']:
            note='Separate concurrent payment stream; historical assignment is inferred from payment amounts, not a verified contract. '+note
        # AI and online-activity exports can contain a missing date on a row.
        # Never let a single null/mixed-type date crash Bank Summary while
        # seeding candidate positions; retain the latest usable ISO date.
        usable_dates=[]
        for row in rows:
            value=row.get('date') if hasattr(row, 'get') else getattr(row, 'date', None)
            if value is None or pd.isna(value):
                continue
            text=str(value).strip()
            if text:
                usable_dates.append(text)
        last_seen=max(usable_dates) if usable_dates else ''
        positions.append(dict(position_id=hashlib.sha256(key.encode()).hexdigest()[:24],verified=False,
            lender=lender,kind='Other debt' if tier=='Bank' else 'MCA' if tier in ['Premium','Standard'] else None,
            status='Active',frequency=frequency,payment_amount=payment,
            account_id=rows[0].account_id,reference=(json.loads(key)[2] or lender)+(f" / payment stream {group['stream_number']}" if group['stream_number'] else ''),
            notes=note+' This lender group may contain multiple contracts; split and verify them individually.',
            evidence=[{k:t.get(k) for k in ['id','date','description','amount','source_file']} for t in rows],
            candidate=True,group_key=key,base_group_key=group['base_key'],observed_total=float(total),observed_payments=len(rows),
            last_seen=last_seen,verified_signature='',verified_at=''))
    return pd.DataFrame(positions) if positions else empty()

def normalize(frame):
    out=[]
    for raw in frame.to_dict('records'):
        row=dict(raw)
        for k,v in [('position_id',uuid.uuid4().hex),('status','Active'),('verified',False),('kind',None),
                    ('account_id',''),('reference',''),('notes',''),('candidate',False),('group_key',''),
                    ('observed_total',0.),('observed_payments',0),('last_seen',''),('verified_signature',''),('verified_at','')]:
            if k not in row or pd.isna(row[k]):row[k]=v
        row['verified']=bool(row['verified']) if pd.notna(row['verified']) else False
        if row['verified'] and row['verified_signature']!=signature(row):row['verified']=False
        out.append(row)
    return pd.DataFrame(out) if out else empty()

def row_issues(row):
    errors=[]
    if not str(row.get('lender') or '').strip():errors.append('Lender is required.')
    if row.get('status') not in STATUSES:errors.append('Choose Active, Closed or Not debt.')
    if row.get('status')=='Active':
        if row.get('kind') not in ['MCA','Other debt']:errors.append('Choose the debt type.')
        if row.get('frequency') not in MULTIPLIERS:errors.append('Choose the payment frequency.')
        try:
            amount=float(row.get('payment_amount'))
            if not math.isfinite(amount) or amount<=0:raise ValueError()
        except (TypeError,ValueError):errors.append('An active position requires a finite positive payment.')
    return errors

def save_position(frame, position_id, changes):
    out=normalize(frame)
    idx=out.index[out.position_id.eq(position_id)]
    if len(idx)!=1:raise ValueError('Debt position not found or duplicated.')
    idx=idx[0];before=out.loc[idx].to_dict();after=dict(before)
    after.update({k:v for k,v in changes.items() if k in FIELDS+['verified','notes']})
    reset=is_verified(before) and signature(after)!=signature(before)
    if reset:after['verified']=False
    if after['verified']:
        problems=row_issues(after)
        if problems:raise ValueError(' '.join(problems))
        after['verified_signature']=signature(after)
        after['verified_at']=datetime.now(timezone.utc).isoformat()
    else:after['verified_signature']='';after['verified_at']=''
    for key,value in after.items():out.at[idx,key]=value
    event={'position_id':position_id,'before':before,'after':after,'timestamp':datetime.now(timezone.utc).isoformat()}
    return out,event,reset


def split_position(frame, position_id):
    out=normalize(frame)
    idx=out.index[out.position_id.eq(position_id)]
    if len(idx)!=1:raise ValueError('Debt position not found.')
    idx=idx[0]
    out.loc[idx,['verified','verified_signature','verified_at']]=[False,'','']
    row=out.loc[idx].to_dict()
    row.update(position_id=uuid.uuid4().hex,payment_amount=0.,reference='',
               notes='Split contract: enter its own payment amount and reference. Adjust the original position to avoid counting the same payment twice.')
    return pd.concat([out,pd.DataFrame([row])],ignore_index=True)

def summary(frame):
    records=normalize(frame).to_dict('records')
    confirmed=[r for r in records if is_verified(r) and not row_issues(r)]
    active=[r for r in confirmed if r['status']=='Active']
    total=sum(float(r['payment_amount'])*MULTIPLIERS[r['frequency']] for r in active)
    suggested=0.
    for row in records:
        if row['status']!='Active':continue
        try:
            amount=float(row.get('payment_amount'))
            if not math.isfinite(amount) or amount<=0:raise ValueError()
            suggested+=amount*MULTIPLIERS[row.get('frequency')]
        except (ValueError,TypeError,KeyError):suggested=None;break
    return dict(monthly_debt=round(total,2),mca_positions=sum(r['kind']=='MCA' for r in active),
                active_positions=len(active),unverified=len(records)-len(confirmed),
                suggested_monthly_debt=round(suggested,2) if suggested is not None else None)

def readiness_issues(frame):
    n=summary(frame)['unverified']
    return [f'{n} debt position(s) need individual verification in Bank Summary.'] if n else []

def debt_payment_mask(df,lender_match,positions=None):
    rejected=set()
    rejected_ids=set()
    included_ids=set()
    if positions is not None:
        grouped={}
        for row in normalize(positions).to_dict('records'):
            if row.get('group_key'):grouped.setdefault(row['group_key'],[]).append(row)
        included_ids={str(t.get('id')) for r in normalize(positions).to_dict('records') if str(r.get('group_key','')).startswith('chat:') and not (is_verified(r) and r.get('status')=='Not debt') for t in (r.get('evidence') if isinstance(r.get('evidence'),list) else []) if t.get('id') is not None}
        rejected={key for key,rows in grouped.items() if all(is_verified(r) and r['status']=='Not debt' for r in rows)}
        for key in rejected:
            for row in grouped[key]:
                if isinstance(row.get('evidence'),list):rejected_ids.update(t.get('id') for t in row['evidence'] if t.get('id'))
    return pd.Series([bool((r.get('tx_type')=='debit' and str(r.get('id')) in included_ids) or (match:=source_match(r,lender_match)) and group_key(r,match) not in rejected and r.get('id') not in rejected_ids)
                      for _,r in df.iterrows()],index=df.index,dtype=bool)

def render(st,ss,df,months,lender_match):
    if 'debts' not in ss or ('position_id' not in ss['debts'] and ss['debts'].empty):
        ss['debts']=seed_positions(df,months,lender_match)
    ss['debts']=normalize(ss['debts'])
    st.subheader('Debt positions')
    st.caption('Verify the current payment and status for each position. A candidate may contain several contracts from the same lender; split those into individual positions.')
    current=summary(ss['debts'])
    left,right=st.columns(2)
    left.metric('Verified active positions',current['active_positions'])
    right.metric('Awaiting verification',current['unverified'])
    revision=ss.get('revision',0);epoch=ss.get('debt_epoch',0)
    for row in ss['debts'].to_dict('records'):
        pid=row['position_id'];prefix=f'debt_{revision}_{epoch}_{pid}'
        with st.form(prefix):
            cols=st.columns([1,3,2])
            verified=cols[0].checkbox('Verified',value=is_verified(row),key=prefix+'_verified')
            lender=cols[1].text_input('Lender / position',value=str(row.get('lender','')),key=prefix+'_lender')
            status=cols[2].selectbox('Status',STATUSES,index=STATUSES.index(row['status']),key=prefix+'_status')
            if row.get('candidate'):
                st.caption(f"Observed {int(row['observed_payments'])} payments totaling ${row['observed_total']:,.2f}; last seen {row['last_seen']}.")
            with st.expander('Payment and contract details',expanded=not is_verified(row)):
                a,b,c=st.columns(3)
                kinds=['MCA','Other debt']
                kind=a.selectbox('Type',kinds,index=kinds.index(row['kind']) if row['kind'] in kinds else None,key=prefix+'_kind')
                frequencies=list(MULTIPLIERS)
                frequency=b.selectbox('Frequency',frequencies,index=frequencies.index(row.get('frequency')) if row.get('frequency') in frequencies else None,key=prefix+'_frequency')
                payment=c.number_input('Payment amount',min_value=0.,value=float(row.get('payment_amount') or 0.),step=.01,key=prefix+'_amount')
                account=st.text_input('Account',value=str(row.get('account_id','')),key=prefix+'_account')
                reference=st.text_input('Contract / payment reference',value=str(row.get('reference','')),key=prefix+'_reference')
                notes=st.text_input('Notes',value=str(row.get('notes','')),key=prefix+'_notes')
                if isinstance(row.get('evidence'),list) and row['evidence']:
                    st.caption('Observed payments supporting this lender group')
                    st.dataframe(pd.DataFrame(row['evidence'])[['date','description','amount']],hide_index=True,use_container_width=True)
            save=st.form_submit_button('Save this position')
            split=st.form_submit_button('Split into another contract')
        if save:
            try:
                out,event,reset=save_position(ss['debts'],pid,dict(verified=verified,lender=lender,status=status,
                    kind=kind,frequency=frequency,payment_amount=payment,account_id=account,reference=reference,notes=notes))
                ss['debts']=out;ss['debt_audit']=ss.get('debt_audit',[])+[event]
                ss['debt_epoch']=epoch+1;ss.pop('underwriting_result',None)
                ss['debt_notice']='Details changed: check Verified again to confirm the revised position.' if reset else 'Debt position saved.'
                st.rerun()
            except ValueError as exc:st.error(str(exc))
        if split:
            ss['debts']=split_position(ss['debts'],pid)
            ss['debt_audit']=ss.get('debt_audit',[])+[{'action':'split','position_id':pid,'timestamp':datetime.now(timezone.utc).isoformat()}]
            ss['debt_epoch']=epoch+1;ss.pop('underwriting_result',None)
            ss['debt_notice']='Both contracts need verification. Enter the separate amounts and references before confirming.'
            st.rerun()
    if ss.get('debt_notice'):st.info(ss.pop('debt_notice'))
    if st.button('Add another debt position',key=f'debt_add_{revision}_{epoch}'):
        row=dict(position_id=uuid.uuid4().hex,lender='',kind=None,status='Active',frequency='Monthly',payment_amount=0.,verified=False)
        ss['debts']=normalize(pd.concat([ss['debts'],pd.DataFrame([row])],ignore_index=True))
        ss['debt_epoch']=epoch+1;ss.pop('underwriting_result',None);st.rerun()
    st.caption('Mark Closed or Not debt and verify the row to exclude it from current obligations. Only verified active positions count toward the offer calculation.')
    st.download_button('Download debt verification audit',json.dumps({'positions':ss['debts'].to_dict('records'),'events':ss.get('debt_audit',[])},indent=2,default=str),
                       'debt_verification_audit.json','application/json')
