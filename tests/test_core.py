import unittest
from unittest.mock import patch
from pathlib import Path
import tempfile
import json
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app as module
from tax_engine import COUNTRIES,country_data,scenario
from ted_client import (guarantee_from_eforms_xml,build_query,request_payload,normalize,
                        safe_ted_url,parse_bid_count,TEDSourceError,fetch_notices)

XML_HEADER=b'<Root xmlns:cac="urn:cac" xmlns:cbc="urn:cbc">'
XML_FOOTER=b'</Root>'
def lot(value, id='LOT-0001'):
    code=(f'<cac:RequiredFinancialGuarantee><cbc:GuaranteeTypeCode listName="tender-guarantee-required">{value}</cbc:GuaranteeTypeCode></cac:RequiredFinancialGuarantee>' if value is not None else '')
    return (f'<cac:ProcurementProjectLot><cbc:ID>{id}</cbc:ID><cac:TenderingTerms>{code}</cac:TenderingTerms></cac:ProcurementProjectLot>').encode()

class CoreTests(unittest.TestCase):
    def test_eu_27_and_snapshot(self):
        self.assertEqual(len(COUNTRIES), 27)
        self.assertEqual(len(country_data()), 27)
        self.assertEqual(dict((x['code'],x['standard_vat']) for x in country_data())['RO'],21)
        self.assertFalse(any(x['cross_border_auto_determination'] for x in country_data()))

    def test_vat_unknown_no_automatic_assumption(self):
        r=scenario({'buyer_country':'DE','bid_amount':100000,'direct_costs':72000})
        self.assertIsNone(r['vat_amount_display_only'])
        self.assertEqual(r['margin_before_income_taxes'],28000)

    def test_margin_and_cash_after_available_capital(self):
        r=scenario({'buyer_country':'FR','bid_amount':100000,'direct_costs':72000,'indirect_costs':6000,
                    'financing_costs':2000,'risk_reserve':3000,'required_cash':5000,
                    'available_cash':20000,'expected_advance':15000,'vat_treatment':'domestic_standard'})
        self.assertEqual(r['margin_before_income_taxes'],17000)
        self.assertEqual(r['cash_gap_before_payment'],53000)
        self.assertEqual(r['vat_amount_display_only'],20000)

    def test_invalid_country_and_negative_money(self):
        with self.assertRaises(ValueError): scenario({'buyer_country':'NO'})
        with self.assertRaises(ValueError): scenario({'buyer_country':'DE','direct_costs':-10})

    def test_query_sanitizes_cpv_and_country(self):
        q=build_query({'countries':['DE','FR'], 'cpv_prefixes':['72','71320000','bad'],'keywords':[]},'competition',60)
        self.assertIn('DEU',q)
        self.assertIn('FRA',q)
        self.assertIn('72*',q)
        self.assertNotIn('bad',q)
        self.assertIn('cn-standard',q)
        self.assertNotIn('can-standard',q)

    def test_lot_guarantee_all_false(self):
        v=guarantee_from_eforms_xml(XML_HEADER+lot('false','LOT-A')+lot('false','LOT-B')+XML_FOOTER)
        self.assertEqual(v['value'],'not_required')
        self.assertEqual(len(v['lots']),2)

    def test_lot_any_required(self):
        v=guarantee_from_eforms_xml(XML_HEADER+lot('false','LOT-A')+lot('true','LOT-B')+XML_FOOTER)
        self.assertEqual(v['value'],'required')

    def test_lot_missing_is_unknown(self):
        v=guarantee_from_eforms_xml(XML_HEADER+lot('false','LOT-A')+lot(None,'LOT-B')+XML_FOOTER)
        self.assertEqual(v['value'],'unknown')

    def test_award_criteria_parse_from_eforms_xml(self):
        crit=b'''<cac:AwardingTerms><cac:AwardingCriterion>
            <cac:SubordinateAwardingCriterion>
            <cbc:AwardingCriterionTypeCode>price</cbc:AwardingCriterionTypeCode>
            <cbc:Name>Price criterion</cbc:Name>
            </cac:SubordinateAwardingCriterion></cac:AwardingCriterion></cac:AwardingTerms>'''
        xml=XML_HEADER+b'<cac:ProcurementProjectLot><cbc:ID>LOT-0001</cbc:ID><cac:TenderingTerms>'+crit+b'</cac:TenderingTerms></cac:ProcurementProjectLot>'+XML_FOOTER
        result=guarantee_from_eforms_xml(xml)
        self.assertEqual(result['value'],'unknown')
        self.assertEqual(result['lots'][0]['award_criteria'][0]['type'],'price')

    def test_no_lot_or_dtd_fails_closed(self):
        self.assertEqual(guarantee_from_eforms_xml(XML_HEADER+XML_FOOTER)['value'],'unknown')
        with self.assertRaises(Exception):guarantee_from_eforms_xml(b'<!DOCTYPE root [<!ENTITY x "boom">]><Root/>')

    def test_no_external_url_ssrf(self):
        self.assertFalse(safe_ted_url('https://localhost/something.xml'))
        self.assertFalse(safe_ted_url('https://ted.europa.eu.evil.example/'))
        self.assertFalse(safe_ted_url('http://ted.europa.eu/file.xml'))
        self.assertTrue(safe_ted_url('https://ted.europa.eu/en/notice/1234-2026/xml'))

    def test_normalize_unverified_not_zero(self):
        notice={'publication-number':'12345-2026','notice-title':{'eng':['A project']},'buyer-country':'DEU',
                'total-value':300000,'total-value-cur':'EUR','classification-cpv':['72000000'],
                'deadline-receipt-tender-date-lot':['2026-12-31']}
        v=normalize(notice,'competition')
        self.assertEqual(v['bid_guarantee'],'unknown')
        self.assertEqual(v['country'],'DE')
        self.assertEqual(v['amount'],300000)
        self.assertEqual(v['deadline'],'2026-12-31')

    def test_no_aggregate_bid_counts_without_grain(self):
        self.assertIsNone(parse_bid_count([{'all':3},{'all':8}]))
        self.assertEqual(parse_bid_count('4'),4)

