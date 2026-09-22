"""Conservative institution candidates and page coverage evidence."""
import re


def inspect_document(document):
    pages=[]
    for number,page in enumerate(document.pages,1):
        text=page.extract_text() or ''
        pages.append({'page':number,'text_characters':len(text.strip()),'text':text})
    header='\n'.join(p['text'] for p in pages[:2])
    patterns={'TD':r'\bTD\b|Toronto.Dominion','RBC':r'Royal Bank|\bRBC\b|banqueroyale',
              'BMO':r'\bBMO\b|Bank of Montreal|Banque de Montr',
              'Scotiabank':r'Scotiabank|scotiabank.com','CIBC':r'\bCIBC\b',
              'ATB':r'\bATB\b|atb.com','Servus':r'Servus|servus.ca',
              'Vancity':r'Vancity','National Bank':r'National Bank|Banque Nationale',
              'Wise':r'Wise Payments','Neo':r'Neo Everyday','Flinks':r'flinks dashboard|dashboard.flinks.com'}
    candidates=[name for name,pattern in patterns.items() if re.search(pattern,header,re.I)]
    readable=sum(p['text_characters']>0 for p in pages)
    totals=sorted({int(m) for p in pages for m in re.findall(r'\bPage\s+\d+\s+(?:of|de|/)\s*(\d+)',p['text'],re.I)})
    return dict(institution_candidate=candidates[0] if len(candidates)==1 else None,
                institution_candidates=candidates,page_count=len(pages),
                format='text' if readable==len(pages) else 'image-only' if not readable else 'mixed',
                pages=[{k:v for k,v in p.items() if k!='text'} for p in pages],printed_page_totals=totals,
                reader_recovery=getattr(document,'reader_recovery',None))


def attach_evidence(result,identification):
    result['document_identification']=identification
    warnings=list(result.get('page_accounting_warnings',[]))
    for total in identification.get('printed_page_totals',[]):
        if total>identification['page_count']:
            warnings.append(f"Printed page count {total} exceeds uploaded pages {identification['page_count']}. Verify whether omitted pages contain transactions or attachments.")
    result['page_accounting_warnings']=list(dict.fromkeys(warnings))
    return result
