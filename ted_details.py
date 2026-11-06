"""Evidence-based eForms lot extraction for TenderCore.

Extract only known structured fields. Never infer absence of bonds, fees, or
supplier eligibility from missing elements. Selection criteria are *requirements*
not proof that a bidder satisfies them.
"""
from __future__ import annotations
from datetime import date, timedelta
import re
from urllib.parse import urlparse
from defusedxml import ElementTree as ET

MAX_XML = 8_000_000


def tag(node):
    return node.tag.rsplit('}', 1)[-1]


def direct(node, local):
    return next((c for c in node if tag(c) == local), None) if node is not None else None


def text_child(node, local):
    child = direct(node, local)
    return (child.text or '').strip() if child is not None else ''


def all_desc(node, local, limit=4):
    if node is None:
        return []
    values = []
    for child in node:
        if tag(child) == local and child.text and child.text.strip():
            values.append({'text': child.text.strip()[:1800], 'language':child.attrib.get('languageID', '')})
    # Prefer English, preserve source language, avoid same text duplicates.
    values.sort(key=lambda d: 0 if d['language'].upper() in ('ENG', 'EN') else 1)
    seen = set()
    out = []
    for value in values:
        if value['text'] not in seen:
            out.append(value); seen.add(value['text'])
        if len(out) >= limit: break
    return out


def https_url(value):
    try:
        u = urlparse(value.strip())
        return bool(u.scheme == 'https' and u.hostname and not u.username and not u.password)
    except ValueError: return False


def duration(period):
    if period is None: return {'days':None,'display':None,'source':None}
    start = text_child(period,'StartDate')[:10]
    end = text_child(period,'EndDate')[:10]
    if start and end:
        try:
            days = (date.fromisoformat(end) - date.fromisoformat(start)).days
            if days >= 0:
                return {'days':days,'display':f'{start} – {end}', 'source':'BT-536 / BT-537'}
        except ValueError: pass
    measure=direct(period,'DurationMeasure')
    if measure is not None and (measure.text or '').strip().isdigit():
        number=int(measure.text.strip()); unit=measure.attrib.get('unitCode','').upper()
        if number <= 10000 and unit in ('DAY','WEEK','MONTH','YEAR'):
            # MONTH/YEAR are not exact day counts. Do not fabricate dates/lengths.
            days = number * {'DAY':1,'WEEK':7}.get(unit,0) if unit in ('DAY','WEEK') else None
            return {'days':days,'display':f'{number} {unit}', 'source':'BT-36'}
    other=text_child(period,'DescriptionCode')
    return {'days':None,'display':other[:80] or None,'source':'BT-538' if other else None}


