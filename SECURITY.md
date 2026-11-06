# Security policy

**Alpha / local-only**. This app is a single-user local analysis tool. It is **not** authenticated and must not be made publicly reachable or deployed as a multi-tenant SaaS in its current form.

- Bind on `127.0.0.1` for local installs. Docker Compose forwards only to `127.0.0.1` on the host.
- Treat VAT IDs, company data, historical bids and notes in the SQLite file as confidential. The `data/` folder is gitignored.
- Do not paste credentials or personal information into public GitHub issues.
- Avoid modifying documented network restrictions. XML download and parsing should remain bounded and origin-controlled.
- Report vulnerabilities privately to repository maintainers via GitHub's private vulnerability reporting if enabled. Otherwise open an issue requesting a secure reporting contact without including exploit details.

The application does not provide certified legal, tax or procurement advice.
