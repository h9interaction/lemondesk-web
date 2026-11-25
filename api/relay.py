#!/usr/bin/env python3
"""Lemon Desk 옛 주소 중계: 회사 인프라 lemondesk-api(/api/…) → 집서버 https://lemongrove.club/lemondesk/api/….

이미 나간 앱(맥 2.2.2·윈도우 2.1.5 이하)이 부르는 옛 주소를 그대로 받아 넘긴다. 데이터는 집서버에만 있다.
실행: python3 relay.py [--host 0.0.0.0] [--port 8891]   (PORT 는 인프라가 넣어 준다)
원래 IP 는 X-LD-Client-IP 로 넘긴다(집서버는 이 중계의 나가는 IP 에서 온 것만 믿는다, LD_RELAY_IPS). 환경 변수 LD_UPSTREAM(기본 집서버 주소)
"""
import os
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM = os.environ.get("LD_UPSTREAM", "https://lemongrove.club/lemondesk/api/")
PREFIX = "/api/"
MAX_BODY = 8 * 1024 * 1024
SKIP = {"host", "content-length", "connection", "keep-alive", "transfer-encoding", "upgrade", "te", "trailer",
        "proxy-authorization", "proxy-connection", "accept-encoding", "x-forwarded-for", "x-ld-client-ip",
        "cf-connecting-ip"}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


opener = urllib.request.build_opener(NoRedirect)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    timeout = 30

    def log_message(self, fmt, *args):  # IP 를 남기지 않는다
        sys.stderr.write("%s %s\n" % (self.command, self.path.split("?")[0]))

    def forward(self):
        if self.path == "/":  # 인프라 헬스체크
            return self.reply(200, {"Content-Type": "application/json"}, b'{"ok": true}')
        if not self.path.startswith(PREFIX):
            return self.reply(404, {"Content-Type": "application/json"}, b'{"error": "not_found"}')
        n = int(self.headers.get("Content-Length") or 0)
        if not 0 <= n <= MAX_BODY:
            return self.reply(413, {"Content-Type": "application/json"}, b'{"error": "too_large"}')
        body = self.rfile.read(n) if n else None
        headers = {k: v for k, v in self.headers.items() if k.lower() not in SKIP}
        ip = (self.headers.get("X-Forwarded-For") or "").split(",")[0].strip() or self.client_address[0]
        headers["X-LD-Client-IP"] = ip
        headers.setdefault("User-Agent", "LemonDesk-relay")  # 윈도우 앱은 UA 가 없다. 없으면 urllib 가 붙이는 Python-urllib 를 Cloudflare 가 막는다(1010)
        req = urllib.request.Request(UPSTREAM + self.path[len(PREFIX):], data=body, method=self.command, headers=headers)
        try:
            r = opener.open(req, timeout=60)  # 폰 보기 롱폴링(25초)보다 길게
        except urllib.error.HTTPError as e:
            r = e
        except Exception:
            return self.reply(502, {"Content-Type": "application/json"}, b'{"error": "upstream"}')
        with r:
            data = r.read()
            keep = {k: v for k, v in r.headers.items()
                    if k.lower() in ("content-type", "cache-control", "retry-after", "vary") or k.lower().startswith("access-control-")}
            self.reply(r.status if hasattr(r, "status") else r.code, keep, data)

    def reply(self, status, headers, data):
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = do_POST = do_PUT = do_DELETE = do_OPTIONS = forward  # CORS(회사 사이트 페이지)는 집서버 --cors 가 답한다


def main(argv):
    args = dict(zip(argv[1::2], argv[2::2]))
    srv = ThreadingHTTPServer((args.get("--host", "0.0.0.0"), int(os.environ.get("PORT") or args.get("--port", 8891))), Handler)
    srv.daemon_threads = True
    sys.stderr.write("relay on %s:%d → %s\n" % (srv.server_address[0], srv.server_address[1], UPSTREAM))
    srv.serve_forever()


if __name__ == "__main__":
    main(sys.argv)
