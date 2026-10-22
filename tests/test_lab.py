import io
import json
import unittest
from unittest.mock import Mock
from urllib.error import HTTPError

from lab.core import GitHubReader, LabError, NoRedirect, Policy, simulate


class Response(io.BytesIO):
    status = 200
    headers = {"ETag": '"v1"'}


class LabTests(unittest.TestCase):
    def setUp(self):
        self.policy = Policy(("secondary-a", "brunnojob"))
        self.data = {"full_name": "secondary-a/lab", "description": "Lab", "license": {"key": "mit"}, "has_issues": True}

    def test_main_account_is_always_excluded(self):
        transport = Mock()
        for target in ("brunnojob/lab", "BRUNNOJOB/lab"):
            with self.assertRaises(LabError):
                GitHubReader(self.policy, transport).repository(target)
        transport.assert_not_called()

    def test_allowlist_is_required(self):
        with self.assertRaises(LabError):
            self.policy.validate("another-owner/lab")

    def test_path_injection_is_rejected(self):
        for target in ("secondary-a/../brunnojob", "secondary-a/lab?x=1", "secondary-a/%2e%2e", "secondary-a/.."):
            with self.assertRaises(LabError):
                self.policy.validate(target)

    def test_read_only_anonymous_request(self):
        transport = Mock(return_value=Response(json.dumps(self.data).encode()))
        result = GitHubReader(self.policy, transport).repository("secondary-a/lab")
        req = transport.call_args.args[0]
        self.assertEqual(req.get_method(), "GET")
        self.assertFalse(req.has_header("Authorization"))
        self.assertEqual(req.full_url, "https://api.github.com/repos/secondary-a/lab")
        self.assertEqual(result["passed"], 4)

    def test_etag_and_304(self):
        transport = Mock(side_effect=[Response(json.dumps(self.data).encode()), HTTPError("url", 304, "cached", {}, None)])
        reader = GitHubReader(self.policy, transport)
        self.assertEqual(reader.repository("secondary-a/lab"), reader.repository("secondary-a/lab"))
        self.assertEqual(transport.call_args.args[0].get_header("If-none-match"), '"v1"')

    def test_rate_limit_stops_without_retry(self):
        for status in (403, 429):
            transport = Mock(side_effect=HTTPError("url", status, "stop", {"Retry-After": "60"}, None))
            with self.assertRaisesRegex(LabError, "stopped without retry"):
                GitHubReader(self.policy, transport).repository("secondary-a/lab")
            self.assertEqual(transport.call_count, 1)

    def test_budget_stops_network_calls(self):
        transport = Mock(side_effect=lambda *a, **k: Response(json.dumps(self.data).encode()))
        reader = GitHubReader(self.policy, transport, budget=1)
        reader.repository("secondary-a/lab")
        with self.assertRaises(LabError):
            reader.repository("secondary-a/lab")
        self.assertEqual(transport.call_count, 1)

    def test_identity_mismatch(self):
        transport = Mock(return_value=Response(b'{"full_name":"brunnojob/lab"}'))
        with self.assertRaisesRegex(LabError, "identity mismatch"):
            GitHubReader(self.policy, transport).repository("secondary-a/lab")

    def test_redirects_are_not_followed(self):
        self.assertIsNone(NoRedirect().redirect_request(None, None, 301, "moved", {}, "https://example.org"))

    def test_offline_simulation(self):
        result = simulate()
        self.assertEqual(result["network_requests"], 0)
        self.assertEqual(result["final_status"], "completed")
        self.assertEqual({event["actor"] for event in result["events"]}, {"secondary-a", "secondary-b"})


if __name__ == "__main__":
    unittest.main()
