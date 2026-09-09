import contextlib
import datetime
import http.client
import io
import json
import os
from pathlib import Path
import plistlib
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import xml.etree.ElementTree as ET

import tick


class Response(io.BytesIO):
    def __init__(self, result=None, ident=1, content_type="application/json", status=200, headers=None, raw=None):
        super().__init__(raw if raw is not None else json.dumps({"jsonrpc": "2.0", "id": ident, "result": result}).encode())
        self.headers = {"Content-Type": content_type, **(headers or {})}
        self.status = status


class FrozenDateTime(datetime.datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 9, 9, 10, 30, tzinfo=tz)


class TickTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cfg = Path(self.temp.name) / ".ticktick"
        self.patch_cfg = patch.object(tick, "CFG", str(self.cfg))
        self.patch_cfg.start()
        self.addCleanup(self.patch_cfg.stop)
        self.frozen = patch.object(tick.datetime, "datetime", FrozenDateTime)
        self.frozen.start()
        self.addCleanup(self.frozen.stop)
        self.env = patch.dict(os.environ, {"TZ": "Asia/Shanghai"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def run_main(self, args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = tick.main(args)
        return code, output.getvalue()

    def configured(self, token="test-token-123"):
        tick.write_config({"token": token, "projectId": "inbox"})

    def init_response(self):
        return Response({"protocolVersion": "2025-03-26", "capabilities": {"tools": {}}}, headers={"Mcp-Session-Id": "session-test"})

    def auth_responses(self, projects=None):
        return [
            self.init_response(),
            Response(status=202),
            Response(
                {
                    "tools": [
                        {"name": "create_task", "inputSchema": {"properties": {"task": {"type": "object"}}}},
                        {"name": "list_projects", "inputSchema": {"properties": {}}},
                    ]
                },
                ident=2,
            ),
            Response({"content": [{"type": "text", "text": json.dumps(projects if projects is not None else [{"id": "inbox"}])}]}, ident=3),
        ]

    def test_task_mapping_and_existing_dates(self):
        cases = [
            ("任务", "任务", None, None, 0, None),
            ("任务 tmr", "任务", "2026-09-10T00:00", True, 0, None),
            ("任务 tomorrow 12:15", "任务", "2026-09-10T12:15", False, 0, None),
            ("任务 09:00", "任务", "2026-09-10T09:00", False, 0, None),
            ("任务 12:00", "任务", "2026-09-09T12:00", False, 0, None),
            ("任务 mon", "任务", "2026-09-14T00:00", True, 0, None),
            ("任务 next fri", "任务", "2026-09-18T00:00", True, 0, None),
            ("任务 01-02", "任务", "2027-01-02T00:00", True, 0, None),
            ("!任务", "任务", None, None, 1, None),
            ("任务 !! tmr", "任务", "2026-09-10T00:00", True, 3, None),
            ("!!!任务 every mon 09:00", "任务", "2026-09-14T09:00", False, 5, "WEEKLY"),
            ("任务 every 09-15", "任务", "2026-09-15T00:00", True, 0, "MONTHLY"),
            ("任务 every 12:00", "任务", "2026-09-09T12:00", False, 0, "DAILY"),
        ]
        for query, title, date, all_day, priority, repeat in cases:
            with self.subTest(query=query):
                item = tick.generate_item(query, "inbox")
                self.assertEqual(item["title"], title)
                self.assertEqual(item["projectId"], "inbox")
                self.assertEqual(item["priority"], priority)
                self.assertEqual(item.get("isAllDay"), all_day)
                if date:
                    self.assertTrue(item["startDate"].startswith(date), item)
                    self.assertEqual(item["dueDate"], item["startDate"])
                    self.assertEqual(item["timeZone"], "Asia/Shanghai")
                else:
                    self.assertNotIn("dueDate", item)
                self.assertEqual(item.get("reminders", []), [tick.DEFAULT_TRIGGER] if all_day is False else [])
                if repeat:
                    self.assertEqual(item["repeatFlag"], "RRULE:FREQ=%s;INTERVAL=1" % repeat)
                else:
                    self.assertNotIn("repeatFlag", item)
                self.assertFalse({"id", "modifiedTime", "reminder", "progress", "items", "cookie"} & item.keys())

    def test_preview_escaping_and_original_argument(self):
        query = "买 \"A&B\" <tea> '中文' tmr"
        code, output = self.run_main(["parse", query])
        self.assertEqual(code, 0)
        root = ET.fromstring(output)
        self.assertEqual(root.find("item").attrib["arg"], query)
        self.assertIn("A&B", root.find("item/title").text)
        self.assertIn("2026-09-10", root.find("item/title").text)

    def test_bad_inputs_do_not_connect(self):
        self.configured()
        with patch.object(tick, "MCPClient") as client:
            for args in ([], ["parse", "task 25:99"], ["task 02-31"], [""], ["!!!!task"], ["auth", "bad\nheader"]):
                with self.subTest(args=args):
                    self.assertEqual(self.run_main(args)[0], 1)
            client.assert_not_called()

    def test_obfuscation_and_strict_decode(self):
        for token in ("short", "abc.DEF_~+/==", "x" * 1000):
            encrypted = tick.encrypt_token(token)
            self.assertNotIn(token, encrypted)
            self.assertEqual(tick.decrypt_token(encrypted), token)
        for value in (None, "", "a", "plaintext", "00", "ff" * 50):
            with self.subTest(value=value), self.assertRaises(tick.TickError):
                tick.decrypt_token(value)

    def test_atomic_config_migration_permissions_and_truncation(self):
        self.cfg.write_text("user=legacy\npwd=legacy-password\ncookie=legacy-cookie\n" + "x" * 2000)
        self.cfg.chmod(0o644)
        self.configured("a-longer-token-1234567890")
        self.configured("short")
        raw = self.cfg.read_text()
        self.assertNotIn("short", raw)
        self.assertNotIn("legacy", raw)
        self.assertEqual(set(json.loads(raw)), {"version", "token", "projectId"})
        self.assertEqual(tick.read_config(), {"token": "short", "projectId": "inbox"})
        self.assertEqual(stat.S_IMODE(self.cfg.stat().st_mode), 0o600)
        self.assertEqual(list(Path(self.temp.name).iterdir()), [self.cfg])
        with patch.object(tick.os, "replace", side_effect=OSError("failed")), self.assertRaises(OSError):
            self.configured("replacement")
        self.assertEqual(self.cfg.read_text(), raw)
        self.assertEqual(list(Path(self.temp.name).iterdir()), [self.cfg])

    def test_missing_legacy_corrupt_configs_do_not_connect(self):
        for raw in (None, "user=old\npwd=old", "{}", "[]", '{"version":1,"token":"bad","projectId":"inbox"}'):
            if raw is not None:
                self.cfg.write_text(raw)
            with patch.object(tick, "MCPClient") as client:
                code, output = self.run_main(["task"])
                self.assertEqual(code, 1)
                self.assertIn("tick_auth", output)
                client.assert_not_called()

    def test_authorization_and_protocol_headers(self):
        with patch.object(tick.urllib.request.OpenerDirector, "open", side_effect=self.auth_responses()) as op:
            code, output = self.run_main(["auth", "new-token"])
        self.assertEqual(code, 0, output)
        self.assertEqual(tick.read_config(), {"token": "new-token", "projectId": "inbox"})
        self.assertNotIn("new-token", output)
        requests = [call.args[0] for call in op.call_args_list]
        bodies = [json.loads(r.data) for r in requests]
        self.assertEqual([b["method"] for b in bodies], ["initialize", "notifications/initialized", "tools/list", "tools/call"])
        self.assertNotIn("id", bodies[1])
        self.assertEqual(bodies[-1]["params"], {"name": "list_projects", "arguments": {}})
        self.assertTrue(all(r.full_url == tick.MCP_URL for r in requests))
        for r in requests:
            self.assertEqual(r.get_header("Authorization"), "Bearer new-token")
            self.assertEqual(r.get_header("Accept"), "application/json, text/event-stream")
            self.assertIsNone(r.get_header("Cookie"))
        for r in requests[1:]:
            self.assertEqual(r.get_header("Mcp-session-id"), "session-test")
            self.assertEqual(r.get_header("Mcp-protocol-version"), "2025-03-26")

    def test_authorization_failure_preserves_config_and_hides_secrets(self):
        self.configured("old-token")
        raw = self.cfg.read_bytes()
        for error in (
            urllib.error.HTTPError(tick.MCP_URL, 401, "new-secret", {}, None),
            urllib.error.URLError("new-secret"),
            RuntimeError("new-secret"),
        ):
            with patch.object(tick.urllib.request.OpenerDirector, "open", side_effect=error):
                code, output = self.run_main(["auth", "new-secret"])
            self.assertEqual(code, 1)
            self.assertNotIn("new-secret", output)
            self.assertEqual(self.cfg.read_bytes(), raw)
        for projects in ([], [{"id": "work"}], [{"id": "inbox"}, {"id": "inbox123"}]):
            with patch.object(tick.urllib.request.OpenerDirector, "open", side_effect=self.auth_responses(projects)):
                self.assertEqual(self.run_main(["auth", "new-token"])[0], 1)
            self.assertEqual(self.cfg.read_bytes(), raw)

    def test_project_list_structured_and_multiple_text_blocks(self):
        variants = [
            {"structuredContent": {"result": [{"id": "work"}, {"id": "inbox123"}]}},
            {"content": [{"type": "text", "text": '{"id":"work"}'}, {"type": "text", "text": '{"id":"inbox123"}'}]},
            {"content": [{"type": "text", "text": '{"id":"inbox123"}'}]},
        ]
        for payload in variants:
            responses = self.auth_responses()
            responses[-1] = Response(payload, ident=3)
            with patch.object(tick.urllib.request.OpenerDirector, "open", side_effect=responses):
                code, output = self.run_main(["auth", "new-token"])
            self.assertEqual(code, 0, output)
            self.assertEqual(tick.read_config()["projectId"], "inbox123")

    def test_successful_task_requires_id_and_correct_wrapper(self):
        self.configured()
        responses = [
            self.init_response(),
            Response(status=202),
            Response({"structuredContent": {"id": "task-123", "projectId": "inbox"}}, ident=2),
        ]
        with patch.object(tick.urllib.request.OpenerDirector, "open", side_effect=responses) as op:
            code, output = self.run_main(["任务 tmr 12:15"])
        self.assertEqual(code, 0, output)
        self.assertIn("成功", output)
        body = json.loads(op.call_args_list[-1].args[0].data)
        self.assertEqual(body["params"]["name"], "create_task")
        self.assertEqual(list(body["params"]["arguments"]), ["task"])
        self.assertEqual(body["params"]["arguments"]["task"]["reminders"], ["TRIGGER:-PT1M"])
        self.assertEqual(op.call_count, 3)

    def test_create_failures_never_retry_or_report_success(self):
        self.configured()
        results = [
            lambda: Response({"isError": True, "content": [{"type": "text", "text": "test-token-123"}]}, ident=2),
            lambda: Response({"structuredContent": {"error": "test-token-123"}}, ident=2),
            lambda: Response({"structuredContent": {}}, ident=2),
            lambda: Response({"content": [None]}, ident=2),
            lambda: Response(raw=b'{"jsonrpc":"2.0","id":2,"error":{"message":"test-token-123"}}'),
            lambda: Response({}, ident=999),
            lambda: Response(raw=b"not-json"),
            lambda: TimeoutError("test-token-123"),
            lambda: http.client.IncompleteRead(b"test-token-123"),
            lambda: urllib.error.HTTPError(tick.MCP_URL, 503, "test-token-123", {}, None),
        ]
        for make_result in results:
            with self.subTest(result=make_result):
                with patch.object(
                    tick.urllib.request.OpenerDirector, "open", side_effect=[self.init_response(), Response(status=202), make_result()]
                ) as op:
                    code, output = self.run_main(["任务"])
                self.assertEqual(code, 1)
                self.assertNotIn("增加任务成功", output)
                self.assertNotIn("test-token-123", output)
                self.assertIn("检查收集箱", output)
                self.assertEqual(op.call_count, 3)

    def test_event_stream_notifications_multiline_and_early_return(self):
        raw = (
            b': keepalive\r\n\r\nevent: message\r\ndata: {"jsonrpc":"2.0","method":"notifications/progress"}\r\n\r\n'
            b'data: {"jsonrpc":"2.0",\r\ndata: "id":1,"result":{"ok":true}}\r\n\r\n'
            b"data: malformed trailing data\n\n"
        )
        with patch.object(tick.urllib.request.OpenerDirector, "open", return_value=Response(content_type="text/event-stream", raw=raw)):
            result = tick.MCPClient("fake-token").request("test", {})
        self.assertEqual(result, {"ok": True})
        for raw in (b"", b": comment\n\n", b"data: invalid\n\n"):
            with (
                patch.object(tick.urllib.request.OpenerDirector, "open", return_value=Response(content_type="text/event-stream", raw=raw)),
                self.assertRaises(tick.TickError),
            ):
                tick.MCPClient("fake-token").request("test", {})

    def test_tool_list_pagination(self):
        responses = [
            Response({"tools": [{"name": "list_projects"}], "nextCursor": "next"}, ident=1),
            Response({"tools": [{"name": "create_task", "inputSchema": {"properties": {"task": {}}}}]}, ident=2),
        ]
        with patch.object(tick.urllib.request.OpenerDirector, "open", side_effect=responses) as op:
            tick.MCPClient("fake-token").validate_tools()
        self.assertEqual(json.loads(op.call_args_list[1].args[0].data)["params"], {"cursor": "next"})

    def test_redirects_are_not_followed(self):
        self.assertIsNone(tick.NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.example"))

    def test_dst_timezone_import_and_date(self):
        env = dict(os.environ, TZ="America/New_York", PYTHONDONTWRITEBYTECODE="1")
        result = subprocess.run(
            ["/usr/bin/python3", "-c", "import tick; print(tick.generate_item('task tmr 12:00', 'inbox')['timeZone'])"],
            env=env,
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "America/New_York")


class ArtifactTests(unittest.TestCase):
    def test_alfred_arguments_keywords_and_notifications(self):
        info = plistlib.loads(Path("info.plist").read_bytes())
        self.assertEqual(info["version"], "1.11")
        self.assertEqual(info["name"], "滴答清单 v1.11")
        configs = [obj["config"] for obj in info["objects"]]
        self.assertEqual({c["keyword"] for c in configs if "keyword" in c}, {"tick", "tick_auth"})
        for c in configs:
            if "script" in c:
                self.assertEqual(c["scriptargtype"], 1)
                self.assertIn('"$1"', c["script"])
                self.assertNotIn("{query}", c["script"])
        notifications = [obj["config"] for obj in info["objects"] if obj["type"] == "alfred.workflow.output.notification"]
        self.assertTrue(all(c["text"] == "{query}" for c in notifications))

    def test_shell_passes_literal_query(self):
        info = plistlib.loads(Path("info.plist").read_bytes())
        parse_script = next(o["config"]["script"] for o in info["objects"] if o["type"] == "alfred.workflow.input.scriptfilter")
        query = "任务 \"quoted\" 'single' $HOME $(echo should-not-run) `echo no` & < >"
        result = subprocess.run(
            ["/bin/bash", "-c", parse_script, "alfred", query],
            text=True,
            capture_output=True,
            env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(ET.fromstring(result.stdout).find("item").attrib["arg"], query)


if __name__ == "__main__":
    unittest.main()
