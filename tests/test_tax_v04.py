"""Tax rules require evidence: unknown != exempt, VAT != profit, 27-country profiles."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

import app
from tax_engine import COUNTRIES
from tax_v04 import TAX_PROFILE_DEFAULT, validate_tax_profile, assess_transaction, calculate_vat_cashflow


def eu_supplier(country='DE'):
    return validate_tax_profile({
        'establishment_country':country,
        'tax_residence_country':country,
        'vat_registration_country':country,
        'vat_registration_status':'registered',
        'vat_id':'DE123456789' if country=='DE' else 'FR12345678901',
        'fixed_establishment_in_buyer_country':'no',
    })

class TaxEngineV04(unittest.TestCase):
    def test_27_countries_support_profiles_and_coverage(self):
        self.assertEqual(len(COUNTRIES),27)
        for country in COUNTRIES:
            p=validate_tax_profile({'establishment_country':country,'tax_residence_country':country})
            self.assertEqual(p['establishment_country'],country)
            r=calculate_vat_cashflow({'buyer_country':country,'bid_amount':100,'vat_treatment':'unknown'},p)
            self.assertIsNone(r['invoice_output_vat_scenario'])

    def test_non_eu_supplier_unknown_no_auto_approval(self):
        a=assess_transaction(TAX_PROFILE_DEFAULT,{'buyer_country':'DE','transaction_kind':'general_services',
           'customer_taxable':True,'special_territory':'no','fixed_establishment_at_buyer':'no'})
        self.assertEqual(a['candidate'],'unknown')
        self.assertFalse(a['automatically_approved'])

    def test_general_service_reverse_charge_candidate_not_auto(self):
        p=eu_supplier()
        a=assess_transaction(p,{'buyer_country':'FR','transaction_kind':'general_services',
           'customer_taxable':True,'fixed_establishment_at_buyer':'no','special_territory':'no'})
        self.assertEqual(a['candidate'],'reverse_charge_review')
        self.assertEqual(a['vat_treatment_for_calculator'],'unknown')
        self.assertTrue(a['review_required'])

    def test_customer_not_taxable_must_not_be_reverse_charge(self):
        p=eu_supplier()
        a=assess_transaction(p,{'buyer_country':'FR','transaction_kind':'general_services',
           'customer_taxable':False,'fixed_establishment_at_buyer':'no','special_territory':'no'})
        self.assertEqual(a['candidate'],'unknown')

    def test_supplier_vat_unconfirmed_blocks_b2b_shortcut(self):
        p=validate_tax_profile({'establishment_country':'DE'})
        a=assess_transaction(p,{'buyer_country':'FR','transaction_kind':'general_services',
           'customer_taxable':True,'special_territory':'no','fixed_establishment_at_buyer':'no'})
        self.assertEqual(a['reason_code'],'supplier_vat_status_unconfirmed')

    def test_goods_evidence_requirements(self):
        p=eu_supplier()
        d={'buyer_country':'FR','transaction_kind':'goods','customer_taxable':True,
           'fixed_establishment_at_buyer':'no','special_territory':'no',
           'dispatch_country':'DE','arrival_country':'FR'}
        self.assertEqual(assess_transaction(p,d)['candidate'],'unknown')
        d['customer_vat_id_valid']=True
        self.assertEqual(assess_transaction(p,d)['reason_code'],'transport_evidence_missing')
        d['transport_evidence']=True
        self.assertEqual(assess_transaction(p,d)['candidate'],'intra_community_supply_review')
        d['arrival_country']='DE'
        self.assertEqual(assess_transaction(p,d)['candidate'],'unknown')

    def test_property_exception_and_territories(self):
        p=eu_supplier()
        x={'buyer_country':'FR','transaction_kind':'construction','customer_taxable':True,'special_territory':'no'}
        self.assertEqual(assess_transaction(p,x)['reason_code'],'immovable_property_exception')
        x['transaction_kind']='general_services';x['special_territory']='unknown'
        self.assertEqual(assess_transaction(p,x)['reason_code'],'territory_not_confirmed')

    def test_nonrecoverable_vat_reduces_margin_not_output_vat(self):
        p=validate_tax_profile({'deduction_right':'partial','deduction_pct':40})
        r=calculate_vat_cashflow({'buyer_country':'FR','bid_amount':100000,'direct_costs':70000,
            'input_vat_paid':10000,'vat_treatment':'unknown','available_cash':20000},p)
        self.assertIsNone(r['invoice_output_vat_scenario'])
        self.assertEqual(r['input_vat_potentially_recoverable'],4000)
        self.assertEqual(r['input_vat_nonrecoverable_cost'],6000)
        self.assertEqual(r['operating_margin_after_input_vat'],24000)
        self.assertEqual(r['cash_gap_before_contract_payment_scenario'],60000)

    def test_unknown_deduction_makes_after_vat_margin_unknown(self):
        r=calculate_vat_cashflow({'buyer_country':'FR','bid_amount':100,'input_vat_paid':20},TAX_PROFILE_DEFAULT)
        self.assertIsNone(r['operating_margin_after_input_vat'])
        self.assertEqual(r['cash_gap_before_contract_payment_scenario'],20)

    def test_zero_input_vat_keeps_margin_known(self):
        r=calculate_vat_cashflow({'buyer_country':'DE','bid_amount':100,'direct_costs':50},TAX_PROFILE_DEFAULT)
        self.assertEqual(r['operating_margin_after_input_vat'],50)

    def test_refund_cash_is_not_automatic_and_cannot_exceed_paid(self):
        with self.assertRaises(ValueError):calculate_vat_cashflow({'buyer_country':'FR','input_vat_paid':10,'confirmed_refund_before_payment':12},TAX_PROFILE_DEFAULT)
        r=calculate_vat_cashflow({'buyer_country':'FR','input_vat_paid':10,'confirmed_refund_before_payment':0},TAX_PROFILE_DEFAULT)
        self.assertEqual(r['cash_gap_before_contract_payment_scenario'],10)

    def test_vat_profile_validation_and_stale_id_checks(self):
        p=validate_tax_profile({'establishment_country':'DE','vat_id':'DE123456789','vat_id_check':'manually_valid'})
        changed=validate_tax_profile({'vat_id':'DE987654321'},p)
        self.assertEqual(changed['vat_id_check'],'unverified')
        with self.assertRaises(ValueError):validate_tax_profile({'deduction_right':'partial'})
        with self.assertRaises(ValueError):validate_tax_profile({'deduction_right':'partial','deduction_pct':101})
        with self.assertRaises(ValueError):validate_tax_profile({'establishment_country':'UK'})
        with self.assertRaises(ValueError):validate_tax_profile({'vat_id':'DE+bad?chars'})

    def test_no_tax_claim_without_explicit_scenario(self):
        r=calculate_vat_cashflow({'buyer_country':'DE','bid_amount':10000,'vat_treatment':'unknown'},TAX_PROFILE_DEFAULT)
        self.assertIsNone(r['rate_applied_pct'])
        self.assertFalse(r['auto_tax_determination'])
        d=calculate_vat_cashflow({'buyer_country':'DE','bid_amount':10000,'vat_treatment':'domestic_standard'},TAX_PROFILE_DEFAULT)
        self.assertEqual(d['invoice_output_vat_scenario'],1900)

class ApiV04(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.old=app.DB
        app.DB=Path(self.temp.name)/'test.sqlite3'
        with app.db_conn():pass
    def tearDown(self):
        app.DB=self.old;self.temp.cleanup()
    def test_profile_migrates_and_preserves_old_profile(self):
        from fastapi.testclient import TestClient
        with TestClient(app.app) as c:
            self.assertEqual(c.get('/api/health').json()['version'],'0.1.0-alpha')
            self.assertEqual(c.get('/api/profile').status_code,200)
            self.assertEqual(c.get('/api/tax/profile').json()['deduction_right'],'unknown')
            p={'legal_name':'Example GmbH','establishment_country':'DE','vat_registration_status':'registered',
               'vat_registration_country':'DE','vat_id':'DE123456789','deduction_right':'full'}
            self.assertEqual(c.put('/api/tax/profile',json={'values':p}).status_code,200)
            self.assertEqual(c.get('/api/tax/profile').json()['deduction_pct'],100)
            self.assertEqual(c.get('/api/profile').json()['home_country'],'NON_EU')
    def test_assess_and_cashflow_endpoints(self):
        from fastapi.testclient import TestClient
        with TestClient(app.app) as c:
            self.assertEqual(c.post('/api/tax/assess',json={'values':{'buyer_country':'FR','transaction_kind':'general_services','customer_taxable':True,'special_territory':'no'}}).json()['candidate'],'unknown')
            self.assertEqual(c.post('/api/tax/cashflow',json={'values':{'buyer_country':'DE','bid_amount':100,'input_vat_paid':20}}).status_code,200)
            self.assertEqual(c.post('/api/tax/cashflow',json={'values':{'buyer_country':'DE','input_vat_paid':-2}}).status_code,422)
    def test_existing_database_keeps_notices(self):
        from fastapi.testclient import TestClient
        with app.db_conn() as db:
            db.execute("INSERT INTO notices(id,kind,country,published,payload,last_seen) VALUES(?,?,?,?,?,?)",('n1','competition','DE','2026-11-06',json.dumps({'id':'n1','kind':'competition','country':'DE'}),'now'))
        with TestClient(app.app) as c:
            self.assertEqual(c.put('/api/tax/profile',json={'values':{'legal_name':'New'}}).status_code,200)
        with app.db_conn() as db:self.assertEqual(db.execute('SELECT count(*) FROM notices').fetchone()[0],1)

if __name__=='__main__':unittest.main()
