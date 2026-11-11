#!/usr/bin/env python3
"""Lemon Desk 자랑 게시판 API.

표준 라이브러리만 쓴다(집서버 /usr/bin/python3 3.9). 앱의 "자랑하기"가 올리고, 웹 게시판(site/brag/)이 읽고 별을 준다.
- 로그인 없음: 앱이 만든 무작위 소유 키(64 hex)의 sha256 만 저장한다.
- IP 는 hmac(salt, ip) 앞 16자만 저장한다(횟수 제한, 신고·별 중복 방지).
- 한 소유자가 한 주(KST ISO 주)에 게시물 하나. 다시 올리면 내용만 바뀌고 별은 남는다.
- 지난주 하이라이트(별 Top 10 + 재미 부문 3개)는 월요일에 스냅숏으로 영구 보관, 나머지 게시물은 8주 뒤 지운다.
- 폰으로 보기(1.6, relay/…): Mac 앱과 폰 웹페이지(site/m/) 사이 중계. 페어링 키는 해시로만 DB 에, 과수원 상태·명령은 메모리에만.

실행: python3 brag.py [--data DIR] [--port 8891] [--host 127.0.0.1] [--prefix /lemondesk/api/] [--board URL] [--cors 출처] [--static SITE_DIR]
  --static 은 로컬 확인용: /lemondesk/<경로> 를 SITE_DIR 에서 준다
  회사 인프라: python brag.py --host 0.0.0.0 --prefix /api/ --board https://lemondesk.interaction.hnine.com/brag/ --cors https://lemondesk.interaction.hnine.com
              (PORT, IX_DATA_DIR 은 인프라가 넣어 준다)
관리: python3 brag.py admin list|hide ID|unhide ID|delete ID
"""
import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import sys
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

KST = timezone(timedelta(hours=9))
# 실행 인자로 바꾼다(main). 기본값은 집서버(경로 규칙 /lemondesk/api/) 설정, 회사 인프라는 --prefix /api/ --board … --cors …
PREFIX = "/lemondesk/api/"
BOARD_URL = "https://lemondesk.interaction.hnine.com/brag/"
CORS_ORIGIN = ""  # 게시판 페이지가 다른 호스트에 있으면 그 출처(예: https://lemondesk.interaction.hnine.com)
KEEP_WEEKS = 8
TOP_N = 10
PAGE = 20
MAX_BODY = 8 * 1024
# 동작 → (횟수, 초). ponytail: 메모리에만 둔다(재시작하면 초기화). 가벼운 조작 방지면 충분하다.
# 회사 사무실은 여러 사람이 같은 공인 IP 를 쓰므로 넉넉하게 둔다.
LIMITS = {"post": (30, 3600), "star": (300, 3600), "report": (60, 3600), "ping": (600, 3600), "install": (600, 3600),
          # 폰으로 보기: pair 는 IP 당, 나머지는 기기(페어링)당
          "pair": (30, 3600), "state": (1800, 3600), "wait": (1200, 3600), "view": (3600, 3600), "command": (600, 3600)}
STATS_KEEP_DAYS = 90       # 사용 통계 원본 보관(그 뒤로는 날짜별 합계만)
STATS_TOKEN = ""           # 통계 조회 토큰(환경 변수 STATS_TOKEN). 비어 있으면 조회를 막는다.
ARCHES = {"arm64", "x86_64"}
VERSION_RE = re.compile(r"\d{1,3}(\.\d{1,3}){0,3}")
LANG_RE = re.compile(r"[A-Za-z]{2,3}([-_][A-Za-z0-9]{2,8})?")

KINDS = {"eureka", "kumquat", "meyer", "calamansi", "lime", "blood", "yuja", "grapefruit", "pink",
         "hallabong", "buddha", "golden", "rainbow",
         # 1.7
         "redhyang", "cheonhye", "bergamot", "pomelo", "fingerlime", "trifoliate", "snowyuja", "moonlemon"}
ROLES = {"planter", "caretaker", "harvester"}
THEMES = {"sunny", "blossom", "sunset", "moon", "garden"}
# ponytail: 짧은 금칙어 목록. 공백을 지우고 소문자로 비교한다. 신고 3건 자동 숨김이 나머지를 맡는다.
BANNED = ["시발", "씨발", "ㅅㅂ", "병신", "ㅂㅅ", "개새", "좆", "섹스", "fuck", "shit", "bitch", "sex", "porn", "nigger"]
# 폰으로 보기(1.6)
RELAY_STATE_MAX = 24 * 1024  # Mac 이 올리는 상태 크기(실제는 6KB 안팎)
RELAY_WAIT = 25              # Mac 롱폴링 최대 초(앞단 프록시 시간 제한보다 짧게)
RELAY_WAITERS = 2            # 한 기기가 동시에 열 수 있는 대기(잠자기에서 깨면 끊긴 대기가 하나 남아 있다)
RELAY_WAITERS_ALL = 2000     # 서버 전체 동시 대기. 넘으면 기다리지 않고 바로 답한다(스레드 고갈 방지)
RELAY_WATCH = 30             # 폰이 이 초 안에 봤으면 '보는 중'
RELAY_ONLINE = 90            # Mac 이 이 초 안에 왔으면(또는 기다리는 중이면) 깨어 있음
RELAY_FRESH = 3              # 폰이 처음 열 때 Mac 의 새 상태를 기다리는 초
RELAY_CMD_TTL = 30           # 명령을 Mac 이 가져가지 않으면 버리는 초
RELAY_QUEUE = 10
RELAY_KEEP_DAYS = 90         # 쓰지 않는 페어링 보관
ACTIONS = {"sell", "plant", "unlock", "hire", "crate"}
CMD_ID = re.compile(r"[A-Za-z0-9-]{1,40}")
KEY = re.compile(r"[0-9a-f]{64}")
URLISH = re.compile(r"(https?:|www\.|\.(com|net|org|kr|io|me|xyz|club)\b|@)", re.I)


