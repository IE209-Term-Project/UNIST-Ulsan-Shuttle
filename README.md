# UNIST ↔ 울산역 수요반응형 셔틀 에이전트

AI 기반 수요대응형 셔틀 예약·추천·알림 시스템 (생산운영관리 텀프로젝트, IE209).

> **메인 앱 = 애플 스타일 웹앱 (`api.py` + `web/`).** Gradio/Streamlit 버전은 `legacy/`에 보관(참고용). 새 작업은 모두 메인 앱 기준으로 합니다.

---

## 🚀 빠르게 실행 (메인 앱)
```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env            # 키 입력 (팀 내 공유)
.venv/bin/uvicorn api:app --port 8000   # → http://127.0.0.1:8000
.venv/bin/pytest                # 테스트 (키 없이도 동작)
```
필요한 키(`.env`): `OPENAI_API_KEY`, `ULSAN_BIS_API_KEY`, `GOOGLE_SERVICE_ACCOUNT_FILE`(또는 JSON), `RESERVATION_SHEET_ID`, (선택) `KAKAO_*`.
> `.env`·`service_account.json`은 git에 올리지 않음. 팀 내 안전 경로로 공유.

---

## 📁 폴더 지도
```
api.py              ★ 메인 앱 진입점 (FastAPI: 예약/추천/카풀/알림/BIS/운행계획 API + 웹 서빙)
web/index.html      ★ 메인 예약 페이지 (애플 스타일 프론트)
index.html          랜딩 페이지 (소개용, GitHub Pages)
shuttle_system/     핵심 패키지
  core/             OR 모델·슬롯·연계 계산 (optimization, schedule, connection)
  agents/           에이전트 (data, notify, report, carpool, alert)
  recommend.py      결정론적 추천 (LLM 없음)
  storage.py        예약/알림/카풀 저장소 (Google Sheets)
  timetable.py      KTX/SRT 시간표 (data/timetable.json)
  kakao.py / config.py
tests/              pytest (47개)
scripts/            seed_demo.py(데모 시드), get_kakao_token.py(카톡 토큰)
docs/               PROJECT_STATUS, ARCHITECTURE, DEPLOY_HF, SETUP_KAKAO, 설계문서
legacy/             Gradio/Streamlit 앱·옛 대시보드 (참고 보관, 메인 아님)
```

---

## 👥 역할 분담 (충돌 방지: 사람 = 모듈)
| 담당 | 파일 | 영역 |
|---|---|---|
| **A** | `shuttle_system/core/*`, `recommend.py` | OR 모델·추천 로직 |
| **B** | `shuttle_system/agents/*`, `kakao.py` | 에이전트·카풀·알림 |
| **C** | `api.py`, `web/`, `index.html` | API·프론트엔드 |
| 공용 | `storage.py`, `timetable.py` | **수정 전 팀 공유 필수** |

## 🔀 Git 협업 규칙
1. 작업 시작 전 **`git pull`** (최신 받기)
2. 작은 단위로 자주 commit, 메시지 명확히
3. 권장: `feat/이름-기능` 브랜치 → push → **PR** → 통합 담당이 main 병합
4. 같은 파일 동시 수정 금지 (담당 경계 지키기)
5. main은 **항상 동작하는 상태** 유지 (`pytest` 통과 후 push)

---

## ✅ 남은 작업 체크리스트
- [ ] (C) 예약 = "잠정/모집 중" 메시지 + 마감(cutoff) 개념
- [ ] (A) `daily_dispatch(date)` — 단일 차량 제약(겹침/일 최대 K회) 반영해 실제 운행 확정
- [ ] (B) 마감 시 확정/미운행 **카톡 알림** + 미운행 시 카풀 자동 연계
- [ ] (B) BIS 키 승인 확인(현재 ACCESS DENIED) → 실시간 513 패널 활성화
- [ ] (C) 메인 앱 HF/Render 배포 + (선택) 커스텀 도메인
- [ ] 발표 자료·보고서 (모델·에이전트·데모·한계)

자세한 현황은 [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md) 참고.
