#!/usr/bin/env python3
"""Store GitHub's 14-day traffic windows as a durable daily JSON time series.

Only GitHub REST is used: the collector performs no git clone/checkout.
"""
from __future__ import annotations

import argparse
import base64
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

API = "https://api.github.com"
HISTORY_PATH = "analytics/github-traffic/history.json"
REPORT_PATH = "analytics/github-traffic/report.md"
REPO_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class GitHubError(RuntimeError):
    """An authenticated GitHub request failed."""


def api_request(repo: str, path: str, token: str, *, method: str = "GET", payload=None):
    """Call only the configured repository, never arbitrary third-party URLs."""
    if not REPO_PATTERN.fullmatch(repo):
        raise ValueError("--repo must look like OWNER/REPO")
    if not token:
        raise ValueError("GitHub API token is not configured")
    if (path and not path.startswith("/")) or ".." in path or "//" in path:
        raise ValueError("Invalid API path")
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = Request(
        f"{API}/repos/{repo}{path}",
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "TenderCore-GitHub-Traffic-Collector",
            **({"Content-Type": "application/json"} if data is not None else {}),
        },
    )
    try:
        with urlopen(req, timeout=25) as res:
            return json.load(res)
    except HTTPError as exc:
        if exc.code == 404:
            raise GitHubError("GitHub HTTP 404") from exc
        raise GitHubError(f"GitHub HTTP {exc.code} on {method} {path}") from exc
    except (URLError, TimeoutError) as exc:
        raise GitHubError(f"GitHub unavailable on {method} {path}") from exc


def blank_archive(repo: str) -> dict:
    return {"schema_version": 1, "repository": repo, "daily": {}, "snapshots": {}}


def check_archive(data: dict, repo: str) -> dict:
    if (not isinstance(data, dict) or data.get("schema_version") != 1
            or data.get("repository") != repo
            or not isinstance(data.get("daily"), dict)
            or not isinstance(data.get("snapshots"), dict)):
        raise ValueError("History schema/repository mismatch; refusing to overwrite")
    return data


def merge_traffic(data: dict, views: dict, clones: dict, referrers: list, paths: list,
                  *, captured_at: str, stars=None, forks=None, runs: dict | None = None) -> dict:
    """Upsert each dated daily observation; rolling uniques are snapshot-only."""
    capture_day = captured_at[:10]
    daily = data["daily"]
    for series, prefix in ((views, "views"), (clones, "clones")):
        if not isinstance(series.get("count"), int) or not isinstance(series.get("uniques"), int):
            raise ValueError(f"Bad {prefix} response")
        for observation in series.get(prefix, []):
            day = observation["timestamp"][:10]
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
                raise ValueError("Invalid traffic timestamp")
            if day > capture_day:
                continue
            count, uniques = observation["count"], observation["uniques"]
            if any(not isinstance(x, int) or x < 0 for x in (count, uniques)):
                raise ValueError("Invalid traffic counts")
            entry = daily.setdefault(day, {})
            entry[prefix] = count
            entry["unique_visitors" if prefix == "views" else "unique_cloners"] = uniques
    if runs is not None:
        for day, count in runs.items():
            daily.setdefault(day, {})["workflow_runs"] = count
    snapshot = {
        "captured_at_utc": captured_at,
        "views_14d": {"count": views["count"], "uniques": views["uniques"]},
        "clones_14d": {"count": clones["count"], "uniques": clones["uniques"]},
        "referrers_14d": referrers,
        "popular_paths_14d": paths,
    }
    if stars is not None:
        snapshot["stars"] = stars
    if forks is not None:
        snapshot["forks"] = forks
    data["snapshots"][capture_day] = snapshot
    return data


def action_run_counts(repo: str, token: str, earliest: str) -> dict[str, int]:
    """Fetch recent GitHub Actions run counts by UTC day (not clone counts)."""
    counts: Counter[str] = Counter()
    for page in range(1, 11):
        response = api_request(repo, f"/actions/runs?per_page=100&page={page}", token)
        runs = response.get("workflow_runs", [])
        for item in runs:
            day = item["created_at"][:10]
            if earliest <= day:
                # Exclude the collector itself from the CI activity estimate.
                if item.get("name") != "GitHub Traffic History":
                    counts[day] += 1
        if len(runs) < 100 or runs[-1]["created_at"][:10] < earliest:
            return dict(counts)
    # Incomplete pagination must not be mistaken for zero activity.
    raise GitHubError("Too many workflow runs; raise pagination limit before storing")


