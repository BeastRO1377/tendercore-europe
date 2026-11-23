# GitHub traffic collection and interpretation

The repository's GitHub Traffic API exposes a rolling **14-day** window. TenderCore keeps an append-only timeline of historical days and the latest per-day observation at `analytics/github-traffic/history.json`, plus a human-readable report at `analytics/github-traffic/report.md`.

**Privacy:** This repository is public. Traffic totals, source domains and popular paths saved in the archive/report become publicly visible. The data is aggregated by GitHub; it does not identify users. Do not use this workflow if public publication of the traffic summaries is unacceptable.

## Enable the scheduled collector

1. Create a **fine-grained personal access token** restricted to `BeastRO1377/tendercore-europe` with **Repository permissions → Administration: Read-only**. No write permissions are required on this PAT.
2. Save it as an Actions repository secret named `GH_TRAFFIC_TOKEN` (Settings → Secrets and variables → Actions). **Never** commit or paste the token into repository files or logs.
3. In Settings → Actions → General, allow workflows to write repository contents using `GITHUB_TOKEN`, if the account's policy permits it. The workflow itself declares `contents: write`.
4. Merge the collector PR into `main`, then optionally run **Actions → GitHub Traffic History → Run workflow** on `main`. The scheduled run executes daily at 03:17 UTC. GitHub may delay scheduled runs.

A missing secret causes a clear job failure instead of silently returning empty traffic. API failures also fail the run without resetting the existing history.

## Architecture

- **No repository checkout in the collector:** GitHub Actions fetches the collector source from the exact workflow commit via `raw.githubusercontent.com` and invokes GitHub REST endpoints. The workflow adds no clone event of its own.
- `GH_TRAFFIC_TOKEN` reads views, clones, popular referrers, and popular pages. `GITHUB_TOKEN` separately reads workflow runs/repository metadata and writes the archival files with the Contents API.
- Date keys are UTC. Individual days are upserted from rolling responses; repeated runs do not double-count observations. Snapshots retain the **14-day totals and unique metrics** and referrers/paths as point-in-time windows.
- Stars and forks are point-in-time repository counts. Workflow runs per UTC day provide context, **not** a verified classification of clone events.
- Each successful run persists JSON first, then a generated Markdown report. Writing with the workflow's `GITHUB_TOKEN` normally does not trigger further push workflows.
- The historical source is seeded with the owner's GitHub Traffic export of 9–22 November 2026. The day-level observations and the 14-day snapshot are **observed data**, not reconstructed estimates.

## CLI

```bash
# Local read-only report from an existing archive
python scripts/github_traffic.py report --repo BeastRO1377/tendercore-europe --days 30

# Local collection (no push). Requires GH_TRAFFIC_TOKEN and optionally GITHUB_TOKEN.
python scripts/github_traffic.py collect --repo BeastRO1377/tendercore-europe

# Verify collector tests without third-party packages
python -m unittest tests/test_github_traffic.py -v
```

## Interpretation guardrails

- `count` is page views or full repository clones; neither metric equals people or adoption.
- `uniques` is unique GitHub-side sources **in its 14-day window**. Never sum daily uniques to calculate all-time unique developers or users.
- Referrers and popular paths summarize the last 14 days, not historic totals by day.
- Missing dates are unknown, not zero; before first collection, older dates can never be recovered from GitHub.
- CI `actions/checkout` activity could contribute to clones, but `workflow_runs` counts alone cannot prove or quantify the overlap. Filtering them from clone metrics is not justified.
- Attributions to LinkedIn, Drips or bots require extra supporting evidence; the Traffic API does not disclose identities or full-clone timestamps.
