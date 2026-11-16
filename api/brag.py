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

실행: python3 brag.py [--data DIR] [--port 8891] [--host 127.0.0.1] [--prefix /lemondesk/api/] [--board URL] [--cors 출처] [--static SITE_DIR]
  --static 은 로컬 확인용: /lemondesk/<경로> 를 SITE_DIR 에서 준다
  --raid-fast YES 는 로컬 확인용: 베타 때처럼 새 키·초보 보호·창고 20%·하루 3번·손실 상한·당한 뒤 개 없이 바로 서리하고, 작전이 6~10초
  회사 인프라: python brag.py --host 0.0.0.0 --prefix /api/ --board https://lemondesk.interaction.hnine.com/brag/ --cors https://lemondesk.interaction.hnine.com
              (PORT, IX_DATA_DIR 은 인프라가 넣어 준다)
관리: python3 brag.py admin list|hide ID|unhide ID|delete ID|clear-name 과수원 이름
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
          "pair": (30, 3600), "state": (1800, 3600), "wait": (1200, 3600), "view": (3600, 3600), "command": (600, 3600),
          # 서리(1.8): 소유 키당, raid_ip·farm_new 는 IP 당(가짜 키를 많이 만들어 터는 것을 막는다)
          "raid_status": (240, 3600), "raid_targets": (120, 3600), "raid": (30, 3600), "raid_ip": (120, 3600), "farm_new": (30, 3600),
          # ponytail: 주인이 깨어 있다는 신호(팔기·관리 창)는 시간당 4번까지만 들킴으로 친다(늘 깨어 있는 척해 서리를 다 막지 못하게)
          "raid_active": (4, 3600),
          # 이웃(1.11): 소유 키당, neighbor_add_ip 는 IP 당(키를 바꿔 가며 코드를 마구 넣어 보지 못하게)
          "neighbors": (120, 3600), "neighbor_code": (10, 3600), "neighbor_add": (20, 3600), "neighbor_add_ip": (30, 3600),
          "neighbor_send": (60, 3600), "neighbor_name": (10, 3600)}
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
RELAY_ONLINE = 90            # Mac 이 이 초 안에 왔으면(또는 기다리는 중이면) 깨어 있음
RELAY_FRESH = 3              # 폰이 처음 열 때 Mac 의 새 상태를 기다리는 초
RELAY_CMD_TTL = 30           # 명령을 Mac 이 가져가지 않으면 버리는 초
RELAY_QUEUE = 10
RELAY_KEEP_DAYS = 90         # 쓰지 않는 페어링 보관
RELAY_RESULT = 3             # 폰 명령이 Mac 의 처리 결과를 기다리는 초(넘으면 폰이 다시 묻는다)
RELAY_ASKERS = 4             # 한 기기에서 동시에 결과를 기다릴 수 있는 명령 수
ACTIONS = {"sell", "plant", "unlock", "hire", "crate", "hire2", "replant", "care"}  # hire2·replant: 1.7.1, care: 1.13 밭 치우기