def report_markdown(data: dict, *, days: int = 30) -> str:
    if not data["snapshots"]:
        return "# TenderCore GitHub Traffic\n\nNo snapshots have been recorded yet.\n"
    latest_date = max(data["snapshots"])
    latest = data["snapshots"][latest_date]
    first_day = (datetime.strptime(latest_date, "%Y-%m-%d") - timedelta(days=days - 1)).date().isoformat()
    entries = [(day, d) for day, d in sorted(data["daily"].items()) if first_day <= day <= latest_date]
    views = sum(e.get("views", 0) for _, e in entries)
    clones = sum(e.get("clones", 0) for _, e in entries)
    window = [x for x in entries if "views" in x[1] or "clones" in x[1]]
    peak = max(window, key=lambda item: item[1].get("clones", 0), default=None)
    lines = [
        "# TenderCore Europe — GitHub Traffic History", "",
        f"Latest snapshot: **{latest_date}** (UTC). Reporting interval: **{first_day}–{latest_date}**.", "",
        f"- Recorded page views over {days} calendar days: **{views}**.",
        f"- Recorded full clones over {days} calendar days: **{clones}**.",
        f"- Days with traffic observations: **{len(window)}** (missing dates are not zero).",
        f"- Peak clone day: **{peak[0]}** with **{peak[1].get('clones', 0)}** clones." if peak else "- Peak clone day: unavailable.",
        f"- Latest rolling 14-day unique visitors: **{latest['views_14d']['uniques']}**.",
        f"- Latest rolling 14-day unique cloners: **{latest['clones_14d']['uniques']}**.",
    ]
    if "stars" in latest:
        lines.append(f"- Repository stars at snapshot: **{latest['stars']}**; forks: **{latest['forks']}**.")
    lines += ["", "## Observations by UTC day", "", "| Date | Views | Daily unique visitors | Full clones | Daily unique cloners | Other Actions runs |", "|---|---:|---:|---:|---:|---:|"]
    for day, entry in reversed(entries):
        def shown(key):
            return str(entry[key]) if key in entry else "—"
        lines.append(f"| {day} | {shown('views')} | {shown('unique_visitors')} | {shown('clones')} | {shown('unique_cloners')} | {shown('workflow_runs')} |")
    lines += ["", "## Top referrers (latest 14-day rolling window)", "", "| Referrer | Views | Unique visitors |", "|---|---:|---:|"]
    for item in latest.get("referrers_14d", []):
        lines.append(f"| {item['referrer'].replace('|', '&#124;')} | {item['count']} | {item['uniques']} |")
    lines += ["", "## Interpretation and limitations", "",
        "- A full clone is **not** evidence of an individual developer, user, or adoption.",
        "- Unique users/cloners are deduplicated **within the GitHub rolling 14-day window**. Daily uniques must never be summed to estimate lifetime unique people.",
        "- Top referrers and paths are rolling 14-day aggregates, not daily or lifetime totals.",
        "- GitHub Actions run counts are contextual evidence only: do **not** subtract them from GitHub clone counts as a verified correction.",
        "- The collection workflow makes API requests without a repository checkout; ordinary CI workflows may still clone the repository.",
        "- Counts include the maintainer's activity if GitHub records it. No claim of independent external interest is established.",
        "- The archive is committed to a **public repository**; all aggregated numbers are publicly accessible.", "",
        "Source: GitHub REST Traffic API; see [`docs/github-traffic.md`](../../docs/github-traffic.md).", ""]
    return "\n".join(lines)


def read_github_file(repo: str, path: str, token: str, branch: str) -> tuple[str | None, str | None]:
    try:
        response = api_request(repo, f"/contents/{path}?ref={quote(branch, safe='')}", token)
    except GitHubError as exc:
        if str(exc) == "GitHub HTTP 404":
            return None, None
        raise
    if response.get("encoding") != "base64" or not response.get("sha"):
        raise GitHubError("Unexpected GitHub contents format")
    return base64.b64decode(response["content"]).decode("utf-8"), response["sha"]


