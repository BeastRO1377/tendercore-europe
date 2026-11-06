# Architecture (alpha)

- `app.py`: FastAPI single-user REST API, local SQLite storage, preferences, basic analytics and web serving.
- `ted_client.py`: TED Search API v3 query construction and cautious normalization.
- `ted_details.py`: bounded, defensive eForms XML detail extraction by lot.
- `tax_engine.py`, `tax_v04.py`: reference VAT rates and **preliminary** scenario assessments, not tax compliance.
- `static/`: vanilla HTML/CSS/JS interface; two languages and three themes.
- `tests/`: Python unit/API tests, including unknown/partial-evidence rules.

## Data quality invariants

1. Unknown security, fees and eligibility must never be treated as zero/approved.
2. A notice may include multiple lots with independent requirements.
3. Winning amount and number of bids can be absent; do not invent them.
4. Analytics are limited to synchronized sample and are not market-wide forecasts.
5. Personal past bid win rate is not a valid probability for a new tender.
6. National legislation and tender documents override automated suggestions.

## Public vs private

TenderCore Europe Community is independent of ProjectControl. No ProjectControl or personal operational database is included.
