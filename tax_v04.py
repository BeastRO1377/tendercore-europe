"""TenderCore Europe v0.4 - conservative, evidence-aware cross-border VAT workflow.

This is NOT a tax assessment for filing. Classification produces *candidates* only.
Even a strong candidate needs substantiating evidence and national tax review.
"""
from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from tax_engine import COUNTRIES, TERRITORIAL_EXCEPTIONS, CROSS_BORDER, SOURCE, RATE_AS_OF, decimal, money

PLACE_OF_SUPPLY = 'https://taxation-customs.ec.europa.eu/taxation/vat/vat-directive/place-taxation_en'
VIES = 'https://europa.eu/youreurope/business/finance-and-tax/vat/check-vat-number-vies/index_en.htm'
DEDUCTION = 'https://europa.eu/youreurope/business/finance-and-tax/vat/charging-deducting-vat/index_en.htm'
TAX_RATES = 'https://taxation-customs.ec.europa.eu/taxation/vat/vat-directive/vat-rates_en'

TAX_PROFILE_DEFAULT = {
    'legal_name': '',
    'establishment_country': 'NON_EU',
    'tax_residence_country': 'NON_EU',
    'vat_registration_country': None,
    'vat_id': '',
    'vat_registration_status': 'unknown',
    'vat_id_check': 'unverified',
    'fixed_establishment_in_buyer_country': 'unknown',
    'deduction_right': 'unknown',
    'deduction_pct': None,
    'notes': '',
}

TRANSACTION_KINDS = ('goods', 'general_services', 'immovable_property_services',
                     'construction', 'electronic_services', 'mixed', 'other', 'unknown')


def validate_tax_profile(changes: dict[str, Any], current: dict | None = None) -> dict:
    if not isinstance(changes, dict):
        raise ValueError('Tax profile must be an object')
    forbidden = set(changes).difference(TAX_PROFILE_DEFAULT)
    if forbidden:
        raise ValueError('Unknown tax profile field: ' + sorted(forbidden)[0])
    result = {**(current or TAX_PROFILE_DEFAULT), **changes}
    for key in ('establishment_country', 'tax_residence_country'):
        if result[key] not in COUNTRIES and result[key] != 'NON_EU':
            raise ValueError(key + ': choose an EU member or NON_EU')
    vat_country = result['vat_registration_country']
    if vat_country not in COUNTRIES and vat_country is not None:
        raise ValueError('vat_registration_country: invalid')
    if result['vat_registration_status'] not in ('unknown', 'registered', 'not_registered'):
        raise ValueError('vat_registration_status: invalid')
    if result['vat_id_check'] not in ('unverified', 'manually_valid', 'manually_invalid'):
        raise ValueError('vat_id_check: invalid')
    if result['fixed_establishment_in_buyer_country'] not in ('unknown','yes','no'):
        raise ValueError('fixed_establishment_in_buyer_country: invalid')
    if result['deduction_right'] not in ('unknown','full','partial','none'):
        raise ValueError('deduction_right: invalid')
    for name, limit in [('legal_name', 160), ('notes', 500)]:
        if not isinstance(result[name], str) or len(result[name]) > limit:
            raise ValueError(name + ': invalid length')
    vat_id = result['vat_id']
    if not isinstance(vat_id, str) or len(vat_id) > 30:
        raise ValueError('vat_id: invalid')
    vat_id = re.sub(r'\s+', '', vat_id).upper()
    if vat_id and not re.fullmatch(r'[A-Z0-9+*.-]{4,30}', vat_id):
        raise ValueError('vat_id: invalid characters')
    result['vat_id'] = vat_id
    # Changing an identifier or registration jurisdiction invalidates any previous manual VIES assertion.
    if current and ('vat_id_check' not in changes) and (vat_id != current.get('vat_id','') or result['vat_registration_country'] != current.get('vat_registration_country')):
        result['vat_id_check'] = 'unverified'
    p = result['deduction_pct']
    if result['deduction_right'] == 'full':
        result['deduction_pct'] = 100
    elif result['deduction_right'] == 'none':
        result['deduction_pct'] = 0
    elif result['deduction_right'] == 'partial':
        if p is None or decimal(p, 'deduction_pct') > 100:
            raise ValueError('deduction_pct: partial deduction requires 0–100')
        result['deduction_pct'] = float(p)
    else:
        result['deduction_pct'] = None
    # A manually entered VAT ID is *not* an automated VIES validation.
    if result['vat_id_check'] == 'manually_valid' and not result['vat_id']:
        raise ValueError('vat_id_check: VAT ID required')
    return result