def write_github_file(repo: str, path: str, content: str, token: str, branch: str, sha: str | None):
    body = {"message": f"chore(traffic): refresh {path}", "branch": branch,
            "content": base64.b64encode(content.encode("utf-8")).decode("ascii")}
    if sha:
        body["sha"] = sha
    return api_request(repo, f"/contents/{path}", token, method="PUT", payload=body)


def collect(repo: str, *, history_path: str, report_path: str, github_store: bool,
            branch: str, days: int = 30) -> dict:
    if not REPO_PATTERN.fullmatch(repo):
        raise ValueError("Invalid repository; use OWNER/REPO")
    traffic_token = os.environ.get("GH_TRAFFIC_TOKEN", "")
    content_token = os.environ.get("GITHUB_TOKEN", "")
    if not traffic_token:
        raise ValueError("GH_TRAFFIC_TOKEN is required (fine-grained PAT: Administration read)")
    if github_store and not content_token:
        raise ValueError("GITHUB_TOKEN is required to persist history via Contents API")
    if github_store:
        raw, sha = read_github_file(repo, HISTORY_PATH, content_token, branch)
        archive = check_archive(json.loads(raw), repo) if raw is not None else blank_archive(repo)
    else:
        archive = check_archive(json.loads(Path(history_path).read_text()), repo) if Path(history_path).exists() else blank_archive(repo)
        sha = None
    views = api_request(repo, "/traffic/views?per=day", traffic_token)
    clones = api_request(repo, "/traffic/clones?per=day", traffic_token)
    referrers = api_request(repo, "/traffic/popular/referrers", traffic_token)
    paths = api_request(repo, "/traffic/popular/paths", traffic_token)
    meta = api_request(repo, "", content_token or traffic_token)
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    earliest = (datetime.now(timezone.utc).date() - timedelta(days=13)).isoformat()
    runs = action_run_counts(repo, content_token or traffic_token, earliest)
    # Zero is only assigned to days for which the paginated Actions query is complete.
    for n in range(14):
        key = (datetime.now(timezone.utc).date() - timedelta(days=n)).isoformat()
        runs.setdefault(key, 0)
    archive = merge_traffic(archive, views, clones, referrers, paths, captured_at=now,
                            stars=meta.get("stargazers_count"), forks=meta.get("forks_count"), runs=runs)
    history = json.dumps(archive, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    report = report_markdown(archive, days=days)
    if github_store:
        write_github_file(repo, HISTORY_PATH, history, content_token, branch, sha)
        old_report, old_report_sha = read_github_file(repo, REPORT_PATH, content_token, branch)
        if old_report != report:
            write_github_file(repo, REPORT_PATH, report, content_token, branch, old_report_sha)
    else:
        for target, content in ((history_path, history), (report_path, report)):
            p = Path(target)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
    return archive


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    def args_for(sub):
        sub.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", "BeastRO1377/tendercore-europe"))
        sub.add_argument("--history", default=HISTORY_PATH)
        sub.add_argument("--report", default=REPORT_PATH)
        sub.add_argument("--days", type=int, default=30)
    a = commands.add_parser("collect", help="Collect GitHub Traffic API and persist archive/report")
    args_for(a)
    a.add_argument("--github-store", action="store_true", help="Save with GitHub Contents API; no checkout")
    a.add_argument("--branch", default="main")
    b = commands.add_parser("report", help="Print a report from a locally saved archive")
    args_for(b)
    args = parser.parse_args(argv)
    if not 1 <= args.days <= 3650:
        parser.error("--days must be between 1 and 3650")
    try:
        if args.command == "collect":
            archive = collect(args.repo, history_path=args.history, report_path=args.report,
                              github_store=args.github_store, branch=args.branch, days=args.days)
            print(f"Stored {len(archive['daily'])} traffic days; {len(archive['snapshots'])} snapshots")
        else:
            archive = check_archive(json.loads(Path(args.history).read_text(encoding="utf-8")), args.repo)
            print(report_markdown(archive, days=args.days), end="")
    except (GitHubError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"traffic collector: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
