# TED details / mapping policy (v0.4.2)

Search source: `POST https://api.ted.europa.eu/v3/notices/search` (no key required for public search). XML per publication: `https://ted.europa.eu/en/notice/{publication-number}/xml`, or TED-provided XML link when available. Official references:

- https://docs.ted.europa.eu/api/latest/search.html
- https://docs.ted.europa.eu/ODS/latest/reuse/field-list.html
- https://docs.ted.europa.eu/eforms/latest/schema/procedure-lot-part-information.html

| User-visible field | Structured source | Known caveat |
|---|---|---|
| Buyer and country | `buyer-name`, `buyer-country` | Multilingual and array-valued |
| Budget | `estimated-value-proc`, `estimated-value-cur-proc` | Procedure estimate is not the value of each lot; no forced currency conversions |
| Subject and scope | `notice-title`, `description-lot`, XML `ProcurementProject/Description` | Buyer language preserved, translation not automatic |
| Bid security | BT-751/BT-75, `guarantee-required-lot`, XML `RequiredFinancialGuarantee` | Only bid security, not performance security; mixed/partial values stay unknown |
| Tender submission date | `deadline-receipt-tender-date-lot`, XML `TenderSubmissionDeadlinePeriod` | Dates may differ by lot; detail shows per lot |
| Execution period | BT-36/BT-536/BT-537, XML `PlannedPeriod` | `MONTH` and `YEAR` not converted to arbitrary number of days |
| Qualification requirements | BT-809/BT-750, search `selection-criterion-description-lot` | **Requirement does not imply company is eligible**; may be in attachments or ESPD |
| Documents | BT-15 `document-url-lot` or XML `CallForTendersDocumentReference` | External linked platform may require authentication |
| Financial terms | BT-77 (`terms-financial-lot`), XML `PaymentTerms/Note` | Narrative only; performance guarantees often in contract package |
| Participation fee | National platform conditions | No universal safe binary conclusion from eForms |
| Margin | User's cost/tax scenario | Bid amount alone cannot determine profit or chance of winning |

Data are persisted per **notice** with a per-lot `lots_detail` collection. Cross-lot aggregation never claims *all* lots are guaranteed free unless every lot's BT-751 is explicitly `false`. The UI may show a risk status for a whole notice; before bidding, select the specific lot and check its official documents.

The available source data are not guaranteed to include all national procurement conditions. We do not automatically classify non-EU bidders as eligible, waive bonds, infer fees, or invent profit or win probabilities. Public users should check legal and tax conclusions with qualified advisers.

Live integration against new/legacy eForms versions and a representative national multi-lot sample remains a release gate for production. A future schema migration should give each lot a first-class identifier to support per-lot financial scoring, corrections, award matching, and versions.
