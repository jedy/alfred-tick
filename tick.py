#!/usr/bin/python
#! -*- coding: utf8 -*-
import json
import datetime
import tzlocal
import time
import urllib2
import os.path
import random
import re
import alfred
import sys
import os

BASE_URL = "https://www.dida365.com"
API_URL = BASE_URL + "/api/v2/task"
LOGIN_URL = BASE_URL + "/api/v2/user/signon?wc=true&remember=true"
CFG = os.path.expanduser("~/.ticktick")
DEFAULT_TRIGGER = "TRIGGER:-PT1M"
LANG = "CN"

WEEKDAY = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}

MSG = {
    "CN": {
        "week": [u"一", u"二", u"三", u"四", u"五", u"六", u"日"],
        "weekday-from": u"每周{w} 开始于{d:%Y-%m-%d}",
        "monthday-from": u"每月{m}号 开始于{d:%Y-%m-%d}",
        "everyday": u"每天",
        "weekday": u"周{w} {d:%Y-%m-%d}",
    },
    "EN": {
        "week": [u"Monday", u"Tuesday", u"Wednesday", u"Thursday", u"Friday", u"Saturday", u"Sunday"],
        "weekday-from": u"every {w} from {d:%Y-%m-%d}",
        "monthday-from": u"every {m} from {d:%Y-%m-%d}",
        "monthday": [u"1st", u"2nd", u"3rd", u"4th", u"5th", u"6th", u"7th", u"8th", u"9th", u"10th",
                     u"11th", u"12th", u"13th", u"14th", u"15th", u"16th", u"17th", u"18th", u"19th", u"20th",
                     u"21st", u"22nd", u"23rd", u"24th", u"25th", u"26th", u"27th", u"28th", u"29th", u"30th",
                     u"31st"],
        "everyday": u"everyday",
        "weekday": u"{w} {d:%Y-%m-%d}",
    }
}

S_NONE = 0
S_TIME = 1
S_DAY = 2
S_WEEKDAY = 4

class UTC(datetime.tzinfo):
    def utcoffset(self, dt):
        return datetime.timedelta(0)

    def tzname(self, dt):
        return "UTC"

    def dst(self, dt):
        return datetime.timedelta(0)


def read_config():
    d = {}
    f = open(CFG)
    for r in f:
        p = r.strip().split("=", 1)
        if p:
            d[p[0]] = p[1]
    f.close()
    return d

def write_config(cfg):
    f = os.fdopen(os.open(CFG, os.O_WRONLY | os.O_CREAT, 0600), "w")
    for k, v in cfg.iteritems():
        f.write("{0}={1}\n".format(k, v))
    f.close()

def generate_request(url, cookie=None):
    r = urllib2.Request(url)
    r.add_header("User-Agent", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.10; rv:36.0) Gecko/20100101 Firefox/36.0")
    r.add_header("Accept-Language", "zh-CN,en-US;q=0.7,en;q=0.3")
    r.add_header("Referer", BASE_URL)
    r.add_header("DNT", "1")
    r.add_header("Accept", "application/json, text/javascript, */*; q=0.01")
    r.add_header("Content-Type", "application/json; charset=UTF-8")
    r.add_header("X-Requested-With", "XMLHttpRequest")
    r.add_header("Accept-Encoding", "deflate")
    if cookie:
        r.add_header("Cookie", cookie)
    return r

def object_id(args=[]):
    if not args:
        args.extend([random.randint(0, 16777215), random.randint(0, 32766), random.randint(0, 16777215)])
    args[1] += 1
    if args[2] > 16777215:
        args[2] = 0
    return "{:08x}{:06x}{:04x}{:06x}".format(int(time.time()), args[0], args[1], args[2])

def send(query):
    cfg = read_config()
    for _ in xrange(2):
        if "projectId" not in cfg or "cookie" not in cfg:
            if "user" in cfg and "pwd" in cfg:
                data = {"username": cfg["user"], "password": cfg["pwd"]}
                try:
                    result = login_request(data)
                except:
                    break
                cfg.update(result)
                write_config(cfg)
            else:
                break
        item = generate_item(query, cfg["projectId"])
        r = generate_request(API_URL, cfg["cookie"])
        r.add_data(json.dumps(item))
        try:
            c = urllib2.urlopen(r)
            c.read()
            c.close()
        except urllib2.HTTPError as e:
            if e.code == 401:
                del cfg["projectId"]
                del cfg["cookie"]
                continue
            return False
        except Exception as e:
            return False
        return c.code == 200
    print "Login first. "
    return False

