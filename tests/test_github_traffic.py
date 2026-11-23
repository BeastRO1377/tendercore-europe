"""Offline correctness tests for the GitHub traffic archive and reports."""
import json
from unittest import TestCase
from unittest.mock import patch

from scripts import github_traffic as traffic


class TrafficArchiveTests(TestCase):
    def setUp(self):
        self.repo = "BeastRO1377/tendercore-europe"
        self.views = {"count": 9, "uniques": 2, "views": [
            {"timestamp": "2026-11-20T00:00:00Z", "count": 7, "uniques": 1},
            {"timestamp": "2026-11-21T00:00:00Z", "count": 2, "uniques": 2},
        ]}
        self.clones = {"count": 61, "uniques": 14, "clones": [
            {"timestamp": "2026-11-20T00:00:00Z", "count": 61, "uniques": 14},
            {"timestamp": "2026-11-21T00:00:00Z", "count": 0, "uniques": 0},
        ]}

    def make_archive(self):
        a = traffic.blank_archive(self.repo)
        return traffic.merge_traffic(a, self.views, self.clones, [], [],
                 captured_at="2026-11-21T12:00:00Z", runs={"2026-11-20": 13})

    def test_merging_same_snapshot_is_idempotent(self):
        archive = self.make_archive()
        before = json.dumps(archive, sort_keys=True)
        traffic.merge_traffic(archive, self.views, self.clones, [], [],
              captured_at="2026-11-21T12:00:00Z", runs={"2026-11-20": 13})
        self.assertEqual(json.dumps(archive, sort_keys=True), before)
        self.assertEqual(archive["daily"]["2026-11-20"]["clones"], 61)
        self.assertEqual(archive["daily"]["2026-11-20"]["workflow_runs"], 13)

    def test_next_day_updates_day_but_preserves_previous_history(self):
        a = self.make_archive()
        later_views = {"count": 10, "uniques": 1, "views": [
            {"timestamp": "2026-11-21T00:00:00Z", "count": 5, "uniques": 1},
            {"timestamp": "2026-11-22T00:00:00Z", "count": 5, "uniques": 1},
        ]}
        traffic.merge_traffic(a, later_views, self.clones, [], [],
              captured_at="2026-11-22T12:00:00Z")
        self.assertEqual(a["daily"]["2026-11-20"]["views"], 7)
        self.assertEqual(a["daily"]["2026-11-21"]["views"], 5)
        self.assertEqual(len(a["snapshots"]), 2)

    def test_does_not_sum_unique_visitors(self):
        report = traffic.report_markdown(self.make_archive())
        self.assertIn("Recorded page views over 30 calendar days: **9**", report)
        self.assertIn("Latest rolling 14-day unique visitors: **2**", report)
        self.assertNotIn("unique visitors: **3**", report)
        self.assertIn("do **not** subtract", report)

    def test_invalid_series_does_not_store_negative_metrics(self):
        self.views["views"][0]["count"] = -1
        with self.assertRaises(ValueError):
            self.make_archive()

    def test_mismatched_repo_rejected(self):
        with self.assertRaises(ValueError):
            traffic.check_archive(traffic.blank_archive(self.repo), "bad/repo")

    def test_actions_runs_do_not_equal_clones(self):
        def fake_api(repo, path, token, **kwargs):
            self.assertEqual(repo, self.repo)
            return {"workflow_runs": [
                {"created_at": "2026-11-20T13:00:00Z", "name": "Tests"},
                {"created_at": "2026-11-20T14:00:00Z", "name": "GitHub Traffic History"},
                {"created_at": "2026-11-19T13:00:00Z", "name": "Tests"},
            ]}
        with patch.object(traffic, "api_request", side_effect=fake_api):
            counts = traffic.action_run_counts(self.repo, "token", "2026-11-20")
        self.assertEqual(counts, {"2026-11-20": 1})

    def test_missing_history_report(self):
        self.assertIn("No snapshots", traffic.report_markdown(traffic.blank_archive(self.repo)))

    def test_authentication_missing_fails_before_network(self):
        with patch.dict("os.environ", {"GH_TRAFFIC_TOKEN": ""}):
            with self.assertRaisesRegex(ValueError, "GH_TRAFFIC_TOKEN"):
                traffic.collect(self.repo, history_path="/tmp/unused", report_path="/tmp/unused-report", github_store=False, branch="main")
