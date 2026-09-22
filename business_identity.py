"""Company names from statement headers, never transaction counterparties."""
import re
import unicodedata


def key(name):
    text=''.join(c for c in unicodedata.normalize('NFKD',name) if not unicodedata.combining(c))
    return re.sub(r'[^A-Z0-9]','',text.upper())


def header_names(text):
    header=re.split(r'Transaction\s*details|Account\s+(?:Activity\s+)?Details\b',text,flags=re.I)[0]
    found=[]
    # Explicit account-holder/trading-name labels are stronger evidence than
    # a corporate suffix. Sole proprietors often have neither Inc. nor Ltd.
    for match in re.finditer(r'(?:Business\s*name|Operating\s*as)\s*:\s*\n([^\n]+)',text,re.I):
        printed=match[1].strip()
        pretty=next((line.strip() for line in header.splitlines()
                     if key(re.split(r'\s+For\s*questions',line,flags=re.I)[0])==key(printed)),printed)
        pretty=re.split(r'\s+For\s*questions',pretty,flags=re.I)[0].strip()
        found.append(pretty)
    for line in header.splitlines():
        line=re.sub(r'\s+',' ',line).strip()
        numbered=re.fullmatch(r'(\d[\d \-]{4,}\d)\s*(CANADA|ONTARIO|QU[ÉE]BEC)\s*(INC\.?|LTD\.?|LIMITED|LT[ÉE]E\.?)',line,re.I)
        if numbered:
            number=re.sub(r'\s','',numbered[1])
            found.append(f'{number} {numbered[2].upper()} {numbered[3].upper().rstrip(".")}.')
        elif re.fullmatch(r'[\w &.,\-/’\']{2,100}\s+(?:INC\.?|LTD\.?|LIMITED|LT[ÉE]E\.?|CORP\.?|CORPORATION)',line,re.I):
            found.append(line)
    return distinct(found)


def distinct(names):
    out={}
    for name in names:
        if name and str(name).strip():out.setdefault(key(str(name)),re.sub(r'\s+',' ',str(name)).strip())
    return list(out.values())


def result_names(results):
    names=[]
    for result in results:
        names.extend(result.get('company_names',[]))
        names.append(result.get('account_holder'))
        names.extend(result_names(result.get('account_statements',[])))
    return sorted(distinct(names),key=key)