def _yes(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def assess_transaction(profile: dict, values: dict) -> dict:
    """Returns a possible VAT treatment, never a binding tax conclusion.

    The decision tree intentionally fails closed for construction/property,
    non-EU, B2C, mixed operations, missing VAT/transport evidence or special territories.
    """
    supplier = profile['establishment_country']
    buyer = values.get('buyer_country')
    if buyer not in COUNTRIES:
        raise ValueError('buyer_country: EU-27 code required')
    kind = values.get('transaction_kind', 'unknown')
    if kind not in TRANSACTION_KINDS:
        raise ValueError('transaction_kind: invalid')
    taxable = _yes(values.get('customer_taxable'))
    vat_valid = _yes(values.get('customer_vat_id_valid'))
    transport = _yes(values.get('transport_evidence'))
    dispatch = values.get('dispatch_country') or None
    arrival = values.get('arrival_country') or None
    if dispatch is not None and dispatch not in COUNTRIES and dispatch != 'NON_EU':
        raise ValueError('dispatch_country: invalid')
    if arrival is not None and arrival not in COUNTRIES and arrival != 'NON_EU':
        raise ValueError('arrival_country: invalid')
    fee = values.get('fixed_establishment_at_buyer') or profile.get('fixed_establishment_in_buyer_country','unknown')
    if fee not in ('yes','no','unknown'):
        raise ValueError('fixed_establishment_at_buyer: invalid')
    territorial = values.get('special_territory', 'unknown')
    if territorial not in ('no','yes','unknown'):
        raise ValueError('special_territory: invalid')
    warnings = []
    missing = []
    candidate = 'unknown'
    code = 'insufficient_evidence'
    if supplier == 'NON_EU':
        code = 'non_eu_establishment_review'
        warnings.append('Non-EU establishment: import, VAT registration, fiscal representative, local supply or reverse-charge obligations require local review.')
    elif territorial != 'no':
        code = 'territory_not_confirmed'
        missing.append('Confirm that both sides fall within the EU VAT territory; special territories may follow different rules.')
    elif kind in ('immovable_property_services','construction'):
        code = 'immovable_property_exception'
        warnings.append('Property/construction-related supplies often have place-of-supply exceptions; evaluate property location and national construction rules.')
    elif kind in ('mixed','other','unknown','electronic_services'):
        code = 'complex_transaction_review'
        warnings.append('Mixed, other or electronic supplies need a dedicated place-of-supply determination.')
    elif taxable is not True:
        code = 'customer_status_unconfirmed'
        missing.append('Verify customer acts as a taxable person for this purchase (public authorities may be non-taxable).')
    elif profile.get('vat_registration_status') != 'registered' or not profile.get('vat_id'):
        code = 'supplier_vat_status_unconfirmed'
        missing.append('Confirm the supplier VAT registration and its VAT ID for the applicable supply.')
    elif supplier == buyer:
        code = 'domestic_standard_candidate'
        candidate = 'domestic_standard_review'
        warnings.append('Domestic standard VAT is illustrative only. Reduced rates, exemptions and sector-specific reverse charge may apply.')
    elif fee != 'no':
        code = 'fixed_establishment_unconfirmed'
        missing.append('Confirm whether the supplier has a fixed establishment involved in the supply in the buyer country.')
    elif kind == 'general_services':
        code = 'intra_eu_general_b2b_service'
        candidate = 'reverse_charge_review'
        warnings.append('General B2B services are commonly taxed where the customer is established, with recipient accounting; verify exceptions.')
    elif kind == 'goods':
        if not dispatch or not arrival:
            code = 'goods_route_missing'
            missing.append('Provide dispatch and arrival countries for the goods.')
        elif dispatch != supplier or arrival != buyer or dispatch == arrival:
            code = 'goods_route_not_simple'
            warnings.append('Goods route does not fit a simple intra-Community supply from supplier to customer.')
        elif vat_valid is not True:
            code = 'vies_not_confirmed'
            missing.append('Confirm the buyer’s EU VAT number for cross-border goods; retain the VIES check record.')
        elif transport is not True:
            code = 'transport_evidence_missing'
            missing.append('Evidence of movement of goods between EU countries is required.')
        else:
            code = 'intra_eu_goods_supply'
            candidate = 'intra_community_supply_review'
            warnings.append('Intra-Community supply may qualify for exemption with deduction; acquisition VAT is accounted for in buyer state. Verify all conditions.')
    if buyer in TERRITORIAL_EXCEPTIONS or supplier in TERRITORIAL_EXCEPTIONS:
        warnings.append('Some territories associated with these countries are outside the EU VAT territory: verify place of supply.')
    warnings.append('This classification is a candidate only. Verify national law, contracts, registrations and transaction facts before invoicing.')
    return {
        'candidate':candidate,'reason_code':code,'automatically_approved':False,
        'review_required':True, 'seller_country':supplier, 'buyer_country':buyer,
        'transaction_kind':kind, 'customer_taxable_confirmed':taxable,
        'customer_vat_valid_manually_confirmed':vat_valid,
        'vat_treatment_for_calculator':'unknown',  # explicitly do NOT fill a tax decision
        'place_of_supply_country':None,
        'missing_evidence':missing, 'warnings':warnings,
        'references':[CROSS_BORDER,PLACE_OF_SUPPLY,VIES,TAX_RATES],
        'tax_rate_reference_date':RATE_AS_OF,
    }


def calculate_vat_cashflow(values:dict, profile:dict)->dict:
    """Per-currency scenario; VAT is cash-flow, non-deductible input VAT is cost.

    No output tax, refunds, deductions or exemptions are inferred. User enters
    cash flows and assumptions. Unknown recovery means after-VAT profit is UNKNOWN.
    """
    buyer = values.get('buyer_country')
    if buyer not in COUNTRIES:
        raise ValueError('buyer_country: EU-27 code required')
    currency = str(values.get('currency','EUR')).upper().strip()
    if currency not in ('EUR','PLN','CZK','DKK','HUF','RON','SEK','BGN'):
        raise ValueError('Unsupported currency')
    price=decimal(values.get('bid_amount',0),'bid_amount')
    direct=decimal(values.get('direct_costs',0),'direct_costs')
    indirect=decimal(values.get('indirect_costs',0),'indirect_costs')
    financing=decimal(values.get('financing_costs',0),'financing_costs')
    reserve=decimal(values.get('risk_reserve',0),'risk_reserve')
    blocked=decimal(values.get('required_cash',0),'required_cash')
    available=decimal(values.get('available_cash',0),'available_cash')
    advance=decimal(values.get('expected_advance',0),'expected_advance')
    input_vat=decimal(values.get('input_vat_paid',0),'input_vat_paid')
    additional_nondeductible=decimal(values.get('additional_nondeductible_taxes',0),'additional_nondeductible_taxes')
    refund_before=decimal(values.get('confirmed_refund_before_payment',0),'confirmed_refund_before_payment')
    if refund_before > input_vat:
        raise ValueError('confirmed_refund_before_payment cannot exceed input VAT paid')
    if advance > price:
        raise ValueError('expected_advance cannot exceed bid_amount')
    treatment=values.get('vat_treatment','unknown')
    if treatment not in ('unknown','domestic_standard','reverse_charge','intra_community_supply','manual','exempt'):
        raise ValueError('vat_treatment: invalid')
    rate=None
    invoice_vat=None
    if treatment in ('domestic_standard','manual'):
        rate=decimal(values.get('manual_vat_rate') if treatment=='manual' else COUNTRIES[buyer][2], 'vat_rate')
        if rate>100:raise ValueError('VAT rate out of range')
        invoice_vat=price*rate/100
    elif treatment in ('reverse_charge','intra_community_supply','exempt'):
        invoice_vat=Decimal(0)
    # VAT deductions must not be assumed from profile alone when VAT eligibility unverified.
    deduction=values.get('deduction_pct',profile.get('deduction_pct'))
    deduction_pct=None if deduction is None or deduction=='' else decimal(deduction,'deduction_pct')
    if deduction_pct is not None and deduction_pct>100:
        raise ValueError('deduction_pct must be 0–100')
    recoverable=input_vat*deduction_pct/100 if deduction_pct is not None else (Decimal(0) if input_vat == 0 else None)
    nonrecoverable=input_vat-recoverable if recoverable is not None else None
    baseline_cost=direct+indirect+financing+reserve+additional_nondeductible
    margin_before_input_vat=price-baseline_cost
    margin_after_vat=(margin_before_input_vat-nonrecoverable) if nonrecoverable is not None else None
    # Cash exposure assumes all paid input VAT is prefinanced; potential refunds
    # only reduce it when explicitly confirmed as received before contract payment.
    cash_before=baseline_cost+blocked+input_vat-advance-available-refund_before
    cash_gap=max(Decimal(0),cash_before)
    problems=['This is a user-provided scenario, not a determination of VAT liability or tax advice.',
              'Cash gap ignores timing of supplier instalments, VAT remittances, customer payment milestones and FX.',
              'Income/withholding tax, customs, social contributions and local tax rules are not calculated.']
    if treatment=='unknown':problems.append('Output VAT treatment is unknown; invoice VAT cannot be quantified.')
    if deduction_pct is None:problems.append('Input VAT recovery is not confirmed; after-VAT operating margin is unavailable.')
    if refund_before:problems.append('A pre-payment VAT refund is assumed based solely on user input; confirm dates and eligibility.')
    if buyer in TERRITORIAL_EXCEPTIONS:
        problems.append('Buyer country has special VAT territories; verify actual place of supply.')
    return {
        'currency':currency,'buyer_country':buyer,'vat_treatment':treatment,
        'rate_applied_pct':money(rate) if rate is not None else None,
        'invoice_output_vat_scenario':money(invoice_vat) if invoice_vat is not None else None,
        'input_vat_paid':money(input_vat),
        'input_vat_recovery_pct':money(deduction_pct) if deduction_pct is not None else None,
        'input_vat_potentially_recoverable':money(recoverable) if recoverable is not None else None,
        'input_vat_nonrecoverable_cost':money(nonrecoverable) if nonrecoverable is not None else None,
        'operating_margin_before_input_vat':money(margin_before_input_vat),
        'operating_margin_after_input_vat':money(margin_after_vat) if margin_after_vat is not None else None,
        'cash_gap_before_contract_payment_scenario':money(cash_gap),
        'refund_before_payment_assumed':money(refund_before),
        'blocked_cash_assumed':money(blocked),
        'reference_rate_as_of':RATE_AS_OF,
        'auto_tax_determination':False,
        'review_required':True,
        'warnings':problems, 'references':[DEDUCTION,CROSS_BORDER,TAX_RATES],
    }
