import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock, Mock, patch
from zipfile import ZipFile

import requests

import main
from bdo_marketplace_tools.market.api_handler import APIHandler, MarketplaceNetworkError, MarketplaceResponseError
from bdo_marketplace_tools.services.diagnostics import DiagnosticRecorder
from bdo_marketplace_tools.services.event_log import EventLog


PUBLIC_URL = "https://na-trade.naeu.playblackdesert.com/Trademarket/GetWorldMarketList"


def response(body, *, status=200, url=PUBLIC_URL, headers=None):
    value = requests.Response()
    value._content = body
    value.status_code = status
    value.reason = "Service Unavailable" if status == 503 else "OK"
    value.url = url
    value.headers.update(headers or {})
    return value


def read_report(path):
    with ZipFile(path) as archive:
        return json.loads(archive.read("report.json")), {name: archive.read(name) for name in archive.namelist()}


class DiagnosticReportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name) / "diagnostics"
        self.recorder = DiagnosticRecorder(self.directory)

    def test_exact_binary_body_and_safe_response_metadata(self):
        raw = b"\x81\x00\x00\x00broken marketplace data\xff"
        value = response(raw, headers={"Content-Type": "application/octet-stream", "Set-Cookie": "secret"})
        path = self.recorder.record("Decode failed", response=value, method="POST")
        report, files = read_report(path)
        self.assertEqual(files["response.bin"], raw)
        self.assertEqual(report["response"]["status_code"], 200)
        self.assertEqual(report["response"]["headers"], {"Content-Type": "application/octet-stream"})
        self.assertFalse(report["response"]["truncated"])
        self.assertNotIn(b"secret", b"".join(files.values()))

    def test_nested_authenticated_json_is_redacted(self):
        raw = json.dumps({"resultCode": -16, "resultMsg": "not enough silver", "nested": {
            "TradeAuth_Session": "session-secret", "__RequestVerificationToken": "token-secret",
            "email": "user@example.com", "otp": "123456", "password": "password-secret"}}).encode()
        value = response(raw, url="https://example.com/GameTradeMarket/BuyItem?token=url-secret",
                         headers={"Set-Cookie": "cookie-secret", "Authorization": "Bearer auth-secret"})
        path = self.recorder.record("Purchase failed", response=value,
                                    parameters={"buyMainKey": "10007", "otp": "123456"})
        report, files = read_report(path)
        saved = json.loads(files["response.json"])
        self.assertEqual(saved["resultCode"], -16)
        self.assertEqual(saved["resultMsg"], "not enough silver")
        self.assertTrue(all(item == "[redacted]" for item in saved["nested"].values()))
        self.assertEqual(report["request"]["parameters"], {"buyMainKey": "10007"})
        for secret in (b"session-secret", b"token-secret", b"123456", b"password-secret", b"url-secret", b"cookie-secret"):
            self.assertNotIn(secret, b"".join(files.values()))

    def test_malformed_binary_without_null_bytes_is_preserved_exactly(self):
        raw = b"\xff\xfe\xfdmalformed"
        path = self.recorder.record("Decode failed", response=response(raw))
        _, files = read_report(path)
        self.assertEqual(files["response.bin"], raw)

    def test_private_html_body_is_omitted(self):
        value = response(b'<html><input value="private-secret"></html>', url="https://example.com/Home/AppSessionRefresh")
        report, files = read_report(self.recorder.record("Refresh failed", response=value))
        self.assertEqual(list(files), ["report.json"])
        self.assertIn("omitted", report["response"]["body_policy"])

    def test_public_html_keeps_error_page_but_redacts_challenge_values(self):
        value = response(b'<html><title>503 Service Unavailable</title><script>token="secret"</script>'
                         b'<input name="token" value="secret"><p>user@example.com</p></html>')
        report, files = read_report(self.recorder.record("Request failed", response=value))
        self.assertIn(b"503 Service Unavailable", files["response.txt"])
        self.assertNotIn(b"secret", files["response.txt"])
        self.assertNotIn(b"user@example.com", files["response.txt"])

    def test_repeated_failure_updates_one_report(self):
        value = response(b"\x00broken")
        first = self.recorder.record("Failed", response=value)
        second = self.recorder.record("Failed", response=value)
        report, _ = read_report(second)
        self.assertEqual(first, second)
        self.assertEqual(report["occurrences"], 2)
        self.assertEqual(len(list(self.directory.glob("*.zip"))), 1)

    def test_retention_and_body_size_are_bounded(self):
        recorder = DiagnosticRecorder(self.directory, report_limit=2, body_limit=8)
        for number in range(3):
            latest = recorder.record(f"Failure {number}", response=response(b"\x00" * 20))
        report, files = read_report(latest)
        self.assertEqual(len(list(self.directory.glob("*.zip"))), 2)
        self.assertEqual(files["response.bin"], b"\x00" * 8)
        self.assertTrue(report["response"]["truncated"])
        self.assertEqual(report["response"]["body_bytes"], 20)
        self.assertEqual(len(recorder._recent), 2)

    def test_write_failure_is_best_effort_and_visible(self):
        self.directory.write_text("not a directory")
        self.assertIsNone(self.recorder.record("Failed"))
        log = EventLog(diagnostics=self.recorder)
        log.add("Failed", "error")
        self.assertIn("Diagnostic save failed", log.plain_events[0])

    def test_error_events_capture_exception_chain_without_locals(self):
        log = EventLog(diagnostics=self.recorder)
        try:
            try:
                private_local = "do-not-record-local-values"
                raise ValueError("invalid data")
            except ValueError as exc:
                raise RuntimeError("Monitor failed") from exc
        except RuntimeError:
            log.add("Monitor failed", "error")
        report, files = read_report(next(self.directory.glob("*.zip")))
        self.assertEqual([item["type"] for item in report["exceptions"]], ["RuntimeError", "ValueError"])
        self.assertTrue(report["exceptions"][1]["frames"])
        self.assertNotIn(private_local.encode(), b"".join(files.values()))
        self.assertIn("Diagnostic file:", log.plain_events[0])

    def test_ui_coalescing_survives_diagnostic_paths(self):
        log = EventLog(diagnostics=self.recorder)
        log.add("Failed", "error")
        log.add("Failed", "error")
        self.assertEqual(len(log.records), 1)
        self.assertIn("×2", log.plain_events[0])
        report, _ = read_report(next(self.directory.glob("*.zip")))
        self.assertEqual(report["occurrences"], 2)

    def test_normal_events_do_not_write_reports(self):
        log = EventLog(diagnostics=self.recorder)
        for level in ("info", "success", "warning"):
            log.add("Routine event", level)
        self.assertFalse(self.directory.exists())

    def test_concurrent_repeated_errors_reuse_a_valid_report(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            paths = list(pool.map(lambda _: self.recorder.record("Same failure"), range(48)))
        self.assertEqual(len(set(paths)), 1)
        report, _ = read_report(paths[0])
        self.assertEqual(report["occurrences"], 48)

    def test_deferred_warning_keeps_original_exception(self):
        error = OSError("database locked")
        log = EventLog(diagnostics=self.recorder)
        log.add("Stats write failed", "warning", exception=error)
        report, _ = read_report(next(self.directory.glob("*.zip")))
        self.assertEqual(report["exceptions"][0]["type"], "OSError")

    def test_exception_message_redacts_cookie_assignments(self):
        path = self.recorder.record("Error", exception=RuntimeError("Cookie=secret; password=hidden"))
        _, files = read_report(path)
        self.assertNotIn(b"secret", files["report.json"])
        self.assertNotIn(b"hidden", files["report.json"])


class DiagnosticApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.recorder = DiagnosticRecorder(Path(self.temporary.name) / "diagnostics")
        self.handler = object.__new__(APIHandler)
        self.handler.diagnostics = self.recorder

    async def test_503_is_captured_before_decoding(self):
        value = response(b"503 Service Unavailable", status=503, headers={"Retry-After": "60"})
        client = Mock()
        client.request.return_value = value
        with self.assertRaises(MarketplaceNetworkError) as caught:
            await self.handler._request(client, "POST", PUBLIC_URL, "male outfit stock check", json={"subCategory": 1})
        report, files = read_report(caught.exception.diagnostic_path)
        self.assertEqual(report["response"]["status_code"], 503)
        self.assertEqual(files["response.txt"], value.content)
        self.assertEqual(report["request"]["parameters"], {"subCategory": 1})
        self.assertEqual(report["exceptions"][1]["type"], "HTTPError")
        self.assertIn("503", str(caught.exception))
        log = EventLog(diagnostics=self.recorder)
        log.add(f"Monitor cycle failed: {caught.exception}", "error")
        self.assertEqual(len(list(self.recorder.directory.glob("*.zip"))), 1)

    async def test_timeout_has_exception_details_without_a_response(self):
        client = Mock()
        client.request.side_effect = requests.Timeout("timed out")
        with self.assertRaises(MarketplaceNetworkError) as caught:
            await self.handler._request(client, "POST", PUBLIC_URL, "stock check")
        report, _ = read_report(caught.exception.diagnostic_path)
        self.assertNotIn("response", report)
        self.assertEqual(report["exceptions"][1]["type"], "Timeout")

    async def test_decode_failure_preserves_exact_response_and_underlying_exception(self):
        value = response(b"\x81\x00\x00\x00")
        self.handler._request = AsyncMock(return_value=value)
        with self.assertRaises(MarketplaceResponseError) as caught:
            await self.handler.check_stock()
        report, files = read_report(caught.exception.diagnostic_path)
        self.assertEqual(files["response.bin"], value.content)
        self.assertEqual(report["exceptions"][1]["type"], "error")  # struct.error
        self.assertIn("unpack", report["exceptions"][1]["message"])
        self.assertTrue(report["exceptions"][1]["frames"])

    async def test_malformed_decoded_rows_also_preserve_response(self):
        value = response(b"\x00broken")
        self.handler._request = AsyncMock(return_value=value)
        with patch("bdo_marketplace_tools.market.api_handler.unpack", return_value="broken-row"):
            with self.assertRaises(MarketplaceResponseError) as caught:
                await self.handler.check_stock()
        _, files = read_report(caught.exception.diagnostic_path)
        self.assertEqual(files["response.bin"], value.content)

    def test_invalid_json_response_has_report(self):
        value = response(b"not JSON", url="https://example.com/Home/AppSessionRefresh")
        with self.assertRaises(MarketplaceResponseError) as caught:
            self.handler._json_response(value, "session refresh")
        report, _ = read_report(caught.exception.diagnostic_path)
        self.assertIn("JSON", report["exceptions"][1]["type"])

    async def test_failed_purchase_result_is_saved_with_body(self):
        self.handler.login_status = True
        self.handler.session = requests.Session()
        self.handler.session.cookies.set("TradeAuth_Session", "secret")
        value = response(b'{"resultCode":-16,"resultMsg":"not enough silver"}', url="https://example.com/GameTradeMarket/BuyItem")
        self.handler._session_request = AsyncMock(return_value=value)
        result = await self.handler.buy_item([["10007", "1", "100"]])
        path = next(self.recorder.directory.glob("*.zip"))
        report, files = read_report(path)
        self.assertEqual(json.loads(files["response.json"])["resultCode"], -16)
        self.assertTrue(any("Diagnostic file:" in item["message"] for item in result["events"]))
        self.assertEqual(result["purchased"], 0)

    async def test_expected_purchase_rejections_keep_warning_without_diagnostics(self):
        self.handler.login_status = True
        self.handler.session = requests.Session()
        self.handler.session.cookies.set("TradeAuth_Session", "secret")
        for code, reason in ((30, "an identical order already exists"),
                             (34, "item was unavailable or would create a duplicate pre-order")):
            with self.subTest(result_code=code):
                value = response(json.dumps({"resultCode": code}).encode(), url="https://example.com/GameTradeMarket/BuyItem")
                self.handler._session_request = AsyncMock(return_value=value)
                result = await self.handler.buy_item([["10007", "2", "100"]])
                self.assertEqual(result["attempted"], 1)
                self.assertEqual(result["purchased"], 0)
                self.assertEqual(result["results"][0]["result_code"], code)
                self.assertTrue(any(reason in event["message"] for event in result["events"]))
                log = EventLog(diagnostics=self.recorder)
                for event in result["events"]:
                    log.add(event["message"], event["level"], notable=True)
                self.assertFalse(any("Diagnostic" in line for line in log.plain_events))
                self.assertFalse(self.recorder.directory.exists())

    async def test_diagnostic_disk_failure_does_not_replace_original_error(self):
        self.recorder.directory.write_text("not a directory")
        self.handler._request = AsyncMock(return_value=response(b"broken"))
        with self.assertRaisesRegex(MarketplaceResponseError, "could not be decoded") as caught:
            await self.handler.check_stock()
        self.assertIn("Diagnostic save failed", str(caught.exception))

    async def test_successful_scan_does_not_write_report(self):
        self.handler._request = AsyncMock(return_value=response(b"data"))
        with patch("bdo_marketplace_tools.market.api_handler.unpack", return_value="10007-1-0-100|"):
            self.assertEqual(await self.handler.check_stock(), [["10007", "1", "100"]] * 2)
        self.assertFalse(self.recorder.directory.exists())

    async def test_uncaught_application_error_saves_developer_report_and_restores_handler(self):
        loop = asyncio.get_running_loop()
        previous = loop.get_exception_handler()
        with patch.object(main, "DATA_DIR", Path(self.temporary.name)), patch.object(main, "run_app", side_effect=RuntimeError("startup failed")), patch("sys.stderr"):
            with self.assertRaisesRegex(RuntimeError, "startup failed"):
                await main.main(["--test-mode"])
        self.assertEqual(loop.get_exception_handler(), previous)
        path = next((Path(self.temporary.name) / "diagnostics.test").glob("*.zip"))
        report, _ = read_report(path)
        self.assertEqual(report["exceptions"][0]["type"], "RuntimeError")
