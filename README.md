# Lemon Desk 웹

[lemondesk.interaction.hnine.com](https://lemondesk.interaction.hnine.com) 사이트와 자랑 게시판 API입니다. 운영: 에이치나인(HNINE).

| 폴더 | 내용 | 회사 인프라 앱 |
|-|-|-|
| `site/` | 정적 사이트(소개, 자랑 게시판 페이지, 개인정보 처리방침) | `lemondesk` (Subdir `site`, static) |
| `api/` | 자랑 게시판 API. Python 표준 라이브러리만 사용 | `lemondesk-api` (Subdir `api`, python) |

- 앱 내려받기(DMG)는 이 저장소의 [Releases](https://github.com/h9interaction/lemondesk-web/releases)에 있습니다.
- 원본은 Lemon Desk 앱 저장소이고, 그쪽 `scripts/publish-web.sh` 가 이곳으로 복사해 올립니다. 여기서 직접 고치지 않습니다.
- `api` 실행: `python brag.py --host 0.0.0.0 --prefix /api/ --board https://lemondesk.interaction.hnine.com/brag/ --cors https://lemondesk.interaction.hnine.com` (`PORT`, `IX_DATA_DIR` 은 인프라가 넣어 줍니다)
