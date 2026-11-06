# Tax methodology and limitations — v0.4

This is an aid to tender **screening and financial scenarios**, not a tax liability or invoicing decision.

## Determination tiers

1. **Reference facts**: standard VAT reference by EU-27 country. Rate snapshot in `tax_engine.py` is dated 2026-11-06, but rates may change and reduced rates are product- and country-specific. Validate via national tax authority before use.
2. **Candidate treatment**: use a restricted place-of-supply decision tree. Never assume taxable status merely because a buyer is a company or a public body.
3. **Evidence requirements**: VAT ID checked through VIES manually, cross-border goods route and transport evidence, ordinary EU VAT territory, and establishment details.
4. **User-selected scenario**: the output VAT treatment remains `unknown` unless selected manually for calculation. No result is automatically legally approved.
5. **Tax liability**: requires accountant/tax professional, formal business/legal facts, correct national and local rules, invoices, dates and documents. Not implemented in v0.4.

## EU-27 tax rules plan

For each country maintain a versioned rule pack:

```text
country_code, effective_from, effective_to, transaction_type,
place_of_supply, taxable_person_rule, standard/reduced rate applicability,
reverse_charge_basis, exemptions_and_deduction_effect,
registration_requirements, cash_timing, source_url, verified_at,
reviewer, status (draft/verified/expired)
```

Do not auto-populate reduced rates, corporate tax or permanent-establishment rules from generic VAT reference figures. For legal exceptions (e.g. construction services, public sector transactions, special territories, triangulation), fail closed until specific rule pack is verified.

## Margin vs cash

- Price and costs are user-entered *ex VAT* for comparison.
- Potentially deductible input VAT should not be treated as an expense, but may need financing until credit/refund.
- Unrecoverable input VAT is a cost and reduces operating margin.
- Output VAT may not constitute revenue or profit; the timing of its payment is not simulated in v0.4.
- With unknown deductibility and nonzero paid input VAT, operating margin after VAT remains unknown.
- All amounts must be entered in a single currency. Exchange-rate changes are not simulated.

## Known gaps

- Corporate income taxes and local surtaxes in 27 jurisdictions, PE/treaties and withholding taxes
- Import VAT, customs, excise, special territories, B2C distance sales and OSS/IOSS regimes
- Supplier VAT registration rules, exemptions, invoice format/e-invoicing obligations and tax representation
- Cross-border supplies outside the core intra-EU B2B cases; property and construction exceptions
- Full cash-flow timeline and refund/tax remittance dates

The software deliberately does **not** make claims about complete coverage of these gaps.
