# TenderCore Europe — Drips project profile (draft)

> Registration copy for Drips. This text is a truthful summary of the public repository as of 2026-11-20. Publish the profile only after the maintainer reviews it and claims the repository.

## Project name

TenderCore Europe

## Short description

Fully open-source, self-hosted tools for discovering and preliminarily evaluating European public procurement opportunities.

## Project summary

TenderCore Europe is an Apache-2.0-licensed, self-hosted platform intended to make European public procurement information more accessible and actionable for suppliers, especially small and medium-sized enterprises. It combines procurement notice discovery, lot-level information, filters, customizable preferences, and preliminary risk indicators in an interface available in English and Russian.

The project is being developed independently and its code is publicly available. Its current public release is **v0.1.0-alpha**, an experimental community edition, **not production-ready**.

The initial data source is the EU's Tenders Electronic Daily (TED), via the TED Search API and eForms enrichment. The project is designed for future extension to additional national or regional procurement sources, subject to integration feasibility.

## Problem

Procurement opportunities are fragmented across sources, languages, document formats and legal requirements. Smaller suppliers frequently lack the resources to discover relevant notices, compare opportunities and identify critical uncertainties early.

## What exists today

- A Python-based, self-hosted application with a local SQLite data store.
- TED Search API connector and lot-level eForms enrichment, subject to further live validation.
- English/Russian UI, country and CPV filters, tile/list views and CSV export.
- Favorites, company preference settings and preliminary financial review tools.
- Explicit **unknown / requires review** states for information not established by the source.
- Public source code, documentation, tests and a Docker-based local setup.
- Synthetic demonstration notices clearly separated from live procurement data.

## Boundaries and transparency

TenderCore Europe does **not** yet provide authoritative legal eligibility assessments, definitive guarantees about bid/performance security, validated EU-wide tax calculations or dependable tender-winning probabilities. Tender documents and official sources must always be checked before bidding. No public claim of production reliability, validated coverage of all national portals, or actual user impact is made at this stage.

## What support would enable

1. Strengthen integration with TED and validate real-world data completeness and field mapping.
2. Expand to national and regional public procurement sources where lawful, accessible integrations exist.
3. Improve security, automated tests, accessibility, documentation and localization.
4. Obtain independent code/security reviews.
5. Cover development infrastructure and AI-assisted engineering tools.
6. Engage specialist contributors for legal, procurement, security and integration reviews.

The independent maintainer may allocate a **modest, disclosed portion** of unrestricted support to living/development time, alongside project expenses. No claim is made that all support goes solely to external vendors or contractors.

## Public links

- GitHub source: https://github.com/BeastRO1377/tendercore-europe
- License: https://github.com/BeastRO1377/tendercore-europe/blob/main/LICENSE
- README: https://github.com/BeastRO1377/tendercore-europe/blob/main/README.md
- Architecture: https://github.com/BeastRO1377/tendercore-europe/blob/main/docs/ARCHITECTURE.md

## Suggested categories / tags

Open Source; Public Procurement; Digital Public Goods; SMEs; Transparency; Civic Technology; European Union; Data Access; Python

## Ownership and registration status

- Maintainer: individual developer (no company or team implied).
- Current funding configuration: **not configured**.
- Drips ownership claim: **not completed**.
- Wallet: **not provided**; never publish a guessed address.
- Drips project URL: **to be confirmed after claim**.

This draft is an informational preparation document, not a donation solicitation currently live on Drips.
