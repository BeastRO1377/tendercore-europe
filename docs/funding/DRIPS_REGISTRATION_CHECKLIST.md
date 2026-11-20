# Drips registration checklist — TenderCore Europe

Reference: https://docs.drips.network/get-support/claim-your-repository/

## Current status (2026-11-20)

- [x] Public GitHub repository exists: https://github.com/BeastRO1377/tendercore-europe
- [x] Main branch: `main`; project licensed under Apache 2.0
- [x] Project profile prepared: [DRIPS_PROJECT_PROFILE.md](DRIPS_PROJECT_PROFILE.md)
- [x] Public Ethereum wallet designated by the maintainer: `0x7e05dc11549F2d8A1AFe8D15e900466053e87F79` (EIP-55 checksum verified; wallet control still requires confirmation in Drips)
- [ ] Connect that wallet in the official Drips App
- [x] Create and validate the real `FUNDING.json` at the **root of `main`** (merged PR #1)
- [ ] Complete Drips on-chain project claim
- [ ] Set recipient split(s), if any, and public project presentation
- [ ] Confirm claimed project link and optionally add it to GitHub sponsor links

## Essential security and operational details

1. **Do not share any wallet seed phrase, private key or wallet password.** The `0x...` public address may be shared to prepare the claim file.
2. Use https://www.drips.network/app and open **Projects → Claim project**, entering the repository's exact GitHub URL.
3. Use the committed `FUNDING.json` in the root of the repository. The Ethereum owner address is `0x7e05dc11549F2d8A1AFe8D15e900466053e87F79`; verify that the same address appears in your wallet connection before proceeding. This address is public.
4. GitHub repository control and Drips project ownership are linked through the `FUNDING.json` file on the **default branch**. A draft PR alone does not complete verification.
5. Review the address and network carefully before submitting a blockchain transaction. Ethereum gas may be required; fees vary. Certain other networks may support gas-sponsored claims.
6. During the claim, choose the incoming-funds split(s) consciously. Do not assign anyone a share of donations without the maintainer's authorization.
7. Validate the claim on the official Drips project page before publishing sponsorship links.
8. If applying for a specific RetroPGF round later, verify eligibility, deadlines, regional restrictions and any round-specific KYC/KYB; claiming alone does not guarantee awards.

## Proposed public profile information

- Name: TenderCore Europe
- Description: Fully open-source, self-hosted tools for discovering and preliminarily evaluating European public procurement opportunities
- Repository: https://github.com/BeastRO1377/tendercore-europe
- License: Apache 2.0
- Version: v0.1.0-alpha
- Maintainer structure: independently developed; no registered corporate status asserted
- Source and image links: use the existing README and tested synthetic screenshots; do not present demo notices as real tenders

## After the Drips claim

Once the **exact project URL** is known, decide whether to create `.github/FUNDING.yml` to show a sponsor link on GitHub and whether to add a short support section in the README. Avoid making these links before the project is claimed and verified.

## Sources

- Claiming: https://docs.drips.network/get-support/claim-your-repository/
- RetroPGF applications: https://docs.drips.network/rpgf/apply-to-a-round/
- FAQ: https://docs.drips.network/faq/
