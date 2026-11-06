# Contributing

Thanks for contributing to TenderCore Europe Community. Please open an issue describing the problem and relevant TED notice/publication ID before submitting a fix. Do not post private supplier credentials or identifiers.

## Development

- Python 3.11+; `python -m pip install -r requirements.txt`.
- Run `python -m unittest discover -s tests -v`.
- UI layout changes must follow [`docs/DESIGN_SYSTEM.md`](docs/DESIGN_SYSTEM.md): 4px rhythm, 40px controls, 18px checkboxes, consistent text baselines, RU/EN and system/light/dark.
- Tests for new eForms fields must include fixture XML and unknown/missing-field cases. Do not infer absence of security or fees from missing data.
- Cite the relevant TED/eForms field and documentation for data-extraction changes.
- Do not include scraped non-public materials, tokens, VAT IDs, private local SQLite data or personal information.

By submitting a contribution, you agree to license it under Apache-2.0, unless otherwise agreed in writing.
