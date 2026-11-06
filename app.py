#!/usr/bin/env python3
"""TenderCore Europe MVP - local single-user API. Do not expose on public networks."""
from __future__ import annotations
import csv
import io
import json
import logging
import re
import sqlite3
import threading
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone, date
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field

from tax_engine import COUNTRIES, country_data, scenario
from tax_v04 import (TAX_PROFILE_DEFAULT, validate_tax_profile, assess_transaction, calculate_vat_cashflow)
from ted_client import TEDSourceError, fetch_notices, enrich_guarantee
from ted_details import fetch_eforms_details, update_from_details

ROOT=Path(__file__).resolve().parent
DB=ROOT/'data'/'tendercore_eu.sqlite3'
LOG=logging.getLogger('tendercore_eu')
SYNC_LOCK=threading.Lock()
SYNC={'running':False,'last_started':None,'last_finished':None,'error':None,'sources':[], 'success':False}
PROFILE_DEFAULT={
 'name':'My company', 'home_country':'NON_EU','countries':list(COUNTRIES),
 'cpv_prefixes':[], 'keywords':[], 'excluded_keywords':[],
 'min_budget':None,'max_budget':None,'budget_currency':'EUR','min_days_to_deadline':4,
 'require_no_bid_guarantee':True,'require_no_performance_guarantee':True,
 'require_no_participation_fee':True,'max_contract_days':None,
 'min_margin_pct':12, 'available_cash':0, 'capital_currency':'EUR',
 'estimated_cost_ratio_pct':80, 'expected_advance_pct':0, 'company_turnover':None,
 'required_languages':['en'],'has_local_entity':False,
 'lookback_days':45, 'fetch_limit':80, 'xml_enrich_limit':30,
}

def iso_now(): return datetime.now(timezone.utc).isoformat(timespec='seconds')

