# Public benefit and development evidence

TenderCore Europe is an independent, fully open-source civic technology initiative, maintained by its individual founder and developer. Its aim is to reduce informational, technological and financial barriers to European public procurement, particularly for small and medium-sized enterprises (SMEs).

## Public benefit

The Apache-2.0 licensed software can be inspected, modified and self-hosted without a software license fee. It brings public procurement discovery, preliminary financial screening and participation planning into a single interface. It is intended to complement, not replace, official procurement portals and professional advice.

## Documented development milestones

| Date (UTC) | Milestone | Evidence |
| --- | --- | --- |
| Before public alpha | Internal MVP v0.4.2, as documented in the public README | [README](../README.md) |
| 2026-11-06 | Public alpha initialization and publication | [Source commit](https://github.com/BeastRO1377/tendercore-europe/commit/aa7fa46cd6c6adc43bbf8f4eea10d73e2cc0f0fc) |
| 2026-11-06 | API-backed synthetic demonstration screenshots | [Commit](https://github.com/BeastRO1377/tendercore-europe/commit/b7ff3f0035915c64abafcce8d6716f3b83a03d4f) |
| 2026-11-20 | Drips ownership configuration | [Commit](https://github.com/BeastRO1377/tendercore-europe/commit/d34d5ccf3ac0d1d93181a212a2807cff99eb4cd1) |
| 2026-11-23 | Python 3.11–3.13 CI matrix repair | [Commit](https://github.com/BeastRO1377/tendercore-europe/commit/4ca99b50e2993e46e1f0115da604324ba5581400) |
| 2026-11-23 | Public repository traffic archive and reporting tooling | [Commit](https://github.com/BeastRO1377/tendercore-europe/commit/e7a0644a9f9fdf29fdf4ac5f5aaafcb61c414a69) |

## Inspectable deliverables

- [Source code and installation instructions](../README.md), including local Docker deployment.
- [TED connector](../ted_client.py) and [notice enrichment](../ted_details.py).
- [Architecture](ARCHITECTURE.md), [tests](../tests/) and [demonstration screenshots](screenshots/) using synthetic data.
- [License](../LICENSE), [security policy](../SECURITY.md) and [contribution guidelines](../CONTRIBUTING.md).
- [Traffic methodology](github-traffic.md) and [public traffic report](../analytics/github-traffic/report.md).

## Impact measurement

Technical deliverables are evidence of development, not proof of real-world adoption. No verified count of beneficiary SMEs, successful bids, or time or money saved is claimed here. GitHub views and clones indicate repository activity only and must not be interpreted as users.

Future evidence should include dated live TED synchronization results (coverage and limitations), reproducible task-completion benchmarks, voluntary independent SME feedback, and documented external contributions. Publish aggregated results without exposing confidential supplier or bid information. Distinguish observed measurements from targets.

## Next milestones

1. Verify live TED API and representative eForms lot mapping against official notices.
2. Complete dependency-license, supply-chain and security reviews.
3. Gather independent feedback from prospective SME users and document reproducible workflows.
4. Investigate and implement additional European procurement sources, including PPDS, subject to validated access and data suitability.

See the [release checklist](RELEASE_CHECKLIST.md) for outstanding technical work. The alpha is experimental, not production-ready; it does not establish legal eligibility or guarantee procurement outcomes.
