#!/usr/bin/env python3
"""Lemon Desk 자랑 게시판 API.

표준 라이브러리만 쓴다(집서버 /usr/bin/python3 3.9). 앱의 "자랑하기"가 올리고, 웹 게시판(site/brag/)이 읽고 별을 준다.
- 로그인 없음: 앱이 만든 무작위 소유 키(64 hex)의 sha256 만 저장한다.
- IP 는 hmac(salt, ip) 앞 16자만 저장한다(횟수 제한, 신고·별 중복 방지).
- 한 소유자가 한 주(KST ISO 주)에 게시물 하나. 다시 올리면 내용만 바뀌고 별은 남는다.
- 지난주 하이라이트(별 Top 10 + 재미 부문 3개)는 월요일에 스냅숏으로 영구 보관, 나머지 게시물은 8주 뒤 지운다.
- 폰으로 보기(1.6, relay/…): Mac 앱과 폰 웹페이지(site/m/) 사이 중계. 페어링 키는 해시로만 DB 에, 과수원 상태·명령은 메모리에만.
- 서리(1.8, raid/…): 1.8 이상 모든 설치가 창고 상태(정원·종류별 개수·탱자 수·창고 레벨)를 알리고, 남의 창고에서 과일을 조금 가져온다.
  키는 자랑 소유 키(X-Owner-Key)와 같다. 한 사람은 늘 '누군가'로 숨기고, 기록은 8주 뒤 지운다.
- 이웃(1.11, neighbors/…): 같은 소유 키로 초대 코드를 넣으면 바로 양쪽 이웃. 이웃마다 하루 한 번씩 돕기·선물(과일 한 개)을 보내고,
  받는 쪽은 raid/status 의 inbox 로 받는다. 이웃 관계·코드·돕기 기록·과수원 모습(look)·고마움 수·내가 정한 과수원 이름(1.12)만 저장하고,
  돕기 기록은 8주 뒤 지운다.
- 쩔(1.13, neighbors/dispatch|basket|sapling): 창고 레벨이 4 이상 높은 선배가 후배 이웃에게 일꾼 출장·큰 바구니·묘목을 보낸다.
  받는 쪽 상한은 모든 선배를 합쳐 센다. 쩔 기록(carries)은 8주 뒤 지우고, 사제 단계는 이웃 관계(neighbors.steps)에 비트로 남긴다.
- 1.14(docs/research/mobile-1.14.md): 이웃 찾기·요청(neighbors/discover|request|accept|decline|block|prefs, 요청·차단 기록),
  폰 중계 예약(Mac 이 잠든 동안 '내 과수원' 명령을 relay_queue 에, Mac 이 relay/queue 로 받는다)과 대리(relay/link 로 소유 키 해시를
  기기에 이어 두면 잠든 동안 이웃 명령을 서버가 처리하고 내 쪽 변화를 relay_effects 에 쌓는다).
- 1.15(docs/research/manager-1.15.md): 폰 명령 mgr_hire·mgr_set·stand_up·make·fill, 이웃 찾기 sort=mentor(선배·후배가 될 곳),
  사용 통계 mg·pv·ms(매니저 레벨·폰으로 보기·매니저 판매 수)와 /stats 의 판매 분포·나무 종류 분포·서리 진단(새로 저장하는 것 없음).
- 기기 연동(1.15.1, docs/research/sync-1.15.1.md, sync/…): 켠 소유 키만 과수원 저장 사본(bundle)·홀더 기기·기기 목록(기기 키 해시,
  mac·windows, laptop·desktop, 마지막 접속)을 저장한다. 진행하는 기기(홀더)는 하나, 다른 기기는 take 로 이어받는다.
  사용 통계 sync(off·on·holder).
- 1.16: 폰 명령 mgr_set 의 plan 이 도담 모드로 늘고, 사용 통계 mm(도담 모드)과 /stats 의 모드 분포.
- 1.17(docs/research/collection-1.17.md): 게시물 칭호·배지·진열장·장면, 스탬프(posts/<id>/stamp), 게시판 표(brag/ticket)와
  구경꾼 날(소유 키 해시·날짜), 배지 수(badges/<id>), 이주의 주제·스탬프 부문, raid/status 의 brag 보상 요약, 게시물로 이웃 요청.

실행: python3 brag.py [--data DIR] [--port 8891] [--host 127.0.0.1] [--prefix /lemondesk/api/] [--board URL] [--cors 출처] [--static SITE_DIR]
  --static 은 로컬 확인용: /lemondesk/<경로> 를 SITE_DIR 에서 준다
  --raid-fast YES 는 로컬 확인용: 베타 때처럼 새 키·초보 보호·창고 20%·하루 3번·손실 상한·당한 뒤 개 없이 바로 서리하고, 작전이 6~10초
  회사 인프라: python brag.py --host 0.0.0.0 --prefix /api/ --board https://lemondesk.interaction.hnine.com/brag/ --cors https://lemondesk.interaction.hnine.com
              (PORT, IX_DATA_DIR 은 인프라가 넣어 준다)
관리: python3 brag.py admin list|hide ID|unhide ID|delete ID|clear-name 과수원 이름
"""
import base64
import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import statistics
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
          "pair": (30, 3600), "state": (1800, 3600), "wait": (1200, 3600), "view": (3600, 3600), "command": (600, 3600),
          # 서리(1.8): 소유 키당, raid_ip·farm_new 는 IP 당(가짜 키를 많이 만들어 터는 것을 막는다)
          "raid_status": (240, 3600), "raid_targets": (120, 3600), "raid": (30, 3600), "raid_ip": (120, 3600), "farm_new": (30, 3600),
          # ponytail: 주인이 깨어 있다는 신호(팔기·관리 창)는 시간당 4번까지만 들킴으로 친다(늘 깨어 있는 척해 서리를 다 막지 못하게)
          "raid_active": (4, 3600),
          # 이웃(1.11): 소유 키당, neighbor_add_ip 는 IP 당(키를 바꿔 가며 코드를 마구 넣어 보지 못하게)
          "neighbors": (120, 3600), "neighbor_code": (10, 3600), "neighbor_add": (20, 3600), "neighbor_add_ip": (30, 3600),
          "neighbor_send": (60, 3600), "neighbor_name": (10, 3600),
          # 1.14 이웃 찾기·요청(소유 키당), 예약 명령 받아 가기(기기당)
          "discover": (120, 3600), "neighbor_request": (60, 3600), "queue": (600, 3600),
          # 1.15.1 기기 연동: 소유 키당(올리기 10초 몰아서 + 멈춘 기기 1분마다 확인), 코드 넣기는 IP 당
          "sync": (1200, 3600), "sync_redeem": (20, 3600),
          # 1.15.2 버그 신고: 표는 소유 키당, 올리기는 IP 당(하루 개수는 소유 키당 BUG_PER_DAY 로 따로 센다)
          "bug_ticket": (10, 3600), "bug": (10, 3600),
          # 1.17 스탬프는 IP 당, 게시판 표는 소유 키당
          "stamp": (300, 3600), "brag_ticket": (30, 3600)}
STATS_KEEP_DAYS = 90       # 사용 통계 원본 보관(그 뒤로는 날짜별 합계만)
STATS_TOKEN = ""           # 통계 조회 토큰(환경 변수 STATS_TOKEN). 비어 있으면 조회를 막는다.
ARCHES = {"arm64", "x86_64"}
PLATFORMS = {"mac", "win"}  # 윈도우판(2026-11-12). 옛 앱은 platform 을 안 보내므로 mac
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
RELAY_STATE_MAX = 64 * 1024  # Mac 이 올리는 상태 크기(v2 는 후반 과수원에서 15KB 안팎, 1.12 부터 넓힌 칸까지 전부 보낸다)
RELAY_WAIT = 25              # Mac 롱폴링 최대 초(앞단 프록시 시간 제한보다 짧게)
RELAY_WAITERS = 2            # 한 기기가 동시에 열 수 있는 대기(잠자기에서 깨면 끊긴 대기가 하나 남아 있다)
RELAY_WAITERS_ALL = 2000     # 서버 전체 동시 대기. 넘으면 기다리지 않고 바로 답한다(스레드 고갈 방지)
RELAY_WATCH = 30             # 폰이 이 초 안에 봤으면 '보는 중'
RELAY_ONLINE = 35            # Mac 이 이 초 안에 왔으면(또는 기다리는 중이면) 깨어 있음. 롱폴링(RELAY_WAIT)을 쉬지 않고 이으므로 그보다 조금 길게(1.14: 90 이면 앱을 끈 직후 명령이 예약되지 않고 사라졌다)
RELAY_FRESH = 3              # 폰이 처음 열 때 Mac 의 새 상태를 기다리는 초
RELAY_CMD_TTL = 30           # 명령을 Mac 이 가져가지 않으면 버리는 초
RELAY_QUEUE = 10
RELAY_KEEP_DAYS = 90         # 쓰지 않는 페어링 보관
RELAY_RESULT = 3             # 폰 명령이 Mac 의 처리 결과를 기다리는 초(넘으면 폰이 다시 묻는다)
RELAY_ASKERS = 4             # 한 기기에서 동시에 결과를 기다릴 수 있는 명령 수
# 1.14 Mac 이 잠들었을 때(docs/research/mobile-1.14.md 확정 절): '내 과수원' 명령은 시각과 함께 쌓아 두고(예약),
# 이웃 명령(nb_*)은 서버가 그 과수원 대리로 바로 처리한다. 서리 명령은 깨어 있을 때만.
RELAY_QUEUE_MAX = 50
RELAY_QUEUE_KEEP = 72 * 3600  # 앱 Balance.maxOffline(따라잡기 상한)과 같게
RELAY_SERVER_RESULTS = 10     # 대리로 처리한 결과를 상태 results[] 에 섞어 줄 개수
RELAY_SERVER_RESULT_TTL = 600
# 대리로 처리한 결과({id, ok, reason, message, code}): reason 은 Mac 결과와 같은 poor|unavailable|failed, code 는 서버 오류 코드 그대로
PROXY_POOR = {"no_fruit"}
PROXY_MESSAGES = {
    "no_fruit": "창고에 그 과일이 모자라요", "done_today": "이미 보냈어요. 다음 때 다시 해 주세요", "full": "이웃이 가득 찼어요",
    "already": "이미 이웃이에요", "pending": "이미 요청을 보냈어요", "cooldown": "조금 뒤에 다시 요청할 수 있어요",
    "closed": "지금은 요청을 받지 않는 과수원이에요", "rate_limited": "너무 많이 보냈어요. 나중에 다시 해 주세요",
    "bad_code": "코드를 찾지 못했어요", "not_junior": "후배에게만 보낼 수 있어요", "taken_today": "오늘은 이미 받았어요",
    "taken_week": "이번 주에는 이미 받았어요", "busy": "그 일꾼은 지금 바빠요", "holding": "아직 심지 않은 묘목이 있어요",
    "not_found": "그 과수원을 찾지 못했어요", "no_farm": "Mac 에서 과수원을 한 번 맞춘 뒤에 할 수 있어요"}

# 자랑 게시판 조작 방지(1.7.1): 올린 숫자가 게임에서 나올 수 있는 범위인지 본다. 앱 Balance.swift 와 같은 값(test_brag 가 대조한다).
# 게임 저장은 서버로 옮기지 않는다. 가능한 최대치 바로 아래로 꾸민 숫자는 못 막고, 신고·관리 명령이 나머지를 맡는다.
WEEK = 7 * 86400
MAX_TREES = 10               # 앞 10칸: 이웃 모습(look)의 나무 줄 상한(1.12 부터 땅은 끝이 없고 앱은 앞 10칸만 보낸다)
MAX_BRAG_TREES = 60          # 자랑 게시물의 나무 줄 상한(1.17.3, 앱 Balance.Land.bragMax)
MIN_FRUIT_INTERVAL = 20      # 가장 빨리 열리는 나무(핑거라임)의 열매 간격(초)
MAX_FRUIT_PRICE = 900        # 가장 비싼 열매(포멜로)
GROW_PER_LEVEL = 0.15        # 돌보기 레벨당 성장 배율
PRICE_PER_LEVEL = 0.12       # 심기 레벨당 판매가 배율
CREW2 = 1.5                  # 두 번째 일꾼 효과
SEASON_GROW, FENCE_GROW, SEASON_PRICE = 1.15, 1.4, 1.5  # 봄 성장, 탱자 양옆, 겨울 유자값
MAX_CRATE = round(40 * 1.5 ** 12 * 1.25 ** 6)            # 창고 최대(레벨 18)
SLACK = 1.2                  # 여유(시계 오차·주 경계)

# 끝없는 땅(1.12). 앱 Balance.Land 와 같은 값. 맥이 밸런스로 바꾸면 여기 숫자만 고치고 python3 server/land_cases.py 로
# server/land_cases.json 을 다시 만든다(앱·윈도우·서버 테스트가 그 파일로 대조한다).
LAND_START = 10              # 처음 칸 수
LAND_BASE = 10_000           # 11번째 칸 값
LAND_GROWTH, LAND_KNEE, LAND_GROWTH_AFTER = 2.0, 22, 1.07  # 22칸이 될 때까지 칸마다 2배, 그 뒤로는 1.07배(맥 BalanceTests 로 고름)
LAND_COST_MAX = 10**18       # 앱처럼 여기서 멈춘다(Int 넘침 방지, 그 전에 코인이 모자란다)
LAND_SECONDS, LAND_STEP, LAND_SECONDS_MAX = 3_600, 0.5, 28_800  # 개간 시간: 1시간에서 칸마다 30분씩, 8시간까지
MAX_PLOTS = 100_000          # 받는 칸 수·칸 번호·탱자 수 상한(땅은 끝이 없지만 받는 숫자에는 둔다)
MAX_EARNED = 10**15          # 지금까지 번 코인 상한


def land_cost(plots):
    """지금 칸 수가 plots 일 때 다음 한 칸 값. 앱 Balance.Land.cost 와 같은 순서로 곱하고, 앱 .rounded() 처럼 0.5 는 올린다
    (Python round 는 짝수 쪽이라 안 쓴다). 너무 크면 LAND_COST_MAX(앱의 min(1e18, …))."""
    try:
        x = LAND_BASE * LAND_GROWTH ** (min(plots, LAND_KNEE) - LAND_START) * LAND_GROWTH_AFTER ** max(0, plots - LAND_KNEE)
    except OverflowError:
        return LAND_COST_MAX
    if x >= LAND_COST_MAX:
        return LAND_COST_MAX
    return min(LAND_COST_MAX, int(x) + (x % 1 >= 0.5))


def land_seconds(plots):
    """지금 칸 수가 plots 일 때 다음 칸 개간 시간(초, 앱처럼 실수)"""
    return float(min(LAND_SECONDS_MAX, LAND_SECONDS * (1 + LAND_STEP * (plots - LAND_START))))


def land_total(plots, stop=float("inf")):
    """11번째부터 plots 번째 칸까지 값 합(plots ≤ 10 이면 0). 합이 stop 을 넘으면 거기서 멈춘다
    (지어 낸 큰 칸 수도 금방 끝난다)."""
    total = 0
    for p in range(LAND_START, plots):
        total += land_cost(p)
        if total > stop:
            break
    return total


GOODS = 1.5 * 1.45  # 1.15 병 값 배율 × 주문 보상 최대 배율(앱 Balance.Stand)
MANAGER_TOP = 2.0  # 앱 Balance.Manager.rates 의 가장 큰 값
SELL_TOP = max(GOODS, 1.5 * MANAGER_TOP)


def plausible(post, baskets=0, dispatches=0):
    """올린 일꾼 레벨로 일주일에 나올 수 있는 최대치 안인지. 레벨은 오르기만 하므로 지금 레벨이 그 주의 상한이다.
    나무는 주중에 바꿔 심을 수 있어 가장 빠른 나무가 밭 칸 수만큼 있다고 본다(손으로 따면 수확 일꾼 속도와 무관).
    밭 칸 수(1.12)는 넓힌 칸 값의 합이 지금까지 번 코인 안이어야 한다(옛 앱은 안 보내 10칸).
    쩔(1.13): 이번 주 받은 바구니 과일 수(baskets)만큼 수확·판매 상한을 넓히고, 받은 출장(dispatches)마다
    4시간 동안 상한 레벨 일꾼(돌보기·심기)이 더 있었다고 본다."""
    card, orch, land = post["card"], post["orchard"], post["land"]
    spendable = land["earned"] * SLACK
    if land_total(land["plots"], spendable) > spendable:
        return False

    def boost(role, per):
        w = orch["workers"].get(role)
        return 1 + per * w["level"] * (CREW2 if len(w["looks"]) >= 2 else 1) if w else 1

    harvest_max = WEEK * land["plots"] * boost("caretaker", GROW_PER_LEVEL) * SEASON_GROW * FENCE_GROW / MIN_FRUIT_INTERVAL * SLACK + 500
    lifted = dispatches * DISPATCH_SECONDS * land["plots"] * (1 + GROW_PER_LEVEL * DISPATCH_LEVEL_CAP * CREW2) * SEASON_GROW * FENCE_GROW / MIN_FRUIT_INTERVAL * SLACK
    if card["harvested"] > harvest_max + lifted + baskets or card["sold"] > card["harvested"] + MAX_CRATE + baskets:
        return False
    extra = dispatches * (MAX_CRATE + lifted) * MAX_FRUIT_PRICE * (1 + PRICE_PER_LEVEL * DISPATCH_LEVEL_CAP * CREW2) * SEASON_PRICE * SLACK
    # 1.15 가판대: 병은 제값의 1.5배, 병 주문 보상은 그 1.45배까지(Balance.Stand) → 레몬 하나당 최대 GOODS 배
    if card["earned"] > card["sold"] * MAX_FRUIT_PRICE * SELL_TOP * boost("planter", PRICE_PER_LEVEL) * SEASON_PRICE * SLACK + extra:
        return False
    kinds = set(orch["trees"]) - {"rainbow"}
    if len(kinds) > orch["dex"] or (orch["rainbow"] and orch["dex"] < 12) or ("rainbow" in orch["trees"] and not orch["rainbow"]):
        return False
    return True

# 서리(1.8). 앱 Balance.Raid 와 같은 규칙(server/raid_cases.json 을 양쪽 테스트가 읽어 대조한다). 확률은 없다.
FRUITS = [("eureka", 2), ("kumquat", 4), ("meyer", 7), ("calamansi", 12), ("lime", 20), ("fingerlime", 5), ("blood", 34),
          ("trifoliate", 2), ("yuja", 55), ("snowyuja", 60), ("grapefruit", 90), ("redhyang", 115), ("moonlemon", 150),
          ("pink", 150), ("cheonhye", 190), ("hallabong", 250), ("bergamot", 330), ("buddha", 420), ("pomelo", 900),
          ("golden", 700), ("rainbow", 700)]  # 앱 TreeKind 순서와 열매 한 개 값
PRICE = dict(FRUITS)
ORDER = {k: i for i, (k, _) in enumerate(FRUITS)}
RAID_PER_DAY = 3
SACK_BASE, SACK_PER_LEVEL, HARVESTER_SACK = 6.0, 1.2, 1.25
RAID_TAKE = 0.08             # 상대 창고에 든 개수의 8%
DAILY_LOSS = 0.2             # 하루에 잃는 개수 상한: 창고 정원의 20%
FENCE, FENCE_MAX = 0.2, 0.6  # 탱자 한 그루마다 −20%, 최대 −60%
DOG, MAX_DOGS, GUARD_MAX = 0.15, 3, 0.75  # 집 지키는 개 한 마리마다 −15%(최대 3마리), 탱자와 합쳐 최대 −75%
VALUE_SHARE = 0.15           # 한 번에 가져오는 값 상한: 내 정원 × 내가 연 가장 비싼 과일 값의 15%
RAID_PLANS = {"light": 300, "normal": 600, "deep": 1200}
CARETAKER_FAST = 0.7
CAUGHT_REST = 600            # 들키면 혹이 나서 10분 늦게 돌아온다
# 정식 값(1.11, 대표 결정 2026-11-15). 1.8 베타 동안은 숨김 조건(창고 20%·초보 3일·창고 레벨 2·새 키 하루)을 0 으로,
# BETA_OPEN 을 True 로 두어 같은 곳 하루 한 번만 남기고 하루 3번·하루 손실 상한·당한 뒤 개 2시간도 껐다(지금은 --raid-fast 만 그렇게).
BETA_OPEN = False
MIN_FILL = 0.2               # 창고가 이만큼 찬 과수원만
MIN_LEVEL = 2                # 창고 레벨이 이 이상인 과수원만
GUARD = 2 * 3600             # 당한 뒤 개가 짖는 시간
TRACKS = 86400               # 발자국(되갚기·되찾아 주기)
NEW_KEY = 86400              # 새 키는 이만큼 뒤부터 서리
NEWBIE = 3 * 86400           # 서버가 처음 본 뒤 이만큼은 서리당하지 않는다
STALE = 14 * 86400           # 소식 없는 설치는 대상에서 뺀다
RAID_TARGETS = 12
RAID_ID = re.compile(r"[A-Za-z0-9_-]{8,24}")
TARGET_ID = re.compile(r"[0-9a-f]{16}")  # 서리 대상·이웃 id(요청한 사람에게만 통하는 HMAC)

# 이웃(1.11). 앱 Balance.Neighbors 와 같은 값. 계정 없이 서리와 같은 소유 키로 맺는다.
MAX_NEIGHBORS = 20  # 1.15.4: 10 → 20(앱 Balance.Neighbors.maxNeighbors)
NEIGHBOR_DOG, MAX_NEIGHBOR_DOGS = 0.05, 3  # 개가 있는 이웃 한 곳마다 서리 −5%(최대 3곳, GUARD_MAX 안에서)
CODE_CHARS, CODE_LEN = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789", 6  # I·O·0·1 없음. 화면에는 ABC-DEF
STAMPS = {"heart", "note", "star"}       # 고마워요·반가워요·멋져요(자유 글은 없다)
SEASONS = {"spring", "summer", "autumn", "winter"}
TREE_LOOK = (KINDS, (0, 7))                    # 과수원 모습의 나무: 종류, 자란 단계
WORKER_LOOK = (ROLES, (0, 1), (0, 4), (0, 6))  # 일꾼: 역할, variant, 장비 단계, 염색
LOOK_MAX = 2048
INBOX = 20                   # raid/status 한 번에 주는 받은 돕기·선물 수