def token(q, remove_last):
    if remove_last:
        i = q["title"].rfind(" ")
        q["title"] = q["title"][:i].strip()

    i = q["title"].rfind(" ")
    if i == -1:
        return None
    t = q["title"][i+1:]
    return t.lower()

def parse(query):
    q = {
        "title": None,
        "priority": 0,
        "dueDate": None,
        "startDate": None,
        "reminder": "",
        "reminders": [],
    }
    q["title"] = query
    m = re.search("(!+)", q["title"])
    if m:
        q["priority"] = 2 * len(m.group(1)) - 1
        q["title"] = re.sub("!+", "", q["title"])
    q["title"] = q["title"].strip()

    state = S_NONE
    tz = tzlocal.get_localzone()
    d = datetime.datetime.now(tz)
    d = d.replace(hour=0, minute=0, second=0, microsecond=0)
    t = None
    while True:
        t = token(q, t)
        if not t:
            break
        if state == S_NONE:
            m = re.match(r"(\d{1,2}):(\d{1,2})", t)
            if m:
                d = d.replace(hour=int(m.group(1)), minute=int(m.group(2)))
                if d < datetime.datetime.now(tz):
                    d += datetime.timedelta(days=1)
                state = S_TIME
                continue
        if state <= S_TIME:
            if t in ("tomorrow", "tmr"):
                state |= S_DAY
                if d.date() == datetime.date.today():
                    d += datetime.timedelta(days=1)
                break

            m = re.match(r"(\d{1,2})-(\d{1,2})", t)
            if m:
                state |= S_DAY
                d = d.replace(month=int(m.group(1)), day=int(m.group(2)))
                if d < datetime.datetime.now(tz):
                    d = d.replace(year=d.year+1)
                continue

            m = re.match(r"\b({0})\b".format("|".join(WEEKDAY.keys())), t, re.I)
            if m:
                state |= S_WEEKDAY
                n = WEEKDAY[m.group(1)]
                d += datetime.timedelta(days=1)
                while d.weekday() != n:
                    d += datetime.timedelta(days=1)
                continue

        if t == "next" and state & S_WEEKDAY != 0:
            if datetime.datetime.now().weekday() < d.weekday():
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
        u = d.astimezone(UTC())
        q["startDate"] = q["dueDate"] = "{0}{1:%z}".format(u.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3], u)
        if state & S_TIME != 0:
            q["reminder"] = DEFAULT_TRIGGER
            q["reminders"].append({"id": object_id(), "trigger": DEFAULT_TRIGGER})
    return q, d, state

def generate_item(query, pid):
    item, _, state = parse(query)
    n = datetime.datetime.now().utcnow()

    item["modifiedTime"] = n.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "+0000"
    item["id"] = object_id()
    item["status"] = 0
    item["timeZone"] = tzlocal.get_localzone().zone
    item["content"] = ""
    item["sortOrder"] = 0
    item["items"] = []
    item["progress"] = 0
    if state == S_NONE:
        item["isAllDay"] = None
    else:
        item["isAllDay"] = (state & S_TIME == 0)
    item["projectId"] = pid
    return item

def week_name(s):
    return MSG[LANG]["week"][s]

def month_day_name(s):
    if LANG == "CN":
        return u"{0}".format(s)
    else:
        return MSG[LANG]["monthday"][s-1]

def desc(query):
    q, d, state = parse(query)
    title = ("!" * ((1 + q["priority"]) / 2)) + q["title"]
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
        title += u" " + day + t
    i = alfred.Item(arg=query, title=title, subtitle=u"send to ticktick", icon=alfred.Icon("icon.png"))
    print alfred.render([i])

def login_request(data):
    r = generate_request(LOGIN_URL)
    r.add_data(json.dumps(data))
    rep = urllib2.urlopen(r)
    c = rep.read()
    rep.close()
    m = re.search("(t=\w+);", rep.headers.getheader("Set-Cookie"))
    result = {"cookie": m.group(1)}
    data = json.loads(c)
    result["projectId"] = data["inboxId"]
    return result

def login(query):
    try:
        user, pwd = query.split(" ", 1)
        data = {"username": user, "password": pwd}
        cfg = login_request(data)
        cfg["user"] = user
        cfg["pwd"] = pwd
        write_config(cfg)
    except:
        print "Login failed"
        return
    print "Login done"


if len(sys.argv) == 3:
    if sys.argv[1] == "parse":
        desc(sys.argv[2].decode("utf8"))
    elif sys.argv[1] == "login":
        login(sys.argv[2])
else:
    if send(sys.argv[1].decode("utf8")):
        print "Done"
    else:
        print "Failed"
