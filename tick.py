#!/usr/bin/python3
import json
import datetime
import time
import os.path
import re
import sys
import os
import urllib.request
import urllib.error
import tempfile
import http.client
from xml.sax.saxutils import escape, quoteattr
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MCP_URL = "https://mcp.dida365.com"
VERSION = "1.11"
AUTH_HINT = "请使用 tick_auth <token> 重新授权。"
CFG = os.path.expanduser("~/.ticktick")
DEFAULT_TRIGGER = "TRIGGER:-PT1M"
LANG = "CN"

WEEKDAY = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}

MSG = {
    "CN": {
        "week": ["一", "二", "三", "四", "五", "六", "日"],
        "weekday-from": "每周{w} 开始于{d:%Y-%m-%d}",
        "monthday-from": "每月{m}号 开始于{d:%Y-%m-%d}",
        "everyday": "每天",
        "weekday": "周{w} {d:%Y-%m-%d}",
    },
    "EN": {
        "week": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
        "weekday-from": "every {w} from {d:%Y-%m-%d}",
        "monthday-from": "every {m} from {d:%Y-%m-%d}",
        "monthday": [
            "1st",
            "2nd",
            "3rd",
            "4th",
            "5th",
            "6th",
            "7th",
            "8th",
            "9th",
            "10th",
            "11th",
            "12th",
            "13th",
            "14th",
            "15th",
            "16th",
            "17th",
            "18th",
            "19th",
            "20th",
            "21st",
            "22nd",
            "23rd",
            "24th",
            "25th",
            "26th",
            "27th",
            "28th",
            "29th",
            "30th",
            "31st",
        ],
        "everyday": "everyday",
        "weekday": "{w} {d:%Y-%m-%d}",
    },
}

S_NONE = 0
S_TIME = 1
S_DAY = 2
S_WEEKDAY = 4


# Reversible obfuscation only; this is not cryptographic protection.
ENCRYPTION_KEY = 0xA5
CONFIG_VERSION = 1


class TickError(Exception):
    """A safe, user-facing error; never include credentials or server bodies."""


def validate_token(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9._~+/-]+=*", value):
        raise TickError("API 口令格式无效。" + AUTH_HINT)
    return value


def encrypt_token(value):
    raw = ("dida-token:" + validate_token(value)).encode("ascii")
    encrypted = []
    for i, byte in enumerate(raw):
        val = byte ^ ENCRYPTION_KEY
        shift = i % 8
        encrypted.append(((val << shift) | (val >> (8 - shift))) & 0xFF)
    return bytes(encrypted).hex()


def decrypt_token(value):
    try:
        if not isinstance(value, str) or not re.fullmatch(r"(?:[0-9a-f]{2})+", value):
            raise ValueError()
        decrypted = bytearray()
        for i, val in enumerate(bytes.fromhex(value)):
            shift = i % 8
            decrypted.append((((val >> shift) | (val << (8 - shift))) & 0xFF) ^ ENCRYPTION_KEY)
        plain = decrypted.decode("ascii")
        if not plain.startswith("dida-token:"):
            raise ValueError()
        return validate_token(plain[len("dida-token:") :])
    except (ValueError, UnicodeError, TickError):
        raise TickError("授权配置损坏。" + AUTH_HINT) from None


class LocalTimezone(datetime.tzinfo):
    STDOFFSET = datetime.timedelta(seconds=-time.timezone)
    if time.daylight:
        DSTOFFSET = datetime.timedelta(seconds=-time.altzone)
    else:
        DSTOFFSET = STDOFFSET

    DSTDIFF = DSTOFFSET - STDOFFSET

    def utcoffset(self, dt):
        if self._isdst(dt):
            return self.DSTOFFSET
        return self.STDOFFSET

    def dst(self, dt):
        if self._isdst(dt):
            return self.DSTDIFF
        return datetime.timedelta(0)

    def tzname(self, dt):
        return time.tzname[self._isdst(dt)]

    def _isdst(self, dt):
        tt = (dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.weekday(), 0, -1)
        stamp = time.mktime(tt)
        tt = time.localtime(stamp)
        return tt.tm_isdst > 0