def extract_eforms(blob:bytes)->dict:
    """Return structured details for every lot. Error rather than guessing."""
    if len(blob)>MAX_XML:raise ValueError('XML exceeds 8 MB')
    root=ET.fromstring(blob)
    lots=[]
    for lot in root.iter():
        if tag(lot)!='ProcurementProjectLot':continue
        identifier=text_child(lot,'ID') or None
        project=direct(lot,'ProcurementProject')
        terms=direct(lot,'TenderingTerms')
        docs=[]; guarantee='unknown';guarantee_description=[]
        criteria=[];award=[];conditions=[];financial=[];deadline=None;submission_url=None
        if terms is not None:
            for node in terms:
                node_type=tag(node)
                if node_type=='RequiredFinancialGuarantee':
                    for child in node:
                        if tag(child)=='GuaranteeTypeCode' and child.attrib.get('listName')=='tender-guarantee-required':
                            val=(child.text or '').strip().lower()
                            if val=='true':guarantee='required'
                            if val=='false' and guarantee!='required':guarantee='not_required'
                    guarantee_description.extend(all_desc(node,'Description'))
                if node_type=='CallForTendersDocumentReference':
                    reference=direct(direct(node,'Attachment'),'ExternalReference')
                    uri=text_child(reference,'URI')
                    if https_url(uri) and len(docs)<12:
                        docs.append({'url':uri,'restricted':text_child(node,'DocumentType')=='restricted-document',
                                     'reference':text_child(node,'ID')})
                if node_type=='PaymentTerms':financial.extend(all_desc(node,'Note'))
                if node_type=='TenderSubmissionDeadlinePeriod':
                    deadline=text_child(node,'EndDate')[:10] or deadline
                if node_type=='TenderRecipientParty':
                    uri=text_child(node,'EndpointID')
                    if https_url(uri):submission_url=uri
                if node_type in ('ContractExecutionRequirement','ContractExecutionRequirements'):
                    conditions.extend(all_desc(node,'Description'))
                if node_type=='AwardingTerms':
                    for c in node.iter():
                        if tag(c)!='SubordinateAwardingCriterion': continue
                        award.append({'type':text_child(c,'AwardingCriterionTypeCode'),
                                      'name':text_child(c,'Name')[:220],
                                      'description':text_child(c,'Description')[:800]})
                if node_type=='TendererQualificationRequest':
                    for c in node.iter():
                        if tag(c)!='SpecificTendererRequirement':continue
                        code=direct(c,'TendererRequirementTypeCode')
                        if code is not None and (code.text or '').strip():
                            criteria.append({'code':code.text.strip(), 'source':code.attrib.get('listName',''),
                                             'description':all_desc(c,'Description')[:2]})
            # There may also be selection criteria in an eForms UBL extension,
            # associated with a particular lot. Don't blindly assign all criteria to all lots.
        for ext in lot.iter():
            if tag(ext)=='SelectionCriteria':
                code=text_child(ext,'TendererRequirementTypeCode')
                if code:
                    criteria.append({'code':code,'source':'eForms BT-809','description':all_desc(ext,'Description')[:2]})
        period=direct(project,'PlannedPeriod') if project is not None else None
        dur=duration(period)
        lots.append({
            'lot':identifier,'title':all_desc(project,'Name')[:1],
            'description':all_desc(project,'Description')[:2],
            'bid_guarantee':guarantee,'bid_guarantee_description':guarantee_description[:3],
            'contract_duration_days':dur['days'],'contract_duration':dur['display'],
            'duration_source':dur['source'],'deadline':deadline,
            'documents':docs,'submission_url':submission_url,
            'qualification_requirements':criteria[:30],
            'award_criteria':award[:25], 'financial_terms':financial[:3],
            'execution_terms':conditions[:3],
        })
    if not lots:return {'lots':[],'bid_guarantee':'unknown','contract_duration_days':None,
                        'documents_count':0,'error':'No eForms procurement lots found'}
    bonds=[l['bid_guarantee'] for l in lots]
    bond=('required' if 'required' in bonds else
          'not_required' if all(b=='not_required' for b in bonds) else 'unknown')
    durations=[l['contract_duration_days'] for l in lots]
    # Never claim notice-level duration is known if one lot has unknown duration.
    days=max(durations) if all(v is not None for v in durations) else None
    dates=[l['deadline'] for l in lots]
    deadline=max(dates) if all(dates) else None
    docs=list(dict.fromkeys(d['url'] for l in lots for d in l['documents']))
    return {'lots':lots,'bid_guarantee':bond,'contract_duration_days':days,
            'deadline':deadline,'documents_count':len(docs),'documents_urls':docs[:20],
            'source':'TED eForms XML, per lot',
            'coverage':{'lots':len(lots), 'guarantee_known':sum(b!='unknown' for b in bonds),
                        'duration_known':sum(d is not None for d in durations),
                        'qualification_described':sum(bool(l['qualification_requirements']) for l in lots)}}


def fetch_eforms_details(url: str, session=None) -> dict:
    """Read one HTTPS XML notice with strict host allowlist, byte cap and no redirects."""
    import requests
    from ted_client import safe_ted_url
    if not url or not safe_ted_url(url):
        return {'error':'TED XML URL missing or not allowlisted'}
    sess=session or requests.Session()
    try:
        with sess.get(url, timeout=(8,30), stream=True, allow_redirects=False,
                      headers={'Accept':'application/xml,text/xml'}) as response:
            response.raise_for_status()
            if response.status_code >= 300: raise ValueError('XML redirect blocked')
            body=bytearray()
            for chunk in response.iter_content(65536):
                body.extend(chunk)
                if len(body)>MAX_XML:raise ValueError('XML exceeds 8 MB')
            return extract_eforms(bytes(body))
    except (requests.RequestException, ValueError, ET.ParseError) as exc:
        return {'error':f'{type(exc).__name__}: {str(exc)[:220]}'}


def update_from_details(item:dict, details:dict)->dict:
    """Apply only verified XML facts, keep manual judgements and amounts untouched."""
    fresh=item.copy()
    if details.get('error'):
        fresh['xml_error']=details['error']
        fresh['details_fetch_status']='failed'
        return fresh
    fresh['xml_error']=None
    fresh['details_fetch_status']='parsed'
    fresh['details_checked_at']=__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(timespec='seconds')
    fresh['lots_detail']=details['lots']
    fresh['details_coverage']=details.get('coverage',{})
    fresh['documents_urls']=details.get('documents_urls',[])
    fresh['bid_guarantee']=details.get('bid_guarantee','unknown')
    fresh['guarantee_evidence']='TED eForms BT-751'
    fresh['guarantee_lots']=[{'lot':lot['lot'], 'value':lot['bid_guarantee'],
                               'description':next((v['text'] for v in lot['bid_guarantee_description']),None)}
                              for lot in details['lots']]
    fresh['award_criteria_lots']=[{'lot':lot['lot'],'criteria':lot['award_criteria']}
                                  for lot in details['lots'] if lot['award_criteria']]
    fresh['contract_duration_days']=details.get('contract_duration_days')
    if details.get('deadline'): fresh['deadline']=details['deadline']
    # Do not set company_eligibility / performance_guarantee / participation_fee
    # from generic prose: those require independent verification.
    return fresh