class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.old=module.DB
        module.DB=Path(self.temp.name)/'test.sqlite3'
        with module.db_conn():pass

    def tearDown(self):
        module.DB=self.old
        self.temp.cleanup()

    def test_profile_rules_and_currency_safety(self):
        p=module.get_profile()
        self.assertEqual(p['home_country'],'NON_EU')
        bad={**p,'countries':[]}
        with self.assertRaises(ValueError):module.validate_profile(bad)
        a={'country':'DE','kind':'competition','amount':1000,'currency':'EUR','deadline':'2099-12-31',
           'bid_guarantee':'not_required','performance_guarantee':'unknown','participation_fee':'unknown'}
        state,reasons=module.status_for(a,p)
        self.assertEqual(state,'REVIEW')
        self.assertIn('performance_guarantee_unknown',reasons)
        a['bid_guarantee']='required'
        self.assertEqual(module.status_for(a,p)[0],'EXCLUDED')
        a['bid_guarantee']='not_required';a['performance_guarantee']='not_required';a['participation_fee']='not_required'
        a['company_eligibility']='eligible';a['qualification_check']='eligible';a['user_estimated_margin_pct']=16;p['home_country']='DE'
        self.assertEqual(module.status_for(a,p)[0],'PRELIMINARY')
        a['user_estimated_margin_pct']=8
        self.assertEqual(module.status_for(a,p)[0],'EXCLUDED')
        a['user_estimated_margin_pct']=16
        p['min_budget']=800;a['currency']='PLN'
        state,reasons=module.status_for(a,p)
        self.assertEqual(state,'REVIEW')
        self.assertIn('budget_currency_not_comparable',reasons)

    def test_finance_is_not_a_probability(self):
        p={**module.PROFILE_DEFAULT,'available_cash':5000,'capital_currency':'EUR'}
        f=module.finance_indicator({'kind':'competition','amount':20000,'currency':'EUR'},p)
        self.assertLess(f['coverage_pct'],100)
        self.assertNotIn('win_probability',f)

    def test_no_demo_in_database(self):
        self.assertEqual(len(module.all_items(demo=True)),3)
        self.assertEqual(len(module.all_items(demo=False)),0)

    def test_api_read_and_scenario(self):
        from fastapi.testclient import TestClient
        with TestClient(module.app) as client:
            self.assertEqual(client.get('/api/countries').json()['countries'].__len__(),27)
            self.assertEqual(client.get('/api/analytics').json()['award_count'],0)
            self.assertEqual(client.get('/api/tenders?demo=true').json()['total'],2)
            self.assertEqual(client.get('/api/tenders').json()['total'],0)
            self.assertEqual(client.post('/api/economics',json={'values':{'buyer_country':'ES','bid_amount':500}}).status_code,200)
            self.assertEqual(client.put('/api/profile',json={'values':{'keywords':['automation']}}).status_code,200)
            self.assertEqual(client.get('/api/profile').json()['keywords'],['automation'])
            self.assertEqual(client.get('/api/export?demo=true').status_code,200)

    def test_no_cross_origin_mutations(self):
        from fastapi.testclient import TestClient
        with TestClient(module.app) as client:
            r=client.post('/api/sync',headers={'origin':'https://malicious.example'})
            self.assertEqual(r.status_code,403)

    def test_personal_bid_history_not_forecast(self):
        from fastapi.testclient import TestClient
        with TestClient(module.app) as client:
            params={'notice_id':'ID-2026','country':'DE','cpv':'72000000','offered_amount':1000,'reference_budget':1300,'currency':'EUR','status':'won'}
            self.assertEqual(client.post('/api/bids',json=params).status_code,200)
            a=client.get('/api/analytics').json()
            self.assertEqual(a['personal_bids']['historical_win_share'],100)
            self.assertNotIn('win_probability',a)

if __name__=='__main__':unittest.main()