def read_config():
    try:
        with open(CFG, encoding="utf-8") as f:
            cfg = json.load(f)
    except FileNotFoundError:
        raise TickError("尚未授权。" + AUTH_HINT) from None
    except (OSError, ValueError):
        raise TickError("旧版或损坏的授权配置。" + AUTH_HINT) from None
    if not isinstance(cfg, dict) or cfg.get("version") != CONFIG_VERSION:
        raise TickError("旧版或损坏的授权配置。" + AUTH_HINT)
    if not isinstance(cfg.get("projectId"), str) or not cfg["projectId"]:
        raise TickError("授权配置缺少收集箱。" + AUTH_HINT)
    return {"token": decrypt_token(cfg.get("token")), "projectId": cfg["projectId"]}


def write_config(cfg):
    stored = {"version": CONFIG_VERSION, "token": encrypt_token(cfg["token"]), "projectId": cfg["projectId"]}
    # Create next to the destination so replacement is atomic on this filesystem.
    fd, path = tempfile.mkstemp(prefix=".ticktick-", dir=os.path.dirname(CFG))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            os.fchmod(f.fileno(), 0o600)
            json.dump(stored, f)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(path, CFG)
    finally:
        if os.path.exists(path):
            os.unlink(path)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Do not forward Authorization to another endpoint.
        return None


class MCPClient:
    def __init__(self, api_token):
        self.headers = {
            "Authorization": "Bearer " + validate_token(api_token),
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        self.opener = urllib.request.build_opener(NoRedirect())
        self.next_id = 0

    def initialize(self):
        result = self.request(
            "initialize",
            {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "alfred-tick", "version": VERSION},
            },
        )
        if result.get("protocolVersion") != "2025-03-26" or "tools" not in result.get("capabilities", {}):
            raise TickError("MCP 协议或工具能力不兼容。")
        self.headers["MCP-Protocol-Version"] = result["protocolVersion"]
        self.request("notifications/initialized", {}, notification=True)

    def request(self, method, params, notification=False):
        body = {"jsonrpc": "2.0", "method": method, "params": params}
        if not notification:
            self.next_id += 1
            body["id"] = self.next_id
        req = urllib.request.Request(MCP_URL, data=json.dumps(body).encode("utf-8"), headers=self.headers)
        try:
            with self.opener.open(req, timeout=20) as response:
                if method == "initialize" and response.headers.get("Mcp-Session-Id"):
                    self.headers["Mcp-Session-Id"] = response.headers["Mcp-Session-Id"]
                if notification and response.status in (200, 202, 204):
                    return {}
                content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip()
                if content_type == "application/json":
                    message = json.load(response)
                elif content_type == "text/event-stream":
                    message = self.read_event_response(response, body.get("id"))
                else:
                    raise TickError("MCP 返回了无法识别的响应。")
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise TickError("Token 无效、已过期或权限不足。" + AUTH_HINT) from None
            raise TickError(f"MCP 请求失败（HTTP {e.code}）。") from None
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException):
            raise TickError("网络连接失败或超时。") from None
        except (ValueError, UnicodeError):
            raise TickError("MCP 返回了无效数据。") from None
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or message.get("id") != body.get("id"):
            raise TickError("MCP 响应与请求不匹配。")
        if "error" in message:
            raise TickError("MCP 请求被拒绝。")
        if not isinstance(message.get("result"), dict):
            raise TickError("MCP 响应缺少结果。")
        return message["result"]

    @staticmethod
    def read_event_response(response, request_id):
        data = []
        deadline = time.monotonic() + 30
        for raw in response:
            if time.monotonic() > deadline:
                raise TickError("MCP 响应超时。")
            line = raw.decode("utf-8").rstrip("\r\n")
            if line.startswith("data:"):
                data.append(line[5:].removeprefix(" "))
            elif not line and data:
                message = json.loads("\n".join(data))
                data = []
                if isinstance(message, dict) and message.get("id") == request_id:
                    return message
        raise TickError("MCP 响应中断或缺少结果。")

    def call_tool(self, name, arguments):
        result = self.request("tools/call", {"name": name, "arguments": arguments})
        if result.get("isError"):
            raise TickError("滴答 MCP 工具执行失败。")
        payload = result.get("structuredContent")
        if payload is None:
            try:
                blocks = result.get("content", [])
                if not isinstance(blocks, list) or any(not isinstance(b, dict) for b in blocks):
                    raise ValueError()
                texts = [block["text"] for block in blocks if block.get("type") == "text"]
                # Older MCP clients can receive one text block per list item.
                if name == "list_projects" and len(texts) > 1:
                    payload = [json.loads(text) for text in texts]
                else:
                    payload = json.loads("\n".join(texts))
            except (ValueError, TypeError, KeyError):
                raise TickError("滴答 MCP 工具返回了无效结果。") from None
        if not isinstance(payload, (dict, list)) or (isinstance(payload, dict) and "error" in payload):
            raise TickError("滴答 MCP 工具执行失败。")
        return payload

    def validate_tools(self):
        found = {}
        params = {}
        cursors = set()
        while True:
            result = self.request("tools/list", params)
            for tool in result.get("tools", []):
                found[tool["name"]] = tool
            cursor = result.get("nextCursor")
            if not cursor:
                break
            if cursor in cursors:
                raise TickError("MCP 工具列表分页异常。")
            cursors.add(cursor)
            params = {"cursor": cursor}
        schema = found.get("create_task", {}).get("inputSchema", {})
        if "task" not in schema.get("properties", {}) or "list_projects" not in found:
            raise TickError("MCP 缺少所需的任务或清单工具。")