# 자랑 게시판 조작 방지(1.7.1): 올린 숫자가 게임에서 나올 수 있는 범위인지 본다. 앱 Balance.swift 와 같은 값(test_brag 가 대조한다).
# 게임 저장은 서버로 옮기지 않는다. 가능한 최대치 바로 아래로 꾸민 숫자는 못 막고, 신고·관리 명령이 나머지를 맡는다.
WEEK = 7 * 86400
MAX_TREES = 10               # 앞 10칸: 이웃 모습(look)·자랑 게시물의 나무 줄 상한(1.12 부터 땅은 끝이 없고 앱은 앞 10칸만 보낸다)
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
    if card["earned"] > card["sold"] * MAX_FRUIT_PRICE * boost("planter", PRICE_PER_LEVEL) * SEASON_PRICE * SLACK + extra:
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
MAX_NEIGHBORS = 10
NEIGHBOR_DOG, MAX_NEIGHBOR_DOGS = 0.05, 3  # 개가 있는 이웃 한 곳마다 서리 −5%(최대 3곳, GUARD_MAX 안에서)
CODE_CHARS, CODE_LEN = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789", 6  # I·O·0·1 없음. 화면에는 ABC-DEF
STAMPS = {"heart", "note", "star"}       # 고마워요·반가워요·멋져요(자유 글은 없다)
SEASONS = {"spring", "summer", "autumn", "winter"}
TREE_LOOK = (KINDS, (0, 7))                    # 과수원 모습의 나무: 종류, 자란 단계
WORKER_LOOK = (ROLES, (0, 1), (0, 4), (0, 6))  # 일꾼: 역할, variant, 장비 단계, 염색
LOOK_MAX = 2048
INBOX = 20                   # raid/status 한 번에 주는 받은 돕기·선물 수

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
    if b.get("arch") not in ARCHES or b.get("platform", "mac") not in PLATFORMS:
        raise BadRequest()
    lang = b.get("lang") or ""
    return {"install": install, "day": day, "version": _match(b.get("version"), VERSION_RE), "os": _match(b.get("os"), VERSION_RE),
            "lang": _match(lang, LANG_RE) if lang else "", "arch": b["arch"],
            "minutes": _int(b.get("minutes"), 0, 1440), "opens": _int(b.get("opens"), 0, 10000),
            "sales": _int(b.get("sales"), 0, 100000), "kinds": _int(b.get("kinds"), 0, 13), "platform": b.get("platform", "mac"),
            # 1.11: 이웃 수, 최근 7일 안에 서리당했는지(0/1). 옛 앱은 안 보내므로 0
            "nb": _int(b.get("nb", 0), 0, MAX_NEIGHBORS), "rb": _int(b.get("rb", 0), 0, 1)}


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


def clean_nickname(v):
    if not isinstance(v, str):
        raise BadRequest("bad_nickname")
    n = " ".join(v.split())
    flat = n.replace(" ", "").lower()
    if not 1 <= len(n) <= 12 or URLISH.search(n) or any(b in flat for b in BANNED) or any(ord(c) < 32 for c in n):
        raise BadRequest("bad_nickname")
    return n