def init_db(db:sqlite3.Connection):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS notices(
     id TEXT PRIMARY KEY, kind TEXT NOT NULL, country TEXT, published TEXT,
     payload TEXT NOT NULL, last_seen TEXT NOT NULL, favorite INTEGER DEFAULT 0,
     note TEXT DEFAULT '', evidence_url TEXT DEFAULT ''
    );
    CREATE INDEX IF NOT EXISTS idx_notices_kind_country ON notices(kind,country);
    CREATE TABLE IF NOT EXISTS prefs(key TEXT PRIMARY KEY,value TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS bid_history(
     id INTEGER PRIMARY KEY AUTOINCREMENT,notice_id TEXT, country TEXT,cpv TEXT,
     currency TEXT, offered_amount REAL, reference_budget REAL,
     status TEXT NOT NULL CHECK(status IN ('submitted','won','lost','cancelled')),
     dated TEXT NOT NULL
    );
    ''')
    if not db.execute("SELECT 1 FROM prefs WHERE key='profile'").fetchone():
        db.execute("INSERT INTO prefs(key,value) VALUES(?,?)",('profile',json.dumps(PROFILE_DEFAULT)))
    if not db.execute("SELECT 1 FROM prefs WHERE key='tax_profile'").fetchone():
        db.execute("INSERT INTO prefs(key,value) VALUES(?,?)",('tax_profile',json.dumps(TAX_PROFILE_DEFAULT)))

@contextmanager
def db_conn():
    DB.parent.mkdir(parents=True,exist_ok=True)
    conn=sqlite3.connect(DB,timeout=25)
    # The local tax profile may include registration identifiers. Restrict DB access.
    try:
        DB.chmod(0o600)
    except OSError:
        LOG.warning('Could not restrict local database permissions')
    conn.row_factory=sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    init_db(conn)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:conn.close()


def get_profile():
    with db_conn() as db:
        v=db.execute("SELECT value FROM prefs WHERE key='profile'").fetchone()
    return {**PROFILE_DEFAULT,**json.loads(v[0])} if v else PROFILE_DEFAULT.copy()


def validate_profile(v: dict)->dict:
    if not isinstance(v,dict): raise ValueError('Profile must be a JSON object')
    allowed=set(PROFILE_DEFAULT)
    if set(v)-allowed: raise ValueError('Unknown profile keys: '+', '.join(sorted(set(v)-allowed)))
    p={**get_profile(),**v}
    p['countries']=list(dict.fromkeys(c for c in p['countries'] if isinstance(c,str) and c in COUNTRIES))
    if not p['countries']: raise ValueError('Select at least one EU country')
    for key in ('home_country',):
        if p[key] not in COUNTRIES and p[key]!='NON_EU': raise ValueError('Invalid '+key)
    for field in ('keywords','excluded_keywords','required_languages','cpv_prefixes'):
        if not isinstance(p[field],list) or len(p[field])>30:raise ValueError(f'{field} must be a list of <= 30 items')
        p[field]=[str(x).strip()[:100] for x in p[field] if str(x).strip()]
    if any(not re.fullmatch(r'\d{2,8}',v) for v in p['cpv_prefixes']): raise ValueError('CPV prefix must have 2-8 digits')
    for key in ('require_no_bid_guarantee','require_no_performance_guarantee','require_no_participation_fee','has_local_entity'):
        if not isinstance(p[key],bool):raise ValueError('Invalid '+key)
    for key,low,high in [('min_days_to_deadline',0,365),('lookback_days',1,730),('fetch_limit',1,250),('xml_enrich_limit',0,250)]:
        if type(p[key]) is not int or not low<=p[key]<=high: raise ValueError('Invalid '+key)
    for key in ('min_budget','max_budget','max_contract_days','company_turnover'):
        if p[key] in (None,''):p[key]=None;continue
        if isinstance(p[key],bool) or not isinstance(p[key],(int,float)) or not 0<=p[key]<=1e14:raise ValueError('Invalid '+key)
    if p['min_budget'] is not None and p['max_budget'] is not None and p['min_budget']>p['max_budget']:
        raise ValueError('Minimum budget exceeds maximum budget')
    for key in ('available_cash','min_margin_pct','estimated_cost_ratio_pct','expected_advance_pct'):
        if isinstance(p[key],bool) or not isinstance(p[key],(int,float)) or not 0<=p[key]<=1e12:raise ValueError('Invalid '+key)
    if p['estimated_cost_ratio_pct']>100 or p['expected_advance_pct']>100 or p['min_margin_pct']>100:
        raise ValueError('Percent must be in 0–100')
    if p['budget_currency'] not in ('EUR','PLN','CZK','DKK','HUF','RON','SEK','BGN'):
        raise ValueError('Invalid budget currency')
    if p['capital_currency'] not in ('EUR','PLN','CZK','DKK','HUF','RON','SEK','BGN'):
        raise ValueError('Invalid capital currency')
    p['name']=str(p['name'])[:120]
    return p


def status_for(item:dict,p:dict)->tuple[str,list[str]]:
    reasons=[]
    country=item.get('country')
    if country not in p['countries']:
        return 'EXCLUDED',['country_not_selected']
    if item.get('kind')=='award':return 'AWARDED',[]
    text=(item.get('title','')+' '+item.get('buyer','')).casefold()
    if p['keywords'] and not any(x.casefold() in text for x in p['keywords']):
        return 'EXCLUDED',['keyword_not_matched']
    if any(x.casefold() in text for x in p['excluded_keywords']):
        return 'EXCLUDED',['excluded_keyword']
    cps=item.get('cpvs') or []
    if p['cpv_prefixes'] and not any(c.startswith(prefix) for c in cps for prefix in p['cpv_prefixes']):
        return 'EXCLUDED',['cpv_not_matched']
    amount=item.get('amount')
    if amount is not None and (p['min_budget'] is not None or p['max_budget'] is not None) and item.get('currency')!=p['budget_currency']:
        reasons.append('budget_currency_not_comparable')
    elif amount is not None:
        if p['min_budget'] is not None and amount < p['min_budget']:return 'EXCLUDED',['budget_below_minimum']
        if p['max_budget'] is not None and amount > p['max_budget']:return 'EXCLUDED',['budget_above_maximum']
    else:reasons.append('budget_missing')
    if item.get('deadline'):
        try:
            remaining=(date.fromisoformat(item['deadline'][:10])-date.today()).days
            if remaining<0:return 'EXPIRED',['deadline_passed']
            if remaining<p['min_days_to_deadline']:return 'EXCLUDED',['deadline_too_close']
        except ValueError:reasons.append('deadline_unreadable')
    else:reasons.append('deadline_unknown')
    for check in ('company_eligibility','qualification_check'):
        val=item.get(check,'unknown')
        if val=='ineligible':return 'EXCLUDED',[check+'_failed']
        if val!='eligible':reasons.append(check+'_unverified')
    if p.get('home_country')=='NON_EU':
        reasons.append('non_eu_supplier_legal_check_required')
    for flag,field in [('require_no_bid_guarantee','bid_guarantee'),('require_no_performance_guarantee','performance_guarantee'),('require_no_participation_fee','participation_fee')]:
        condition=item.get(field,'unknown')
        if p[flag] and condition=='required':return 'EXCLUDED',[field+'_required']
        if p[flag] and condition!='not_required':reasons.append(field+'_unknown')
    if p.get('min_margin_pct', 0) > 0:
        user_margin=item.get('user_estimated_margin_pct')
        if user_margin is None:reasons.append('tender_margin_not_calculated')
        elif user_margin < p['min_margin_pct']:return 'EXCLUDED',['estimated_margin_below_target']
    if p['max_contract_days'] is not None:
        x=item.get('contract_duration_days')
        if x is None:reasons.append('contract_duration_unknown')
        elif x>p['max_contract_days']:return 'EXCLUDED',['contract_too_long']
    # We do NOT elevate to READY if missing budget, deadline, or mandatory terms.
    return ('REVIEW',reasons) if reasons else ('PRELIMINARY',[])


def sample_items():
    # Explicit synthetic example rows. NEVER stored as live data.
    return [
     {'id':'demo-1','notice_number':'DEMO-001','title':'Industrial control panels and automation systems',
      'buyer':'Example Water Utility','country':'DE','cpvs':['31682210','42961000'],
      'kind':'competition','notice_type':'cn-standard','amount':350000,'currency':'EUR',
      'published':date.today().isoformat(),'deadline':(date.today()+__import__('datetime').timedelta(days=19)).isoformat(),
      'bid_guarantee':'not_required','performance_guarantee':'unknown','participation_fee':'unknown',
      'url':'','xml_url':None,'favorite':False,'note':'','guarantee_evidence':'DEMO only', 'demo':True},
     {'id':'demo-2','notice_number':'DEMO-002','title':'Technical documentation and design for pumping station',
      'buyer':'Example Infrastructure Agency','country':'FR','cpvs':['71320000'],
      'kind':'competition','notice_type':'cn-standard','amount':870000,'currency':'EUR',
      'published':date.today().isoformat(),'deadline':(date.today()+__import__('datetime').timedelta(days=26)).isoformat(),
      'bid_guarantee':'required','performance_guarantee':'unknown','participation_fee':'unknown',
      'url':'','xml_url':None,'favorite':False,'note':'','guarantee_evidence':'DEMO only','demo':True},
     {'id':'demo-3','notice_number':'DEMO-003','title':'Contract award: industrial equipment servicing',
      'buyer':'Example Municipal Buyer','country':'NL','cpvs':['50530000'],
      'kind':'award','notice_type':'can-standard','amount':210000,'currency':'EUR',
      'published':date.today().isoformat(),'deadline':None,'winner':'Example Company BV',
      'received_bids':4,'bid_guarantee':'unknown','performance_guarantee':'unknown','participation_fee':'unknown',
      'url':'','xml_url':None,'favorite':False,'note':'','demo':True},
    ]


def all_items(demo:bool=False)->list[dict]:
    if demo:return sample_items()
    with db_conn() as db:
        rows=db.execute('SELECT * FROM notices ORDER BY published DESC,id DESC').fetchall()
    out=[]
    for row in rows:
        item=json.loads(row['payload']);item.update(favorite=bool(row['favorite']),note=row['note'],
                                  evidence_url=row['evidence_url'],demo=False,last_seen=row['last_seen'])
        out.append(item)
    return out


def finance_indicator(item:dict,p:dict)->dict:
    """Indicative finance coverage, not bidding success probability."""
    amount=item.get('amount')
    if amount is None or item.get('kind')=='award':
        return {'state':'unknown','reason':'no_comparable_budget'}
    if item.get('currency')!=p['capital_currency']:
        return {'state':'unknown','reason':'currency_mismatch','capital_currency':p['capital_currency']}
    if not p['available_cash']:
        return {'state':'unknown','reason':'available_cash_not_set'}
    cost_est=max(0,float(amount)*(float(p['estimated_cost_ratio_pct'])-float(p['expected_advance_pct']))/100)
    if not cost_est:return {'state':'unknown','reason':'estimated_financing_need_zero'}
    ratio=p['available_cash']/cost_est
    return {'state':'covered' if ratio>=1 else 'gap','coverage_pct':round(ratio*100,1),
            'estimated_financing_need':round(cost_est,2),'capital_currency':p['capital_currency'],
            'basis':'user_entered_cost_ratio_and_advance_pct; not a win probability'}


def enriched_items(demo:bool=False):
    profile=get_profile()
    res=[]
    for item in all_items(demo):
        state,reasons=status_for(item,profile)
        res.append({**item,'eligibility':state,'reasons':reasons,'finance':finance_indicator(item,profile)})
    return res


def _do_sync():
    results=[]; errors=[]
    try:
        profile=get_profile()
        for kind in ('competition','award'):
            try:
                data=fetch_notices(profile,kind,profile['lookback_days'] if kind=='competition' else max(90,profile['lookback_days']),profile['fetch_limit'])
                items=[r for r in data['items'] if r.get('id') and not r.get('invalid')]
                for item in items[:profile['xml_enrich_limit'] if kind=='competition' else min(8,profile['xml_enrich_limit'])]:
                    details=fetch_eforms_details(item.get('xml_url'))
                    item.update(update_from_details(item,details))
                with db_conn() as db:
                    for item in items:
                        existing=db.execute('SELECT payload FROM notices WHERE id=?',(item['id'],)).fetchone()
                        if existing:
                            prior=json.loads(existing['payload'])
                            for attr in ('performance_guarantee','participation_fee','company_eligibility','qualification_check','user_estimated_margin_pct'):
                                if (attr=='user_estimated_margin_pct' and prior.get(attr) is not None) or (attr!='user_estimated_margin_pct' and prior.get(attr) in ('required','not_required','eligible','ineligible')):
                                    item[attr]=prior[attr]
                            if item.get('details_fetch_status')!='parsed':
                                for attr in ('bid_guarantee','guarantee_evidence','guarantee_lots','award_criteria_lots',
                                             'contract_duration_days','lots_detail','details_coverage','documents_urls',
                                             'details_checked_at','details_fetch_status'):
                                    if attr in prior and prior.get('details_fetch_status')=='parsed':
                                        item[attr]=prior[attr]
                        db.execute('''INSERT INTO notices(id,kind,country,published,payload,last_seen)
                          VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                          kind=excluded.kind,country=excluded.country,published=excluded.published,
                          payload=excluded.payload,last_seen=excluded.last_seen''',
                          (item['id'],kind,item.get('country'),item.get('published'),json.dumps(item,ensure_ascii=False),iso_now()))
                results.append({'kind':kind,'stored':len(items),'reported_total':data['reported_total'],
                                'limit':data['limit'],'truncated':isinstance(data['reported_total'],int) and data['reported_total']>len(items),
                                'query':data['query']})
            except TEDSourceError as e:
                errors.append(str(e))
                LOG.warning('TED source error: %s',e)
    except Exception as e:
        LOG.exception('Unexpected sync error')
        errors.append(f'{type(e).__name__}: {str(e)[:200]}')
    finally:
        SYNC.update(running=False,last_finished=iso_now(),error='; '.join(errors) if errors else None,
                    success=bool(results),sources=results)
        SYNC_LOCK.release()


def start_sync():
    if not SYNC_LOCK.acquire(blocking=False): return False
    SYNC.update(running=True,last_started=iso_now(),error=None,success=False,sources=[])
    threading.Thread(target=_do_sync,daemon=True,name='ted-sync').start()
    return True

@asynccontextmanager
async def lifespan(app:FastAPI):
    with db_conn():pass
    yield

app=FastAPI(title='TenderCore Europe',version='0.1.0-alpha',lifespan=lifespan)
# Prevent DNS rebinding against this unauthenticated local application.
app.add_middleware(TrustedHostMiddleware, allowed_hosts=['localhost', '127.0.0.1', 'testserver'])
app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')

@app.middleware('http')
async def local_write_guard(request:Request,call_next):
    # Local single-user app: block cross-origin browser POSTs to prevent drive-by changes.
    if request.method in ('POST','PUT','PATCH','DELETE'):
        origin=request.headers.get('origin')
        host=request.headers.get('host','')
        if origin:
            o=urlparse(origin)
            if o.netloc!=host or o.scheme not in ('http','https'):
                from fastapi.responses import JSONResponse
                return JSONResponse({'detail':'Cross-origin writes disabled'},status_code=403)
    return await call_next(request)

@app.get('/')
def root():return FileResponse(ROOT/'static'/'index.html')

@app.get('/api/health')
def health():return {'ok':True,'version':'0.1.0-alpha','source':'TED Search API v3','time':iso_now()}

@app.get('/api/countries')
def countries():return {'countries':country_data()}

@app.get('/api/profile')
def profile():return get_profile()

class ProfileUpdate(BaseModel):
    values:dict[str,Any]

@app.put('/api/profile')
def update_profile(body:ProfileUpdate):
    try:val=validate_profile(body.values)
    except ValueError as e: raise HTTPException(status_code=422,detail=str(e))
    with db_conn() as db:
        db.execute("UPDATE prefs SET value=? WHERE key='profile'",(json.dumps(val,ensure_ascii=False),))
    return val

def get_tax_profile() -> dict:
    with db_conn() as db:
        row = db.execute("SELECT value FROM prefs WHERE key='tax_profile'").fetchone()
    return {**TAX_PROFILE_DEFAULT, **(json.loads(row['value']) if row else {})}

@app.get('/api/tax/profile')
def tax_profile():
    return get_tax_profile()

class TaxProfileUpdate(BaseModel):
    values: dict[str, Any]

@app.put('/api/tax/profile')
def save_tax_profile(body: TaxProfileUpdate):
    old = get_tax_profile()
    try:
        updated = validate_tax_profile(body.values, old)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    with db_conn() as db:
        db.execute("INSERT INTO prefs(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                   ('tax_profile', json.dumps(updated, ensure_ascii=False)))
    return updated

class TaxAssessmentRequest(BaseModel):
    values: dict[str, Any]

@app.post('/api/tax/assess')
def tax_assess(body: TaxAssessmentRequest):
    try:
        return assess_transaction(get_tax_profile(), body.values)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

@app.post('/api/tax/cashflow')
def tax_cashflow(body: TaxAssessmentRequest):
    try:
        return calculate_vat_cashflow(body.values, get_tax_profile())
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

@app.post('/api/sync',status_code=202)
def sync():
    if not start_sync():raise HTTPException(status_code=409,detail='Sync already running')
    return {'accepted':True}

@app.get('/api/sync-status')
def sync_status():return dict(SYNC)


# Optional repair pass for previously synced notices. Uses existing records,
# never overwrites manual checks, and limits requests per pass.
ENRICH={'running':False,'checked':0,'updated':0,'failed':0,'total':0,'error':None,'last_finished':None}

def _enrich_pending(limit:int=20):
    try:
        with db_conn() as db:
            rows=db.execute("SELECT id,payload FROM notices WHERE kind='competition' ORDER BY last_seen DESC").fetchall()
        pending=[]
        for row in rows:
            item=json.loads(row['payload'])
            if item.get('details_fetch_status') not in ('parsed','failed') and item.get('xml_url'):
                pending.append((row['id'],item))
        ENRICH['total']=min(limit,len(pending))
        for id,item in pending[:limit]:
            details=fetch_eforms_details(item.get('xml_url'))
            updated=update_from_details(item,details)
            with db_conn() as db:
                row=db.execute('SELECT payload FROM notices WHERE id=?',(id,)).fetchone()
                if row:
                    current=json.loads(row['payload'])
                    # Do not replace manual review values changed during this network request.
                    for field in ('bid_guarantee','guarantee_evidence','guarantee_lots','award_criteria_lots',
                                  'contract_duration_days','lots_detail','details_coverage','documents_urls',
                                  'deadline','details_checked_at','details_fetch_status','xml_error'):
                        if field in updated:current[field]=updated[field]
                    db.execute('UPDATE notices SET payload=? WHERE id=?',
                        (json.dumps(current,ensure_ascii=False),id))
            ENRICH['checked']+=1
            if details.get('error'):ENRICH['failed']+=1
            else:ENRICH['updated']+=1
            __import__('time').sleep(0.2)
    except Exception as exc:
        ENRICH['error']=f'{type(exc).__name__}: {str(exc)[:220]}'
    finally:
        ENRICH['running']=False
        ENRICH['last_finished']=iso_now()
        SYNC_LOCK.release()

def start_enrichment():
    if not SYNC_LOCK.acquire(blocking=False):return False
    ENRICH.update(running=True,checked=0,updated=0,failed=0,total=0,error=None)
    threading.Thread(target=_enrich_pending,daemon=True,name='ted-detail-repair').start()
    return True

@app.post('/api/enrich',status_code=202)
def enrich_pending():
    if not start_enrichment():raise HTTPException(409,'TED operation already running')
    return {'accepted':True}

@app.get('/api/enrich-status')
def enrich_status():return dict(ENRICH)

@app.get('/api/tenders')
def tenders(kind:str='competition',state:str='all',country:str='all',q:str='',favorites:bool=False,
            sort:str='published',demo:bool=False):
    if kind not in ('competition','award','all'):raise HTTPException(422,'Invalid kind')
    if len(q)>150:raise HTTPException(422,'Query too long')
    xs=enriched_items(demo)
    if kind!='all':xs=[x for x in xs if x['kind']==kind]
    if state!='all':xs=[x for x in xs if x['eligibility']==state]
    if country!='all':xs=[x for x in xs if x['country']==country]
    if q: xs=[x for x in xs if q.casefold() in (x.get('title','')+' '+x.get('buyer','')+' '+','.join(x.get('cpvs',[]))).casefold()]
    if favorites:xs=[x for x in xs if x.get('favorite')]
    if sort=='amount':xs.sort(key=lambda x:x.get('amount') or -1,reverse=True)
    elif sort=='deadline':xs.sort(key=lambda x:x.get('deadline') or '9999')
    else:xs.sort(key=lambda x:x.get('published') or '',reverse=True)
    return {'items':xs,'total':len(xs),'demo':demo,'source_limit_warning':'TED API uses a capped sample per sync, not exhaustive coverage'}

class ManualUpdate(BaseModel):
    note:str=Field(default='',max_length=2500)
    favorite:bool=False
    performance_guarantee:str='unknown'
    participation_fee:str='unknown'
    company_eligibility:str='unknown'
    qualification_check:str='unknown'
    user_estimated_margin_pct:float|None=Field(default=None,ge=0,le=100)
    evidence_url:str=''

@app.put('/api/tenders/{notice_id}/review')
def review(notice_id:str,body:ManualUpdate):
    if any(x not in ('unknown','required','not_required') for x in (body.performance_guarantee,body.participation_fee)):
        raise HTTPException(422,'Invalid guarantee status')
    if any(x not in ('unknown','eligible','ineligible') for x in (body.company_eligibility,body.qualification_check)):
        raise HTTPException(422,'Invalid eligibility status')
    if body.evidence_url:
        p=urlparse(body.evidence_url)
        if p.scheme!='https' or not p.netloc:raise HTTPException(422,'Evidence must be HTTPS URL')
    with db_conn() as db:
        old=db.execute('SELECT payload FROM notices WHERE id=?',(notice_id,)).fetchone()
        if not old:raise HTTPException(404,'Tender not found')
        item=json.loads(old[0])
        item['performance_guarantee']=body.performance_guarantee
        item['participation_fee']=body.participation_fee
        item['company_eligibility']=body.company_eligibility
        item['qualification_check']=body.qualification_check
        item['user_estimated_margin_pct']=body.user_estimated_margin_pct
        db.execute('UPDATE notices SET payload=?,note=?,favorite=?,evidence_url=? WHERE id=?',
                   (json.dumps(item,ensure_ascii=False),body.note,int(body.favorite),body.evidence_url,notice_id))
    return {'ok':True,'item':item}

@app.post('/api/tenders/{notice_id}/verify-bid-guarantee')
def verify_bid_guarantee(notice_id:str):
    with db_conn() as db:
        old=db.execute('SELECT payload FROM notices WHERE id=?',(notice_id,)).fetchone()
        if not old:raise HTTPException(404,'Tender not found')
        item=json.loads(old['payload'])
    if item['kind']!='competition':raise HTTPException(400,'Not a competition notice')
    report=fetch_eforms_details(item.get('xml_url'))
    item=update_from_details(item,report)
    with db_conn() as db:
        db.execute('UPDATE notices SET payload=? WHERE id=?',(json.dumps(item,ensure_ascii=False),notice_id))
    return report

class ScenarioRequest(BaseModel):
    values:dict[str,Any]
@app.post('/api/economics')
def economics(body:ScenarioRequest):
    try:return scenario(body.values)
    except ValueError as e:raise HTTPException(422,str(e))

class BidHistoryInput(BaseModel):
    notice_id:str=Field(default='',max_length=120)
    country:str
    cpv:str=Field(default='',max_length=8)
    currency:str=Field(default='EUR',max_length=3)
    offered_amount:float=Field(ge=0,le=1e14)
    reference_budget:float|None=Field(default=None,ge=0,le=1e14)
    status:str

@app.post('/api/bids')
def add_bid(body:BidHistoryInput):
    if body.country not in COUNTRIES or body.status not in ('submitted','won','lost','cancelled'):
        raise HTTPException(422,'Invalid country or status')
    if body.cpv and not re.fullmatch(r'\d{2,8}',body.cpv):raise HTTPException(422,'Invalid CPV')
    with db_conn() as db:
        cur=db.execute('''INSERT INTO bid_history(notice_id,country,cpv,currency,offered_amount,reference_budget,status,dated)
          VALUES(?,?,?,?,?,?,?,?)''',(body.notice_id,body.country,body.cpv,body.currency,body.offered_amount,body.reference_budget,body.status,iso_now()))
        row_id=cur.lastrowid
    return {'ok':True,'id':row_id}

@app.get('/api/analytics')
def analytics(demo:bool=False):
    xs=enriched_items(demo)
    competitions=[x for x in xs if x['kind']=='competition']
    awards=[x for x in xs if x['kind']=='award']
    from collections import Counter
    award_criteria_types=Counter(c['type'] for x in awards for l in x.get('award_criteria_lots',[]) for c in l.get('criteria',[]))
    counts={s:sum(x['eligibility']==s for x in competitions) for s in ('PRELIMINARY','REVIEW','EXCLUDED','EXPIRED')}
    from collections import Counter, defaultdict
    countries=Counter(x.get('country') or '??' for x in competitions)
    sectors=Counter(next((c[:2] for c in (x.get('cpvs') or []) if len(c)>=2),'??') for x in competitions)
    award_values=defaultdict(lambda:{'count':0,'value':0.0,'with_value':0,'with_bids':0,'bids_sum':0.0})
    for x in awards:
        cur=x.get('currency') or 'UNKNOWN'
        a=award_values[cur];a['count']+=1
        if x.get('amount') is not None:a['value']+=x['amount'];a['with_value']+=1
        if x.get('received_bids') is not None:a['with_bids']+=1;a['bids_sum']+=x['received_bids']
    with db_conn() as db:
        h=db.execute('SELECT country,cpv,offered_amount,reference_budget,status FROM bid_history').fetchall()
    decided=[r for r in h if r['status'] in ('won','lost')]
    won=sum(r['status']=='won' for r in decided)
    return {'demo':demo,'sample_notice_count':len(xs),'competition_count':len(competitions),'award_count':len(awards),
      'counts':counts,'by_country':dict(countries),'by_cpv_division':dict(sectors),
      'published_award_criteria_by_type':dict(award_criteria_types),
      'awards_by_currency':{k:{**v,'average_bid_count':round(v['bids_sum']/v['with_bids'],2) if v['with_bids'] else None} for k,v in award_values.items()},
      'personal_bids':{'decided':len(decided),'won':won,'historical_win_share':round(won/len(decided)*100,1) if decided else None},
      'limitations':['This is a capped sample of notice records, not all tenders in the EU.',
        'Notice-level awarded amounts may cover multiple lots; figures are kept per original currency, not converted.',
        'Personal past success is not a prediction for a specific tender. Budget alone cannot produce reliable winning odds.']}

@app.get('/api/export')
def export(kind:str='competition',demo:bool=False):
    if kind not in ('competition','award','all'):raise HTTPException(422,'Invalid kind')
    rows=[x for x in enriched_items(demo) if kind=='all' or x.get('kind')==kind]
    keys=['notice_number','kind','title','buyer','country','cpvs','amount','currency','deadline',
          'bid_guarantee','performance_guarantee','participation_fee','eligibility','reasons','winner','url']
    buff=io.StringIO();writer=csv.writer(buff);writer.writerow(keys)
    def safe(v):
        if isinstance(v,list):v='; '.join(map(str,v))
        s='' if v is None else str(v)
        if s.lstrip().startswith(('=','+','-','@')):s="'"+s
        return s
    for r in rows:writer.writerow([safe(r.get(k)) for k in keys])
    content='\ufeff'+buff.getvalue()
    return StreamingResponse(iter([content]),media_type='text/csv; charset=utf-8',
                             headers={'Content-Disposition':'attachment; filename="tendercore_europe.csv"'})

if __name__=='__main__':
    uvicorn.run('app:app',host='127.0.0.1',port=8766,reload=False)