# 이웃 찾기·요청(1.14). id 는 이웃·서리 대상과 같은 _target_id(요청한 사람마다 다르다)
REQUESTS_PER_DAY, REQUESTS_PENDING = 20, 30
REQUEST_DAYS = 7 * 86400     # 요청이 사라지는 때이자, 거절·만료 뒤 같은 곳에 다시 요청을 막는 때
DISCOVER_PAGE = 20

# 선배·후배(1.13, docs/research/carry-1.13.md). 앱 Balance.Carry 와 같은 값.
JUNIOR_GAP = 4               # 내 창고 레벨 − 이웃 창고 레벨 ≥ 4 이고
GRADUATE_LEVEL = 12          # 이웃이 아직 졸업(창고 레벨 12) 전이면 그 이웃은 내 후배(그때그때 계산, 저장 안 함)
BASKET_SHARE, BASKET_FLOOR = 0.25, 3_000.0  # 큰 바구니 값 상한 = max(3,000, 다음 해금 값 × 0.25)
DISPATCH_SECONDS = 14_400    # 일꾼 출장 4시간
DISPATCH_LEVEL_CAP = 20      # 출장 일꾼 레벨 상한
CARRY_THANKS = {"dispatch": 2, "basket": 1, "sapling": 1, "step": 3}  # 받은 쪽이 반영(ack)하면 선배 고마움
# 앱 Balance.spec 의 unlockCost(test_brag 가 Balance.swift 와 대조한다). 무지개 레몬은 황금 레몬과 한 묶음
UNLOCK = {"eureka": 0, "kumquat": 60, "meyer": 150, "calamansi": 450, "lime": 1_200, "fingerlime": 2_000, "blood": 3_200,
          "trifoliate": 5_000, "yuja": 8_000, "snowyuja": 12_000, "grapefruit": 30_000, "redhyang": 60_000, "moonlemon": 90_000,
          "pink": 120_000, "cheonhye": 450_000, "hallabong": 2_000_000, "bergamot": 5_000_000, "buddha": 12_000_000,
          "pomelo": 22_000_000, "golden": 42_000_000, "rainbow": 42_000_000}
COLLECTIBLE = [k for k, _ in FRUITS if k != "rainbow"]  # 해금 순서(앱 TreeKind 순서)
SAPLING_RANGE = 2            # 묘목: 후배 best 다음 두 종류(해금 순서) 안
# 기기 연동(1.15.1, docs/research/sync-1.15.1.md 확정 절). 앱 Balance.Sync 와 같다
SYNC_MAX = 262_144           # maxBundle: sync/… 본문 상한(다른 API 는 MAX_BODY)
SYNC_CODE_TTL = 600          # codeTTL: 다른 기기 추가 코드(한 번만)
# 1.15.2 버그 신고(대표 요청 2026-11-17): 앱이 받은 일회용 표로만 쓴다(게임을 최근에 켠 사람만). 운영자만 본다.
BUG_TICKET_TTL = 3600        # 표 하나 = 신고 하나, 1시간
BUG_ACTIVE_DAYS = 14         # 서리 맞추기(farms.seen)가 이 안에 있어야 '활성 사용자'
BUG_PER_DAY = 5              # 소유 키당 하루 신고 수
BUG_TEXT = (5, 2000)         # 글 길이(자)
BUG_IMAGES, BUG_IMAGE_MAX = 3, 1_500_000   # 이미지 수, 한 장 바이트(브라우저가 줄여 올린다)
BUG_MAX = 6 * 1024 * 1024    # 올리기 본문 상한(base64 라 이미지보다 크다)
BUG_KEEP_DAYS = 180
SYNC_SKEW = 600              # clockSkew: 저장 시각(at)이 서버 시각보다 이만큼 넘게 미래면 bad_clock
SYNC_PLATFORMS = {"mac", "windows"}
SYNC_LABELS = {"laptop", "desktop"}
SYNC_TARGET = re.compile(r"[0-9a-f]{8}")  # 기기 목록 id = sha256(device) 앞 8자
SYNC_STATES = re.compile(r"(off|on|holder)?")  # 통계 ping 의 sync(옛 앱은 안 보낸다)
MANAGER_PLANS = {"cheap", "dex", "crew", "rich", "garden", "barista", "land", "custom"}  # 1.16 도담 모드, 1.18 custom

# 1.17 게시판(docs/research/collection-1.17.md 확정): 도전 id(앱 Achievements, 기본은 Goals id), 스탬프, 이주의 주제
_GOALS = {"plant": (1, 10, 30), "dex": (6, 12, 20), "rainbow": (1,), "crate": (6, 12, 18), "worker": (10, 20), "second": (1,),
          "gear": (3,), "sold": (100, 1_000, 10_000), "earned": (10_000, 1_000_000), "dogs": (3,), "secrets": (5, 10, 20),
          "scrump": (5, 10, 20), "neighbors": (1, 5), "acts": (10, 50), "gifted": (5, 10, 20), "thanks": (5, 15, 40),
          "land": (15, 20, 30, 50), "finds": (4, 8), "mentor": (1, 3, 5), "tasks": (1, 10, 50)}
ACHIEVEMENTS = ({"%s-%d" % (k, n) for k, ns in _GOALS.items() for n in ns}
                | {"exact999", "monoculture", "rainseller", "underrainbow", "lastone", "snowkumquat", "sevenfaces", "recipes",
                   "rainbowcloset", "names", "caughtthrice", "ironfarm", "giftbottle", "sunset", "moonpair", "firstharvest",
                   "myvariety", "friendship"}
                | {"midnight", "mondayblues", "tgif", "fullnight", "vacation", "lonelytree", "weekend", "allsky"})
BADGES_MAX = 3
SHOWCASE = {"variety", "plaque", "frame", "nickname", "trophy", "friend"}
BOARD_STAMPS = ("lemon", "flower", "laugh", "clap")  # 탐나요·예뻐요·웃겨요·대단해요
WEEK_THEMES = ("pink", "even", "manager", "dogs", "decor", "stand", "rare")  # ISO 주 번호 % 7
BRAG_TICKET_TTL = 3600
BURST = (600, 2)             # 보상 집계: 게시 뒤 10분 안에 같은 IP 해시에서 2개 넘게 몰린 반응은 뺀다
DECOR_ID = re.compile(r"[a-z0-9-]{1,32}")
POST_ID = re.compile(r"[A-Za-z0-9_-]{1,32}")
CATEGORIES = ("harvest", "secrets", "dex", "theme") + tuple("stamp-" + k for k in BOARD_STAMPS)  # 하이라이트 부문(1위 하나씩)


def week_theme(week):
    m = re.fullmatch(r"\d{4}-W(\d{2})", week or "")
    return WEEK_THEMES[int(m.group(1)) % len(WEEK_THEMES)] if m else None


def _twin(k):
    return "golden" if k == "rainbow" else k  # 무지개 레몬은 황금 레몬과 한 묶음(앱 priceTwin)


# 사제 단계(neighbors.steps 비트, 앱 Balance.Carry.Step 순서): 후배가 이 조건을 처음 넘으면 그 이웃 사이에서 한 번.
# crate12(창고 레벨 12)가 졸업. 유자·핑크 레몬은 가장 비싼 과일(farms.best)의 해금 순서로 본다(앱 reached 와 같게).
STEPS = (("crate6", 1, lambda lv, best: lv >= 6), ("crate12", 2, lambda lv, best: lv >= 12),
         ("yuja", 4, lambda lv, best: ORDER[_twin(best)] >= ORDER["yuja"]), ("pink", 8, lambda lv, best: ORDER[_twin(best)] >= ORDER["pink"]))
GRAD = 2


def is_junior(mine, theirs):
    """앱 Balance.Carry.isJunior: 창고 레벨이 4 이상 낮고 아직 졸업 전인 이웃이 후배(졸업 뒤까지 받으면 끝판이 빨라진다)"""
    return mine - theirs >= JUNIOR_GAP and theirs < GRADUATE_LEVEL


def next_unlock_value(best):
    """후배가 연 가장 비싼 과일(best)의 해금 순서 다음 종류 unlockCost(마지막이면 그 종류 값)"""
    i = COLLECTIBLE.index(_twin(best))
    return UNLOCK[COLLECTIBLE[min(i + 1, len(COLLECTIBLE) - 1)]]


def basket_value(best):
    """큰 바구니 값 상한(앱 Balance.Carry.basketValue): max(3,000, 다음 해금 값 × 0.25). 앱 .rounded() 처럼 0.5 는 올린다."""
    return int(max(BASKET_FLOOR, next_unlock_value(best) * BASKET_SHARE) + 0.5)


def sapling_kinds(junior_best, senior_best):
    """보낼 수 있는 묘목(앱 Balance.Carry.saplingKinds): 해금 순서로 후배 best 다음 두 종류 중 best 보다 비싼 것,
    그중 선배 best 값 이하(서버는 선배가 연 종류 목록을 모른다)"""
    b = _twin(junior_best)
    return [k for k in COLLECTIBLE if ORDER[b] < ORDER[k] <= ORDER[b] + SAPLING_RANGE and PRICE[b] < PRICE[k] <= PRICE[_twin(senior_best)]]


def week_start(now):
    """그 주(KST 월요일 0시) 시작 시각"""
    d = now.astimezone(KST)
    return (d - timedelta(days=d.weekday())).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def crate_capacity(level):
    return int(40 * 1.5 ** min(level, 12) * 1.25 ** max(0, level - 12) + 0.5)  # 앱 .rounded() 와 같게(반올림)


def raid_duration(role, plan):
    return RAID_PLANS[plan] * (CARETAKER_FAST if role == "caretaker" else 1)


def _size(k):
    return 3 if PRICE[k] >= 400 else 2 if PRICE[k] >= 100 else 1


def raid_budget(cap, best):
    return int(cap * PRICE[best] * VALUE_SHARE)


