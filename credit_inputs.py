"""Applicant score extraction and case-bound editable underwriting input."""
import hashlib
import json
import re
from pdf_access import open_pdf


def extract_score(data):
    with open_pdf(data) as doc:
        text='\n'.join(page.extract_text() or '' for page in doc.pages)
    scores={int(value) for value in re.findall(r'\bFICO\s+Score\s+8\s*[:\-]?\s*(\d{3})\b',text,re.I)}
    if len(scores)==1 and 300<=next(iter(scores))<=900:
        return next(iter(scores))
    return None


def render_score(st, ss, business, fallback=None):
    report=ss.get('credit_reports',{}).get('applicant',{})
    extracted=report.get('profile',{}).get('fico_score')
    try:
        extracted=int(extracted) if extracted is not None else None
        if extracted is not None and not 300<=extracted<=900:extracted=None
    except (TypeError,ValueError):extracted=None
    suggested=extracted if extracted is not None else fallback
    token=hashlib.sha256(json.dumps([business,ss.get('revision'),report.get('source_sha256'),suggested]).encode()).hexdigest()[:20]
    value=st.number_input('Applicant credit score',min_value=300,max_value=900,value=suggested,step=1,
                          key='underwriting_credit_'+token,
                          help='Automatically filled from the applicant report. Enter or correct the score here; co-applicant scores are not substituted.')
    origin=('applicant PDF' if extracted is not None else 'underwriter case setting') if value==suggested and value is not None else 'manual entry on Underwriting Model'
    if value is None:origin='not supplied'
    evidence={'value':value,'source':origin,'extracted_score':extracted,'source_sha256':report.get('source_sha256'),
              'source_file':report.get('source_file'),'report_verified':bool(report.get('verified'))}
    if ss.get('underwriting_credit_input')!=evidence:
        ss.pop('underwriting_result',None)
        ss['underwriting_credit_input']=evidence
    st.caption('Credit score source: '+origin+'. This field is used in the scorecard.')
    if extracted is not None and not report.get('verified'):
        st.caption('The extracted score is included; applicant identity and report figures remain unverified. Review them before confirming the underwriting inputs.')
    if value is None:st.info('No credit score available. Enter it here or upload a readable applicant report. Missing credit receives zero points.')
    return value,evidence