def clean_post(body, baskets=0, dispatches=0):
    """앱이 보낸 내용을 검사해 저장할 형태로. 범위를 벗어나면 BadRequest."""
    if not isinstance(body, dict):
        raise BadRequest()
    card, orch = body.get("card"), body.get("orchard")
    if not isinstance(card, dict) or not isinstance(orch, dict):
        raise BadRequest()
    trees = orch.get("trees")
    workers = orch.get("workers")
    if not isinstance(trees, list) or len(trees) > MAX_TREES or any(t not in KINDS for t in trees):
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
                                 ("farms", "seedling", "INTEGER NOT NULL DEFAULT 0")):
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
        # 1.13: 이번 주 받은 바구니 과일 수·출장 수만큼 조작 방지 상한을 넓힌다
        baskets, dispatches = self.db.execute(
            "SELECT COALESCE(SUM(CASE WHEN kind='basket' THEN count END), 0), COALESCE(SUM(kind='dispatch'), 0) FROM carries "
            "WHERE receiver=? AND kind IN ('basket', 'dispatch') AND end>=?", (owner, week_start(now))).fetchone()
        post = clean_post(body, baskets, dispatches)
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
    def _drop_posts(self, owner):
        """내 게시물과 거기 받은 별·신고, 하이라이트 기록(잠금 안에서 부른다)."""
        ids = [r[0] for r in self.db.execute("SELECT id FROM posts WHERE owner=?", (owner,))]
        for pid in ids:
            self.db.execute("DELETE FROM stars WHERE post=?", (pid,))
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
        self.db.execute("INSERT INTO pings(install, day, version, os, lang, arch, minutes, opens, sales, kinds, received, platform, nb, rb) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(install, day) DO UPDATE SET "
                        "version=excluded.version, os=excluded.os, lang=excluded.lang, arch=excluded.arch, platform=excluded.platform, "
                        "minutes=max(minutes, excluded.minutes), opens=max(opens, excluded.opens), "
                        "sales=max(sales, excluded.sales), kinds=excluded.kinds, received=excluded.received, "
                        "nb=max(nb, excluded.nb), rb=max(rb, excluded.rb)",
                        (inst, p["day"], p["version"], p["os"], p["lang"], p["arch"], p["minutes"], p["opens"],
                         p["sales"], p["kinds"], now.timestamp(), p["platform"], p["nb"], p["rb"]))
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

        def best(value):  # 1.7.1: 별을 하나라도 받은 게시물에서만(사람 눈을 한 번 거친다)
            c = [p for p in posts if value(p) > 0 and p["stars"] > 0]
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
            # 서리: 8주 소식 없는 설치와 8주 지난 기록
            self.db.execute("DELETE FROM farms WHERE seen < ?", (t - KEEP_WEEKS * WEEK,))
            self.db.execute("DELETE FROM raids WHERE end < ?", (t - KEEP_WEEKS * WEEK,))
            # 이웃: 8주 지난 돕기·선물 기록, 과수원이 지워진 설치의 코드와 이웃 관계(빈자리가 상한을 차지하지 않게)
            self.db.execute("DELETE FROM gifts WHERE created < ?", (t - KEEP_WEEKS * WEEK,))
            self.db.execute("DELETE FROM carries WHERE end < ?", (t - KEEP_WEEKS * WEEK,))  # 1.13 쩔 기록
            self.db.execute("DELETE FROM codes WHERE owner NOT IN (SELECT owner FROM farms)")
            self.db.execute("DELETE FROM neighbors WHERE owner NOT IN (SELECT owner FROM farms) OR other NOT IN (SELECT owner FROM farms)")
            self.db.commit()

    # 서리 (1.8). 한 사람(raider)은 당한 쪽 응답 어디에도 넣지 않는다.

    FARM = "SELECT owner, cap, crate, fences, level, first, seen, guard, lost_day, lost, dogs, best, thanks, name, seedling FROM farms"

    @staticmethod
    def _farm_row(r):
        return {"owner": r[0], "cap": r[1], "crate": json.loads(r[2]), "fences": r[3], "level": r[4], "first": r[5],
                "seen": r[6], "guard": r[7], "lost_day": r[8], "lost": r[9], "dogs": r[10], "best": r[11], "thanks": r[12], "name": r[13], "seedling": r[14]}

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
    def raid_status(self, owner_key, body, ip, now):
        """창고 상태 알리기(앱이 켤 때·팔 때·관리 창을 열 때·20% 경계·30분마다, 일꾼이 나가 있으면 1분마다).
        active: 주인이 방금 팔았거나 창을 열었다 → 지금 내 밭과 이웃 밭(1.11)에 있는 서리꾼이 들킨다.
        look(1.11): 과수원 모습. ack 에는 반영한 서리·돕기·선물·되찾은 것 id 를 함께 넣는다."""
        me = self.owner(owner_key)
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
        return self._raid_view(me, now)

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
                "me": {"name": mine["name"] or None, "seed": self._seed(me)}}

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
                                     "wake": False, "commands": [], "saved": 0.0, "cond": threading.Condition(self.lock), "results": {}, "asking": 0}
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
        return {"state": json.loads(e["state"]) if e["state"] else None, "stateAt": e["state_at"] or None,
                "macSeen": t if e["waiting"] else (e["mac_seen"] or None), "online": self._online(e, t), "now": t}

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
            return self._seen(e)

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
        if action in ("hire", "hire2"):
            if body.get("role") not in ROLES:
                raise BadRequest()
            cmd["role"] = body["role"]
        if action == "replant":
            plot = body.get("plot")
            # 1.12: 넓힌 칸도. 실제 칸 수 안인지는 Mac 이 본다(서버는 칸 수를 모른다)
            if body.get("kind") not in KINDS or isinstance(plot, bool) or not isinstance(plot, int) or not 0 <= plot < MAX_PLOTS:
                raise BadRequest()
            cmd["kind"], cmd["plot"] = body["kind"], plot
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
                if parts[:1] == ["raid"]:
                    return self.raid(method, parts[1:], owner, now)
                if parts[:1] == ["neighbors"]:
                    return self.neighbors(method, parts[1:], owner, now)
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
                                  }.get(e.code, 422), {"error": e.code})
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

        def raid(self, method, parts, owner, now):
            if method == "POST" and parts == ["status"]:
                return self.send(200, board.raid_status(owner, self.body(), self.client_ip(), now))
            if method == "GET" and parts == ["targets"]:
                return self.send(200, board.raid_targets(owner, now))
            if method == "POST" and parts == []:
                return self.send(200, board.raid(owner, self.body(), self.client_ip(), now))
            return self.send(404, {"error": "not_found"})

        def neighbors(self, method, parts, owner, now):
            if method == "GET" and parts == []:
                return self.send(200, board.neighbor_list(owner, now))
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
