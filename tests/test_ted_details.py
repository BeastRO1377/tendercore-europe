import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import unittest
from unittest.mock import Mock
from ted_details import extract_eforms,update_from_details,fetch_eforms_details, duration

XML_HEAD='''<Notice xmlns:cac="urn:cac" xmlns:cbc="urn:cbc" xmlns:efac="urn:efac">'''
XML_TAIL='</Notice>'
def lot(lot_id,gt='false',start='2026-12-01',end='2027-03-01',doc=True):
  bond=(f'<cac:RequiredFinancialGuarantee><cbc:GuaranteeTypeCode listName="tender-guarantee-required">{gt}</cbc:GuaranteeTypeCode><cbc:Description languageID="ENG">Security details</cbc:Description></cac:RequiredFinancialGuarantee>' if gt is not None else '')
  duration=(f'<cac:PlannedPeriod><cbc:StartDate>{start}</cbc:StartDate><cbc:EndDate>{end}</cbc:EndDate></cac:PlannedPeriod>' if start and end else '')
  documents=('<cac:CallForTendersDocumentReference><cbc:ID>DOC-1</cbc:ID><cac:Attachment><cac:ExternalReference><cbc:URI>https://buyer.example/docs</cbc:URI></cac:ExternalReference></cac:Attachment></cac:CallForTendersDocumentReference>' if doc else '')
  return f'''<cac:ProcurementProjectLot><cbc:ID>{lot_id}</cbc:ID><cac:ProcurementProject><cbc:Name languageID="ENG">Automation works</cbc:Name><cbc:Description languageID="ENG">Replace controllers</cbc:Description>{duration}</cac:ProcurementProject><cac:TenderingTerms>{bond}{documents}
    <cac:TenderSubmissionDeadlinePeriod><cbc:EndDate>2026-12-05</cbc:EndDate><cbc:EndTime>12:00:00+01:00</cbc:EndTime></cac:TenderSubmissionDeadlinePeriod>
    <cac:PaymentTerms><cbc:Note languageID="ENG">Payment after acceptance</cbc:Note></cac:PaymentTerms>
    <cac:TendererQualificationRequest><cac:SpecificTendererRequirement><cbc:TendererRequirementTypeCode listName="reserved-procurement">res-ws</cbc:TendererRequirementTypeCode><cbc:Description languageID="ENG">Reserved for workshops</cbc:Description></cac:SpecificTendererRequirement></cac:TendererQualificationRequest>
    <efac:SelectionCriteria><cbc:TendererRequirementTypeCode>slc-abil-staff-tech-work</cbc:TendererRequirementTypeCode><cbc:Description languageID="ENG">Prior technical experience</cbc:Description></efac:SelectionCriteria>
    </cac:TenderingTerms></cac:ProcurementProjectLot>'''

class TEDDetailTests(unittest.TestCase):
 def test_extraction_returns_scope_docs_qualification_terms_duration(self):
  r=extract_eforms((XML_HEAD+lot('LOT-0001')+XML_TAIL).encode())
  self.assertEqual(r['bid_guarantee'],'not_required')
  self.assertEqual(r['deadline'],'2026-12-05')
  self.assertEqual(r['documents_urls'],['https://buyer.example/docs'])
  self.assertEqual(r['coverage']['qualification_described'],1)
  self.assertEqual(r['contract_duration_days'],90)
  self.assertEqual(r['lots'][0]['financial_terms'][0]['text'],'Payment after acceptance')
  self.assertEqual(r['lots'][0]['qualification_requirements'][0]['code'],'res-ws')
 def test_multiple_lots_unknown_not_false(self):
  r=extract_eforms((XML_HEAD+lot('A')+lot('B',gt=None,start=None,end=None)+XML_TAIL).encode())
  self.assertEqual(r['bid_guarantee'],'unknown')
  self.assertIsNone(r['contract_duration_days'])
  self.assertEqual(r['coverage']['guarantee_known'],1)
 def test_multiple_lots_true_overrides_false(self):
  r=extract_eforms((XML_HEAD+lot('A')+lot('B',gt='true')+XML_TAIL).encode())
  self.assertEqual(r['bid_guarantee'],'required')
 def test_unknown_cannot_become_positive_eligibility(self):
  r=extract_eforms((XML_HEAD+lot('A')+XML_TAIL).encode())
  item={'company_eligibility':'unknown','qualification_check':'unknown','performance_guarantee':'unknown','participation_fee':'unknown','user_estimated_margin_pct':None}
  x=update_from_details(item,r)
  for key in item:self.assertEqual(x[key],item[key])
 def test_xml_error_keeps_prior_verified_value(self):
  item={'bid_guarantee':'not_required'}
  x=update_from_details(item,{'error':'offline'})
  self.assertEqual(x['bid_guarantee'],'not_required')
  self.assertEqual(x['details_fetch_status'],'failed')
 def test_non_eforms_not_fake_valid(self):
  r=extract_eforms(b'<root><anything/></root>')
  self.assertIn('error',r)
 def test_xml_entity_blocked(self):
  with self.assertRaises(Exception):extract_eforms(b'<!DOCTYPE foo [<!ENTITY x SYSTEM "file:///etc/passwd">]><root>&x;</root>')
 def test_invalid_source_not_fetched(self):
  class Fake:
   def get(self,*args,**kwargs):raise AssertionError('must not fetch')
  self.assertIn('error',fetch_eforms_details('https://private.example/data',Fake()))
 def test_month_not_synthetic_days(self):
  from defusedxml import ElementTree as ET
  e=ET.fromstring('<p><DurationMeasure unitCode="MONTH">3</DurationMeasure></p>')
  self.assertIsNone(duration(e)['days'])
  self.assertEqual(duration(e)['display'],'3 MONTH')

if __name__=='__main__':unittest.main()

class TEDSearchSnapshotTests(unittest.TestCase):
 def test_search_fields_populate_before_xml(self):
  from ted_client import normalize, FIELDS
  n={'publication-number':'766353-2026','publication-date':'2026-11-04+01:00','notice-title':{'eng':['Automated controls']},
   'buyer-name':{'deu':['Municipal utility']},'buyer-country':['DEU'],
   'estimated-value-proc':'3156000.00','estimated-value-cur-proc':'EUR',
   'identifier-lot':['LOT-0001'], 'guarantee-required-lot':['false'],
   'description-lot':{'eng':['PLC replacement and training']},
   'document-url-lot':['https://buyer.example/specs.pdf'],
   'contract-duration-start-date-lot':['2026-12-01'],
   'contract-duration-end-date-lot':['2027-03-01']}
  result=normalize(n,'competition')
  self.assertEqual(result['amount'],3156000)
  self.assertEqual(result['bid_guarantee'],'not_required')
  self.assertEqual(result['contract_duration_days'],90)
  self.assertEqual(result['documents_urls'],['https://buyer.example/specs.pdf'])
  self.assertIn('PLC',result['search_description'])
  self.assertIn('guarantee-required-lot',FIELDS)
 def test_partial_guarantee_data_unknown(self):
  from ted_client import search_snapshot
  n={'identifier-lot':['LOT-0001','LOT-0002'],'guarantee-required-lot':['false']}
  self.assertEqual(search_snapshot(n)['bid_guarantee'],'unknown')
 def test_positive_guarantee_required_even_multilot(self):
  from ted_client import search_snapshot
  n={'identifier-lot':['LOT-0001','LOT-0002'],'guarantee-required-lot':['true']}
  self.assertEqual(search_snapshot(n)['bid_guarantee'],'required')