def send(query):
    cfg = read_config()
    item = generate_item(query, cfg["projectId"])
    client = MCPClient(cfg["token"])
    client.initialize()
    # Never retry a task submission: an interrupted response may hide success.
    try:
        result = client.call_tool("create_task", {"task": item})
        if not isinstance(result, dict) or not isinstance(result.get("id"), str) or not result["id"]:
            raise TickError("返回结果缺少任务 ID。")
    except TickError as e:
        raise TickError(str(e) + " 未确认创建成功；请先检查收集箱再重试。") from None
    return True


def token(q, remove_last):
    if remove_last:
        i = q["title"].rfind(" ")
        q["title"] = q["title"][:i].strip()

    i = q["title"].rfind(" ")
    if i == -1:
        return None
    t = q["title"][i + 1 :]
    return t.lower()


def parse(query):
    q = {"title": None, "priority": 0, "dueDate": None, "startDate": None, "reminder": "", "reminders": []}
    q["title"] = query
    m = re.search("(!+)", q["title"])
    if m:
        q["priority"] = 2 * len(m.group(1)) - 1
        q["title"] = re.sub("!+", "", q["title"])
    q["title"] = q["title"].strip()

    state = S_NONE
    now = datetime.datetime.now(tz=LocalTimezone())
    d = now.replace(hour=0, minute=0, second=0, microsecond=0)
    t = None
    while True:
        t = token(q, t)
        if not t:
            break
        if state == S_NONE:
            m = re.match(r"(\d{1,2}):(\d{1,2})", t)
            if m:
                d = d.replace(hour=int(m.group(1)), minute=int(m.group(2)))
                if d < now:
                    d += datetime.timedelta(days=1)
                state = S_TIME
                continue
        if state <= S_TIME:
            if t in ("tomorrow", "tmr"):
                state |= S_DAY
                if d.date() == now.date():
                    d += datetime.timedelta(days=1)
                break

            m = re.match(r"(\d{1,2})-(\d{1,2})", t)
            if m:
                state |= S_DAY
                d = d.replace(month=int(m.group(1)), day=int(m.group(2)))
                if d < now:
                    d = d.replace(year=d.year + 1)
                continue

            m = re.match(r"\b({})\b".format("|".join(WEEKDAY.keys())), t, re.I)
            if m:
                state |= S_WEEKDAY
                n = WEEKDAY[m.group(1)]
                d += datetime.timedelta(days=1)
                while d.weekday() != n:
                    d += datetime.timedelta(days=1)
                continue

        if t == "next" and state & S_WEEKDAY != 0:
            if now.weekday() < d.weekday():
                d += datetime.timedelta(days=7)
            break

        if t == "every":
            if state == S_TIME:
                q["repeatFlag"] = "RRULE:FREQ=DAILY;INTERVAL=1"
            elif state & S_DAY != 0:
                q["repeatFlag"] = "RRULE:FREQ=MONTHLY;INTERVAL=1"
            elif state & S_WEEKDAY != 0:
                q["repeatFlag"] = "RRULE:FREQ=WEEKLY;INTERVAL=1"
            break
        t = None
        break
    token(q, t)
    if state != S_NONE:
        if state & S_TIME != 0:
            q["startDate"] = q["dueDate"] = d.strftime("%Y-%m-%dT%H:%M:%S.000%z")
            q["reminder"] = DEFAULT_TRIGGER
            q["reminders"].append(DEFAULT_TRIGGER)
        else:
            q["startDate"] = q["dueDate"] = d.strftime("%Y-%m-%dT%H:%M:%S.000+0000")
    return q, d, state