def raid_loot(crate, cap, fences, dogs, lost, role, level, plan, budget, revenge=False, neighbor_dogs=0):
    """한 번에 담아 오는 과일. 살짝은 값싼 것부터, 깊숙이는 비싼 것부터, 보통은 종류를 돌아가며 하나씩.
    자루 칸·상대 창고의 8%·오늘 남은 손실 허용량 중 가장 작은 만큼, 한 종류는 든 개수의 절반까지, 값은 budget 까지.
    neighbor_dogs(1.11): 당하는 쪽 이웃 중 개가 있는 곳 수. 앱과 같은 순서로 더해야 소수 끝자리까지 같다."""
    total = sum(crate.values())
    if total <= 0:
        return {}
    walls = min(FENCE_MAX, FENCE * fences) * (0.5 if role == "planter" else 1.0)
    guard = 1 - min(GUARD_MAX, walls + DOG * min(dogs, MAX_DOGS) + NEIGHBOR_DOG * min(neighbor_dogs, MAX_NEIGHBOR_DOGS))
    twice = 2.0 if revenge else 1.0
    slots = int((SACK_BASE + SACK_PER_LEVEL * level) * (HARVESTER_SACK if role == "harvester" else 1.0) * twice * guard)
    allow = max(0, int(cap * DAILY_LOSS) - lost)
    limit = min(max(1, int(total * RAID_TAKE * twice * guard)), allow)
    by_price = sorted((k for k, n in crate.items() if n > 0), key=lambda k: (PRICE[k], ORDER[k]))
    money = int(budget * twice)
    picked, state = {}, {"used": 0, "n": 0, "value": 0}

    def add(k):
        if (state["n"] >= limit or state["used"] + _size(k) > slots or state["value"] + PRICE[k] > money
                or picked.get(k, 0) >= crate[k] // 2):
            return False
        picked[k] = picked.get(k, 0) + 1
        state["used"] += _size(k)
        state["n"] += 1
        state["value"] += PRICE[k]
        return True

    if plan == "normal":
        more = True
        while more:
            more = False
            for k in by_price:
                more = add(k) or more
    else:
        for k in (by_price if plan == "light" else reversed(by_price)):
            while add(k):
                pass
    return picked


def raid_caught(loot):
    """들키면 담은 것의 절반만, 값싼 것부터"""
    items = [k for k in sorted(loot, key=lambda k: (PRICE[k], ORDER[k])) for _ in range(loot[k])]
    out = {}
    for k in items[:len(items) // 2]:
        out[k] = out.get(k, 0) + 1
    return out


def clean_farm(b):
    """앱이 알리는 창고 상태(서리 대상 판단·양 계산에만 쓴다). 나무·일꾼·코인·닉네임은 받지 않는다."""
    if not isinstance(b, dict):
        raise BadRequest()
    level = _int(b.get("level"), 0, 18)
    cap = _int(b.get("cap"), 1, MAX_CRATE)
    crate = b.get("crate")
    if cap != crate_capacity(level) or not isinstance(crate, dict) or any(k not in PRICE for k in crate):
        raise BadRequest()
    crate = {k: n for k, n in ((k, _int(v, 0, cap)) for k, v in crate.items()) if n > 0}
    if sum(crate.values()) > cap:
        raise BadRequest("implausible")
    ack = b.get("ack") or []
    if not isinstance(ack, list) or len(ack) > 50:
        raise BadRequest()
    if b.get("best") not in PRICE:
        raise BadRequest()
    return {"cap": cap, "level": level, "crate": crate, "fences": _int(b.get("fences"), 0, MAX_PLOTS),
            "dogs": _int(b.get("dogs", 0), 0, MAX_DOGS), "best": b["best"],
            "active": b.get("active") is True, "ack": [_match(a, RAID_ID) for a in ack],
            "look": clean_look(b.get("look")),  # 1.11. 옛 앱은 안 보낸다(None: 저장된 모습을 그대로 둔다)
            # 1.13: 받아 두고 아직 안 심은 묘목 종류(없으면 null). 있으면 새 묘목은 holding 으로 거절
            "seedling": isinstance(b.get("seedling"), str) and b["seedling"] in KINDS}


def _one(v, allowed):
    if not isinstance(v, str) or v not in allowed:
        raise BadRequest()
    return v


def _tuple(v, *specs):
    """[값, …] 한 줄. 칸마다 허용 집합 또는 (최소, 최대) 정수"""
    if not isinstance(v, list) or len(v) != len(specs):
        raise BadRequest()
    for x, s in zip(v, specs):
        if isinstance(s, tuple):
            _int(x, *s)
        else:
            _one(x, s)
    return v


def _rows(v, n, *specs):
    if not isinstance(v, list) or len(v) > n:
        raise BadRequest()
    return [_tuple(r, *specs) for r in v]


def clean_look(v):
    """과수원 모습(1.11, 이웃 엽서 그림용). 틀린 필드만 버린다(서리 맞추기는 그대로 성공).
    dict 가 아니거나 2KB 를 넘으면 None 이라 저장된 모습을 그대로 둔다."""
    if not isinstance(v, dict) or len(json.dumps(v, separators=(",", ":")).encode()) > LOOK_MAX:
        return None
    checks = {"trees": lambda x: _rows(x, MAX_TREES, *TREE_LOOK), "workers": lambda x: _rows(x, 6, *WORKER_LOOK),
              "dogs": lambda x: _int(x, 0, MAX_DOGS), "theme": lambda x: _one(x, THEMES), "season": lambda x: _one(x, SEASONS),
              "weeds": lambda x: _int(x, 0, 3)}  # 1.13 잡초·낙엽 단계
    out = {}
    for k, check in checks.items():
        try:
            out[k] = check(v[k])
        except (KeyError, BadRequest):
            pass
    return out


CMD_ID = re.compile(r"[A-Za-z0-9-]{1,40}")


def _v_int(lo, hi):
    return lambda v: isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi


def _v_in(allowed):
    return lambda v: isinstance(v, str) and v in allowed


def _v_re(pattern):
    return lambda v: isinstance(v, str) and pattern.fullmatch(v) is not None


def _v_opt(f):
    return lambda v: v is None or f(v)


_NID, _STAMP, _ROLE, _KIND, _FRUIT, _PLAN = _v_re(TARGET_ID), _v_in(STAMPS), _v_in(ROLES), _v_in(KINDS), _v_in(PRICE), _v_in(RAID_PLANS)
_TEXT = lambda v: isinstance(v, str) and len(v) <= 40  # noqa: E731 이름·검색어(이름 검사는 처리하는 쪽이 한다)
_BOOL = lambda v: isinstance(v, bool)  # noqa: E731
DISCOVER_SORTS = {"recent", "similar", "new", "mentor"}  # mentor: 1.15 선배 이어 주기
# 폰 → Mac 명령과 받는 칸(그 밖의 칸은 버린다). 본문의 id 는 명령 id 라서, 확정 절에 id 로 적힌 이웃·찾은 과수원은 target,
# 소품은 prop·pos 로 받는다(2026-11-16 코디네이터 정정). 실제로 되는지(코인·칸 수 등)는 Mac(또는 대리면 서버 규칙)이 본다.
MINE = {  # '내 과수원' 명령: Mac 이 잠들었으면 예약(1.14). hire2·replant: 1.7.1, care: 1.13 밭 치우기
    "sell": {}, "plant": {"kind": _KIND}, "unlock": {"kind": _KIND}, "hire": {"role": _ROLE}, "crate": {}, "hire2": {"role": _ROLE},
    "replant": {"plot": _v_int(0, MAX_PLOTS - 1), "kind": _KIND}, "care": {},
    "clear": {}, "seedling": {"plot": _v_opt(_v_int(0, MAX_PLOTS - 1))}, "theme": {"theme": _v_in(THEMES)},
    "dye": {"role": _ROLE, "slot": _v_opt(_v_int(0, 5)), "variant": _v_opt(_v_int(0, 1)), "dye": _v_int(0, 6)},
    "decor": {"prop": _v_re(re.compile(r"[a-z0-9-]{1,32}")),  # pos: 0~1, null 이면 치움
              "pos": _v_opt(lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 1)},
    # 1.15 매니저(고용·레벨 업, 할 일 켜고 끄기·사는 방식·남길 코인 %)·가판대(열기·레벨 업, 만들기)·손님 주문 채우기
    "mgr_hire": {}, "mgr_set": {"sell": _v_opt(_BOOL), "plant": _v_opt(_BOOL), "buy": _v_opt(_BOOL),
                                "plan": _v_opt(_v_in(MANAGER_PLANS | {"fruit"})),
                                "keep": _v_opt(lambda v: isinstance(v, int) and not isinstance(v, bool) and v in (0, 30, 50))},
    "mgr_task": {"op": _v_in({"add", "remove", "up"}), "i": _v_opt(_v_int(0, 9)), "task": _v_opt(lambda v: isinstance(v, dict) and set(v) <= {"kind", "target", "role", "tree"}
                 and v.get("kind") in ("land", "worker", "unlock", "raid", "help") and _v_opt(_v_int(1, MAX_PLOTS))(v.get("target"))
                 and _v_opt(_ROLE)(v.get("role")) and _v_opt(_KIND)(v.get("tree")))},  # 1.18 커스텀 도담 할 일
    "stand_up": {}, "make": {"recipe": _v_in({"lemonade", "syrup", "jam"})}, "fill": {"order": _v_re(re.compile(r"[a-z0-9]{1,16}"))}}
SERVER = {  # '서버' 명령: Mac 이 깨어 있으면 Mac 이 서버에 보내고, 잠들었으면 nb_* 만 서버가 대리로(서리는 mac_asleep)
    "nb_help": {"target": _NID, "stamp": _STAMP}, "nb_gift": {"target": _NID, "fruit": _FRUIT, "stamp": _STAMP},
    "nb_add": {"code": _v_re(re.compile(r"[A-Za-z0-9 -]{1,20}"))}, "nb_name": {"name": _TEXT},
    "nb_dispatch": {"target": _NID, "role": _ROLE}, "nb_basket": {"target": _NID, "fruit": _FRUIT, "count": _v_int(1, MAX_CRATE), "stamp": _STAMP},
    "nb_sapling": {"target": _NID, "kind": _KIND}, "nb_request": {"target": _NID, "stamp": _v_opt(_STAMP)},
    "nb_accept": {"target": _NID}, "nb_decline": {"target": _NID}, "nb_block": {"target": _NID},
    "nb_discover": {"q": _v_opt(_TEXT), "sort": _v_opt(_v_in(DISCOVER_SORTS)), "page": _v_opt(_v_int(0, 50))},
    "raid_targets": {}, "raid_send": {"target": _NID, "role": _ROLE, "plan": _PLAN},
    "raid_revenge": {"track": _v_re(RAID_ID), "role": _ROLE, "plan": _PLAN}, "raid_recover": {"target": _NID, "role": _ROLE, "plan": _PLAN}}
COMMANDS = {**MINE, **SERVER}
ACTIONS = set(COMMANDS)
KEY = re.compile(r"[0-9a-f]{64}")
URLISH = re.compile(r"(https?:|www\.|\.(com|net|org|kr|io|me|xyz|club)\b|@)", re.I)


class BadRequest(Exception):
    def __init__(self, code="bad_data"):
        super().__init__(code)
        self.code = code


class Owner(str):
    """이미 해시한 소유자(1.14 폰 대리: 서버는 relay_link 에 해시만 갖고 있다). Board.owner 가 그대로 쓴다."""


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
    if b.get("arch") not in ARCHES or b.get("platform", "mac") not in PLATFORMS:
        raise BadRequest()
    lang = b.get("lang") or ""
    return {"install": install, "day": day, "version": _match(b.get("version"), VERSION_RE), "os": _match(b.get("os"), VERSION_RE),
            "lang": _match(lang, LANG_RE) if lang else "", "arch": b["arch"],
            "minutes": _int(b.get("minutes"), 0, 1440), "opens": _int(b.get("opens"), 0, 10000),
            "sales": _int(b.get("sales"), 0, 100000), "kinds": _int(b.get("kinds"), 0, 13), "platform": b.get("platform", "mac"),
            # 1.11: 이웃 수, 최근 7일 안에 서리당했는지(0/1). 옛 앱은 안 보내므로 0
            "nb": _int(b.get("nb", 0), 0, MAX_NEIGHBORS), "rb": _int(b.get("rb", 0), 0, 1),
            # 1.15: 매니저 레벨, 폰으로 보기 켬(0/1), 그날 매니저가 판 횟수. 옛 앱은 안 보내므로 0
            "mg": _int(b.get("mg", 0), 0, 20), "pv": _int(b.get("pv", 0), 0, 1), "ms": _int(b.get("ms", 0), 0, 100000),
            # 1.15.1: 기기 연동 끔·켬(멈춤)·홀더. 옛 앱은 안 보내므로 ''
            "sync": _match(b.get("sync", ""), SYNC_STATES),
            # 1.16: 도담 모드(모르는 값·옛 앱은 '')
            "mm": b.get("mm") if b.get("mm") in MANAGER_PLANS else ""}


def clean_sync(b, now, *fields):
    """기기 연동 본문(확정 절 '검사'). device 는 sha256 으로, bundle 은 저장할 JSON 문자열로 바꿔 돌려준다."""
    if not isinstance(b, dict):
        raise BadRequest()
    out = {"device": sha(_match(b.get("device"), KEY))}
    for f in fields:
        v = b.get(f)
        if f == "platform" and v not in SYNC_PLATFORMS or f == "label" and v not in SYNC_LABELS:
            raise BadRequest()
        if f == "schema":
            v = _int(v, 1, 99)
        if f == "rev":
            v = _int(v, 0, 2 ** 53)
        if f == "at":
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not v >= 0:  # NaN 도 거른다
                raise BadRequest()
            if v > now.timestamp() + SYNC_SKEW:
                raise BadRequest("bad_clock")
        if f == "bundle":
            save = v.get("save") if isinstance(v, dict) else None
            if not (isinstance(save, dict) and isinstance(save.get("payload"), str) and isinstance(save.get("sig"), str)
                    and isinstance(v.get("prefs"), dict)):
                raise BadRequest()
            v = json.dumps(v, ensure_ascii=False, separators=(",", ":"))
        out[f] = v
    return out


def clean_install(b):
    """설치 신호(동의와 상관없이, 처음 실행 때 한 번). 식별자가 없다."""
    if (not isinstance(b, dict) or b.get("kind") not in ("new", "upgrade") or b.get("arch") not in ARCHES
            or b.get("platform", "mac") not in PLATFORMS):
        raise BadRequest()
    return {"version": _match(b.get("version"), VERSION_RE), "kind": b["kind"], "arch": b["arch"], "os": _match(b.get("os"), VERSION_RE),
            "platform": b.get("platform", "mac")}


def slot_key(dt):
    """돕기 칸(1.13, 이웃마다 하루 2번): 한국 시간 0~12시 오전, 12~24시 오후. 예: 2026-11-16am"""
    return day_key(dt) + ("am" if dt.astimezone(KST).hour < 12 else "pm")


def week_key(dt):
    y, w, _ = dt.astimezone(KST).isocalendar()
    return "%04d-W%02d" % (y, w)


def _int(v, lo, hi):
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise BadRequest()
    return v


def clean_nickname(v, most=12, code="bad_nickname"):
    if not isinstance(v, str):
        raise BadRequest(code)
    n = " ".join(v.split())
    flat = n.replace(" ", "").lower()
    if not 1 <= len(n) <= most or URLISH.search(n) or any(b in flat for b in BANNED) or any(ord(c) < 32 for c in n):
        raise BadRequest(code)
    return n


def _num(v, lo, hi):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
        raise BadRequest()
    return v


def clean_scene(v):
    """1.17 살아 있는 과수원(앞 60칸): 나무 종류·단계, 일꾼 역할·variant·염색·장비 단계, 개 수, 테마, 놓은 소품과 자리(0~1)"""
    if not isinstance(v, dict) or not all(isinstance(v.get(k, []), list) for k in ("trees", "workers", "decor")):
        raise BadRequest()
    trees, workers, decor = v.get("trees", []), v.get("workers", []), v.get("decor", [])
    if len(trees) > MAX_BRAG_TREES or len(workers) > 2 * len(ROLES) or len(decor) > 64 or v.get("theme") not in THEMES:
        raise BadRequest()
    d = lambda x: x if isinstance(x, dict) else {}  # noqa: E731
    return {"trees": [{"k": _one(d(t).get("k"), KINDS), "s": _int(d(t).get("s"), 0, 7)} for t in trees],
            "workers": [{"r": _one(d(w).get("r"), ROLES), "v": _int(d(w).get("v"), 0, 1), "d": _int(d(w).get("d"), 0, 6),
                         "t": _int(d(w).get("t"), 0, 4)} for w in workers],
            "dogs": _int(v.get("dogs", 0), 0, 3), "theme": v["theme"],
            "decor": [{"id": _match(d(p).get("id"), DECOR_ID), "x": _num(d(p).get("x"), 0, 1)} for p in decor]}


def clean_showcase(v):
    if not isinstance(v, dict) or v.get("kind") not in SHOWCASE:
        raise BadRequest("bad_showcase")
    out = {"kind": v["kind"]}
    if v.get("name") is not None and v["kind"] != "friend":  # 우정 소품은 이웃 이름 대신 '이웃과 함께'(게시판이 쓴다)
        out["name"] = clean_nickname(v["name"], 24, "bad_showcase")
    if v.get("text") is not None:
        out["text"] = clean_nickname(v["text"], 60, "bad_showcase")
    if v.get("hue") is not None:
        out["hue"] = _num(v["hue"], 0, 1)
    return out


def _badge_ok(b, post, crate, dogs):
    """게시물 숫자로 볼 수 있는 기본 도전만 대조한다(plant 는 주간 숫자뿐이라 못 본다, 도전·숨은 것은 못 본다)"""
    prefix, _, n = b.rpartition("-")
    o, land = post["orchard"], post["land"]
    have = {"crate": crate, "dex": o["dex"], "secrets": o["secrets"], "scrump": o["scrump"], "rainbow": int(o["rainbow"]),
            "worker": max([w["level"] for w in o["workers"].values()] or [0]),
            "second": int(any(len(w["looks"]) >= 2 for w in o["workers"].values())),
            "land": land["plots"], "earned": land["earned"], "dogs": dogs}.get(prefix)
    return have is None or not n.isdigit() or have >= int(n)


def clean_post(body, baskets=0, dispatches=0, farm=(0, 0)):
    """앱이 보낸 내용을 검사해 저장할 형태로. 범위를 벗어나면 BadRequest. farm: 서버가 아는 (창고 레벨, 개 수)"""
    if not isinstance(body, dict):
        raise BadRequest()
    card, orch = body.get("card"), body.get("orchard")
    if not isinstance(card, dict) or not isinstance(orch, dict):
        raise BadRequest()
    trees = orch.get("trees")
    workers = orch.get("workers")
    if not isinstance(trees, list) or len(trees) > MAX_BRAG_TREES or any(t not in KINDS for t in trees):
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
    post = {
        "nickname": clean_nickname(body.get("nickname")),
        "card": {"harvested": _int(card.get("harvested"), 0, 10**8), "sold": _int(card.get("sold"), 0, 10**8),
                 "earned": _int(card.get("earned"), 0, 10**13), "planted": _int(card.get("planted"), 0, 10**5)},
        "orchard": {"trees": trees, "workers": crew, "dex": _int(orch.get("dex"), 0, 20),
                    "secrets": _int(orch.get("secrets"), 0, 20), "rainbow": orch["rainbow"], "theme": orch["theme"],
                    "scrump": _int(orch.get("scrump", 0), 0, 20)},  # 1.8 서리 수첩
        # 1.12 끝없는 땅: 밭 칸 수와 지금까지 번 코인(Orchard.totals.earned). 조작 방지 검사에만 쓰고 저장하지 않는다(옛 앱은 안 보낸다 → 10칸)
        "land": {"plots": _int(orch.get("plots", LAND_START), LAND_START, MAX_PLOTS),
                 "earned": _int(orch.get("totalEarned", 0), 0, MAX_EARNED)},
    }
    if not plausible(post, baskets, dispatches):
        raise BadRequest("implausible")
    # 1.17 진열장: 칭호·배지·진열장 소품, 장면, 이주의 주제에 쓰는 도담 판매·만든 병(모두 옛 앱은 안 보낸다)
    o = post["orchard"]
    if orch.get("scene") is not None:
        o["scene"] = clean_scene(orch["scene"])
    for k in ("managerSold", "bottles"):
        if orch.get(k) is not None:
            o[k] = _int(orch[k], 0, 10**9)
    if body.get("title") is not None:
        post["title"] = clean_nickname(body["title"], 24, "bad_title")
    badges = body.get("badges")
    if badges is not None:
        crate = max(farm[0], _int(orch.get("crate", 0), 0, 99))
        dogs = max(farm[1], o.get("scene", {}).get("dogs", 0))
        if (not isinstance(badges, list) or len(badges) > BADGES_MAX or len(set(map(str, badges))) < len(badges)
                or any(not isinstance(b, str) or b not in ACHIEVEMENTS or not _badge_ok(b, post, crate, dogs) for b in badges)):
            raise BadRequest("bad_badge")
        post["badges"] = badges
    if body.get("showcase") is not None:
        post["showcase"] = clean_showcase(body["showcase"])
    return post


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
            CREATE TABLE IF NOT EXISTS farms(owner TEXT PRIMARY KEY, cap INTEGER NOT NULL, crate TEXT NOT NULL,
                fences INTEGER NOT NULL, dogs INTEGER NOT NULL DEFAULT 0, best TEXT NOT NULL DEFAULT 'eureka',
                level INTEGER NOT NULL, first REAL NOT NULL, seen REAL NOT NULL,
                guard REAL NOT NULL DEFAULT 0, lost_day TEXT NOT NULL DEFAULT '', lost INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS raids(id TEXT PRIMARY KEY, raider TEXT NOT NULL, victim TEXT NOT NULL, day TEXT NOT NULL,
                role TEXT NOT NULL, plan TEXT NOT NULL, start REAL NOT NULL, end REAL NOT NULL, loot TEXT NOT NULL,
                caught INTEGER NOT NULL DEFAULT 0, revenge INTEGER NOT NULL DEFAULT 0, avenged INTEGER NOT NULL DEFAULT 0,
                raider_done INTEGER NOT NULL DEFAULT 0, victim_done INTEGER NOT NULL DEFAULT 0);
            CREATE INDEX IF NOT EXISTS raids_raider ON raids(raider, end);
            CREATE INDEX IF NOT EXISTS raids_victim ON raids(victim, end);
            CREATE TABLE IF NOT EXISTS codes(owner TEXT PRIMARY KEY, code TEXT NOT NULL UNIQUE, created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS neighbors(owner TEXT NOT NULL, other TEXT NOT NULL, created REAL NOT NULL,
                PRIMARY KEY(owner, other));
            CREATE TABLE IF NOT EXISTS gifts(id TEXT PRIMARY KEY, sender TEXT NOT NULL, receiver TEXT NOT NULL, day TEXT NOT NULL,
                kind TEXT NOT NULL, fruit TEXT, stamp TEXT NOT NULL, worker TEXT NOT NULL, created REAL NOT NULL,
                done INTEGER NOT NULL DEFAULT 0);
            CREATE INDEX IF NOT EXISTS gifts_receiver ON gifts(receiver, done);
            CREATE INDEX IF NOT EXISTS gifts_sender ON gifts(sender, day);
            -- 1.13 쩔: dispatch(출장, start~end 4시간)·basket(fruit, count, stamp)·sapling(fruit 에 나무 종류)·
            -- step(사제 단계 알림, fruit 에 단계 이름). done: 받은 쪽이 반영(선배 고마움), seen: 선배가 단계 알림을 봄
            CREATE TABLE IF NOT EXISTS carries(id TEXT PRIMARY KEY, sender TEXT NOT NULL, receiver TEXT NOT NULL, day TEXT NOT NULL,
                week TEXT NOT NULL, kind TEXT NOT NULL, role TEXT, level INTEGER, fruit TEXT, count INTEGER, stamp TEXT, worker TEXT,
                start REAL NOT NULL, end REAL NOT NULL, done INTEGER NOT NULL DEFAULT 0, seen INTEGER NOT NULL DEFAULT 0);
            CREATE INDEX IF NOT EXISTS carries_receiver ON carries(receiver, kind, day);
            CREATE INDEX IF NOT EXISTS carries_sender ON carries(sender, kind, end);
            -- 1.14 이웃 요청(status: pending·declined, 수락하면 지운다. ended: 거절한 때)과 차단
            CREATE TABLE IF NOT EXISTS requests(sender TEXT NOT NULL, receiver TEXT NOT NULL, created REAL NOT NULL, stamp TEXT,
                status TEXT NOT NULL, ended REAL NOT NULL DEFAULT 0, PRIMARY KEY(sender, receiver));
            CREATE INDEX IF NOT EXISTS requests_receiver ON requests(receiver, status);
            CREATE TABLE IF NOT EXISTS blocks(owner TEXT NOT NULL, other TEXT NOT NULL, created REAL NOT NULL, PRIMARY KEY(owner, other));
            -- 1.14 폰 중계: Mac 이 잠든 동안의 예약 명령, 폰 대리 연결(소유 키 해시), 대리로 한 일의 내 쪽 변화
            CREATE TABLE IF NOT EXISTS relay_queue(device TEXT NOT NULL, id TEXT NOT NULL, action TEXT NOT NULL, body TEXT NOT NULL,
                at REAL NOT NULL, PRIMARY KEY(device, id));
            CREATE TABLE IF NOT EXISTS relay_link(device TEXT PRIMARY KEY, owner TEXT NOT NULL, created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS relay_effects(device TEXT NOT NULL, id TEXT NOT NULL, kind TEXT NOT NULL, body TEXT NOT NULL,
                at REAL NOT NULL, PRIMARY KEY(device, id));
            -- 1.15.1 기기 연동: 과수원 사본(bundle JSON)·홀더 기기 해시, 기기 목록, 다른 기기 추가 코드.
            -- 코드 행의 key 만 소유 키 원문이다(redeem 이 새 기기에 돌려줘야 한다). 쓰면 바로, 안 쓰면 10분 뒤 지운다.
            CREATE TABLE IF NOT EXISTS sync(owner TEXT PRIMARY KEY, bundle TEXT NOT NULL, rev INTEGER NOT NULL, holder TEXT NOT NULL,
                schema INTEGER NOT NULL, at REAL NOT NULL, updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS sync_devices(owner TEXT NOT NULL, device TEXT NOT NULL, platform TEXT NOT NULL, label TEXT NOT NULL,
                added REAL NOT NULL, seen REAL NOT NULL, revoked INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(owner, device));
            CREATE TABLE IF NOT EXISTS sync_codes(code TEXT PRIMARY KEY, owner TEXT NOT NULL, key TEXT NOT NULL, expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS bug_tickets(ticket TEXT PRIMARY KEY, owner TEXT NOT NULL, app TEXT NOT NULL, os TEXT NOT NULL,
                platform TEXT NOT NULL, expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS bugs(id TEXT PRIMARY KEY, owner TEXT NOT NULL, created REAL NOT NULL, app TEXT NOT NULL,
                os TEXT NOT NULL, platform TEXT NOT NULL, text TEXT NOT NULL, images INTEGER NOT NULL, done INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS bug_images(bug TEXT NOT NULL, n INTEGER NOT NULL, mime TEXT NOT NULL, data BLOB NOT NULL,
                PRIMARY KEY(bug, n));
            -- 1.17 게시판: 스탬프(별처럼 브라우저 ID·IP 해시, own: 주인이 자기 표로 준 것), 구경꾼 날(소유 키 해시·날짜),
            -- 게시판 표(1시간), 8주 뒤 지운 게시물의 보상 집계(지금까지 받은 별·스탬프가 줄지 않게)
            CREATE TABLE IF NOT EXISTS stamps(post TEXT NOT NULL, voter TEXT NOT NULL, ip TEXT NOT NULL, kind TEXT NOT NULL,
                created REAL NOT NULL, own INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(post, voter));
            CREATE TABLE IF NOT EXISTS visits(owner TEXT NOT NULL, day TEXT NOT NULL, PRIMARY KEY(owner, day));
            CREATE TABLE IF NOT EXISTS brag_tickets(ticket TEXT PRIMARY KEY, owner TEXT NOT NULL, expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS brag_kept(owner TEXT PRIMARY KEY, posts INTEGER NOT NULL, stars INTEGER NOT NULL,
                lemon INTEGER NOT NULL, flower INTEGER NOT NULL, laugh INTEGER NOT NULL, clap INTEGER NOT NULL);
            CREATE INDEX IF NOT EXISTS highlights_owner ON highlights(owner);
        """)
        # 옛 데이터에 열을 더한다. 윈도우판: 통계에 플랫폼 열(옛 행은 mac). 맥 os("26")와 윈도우 os("10"/"11")는 겹치지 않아 기본 키는 그대로 둔다.
        # 1.11 이웃: 통계 nb·rb, 과수원 모습·고마움, 되찾아 주기(beneficiary)·이웃이 쫓아냄(caught_by). 1.12: 내 과수원 이름
        # 1.13 쩔: 사제 단계 비트(선배 쪽 행 owner=선배, other=후배), 선배의 1시간 돕기, 받아 둔 묘목
        for table, col, decl in (("install_counts", "platform", "TEXT NOT NULL DEFAULT 'mac'"), ("pings", "platform", "TEXT NOT NULL DEFAULT 'mac'"),
                                 ("pings", "nb", "INTEGER NOT NULL DEFAULT 0"), ("pings", "rb", "INTEGER NOT NULL DEFAULT 0"),
                                 ("farms", "look", "TEXT NOT NULL DEFAULT '{}'"), ("farms", "thanks", "INTEGER NOT NULL DEFAULT 0"),
                                 ("farms", "name", "TEXT NOT NULL DEFAULT ''"),
                                 ("raids", "beneficiary", "TEXT NOT NULL DEFAULT ''"), ("raids", "beneficiary_done", "INTEGER NOT NULL DEFAULT 0"),
                                 ("raids", "caught_by", "INTEGER NOT NULL DEFAULT 0"),
                                 ("neighbors", "steps", "INTEGER NOT NULL DEFAULT 0"), ("gifts", "long", "INTEGER NOT NULL DEFAULT 0"),
                                 ("farms", "seedling", "INTEGER NOT NULL DEFAULT 0"),
                                 # 1.14 이웃 찾기에 보이기·요청 받기(기본 켬)
                                 ("farms", "listed", "INTEGER NOT NULL DEFAULT 1"), ("farms", "asks", "INTEGER NOT NULL DEFAULT 1"),
                                 # 1.15 통계: 매니저 레벨·폰으로 보기·매니저 판매 수
                                 ("pings", "mg", "INTEGER NOT NULL DEFAULT 0"), ("pings", "pv", "INTEGER NOT NULL DEFAULT 0"),
                                 ("pings", "ms", "INTEGER NOT NULL DEFAULT 0"),
                                 # 1.15.1 통계: 기기 연동(off·on·holder, 옛 앱은 '')
                                 ("pings", "sync", "TEXT NOT NULL DEFAULT ''"),
                                 ("pings", "mm", "TEXT NOT NULL DEFAULT ''"),  # 1.16 도담 모드
                                 ("stars", "own", "INTEGER NOT NULL DEFAULT 0")):  # 1.17 주인이 자기 표로 준 별
            if col not in [r[1] for r in self.db.execute("PRAGMA table_info(%s)" % table)]:
                self.db.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, col, decl))
        self.db.execute("CREATE INDEX IF NOT EXISTS raids_beneficiary ON raids(beneficiary, end)")
        self.db.commit()

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
        if isinstance(key, Owner):
            return str(key)
        if not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]{64}", key):
            raise BadRequest("unauthorized")
        return sha(key)

    def _row(self, r, voter=None):
        pid, week, nick, data, created, stars = r
        d = json.loads(data)
        out = {"id": pid, "week": week, "nickname": nick, "card": d["card"], "orchard": d["orchard"],
               "stars": stars, "created": int(created), "stamps": self._stamps(pid)}
        out.update({k: d[k] for k in ("title", "badges", "showcase") if k in d})  # 1.17 진열장
        if voter is not None:
            out["starred"] = self.db.execute("SELECT 1 FROM stars WHERE post=? AND voter=?", (pid, sha(voter))).fetchone() is not None
            m = self.db.execute("SELECT kind FROM stamps WHERE post=? AND voter=?", (pid, sha(voter))).fetchone()
            out["mine"] = m[0] if m else None
        return out

    def _stamps(self, pid):
        n = dict(self.db.execute("SELECT kind, COUNT(*) FROM stamps WHERE post=? GROUP BY kind", (pid,)).fetchall())
        return {k: n.get(k, 0) for k in BOARD_STAMPS}

    def _post_owner(self, pid):
        r = self.db.execute("SELECT owner FROM posts WHERE id=? AND hidden=0", (pid,)).fetchone()
        if not r:
            raise KeyError(pid)
        return r[0]

    def _brag_ticket(self, ticket, now):
        """게시판 표의 소유자. 없거나 지났으면 None(표 없이 연 게시판처럼 반응만 센다)"""
        if not isinstance(ticket, str) or not re.fullmatch(r"[0-9a-f]{32}", ticket):
            return None
        r = self.db.execute("SELECT owner FROM brag_tickets WHERE ticket=? AND expires>?", (sha(ticket), now.timestamp())).fetchone()
        return r[0] if r else None

    SELECT = ("SELECT p.id, p.week, p.nickname, p.data, p.created, "
              "(SELECT COUNT(*) FROM stars s WHERE s.post=p.id) AS n FROM posts p")

    # 동작

    @locked
    def create_or_update(self, owner_key, body, ip, now):
        owner = self.owner(owner_key)
        # 1.13: 이번 주 받은 바구니 과일 수·출장 수만큼 조작 방지 상한을 넓힌다
        baskets, dispatches = self.db.execute(
            "SELECT COALESCE(SUM(CASE WHEN kind='basket' THEN count END), 0), COALESCE(SUM(kind='dispatch'), 0) FROM carries "
            "WHERE receiver=? AND kind IN ('basket', 'dispatch') AND end>=?", (owner, week_start(now))).fetchone()
        f = self._farm(owner)
        post = clean_post(body, baskets, dispatches, (f["level"], f["dogs"]) if f else (0, 0))
        with self.lock:
            self.limit("post", self.ip(ip), now)
            week = self.week(now)
            data = json.dumps({k: post[k] for k in ("card", "orchard", "title", "badges", "showcase") if k in post}, ensure_ascii=False)
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
    def toggle_star(self, pid, voter, ip, now, ticket=None):
        """ticket(1.17): 앱이 연 게시판이면 게시판 표. 주인이 자기 게시물에 준 별은 보상에서 뺀다."""
        if not isinstance(voter, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", voter):
            raise BadRequest()
        with self.lock:
            owner = self._post_owner(pid)
            self.limit("star", self.ip(ip), now)
            v = sha(voter)
            if self.db.execute("DELETE FROM stars WHERE post=? AND voter=?", (pid, v)).rowcount:
                starred = False
            else:
                self.db.execute("INSERT INTO stars(post, voter, ip, created, own) VALUES(?,?,?,?,?)",
                                (pid, v, self.ip(ip), now.timestamp(), int(self._brag_ticket(ticket, now) == owner)))
                starred = True
            self.db.commit()
            n = self.db.execute("SELECT COUNT(*) FROM stars WHERE post=?", (pid,)).fetchone()[0]
        return {"stars": n, "starred": starred}

    @locked
    def stamp(self, pid, body, ip, now):
        """1.17 스탬프 {voter, kind, ticket?} → {stamps, mine}. 브라우저마다 게시물에 하나: 같은 것 다시 = 취소, 다른 것 = 바꿈.
        살아 있는 표로 남의 게시물에 남기면 표 주인의 오늘이 구경꾼 날이 된다."""
        b = body if isinstance(body, dict) else {}
        voter, kind = b.get("voter"), b.get("kind")
        if not isinstance(voter, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", voter) or kind not in BOARD_STAMPS:
            raise BadRequest()
        owner = self._post_owner(pid)
        self.limit("stamp", self.ip(ip), now)
        v, who = sha(voter), self._brag_ticket(b.get("ticket"), now)
        old = self.db.execute("SELECT kind FROM stamps WHERE post=? AND voter=?", (pid, v)).fetchone()
        mine = None if old and old[0] == kind else kind
        if mine is None:
            self.db.execute("DELETE FROM stamps WHERE post=? AND voter=?", (pid, v))
        elif old:
            self.db.execute("UPDATE stamps SET kind=?, own=MAX(own, ?) WHERE post=? AND voter=?", (kind, int(who == owner), pid, v))
        else:
            self.db.execute("INSERT INTO stamps VALUES(?,?,?,?,?,?)", (pid, v, self.ip(ip), kind, now.timestamp(), int(who == owner)))
        if mine and who and who != owner:
            self.db.execute("INSERT OR IGNORE INTO visits VALUES(?,?)", (who, day_key(now)))
        self.db.commit()
        return {"stamps": self._stamps(pid), "mine": mine}

    @locked
    def brag_ticket(self, owner_key, now):
        """1.17 앱이 '자랑 게시판…'을 열 때 받는 표(1시간, 그 동안 여러 번). 구경꾼 날과 내 반응 빼기에만 쓴다."""
        me = self.owner(owner_key)
        self.limit("brag_ticket", me, now)
        t = self._active(me, now)
        ticket = secrets.token_hex(16)
        self.db.execute("DELETE FROM brag_tickets WHERE expires<=?", (t,))
        self.db.execute("INSERT INTO brag_tickets VALUES(?,?,?)", (sha(ticket), me, t + BRAG_TICKET_TTL))
        self.db.commit()
        return {"ticket": ticket, "expires": int(t + BRAG_TICKET_TTL)}

    @locked
    def badge_count(self, bid):
        """그 배지를 건 게시물의 과수원 수(숨김 제외, 남아 있는 게시물에서)"""
        if bid not in ACHIEVEMENTS:
            raise KeyError(bid)
        rows = self.db.execute("SELECT owner, data FROM posts WHERE hidden=0 AND data LIKE ?", ('%"' + bid + '"%',)).fetchall()
        return {"count": len({o for o, d in rows if bid in json.loads(d).get("badges", ())})}

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
    def _drop_posts(self, owner):
        """내 게시물과 거기 받은 별·신고, 하이라이트 기록(잠금 안에서 부른다)."""
        ids = [r[0] for r in self.db.execute("SELECT id FROM posts WHERE owner=?", (owner,))]
        for pid in ids:
            self.db.execute("DELETE FROM stars WHERE post=?", (pid,))
            self.db.execute("DELETE FROM stamps WHERE post=?", (pid,))
            self.db.execute("DELETE FROM reports WHERE post=?", (pid,))
        self.db.execute("DELETE FROM posts WHERE owner=?", (owner,))
        self.db.execute("DELETE FROM highlights WHERE owner=?", (owner,))
        return len(ids)

    def delete_posts(self, owner_key):
        """'내 자랑 지우기'(1.11.1): 게시물·별·하이라이트만. 서리·이웃 기록과 초대 코드는 그대로 둔다.
        1.11 까지는 앱이 delete_mine 만 불러서, 게시물을 고치려고 지운 사람이 이웃까지 잃었다."""
        owner = self.owner(owner_key)
        with self.lock:
            n = self._drop_posts(owner)
            self.db.commit()
        return n

    def delete_mine(self, owner_key):
        """'서버의 내 기록 모두 지우기': 게시물에 더해 서리·이웃 참여 정보와 기록까지(개인정보 처리방침의 약속)."""
        owner = self.owner(owner_key)
        with self.lock:
            n = self._drop_posts(owner)
            self.db.execute("DELETE FROM farms WHERE owner=?", (owner,))  # 1.8 서리 참여·기록도 함께
            self.db.execute("DELETE FROM raids WHERE raider=? OR victim=? OR beneficiary=?", (owner, owner, owner))
            # 1.11 이웃: 코드, 이웃 관계(양쪽), 보내고 받은 돕기·선물
            self.db.execute("DELETE FROM codes WHERE owner=?", (owner,))
            self.db.execute("DELETE FROM neighbors WHERE owner=? OR other=?", (owner, owner))
            self.db.execute("DELETE FROM gifts WHERE sender=? OR receiver=?", (owner, owner))
            self.db.execute("DELETE FROM carries WHERE sender=? OR receiver=?", (owner, owner))  # 1.13 쩔 기록
            # 1.14 이웃 요청·차단, 폰 대리 연결
            self.db.execute("DELETE FROM requests WHERE sender=? OR receiver=?", (owner, owner))
            self.db.execute("DELETE FROM blocks WHERE owner=? OR other=?", (owner, owner))
            self.db.execute("DELETE FROM relay_link WHERE owner=?", (owner,))
            self._drop_sync(owner)  # 1.15.1 기기 연동
            self._drop_bugs(owner)  # 1.15.2 버그 신고
            for table in ("visits", "brag_tickets", "brag_kept"):  # 1.17 구경꾼 날·게시판 표·지운 게시물의 보상 집계
                self.db.execute("DELETE FROM %s WHERE owner=?" % table, (owner,))
            self.db.commit()
        return n

    # 통계

    @locked
    def install(self, body, ip, now):
        p = clean_install(body)
        self.limit("install", self.ip(ip), now)
        self.db.execute("INSERT INTO install_counts(day, version, kind, arch, os, n, platform) VALUES(?,?,?,?,?,1,?) "
                        "ON CONFLICT(day, version, kind, arch, os) DO UPDATE SET n = n + 1",
                        (day_key(now), p["version"], p["kind"], p["arch"], p["os"], p["platform"]))
        self.db.commit()

    @locked
    def ping(self, body, ip, now):
        p = clean_ping(body, now)
        self.limit("ping", self.ip(ip), now)
        inst = sha(p["install"])
        self.db.execute("INSERT INTO participants VALUES(?,?) "
                        "ON CONFLICT(install) DO UPDATE SET first_day = min(first_day, excluded.first_day)", (inst, p["day"]))
        self.db.execute("INSERT INTO pings(install, day, version, os, lang, arch, minutes, opens, sales, kinds, received, platform, nb, rb, mg, pv, ms, sync, mm) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(install, day) DO UPDATE SET mm=excluded.mm, "
                        "sync=CASE WHEN excluded.sync<>'' THEN excluded.sync ELSE sync END, "
                        "version=excluded.version, os=excluded.os, lang=excluded.lang, arch=excluded.arch, platform=excluded.platform, "
                        "minutes=max(minutes, excluded.minutes), opens=max(opens, excluded.opens), "
                        "sales=max(sales, excluded.sales), kinds=excluded.kinds, received=excluded.received, "
                        "nb=max(nb, excluded.nb), rb=max(rb, excluded.rb), mg=max(mg, excluded.mg), pv=max(pv, excluded.pv), ms=max(ms, excluded.ms)",
                        (inst, p["day"], p["version"], p["os"], p["lang"], p["arch"], p["minutes"], p["opens"],
                         p["sales"], p["kinds"], now.timestamp(), p["platform"], p["nb"], p["rb"], p["mg"], p["pv"], p["ms"], p["sync"], p["mm"]))
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
                    "versions": by_installs("version"), "arch": by_installs("arch"), "os": by_installs("os"),
                    "platform": by_installs("platform")}
        active = {k: one("SELECT COUNT(DISTINCT install) FROM pings WHERE day >= ? AND day <= ?", ago(n - 1), today)
                  for k, n in (("dau", 1), ("wau", 7), ("mau", 30))}
        cohort = [r[0] for r in self.db.execute("SELECT install FROM participants WHERE first_day BETWEEN ? AND ?", (ago(14), ago(8)))]
        retained = sum(1 for i in cohort if self.db.execute("SELECT 1 FROM pings WHERE install = ? AND day >= ?", (i, ago(6))).fetchone())

        def next_day(rb):
            """rb 가 같은 날(30일~2일 전) 중 다음 날도 쓴 날 수. 어제는 오늘 신호가 아직 다 오지 않아 뺀다."""
            days, back = self.db.execute(
                "SELECT COUNT(*), COALESCE(SUM(EXISTS(SELECT 1 FROM pings q WHERE q.install = p.install AND q.day = date(p.day, '+1 day'))), 0) "
                "FROM pings p WHERE p.rb = ? AND p.day BETWEEN ? AND ?", (rb, ago(30), ago(2))).fetchone()
            return {"days": days, "back": back}

        nb_active, nb_with = self.db.execute("SELECT COUNT(*), COALESCE(SUM(m >= 1), 0) FROM "
                                             "(SELECT MAX(nb) AS m FROM pings WHERE day >= ? GROUP BY install)", (ago(6),)).fetchone()
        usage = {"participants": one("SELECT COUNT(*) FROM participants"),
                 "new_today": one("SELECT COUNT(*) FROM participants WHERE first_day = ?", today),
                 "active": active, "retention7": {"cohort": len(cohort), "retained": retained},
                 "versions": by_usage("version"), "os": by_usage("os"), "arch": by_usage("arch"), "lang": by_usage("lang"),
                 "platform": by_usage("platform"),
                 # 1.11: 7일 안에 쓴 설치 중 이웃이 있는 설치, 서리당한(rb=1) 설치와 아닌 설치의 다음 날 활동
                 "neighbors": {"active": nb_active, "with": nb_with},
                 "raided_next_day": {"raided": next_day(1), "others": next_day(0)}}
        # 1.15: (설치, 날)별 판매 수 분포(봇처럼 튀는 설치), 설치마다 마지막 날의 연 나무 종류 수(원본이 남은 90일 안), 매니저·폰으로 보기(7일)
        sales = sorted(r[0] or 0 for r in self.db.execute("SELECT sales FROM pings WHERE day >= ?", (ago(6),)))
        usage["sales_per_install"] = {"median": statistics.median(sales) if sales else 0,
                                      "p90": sales[-(-len(sales) * 9 // 10) - 1] if sales else 0, "max": sales[-1] if sales else 0}
        usage["kinds"] = {str(k): c for k, c in self.db.execute(
            "SELECT p.kinds, COUNT(*) FROM pings p JOIN (SELECT install, MAX(day) AS d FROM pings GROUP BY install) m "
            "ON p.install = m.install AND p.day = m.d GROUP BY p.kinds ORDER BY p.kinds")}
        mg_with, mg_avg, ms_sum, pv_with = self.db.execute(
            "SELECT COALESCE(SUM(mg >= 1), 0), AVG(CASE WHEN mg >= 1 THEN mg END), COALESCE(SUM(ms), 0), COALESCE(SUM(pv), 0) "
            "FROM (SELECT MAX(mg) AS mg, SUM(ms) AS ms, MAX(pv) AS pv FROM pings WHERE day >= ? GROUP BY install)", (ago(6),)).fetchone()
        modes = dict(self.db.execute(  # 1.16: 7일 안에 쓴 설치마다 가장 최근 날의 도담 모드
            "SELECT p.mm, COUNT(*) FROM pings p JOIN (SELECT install, MAX(day) AS d FROM pings WHERE day >= ? GROUP BY install) m "
            "ON p.install = m.install AND p.day = m.d WHERE p.mm <> '' GROUP BY p.mm ORDER BY 2 DESC", (ago(6),)).fetchall())
        usage["manager"] = {"with": mg_with, "avg_level": round(mg_avg or 0, 1), "sold": ms_sum, "modes": modes}
        usage["phone"] = {"with": pv_with}
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
        for d, sy, c in self.db.execute("SELECT day, sync, COUNT(*) FROM pings WHERE day >= ? AND sync <> '' GROUP BY day, sync", (start,)):
            rows[d].setdefault("sync", {"off": 0, "on": 0, "holder": 0})[sy] = c  # 1.15.1 기기 연동(날짜별 설치 수)
        week = self.week(now)
        board = {"posts_this_week": one("SELECT COUNT(*) FROM posts WHERE week = ? AND hidden = 0", week),
                 "stars_this_week": one("SELECT COUNT(*) FROM stars s JOIN posts p ON p.id = s.post WHERE p.week = ?", week)}
        return {"today": today, "installs": installs, "usage": usage, "daily": [rows[d] for d in sorted(rows)], "board": board,
                "raid": self._raid_health(now)}

    def _raid_health(self, now):
        """서리 진단(1.15, 이미 있는 farms·raids 에서 계산). targetable: _candidates 조건 중 서리꾼과 무관한 것(14일 소식·초보·
        창고 레벨·창고 20%·오늘 손실 상한)을 모두 넘는 곳. filtered: 14일 안에 소식 있는 곳 중 각 조건에 걸리는 수(겹칠 수 있다)."""
        t, day, week = now.timestamp(), day_key(now), now.timestamp() - 7 * 86400
        filtered = {"newbie": 0, "level": 0, "fill": 0, "lost": 0, "stale": 0}
        farms_7d = targetable = 0
        for cap, crate, level, first, seen, lost_day, lost in self.db.execute(
                "SELECT cap, crate, level, first, seen, lost_day, lost FROM farms"):
            farms_7d += seen > week
            if seen <= t - STALE:
                filtered["stale"] += 1
                continue
            why = {"newbie": first > t - NEWBIE, "level": level < MIN_LEVEL, "fill": sum(json.loads(crate).values()) < cap * MIN_FILL,
                   "lost": not BETA_OPEN and lost_day == day and lost >= int(cap * DAILY_LOSS)}
            for k, hit in why.items():
                filtered[k] += hit
            targetable += not any(why.values())
        raids, raiders, victims = self.db.execute(
            "SELECT COUNT(*), COUNT(DISTINCT raider), COUNT(DISTINCT victim) FROM raids WHERE start > ?", (week,)).fetchone()
        return {"farms_7d": farms_7d, "targetable": targetable, "filtered": filtered,
                "raids_7d": raids, "raiders_7d": raiders, "victims_7d": victims}

    # 하이라이트

    def _compute(self, week):
        rows = self.db.execute(self.SELECT + " WHERE p.week=? AND p.hidden=0", (week,)).fetchall()
        posts = [self._row(r) for r in rows]
        top = sorted([p for p in posts if p["stars"] > 0], key=lambda p: (-p["stars"], p["created"]))[:TOP_N]

        def best(value, starred=True):  # 1.7.1: 별을 하나라도 받은 게시물에서만(사람 눈을 한 번 거친다)
            c = [p for p in posts if value(p) > 0 and (p["stars"] > 0 or not starred)]
            return min(c, key=lambda p: (-value(p), -p["stars"], p["created"])) if c else None

        # 1.17 이주의 주제(게시물 데이터로만). rare: 그 주 별 받은 게시물 중 가장 적게 걸린 배지
        seen = defaultdict(int)
        for p in posts:
            if p["stars"] > 0:
                for b in p.get("badges", ()):
                    seen[b] += 1
        scene = lambda p: p["orchard"].get("scene", {})  # noqa: E731
        theme = {"pink": lambda p: p["orchard"]["trees"].count("pink"),
                 "even": lambda p: len(set(p["orchard"]["trees"])),
                 "manager": lambda p: p["orchard"].get("managerSold", 0),
                 "dogs": lambda p: scene(p).get("dogs", 0),
                 "decor": lambda p: len(scene(p).get("decor", ())),
                 "stand": lambda p: p["orchard"].get("bottles", 0),
                 "rare": lambda p: max([1 / seen[b] for b in p.get("badges", ()) if seen[b]] or [0])}.get(week_theme(week), lambda p: 0)
        cats = {"harvest": best(lambda p: p["card"]["harvested"]),
                "secrets": best(lambda p: p["orchard"]["secrets"]),
                "dex": best(lambda p: p["orchard"]["dex"]),
                "theme": best(theme)}
        for k in BOARD_STAMPS:  # 스탬프 부문: 그 스탬프를 가장 많이 받은 게시물(스탬프가 곧 사람 눈이라 별은 안 따진다)
            cats["stamp-" + k] = best(lambda p, k=k: p["stamps"][k], starred=False)
        return top, cats

    @locked
    def highlights(self, week, now):
        rows = self.db.execute("SELECT kind, rank, snapshot FROM highlights WHERE week=? ORDER BY kind, rank", (week,)).fetchall()
        closed = self.db.execute("SELECT 1 FROM closed WHERE week=?", (week,)).fetchone() is not None
        if closed:
            top = [json.loads(s) for k, _, s in rows if k == "top"]
            cats = {k: None for k in CATEGORIES}
            cats.update({k: json.loads(s) for k, _, s in rows if k != "top"})
            return {"week": week, "top": top, "categories": cats, "themeId": week_theme(week), "final": True}
        top, cats = self._compute(week)
        return {"week": week, "top": top, "categories": cats, "themeId": week_theme(week), "final": False}

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
            old = self.db.execute("SELECT id, owner, created, hidden FROM posts WHERE week < ? AND id NOT IN (SELECT post FROM highlights)",
                                  (cutoff,)).fetchall()
            for pid, owner, created, hidden in old:
                if not hidden:  # 1.17: 지운 게시물의 보상 집계는 소유자 합계로 남긴다
                    n = self._fair(pid, created)
                    self.db.execute("INSERT OR IGNORE INTO brag_kept VALUES(?,0,0,0,0,0,0)", (owner,))
                    self.db.execute("UPDATE brag_kept SET posts=posts+1, stars=stars+?, lemon=lemon+?, flower=flower+?, laugh=laugh+?, "
                                    "clap=clap+? WHERE owner=?", (n["stars"],) + tuple(n[k] for k in BOARD_STAMPS) + (owner,))
            for pid in [r[0] for r in old]:
                self.db.execute("DELETE FROM stars WHERE post=?", (pid,))
                self.db.execute("DELETE FROM stamps WHERE post=?", (pid,))
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
            # 1.15.2 버그 신고: 지난 표, 180일 지난 신고와 이미지
            self.db.execute("DELETE FROM bug_tickets WHERE expires<=?", (t,))
            self.db.execute("DELETE FROM brag_tickets WHERE expires<=?", (t,))
            self.db.execute("DELETE FROM bug_images WHERE bug IN (SELECT id FROM bugs WHERE created<?)", (t - BUG_KEEP_DAYS * 86400,))
            self.db.execute("DELETE FROM bugs WHERE created<?", (t - BUG_KEEP_DAYS * 86400,))
            # 서리: 8주 소식 없는 설치와 8주 지난 기록
            self.db.execute("DELETE FROM farms WHERE seen < ?", (t - KEEP_WEEKS * WEEK,))
            self.db.execute("DELETE FROM raids WHERE end < ?", (t - KEEP_WEEKS * WEEK,))
            # 이웃: 8주 지난 돕기·선물 기록, 과수원이 지워진 설치의 코드와 이웃 관계(빈자리가 상한을 차지하지 않게)
            self.db.execute("DELETE FROM gifts WHERE created < ?", (t - KEEP_WEEKS * WEEK,))
            self.db.execute("DELETE FROM carries WHERE end < ?", (t - KEEP_WEEKS * WEEK,))  # 1.13 쩔 기록
            self.db.execute("DELETE FROM codes WHERE owner NOT IN (SELECT owner FROM farms)")
            self.db.execute("DELETE FROM neighbors WHERE owner NOT IN (SELECT owner FROM farms) OR other NOT IN (SELECT owner FROM farms)")
            # 1.14: 요청은 7일 뒤 사라지고 다시 7일 뒤(다시 요청 막기가 끝나면) 지운다. 과수원이 지워진 설치의 요청·차단
            self.db.execute("DELETE FROM requests WHERE created < ? OR sender NOT IN (SELECT owner FROM farms) "
                            "OR receiver NOT IN (SELECT owner FROM farms)", (t - 2 * REQUEST_DAYS,))
            self.db.execute("DELETE FROM blocks WHERE owner NOT IN (SELECT owner FROM farms) OR other NOT IN (SELECT owner FROM farms)")
            self.db.execute("DELETE FROM sync_codes WHERE expires <= ?", (t,))  # 1.15.1: 소유 키 원문이 든 코드는 10분만
            self.db.commit()

    # 서리 (1.8). 한 사람(raider)은 당한 쪽 응답 어디에도 넣지 않는다.

    FARM = "SELECT owner, cap, crate, fences, level, first, seen, guard, lost_day, lost, dogs, best, thanks, name, seedling, listed, asks FROM farms"

    @staticmethod
    def _farm_row(r):
        return {"owner": r[0], "cap": r[1], "crate": json.loads(r[2]), "fences": r[3], "level": r[4], "first": r[5],
                "seen": r[6], "guard": r[7], "lost_day": r[8], "lost": r[9], "dogs": r[10], "best": r[11], "thanks": r[12], "name": r[13], "seedling": r[14],
                "listed": bool(r[15]), "asks": bool(r[16])}

    def _farm(self, owner):
        r = self.db.execute(self.FARM + " WHERE owner=?", (owner,)).fetchone()
        return self._farm_row(r) if r else None

    def _target_id(self, me, owner):
        """대상 id 는 요청한 사람에게만 통한다(키 해시를 내려 주지 않는다)"""
        return hmac.new(self.salt, (me + "|" + owner).encode(), hashlib.sha256).hexdigest()[:16]

    def _nick(self, owner):
        """남에게 보이는 이름: 내가 정한 과수원 이름(1.12) → 마지막 게시물 닉네임 → None(앱이 seed 로 짓는다)"""
        r = (self.db.execute("SELECT name FROM farms WHERE owner=? AND name<>''", (owner,)).fetchone()
             or self.db.execute("SELECT nickname FROM posts WHERE owner=? AND hidden=0 ORDER BY created DESC LIMIT 1", (owner,)).fetchone())
        return r[0] if r else None

    def _seed(self, owner):
        """닉네임이 없으면 앱이 이 수로 이름을 짓는다("졸린 유자 과수원"). 같은 설치는 늘 같은 이름."""
        return int(hmac.new(self.salt, owner.encode(), hashlib.sha256).hexdigest()[:8], 16)

    def _nb_dogs(self, owner):
        """개가 있는 이웃 수(1.11, 최대 3). 서리당할 때 한 곳마다 NEIGHBOR_DOG 만큼 덜 가져간다."""
        n = self.db.execute("SELECT COUNT(*) FROM neighbors n JOIN farms f ON f.owner = n.other WHERE n.owner=? AND f.dogs>0",
                            (owner,)).fetchone()[0]
        return min(n, MAX_NEIGHBOR_DOGS)

    def _footprint(self, me, other, t):
        """되찾아 주기(1.11): 이웃(other)이 24시간 안에 당하고 아직 되갚지 않은 가장 최근 서리 (id, 서리꾼, 끝난 시각).
        원래 서리꾼이 나거나 내 이웃이면 뺀다(이웃끼리는 털지 않는다)."""
        return self.db.execute(
            "SELECT r.id, r.raider, r.end FROM raids r JOIN farms f ON f.owner = r.raider WHERE r.victim=? AND r.end<=? AND r.end>? "
            "AND r.revenge=0 AND r.avenged=0 AND r.raider<>? AND r.raider NOT IN (SELECT other FROM neighbors WHERE owner=?) "
            "ORDER BY r.end DESC LIMIT 1", (other, t, t - TRACKS, me, me)).fetchone()

    @staticmethod
    def _final(loot, caught):
        loot = json.loads(loot)
        return raid_caught(loot) if caught else loot

    def _raids_left(self, me, day):
        if BETA_OPEN:
            return RAID_PER_DAY
        used = self.db.execute("SELECT COUNT(*) FROM raids WHERE raider=? AND day=? AND revenge=0", (me, day)).fetchone()[0]
        return max(0, RAID_PER_DAY - used)

    def _raid_view(self, me, now):
        t, day = now.timestamp(), day_key(now)
        f = self._farm(me)
        q = self.db.execute

        def back(r):  # 이웃 대신 되찾아 온 것은 이웃에게 간다(내 창고에는 없음)
            out = {"id": r[0], "role": r[1], "loot": {} if r[4] else self._final(r[2], r[3]), "caught": bool(r[3])}
            if r[4]:
                out["for"] = "neighbor"
            return out

        inbox = q("SELECT * FROM (SELECT id, kind, fruit, stamp, worker, sender, created, long FROM gifts WHERE receiver=? AND done=0 "
                  "ORDER BY created DESC LIMIT ?) ORDER BY created", (me, INBOX)).fetchall()

        def who(o):
            return {"name": self._nick(o), "seed": self._seed(o)}

        def carry(r):  # id, kind, sender, role, level, fruit, count, stamp, worker
            out = {"id": r[0], "kind": r[1], "worker": json.loads(r[8]), **who(r[2])}
            out.update({"dispatch": {"role": r[3], "level": r[4]}, "basket": {"fruit": r[5], "count": r[6], "stamp": r[7]},
                        "sapling": {"tree": r[5]}}[r[1]])
            return out

        cols = "id, kind, sender, role, level, fruit, count, stamp, worker"
        live = q("SELECT " + cols + ", end FROM carries WHERE receiver=? AND kind='dispatch' AND start<=? AND end>? ORDER BY start LIMIT 1",
                 (me, t, t)).fetchone()
        return {
            # 내가 당한 것(끝난 것만): 앱이 창고에서 빼고 ack 한다. by: 들켰다면 누가 봤는지(1.11, 들키지 않았으면 owner)
            "raided": [{"id": r[0], "loot": self._final(r[1], r[2]), "caught": bool(r[2]), "by": "neighbor" if r[3] else "owner"} for r in
                       q("SELECT id, loot, caught, caught_by FROM raids WHERE victim=? AND end<=? AND victim_done=0 ORDER BY end", (me, t))],
            # 내가 보낸 일꾼이 들고 온 것
            "back": [back(r) for r in q("SELECT id, role, loot, caught, beneficiary<>'' FROM raids WHERE raider=? AND end<=? AND raider_done=0 "
                                        "ORDER BY end", (me, t))],
            # 1.11: 이웃이 보낸 돕기·선물(최근 20개, 오래된 것부터). 앱이 반영하고 ack 하면 보낸 사람 고마움 +1
            "inbox": [{"id": r[0], "kind": r[1], "fruit": r[2], "stamp": r[3], "worker": json.loads(r[4]), "name": self._nick(r[5]),
                       "seed": self._seed(r[5]), "long": bool(r[7])} for r in inbox],  # long(1.13): 선배의 돕기라 손길 1시간
            # 1.13 쩔: 지금 와 있는 출장 일꾼(없으면 null). 끝나면 carries 로 와서 ack 하면 선배 고마움 +2
            "dispatch": dict(carry(live), left=int(live[9] - t + 0.999)) if live else None,
            # 받은 바구니·묘목과 끝난 출장(오래된 것부터). 반영하고 ack 하면 선배 고마움(바구니·묘목 +1, 출장 +2)
            "carries": [carry(r) for r in q("SELECT " + cols + " FROM carries WHERE receiver=? AND done=0 AND kind<>'step' AND end<=? "
                                            "ORDER BY start LIMIT ?", (me, t, INBOX))],
            # 사제 단계(crate6·crate12(졸업)·yuja·pink). as=junior: 내가 넘었다(축하 카드, ack 하면 그 선배 고마움 +3, name 은 선배),
            # as=teacher: 내 후배가 넘었다(name 은 후배, ack 하면 사라진다)
            "mentor": [{"id": r[0], "step": r[1], "as": "junior", **who(r[2])} for r in
                       q("SELECT id, fruit, sender FROM carries WHERE receiver=? AND kind='step' AND done=0 ORDER BY start LIMIT ?", (me, INBOX))]
                    + [{"id": r[0], "step": r[1], "as": "teacher", **who(r[2])} for r in
                       q("SELECT id, fruit, receiver FROM carries WHERE sender=? AND kind='step' AND seen=0 ORDER BY start LIMIT ?", (me, INBOX))],
            "teacher": self._grads(me),  # 졸업시킨 제자 수(지금 이웃인 사람만)
            # 1.11: 이웃이 나 대신 되찾아 온 것(ack 하면 되찾아 준 사람 고마움 +1)
            "recovered": [{"id": r[0], "loot": self._final(r[1], r[2]), "caught": bool(r[2])} for r in
                          q("SELECT id, loot, caught FROM raids WHERE beneficiary=? AND end<=? AND beneficiary_done=0 ORDER BY end", (me, t))],
            "thanks": f["thanks"] if f else 0,
            # 아직 나가 있는 일꾼(들키면 10분 늘어난다)
            "away": [{"id": r[0], "role": r[1], "left": int(r[2] - t + 0.999)} for r in
                     q("SELECT id, role, end FROM raids WHERE raider=? AND end>?", (me, t))],
            # 발자국: 24시간 동안 한 번 되갚을 수 있다(되갚기의 발자국은 남기지 않는다)
            "tracks": [{"id": r[0], "left": int(r[1] + TRACKS - t)} for r in
                       q("SELECT id, end FROM raids WHERE victim=? AND end<=? AND end>? AND revenge=0 AND avenged=0",
                         (me, t, t - TRACKS))],
            "left": self._raids_left(me, day),
            "ready": int(max(0, f["first"] + NEW_KEY - t)) if f else NEW_KEY,
            "guard": int(max(0, f["guard"] - t)) if f else 0,
        }

    @locked
    def raid_status(self, owner_key, body, ip, now, device=None):
        """창고 상태 알리기(앱이 켤 때·팔 때·관리 창을 열 때·20% 경계·30분마다, 일꾼이 나가 있으면 1분마다).
        active: 주인이 방금 팔았거나 창을 열었다 → 지금 내 밭과 이웃 밭(1.11)에 있는 서리꾼이 들킨다.
        look(1.11): 과수원 모습. ack 에는 반영한 서리·돕기·선물·되찾은 것 id 를 함께 넣는다."""
        me = self.owner(owner_key)
        if device is not None:  # 1.15.1: 연동을 켠 소유 키는 홀더 기기만(헤더 X-Sync-Device 가 없는 옛 앱은 그대로)
            r = self.db.execute("SELECT holder FROM sync WHERE owner=?", (me,)).fetchone()
            if r and r[0] != sha(device):
                raise BadRequest("not_holder")
        farm = clean_farm(body)
        t = now.timestamp()
        self.limit("raid_status", me, now)
        crate = json.dumps(farm["crate"], sort_keys=True)
        old = self._farm(me)
        if old is None:
            self.limit("farm_new", self.ip(ip), now)
            self.db.execute("INSERT INTO farms(owner, cap, crate, fences, dogs, best, level, first, seen) VALUES(?,?,?,?,?,?,?,?,?)",
                            (me, farm["cap"], crate, farm["fences"], farm["dogs"], farm["best"], farm["level"], t, t))
        else:
            self.db.execute("UPDATE farms SET cap=?, crate=?, fences=?, dogs=?, best=?, level=?, seen=? WHERE owner=?",
                            (farm["cap"], crate, farm["fences"], farm["dogs"], farm["best"], farm["level"], t, me))
        if farm["look"] is not None:
            self.db.execute("UPDATE farms SET look=? WHERE owner=?", (json.dumps(farm["look"]), me))
        self.db.execute("UPDATE farms SET seedling=? WHERE owner=?", (int(farm["seedling"]), me))
        if old is not None:
            self._steps(me, old, farm, now)
        live = " AND start<=? AND end>? AND caught=0"
        near = "victim IN (SELECT other FROM neighbors WHERE owner=?)"
        if farm["active"] and self.db.execute("SELECT 1 FROM raids WHERE (victim=? OR " + near + ")" + live, (me, me, t, t)).fetchone():
            try:
                self.limit("raid_active", me, now)
                self.db.execute("UPDATE raids SET caught=1, end=end+? WHERE victim=?" + live, (CAUGHT_REST, me, t, t))
                self.db.execute("UPDATE raids SET caught=1, caught_by=1, end=end+? WHERE " + near + live, (CAUGHT_REST, me, t, t))
            except RateLimited:
                pass
        for rid in farm["ack"]:
            self.db.execute("UPDATE raids SET raider_done=1 WHERE id=? AND raider=? AND end<=?", (rid, me, t))
            self.db.execute("UPDATE raids SET victim_done=1 WHERE id=? AND victim=? AND end<=?", (rid, me, t))
            # 앱은 반영한 id 를 계속 다시 보낸다. 고마움은 처음 반영할 때 한 번만 센다.
            if self.db.execute("UPDATE gifts SET done=1 WHERE id=? AND receiver=? AND done=0", (rid, me)).rowcount:
                self.db.execute("UPDATE farms SET thanks=thanks+1 WHERE owner=(SELECT sender FROM gifts WHERE id=?)", (rid,))
            if self.db.execute("UPDATE raids SET beneficiary_done=1 WHERE id=? AND beneficiary=? AND end<=? AND beneficiary_done=0",
                               (rid, me, t)).rowcount:
                self.db.execute("UPDATE farms SET thanks=thanks+1 WHERE owner=(SELECT raider FROM raids WHERE id=?)", (rid,))
            # 1.13 쩔: 받은 쪽이 반영(출장은 끝난 뒤에만) → 선배 고마움. 선배가 단계 알림을 ack 하면 seen
            c = self.db.execute("SELECT kind, sender FROM carries WHERE id=? AND receiver=? AND done=0 AND end<=?", (rid, me, t)).fetchone()
            if c:
                self.db.execute("UPDATE carries SET done=1 WHERE id=?", (rid,))
                self.db.execute("UPDATE farms SET thanks=thanks+? WHERE owner=?", (CARRY_THANKS[c[0]], c[1]))
            self.db.execute("UPDATE carries SET seen=1 WHERE id=? AND sender=? AND kind='step'", (rid, me))
        self.db.commit()
        return dict(self._raid_view(me, now), brag=self._brag(me))

    def _fair(self, pid, created):
        """보상용 반응 수(1.17): IP 해시마다 하나, 주인이 자기 표로 준 것과 게시 뒤 10분 안에 같은 IP 해시에서 몰린 것(2개 넘음)은 뺀다."""
        out = dict.fromkeys(("stars",) + BOARD_STAMPS, 0)
        for table, kind in (("stars", "'stars'"), ("stamps", "kind")):
            by = defaultdict(list)
            for ip, at, k in self.db.execute("SELECT ip, created, %s FROM %s WHERE post=? AND own=0" % (kind, table), (pid,)):
                by[ip].append((at, k))
            for rows in by.values():
                if sum(at < created + BURST[0] for at, _ in rows) <= BURST[1]:
                    for k in {k for _, k in rows}:
                        out[k] += 1
        return out

    def _brag(self, me):
        """raid/status 의 게시판 보상 요약: 지금까지(지운 게시물 합계 포함) 게시물·별·스탬프, 구경꾼 날, 확정된 주의 트로피.
        숨긴 게시물은 뺀다. 트로피는 top 1~3위와 부문 1위."""
        q = self.db.execute
        kept = q("SELECT posts, stars, lemon, flower, laugh, clap FROM brag_kept WHERE owner=?", (me,)).fetchone() or (0,) * 6
        n = dict(zip(("posts", "stars") + BOARD_STAMPS, kept))
        for pid, created in q("SELECT id, created FROM posts WHERE owner=? AND hidden=0", (me,)).fetchall():
            n["posts"] += 1
            for k, v in self._fair(pid, created).items():
                n[k] += v
        trophies = q("SELECT h.week, h.kind, h.rank FROM highlights h JOIN closed c ON c.week = h.week "
                     "WHERE h.owner=? AND h.rank<=3 AND NOT EXISTS (SELECT 1 FROM posts p WHERE p.id = h.post AND p.hidden=1) "
                     "ORDER BY h.week, h.kind", (me,)).fetchall()
        return {"posts": n["posts"], "stars": n["stars"], "stamps": {k: n[k] for k in BOARD_STAMPS},
                "visits": q("SELECT COUNT(*) FROM visits WHERE owner=?", (me,)).fetchone()[0],
                "trophies": [{"week": w, "kind": k, "rank": r} for w, k, r in trophies]}

    def _steps(self, me, old, new, now):
        """사제 단계(1.13): 이번 맞추기에서 넘은 단계마다, 넘기 전 내 창고 레벨보다 4 이상 높은 이웃(선배)에게 한 번씩
        step 알림을 남긴다(이웃 사이마다 비트로 한 번, 맺은 뒤 넘은 것만)."""
        crossed = [(name, bit) for name, bit, ok in STEPS if not ok(old["level"], old["best"]) and ok(new["level"], new["best"])]
        if not crossed:
            return
        t = now.timestamp()
        for senior, steps, level in self.db.execute("SELECT n.owner, n.steps, f.level FROM neighbors n JOIN farms f ON f.owner = n.owner "
                                                    "WHERE n.other=?", (me,)).fetchall():
            if not is_junior(level, old["level"]):  # 넘기 전 내 레벨로 본다(졸업 단계도 넘기 전에는 후배)
                continue
            for name, bit in crossed:
                if not steps & bit:
                    steps |= bit
                    self.db.execute("INSERT INTO carries(id, sender, receiver, day, week, kind, fruit, start, end) VALUES(?,?,?,?,?,'step',?,?,?)",
                                    (secrets.token_urlsafe(9), senior, me, day_key(now), week_key(now), name, t, t))
            self.db.execute("UPDATE neighbors SET steps=? WHERE owner=? AND other=?", (steps, senior, me))

    def _grads(self, owner):
        """졸업시킨 제자 수(1.13): 지금 이웃 중 나와 이웃일 때 창고 레벨 12 를 넘은 후배"""
        return self.db.execute("SELECT COUNT(*) FROM neighbors WHERE owner=? AND steps & ?", (owner, GRAD)).fetchone()[0]

    def _candidates(self, me, now):
        """서리할 수 있는 과수원(개가 짖는 곳도 보여 준다). 내 이웃(1.11)·초보(설치 3일·창고 레벨 2 미만)·14일 소식 없음·20% 미만·
        오늘 손실 상한·오늘 내가 이미 간 곳은 뺀다. ponytail: farms 를 다 훑는다. 참여자가 수만이 되면 seen·first 색인으로."""
        t, day = now.timestamp(), day_key(now)
        done = {r[0] for r in self.db.execute("SELECT victim FROM raids WHERE raider=? AND day=? AND revenge=0", (me, day))}
        out = []
        for r in self.db.execute(self.FARM + " WHERE owner<>? AND seen>? AND first<=? AND level>=? "
                                 "AND owner NOT IN (SELECT other FROM neighbors WHERE owner=?)", (me, t - STALE, t - NEWBIE, MIN_LEVEL, me)).fetchall():
            f = self._farm_row(r)
            f["lost"] = f["lost"] if f["lost_day"] == day else 0
            if f["owner"] in done or sum(f["crate"].values()) < f["cap"] * MIN_FILL or (not BETA_OPEN and f["lost"] >= int(f["cap"] * DAILY_LOSS)):
                continue
            out.append(f)
        return out

    @locked
    def raid_targets(self, owner_key, now):
        me = self.owner(owner_key)
        self.limit("raid_targets", me, now)
        if self._farm(me) is None:
            raise BadRequest("no_farm")
        hour = now.astimezone(KST).strftime("%Y%m%d%H")  # 한 시간마다 다른 12곳
        picks = sorted(self._candidates(me, now), key=lambda f: sha(me + hour + f["owner"]))[:RAID_TARGETS]
        t = now.timestamp()
        out = []
        for f in picks:
            n = sum(f["crate"].values())
            kinds = sorted(f["crate"], key=lambda k: (-PRICE[k], ORDER[k]))
            out.append({"id": self._target_id(me, f["owner"]), "name": self._nick(f["owner"]), "seed": self._seed(f["owner"]),
                        # 찬 정도는 10% 단위(작은 변화로 누가 누군지 맞춰 보지 못하게)
                        "fill": round(n / f["cap"], 1), "kinds": [{"kind": k, "lots": f["crate"][k] >= 10} for k in kinds],
                        "fences": f["fences"], "dogs": f["dogs"], "nbDogs": self._nb_dogs(f["owner"]), "dog": f["guard"] > t})
        view = self._raid_view(me, now)
        return {"targets": out, "left": view["left"], "ready": view["ready"]}

    @locked
    def raid(self, owner_key, body, ip, now):
        """일꾼을 보낸다. {target, role, level, plan}, 되갚기 {revenge: 발자국 id, …},
        되찾아 주기(1.11) {recover: 이웃 id, …}: 그 이웃의 가장 최근 발자국을 따라 되갚기처럼 털고, 담은 것은 이웃에게 간다(recovered)."""
        me = self.owner(owner_key)
        if not isinstance(body, dict) or body.get("role") not in ROLES or body.get("plan") not in RAID_PLANS:
            raise BadRequest()
        role, plan, level = body["role"], body["plan"], _int(body.get("level"), 1, 20)
        self.limit("raid", me, now)
        self.limit("raid_ip", self.ip(ip), now)
        t, day = now.timestamp(), day_key(now)
        mine = self._farm(me)
        if mine is None or mine["first"] > t - NEW_KEY:
            raise BadRequest("too_new")
        if (self.db.execute("SELECT 1 FROM raids WHERE raider=? AND role=? AND end>?", (me, role, t)).fetchone()
                or self.db.execute("SELECT 1 FROM carries WHERE sender=? AND kind='dispatch' AND role=? AND end>?", (me, role, t)).fetchone()):
            raise BadRequest("busy")  # 1.13: 출장 간 일꾼도
        revenge, recover, beneficiary = body.get("revenge"), body.get("recover"), ""
        if revenge is not None or recover is not None:
            if recover is not None:  # 되찾아 주기는 이웃의 발자국으로 하는 되갚기다(양 두 배, 하루 3번에 안 센다)
                beneficiary = self._neighbor(me, recover)
                r = self._footprint(me, beneficiary, t)
                revenge = r[0] if r else recover
            else:
                r = self.db.execute("SELECT id, raider FROM raids WHERE id=? AND victim=? AND revenge=0 AND avenged=0 AND end<=? AND end>?",
                                    (_match(revenge, RAID_ID), me, t, t - TRACKS)).fetchone()
            victim = self._farm(r[1]) if r else None
            if victim is None:
                raise KeyError(revenge)
            victim["lost"] = victim["lost"] if victim["lost_day"] == day else 0
        else:
            if self._raids_left(me, day) <= 0:
                raise BadRequest("no_raids_left")
            tid = _match(body.get("target"), TARGET_ID)
            victim = next((f for f in self._candidates(me, now) if self._target_id(me, f["owner"]) == tid), None)
            if victim is None:
                raise KeyError(tid)
            if victim["guard"] > t and not BETA_OPEN:
                raise BadRequest("guarded")
        loot = raid_loot(victim["crate"], victim["cap"], victim["fences"], victim["dogs"], 0 if BETA_OPEN else victim["lost"], role, level, plan,
                         raid_budget(mine["cap"], mine["best"]), revenge is not None, self._nb_dogs(victim["owner"]))
        if not loot:
            raise BadRequest("empty")
        rid = secrets.token_urlsafe(9)
        dur = raid_duration(role, plan)
        self.db.execute("INSERT INTO raids(id, raider, victim, day, role, plan, start, end, loot, revenge, beneficiary) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (rid, me, victim["owner"], day, role, plan, t, t + dur, json.dumps(loot, sort_keys=True), int(revenge is not None),
                         beneficiary))
        if revenge is not None:
            self.db.execute("UPDATE raids SET avenged=1 WHERE id=?", (revenge,))
        if revenge is not None:
            # 되갚기는 손실 상한만 센다. 개·창고를 바꾸면 되갚은 사람이 대상 목록 변화로 원래 서리꾼을 알아챌 수 있다.
            self.db.execute("UPDATE farms SET lost_day=?, lost=? WHERE owner=?", (day, victim["lost"] + sum(loot.values()), victim["owner"]))
        else:
            left = {k: n - loot.get(k, 0) for k, n in victim["crate"].items() if n - loot.get(k, 0) > 0}
            self.db.execute("UPDATE farms SET crate=?, lost_day=?, lost=?, guard=? WHERE owner=?",
                            (json.dumps(left, sort_keys=True), day, victim["lost"] + sum(loot.values()), t + (0 if BETA_OPEN else GUARD), victim["owner"]))
        self.db.commit()
        return {"id": rid, "role": role, "left": int(dur)}

    # 이웃 (1.11). 서로 돕는 사이: 서리 대상에서 빠지고 하루 한 번씩 돕기·선물. 상대 키 해시는 내려 주지 않는다(id 는 _target_id).

    def _member(self, owner_key, action, now):
        """이웃 요청 공통: 키 확인 → 횟수 제한 → 서리 맞추기로 만든 내 과수원이 있어야 한다"""
        me = self.owner(owner_key)
        self.limit(action, me, now)
        mine = self._farm(me)
        if mine is None:
            raise BadRequest("no_farm")
        return me, mine

    def _neighbor(self, me, nid):
        """요청한 사람에게 준 id 로 이웃을 찾는다"""
        nid = _match(nid, TARGET_ID)
        for (other,) in self.db.execute("SELECT other FROM neighbors WHERE owner=?", (me,)).fetchall():
            if self._target_id(me, other) == nid:
                return other
        raise KeyError(nid)

    def _code(self, me, now, renew=False):
        """내 초대 코드(없으면 만든다). renew 면 새 코드로 바꾸고 옛 코드는 더 통하지 않는다."""
        r = self.db.execute("SELECT code FROM codes WHERE owner=?", (me,)).fetchone()
        if r and not renew:
            return r[0]
        code = ""
        while not code or self.db.execute("SELECT 1 FROM codes WHERE code=?", (code,)).fetchone():
            code = "".join(secrets.choice(CODE_CHARS) for _ in range(CODE_LEN))
        self.db.execute("DELETE FROM codes WHERE owner=?", (me,))
        self.db.execute("INSERT INTO codes VALUES(?,?,?)", (me, code, now.timestamp()))
        return code

    def _carry_room(self, other, now):
        """후배(other)가 지금 더 받을 수 있는 쩔(모든 선배 합산): 출장·바구니는 오늘, 묘목은 이번 주, 받아 둔 묘목이 없을 때"""
        t, q = now.timestamp(), self.db.execute
        taken = {k for (k,) in q("SELECT DISTINCT kind FROM carries WHERE receiver=? AND ((kind IN ('dispatch', 'basket') AND day=?) "
                                 "OR (kind='sapling' AND week=?))", (other, day_key(now), week_key(now)))}
        live = q("SELECT 1 FROM carries WHERE receiver=? AND kind='dispatch' AND end>?", (other, t)).fetchone()
        holding = (q("SELECT seedling FROM farms WHERE owner=?", (other,)).fetchone() or (0,))[0] or \
            q("SELECT 1 FROM carries WHERE receiver=? AND kind='sapling' AND done=0", (other,)).fetchone()
        return {"dispatch": None if "dispatch" in taken else "busy" if live else True,
                "basket": None if "basket" in taken else True, "sapling": None if "sapling" in taken else "holding" if holding else True}

    def _neighbor_view(self, me, mine, now):
        t, day = now.timestamp(), day_key(now)
        # gifts.day: 선물은 날짜, 돕기는 칸(1.13, slot_key). 1.12 까지 날짜로 적힌 돕기는 칸과 안 맞아 그날 한 번 더 될 수 있다(배포 날만)
        done = set(self.db.execute("SELECT receiver, kind, day FROM gifts WHERE sender=? AND day IN (?, ?, ?)",
                                   (me, day, day + "am", slot_key(now))).fetchall())
        out = []
        for other, seen, dogs, look, level, best in self.db.execute(
                "SELECT n.other, f.seen, f.dogs, f.look, f.level, f.best FROM neighbors n JOIN farms f ON f.owner = n.other "
                "WHERE n.owner=? ORDER BY n.created, n.rowid", (me,)).fetchall():
            fp = self._footprint(me, other, t)
            look = json.loads(look)
            junior = is_junior(mine["level"], level)
            room = self._carry_room(other, now) if junior else {}
            saplings = sapling_kinds(best, mine["best"]) if junior else []
            out.append({"id": self._target_id(me, other), "name": self._nick(other), "seed": self._seed(other), "look": look,
                        # 마지막으로 맞춘 지 몇 초. 언제 켜고 끄는지 자세히 드러나지 않게 시간 단위로 반올림
                        "seen": int(max(0, t - seen) / 3600 + 0.5) * 3600,
                        # helped: 지금 칸(오전/오후)에 이미 돕기를 했는지, helpedAm: 오늘 오전에 했는지(1.13 하루 2번)
                        "helped": (other, "help", slot_key(now)) in done, "helpedAm": (other, "help", day + "am") in done,
                        "gifted": (other, "gift", day) in done, "dogs": dogs,
                        # 24시간 안에 당하고 아직 아무도 되갚지 않았으면 남은 초(내가 되찾아 줄 수 있다)
                        "track": int(fp[2] + TRACKS - t) if fp else 0,
                        # 1.13 쩔: 후배(내가 4 이상 높음)·선배, 이 이웃이 졸업시킨 제자 수, 잡초 단계,
                        # 후배면 오늘 출장·바구니·이번 주 묘목을 더 받을 수 있는지(모든 선배 합산), 바구니 값 상한, 보낼 수 있는 묘목
                        "junior": junior, "senior": is_junior(level, mine["level"]), "teacher": self._grads(other),
                        "weeds": look.get("weeds", 0),
                        "canDispatch": room.get("dispatch") is True, "canBasket": room.get("basket") is True,
                        "canSapling": room.get("sapling") is True and bool(saplings),
                        "basketValue": basket_value(best) if junior else 0, "saplings": saplings})
        return {"code": self._code(me, now), "max": MAX_NEIGHBORS, "thanks": mine["thanks"], "neighbors": out,
                "teacher": self._grads(me),  # 1.13 내가 졸업시킨 제자 수
                # 1.12 내가 정한 과수원 이름(없으면 null)과 앱이 이름을 지을 seed
                "me": {"name": mine["name"] or None, "seed": self._seed(me)},
                # 1.14 받은·보낸 이웃 요청(7일 안), 찾기에 보이기·요청 받기
                "requests": self._requests(me, t), "prefs": {"listed": mine["listed"], "requests": mine["asks"]}}

    def _requests(self, me, t):
        q = self.db.execute
        return {
            "in": [{"id": self._target_id(me, o), "name": self._nick(o), "seed": self._seed(o), "look": json.loads(look), "level": level,
                    "stamp": stamp, "at": int(at)} for o, stamp, at, look, level in
                   q("SELECT r.sender, r.stamp, r.created, f.look, f.level FROM requests r JOIN farms f ON f.owner = r.sender "
                     "WHERE r.receiver=? AND r.status='pending' AND r.created>? AND r.sender NOT IN (SELECT other FROM blocks WHERE owner=?) "
                     "ORDER BY r.created", (me, t - REQUEST_DAYS, me))],
            # 거절된 것도 7일 동안 그대로 보인다(거절했다고 알리지 않는다: "아직 답이 없어요")
            "out": [{"id": self._target_id(me, o), "name": self._nick(o), "seed": self._seed(o), "at": int(at)} for o, at in
                    q("SELECT r.receiver, r.created FROM requests r JOIN farms f ON f.owner = r.receiver WHERE r.sender=? AND r.created>? "
                      "ORDER BY r.created", (me, t - REQUEST_DAYS))]}

    def _find(self, me, nid, owners):
        """요청한 사람에게 준 id(_target_id)로 owners 중에서 찾는다"""
        nid = _match(nid, TARGET_ID)
        for o in owners:
            if self._target_id(me, o) == nid:
                return o
        raise KeyError(nid)

    def _blocked(self, a, b):
        return self.db.execute("SELECT 1 FROM blocks WHERE (owner=? AND other=?) OR (owner=? AND other=?)", (a, b, b, a)).fetchone() is not None

    def _befriend(self, a, b, t):
        if any(self.db.execute("SELECT COUNT(*) FROM neighbors WHERE owner=?", (o,)).fetchone()[0] >= MAX_NEIGHBORS for o in (a, b)):
            raise BadRequest("full")
        self.db.executemany("INSERT INTO neighbors(owner, other, created) VALUES(?,?,?)", [(a, b, t), (b, a, t)])
        self.db.execute("DELETE FROM requests WHERE (sender=? AND receiver=?) OR (sender=? AND receiver=?)", (a, b, b, a))

    @locked
    def discover(self, owner_key, query, now):
        """이웃 찾기(1.14): 최근 14일 안에 켜진 과수원 중 나·내 이웃·차단(양쪽)·보이기 끈 곳을 뺀다. 한 번에 20곳.
        sort: recent(최근 활동, 기본)·similar(창고 레벨이 비슷한 순)·new(후배가 될 과수원만, 새로 시작한 순)·
        mentor(1.15, 나와 선배·후배가 될 수 있는 곳만, 최근 활동 순. junior 가 거짓이면 그곳이 내 선배). q: 이름 검색.
        ponytail: farms 를 다 훑고 이름도 하나씩 찾는다. 참여자가 수만이 되면 seen 색인과 이름 열 검색으로."""
        me, mine = self._member(owner_key, "discover", now)
        query = query if isinstance(query, dict) else {}
        sort, text, page = query.get("sort") or "recent", query.get("q") or "", query.get("page") or 0
        if sort not in DISCOVER_SORTS or not _TEXT(text):
            raise BadRequest()
        page = _int(int(page) if isinstance(page, str) and page.isdigit() else page, 0, 50)
        t = now.timestamp()
        rows = self.db.execute("SELECT owner, look, level, seen, first FROM farms WHERE owner<>? AND listed=1 AND seen>? "
                               "AND owner NOT IN (SELECT other FROM neighbors WHERE owner=?) "
                               "AND owner NOT IN (SELECT other FROM blocks WHERE owner=?) AND owner NOT IN (SELECT owner FROM blocks WHERE other=?)",
                               (me, t - STALE, me, me, me)).fetchall()
        text = " ".join(text.split()).lower()
        if text:
            rows = [r for r in rows if text in (self._nick(r[0]) or "").lower()]
        if sort == "new":
            rows = sorted((r for r in rows if is_junior(mine["level"], r[2])), key=lambda r: -r[4])
        elif sort == "mentor":
            rows = sorted((r for r in rows if is_junior(mine["level"], r[2]) or is_junior(r[2], mine["level"])), key=lambda r: -r[3])
        elif sort == "similar":
            rows.sort(key=lambda r: (abs(r[2] - mine["level"]), -r[3]))
        else:
            rows.sort(key=lambda r: -r[3])
        part = rows[page * DISCOVER_PAGE:(page + 1) * DISCOVER_PAGE]
        return {"farms": [{"id": self._target_id(me, o), "name": self._nick(o), "seed": self._seed(o), "look": json.loads(look), "level": level,
                           "neighbors": self.db.execute("SELECT COUNT(*) FROM neighbors WHERE owner=?", (o,)).fetchone()[0],
                           "seen": int(max(0, t - seen) / 3600 + 0.5) * 3600, "junior": is_junior(mine["level"], level)}
                          for o, look, level, seen, _ in part],
                "more": len(rows) > (page + 1) * DISCOVER_PAGE}

    @locked
    def neighbor_request(self, owner_key, body, now):
        """이웃 요청(1.14) {id 또는 post(1.17 게시물 id), stamp?} → {ok}. 상대가 이미 나에게 요청해 두었으면 바로 이웃({ok, added}).
        차단(어느 쪽이든)이면 조용히 ok. 보낸 요청 하루 20·대기 30, 거절·만료 뒤 같은 곳은 7일 뒤에."""
        me, mine = self._member(owner_key, "neighbor_request", now)
        if not isinstance(body, dict) or not _v_opt(_STAMP)(body.get("stamp")):
            raise BadRequest()
        t = now.timestamp()
        if "post" in body:  # 1.17 게시판 '이웃 되기': 게시물 주인에게
            other = self._post_owner(_match(body["post"], POST_ID))
            if other == me:
                raise BadRequest("self")
            if not self._farm(other):
                raise KeyError(other)
        else:
            other = self._find(me, body.get("id"), [r[0] for r in self.db.execute("SELECT owner FROM farms WHERE owner<>?", (me,))])
        if self._blocked(me, other):
            return {"ok": True}
        if self.db.execute("SELECT 1 FROM neighbors WHERE owner=? AND other=?", (me, other)).fetchone():
            raise BadRequest("already")
        if self.db.execute("SELECT 1 FROM requests WHERE sender=? AND receiver=? AND status='pending' AND created>?",
                           (other, me, t - REQUEST_DAYS)).fetchone():
            self._befriend(me, other, t)
            self.db.commit()
            return {"ok": True, "added": self._target_id(me, other)}
        old = self.db.execute("SELECT status, created, ended FROM requests WHERE sender=? AND receiver=?", (me, other)).fetchone()
        if old and old[0] == "pending" and old[1] > t - REQUEST_DAYS:
            raise BadRequest("pending")
        if old and (old[2] if old[0] == "declined" else old[1] + REQUEST_DAYS) > t - REQUEST_DAYS:
            raise BadRequest("cooldown")
        if not self._farm(other)["asks"]:
            raise BadRequest("closed")
        if any(self.db.execute("SELECT COUNT(*) FROM neighbors WHERE owner=?", (o,)).fetchone()[0] >= MAX_NEIGHBORS for o in (me, other)):
            raise BadRequest("full")
        today = datetime.strptime(day_key(now), "%Y-%m-%d").replace(tzinfo=KST).timestamp()  # KST 오늘 0시
        sent, waiting = self.db.execute("SELECT SUM(created>=?), SUM(status='pending' AND created>?) FROM requests WHERE sender=?",
                                        (today, t - REQUEST_DAYS, me)).fetchone()
        if (sent or 0) >= REQUESTS_PER_DAY or (waiting or 0) >= REQUESTS_PENDING:
            raise RateLimited()
        self.db.execute("INSERT OR REPLACE INTO requests(sender, receiver, created, stamp, status) VALUES(?,?,?,?,'pending')",
                        (me, other, t, body.get("stamp")))
        self.db.commit()
        return {"ok": True}

    @locked
    def neighbor_answer(self, owner_key, kind, body, now):
        """받은 요청에 accept(양쪽 이웃, 이웃 목록 + added)·decline(보낸 쪽에는 알리지 않는다), block(요청·찾기에서 서로 안 보이고
        이웃이었으면 끊긴다. id 는 받은 요청·찾기·이웃 목록 어디서 온 것이든). 셋 다 이웃 목록을 돌려준다."""
        me, mine = self._member(owner_key, "neighbors", now)
        nid = body.get("id") if isinstance(body, dict) else None
        t = now.timestamp()
        if kind == "block":
            other = self._find(me, nid, [r[0] for r in self.db.execute("SELECT owner FROM farms WHERE owner<>?", (me,))])
            self.db.execute("INSERT OR IGNORE INTO blocks VALUES(?,?,?)", (me, other, t))
            self.db.execute("DELETE FROM requests WHERE (sender=? AND receiver=?) OR (sender=? AND receiver=?)", (me, other, other, me))
            self.db.execute("DELETE FROM neighbors WHERE (owner=? AND other=?) OR (owner=? AND other=?)", (me, other, other, me))
            extra = {}
        else:
            other = self._find(me, nid, [r[0] for r in self.db.execute(
                "SELECT sender FROM requests WHERE receiver=? AND status='pending' AND created>?", (me, t - REQUEST_DAYS))])
            if kind == "accept":
                self._befriend(me, other, t)
                extra = {"added": self._target_id(me, other)}
            else:
                self.db.execute("UPDATE requests SET status='declined', ended=? WHERE sender=? AND receiver=?", (t, other, me))
                extra = {}
        out = dict(self._neighbor_view(me, self._farm(me), now), **extra)
        self.db.commit()
        return out

    @locked
    def neighbor_prefs(self, owner_key, body, now):
        """{listed?, requests?}(1.14): 이웃 찾기에 보이기, 요청 받기. 보낸 것만 바꾼다."""
        me, mine = self._member(owner_key, "neighbor_name", now)
        if not isinstance(body, dict) or any(k in body and not isinstance(body[k], bool) for k in ("listed", "requests")):
            raise BadRequest()
        listed, asks = body.get("listed", mine["listed"]), body.get("requests", mine["asks"])
        self.db.execute("UPDATE farms SET listed=?, asks=? WHERE owner=?", (int(listed), int(asks), me))
        self.db.commit()
        return {"prefs": {"listed": listed, "requests": asks}}

    @locked
    def proxy_view(self, owner, now):
        """폰 대리(1.14): Mac 이 잠든 동안 relay/view 에 덧붙일 이웃 목록(횟수 제한 없이, 폰이 5초마다 본다)"""
        mine = self._farm(owner)
        if mine is None:
            return None
        out = self._neighbor_view(owner, mine, now)
        self.db.commit()
        return out

    @locked
    def proxy_farm(self, owner):
        """폰 대리: 창고(선물할 과일이 있는지)와 과수원 모습(보내는 일꾼 모습)"""
        f = self._farm(owner)
        if f:
            f["look"] = json.loads(self.db.execute("SELECT look FROM farms WHERE owner=?", (owner,)).fetchone()[0])
        return f

    @locked
    def neighbor_list(self, owner_key, now):
        me, mine = self._member(owner_key, "neighbors", now)
        out = self._neighbor_view(me, mine, now)
        self.db.commit()  # 처음 보면 코드를 만든다
        return out

    @locked
    def neighbor_name(self, owner_key, body, now):
        """내 과수원 이름(1.12): 이웃 카드·방문·서리 대상 목록에 보인다. 게시물 닉네임과 같은 검사, 비우면 지운다
        (그러면 마지막 게시물 닉네임, 그것도 없으면 앱이 seed 로 지은 이름)."""
        me, _ = self._member(owner_key, "neighbor_name", now)
        name = body.get("name") if isinstance(body, dict) else None
        name = "" if isinstance(name, str) and not name.strip() else clean_nickname(name)
        self.db.execute("UPDATE farms SET name=? WHERE owner=?", (name, me))
        self.db.commit()
        return {"name": name or None}

    @locked
    def clear_name(self, name):
        """관리(1.12, 욕설 신고 대응): 그 이름인 과수원 이름을 모두 지운다. 지운 수를 돌려준다."""
        n = self.db.execute("UPDATE farms SET name='' WHERE name=? AND name<>''", (" ".join(name.split()),)).rowcount
        self.db.commit()
        return n

    @locked
    def neighbor_code(self, owner_key, body, now):
        me, _ = self._member(owner_key, "neighbor_code", now)
        code = self._code(me, now, renew=isinstance(body, dict) and body.get("renew") is True)
        self.db.commit()
        return {"code": code}

    @locked
    def neighbor_add(self, owner_key, body, ip, now):
        """받은 코드를 넣으면 바로 양쪽 이웃. 입력의 대소문자·하이픈·공백은 무시한다."""
        me, mine = self._member(owner_key, "neighbor_add", now)
        self.limit("neighbor_add_ip", self.ip(ip), now)
        code = body.get("code") if isinstance(body, dict) else None
        code = re.sub(r"[\s-]", "", code).upper() if isinstance(code, str) else ""
        r = self.db.execute("SELECT c.owner FROM codes c JOIN farms f ON f.owner = c.owner WHERE c.code=?", (code,)).fetchone()
        if not r or r[0] == me:
            raise BadRequest("bad_code")
        other = r[0]
        if self.db.execute("SELECT 1 FROM neighbors WHERE owner=? AND other=?", (me, other)).fetchone():
            raise BadRequest("already")
        if any(self.db.execute("SELECT COUNT(*) FROM neighbors WHERE owner=?", (o,)).fetchone()[0] >= MAX_NEIGHBORS for o in (me, other)):
            raise BadRequest("full")
        t = now.timestamp()
        self.db.executemany("INSERT INTO neighbors(owner, other, created) VALUES(?,?,?)", [(me, other, t), (other, me, t)])
        out = dict(self._neighbor_view(me, mine, now), added=self._target_id(me, other))
        self.db.commit()  # 목록을 만들며 내 코드가 처음 생길 수 있어 그 뒤에
        return out

    @locked
    def neighbor_remove(self, owner_key, body, now):
        """이웃 끊기(양쪽). 이미 보낸 돕기·선물은 그대로 간다."""
        me, mine = self._member(owner_key, "neighbors", now)
        other = self._neighbor(me, body.get("id") if isinstance(body, dict) else None)
        self.db.execute("DELETE FROM neighbors WHERE (owner=? AND other=?) OR (owner=? AND other=?)", (me, other, other, me))
        out = self._neighbor_view(me, mine, now)
        self.db.commit()
        return out

    @locked
    def neighbor_send(self, owner_key, kind, body, now):
        """돕기(help, 1.13 부터 오전·오후 칸마다)·선물(gift, 과일 한 개, 하루 한 번)을 이웃마다. 받는 쪽은 raid/status 의 inbox 로 받는다.
        선물 과일은 내가 연 가장 비싼 과일 값 이하만 확인한다(창고에서 빼는 것은 앱이 한다)."""
        me, mine = self._member(owner_key, "neighbor_send", now)
        if not isinstance(body, dict):
            raise BadRequest()
        other = self._neighbor(me, body.get("id"))
        stamp, worker, fruit = _one(body.get("stamp"), STAMPS), _tuple(body.get("worker"), *WORKER_LOOK), None
        if kind == "gift":
            fruit = body.get("fruit")
            if not isinstance(fruit, str) or fruit not in PRICE or PRICE[fruit] > PRICE[mine["best"]]:
                raise BadRequest("bad_fruit")
        day = slot_key(now) if kind == "help" else day_key(now)  # 1.13: 돕기는 오전·오후 칸마다 한 번, 선물은 하루 한 번
        if self.db.execute("SELECT 1 FROM gifts WHERE sender=? AND receiver=? AND day=? AND kind=?", (me, other, day, kind)).fetchone():
            raise BadRequest("done_today")
        # 1.13 손길 강화: 선배가 후배에게 보낸 돕기는 손길 1시간(받는 쪽 inbox 의 long)
        long = kind == "help" and is_junior(mine["level"], self._farm(other)["level"])
        self.db.execute("INSERT INTO gifts(id, sender, receiver, day, kind, fruit, stamp, worker, created, long) VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (secrets.token_urlsafe(9), me, other, day, kind, fruit, stamp, json.dumps(worker), now.timestamp(), int(long)))
        self.db.commit()
        return {"ok": True, "long": True} if long else {"ok": True}

    @locked
    def neighbor_carry(self, owner_key, kind, body, now):
        """쩔(1.13): 선배가 후배(창고 레벨이 4 이상 낮은 이웃)에게 보낸다. 받는 쪽 상한은 모든 선배를 합쳐 센다.
        dispatch {id, role, level, worker} → {ok, end, left}: 4시간 출장(후배는 raid/status 의 dispatch 로 받는다). 하루 1번,
          한 번에 한 명(내가 보낸 출장·서리 나간 그 역할·후배에게 와 있는 출장이 있으면 busy).
        basket {id, fruit, count, stamp, worker} → {ok, count}: 과일 값 ≤ 내 best, 값 합 ≤ basket_value(후배 best), 개수 ≤ 후배 정원으로
          줄여 돌려준다(창고에서 빼는 것은 앱이). 하루 1바구니.
        sapling {id, kind, worker} → {ok}: sapling_kinds 안. 주 1그루, 받아 두고 안 심은 묘목이 있으면 holding."""
        me, mine = self._member(owner_key, "neighbor_send", now)
        if not isinstance(body, dict):
            raise BadRequest()
        other = self._neighbor(me, body.get("id"))
        junior = self._farm(other)
        worker = _tuple(body.get("worker"), *WORKER_LOOK)
        role = level = fruit = count = stamp = None
        if kind == "dispatch":
            role, level = _one(body.get("role"), ROLES), _int(body.get("level"), 0, DISPATCH_LEVEL_CAP)
            if worker[0] != role:
                raise BadRequest()
        elif kind == "basket":
            fruit = body.get("fruit")
            if not isinstance(fruit, str) or fruit not in PRICE or fruit == "rainbow" or PRICE[fruit] > PRICE[mine["best"]]:
                raise BadRequest("bad_fruit")  # 무지개 레몬은 바구니에 못 담는다(앱 basketCount)
            count, stamp = _int(body.get("count"), 1, MAX_CRATE), _one(body.get("stamp"), STAMPS)
        else:
            fruit = body.get("kind")
            if not isinstance(fruit, str) or fruit not in sapling_kinds(junior["best"], mine["best"]):
                raise BadRequest("bad_kind")
        if not is_junior(mine["level"], junior["level"]):
            raise BadRequest("not_junior")
        t = now.timestamp()
        room = self._carry_room(other, now)[kind]
        if room is None:
            raise BadRequest("taken_week" if kind == "sapling" else "taken_today")
        if room in ("busy", "holding"):
            raise BadRequest(room)
        if kind == "dispatch" and (
                self.db.execute("SELECT 1 FROM carries WHERE sender=? AND kind='dispatch' AND end>?", (me, t)).fetchone()
                or self.db.execute("SELECT 1 FROM raids WHERE raider=? AND role=? AND end>?", (me, role, t)).fetchone()):
            raise BadRequest("busy")
        if kind == "basket":
            count = min(count, basket_value(junior["best"]) // PRICE[fruit], junior["cap"])
            if count < 1:
                raise BadRequest("bad_fruit")  # 한 개도 상한 안에 들지 않는 비싼 과일
        end = t + (DISPATCH_SECONDS if kind == "dispatch" else 0)
        self.db.execute("INSERT INTO carries(id, sender, receiver, day, week, kind, role, level, fruit, count, stamp, worker, start, end) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (secrets.token_urlsafe(9), me, other, day_key(now), week_key(now), kind,
                                                                 role, level, fruit, count, stamp, json.dumps(worker), t, end))
        self.db.commit()
        if kind == "dispatch":
            return {"ok": True, "end": int(end), "left": DISPATCH_SECONDS}
        return {"ok": True, "count": count} if kind == "basket" else {"ok": True}

    # 기기 연동 (1.15.1, docs/research/sync-1.15.1.md 확정 절). owner·device 는 sha256 만 저장한다.
    # 예외: sync_codes.key 는 소유 키 원문이다. redeem 은 소유 키 없이 코드만으로 새 기기에 소유 키를 돌려줘야 해서,
    # 아직 쓰지 않은 코드 행에만 두고 쓰면 바로, 쓰지 않으면 10분 뒤(redeem·code 가 읽을 때와 maintain) 지운다.

    def _sync_on(self, owner_key, body, now, *fields):
        """공통: 키 확인 → 횟수 제한 → 본문 검사 → 켜져 있어야 한다(아니면 404 off). (me, 본문, (rev, holder, schema))"""
        me = self.owner(owner_key)
        self.limit("sync", me, now)
        b = clean_sync(body, now, *fields)
        row = self.db.execute("SELECT rev, holder, schema FROM sync WHERE owner=?", (me,)).fetchone()
        if row is None:
            raise BadRequest("off")
        return me, b, row

    def _sync_member(self, me, dev):
        """목록에 없거나 끊긴 기기는 이어받지 못한다(코드를 다시 받아야 한다)"""
        if not self.db.execute("SELECT 1 FROM sync_devices WHERE owner=? AND device=? AND revoked=0", (me, dev)).fetchone():
            raise BadRequest("revoked")

    def _sync_join(self, me, b, t):
        """이 기기를 목록에 넣는다(끊겼던 기기도 켜기·코드로 다시 들어오면 되살린다)"""
        self.db.execute("INSERT INTO sync_devices(owner, device, platform, label, added, seen) VALUES(?,?,?,?,?,?) "
                        "ON CONFLICT(owner, device) DO UPDATE SET platform=excluded.platform, label=excluded.label, seen=excluded.seen, revoked=0",
                        (me, b["device"], b["platform"], b["label"], t, t))

    def _sync_seen(self, me, dev, t):
        self.db.execute("UPDATE sync_devices SET seen=? WHERE owner=? AND device=?", (t, me, dev))

    def _drop_sync(self, me):
        for table in ("sync", "sync_devices", "sync_codes"):
            self.db.execute("DELETE FROM %s WHERE owner=?" % table, (me,))

    @locked
    def sync_enable(self, owner_key, body, now):
        """켜기: 지금 과수원을 올리고 이 기기가 홀더. 이미 켜져 있으면 덮어쓴다. 끊긴 기기는 못 켠다(끊은 뜻을 지킨다)."""
        me = self.owner(owner_key)
        self.limit("sync", me, now)
        b = clean_sync(body, now, "platform", "label", "schema", "at", "bundle")
        if self.db.execute("SELECT 1 FROM sync_devices WHERE owner=? AND device=? AND revoked=1", (me, b["device"])).fetchone():
            raise BadRequest("revoked")
        t = now.timestamp()
        old = self.db.execute("SELECT rev FROM sync WHERE owner=?", (me,)).fetchone()
        rev = (old[0] if old else 0) + 1
        self.db.execute("INSERT OR REPLACE INTO sync VALUES(?,?,?,?,?,?,?)", (me, b["bundle"], rev, b["device"], b["schema"], b["at"], t))
        self._sync_join(me, b, t)
        self.db.commit()
        return {"rev": rev}

    @locked
    def sync_status(self, owner_key, device, now):
        me = self.owner(owner_key)
        self.limit("sync", me, now)
        dev = sha(_match(device, KEY))
        row = self.db.execute("SELECT rev, holder, schema FROM sync WHERE owner=?", (me,)).fetchone()
        if row is None:
            return {"on": False}
        self._sync_member(me, dev)
        self._sync_seen(me, dev, now.timestamp())
        self.db.commit()
        rev, holder, schema = row
        devices = self.db.execute("SELECT device, platform, label, seen FROM sync_devices WHERE owner=? AND revoked=0 ORDER BY added",
                                  (me,)).fetchall()
        hp, hl = next(((p, l) for d, p, l, _ in devices if d == holder), ("", ""))
        return {"on": True, "rev": rev, "schema": schema, "holder": holder == dev, "holderPlatform": hp, "holderLabel": hl,
                "devices": [{"id": d[:8], "platform": p, "label": l, "seen": int(s), "me": d == dev} for d, p, l, s in devices]}

    @locked
    def sync_put(self, owner_key, body, now):
        """올리기(홀더만). rev 는 마지막으로 맞춘 서버 rev 여야 한다."""
        me, b, (rev, holder, schema) = self._sync_on(owner_key, body, now, "rev", "schema", "at", "bundle")
        if holder != b["device"]:
            raise BadRequest("not_holder")
        if b["schema"] < schema:  # 옛 앱이 모르는 필드를 지운 채 덮어쓰지 못하게
            raise BadRequest("old_schema")
        if b["rev"] != rev:
            raise BadRequest("stale")
        t = now.timestamp()
        self.db.execute("UPDATE sync SET bundle=?, rev=?, schema=?, at=?, updated=? WHERE owner=?",
                        (b["bundle"], rev + 1, b["schema"], b["at"], t, me))
        self._sync_seen(me, b["device"], t)
        self.db.commit()
        return {"rev": rev + 1}

    @locked
    def sync_code(self, owner_key, body, now):
        """다른 기기 추가 코드(홀더만, 10분, 한 번). 새 코드를 만들면 옛 코드는 지운다."""
        me, b, (_, holder, _) = self._sync_on(owner_key, body, now)
        if holder != b["device"]:
            raise BadRequest("not_holder")
        t = now.timestamp()
        self.db.execute("DELETE FROM sync_codes WHERE owner=? OR expires<=?", (me, t))
        code = ""
        while not code or self.db.execute("SELECT 1 FROM sync_codes WHERE code=?", (code,)).fetchone():
            code = "".join(secrets.choice(CODE_CHARS) for _ in range(CODE_LEN))
        self.db.execute("INSERT INTO sync_codes VALUES(?,?,?,?)", (code, me, owner_key, t + SYNC_CODE_TTL))
        self._sync_seen(me, b["device"], t)
        self.db.commit()
        return {"code": code, "expires": int(t + SYNC_CODE_TTL)}

    @locked
    def sync_redeem(self, body, ip, now):
        """새 기기에서 코드 넣기(소유 키 없음): 소유 키 원문·사본을 받고 이 기기가 홀더. 플랫폼은 섞여도 된다(맥 ↔ 윈도우)."""
        self.limit("sync_redeem", self.ip(ip), now)
        b = clean_sync(body, now, "platform", "label", "schema")
        code = body.get("code")
        code = re.sub(r"[\s-]", "", code).upper() if isinstance(code, str) else ""
        t = now.timestamp()
        self.db.execute("DELETE FROM sync_codes WHERE expires<=?", (t,))
        self.db.commit()
        r = self.db.execute("SELECT c.owner, c.key, s.rev, s.schema, s.bundle FROM sync_codes c JOIN sync s ON s.owner = c.owner "
                            "WHERE c.code=?", (code,)).fetchone()
        if not r:
            raise BadRequest("bad_code")
        me, key, rev, schema, bundle = r
        if b["schema"] < schema:  # 코드는 남긴다(업데이트하고 10분 안에 다시 넣으면 된다)
            raise BadRequest("old_schema")
        self.db.execute("DELETE FROM sync_codes WHERE code=?", (code,))
        self.db.execute("UPDATE sync SET rev=?, holder=?, updated=? WHERE owner=?", (rev + 1, b["device"], t, me))
        self._sync_join(me, b, t)
        self.db.commit()
        return {"owner": key, "rev": rev + 1, "bundle": json.loads(bundle)}

    @locked
    def sync_take(self, owner_key, body, now):
        """여기서 이어 키우기: 사본은 그대로, 홀더만 바꾸고 rev 를 올린다(옛 홀더의 PUT 이 not_holder 로 걸린다)."""
        me, b, (rev, _, schema) = self._sync_on(owner_key, body, now, "schema")
        self._sync_member(me, b["device"])
        if b["schema"] < schema:
            raise BadRequest("old_schema")
        t = now.timestamp()
        self.db.execute("UPDATE sync SET rev=?, holder=?, updated=? WHERE owner=?", (rev + 1, b["device"], t, me))
        self._sync_seen(me, b["device"], t)
        bundle = self.db.execute("SELECT bundle FROM sync WHERE owner=?", (me,)).fetchone()[0]
        self.db.commit()
        return {"rev": rev + 1, "bundle": json.loads(bundle)}

    @locked
    def sync_revoke(self, owner_key, body, now):
        """다른 기기 끊기(홀더만, 자기 자신은 self). target 은 기기 목록 id(sha256(device) 앞 8자)."""
        me, b, (_, holder, _) = self._sync_on(owner_key, body, now)
        if holder != b["device"]:
            raise BadRequest("not_holder")
        target = _match(body.get("target"), SYNC_TARGET)
        if b["device"].startswith(target):
            raise BadRequest("self")
        if not self.db.execute("UPDATE sync_devices SET revoked=1 WHERE owner=? AND substr(device, 1, 8)=? AND revoked=0",
                               (me, target)).rowcount:
            raise KeyError(target)
        self.db.commit()
        return {}

    @locked
    def sync_off(self, owner_key):
        """연동 끄기: 사본·기기 목록·코드를 지운다(각 기기에는 마지막 로컬 저장이 남는다)."""
        me = self.owner(owner_key)
        self._drop_sync(me)
        self.db.commit()
        return {}

    # 버그 신고(1.15.2)

    @locked
    def bug_ticket(self, owner_key, body, now):
        """앱이 '버그 신고…'를 누르면: 최근에 게임을 켠 과수원에만 1시간짜리 일회용 표를 준다(웹페이지는 누가 쓰는지 모르므로)."""
        me = self.owner(owner_key)
        self.limit("bug_ticket", me, now)
        t = self._active(me, now)
        b = body if isinstance(body, dict) else {}
        app = b.get("app") if isinstance(b.get("app"), str) and re.fullmatch(r"\d{1,2}\.\d{1,2}(\.\d{1,2})?", b.get("app")) else "?"
        osv = b.get("os") if isinstance(b.get("os"), str) else ""
        osv = re.sub(r"[^\w .()-]", "", osv)[:40] or "?"
        platform = b.get("platform") if b.get("platform") in ("mac", "windows") else "mac"
        ticket = secrets.token_hex(16)
        self.db.execute("DELETE FROM bug_tickets WHERE expires<=?", (t,))
        self.db.execute("INSERT INTO bug_tickets VALUES(?,?,?,?,?,?)", (sha(ticket), me, app, osv, platform, t + BUG_TICKET_TTL))
        self.db.commit()
        return {"ticket": ticket, "expires": int(t + BUG_TICKET_TTL)}

    def _active(self, me, now):
        """14일 안에 서리 맞추기(farms.seen)가 있는 과수원만. 지금 시각(초)을 돌려준다."""
        t = now.timestamp()
        seen = self.db.execute("SELECT seen FROM farms WHERE owner=?", (me,)).fetchone()
        if not seen or seen[0] < t - BUG_ACTIVE_DAYS * 86400:
            raise BadRequest("inactive")
        return t

    def _ticket(self, ticket, now):
        if not isinstance(ticket, str) or not re.fullmatch(r"[0-9a-f]{32}", ticket):
            raise BadRequest("bad_ticket")
        r = self.db.execute("SELECT owner, app, os, platform, expires FROM bug_tickets WHERE ticket=?", (sha(ticket),)).fetchone()
        if not r or r[4] <= now.timestamp():
            raise BadRequest("bad_ticket")
        return r

    @locked
    def bug_check(self, ticket, now):
        """게시판 페이지가 글을 쓰기 전에 표가 살아 있는지 본다."""
        r = self._ticket(ticket, now)
        return {"ok": True, "expires": int(r[4]), "app": r[1], "platform": r[3]}

    @locked
    def bug_create(self, body, ip, now):
        """글(5~2000자)과 이미지(최대 3장, JPEG·PNG, data URL)를 받는다. 표는 한 번 쓰면 지운다."""
        self.limit("bug", self.ip(ip), now)
        b = body if isinstance(body, dict) else {}
        owner, app, osv, platform, _ = self._ticket(b.get("ticket"), now)
        t = now.timestamp()
        if self.db.execute("SELECT COUNT(*) FROM bugs WHERE owner=? AND created>?", (owner, t - 86400)).fetchone()[0] >= BUG_PER_DAY:
            raise RateLimited()
        text = b.get("text") if isinstance(b.get("text"), str) else ""
        text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", text).strip()
        if not BUG_TEXT[0] <= len(text) <= BUG_TEXT[1]:
            raise BadRequest("bad_text")
        raw = b.get("images") or []
        if not isinstance(raw, list) or len(raw) > BUG_IMAGES:
            raise BadRequest("bad_image")
        images = []
        for u in raw:
            m = re.fullmatch(r"data:(image/(?:jpeg|png));base64,([A-Za-z0-9+/=]+)", u) if isinstance(u, str) else None
            if not m:
                raise BadRequest("bad_image")
            try:
                data = base64.b64decode(m.group(2), validate=True)
            except ValueError:
                raise BadRequest("bad_image")
            magic = data[:3] == b"\xff\xd8\xff" if m.group(1) == "image/jpeg" else data[:8] == b"\x89PNG\r\n\x1a\n"
            if not magic or len(data) > BUG_IMAGE_MAX:
                raise BadRequest("bad_image")
            images.append((m.group(1), data))
        bid = secrets.token_hex(6)
        self.db.execute("DELETE FROM bug_tickets WHERE ticket=?", (sha(b["ticket"]),))
        self.db.execute("INSERT INTO bugs(id, owner, created, app, os, platform, text, images) VALUES(?,?,?,?,?,?,?,?)",
                        (bid, owner, t, app, osv, platform, text, len(images)))
        for n, (mime, data) in enumerate(images):
            self.db.execute("INSERT INTO bug_images VALUES(?,?,?,?)", (bid, n, mime, sqlite3.Binary(data)))
        self.db.commit()
        return {"id": bid}

    @locked
    def bug_list(self, limit=100):
        """운영자용(통계 토큰). 소유 키 해시 앞 8자로 같은 사람의 신고를 묶어 볼 수 있다."""
        rows = self.db.execute("SELECT id, owner, created, app, os, platform, text, images, done FROM bugs ORDER BY created DESC LIMIT ?",
                               (limit,)).fetchall()
        return {"bugs": [{"id": r[0], "who": r[1][:8], "created": int(r[2]), "app": r[3], "os": r[4], "platform": r[5],
                          "text": r[6], "images": r[7], "done": bool(r[8])} for r in rows]}

    @locked
    def bug_image(self, bid, n):
        r = self.db.execute("SELECT mime, data FROM bug_images WHERE bug=? AND n=?", (bid, n)).fetchone()
        if not r:
            raise KeyError(bid)
        return r[0], bytes(r[1])

    @locked
    def bug_done(self, bid, done=True):
        self.db.execute("UPDATE bugs SET done=? WHERE id=?", (1 if done else 0, bid))
        self.db.commit()
        return {}

    def _drop_bugs(self, owner):
        self.db.execute("DELETE FROM bug_images WHERE bug IN (SELECT id FROM bugs WHERE owner=?)", (owner,))
        self.db.execute("DELETE FROM bugs WHERE owner=?", (owner,))
        self.db.execute("DELETE FROM bug_tickets WHERE owner=?", (owner,))

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
                                     "wake": False, "commands": [], "saved": 0.0, "cond": threading.Condition(self.lock), "results": {}, "asking": 0,
                                     "server_results": [], "discover": None}  # 1.14 대리로 처리한 결과·찾기(Mac 이 잠든 동안)
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
            for table in ("relay", "relay_queue", "relay_link", "relay_effects"):  # 1.14 예약·대리 연결·대리로 한 일도
                self.board.db.execute("DELETE FROM %s WHERE device=?" % table, (device,))
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
            rs = body.get("results")
            e["results"] = {r["id"]: r for r in rs if isinstance(r, dict) and isinstance(r.get("id"), str)} if isinstance(rs, list) else {}
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

    def _seen(self, e):
        """폰에 돌려주는 모양(잠근 채로 부른다)"""
        t = time.time()
        state = json.loads(e["state"]) if e["state"] else None
        e["server_results"] = [(at, r) for at, r in e["server_results"] if t - at < RELAY_SERVER_RESULT_TTL]
        if state is not None and e["server_results"]:  # 1.14 서버가 대리로 처리한 결과도 Mac 의 결과와 같은 자리에
            state["results"] = (state.get("results") if isinstance(state.get("results"), list) else []) + [r for _, r in e["server_results"]]
        return {"state": state, "stateAt": e["state_at"] or None,
                "macSeen": t if e["waiting"] else (e["mac_seen"] or None), "online": self._online(e, t), "now": t}

    def _out(self, device, e, now):
        """폰에 돌려줄 모양 + Mac 이 잠들었으면(1.14) 예약 대기 수, 대리 연결이 있으면 서버가 만든 이웃 목록·요청·찾기를 덧붙인다"""
        with self.lock:
            s, discover = self._seen(e), e["discover"]
        st = s["state"]
        if s["online"] or st is None:
            return s
        with self.board.lock:
            st["queued"] = self.board.db.execute("SELECT COUNT(*) FROM relay_queue WHERE device=? AND at>?",
                                                 (device, now.timestamp() - RELAY_QUEUE_KEEP)).fetchone()[0]
        owner = self._linked(device)
        v = self.board.proxy_view(Owner(owner), now) if owner else None
        if v:
            st.update(neighbors=v["neighbors"], requests=v["requests"], prefs=v["prefs"], thanks=v["thanks"], myCode=v["code"],
                      myName=v["me"]["name"])
            if discover is not None:
                st["discover"] = discover
        return s

    def _linked(self, device):
        with self.board.lock:
            r = self.board.db.execute("SELECT owner FROM relay_link WHERE device=?", (device,)).fetchone()
        return r[0] if r else None

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
            online = self._online(e, t)
            if online:
                return self._seen(e)
        return self._out(device, e, now)

    def command(self, auth, body, now, ip=""):
        device = self.phone(auth)
        self.board.limit("command", device, now)
        if not isinstance(body, dict):
            raise BadRequest()
        cid, action = body.get("id"), body.get("action")
        if not isinstance(cid, str) or not CMD_ID.fullmatch(cid) or action not in ACTIONS:
            raise BadRequest()
        cmd = {"id": cid, "action": action}
        for k, ok in COMMANDS[action].items():  # 정한 칸만 넘긴다(1.12 부터 칸 번호는 넓힌 칸까지, 실제 칸 수 안인지는 Mac 이 본다)
            if not ok(body.get(k)):
                raise BadRequest()
            if k in body:
                cmd[k] = body[k]
        with self.lock:
            e = self._entry(device)
            t = time.time()
            asleep = not self._online(e, t)
        if asleep:  # 1.14: 내 과수원 명령은 예약, 이웃 명령은 대리(연결이 있으면), 서리는 깨어 있을 때만
            if action in MINE:
                return self._queue(device, e, cmd, now)
            if action.startswith("nb_") and self._linked(device):
                return self._proxy(device, e, cmd, now, ip)
            raise BadRequest("mac_asleep")
        with self.lock:
            t = time.time()
            e["commands"] = [c for c in e["commands"] if t - c["at"] < RELAY_CMD_TTL]
            if len(e["commands"]) >= RELAY_QUEUE:
                raise RateLimited()
            cmd["at"] = t
            e["commands"].append(cmd)
            e["cond"].notify_all()
            # 1.7.1: Mac 이 처리해 결과를 올릴 때까지 잠깐 기다렸다가 새 상태와 함께 돌려준다(폰이 한 번에 받는다)
            # 기다리는 수에도 상한을 둔다(스레드 고갈 방지). 넘으면 결과 없이 바로 돌려주고 폰이 1초 뒤 다시 묻는다.
            if e["asking"] < RELAY_ASKERS and self.waiting < RELAY_WAITERS_ALL:
                e["asking"] += 1
                self.waiting += 1
                try:
                    end = time.monotonic() + RELAY_RESULT
                    while cid not in e["results"] and time.monotonic() < end:
                        e["cond"].wait(end - time.monotonic())
                finally:
                    e["asking"] -= 1
                    self.waiting -= 1
            return {"ok": True, "result": e["results"].get(cid), **self._seen(e)}

    def _queue(self, device, e, cmd, now):
        """1단계 예약(1.14): 누른 시각과 함께 쌓는다. Mac 이 깨어나 따라잡기 중 그 시각에 끼워 실행한다. 같은 id 는 한 번만."""
        t = now.timestamp()
        with self.board.lock:
            db = self.board.db
            db.execute("DELETE FROM relay_queue WHERE device=? AND at<=?", (device, t - RELAY_QUEUE_KEEP))
            r = db.execute("SELECT at FROM relay_queue WHERE device=? AND id=?", (device, cmd["id"])).fetchone()
            if r is None:
                if db.execute("SELECT COUNT(*) FROM relay_queue WHERE device=?", (device,)).fetchone()[0] >= RELAY_QUEUE_MAX:
                    db.commit()
                    raise RateLimited()
                db.execute("INSERT INTO relay_queue VALUES(?,?,?,?,?)", (device, cmd["id"], cmd["action"],
                           json.dumps({k: v for k, v in cmd.items() if k not in ("id", "action")}), t))
            db.commit()
        return {"ok": True, "queued": True, "at": r[0] if r else t, "result": None, **self._out(device, e, now)}

    def _proxy(self, device, e, cmd, now, ip):
        """2단계 대리(1.14): Mac 이 잠든 동안 이웃 명령을 서버가 그 과수원으로 바로 처리한다. 결과는 바로 돌려주고 상태 results[] 에도
        섞는다. 내 쪽에 남는 변화(선물·바구니 과일, 출장 일꾼, 보낸 횟수)는 relay_effects 에 쌓아 Mac 이 깨어나면 반영한다."""
        b, action, cid = self.board, cmd["action"], cmd["id"]
        me = Owner(self._linked(device))
        state = json.loads(e["state"]) if e["state"] else {}
        effect, discover = None, None
        try:
            farm = b.proxy_farm(me)
            if farm is None:
                raise BadRequest("no_farm")
            look = farm["look"]

            def worker(role=None):  # 보내는 일꾼 모습: 과수원 모습(look)에서, 없으면 기본 모습
                return next((w for w in look.get("workers", []) if role is None or w[0] == role), [role or "caretaker", 0, 0, 0])
            if action in ("nb_gift", "nb_basket"):  # 그새 창고(마지막으로 알린 것 − 아직 반영 안 된 대리 선물)에 없으면 막는다
                have = farm["crate"].get(cmd["fruit"], 0) - self._spent(device, cmd["fruit"])
                if have < 1:
                    raise BadRequest("no_fruit")
            if action in ("nb_help", "nb_gift"):
                kind = action[3:]
                b.neighbor_send(me, kind, {"id": cmd["target"], "stamp": cmd["stamp"], "worker": worker(),
                                           **({"fruit": cmd["fruit"]} if kind == "gift" else {})}, now)
                out, effect = {}, {"kind": kind, **({"fruit": cmd["fruit"], "count": 1} if kind == "gift" else {})}  # help: 보낸 횟수만
            elif action == "nb_dispatch":
                level = next((w.get("level") for w in state.get("workers") or [] if isinstance(w, dict) and w.get("role") == cmd["role"]), 1)
                level = max(0, min(level if isinstance(level, int) and not isinstance(level, bool) else 1, DISPATCH_LEVEL_CAP))
                out = b.neighbor_carry(me, "dispatch", {"id": cmd["target"], "role": cmd["role"], "level": level,
                                                       "worker": worker(cmd["role"])}, now)
                effect = {"kind": "dispatch", "role": cmd["role"]}  # 출장 4시간 동안 그 일꾼 자리가 빈다
            elif action == "nb_basket":
                count = min(cmd["count"], have)
                out = b.neighbor_carry(me, "basket", {"id": cmd["target"], "fruit": cmd["fruit"], "count": count, "stamp": cmd["stamp"],
                                                     "worker": worker()}, now)
                effect = {"kind": "basket", "fruit": cmd["fruit"], "count": out["count"]}
            elif action == "nb_sapling":
                out = b.neighbor_carry(me, "sapling", {"id": cmd["target"], "kind": cmd["kind"], "worker": worker()}, now)
                effect = {"kind": "sapling"}
            elif action == "nb_add":
                out = b.neighbor_add(me, {"code": cmd["code"]}, ip or "0.0.0.0", now)
            elif action == "nb_name":
                out = b.neighbor_name(me, {"name": cmd["name"]}, now)
            elif action == "nb_request":
                out = b.neighbor_request(me, {"id": cmd["target"], "stamp": cmd.get("stamp")}, now)
            elif action == "nb_discover":
                out = discover = b.discover(me, cmd, now)
            else:  # nb_accept·nb_decline·nb_block
                out = b.neighbor_answer(me, action[3:], {"id": cmd["target"]}, now)
            result = {"id": cid, "ok": True, **{k: out[k] for k in ("count", "added", "name") if k in out}}
        except (BadRequest, RateLimited, KeyError) as x:
            code = x.code if isinstance(x, BadRequest) else "rate_limited" if isinstance(x, RateLimited) else "not_found"
            result = {"id": cid, "ok": False, "reason": "poor" if code in PROXY_POOR else "unavailable" if code in PROXY_MESSAGES else "failed",
                      "message": PROXY_MESSAGES.get(code, "보내지 못했어요"), "code": code}
        t = now.timestamp()
        if effect:
            with b.lock:
                b.db.execute("INSERT INTO relay_effects VALUES(?,?,?,?,?)", (device, secrets.token_hex(8), effect.pop("kind"), json.dumps(effect), t))
                b.db.commit()
        with self.lock:
            e["server_results"] = (e["server_results"] + [(time.time(), result)])[-RELAY_SERVER_RESULTS:]
            if discover is not None:
                e["discover"] = discover
        return {"ok": True, "result": result, **self._out(device, e, now)}

    def _spent(self, device, fruit):
        """대리로 보내고 Mac 이 아직 반영하지 않은 그 과일 개수"""
        with self.board.lock:
            return sum(json.loads(body).get("count", 0) for (body,) in self.board.db.execute(
                "SELECT body FROM relay_effects WHERE device=? AND kind IN ('gift', 'basket')", (device,))
                if json.loads(body).get("fruit") == fruit)

    def link(self, auth, owner_key, now):
        """2단계 대리 등록(1.14): Mac 이 폰으로 보기를 켤 때마다. 소유 키는 해시만 둔다(다른 표와 같은 소유자 값)."""
        device = self.mac(auth)
        owner = Board.owner(owner_key)
        self.board.limit("pair", device, now)
        with self.board.lock:
            self.board.db.execute("INSERT OR REPLACE INTO relay_link VALUES(?,?,?)", (device, owner, now.timestamp()))
            self.board.db.commit()
        return {"ok": True}

    def queue(self, auth, now):
        """Mac 이 깨어나면 받는다: 예약 명령(오래된 것부터, 72시간 지난 것은 지운다)과 대리로 한 일의 내 쪽 변화"""
        device = self.mac(auth)
        self.board.limit("queue", device, now)
        with self.board.lock:
            db = self.board.db
            db.execute("DELETE FROM relay_queue WHERE device=? AND at<=?", (device, now.timestamp() - RELAY_QUEUE_KEEP))
            db.commit()
            return {"commands": [{"id": i, "action": a, **json.loads(body), "at": at} for i, a, body, at in
                                 db.execute("SELECT id, action, body, at FROM relay_queue WHERE device=? ORDER BY at, rowid", (device,))],
                    "effects": [{"id": i, "kind": k, **json.loads(body), "at": at} for i, k, body, at in
                                db.execute("SELECT id, kind, body, at FROM relay_effects WHERE device=? ORDER BY at, rowid", (device,))]}

    def queue_done(self, auth, body, now):
        """{ids}: 반영한 예약 명령·변화를 지운다"""
        device = self.mac(auth)
        self.board.limit("queue", device, now)
        ids = body.get("ids") if isinstance(body, dict) else None
        if not isinstance(ids, list) or len(ids) > 200 or not all(isinstance(i, str) and CMD_ID.fullmatch(i) for i in ids):
            raise BadRequest()
        with self.board.lock:
            for table in ("relay_queue", "relay_effects"):
                self.board.db.executemany("DELETE FROM %s WHERE device=? AND id=?" % table, [(device, i) for i in ids])
            self.board.db.commit()
        return {"ok": True}

    def maintain(self, now):
        t = now.timestamp()
        with self.board.lock:
            self.board.db.execute("DELETE FROM relay WHERE seen < ?", (t - RELAY_KEEP_DAYS * 86400,))
            self.board.db.execute("DELETE FROM relay_queue WHERE at <= ?", (t - RELAY_QUEUE_KEEP,))
            for table in ("relay_link", "relay_effects"):  # 1.14: 페어링이 지워진 기기
                self.board.db.execute("DELETE FROM %s WHERE device NOT IN (SELECT device FROM relay)" % table)
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
                    return self.relay(method, parts[1:], q, owner, now)
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
                    b = self.body()
                    return self.send(200, board.toggle_star(parts[1], b.get("voter"), self.client_ip(), now, b.get("ticket")))
                if method == "POST" and len(parts) == 3 and parts[0] == "posts" and parts[2] == "stamp":  # 1.17
                    return self.send(200, board.stamp(parts[1], self.body(), self.client_ip(), now))
                if method == "POST" and parts == ["brag", "ticket"]:
                    return self.send(200, board.brag_ticket(owner, now))
                if method == "GET" and len(parts) == 2 and parts[0] == "badges":
                    return self.send(200, board.badge_count(parts[1]))
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
                if parts[:1] == ["raid"]:
                    return self.raid(method, parts[1:], owner, now)
                if parts[:1] == ["neighbors"]:
                    return self.neighbors(method, parts[1:], q, owner, now)
                if parts[:1] == ["sync"]:
                    return self.sync(method, parts[1:], q, owner, now)
                if parts[:1] == ["bugs"]:
                    return self.bugs(method, parts[1:], q, owner, now)
                if method == "GET" and parts == ["me"]:
                    return self.send(200, board.me(owner, now))
                if method == "DELETE" and parts == ["me", "posts"]:  # 1.11.1 게시물만
                    return self.send(200, {"deleted": board.delete_posts(owner)})
                if method == "DELETE" and parts == ["me"]:
                    return self.send(200, {"deleted": board.delete_mine(owner)})
                return self.send(404, {"error": "not_found"})
            except BadRequest as e:
                return self.send({"unauthorized": 401, "mac_asleep": 409, "conflict": 409, "too_large": 413, "implausible": 422,
                                  # 서리
                                  "too_new": 409, "busy": 409, "no_raids_left": 409, "guarded": 409, "empty": 409, "no_farm": 409,
                                  # 이웃(bad_fruit 은 422)
                                  "bad_code": 409, "full": 409, "already": 409, "done_today": 409,
                                  # 쩔(1.13, bad_kind 는 422)
                                  "not_junior": 409, "taken_today": 409, "taken_week": 409, "holding": 409,
                                  # 이웃 요청(1.14)
                                  "pending": 409, "cooldown": 409, "closed": 409,
                                  # 기기 연동(1.15.1, bad_clock 은 422)
                                  "not_holder": 409, "stale": 409, "old_schema": 409, "revoked": 409, "self": 409, "off": 404,
                                  # 버그 신고(1.15.2, bad_text·bad_image 는 422)
                                  "inactive": 403, "bad_ticket": 409, "forbidden": 403,
                                  }.get(e.code, 422), {"error": e.code})
            except RateLimited:
                return self.send(429, {"error": "rate_limited"})
            except KeyError:
                return self.send(404, {"error": "not_found"})
            except ValueError:
                return self.send(422, {"error": "bad_data"})

        def relay(self, method, parts, q, owner, now):
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
                return self.send(200, relay.command(auth, self.body(), now, self.client_ip()))
            # 1.14 예약·대리
            if method == "GET" and parts == ["queue"]:
                return self.send(200, relay.queue(auth, now))
            if method == "POST" and parts == ["queue", "done"]:
                return self.send(200, relay.queue_done(auth, self.body(), now))
            if method == "POST" and parts == ["link"]:
                return self.send(200, relay.link(auth, owner, now))
            return self.send(404, {"error": "not_found"})

        def raid(self, method, parts, owner, now):
            if method == "POST" and parts == ["status"]:
                return self.send(200, board.raid_status(owner, self.body(), self.client_ip(), now, self.headers.get("X-Sync-Device")))
            if method == "GET" and parts == ["targets"]:
                return self.send(200, board.raid_targets(owner, now))
            if method == "POST" and parts == []:
                return self.send(200, board.raid(owner, self.body(), self.client_ip(), now))
            return self.send(404, {"error": "not_found"})

        def neighbors(self, method, parts, q, owner, now):
            if method == "GET" and parts == []:
                return self.send(200, board.neighbor_list(owner, now))
            if method == "GET" and parts == ["discover"]:  # 1.14 이웃 찾기·요청
                return self.send(200, board.discover(owner, q, now))
            if method == "POST" and parts == ["request"]:
                return self.send(200, board.neighbor_request(owner, self.body(), now))
            if method == "POST" and parts in (["accept"], ["decline"], ["block"]):
                return self.send(200, board.neighbor_answer(owner, parts[0], self.body(), now))
            if method == "POST" and parts == ["prefs"]:
                return self.send(200, board.neighbor_prefs(owner, self.body(), now))
            if method == "POST" and parts == ["code"]:
                return self.send(200, board.neighbor_code(owner, self.body(), now))
            if method == "POST" and parts == ["add"]:
                return self.send(200, board.neighbor_add(owner, self.body(), self.client_ip(), now))
            if method == "POST" and parts == ["remove"]:
                return self.send(200, board.neighbor_remove(owner, self.body(), now))
            if method == "POST" and parts in (["help"], ["gift"]):
                return self.send(200, board.neighbor_send(owner, parts[0], self.body(), now))
            if method == "POST" and parts in (["dispatch"], ["basket"], ["sapling"]):  # 1.13 쩔
                return self.send(200, board.neighbor_carry(owner, parts[0], self.body(), now))
            if method == "POST" and parts == ["name"]:
                return self.send(200, board.neighbor_name(owner, self.body(), now))
            return self.send(404, {"error": "not_found"})

        def bugs(self, method, parts, q, owner, now):  # 1.15.2 버그 신고
            if method == "POST" and parts == ["ticket"]:
                return self.send(200, board.bug_ticket(owner, self.body(), now))
            if method == "GET" and parts == ["ticket"]:
                return self.send(200, board.bug_check(q.get("t"), now))
            if method == "POST" and parts == []:
                return self.send(200, board.bug_create(self.body(BUG_MAX), self.client_ip(), now))
            # 아래는 운영자만(통계 토큰)
            auth = self.headers.get("Authorization") or ""
            if not STATS_TOKEN or not hmac.compare_digest(auth.encode(), ("Bearer " + STATS_TOKEN).encode()):
                raise BadRequest("forbidden")
            if method == "GET" and parts == []:
                return self.send(200, board.bug_list())
            if method == "GET" and len(parts) == 2 and parts[1].isdigit():
                mime, data = board.bug_image(parts[0], int(parts[1]))
                self.send_response(200)
                self.cors()
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "private, no-store")
                self.end_headers()
                self.wfile.write(data)
                return
            if method == "POST" and len(parts) == 2 and parts[1] == "done":
                return self.send(200, board.bug_done(parts[0], bool(self.body().get("done", True))))
            return self.send(404, {"error": "not_found"})

        def sync(self, method, parts, q, owner, now):  # 1.15.1 기기 연동: 본문은 SYNC_MAX 까지
            if method == "GET" and parts == ["status"]:
                return self.send(200, board.sync_status(owner, q.get("device"), now))
            if method == "DELETE" and parts == []:
                return self.send(200, board.sync_off(owner))
            if method == "POST" and parts == ["redeem"]:
                return self.send(200, board.sync_redeem(self.body(SYNC_MAX), self.client_ip(), now))
            act = {("POST", "enable"): board.sync_enable, ("PUT", ""): board.sync_put, ("POST", "code"): board.sync_code,
                   ("POST", "take"): board.sync_take, ("POST", "revoke"): board.sync_revoke}.get((method, "/".join(parts)))
            if act is None:
                return self.send(404, {"error": "not_found"})
            return self.send(200, act(owner, self.body(SYNC_MAX), now))

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

        def do_PUT(self):  # 1.15.1 PUT sync
            self.route("PUT")

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


def fast_raids():
    """--raid-fast YES(로컬 확인·자체 점검 전용): 베타 때처럼 새 키·초보 보호·창고 20%·하루 3번·손실 상한·당한 뒤 개 없이
    바로 서리하고, 작전은 6~10초. 자체 점검을 하루에 여러 번 돌려도 막히지 않는다."""
    global NEW_KEY, NEWBIE, MIN_FILL, MIN_LEVEL, BETA_OPEN
    NEW_KEY, NEWBIE, MIN_FILL, MIN_LEVEL, BETA_OPEN = 0, 0, 0, 0, True
    RAID_PLANS.update(light=6, normal=8, deep=10)


def main(argv):
    global PREFIX, BOARD_URL, CORS_ORIGIN, STATS_TOKEN
    STATS_TOKEN = os.environ.get("STATS_TOKEN", "")
    args = dict(zip(argv[1::2], argv[2::2])) if argv[1:2] != ["admin"] else {}
    # 회사 인프라는 Data dir 을 IX_DATA_DIR 로, 포트를 PORT 로 넣어 준다
    data = os.path.expanduser(os.environ.get("IX_DATA_DIR") or os.environ.get("BRAG_DATA") or args.get("--data") or "~/sites-data/lemondesk")
    PREFIX = args.get("--prefix", PREFIX)
    BOARD_URL = args.get("--board", BOARD_URL)
    CORS_ORIGIN = args.get("--cors", CORS_ORIGIN)
    if args.get("--raid-fast") == "YES":  # 로컬 확인 전용(자체 점검·캡처)
        fast_raids()
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
            board.db.execute("DELETE FROM stamps WHERE post=?", (pid,))
            board.db.execute("DELETE FROM reports WHERE post=?", (pid,))
            board.db.execute("DELETE FROM highlights WHERE post=?", (pid,))
            board.db.execute("DELETE FROM posts WHERE id=?", (pid,))
            board.db.commit()
        elif cmd == "clear-name":  # 이름에 띄어쓰기가 있어도 따옴표 없이 된다
            print(board.clear_name(" ".join(argv[3:])), "cleared")
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
