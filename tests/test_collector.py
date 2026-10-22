import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from urllib.error import HTTPError

from lab.collector import Collector, Store, demo_transport, next_link, spreadsheet_cell
from lab.core import LabError, Policy


def response(data, following=None):
    result = io.BytesIO(json.dumps(data).encode())
    result.status = 200
    result.headers = {"ETag": '"v1"'}
    if following:
        result.headers["Link"] = f'<{following}>; rel="next"'
    return result


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.store = Store(self.path / "state.sqlite3")
        self.policy = Policy(("secondary-a", "brunnojob"))
        self.url = "https://api.github.com/users/secondary-a/repos?type=owner&sort=full_name&direction=asc&per_page=1&page=2"
        self.item = {"full_name": "secondary-a/api-lab", "owner": {"login": "secondary-a", "id": 123}, "private": False, "description": "=DANGEROUS()"}

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def client(self, transport):
        return Collector(self.policy, self.store, transport, clock=lambda: 1000, sleep=Mock())

    def test_resumes_after_page_budget_and_deduplicates(self):
        client = self.client(demo_transport)
        self.assertFalse(client.collect("secondary-a", 1, 1)["complete"])
        self.assertTrue(client.collect("secondary-a", 1, 5)["complete"])
        report = self.store.export("secondary-a", self.path / "report")
        self.assertEqual(report["count"], 3)
        self.assertEqual(client.collect("secondary-a", 1, 5)["pages_requested"], 0)

    def test_checkpoint_survives_restart(self):
        self.client(demo_transport).collect("secondary-a", 1, 1)
        self.store.close()
        self.store = Store(self.path / "state.sqlite3")
        self.assertTrue(self.client(demo_transport).collect("secondary-a", 1, 5)["complete"])

    def test_failure_does_not_skip_page(self):
        transport = Mock(side_effect=[response([self.item], self.url), HTTPError("url", 500, "failed", {}, None)])
        with self.assertRaises(LabError):
            self.client(transport).collect("secondary-a", 1, 2)
        row = self.store.db.execute("SELECT next_url,complete FROM runs").fetchone()
        self.assertEqual(row, (self.url, 0))
        self.assertEqual(self.store.export("secondary-a", self.path / "partial")["count"], 1)

    def test_etag_survives_restart_and_refresh(self):
        self.client(Mock(return_value=response([self.item]))).collect("secondary-a", 1)
        transport = Mock(side_effect=HTTPError("url", 304, "cached", {}, None))
        self.client(transport).collect("secondary-a", 1, refresh=True)
        self.assertEqual(transport.call_args.args[0].get_header("If-none-match"), '"v1"')
        self.assertEqual(self.store.export("secondary-a", self.path / "report")["count"], 1)

    def test_main_account_never_reaches_transport(self):
        transport = Mock()
        with self.assertRaises(LabError):
            self.client(transport).collect("BRUNNOJOB")
        transport.assert_not_called()

    def test_malicious_pagination_is_not_requested_or_committed(self):
        for url in ("https://evil.example/page", self.url.replace("secondary-a", "brunnojob"), self.url + "&page=3"):
            transport = Mock(return_value=response([self.item], url))
            with self.assertRaises(LabError):
                self.client(transport).collect("secondary-a", 1, refresh=True)
            self.assertEqual(transport.call_count, 1)
            self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM items").fetchone()[0], 0)

    def test_private_or_wrong_owner_response_is_rejected(self):
        for item in (dict(self.item, private=True), dict(self.item, full_name="brunnojob/lab")):
            with self.assertRaises(LabError):
                self.client(Mock(return_value=response([item]))).collect("secondary-a", 1, refresh=True)

    def test_rate_limit_persists_between_clients(self):
        transport = Mock(side_effect=HTTPError("url", 429, "limit", {"Retry-After": "120"}, None))
        with self.assertRaises(LabError):
            self.client(transport).collect("secondary-a", 1)
        other = Mock()
        with self.assertRaisesRegex(LabError, "cooldown"):
            self.client(other).collect("secondary-a", 1)
        other.assert_not_called()
        self.assertEqual(self.store.db.execute("SELECT not_before FROM limits").fetchone()[0], 1120)

    def test_last_successful_request_exhausts_api_budget(self):
        page = response([self.item], self.url)
        page.headers.update({"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1300"})
        transport = Mock(return_value=page)
        with self.assertRaisesRegex(LabError, "cooldown"):
            self.client(transport).collect("secondary-a", 1, 2)
        self.assertEqual(transport.call_count, 1)
        self.assertEqual(self.store.export("secondary-a", self.path / "partial")["count"], 1)

    def test_csv_formula_is_escaped_and_json_is_original(self):
        self.client(Mock(return_value=response([self.item]))).collect("secondary-a", 1)
        self.store.export("secondary-a", self.path / "report")
        self.assertIn("'=DANGEROUS()", (self.path / "report.csv").read_text(encoding="utf-8-sig"))
        self.assertEqual(json.loads((self.path / "report.json").read_text())["repositories"][0]["description"], "=DANGEROUS()")
        self.assertEqual(spreadsheet_cell("  +formula"), "'  +formula")

    def test_invalid_page_size_does_not_call_transport(self):
        transport = Mock()
        with self.assertRaises(LabError):
            self.client(transport).collect("secondary-a", 101)
        transport.assert_not_called()

    def test_checkpoint_page_size_cannot_change(self):
        self.client(demo_transport).collect("secondary-a", 1, 1)
        with self.assertRaisesRegex(LabError, "Page size"):
            self.client(demo_transport).collect("secondary-a", 2)

    def test_pagination_uses_next_relation(self):
        self.assertEqual(next_link(f'<{self.url}>; rel="next", <other>; rel="last"'), self.url)
        self.assertIsNone(next_link('<other>; rel="last"'))

    def test_canonical_numeric_pagination_is_bound_to_owner_id(self):
        following = self.url.replace("users/secondary-a", "user/123")
        transport = Mock(side_effect=[response([self.item], following), response([])])
        self.assertTrue(self.client(transport).collect("secondary-a", 1, 2)["complete"])
        self.assertEqual(transport.call_args.args[0].full_url, following)

    def test_wrong_numeric_owner_id_is_blocked(self):
        following = self.url.replace("users/secondary-a", "user/999")
        transport = Mock(return_value=response([self.item], following))
        with self.assertRaisesRegex(LabError, "approved endpoint"):
            self.client(transport).collect("secondary-a", 1, 2)
        self.assertEqual(transport.call_count, 1)

    def test_schema_failure_does_not_advance_checkpoint(self):
        for data in ({"message": "failed"}, ["invalid"], [dict(self.item, full_name=None)]):
            with self.assertRaises(LabError):
                self.client(Mock(return_value=response(data))).collect("secondary-a", 1, refresh=True)
        self.assertEqual(self.store.db.execute("SELECT complete FROM runs").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