class BadRequest(Exception):
    def __init__(self, code="bad_data"):
        super().__init__(code)
        self.code = code


class RateLimited(Exception):
    pass


def day_key(dt):
    return dt.astimezone(KST).strftime("%Y-%m-%d")


def _match(v, pattern):
    if not isinstance(v, str) or not pattern.fullmatch(v):
        raise BadRequest()
    return v


def clean_ping(b, now):
    """익명 사용 통계(동의한 설치만). 설치 ID 는 앱이 만든 무작위 값이고 서버는 해시만 저장한다."""
    if not isinstance(b, dict):
        raise BadRequest()
    install = _match(b.get("install"), re.compile(r"[0-9a-fA-F-]{16,64}")).lower()
    day = b.get("day")
    try:
        d = datetime.strptime(day, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        raise BadRequest()
    if abs((d - now.astimezone(KST).date()).days) > 2:  # 앱은 자기 시간대의 날짜를 보낸다
        raise BadRequest()
    if b.get("arch") not in ARCHES:
        raise BadRequest()
    lang = b.get("lang") or ""
    return {"install": install, "day": day, "version": _match(b.get("version"), VERSION_RE), "os": _match(b.get("os"), VERSION_RE),
            "lang": _match(lang, LANG_RE) if lang else "", "arch": b["arch"],
            "minutes": _int(b.get("minutes"), 0, 1440), "opens": _int(b.get("opens"), 0, 10000),
            "sales": _int(b.get("sales"), 0, 100000), "kinds": _int(b.get("kinds"), 0, 13)}


def clean_install(b):
    """설치 신호(동의와 상관없이, 처음 실행 때 한 번). 식별자가 없다."""
    if not isinstance(b, dict) or b.get("kind") not in ("new", "upgrade") or b.get("arch") not in ARCHES:
        raise BadRequest()
    return {"version": _match(b.get("version"), VERSION_RE), "kind": b["kind"], "arch": b["arch"], "os": _match(b.get("os"), VERSION_RE)}


def week_key(dt):
    y, w, _ = dt.astimezone(KST).isocalendar()
    return "%04d-W%02d" % (y, w)


def _int(v, lo, hi):
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise BadRequest()
    return v


def clean_nickname(v):
    if not isinstance(v, str):
        raise BadRequest("bad_nickname")
    n = " ".join(v.split())
    flat = n.replace(" ", "").lower()
    if not 1 <= len(n) <= 12 or URLISH.search(n) or any(b in flat for b in BANNED) or any(ord(c) < 32 for c in n):
        raise BadRequest("bad_nickname")
    return n


def clean_post(body):
    """앱이 보낸 내용을 검사해 저장할 형태로. 범위를 벗어나면 BadRequest."""
    if not isinstance(body, dict):
        raise BadRequest()
    card, orch = body.get("card"), body.get("orchard")
    if not isinstance(card, dict) or not isinstance(orch, dict):
        raise BadRequest()
    trees = orch.get("trees")
    workers = orch.get("workers")
    if not isinstance(trees, list) or len(trees) > 10 or any(t not in KINDS for t in trees):
        raise BadRequest()
    if not isinstance(workers, dict) or any(r not in ROLES for r in workers):
        raise BadRequest()
    crew = {}
    for role, w in workers.items():
        looks = w.get("looks") if isinstance(w, dict) else None
        if not isinstance(looks, list) or len(looks) > 2:
            raise BadRequest()
        crew[role] = {"level": _int(w.get("level"), 0, 20),
                      "looks": [{"variant": _int(l.get("variant"), 0, 1), "dye": _int(l.get("dye"), 0, 6)}
                                for l in looks if isinstance(l, dict)]}
    if orch.get("theme") not in THEMES or not isinstance(orch.get("rainbow"), bool):
        raise BadRequest()
    return {
        "nickname": clean_nickname(body.get("nickname")),
        "card": {"harvested": _int(card.get("harvested"), 0, 10**8), "sold": _int(card.get("sold"), 0, 10**8),
                 "earned": _int(card.get("earned"), 0, 10**13), "planted": _int(card.get("planted"), 0, 10**5)},
        "orchard": {"trees": trees, "workers": crew, "dex": _int(orch.get("dex"), 0, 20),
                    "secrets": _int(orch.get("secrets"), 0, 20), "rainbow": orch["rainbow"], "theme": orch["theme"]},
    }


def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


def locked(f):
    """sqlite 연결 하나를 여러 요청 스레드가 같이 쓰므로 읽기까지 전부 잠근다(동시에 읽으면 세그폴트가 났다)."""
    def wrapper(self, *a, **kw):
        with self.lock:
            return f(self, *a, **kw)
    return wrapper


class Board:
    def __init__(self, path, salt):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.RLock()
        self.salt = salt
        self.hits = defaultdict(deque)
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS posts(id TEXT PRIMARY KEY, owner TEXT NOT NULL, week TEXT NOT NULL,
                nickname TEXT NOT NULL, data TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
                hidden INTEGER NOT NULL DEFAULT 0, UNIQUE(owner, week));
            CREATE TABLE IF NOT EXISTS stars(post TEXT NOT NULL, voter TEXT NOT NULL, ip TEXT NOT NULL,
                created REAL NOT NULL, PRIMARY KEY(post, voter));
            CREATE TABLE IF NOT EXISTS reports(post TEXT NOT NULL, ip TEXT NOT NULL, created REAL NOT NULL,
                PRIMARY KEY(post, ip));
            CREATE TABLE IF NOT EXISTS highlights(week TEXT NOT NULL, kind TEXT NOT NULL, rank INTEGER NOT NULL,
                post TEXT NOT NULL, owner TEXT NOT NULL, snapshot TEXT NOT NULL, PRIMARY KEY(week, kind, rank));
            CREATE TABLE IF NOT EXISTS closed(week TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS install_counts(day TEXT NOT NULL, version TEXT NOT NULL, kind TEXT NOT NULL,
                arch TEXT NOT NULL, os TEXT NOT NULL, n INTEGER NOT NULL, PRIMARY KEY(day, version, kind, arch, os));
            CREATE TABLE IF NOT EXISTS participants(install TEXT PRIMARY KEY, first_day TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS pings(install TEXT NOT NULL, day TEXT NOT NULL, version TEXT, os TEXT, lang TEXT,
                arch TEXT, minutes INTEGER, opens INTEGER, sales INTEGER, kinds INTEGER, received REAL,
                PRIMARY KEY(install, day));
            CREATE TABLE IF NOT EXISTS daily(day TEXT PRIMARY KEY, active INTEGER, new INTEGER, minutes INTEGER,
                opens INTEGER, sales INTEGER);
        """)

    def close(self):
        self.db.close()

    # 도우미

    def week(self, now):
        return week_key(now)

    def ip(self, ip):
        return hmac.new(self.salt, ip.encode(), hashlib.sha256).hexdigest()[:16]

    def limit(self, action, ip_hash, now):
        n, window = LIMITS[action]
        q = self.hits[(action, ip_hash)]
        t = now.timestamp()
        while q and q[0] <= t - window:
            q.popleft()
        if len(q) >= n:
            raise RateLimited()
        q.append(t)

    @staticmethod
    def owner(key):
        if not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]{64}", key):
            raise BadRequest("unauthorized")
        return sha(key)

    def _row(self, r, voter=None):
        pid, week, nick, data, created, stars = r
        d = json.loads(data)
        out = {"id": pid, "week": week, "nickname": nick, "card": d["card"], "orchard": d["orchard"],
               "stars": stars, "created": int(created)}
        if voter is not None:
            out["starred"] = self.db.execute("SELECT 1 FROM stars WHERE post=? AND voter=?", (pid, sha(voter))).fetchone() is not None
        return out

    SELECT = ("SELECT p.id, p.week, p.nickname, p.data, p.created, "
              "(SELECT COUNT(*) FROM stars s WHERE s.post=p.id) AS n FROM posts p")

    # 동작

    @locked
    def create_or_update(self, owner_key, body, ip, now):
        owner = self.owner(owner_key)
        post = clean_post(body)
        with self.lock:
            self.limit("post", self.ip(ip), now)
            week = self.week(now)
            data = json.dumps({"card": post["card"], "orchard": post["orchard"]}, ensure_ascii=False)
            row = self.db.execute("SELECT id FROM posts WHERE owner=? AND week=?", (owner, week)).fetchone()
            t = now.timestamp()
            if row:
                pid = row[0]
                self.db.execute("UPDATE posts SET nickname=?, data=?, updated=? WHERE id=?", (post["nickname"], data, t, pid))
            else:
                pid = secrets.token_urlsafe(6)
                self.db.execute("INSERT INTO posts(id, owner, week, nickname, data, created, updated) VALUES(?,?,?,?,?,?,?)",
                                (pid, owner, week, post["nickname"], data, t, t))
            self.db.commit()
        return {"id": pid, "url": BOARD_URL + "?p=" + pid}

    @locked
    def get(self, pid, voter=None):
        r = self.db.execute(self.SELECT + " WHERE p.id=? AND p.hidden=0", (pid,)).fetchone()
        return self._row(r, voter) if r else None

    @locked
    def list(self, week, sort, page, voter=None):
        order = "n DESC, p.created ASC" if sort == "stars" else "p.created DESC"
        rows = self.db.execute(self.SELECT + " WHERE p.week=? AND p.hidden=0 ORDER BY " + order + " LIMIT ? OFFSET ?",
                               (week, PAGE, PAGE * max(0, page))).fetchall()
        return [self._row(r, voter) for r in rows]

    @locked
    def toggle_star(self, pid, voter, ip, now):
        if not isinstance(voter, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", voter):
            raise BadRequest()
        with self.lock:
            if not self.db.execute("SELECT 1 FROM posts WHERE id=? AND hidden=0", (pid,)).fetchone():
                raise KeyError(pid)
            self.limit("star", self.ip(ip), now)
            v = sha(voter)
            if self.db.execute("DELETE FROM stars WHERE post=? AND voter=?", (pid, v)).rowcount:
                starred = False
            else:
                self.db.execute("INSERT INTO stars VALUES(?,?,?,?)", (pid, v, self.ip(ip), now.timestamp()))
                starred = True
            self.db.commit()
            n = self.db.execute("SELECT COUNT(*) FROM stars WHERE post=?", (pid,)).fetchone()[0]
        return {"stars": n, "starred": starred}

    @locked
    def report(self, pid, ip, now):
        with self.lock:
            if not self.db.execute("SELECT 1 FROM posts WHERE id=?", (pid,)).fetchone():
                raise KeyError(pid)
            h = self.ip(ip)
            self.limit("report", h, now)
            self.db.execute("INSERT OR IGNORE INTO reports VALUES(?,?,?)", (pid, h, now.timestamp()))
            if self.db.execute("SELECT COUNT(*) FROM reports WHERE post=?", (pid,)).fetchone()[0] >= 3:
                self.db.execute("UPDATE posts SET hidden=1 WHERE id=?", (pid,))
            self.db.commit()

    @locked
    def me(self, owner_key, now):
        owner = self.owner(owner_key)
        r = self.db.execute(self.SELECT + " WHERE p.owner=? AND p.week=?", (owner, self.week(now))).fetchone()
        if not r:
            return {"post": None}
        return {"post": {"id": r[0], "stars": r[5], "url": BOARD_URL + "?p=" + r[0]}}

    @locked
    def delete_mine(self, owner_key):
        owner = self.owner(owner_key)
        with self.lock:
            ids = [r[0] for r in self.db.execute("SELECT id FROM posts WHERE owner=?", (owner,))]
            for pid in ids:
                self.db.execute("DELETE FROM stars WHERE post=?", (pid,))
                self.db.execute("DELETE FROM reports WHERE post=?", (pid,))
            self.db.execute("DELETE FROM posts WHERE owner=?", (owner,))
            self.db.execute("DELETE FROM highlights WHERE owner=?", (owner,))
            self.db.commit()
        return len(ids)

    # 통계

    @locked
    def install(self, body, ip, now):
        p = clean_install(body)
        self.limit("install", self.ip(ip), now)
        self.db.execute("INSERT INTO install_counts VALUES(?,?,?,?,?,1) "
                        "ON CONFLICT(day, version, kind, arch, os) DO UPDATE SET n = n + 1",
                        (day_key(now), p["version"], p["kind"], p["arch"], p["os"]))
        self.db.commit()

    @locked
    def ping(self, body, ip, now):
        p = clean_ping(body, now)
        self.limit("ping", self.ip(ip), now)
        inst = sha(p["install"])
        self.db.execute("INSERT INTO participants VALUES(?,?) "
                        "ON CONFLICT(install) DO UPDATE SET first_day = min(first_day, excluded.first_day)", (inst, p["day"]))
        self.db.execute("INSERT INTO pings VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(install, day) DO UPDATE SET "
                        "version=excluded.version, os=excluded.os, lang=excluded.lang, arch=excluded.arch, "
                        "minutes=max(minutes, excluded.minutes), opens=max(opens, excluded.opens), "
                        "sales=max(sales, excluded.sales), kinds=excluded.kinds, received=excluded.received",
                        (inst, p["day"], p["version"], p["os"], p["lang"], p["arch"], p["minutes"], p["opens"],
                         p["sales"], p["kinds"], now.timestamp()))
        self.db.commit()

    @locked
    def summary(self, days, now):
        days = max(1, min(int(days), 400))
        today = day_key(now)

        def ago(n):
            return day_key(now - timedelta(days=n))

        def one(sql, *a):
            return self.db.execute(sql, a).fetchone()[0]

        def by_installs(col):
            return dict(self.db.execute("SELECT %s, SUM(n) FROM install_counts GROUP BY %s ORDER BY 2 DESC" % (col, col)).fetchall())

        def by_usage(col):
            return dict(self.db.execute("SELECT %s, COUNT(DISTINCT install) FROM pings WHERE day >= ? GROUP BY %s ORDER BY 2 DESC"
                                        % (col, col), (ago(6),)).fetchall())

        kinds = by_installs("kind")
        installs = {"total": one("SELECT COALESCE(SUM(n), 0) FROM install_counts"), "new": kinds.get("new", 0),
                    "upgrade": kinds.get("upgrade", 0), "today": one("SELECT COALESCE(SUM(n), 0) FROM install_counts WHERE day = ?", today),
                    "versions": by_installs("version"), "arch": by_installs("arch"), "os": by_installs("os")}
        active = {k: one("SELECT COUNT(DISTINCT install) FROM pings WHERE day >= ? AND day <= ?", ago(n - 1), today)
                  for k, n in (("dau", 1), ("wau", 7), ("mau", 30))}
        cohort = [r[0] for r in self.db.execute("SELECT install FROM participants WHERE first_day BETWEEN ? AND ?", (ago(14), ago(8)))]
        retained = sum(1 for i in cohort if self.db.execute("SELECT 1 FROM pings WHERE install = ? AND day >= ?", (i, ago(6))).fetchone())
        usage = {"participants": one("SELECT COUNT(*) FROM participants"),
                 "new_today": one("SELECT COUNT(*) FROM participants WHERE first_day = ?", today),
                 "active": active, "retention7": {"cohort": len(cohort), "retained": retained},
                 "versions": by_usage("version"), "os": by_usage("os"), "arch": by_usage("arch"), "lang": by_usage("lang")}
        start = ago(days - 1)
        rows = {d: {"day": d, "installs": 0, "active": a, "new": nw, "avg_minutes": round(m / a) if a else 0, "opens": o, "sales": sl}
                for d, a, nw, m, o, sl in self.db.execute("SELECT day, active, new, minutes, opens, sales FROM daily WHERE day >= ?", (start,))}
        for d, a, m, o, sl in self.db.execute("SELECT day, COUNT(DISTINCT install), SUM(minutes), SUM(opens), SUM(sales) "
                                               "FROM pings WHERE day >= ? GROUP BY day", (start,)):
            rows[d] = {"day": d, "installs": 0, "active": a, "new": 0, "avg_minutes": round((m or 0) / a) if a else 0,
                       "opens": o or 0, "sales": sl or 0}
        for d, nw in self.db.execute("SELECT first_day, COUNT(*) FROM participants WHERE first_day >= ? GROUP BY first_day", (start,)):
            rows.setdefault(d, {"day": d, "installs": 0, "active": 0, "new": 0, "avg_minutes": 0, "opens": 0, "sales": 0})["new"] = nw
        for d, n in self.db.execute("SELECT day, SUM(n) FROM install_counts WHERE day >= ? GROUP BY day", (start,)):
            rows.setdefault(d, {"day": d, "installs": 0, "active": 0, "new": 0, "avg_minutes": 0, "opens": 0, "sales": 0})["installs"] = n
        week = self.week(now)
        board = {"posts_this_week": one("SELECT COUNT(*) FROM posts WHERE week = ? AND hidden = 0", week),
                 "stars_this_week": one("SELECT COUNT(*) FROM stars s JOIN posts p ON p.id = s.post WHERE p.week = ?", week)}
        return {"today": today, "installs": installs, "usage": usage, "daily": [rows[d] for d in sorted(rows)], "board": board}

    # 하이라이트

    def _compute(self, week):
        rows = self.db.execute(self.SELECT + " WHERE p.week=? AND p.hidden=0", (week,)).fetchall()
        posts = [self._row(r) for r in rows]
        top = sorted([p for p in posts if p["stars"] > 0], key=lambda p: (-p["stars"], p["created"]))[:TOP_N]

        def best(value):
            c = [p for p in posts if value(p) > 0]
            return min(c, key=lambda p: (-value(p), -p["stars"], p["created"])) if c else None

        cats = {"harvest": best(lambda p: p["card"]["harvested"]),
                "secrets": best(lambda p: p["orchard"]["secrets"]),
                "dex": best(lambda p: p["orchard"]["dex"])}
        return top, cats

    @locked
    def highlights(self, week, now):
        rows = self.db.execute("SELECT kind, rank, snapshot FROM highlights WHERE week=? ORDER BY kind, rank", (week,)).fetchall()
        closed = self.db.execute("SELECT 1 FROM closed WHERE week=?", (week,)).fetchone() is not None
        if closed:
            top = [json.loads(s) for k, _, s in rows if k == "top"]
            cats = {k: None for k in ("harvest", "secrets", "dex")}
            cats.update({k: json.loads(s) for k, _, s in rows if k != "top"})
            return {"week": week, "top": top, "categories": cats, "final": True}
        top, cats = self._compute(week)
        return {"week": week, "top": top, "categories": cats, "final": False}

    @locked
    def weeks(self):
        return [r[0] for r in self.db.execute(
            "SELECT DISTINCT week FROM highlights ORDER BY week DESC LIMIT 104")]

    @locked
    def maintain(self, now):
        """지난 주를 닫아 하이라이트를 스냅숏하고, 8주 지난 일반 게시물을 지운다. 한 시간마다 부른다."""
        # 횟수 제한 기록: 한 시간 넘게 안 쓴 키는 지운다(IP·기기가 많아져도 메모리가 늘기만 하지 않게)
        t = now.timestamp()
        for k, q in list(self.hits.items()):
            if not q or q[-1] < t - 3600:
                self.hits.pop(k, None)
        current = self.week(now)
        with self.lock:
            weeks = [r[0] for r in self.db.execute(
                "SELECT DISTINCT week FROM posts WHERE week < ? AND week NOT IN (SELECT week FROM closed)", (current,))]
            for w in weeks:
                top, cats = self._compute(w)
                for i, p in enumerate(top, 1):
                    self._snap(w, "top", i, p)
                for k, p in cats.items():
                    if p:
                        self._snap(w, k, 1, p)
                self.db.execute("INSERT OR IGNORE INTO closed VALUES(?)", (w,))
            cutoff = week_key(now - timedelta(weeks=KEEP_WEEKS))
            old = [r[0] for r in self.db.execute(
                "SELECT id FROM posts WHERE week < ? AND id NOT IN (SELECT post FROM highlights)", (cutoff,))]
            for pid in old:
                self.db.execute("DELETE FROM stars WHERE post=?", (pid,))
                self.db.execute("DELETE FROM reports WHERE post=?", (pid,))
                self.db.execute("DELETE FROM posts WHERE id=?", (pid,))
            # 사용 통계 원본은 90일 뒤 지우고 날짜별 합계만 남긴다
            stats_cut = day_key(now - timedelta(days=STATS_KEEP_DAYS))
            for (d,) in self.db.execute("SELECT DISTINCT day FROM pings WHERE day < ? AND day NOT IN (SELECT day FROM daily)",
                                        (stats_cut,)).fetchall():
                a, m, o, sl = self.db.execute("SELECT COUNT(DISTINCT install), SUM(minutes), SUM(opens), SUM(sales) FROM pings WHERE day=?",
                                              (d,)).fetchone()
                nw = self.db.execute("SELECT COUNT(*) FROM participants WHERE first_day=?", (d,)).fetchone()[0]
                self.db.execute("INSERT INTO daily VALUES(?,?,?,?,?,?)", (d, a, nw, m or 0, o or 0, sl or 0))
            self.db.execute("DELETE FROM pings WHERE day < ?", (stats_cut,))
            self.db.commit()

    def _snap(self, week, kind, rank, p):
        owner = self.db.execute("SELECT owner FROM posts WHERE id=?", (p["id"],)).fetchone()[0]
        self.db.execute("INSERT OR REPLACE INTO highlights VALUES(?,?,?,?,?,?)",
                        (week, kind, rank, p["id"], owner, json.dumps(p, ensure_ascii=False)))


class Relay:
    """폰으로 보기 중계(1.6). 게임 상태의 주인은 Mac 앱이고 서버는 전달만 한다.
    - Mac 은 macKey, 폰은 phoneKey(둘 다 앱이 만든 64 hex)로 `Authorization: Bearer` 인증한다. 서버는 sha256 만 저장한다.
      phoneKey 해시는 Mac 이 보낸다(서버는 폰 키 원문을 Mac 에서 받지 않는다). Mac 이 키를 바꾸면 기존 폰이 한꺼번에 끊긴다.
    - Mac: pair → (wait 롱폴링 → 명령 처리 → state) 반복. 폰: view(5초마다), command.
    - 상태·명령은 메모리에만 둔다. 재시작하면 Mac 이 다시 올린다. 페어링은 90일 안 쓰면 지운다.
    잠금은 하나, 깨우기는 기기별 조건 변수라 한 기기의 일로 다른 기기의 대기가 깨지 않는다."""

    def __init__(self, board):
        self.board = board
        self.lock = threading.Lock()
        self.live = {}
        self.waiting = 0
        with board.lock:
            board.db.executescript("""
                CREATE TABLE IF NOT EXISTS relay(device TEXT PRIMARY KEY, phone TEXT NOT NULL UNIQUE, created REAL NOT NULL, seen REAL NOT NULL);
            """)

    @staticmethod
    def _hash(auth):
        m = re.fullmatch(r"Bearer ([0-9a-f]{64})", auth or "")
        if not m:
            raise BadRequest("unauthorized")
        return sha(m.group(1))

    def _entry(self, device):
        e = self.live.get(device)
        if e is None:
            e = self.live[device] = {"state": None, "state_at": 0.0, "mac_seen": 0.0, "waiting": 0, "viewer_seen": 0.0,
                                     "wake": False, "commands": [], "saved": 0.0, "cond": threading.Condition(self.lock)}
        return e

    def _online(self, e, t):
        return e["waiting"] > 0 or t - e["mac_seen"] < RELAY_ONLINE

    def mac(self, auth):
        device = self._hash(auth)
        with self.board.lock:
            if not self.board.db.execute("SELECT 1 FROM relay WHERE device=?", (device,)).fetchone():
                raise BadRequest("unauthorized")
        return device

    def phone(self, auth):
        h = self._hash(auth)
        with self.board.lock:
            r = self.board.db.execute("SELECT device FROM relay WHERE phone=?", (h,)).fetchone()
        if not r:
            raise BadRequest("unauthorized")
        return r[0]

    def pair(self, auth, body, ip, now):
        device = self._hash(auth)
        phone = body.get("phone") if isinstance(body, dict) else None
        if not isinstance(phone, str) or not KEY.fullmatch(phone):
            raise BadRequest()
        self.board.limit("pair", self.board.ip(ip), now)
        t = now.timestamp()
        with self.board.lock:
            try:
                self.board.db.execute("INSERT INTO relay VALUES(?,?,?,?) ON CONFLICT(device) DO UPDATE SET phone=excluded.phone, seen=excluded.seen",
                                      (device, phone, t, t))
                self.board.db.commit()
            except sqlite3.IntegrityError:  # 다른 기기가 쓰는 폰 키(남의 폰을 내 과수원으로 끌어오지 못하게)
                self.board.db.rollback()
                raise BadRequest("conflict")
        with self.lock:  # 키를 바꾸면 그 전 폰이 남긴 명령은 버린다
            self._entry(device)["commands"] = []
        return {"ok": True}

    def unpair(self, auth):
        device = self.mac(auth)
        with self.board.lock:
            self.board.db.execute("DELETE FROM relay WHERE device=?", (device,))
            self.board.db.commit()
        with self.lock:
            e = self.live.pop(device, None)
            if e:
                e["cond"].notify_all()
        return {"ok": True}

    def push(self, auth, body, now):
        device = self.mac(auth)
        self.board.limit("state", device, now)
        if not isinstance(body, dict):
            raise BadRequest()
        t = now.timestamp()
        with self.lock:
            e = self._entry(device)
            e["state"], e["state_at"], e["mac_seen"] = json.dumps(body, ensure_ascii=False), t, t
            e["cond"].notify_all()
            return {"ok": True, "watching": t - e["viewer_seen"] < RELAY_WATCH}

    def wait(self, auth, timeout, now):
        """명령이 들어오거나, 폰이 새로 보기 시작하거나, timeout 이 되면 돌아온다."""
        device = self.mac(auth)
        self.board.limit("wait", device, now)
        with self.lock:
            e = self._entry(device)
            if e["waiting"] >= RELAY_WAITERS:
                raise RateLimited()
            if self.waiting >= RELAY_WAITERS_ALL:
                timeout = 0
            end = time.monotonic() + max(0, min(timeout, RELAY_WAIT))
            e["waiting"] += 1
            self.waiting += 1
            e["mac_seen"] = time.time()
            try:
                while True:
                    t = time.time()
                    e["commands"] = [c for c in e["commands"] if t - c["at"] < RELAY_CMD_TTL]
                    if e["commands"] or e["wake"] or device not in self.live:
                        break
                    left = end - time.monotonic()
                    if left <= 0:
                        break
                    e["cond"].wait(left)
                commands, woke, e["commands"], e["wake"] = e["commands"], e["wake"], [], False
                # 마지막으로 본 때는 기다리기 시작할 때만 적는다(끊긴 연결이 대기를 마칠 때 적으면 잠든 Mac 이 깨어 있어 보인다)
                t = time.time()
                save = t - e["saved"] > 3600
                if save:
                    e["saved"] = t
            finally:
                e["waiting"] -= 1
                self.waiting -= 1
            # push: 폰이 막 열었거나 서버에 상태가 없으면(재시작 등) 지금 올려 달라
            out = {"commands": [{k: v for k, v in c.items() if k != "at"} for c in commands], "push": woke or e["state"] is None,
                   "watching": t - e["viewer_seen"] < RELAY_WATCH, "viewerSeen": e["viewer_seen"] or None}
        if save:  # 마지막으로 쓴 때(90일 정리용)는 한 시간에 한 번만 적는다
            with self.board.lock:
                self.board.db.execute("UPDATE relay SET seen=? WHERE device=?", (t, device))
                self.board.db.commit()
        return out

    def view(self, auth, now):
        device = self.phone(auth)
        self.board.limit("view", device, now)
        with self.lock:
            e = self._entry(device)
            t = time.time()
            started = t - e["viewer_seen"] >= RELAY_WATCH
            e["viewer_seen"] = t
            if started and self._online(e, t):  # 처음 열면 Mac 을 깨워 새 상태를 잠깐 기다린다
                e["wake"] = True
                e["cond"].notify_all()
                end = time.monotonic() + RELAY_FRESH
                while e["state_at"] < t and time.monotonic() < end:
                    e["cond"].wait(end - time.monotonic())
            t = time.time()
            return {"state": json.loads(e["state"]) if e["state"] else None, "stateAt": e["state_at"] or None,
                    "macSeen": t if e["waiting"] else (e["mac_seen"] or None), "online": self._online(e, t), "now": t}

    def command(self, auth, body, now):
        device = self.phone(auth)
        self.board.limit("command", device, now)
        if not isinstance(body, dict):
            raise BadRequest()
        cid, action = body.get("id"), body.get("action")
        if not isinstance(cid, str) or not CMD_ID.fullmatch(cid) or action not in ACTIONS:
            raise BadRequest()
        cmd = {"id": cid, "action": action}
        if action in ("plant", "unlock"):
            if body.get("kind") not in KINDS:
                raise BadRequest()
            cmd["kind"] = body["kind"]
        if action == "hire":
            if body.get("role") not in ROLES:
                raise BadRequest()
            cmd["role"] = body["role"]
        with self.lock:
            e = self._entry(device)
            t = time.time()
            if not self._online(e, t):
                raise BadRequest("mac_asleep")
            e["commands"] = [c for c in e["commands"] if t - c["at"] < RELAY_CMD_TTL]
            if len(e["commands"]) >= RELAY_QUEUE:
                raise RateLimited()
            cmd["at"] = t
            e["commands"].append(cmd)
            e["cond"].notify_all()
        return {"ok": True}

    def maintain(self, now):
        t = now.timestamp()
        with self.board.lock:
            self.board.db.execute("DELETE FROM relay WHERE seen < ?", (t - RELAY_KEEP_DAYS * 86400,))
            self.board.db.commit()
        with self.lock:  # 하루 넘게 아무도 안 온 기기의 메모리 상태
            for d in [d for d, e in self.live.items() if not e["waiting"] and max(e["mac_seen"], e["viewer_seen"], e["state_at"]) < t - 86400]:
                del self.live[d]


# HTTP

def make_server(board, port=8891, host="127.0.0.1", static=None, relay=None):
    relay = relay or Relay(board)

    class Handler(BaseHTTPRequestHandler):
        server_version = "lemondesk-brag"
        timeout = 30  # 요청을 천천히 보내며 스레드를 붙잡는 연결을 끊는다(롱폴링 대기는 소켓 시간이 아니라 상관없다)

        def log_message(self, fmt, *args):  # 접속 기록에 IP 를 남기지 않는다
            sys.stderr.write("%s %s\n" % (self.command, self.path.split("?")[0]))

        def client_ip(self):
            # Cloudflare 터널(집서버) → CF-Connecting-IP, Caddy(회사 인프라) → X-Forwarded-For 첫 번째.
            # 회사 인프라 앞에는 Cloudflare 가 없어 CF 헤더를 누구나 지어 보낼 수 있으니 집서버 경로일 때만 믿는다.
            fwd = (self.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
            cf = self.headers.get("CF-Connecting-IP") if PREFIX == "/lemondesk/api/" else None
            return cf or fwd or self.client_address[0]

        def cors(self):
            if CORS_ORIGIN and self.headers.get("Origin") == CORS_ORIGIN:
                self.send_header("Access-Control-Allow-Origin", CORS_ORIGIN)
                self.send_header("Vary", "Origin")

        def send(self, status, obj):
            body = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(status)
            self.cors()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def body(self, limit=MAX_BODY):
            n = int(self.headers.get("Content-Length") or 0)
            if not 0 <= n <= limit:
                raise BadRequest("too_large")
            try:
                return json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                raise BadRequest()

        def route(self, method):
            u = urlparse(self.path)
            if static and method == "GET" and u.path.startswith("/lemondesk/") and not u.path.startswith(PREFIX):
                return self.serve_static(u.path[len("/lemondesk/"):])
            if u.path == "/":  # 호스팅 쪽 헬스체크용
                return self.send(200, {"ok": True})
            if not u.path.startswith(PREFIX):
                return self.send(404, {"error": "not_found"})
            parts = [p for p in u.path[len(PREFIX):].split("/") if p]
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            now = datetime.now(KST)
            owner = self.headers.get("X-Owner-Key")
            try:
                if parts[:1] == ["relay"]:
                    return self.relay(method, parts[1:], q, now)
                if method == "GET" and parts == ["health"]:
                    return self.send(200, {"ok": True})
                if method == "GET" and parts == ["posts"]:
                    week = q.get("week") or board.week(now)
                    return self.send(200, {"week": week, "posts": board.list(week, q.get("sort", "new"), int(q.get("page", 0) or 0), q.get("voter"))})
                if method == "GET" and len(parts) == 2 and parts[0] == "posts":
                    p = board.get(parts[1], q.get("voter"))
                    return self.send(200, p) if p else self.send(404, {"error": "not_found"})
                if method == "POST" and parts == ["posts"]:
                    return self.send(200, board.create_or_update(owner, self.body(), self.client_ip(), now))
                if method == "POST" and len(parts) == 3 and parts[0] == "posts" and parts[2] == "star":
                    return self.send(200, board.toggle_star(parts[1], self.body().get("voter"), self.client_ip(), now))
                if method == "POST" and len(parts) == 3 and parts[0] == "posts" and parts[2] == "report":
                    board.report(parts[1], self.client_ip(), now)
                    return self.send(200, {"ok": True})
                if method == "POST" and parts == ["stats", "install"]:
                    board.install(self.body(), self.client_ip(), now)
                    return self.send(200, {"ok": True})
                if method == "POST" and parts == ["stats", "ping"]:
                    board.ping(self.body(), self.client_ip(), now)
                    return self.send(200, {"ok": True})
                if method == "GET" and parts == ["stats"]:
                    auth = self.headers.get("Authorization") or ""
                    if not STATS_TOKEN or not hmac.compare_digest(auth.encode(), ("Bearer " + STATS_TOKEN).encode()):
                        return self.send(403, {"error": "forbidden"})
                    return self.send(200, board.summary(int(q.get("days") or 30), now))
                if method == "GET" and parts == ["highlights"]:
                    return self.send(200, board.highlights(q.get("week") or board.week(now), now))
                if method == "GET" and parts == ["weeks"]:
                    return self.send(200, {"current": board.week(now), "weeks": board.weeks()})
                if method == "GET" and parts == ["me"]:
                    return self.send(200, board.me(owner, now))
                if method == "DELETE" and parts == ["me"]:
                    return self.send(200, {"deleted": board.delete_mine(owner)})
                return self.send(404, {"error": "not_found"})
            except BadRequest as e:
                return self.send({"unauthorized": 401, "mac_asleep": 409, "conflict": 409, "too_large": 413}.get(e.code, 422), {"error": e.code})
            except RateLimited:
                return self.send(429, {"error": "rate_limited"})
            except KeyError:
                return self.send(404, {"error": "not_found"})
            except ValueError:
                return self.send(422, {"error": "bad_data"})

        def relay(self, method, parts, q, now):
            auth = self.headers.get("Authorization")
            if method == "POST" and parts == ["pair"]:
                return self.send(200, relay.pair(auth, self.body(), self.client_ip(), now))
            if method == "DELETE" and parts == []:
                return self.send(200, relay.unpair(auth))
            if method == "POST" and parts == ["state"]:
                return self.send(200, relay.push(auth, self.body(RELAY_STATE_MAX), now))
            if method == "GET" and parts == ["wait"]:
                return self.send(200, relay.wait(auth, float(q.get("t") or RELAY_WAIT), now))
            if method == "GET" and parts == ["view"]:
                return self.send(200, relay.view(auth, now))
            if method == "POST" and parts == ["command"]:
                return self.send(200, relay.command(auth, self.body(), now))
            return self.send(404, {"error": "not_found"})

        def serve_static(self, rel):
            root = os.path.abspath(static)
            path = os.path.normpath(os.path.join(root, rel or "index.html"))
            if os.path.isdir(path):
                path = os.path.join(path, "index.html")
            if not path.startswith(root + os.sep) or not os.path.isfile(path):
                return self.send(404, {"error": "not_found"})
            with open(path, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(path)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self.route("GET")

        def do_POST(self):
            self.route("POST")

        def do_DELETE(self):
            self.route("DELETE")

        def do_OPTIONS(self):  # 게시판 페이지의 CORS 사전 요청(JSON 본문 POST)
            self.send_response(204)
            self.cors()
            self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
            self.send_header("Access-Control-Max-Age", "86400")
            self.send_header("Content-Length", "0")
            self.end_headers()

    srv = ThreadingHTTPServer((host, port), Handler)
    srv.relay = relay
    return srv


def open_board(data_dir):
    os.makedirs(data_dir, exist_ok=True)
    salt_path = os.path.join(data_dir, "salt")
    if not os.path.exists(salt_path):
        with open(salt_path, "wb") as f:
            f.write(secrets.token_bytes(32))
        os.chmod(salt_path, 0o600)
    with open(salt_path, "rb") as f:
        salt = f.read()
    return Board(os.path.join(data_dir, "brag.sqlite3"), salt)


def main(argv):
    global PREFIX, BOARD_URL, CORS_ORIGIN, STATS_TOKEN
    STATS_TOKEN = os.environ.get("STATS_TOKEN", "")
    args = dict(zip(argv[1::2], argv[2::2])) if argv[1:2] != ["admin"] else {}
    # 회사 인프라는 Data dir 을 IX_DATA_DIR 로, 포트를 PORT 로 넣어 준다
    data = os.path.expanduser(os.environ.get("IX_DATA_DIR") or os.environ.get("BRAG_DATA") or args.get("--data") or "~/sites-data/lemondesk")
    PREFIX = args.get("--prefix", PREFIX)
    BOARD_URL = args.get("--board", BOARD_URL)
    CORS_ORIGIN = args.get("--cors", CORS_ORIGIN)
    board = open_board(data)
    if argv[1:2] == ["admin"]:
        cmd, pid = (argv[2:] + ["", ""])[:2]
        if cmd == "list":
            for r in board.db.execute("SELECT id, week, nickname, hidden, (SELECT COUNT(*) FROM reports WHERE post=posts.id) "
                                      "FROM posts ORDER BY created DESC LIMIT 100"):
                print("%s %s %-12s hidden=%d reports=%d" % r)
        elif cmd in ("hide", "unhide"):
            board.db.execute("UPDATE posts SET hidden=? WHERE id=?", (1 if cmd == "hide" else 0, pid))
            board.db.commit()
        elif cmd == "delete":
            board.db.execute("DELETE FROM stars WHERE post=?", (pid,))
            board.db.execute("DELETE FROM reports WHERE post=?", (pid,))
            board.db.execute("DELETE FROM highlights WHERE post=?", (pid,))
            board.db.execute("DELETE FROM posts WHERE id=?", (pid,))
            board.db.commit()
        else:
            print(__doc__)
        return
    srv = make_server(board, port=int(os.environ.get("PORT") or args.get("--port", 8891)),
                      host=args.get("--host", "127.0.0.1"), static=args.get("--static"))

    def maintenance():
        while True:
            try:
                board.maintain(datetime.now(KST))
                srv.relay.maintain(datetime.now(KST))
            except Exception as e:  # 정리가 실패해도 API 는 계속 돈다
                sys.stderr.write("maintain failed: %r\n" % e)
            time.sleep(3600)

    threading.Thread(target=maintenance, daemon=True).start()
    sys.stderr.write("brag api on %s:%d data=%s\n" % (srv.server_address[0], srv.server_address[1], data))
    srv.serve_forever()


if __name__ == "__main__":
    main(sys.argv)
