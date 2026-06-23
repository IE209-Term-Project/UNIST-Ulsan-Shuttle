# UNIST ↔ 울산역 AI 수요반응형 셔틀 시스템

> 학기·주 단위 자동 학습 에이전트 4종이 시간표를 데이터로 결정하게 만든 OR 기반 멀티에이전트 시스템.
> **IE209 생산운영관리 텀프로젝트** · UNIST · 2026-1학기

[![Tests](https://img.shields.io/badge/tests-121%20passed-brightgreen)]()
[![Python](https://img.shields.io/badge/python-3.9%2B-blue)]()
[![FastAPI](https://img.shields.io/badge/FastAPI-005A7E)]()
[![License](https://img.shields.io/badge/license-MIT-green)]()

---

## ✨ Highlights

- 🧮 **OR 모델 기반 운행 결정** — 손익분기 N\* = ⌈C/b⌉ = 8명 (b = 사회적 편익 ₩4,983/명, C = ₩35,000/회)
- 🤖 **단기 Promotion Agent** — 매주 월요일 00시(KST) cron이 직전 4주 데이터로 슬롯 등급 자동 개편
- 🎓 **장기 Semester Agent** — 학기 종료 시 archive 적재 + EWMA(0.5/0.3/0.2)로 다음 학기 baseline 자동 도출
- 📊 **Weekly Report Agent** — LLM이 KPI 해석한 운영 보고서를 xlsx 첨부 메일로 자동 발송
- 🔔 **Alert Agent** — N\* 첫 충족 / 카풀 가능 / 지연을 능동 감지 후 단체 메일
- ✅ **TDD 기반 121 단위 테스트 GREEN**
- 🛡️ **롤백 안전망** — 자동 변경이 마음에 안 들면 관리자 1클릭으로 직전 상태 복원

---

## 🎬 라이브 데모

| 서비스 | URL |
|---|---|
| **학생 예약 앱** (FastAPI + Vanilla JS) | [jaeeewons-unist-shuttle-web.hf.space](https://jaeeewons-unist-shuttle-web.hf.space) |
| **관리자 대시보드** (Streamlit) | [jaeeewons-unist-shuttle-admin.hf.space](https://jaeeewons-unist-shuttle-admin.hf.space) |

> HuggingFace Spaces는 미사용 시 잠들 수 있어 첫 호출은 ~10초 대기. 새로고침하면 깨어납니다.

---

## 🏗 시스템 아키텍처

```
┌──────────────────────────────────────────────────────────────┐
│              매주 월요일 00:00 KST · GitHub Actions cron       │
└─────────────────────┬────────────────────────────────────────┘
                      ▼
   ┌──────────────────────────────────┐
   │  POST /api/promotion/run          │ ─ 단기: 4주 데이터로 등급 개편
   │  POST /api/semester/run           │ ─ 장기: 학기 1주차일 때만 EWMA
   │  POST /api/weekly_report/send     │ ─ 보고서: xlsx 첨부 메일
   └──────────────────────────────────┘
                      ▼
   ┌──────────────────────────────────┐
   │  Google Sheets (단일 진실)        │
   │   · 시트1            예약 로그    │
   │   · notifications   알림 이력    │
   │   · carpool         카풀 신청    │
   │   · schedule_overrides  활성 baseline │
   │   · semester_archive    학기 누적  │
   └──────────────────────────────────┘
                      ▼
   ┌──────────────────────┬──────────────────────┐
   │  FastAPI 학생 앱     │  Streamlit 관리자     │
   │  (web/index.html)    │  (legacy/app_admin)   │
   │  · 예약 / 카풀       │  · 운영 KPI 차트      │
   │  · 5분 캐시 자동반영 │  · 평가/적용/롤백     │
   └──────────────────────┴──────────────────────┘
```

### 두 시간 척도, 두 학습 방식

| 척도 | 에이전트 | 학습 방식 | 동작 시점 |
|---|---|---|---|
| **주간** | Promotion Agent | 4주 평균·운행률 룰 (이중조건 + Dead Zone) | 매주 월요일 00시 |
| **학기** | Semester Agent | 동일학기 EWMA (0.5/0.3/0.2) | 학기 1주차 월요일 |

---

## 🛠 기술 스택

| 영역 | 기술 |
|---|---|
| **백엔드 API** | FastAPI · Python 3.9+ · Pydantic |
| **학생 앱** | Vanilla JS · Tailwind CSS (모바일 최적화) |
| **관리자 대시보드** | Streamlit · Altair · openpyxl (xlsx 차트) |
| **저장소** | Google Sheets API (gspread) |
| **자동화** | GitHub Actions (cron) |
| **메일** | Resend API + Gmail SMTP 폴백 |
| **LLM** | OpenAI GPT-4o-mini (운영 보고서·메시지) |
| **테스트** | pytest (121개 GREEN) · TDD |
| **배포** | HuggingFace Spaces (Docker) |

---

## 📂 디렉토리 구조

```
api.py                       FastAPI 진입점 (학생 앱 + 관리자 API)
web/index.html               학생 예약 페이지
legacy/app_admin_streamlit.py  관리자 대시보드 (Streamlit)

shuttle_system/
├── core/
│   ├── optimization.py      OR 모델 — N* = ⌈C/b⌉, 사회적 편익 계산
│   ├── schedule.py          그리드 슬롯·고정 시간표·daily_dispatch
│   ├── schedule_overrides.py  동적 baseline (5분 캐시)
│   ├── booking_window.py    예약 가능 윈도우 (이번 주 단위)
│   ├── semester.py          학기 경계 (3·9월 첫 월요일 + 16주)
│   └── connection.py        KTX-셔틀 연계 평가
├── agents/
│   ├── promotion_agent.py   단기: 4주 데이터로 슬롯 등급 개편
│   ├── semester_agent.py    장기: EWMA로 학기 baseline 도출
│   ├── alert_agent.py       능동 감지 (N* 충족/카풀/지연)
│   ├── report_agent.py      LLM 운영 보고서 + xlsx
│   └── (carpool/data/notify agent)
├── recommend.py             결정론 추천 (학생 경로, LLM 없음)
├── storage.py               Memory/Sheets 양쪽 인터페이스
└── emailer.py               Resend + SMTP 폴백

tests/                       pytest TDD (121 passed)
scripts/                     시드/정리 도구 (발표 시연용)
.github/workflows/
├── weekly_promotion.yml     매주 월요일 cron (3개 에이전트 동시 실행)
└── deploy-hf.yml            push 시 HF Spaces 자동 sync
docs/                        설계 문서·노트북
```

---

## 🚀 로컬 실행

```bash
# 1. 가상환경 + 의존성
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 2. (선택) 환경변수 — Google Sheets/메일/LLM 사용 시
cp .env.example .env
#   GOOGLE_SERVICE_ACCOUNT_FILE 또는 GOOGLE_SERVICE_ACCOUNT_JSON
#   RESERVATION_SHEET_ID
#   RESEND_API_KEY / RESEND_FROM 또는 GMAIL_USER + GMAIL_APP_PASSWORD
#   ADMIN_EMAIL
#   OPENAI_API_KEY (LLM 보고서/메시지)

# 3. 학생 앱 실행
.venv/bin/uvicorn api:app --reload --port 8000
#   → http://127.0.0.1:8000

# 4. 관리자 대시보드
.venv/bin/streamlit run legacy/app_admin_streamlit.py

# 5. 테스트
.venv/bin/pytest
```

> `.env`·`service_account.json`은 `.gitignore`로 보호. 절대 커밋 금지.

---

## 🎓 핵심 설계 결정

### 1. 손익분기 N* = 8 — 어떻게 나왔나
```
편익 b = 0.3 × (택시 ₩12,000 − 셔틀 ₩2,000)
      + 0.7 × (시간가치 ₩10,000/h × 20/60 + 시내버스 ₩1,500 − 셔틀 ₩2,000)
      ≈ ₩4,983/명

N* = ⌈C/b⌉ = ⌈35,000 / 4,983⌉ = 8명
```
→ 운행 1회 사회후생이 양수가 되는 최소 인원.

### 2. 단기 Promotion Agent — 룰 기반
```
승격 (conditional → fixed):  avg ≥ 8 AND rate ≥ 0.75 (3/4주)
강등 (fixed → conditional):  avg < 4 AND rate ≤ 0.25 (1/4주)
유지 (Dead Zone):             그 외
콜드 스타트:                  학기 1~3주차 평가 동결
```
4주 = 표본 4개. 가중평균 의미 없음 → 단순 평균 + 이중 조건 + Dead Zone으로 단기 변동에 robust.

### 3. 장기 Semester Agent — EWMA
```
2026-1 baseline = 2025-1 × 0.5 + 2024-1 × 0.3 + 2023-1 × 0.2
```
동일학기명 매칭으로 봄·가을 차이 자동 반영. 데이터 부족 시 가중치 정규화.
첫·둘째 학기엔 archive 없음 → 하드코딩 fallback 자동 작동.

### 4. 학생 보호 장치
- **예약 가능 기간 = 이번 주(월~일)** — 변경 시점 이전까지만 예약, 사후 변경 영향 원천 차단
- **5분 캐시** — 새 baseline 적재 후 5분 내 학생 앱 자동 반영
- **롤백 1클릭** — 자동 변경이 잘못되면 관리자 대시보드에서 즉시 복원

---

## 📊 정량 결과

설문 N=69 응답 기반 As-Is → To-Be 매칭:

| As-Is 불편 (응답률) | To-Be 정량 개선 |
|---|---|
| 대기 시간 과도 (72.5%) | KTX-513 평균 **18.5분 절약** (97개 실측) |
| 시간 미스매치 (50.7%) | N\*=8 임계 **자동 확정** 통보 |
| 택시비 부담 (46.4%) | **₩10,000/회 절약** (택시 ₩12k → 셔틀 ₩2k) |
| 야간 단절 (39.1%) | 그리드 **22:10/23:30까지** 운영 |

121 unit tests · TDD 기반 · 회귀 0건.

---

## ⚠️ 한계 & Future Work

- **Cold-start data shortage** — demand estimated from a one-time survey, not accumulated reservation logs.
- **No-show problem** — reservations may not convert to actual ridership, distorting the threshold decision.
- **Simulation-based KPI** — no real operation yet.
- **Operating parameters assumed** — per-trip cost (₩35,000), fare (₩2,000), capacity (12), fleet=1, driver model are external estimates rather than UNIST accounting.
- **Small sample per slot** — 4 weekly observations per slot.
- **Homogeneous students assumed** — single value-of-time and taxi/bus share.

### Future Directions
- 🚌 **Real-world pilot & A/B test** — deploy alongside current shuttle for one semester
- 🛂 **No-show handling** — deposits, confirmation prompts, per-user reliability scores
- 🧠 **ML demand forecasting** — upgrade EWMA with day-of-week and seasonal patterns
- 🚍 **Multi-vehicle expansion** — fleet=1 → small bus pool for concurrent slots
- 🚉 **2030 UNIST Station integration** — parallel short route absorbs idle time of the long route

---

## 📑 발표 자료

- `docs/notebooks/operation_optimizer_agent.ipynb` — OR 모델 설계 노트북
- `docs/ARCHITECTURE.md` — 아키텍처 상세
- `docs/PROJECT_BRIEF.md` — 초기 기획서
- 발표 슬라이드/영상 — *(추후 추가)*

---

## 👤 작성자

**배재원** · UNIST 산업공학과 · IE209 생산운영관리 (2026-1)

코드와 자료는 IE209 텀프로젝트 결과물이며, 비상업적 학습/포트폴리오 목적으로 공개됩니다.

## 📄 License

[MIT License](LICENSE)
