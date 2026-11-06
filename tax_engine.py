"""Country-aware VAT *scenario* engine (not tax advice or tax determination).

Each rate is a dated reference rate. Tax treatment is NOT inferred from the buyer's
country. Reverse charge, permanent establishments, reduced rates, customs,
withholding taxes and direct taxation remain user/accountant questions.
"""
from __future__ import annotations
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

SOURCE = 'https://europa.eu/youreurope/business/finance-and-tax/vat/vat-rules-rates/index_en.htm'
CROSS_BORDER = 'https://europa.eu/youreurope/business/finance-and-tax/vat/cross-border-vat/index_en.htm'
RATE_AS_OF = '2026-11-06'  # reference table snapshot; verify before invoicing
# ISO-2, name EN, name RU, standard VAT, main currency
COUNTRIES = {
 'AT': ('Austria','Австрия',20,'EUR'), 'BE': ('Belgium','Бельгия',21,'EUR'),
 'BG': ('Bulgaria','Болгария',20,'EUR'), 'HR': ('Croatia','Хорватия',25,'EUR'),
 'CY': ('Cyprus','Кипр',19,'EUR'), 'CZ': ('Czechia','Чехия',21,'CZK'),
 'DK': ('Denmark','Дания',25,'DKK'), 'EE': ('Estonia','Эстония',24,'EUR'),
 'FI': ('Finland','Финляндия',25.5,'EUR'), 'FR': ('France','Франция',20,'EUR'),
 'DE': ('Germany','Германия',19,'EUR'), 'GR': ('Greece','Греция',24,'EUR'),
 'HU': ('Hungary','Венгрия',27,'HUF'), 'IE': ('Ireland','Ирландия',23,'EUR'),
 'IT': ('Italy','Италия',22,'EUR'), 'LV': ('Latvia','Латвия',21,'EUR'),
 'LT': ('Lithuania','Литва',21,'EUR'), 'LU': ('Luxembourg','Люксембург',17,'EUR'),
 'MT': ('Malta','Мальта',18,'EUR'), 'NL': ('Netherlands','Нидерланды',21,'EUR'),
 'PL': ('Poland','Польша',23,'PLN'), 'PT': ('Portugal','Португалия',23,'EUR'),
 'RO': ('Romania','Румыния',21,'RON'), 'SK': ('Slovakia','Словакия',23,'EUR'),
 'SI': ('Slovenia','Словения',22,'EUR'), 'ES': ('Spain','Испания',21,'EUR'),
 'SE': ('Sweden','Швеция',25,'SEK')
}
ISO3 = {'AT':'AUT','BE':'BEL','BG':'BGR','HR':'HRV','CY':'CYP','CZ':'CZE',
 'DK':'DNK','EE':'EST','FI':'FIN','FR':'FRA','DE':'DEU','GR':'GRC',
 'HU':'HUN','IE':'IRL','IT':'ITA','LV':'LVA','LT':'LTU','LU':'LUX',
 'MT':'MLT','NL':'NLD','PL':'POL','PT':'PRT','RO':'ROU','SK':'SVK',
 'SI':'SVN','ES':'ESP','SE':'SWE'}
REVERSE_ISO3 = {v:k for k,v in ISO3.items()}
# Explicit national territory caveats drawn from EU guidance; NOT exhaustive.
TERRITORIAL_EXCEPTIONS = {
 'FI':['Åland Islands'], 'FR':['French overseas departments'],
 'DE':['Büsingen','Heligoland'], 'GR':['Mount Athos'],
 'IT':['Campione d’Italia','Italian waters of Lake Lugano','Livigno'],
 'ES':['Canary Islands','Ceuta','Melilla']
}



def country_data() -> list[dict]:
    return [{'code': code, 'iso3': ISO3[code], 'en': r[0], 'ru': r[1],
             'standard_vat': r[2], 'currency': r[3], 'rate_as_of': RATE_AS_OF,
             'special_territories': TERRITORIAL_EXCEPTIONS.get(code,[]),
             'reduced_rates_automatic':False, 'cross_border_auto_determination':False,
             'tax_review_required':True}
            for code, r in COUNTRIES.items()]


