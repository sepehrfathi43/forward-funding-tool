"""French RBC statements: preserve positioned amounts and inherited dates."""
import re
import unicodedata
from datetime import date
from rbc_td_parser import _base, _word_lines, _add_row, _finish
from statement_validation import parse_money


def norm(s):
    return ''.join(c for c in unicodedata.normalize('NFD',s.lower()) if not unicodedata.combining(c))


MONTHS={'janvier':1,'janv':1,'fevrier':2,'fevr':2,'mars':3,'avril':4,'avr':4,'mai':5,'juin':6,'juillet':7,'juil':7,'aout':8,'septembre':9,'sept':9,'octobre':10,'oct':10,'novembre':11,'nov':11,'decembre':12,'dec':12}


def parse_rbc_french(data,filename,doc):
    r=_base(data,filename,'rbc_french')
    first=norm(doc.pages[0].extract_text(x_tolerance=2) or '')
    period=re.search(r'du (\d+) (\w+) (\d{4}) au (\d+) (\w+) (\d{4})',first)
    account=re.search(r'numero de compte\s*:\s*([\d-]+)',first)
    if not period or not account:
        r['issues'].append('French RBC account or period missing');return r
    a,b,c,d,e,f=period.groups();start=date(int(c),MONTHS[b],int(a));end=date(int(f),MONTHS[e],int(d))
    r.update(account_id='rbc:'+account[1].replace('-',''),currency='CAD',period_start=start.isoformat(),period_end=end.isoformat())
    def summary(label):
        line=next((l for l in first.splitlines() if label in l),None)
        if not line:return None
        if 'solde' in label:line=re.sub(r'^.*?\b\d{4}\b','',line)
        m=re.search(r'(-?\d[\d ]*,\d{2})\s*\$?$',line)
        return parse_money(m[1]) if m else None
    opening=summary("votre solde d'ouverture");closing=summary('votre solde de cloture')
    expected={'debits':summary('total des retraits'),'credits':summary('total des depots')}
    if opening is None or closing is None or any(v is None for v in expected.values()):r['issues'].append('French RBC printed summary incomplete')
    last_date=None;pending=''
    for pn,page in enumerate(doc.pages,1):
        ls=_word_lines(page)
        header=next(((y,ws) for y,ws in ls if {'date','description','retraits','depots','solde'}.issubset({norm(w['text']) for w in ws})),None)
        if not header:
            r.setdefault('excluded_notice_pages',[]).append(pn);continue
        hy,hws=header;pos={norm(w['text']):w['x0'] for w in hws}
        dx=pos['description'];wx=pos['retraits'];cx=pos['depots'];bx=pos['solde'];datex=pos['date']
        for y,ws in ls:
            ws=[w for w in ws if w.get('upright',True)]
            if y<=hy+4 or y>page.height-40:continue
            visible=' '.join(w['text'] for w in ws if w['x0']>=datex-2)
            if re.fullmatch(r'\d+ de \d+',visible.strip()):continue
            desc=' '.join(w['text'] for w in ws if dx-3<=w['x0']<wx-28)
            compact=norm(desc).replace(' ','')
            if compact.startswith('soldedecloture'):pending='';break
            if compact.startswith("solded'ouverture"):continue
            prefix=norm(' '.join(w['text'] for w in ws if datex-2<=w['x0']<dx-3)).strip('. ')
            match=re.fullmatch(r'(\d{1,2})\s+([a-z]+)',prefix)
            if match:
                try:last_date=date(start.year+(MONTHS[match[2]]<start.month),MONTHS[match[2]],int(match[1]))
                except (KeyError,ValueError):last_date=None;r['issues'].append(f'Page {pn}: invalid date {prefix}')
            elif prefix:
                r['issues'].append(f'Page {pn}: unreadable date {prefix}');last_date=None
            def amount(left,right):
                s=' '.join(w['text'] for w in ws if left<=w['x0']<right).strip()
                if not s or s=='-':return None
                try:return parse_money(s)
                except ValueError:r['issues'].append(f'Page {pn}: unreadable amount {s}');return None
            debit=amount(wx-28,(wx+cx)/2);credit=amount((wx+cx)/2,(cx+bx)/2);balance=amount((cx+bx)/2,page.width)
            if debit is None and credit is None:
                if desc:pending=(pending+' '+desc).strip()
                continue
            description=(pending+' '+desc).strip();pending=''
            _add_row(r,filename,pn,y,last_date,description,debit,credit,balance)
    r['warnings'].append('This layout has no printed transaction counts; printed totals and balance checkpoints are checked.')
    return _finish(r,opening,closing,expected)
