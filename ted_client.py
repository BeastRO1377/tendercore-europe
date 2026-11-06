"""TED Search API v3 adapter, with conservative normalization and no fabricated facts."""
from __future__ import annotations
import re
from datetime import date, timedelta
from urllib.parse import urlparse
from typing import Any
from defusedxml import ElementTree as SafeET
import requests
from tax_engine import ISO3, REVERSE_ISO3

API_URL = 'https://api.ted.europa.eu/v3/notices/search'
FIELDS = [
 'publication-number','publication-date','notice-title','buyer-name','buyer-country',
 'notice-type','form-type','classification-cpv','total-value','total-value-cur',
 'deadline-receipt-tender-date-lot','winner-name','received-submissions-type-val',
 'title-proc','title-lot','description-lot','identifier-lot',
 'estimated-value-proc','estimated-value-cur-proc',
 'guarantee-required-lot','guarantee-required-description-lot',
 'document-url-lot','selection-criterion-description-lot',
 'contract-duration-start-date-lot','contract-duration-end-date-lot',
 'terms-financial-lot'
]
AWARDS = ['can-standard','can-social','can-desg','can-tran']
COMPETITIONS = ['cn-standard','cn-social','cn-desg']

class TEDSourceError(RuntimeError):
    pass


def clean_cpvs(values: Any) -> list[str]:
    if isinstance(values,str): values = values.replace(',', ' ').split()
    if not isinstance(values,list): return []
    return list(dict.fromkeys(str(v).strip() for v in values if re.fullmatch(r'\d{2,8}',str(v).strip())))[:15]


def build_query(profile: dict, kind: str, lookback_days: int = 90) -> str:
    if kind not in ('competition','award'):
        raise ValueError('Invalid kind')
    days = min(max(int(lookback_days), 1), 730)
    clauses = [f'publication-date>={(date.today()-timedelta(days=days)).strftime("%Y%m%d")}',
               'notice-type IN ('+' '.join(COMPETITIONS if kind=='competition' else AWARDS)+')']
    countries = profile.get('countries',[])
    iso3 = [ISO3[c] for c in countries if c in ISO3]
    if iso3:
        clauses.append('buyer-country IN ('+' '.join(sorted(set(iso3)))+')')
    codes = clean_cpvs(profile.get('cpv_prefixes',[]))
    if codes:
        clauses.append('('+' OR '.join('classification-cpv = '+c+('*' if len(c)<8 else '') for c in codes)+')')
    return ' AND '.join(clauses) + ' SORT BY publication-date DESC'


def request_payload(profile: dict,kind: str,lookback_days: int = 90,limit:int=80,page:int=1) -> dict:
    return {'query':build_query(profile,kind,lookback_days),'fields':FIELDS,
            'limit':min(max(int(limit),1),250),'scope':'ALL','paginationMode':'PAGE_NUMBER',
            'page':min(max(page,1),60), 'onlyLatestVersions':True}


def fetch_notices(profile: dict, kind: str, lookback_days: int = 90, limit:int=80,
                  session:requests.Session|None=None) -> dict:
    sess = session or requests.Session()
    sess.headers.update({'Accept':'application/json','User-Agent':'TenderCoreEuropeCommunity/0.1.0-alpha (open-source research client)'})
    payload=request_payload(profile,kind,lookback_days,limit)
    try:
        r=sess.post(API_URL,json=payload,timeout=(8,30))
        r.raise_for_status()
        raw=r.json()
    except (requests.RequestException,ValueError) as e:
        raise TEDSourceError(f'TED {kind}: {type(e).__name__}: {str(e)[:300]}') from e
    if not isinstance(raw,dict) or not isinstance(raw.get('notices'),list):
        raise TEDSourceError('TED response is not a notice collection')
    return {'items':[normalize(n,kind) for n in raw['notices'] if isinstance(n,dict)],
            'reported_total':raw.get('totalNoticeCount'), 'request_count':len(raw['notices']),
            'query':payload['query'],'limit':payload['limit']}


def flatten(value: Any,lang='eng') -> str:
    if value is None: return ''
    if isinstance(value,str): return value
    if isinstance(value,(int,float)): return str(value)
    if isinstance(value,list):
        return ', '.join(filter(None,(flatten(v,lang) for v in value)))
    if isinstance(value,dict):
        for k in [lang,lang.upper(), 'eng','ENG','en','EN','fra','deu','rus']:
            if k in value and value[k]: return flatten(value[k],lang)
        return flatten(next(iter(value.values()),''),lang)
    return ''


def get_field(n:dict,*keys:str) -> Any:
    for k in keys:
        val=n.get(k)
        if val not in (None,'',[]): return val
    return None


def parse_amount(raw:Any) -> float|None:
    text=flatten(raw).replace(' ','').replace('\u00a0','')
    if not text: return None
    try:
        import decimal
        v=decimal.Decimal(text)
        if not v.is_finite() or v<0: return None
        return float(v)
    except Exception: return None