def generate_item(query, pid):
    parsed, _, state = parse(query)
    if not parsed["title"]:
        raise TickError("请输入任务标题。")
    if parsed["priority"] not in (0, 1, 3, 5):
        raise TickError("优先级最多使用三个感叹号。")
    item = {k: parsed[k] for k in ("title", "priority", "startDate", "dueDate", "repeatFlag") if k in parsed and parsed[k] is not None}
    if state != S_NONE:
        item["isAllDay"] = state & S_TIME == 0
        # Use the macOS IANA zone, not ambiguous abbreviations such as CST.
        zone = os.environ.get("TZ", "").lstrip(":")
        if not zone:
            zone = os.path.realpath("/etc/localtime").split("/zoneinfo/", 1)[-1]
        try:
            ZoneInfo(zone)
        except (ValueError, ZoneInfoNotFoundError):
            raise TickError("无法识别本机时区，请检查系统时区设置。") from None
        item["timeZone"] = zone
        if state & S_TIME:
            item["reminders"] = parsed["reminders"]
    item["projectId"] = pid
    return item


def week_name(s):
    return MSG[LANG]["week"][s]


def month_day_name(s):
    if LANG == "CN":
        return f"{s}"
    return MSG[LANG]["monthday"][s - 1]


def desc(query):
    q, d, state = parse(query)
    title = ("!" * int((1 + q["priority"]) / 2)) + q["title"]
    if state != S_NONE:
        if state & S_TIME != 0:
            t = d.strftime(" %H:%M")
        else:
            t = ""
        if "repeatFlag" in q:
            if "WEEKLY" in q["repeatFlag"]:
                day = MSG[LANG]["weekday-from"].format(w=week_name(d.weekday()), d=d)
            elif "MONTHLY" in q["repeatFlag"]:
                day = MSG[LANG]["monthday-from"].format(m=month_day_name(d.day), d=d)
            else:
                day = MSG[LANG]["everyday"]
        else:
            day = MSG[LANG]["weekday"].format(w=week_name(d.weekday()), d=d)
        title += " " + day + t
    print_item(query, title)


def print_item(arg, title):
    print(
        f"""<?xml version='1.0' encoding='utf-8'?>
<items>
  <item valid="yes" arg={quoteattr(arg)}>
    <title>{escape(title)}</title>
    <subtitle>send to ticktick</subtitle>
    <icon>icon.png</icon>
  </item>
</items>
"""
    )


def auth(query):
    api_token = validate_token(query.strip())
    client = MCPClient(api_token)
    client.initialize()
    client.validate_tools()
    projects = client.call_tool("list_projects", {})
    if isinstance(projects, dict):
        projects = [projects] if "id" in projects else projects.get("result")
    if not isinstance(projects, list):
        raise TickError("无法读取收集箱，原授权配置未更改。")
    inboxes = [
        p["id"] for p in projects if isinstance(p, dict) and isinstance(p.get("id"), str) and re.fullmatch(r"inbox(?:[0-9]+)?", p["id"])
    ]
    if len(inboxes) != 1:
        raise TickError("无法唯一识别收集箱，原授权配置未更改。")
    write_config({"token": api_token, "projectId": inboxes[0]})


def main(args=None):
    args = sys.argv[1:] if args is None else args
    try:
        if len(args) == 2 and args[0] == "parse":
            desc(args[1])
        elif len(args) == 2 and args[0] == "auth":
            auth(args[1])
            print("授权成功")
        elif len(args) == 1:
            send(args[0])
            print("增加任务成功")
        else:
            raise TickError("用法：tick.py auth <token> 或 tick.py '任务 [日期] [时间]'。")
        return 0
    except TickError as e:
        print(str(e))
    except (ValueError, OverflowError):
        print("日期、时间或输入格式无效。")
    except OSError:
        print("无法读写配置或连接服务；请检查文件权限和网络。")
    except Exception:
        # Do not emit raw exceptions or tracebacks: they may contain a credential.
        print("处理失败，请检查输入和 MCP 服务。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