def decimal(value: Any, label: str) -> Decimal:
    try:
        x = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f'{label}: invalid number') from None
    if not x.is_finite() or x < 0:
        raise ValueError(f'{label}: must be a finite nonnegative number')
    return x


def money(x: Decimal) -> float:
    return float(x.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))


def scenario(payload: dict) -> dict:
    """Transparent cost scenario, NOT a tax filing / eligibility decision.

    User must choose VAT treatment. Default is UNKNOWN and no VAT is added or
    deducted. When 'domestic_standard' is explicitly selected, display-only
    illustrative tax-inclusive amount is computed, without changing margin.
    """
    country = payload.get('buyer_country', 'DE')
    if country not in COUNTRIES:
        raise ValueError('buyer_country: EU-27 code required')
    currency = str(payload.get('currency','EUR')).upper().strip()
    if currency not in ('EUR','PLN','CZK','DKK','HUF','RON','SEK','BGN'):
        raise ValueError('unsupported currency')
    revenue = decimal(payload.get('bid_amount', 0), 'bid_amount')
    direct = decimal(payload.get('direct_costs',0), 'direct_costs')
    indirect = decimal(payload.get('indirect_costs',0), 'indirect_costs')
    financing = decimal(payload.get('financing_costs',0), 'financing_costs')
    risk = decimal(payload.get('risk_reserve',0), 'risk_reserve')
    required_cash = decimal(payload.get('required_cash',0), 'required_cash')
    available_cash = decimal(payload.get('available_cash',0), 'available_cash')
    advance = decimal(payload.get('expected_advance',0), 'expected_advance')
    treatment = payload.get('vat_treatment','unknown')
    if treatment not in ('unknown','domestic_standard','reverse_charge','exempt_or_zero','manual'):
        raise ValueError('unknown vat_treatment')
    rate = Decimal(str(COUNTRIES[country][2]))
    if treatment == 'manual':
        rate = decimal(payload.get('manual_vat_rate'), 'manual_vat_rate')
        if rate > 100:
            raise ValueError('VAT rate out of range')
    cost = direct + indirect + financing + risk
    margin = revenue - cost
    margin_pct = (margin / revenue * 100) if revenue else Decimal('0')
    vat = None
    gross = None
    if treatment in ('domestic_standard','manual'):
        vat = revenue * rate / 100
        gross = revenue + vat
    issues = ['VAT treatment must be verified for supplier location, establishment, place of supply, and transaction type.',
              'Withholding tax, permanent establishment, corporate income tax, social taxes, and local duties are not calculated.',
              'Cross-currency FX and price VAT inclusion/exclusion are not automatically inferred.']
    if country in TERRITORIAL_EXCEPTIONS:
        issues.append('Special territories of '+country+': '+', '.join(TERRITORIAL_EXCEPTIONS[country])+'. VAT treatment can differ.')
    if treatment == 'reverse_charge':
        issues.append('Reverse charge is a USER-SELECTED assumption, not an automated legal conclusion.')
    if treatment == 'exempt_or_zero':
        issues.append('Exemption/zero rate is a USER-SELECTED assumption and requires legal verification.')
    return {'buyer_country':country,'currency':currency,'vat_treatment':treatment,
            'standard_vat_rate': COUNTRIES[country][2], 'applied_rate':money(rate) if treatment != 'unknown' else None,
            'vat_amount_display_only':money(vat) if vat is not None else None,
            'gross_display_only':money(gross) if gross is not None else None,
            'bid_amount_ex_vat_assumed':money(revenue), 'total_costs':money(cost),
            'margin_before_income_taxes':money(margin), 'margin_pct_before_income_taxes':round(float(margin_pct),2),
            'required_cash_user_input':money(required_cash), 'cash_gap_before_payment': money(max(Decimal('0'), cost+required_cash-advance-available_cash)),
            'available_cash_user_input':money(available_cash), 'expected_advance_user_input':money(advance),
            'rate_source':SOURCE,'rate_as_of':RATE_AS_OF,'tax_warnings':issues}