def xml_link(n:dict) -> str|None:
    links=n.get('links') or {}
    if not isinstance(links,dict): return None
    value=links.get('xml') or links.get('XML')
    if isinstance(value,str): return value
    if isinstance(value,dict):
        for k in ['ENG','eng','en','original']:
            if isinstance(value.get(k),str):return value[k]
        for v in value.values():
            if isinstance(v,str):return v
            if isinstance(v,dict):
                val=v.get('url') or v.get('href')
                if isinstance(val,str): return val
    if isinstance(value,list):
        for v in value:
            if isinstance(v,str):return v
            if isinstance(v,dict) and isinstance(v.get('url'),str):return v['url']
    return None


def safe_ted_url(url:str) -> bool:
    try:
        p=urlparse(url)
        return p.scheme=='https' and p.hostname in ('ted.europa.eu','api.ted.europa.eu') and not p.username and not p.password and p.port in (None,443)
    except ValueError:
        return False


def _values(v):
    if v is None:return []
    if isinstance(v,list):return [x for x in v if x not in (None,'')]
    if isinstance(v,dict):
        for key in ('eng','ENG','en','deu','fra'):
            if key in v:return _values(v[key])
        return _values(next(iter(v.values()),[]))
    return [v]

def search_snapshot(n:dict)->dict:
    """Best-effort fields directly from TED search; XML remains authoritative."""
    lot_ids=_values(n.get('identifier-lot'))
    indicators=_values(n.get('guarantee-required-lot'))
    flags=[str(x).strip().lower() for x in indicators]
    guarantee='unknown'
    if any(x in ('true','1') for x in flags):guarantee='required'
    elif flags and all(x in ('false','0') for x in flags) and lot_ids and len(flags)==len(lot_ids):
        guarantee='not_required'
    documents=[x for x in _values(n.get('document-url-lot')) if isinstance(x,str)
               and x.startswith('https://')]
    starts=[str(v)[:10] for v in _values(n.get('contract-duration-start-date-lot'))]
    ends=[str(v)[:10] for v in _values(n.get('contract-duration-end-date-lot'))]
    contract_days=None
    if lot_ids and starts and ends and len(lot_ids)==len(starts)==len(ends):
        try:
            lengths=[(date.fromisoformat(e)-date.fromisoformat(s)).days for s,e in zip(starts,ends)]
            if all(x>=0 for x in lengths):contract_days=max(lengths)
        except ValueError:pass
    desc=flatten(n.get('description-lot'))[:500]
    return {'bid_guarantee':guarantee, 'contract_duration_days':contract_days,
            'search_description':desc,'documents_urls':list(dict.fromkeys(documents))[:15],
            'search_guarantee_description':flatten(n.get('guarantee-required-description-lot'))[:450],
            'search_selection_requirements':flatten(n.get('selection-criterion-description-lot'))[:600],
            'search_financial_terms':flatten(n.get('terms-financial-lot'))[:500],
            'search_lot_count':len(lot_ids) or None}

def normalize(n:dict,kind:str) -> dict:
    number=flatten(get_field(n,'publication-number')).strip()
    # Required stable identifier: do not create one from a missing publication number.
    if not re.fullmatch(r'\d{1,8}-\d{4}',number):
        return {'id':'','invalid':True}
    country_raw=flatten(get_field(n,'buyer-country')).upper()
    country=REVERSE_ISO3.get(country_raw,country_raw if len(country_raw)==2 else '')
    cpvs=clean_cpvs(get_field(n,'classification-cpv') or [])
    kind_val=flatten(get_field(n,'notice-type')).lower()
    value=parse_amount(get_field(n,'estimated-value-proc','total-value') if kind=='competition' else get_field(n,'total-value'))
    currency=flatten(get_field(n,'estimated-value-cur-proc','total-value-cur') if kind=='competition' else get_field(n,'total-value-cur')).upper() or None
    dates=get_field(n,'deadline-receipt-tender-date-lot')
    if dates is None: deadline=None
    else:
        xs=re.findall(r'\d{4}-\d{2}-\d{2}',flatten(dates))
        deadline=max(xs) if xs else None
    return {
      'id':number,'notice_number':number,'kind':kind,'notice_type':kind_val,
      'title':flatten(get_field(n,'notice-title','title-proc','title-lot')) or number,
      'buyer':flatten(get_field(n,'buyer-name')),'country':country,
      'cpvs':cpvs,'published':flatten(get_field(n,'publication-date'))[:10],
      'deadline':deadline,'amount':value,'currency':currency,
      'amount_semantics': ('estimated_procedure_value' if n.get('estimated-value-proc') is not None else 'published_notice_total_unverified') if kind=='competition' else 'aggregated_award_notice_value',
      'winner':flatten(get_field(n,'winner-name')) if kind=='award' else None,
      'received_bids':parse_bid_count(get_field(n,'received-submissions-type-val')) if kind=='award' else None,
      'xml_url':xml_link(n) or f'https://ted.europa.eu/en/notice/{number}/xml',
      'url':f'https://ted.europa.eu/en/notice/{number}',
      'bid_guarantee':'unknown','performance_guarantee':'unknown','participation_fee':'unknown',
      'company_eligibility':'unknown','qualification_check':'unknown','user_estimated_margin_pct':None,
      'guarantee_evidence':None,'contract_duration_days':None,'origin':'TED',
      **search_snapshot(n),
    }


def parse_bid_count(raw:Any)->int|None:
    # The submissions data may contain multiple *types* or lots; do not sum blindly.
    if isinstance(raw,(int,float)) and float(raw).is_integer() and raw>=0:return int(raw)
    if isinstance(raw,str) and raw.strip().isdigit():return int(raw.strip())
    return None


def guarantee_from_eforms_xml(blob:bytes) -> dict:
    """Read BT-751 per LOT. No fields/missing indicators => unknown.
    Only cbc:GuaranteeTypeCode with listName=tender-guarantee-required
    within a Lot's TenderingTerms/RequiredFinancialGuarantee is accepted.
    """
    if len(blob)>8_000_000: raise ValueError('XML exceeds 8 MB')
    root=SafeET.fromstring(blob)
    lot_values=[]
    for lot in root.iter():
        if lot.tag.rsplit('}',1)[-1]!='ProcurementProjectLot':continue
        lot_id=None; indicators=[]; descriptions=[]; criteria=[]
        for child in lot:
            local=child.tag.rsplit('}',1)[-1]
            if local=='ID': lot_id=(child.text or '').strip()
            if local!='TenderingTerms':continue
            for terms in child:
                if terms.tag.rsplit('}',1)[-1]=='AwardingTerms':
                    for criterion in terms.iter():
                        if criterion.tag.rsplit('}',1)[-1]!='SubordinateAwardingCriterion':continue
                        typ=None;name=None;desc=None;weights=[]
                        for item in criterion:
                            tag=item.tag.rsplit('}',1)[-1]
                            if tag=='AwardingCriterionTypeCode':typ=(item.text or '').strip()
                            if tag=='Name' and not name:name=(item.text or '').strip()
                            if tag=='Description' and not desc:desc=(item.text or '').strip()[:350]
                        for par in criterion.iter():
                            if par.tag.rsplit('}',1)[-1]!='AwardCriterionParameter':continue
                            code=next(((c.text or '').strip() for c in par if c.tag.rsplit('}',1)[-1]=='ParameterCode'),None)
                            code_type=next((c.attrib.get('listName') for c in par if c.tag.rsplit('}',1)[-1]=='ParameterCode'),None)
                            val=next(((c.text or '').strip() for c in par if c.tag.rsplit('}',1)[-1]=='ParameterNumeric'),None)
                            if code_type=='number-weight' and val:
                                weights.append({'type':code,'value':val})
                        if typ in ('price','quality','cost'):
                            criteria.append({'type':typ,'name':name,'description':desc,'weights':weights})
                
                if terms.tag.rsplit('}',1)[-1]!='RequiredFinancialGuarantee':continue
                for el in terms:
                    t=el.tag.rsplit('}',1)[-1]
                    if t=='GuaranteeTypeCode' and el.attrib.get('listName')=='tender-guarantee-required':
                        if (el.text or '').strip().lower() in ('true','false'):
                            indicators.append((el.text or '').strip().lower())
                    if t=='Description' and el.text:descriptions.append(el.text.strip()[:500])
        if indicators:
            status='required' if 'true' in indicators else 'not_required'
        else:status='unknown'
        lot_values.append({'lot':lot_id,'value':status,'description':descriptions[0] if descriptions else None,
                           'award_criteria':criteria})
    if not lot_values or any(x['value']=='unknown' for x in lot_values): state='unknown'
    elif any(x['value']=='required' for x in lot_values): state='required'
    else: state='not_required'
    return {'value':state,'lots':lot_values,'source':'eForms BT-751 / BT-539'}


def enrich_guarantee(item:dict,session:requests.Session|None=None)->dict:
    url=item.get('xml_url')
    if not url or not safe_ted_url(url):
        return {'value':'unknown','lots':[],'error':'XML URL unavailable / not allowlisted'}
    sess=session or requests.Session()
    try:
        r=sess.get(url,timeout=(8,30),stream=True,allow_redirects=False,headers={'Accept':'application/xml,text/xml'})
        r.raise_for_status()
        if 300<=r.status_code<400: raise ValueError('Redirect not followed for safety')
        body=bytearray()
        for chunk in r.iter_content(65536):
            body.extend(chunk)
            if len(body)>8_000_000:raise ValueError('XML exceeds 8 MB')
        return guarantee_from_eforms_xml(bytes(body))
    except (requests.RequestException,ValueError,SafeET.ParseError) as e:
        return {'value':'unknown','lots':[],'error':str(e)[:250]}
