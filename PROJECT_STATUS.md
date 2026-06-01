# UNIST ↔ 울산역 수요대응형 셔틀 에이전트 — 프로젝트 현황

> 생산운영관리 텀프로젝트 · 팀 협업용 현황 문서

## 1. 한 줄 요약
KTX/SRT 시간표와 학생 예약을 기반으로, **OR 최적화 모델(손익분기 N\*)** 에 따라 수요대응형 셔틀 운행 여부를 결정하고,
LLM 에이전트가 **개인화 추천·자동 예약·카풀 편성·능동 알림(카톡)** 을 수행하는 멀티 에이전트 시스템.

**핵심 원칙:** LLM은 계산하지 않는다. Python/OR이 계산하고, 에이전트는 그 결과를 해석·전달·행동한다.

## 2. 시스템 구성

```
shuttle_system/
├── core/                  # 순수 계산 로직 (LLM 無, 100% 테스트됨)
│   ├── optimization.py    #   b(편익), C(운영비), N*=⌈C/b⌉, 순편익  ← OR 모델
│   ├── schedule.py        #   고정8/조건부5 슬롯, 요일+KTX 매칭, 근방 셔틀 매칭
│   └── connection.py      #   KTX↔513 연계 판정, 택시 추정
├── agents/
│   ├── data_agent.py      # 실시간 Data Agent — 울산 BIS API(513 도착)
│   ├── notify_agent.py    # 추천/예약 Agent — 셔틀→513→택시 캐스케이드 + 자율 예약 + 카풀 추천
│   ├── report_agent.py    # Report Agent — 운영 집계·순편익·차트·LLM 브리핑
│   ├── carpool_agent.py   # 카풀 Agent — 4명 자동 그룹·장소·시각·요금
│   └── alert_agent.py     # 알림 Agent — 능동 감지(확정/카풀/지연) + 메시지 + 발송 훅
├── timetable.py           # KTX/SRT 울산 시간표 로드(data/timetable.json)
├── storage.py             # 예약·알림·카풀 저장소 (메모리/Colab/서비스계정 Sheets)
├── config.py              # 시크릿 로딩(.env / Colab / 환경변수)
├── kakao.py               # 카카오 '나에게 보내기' 발송(PoC)
├── app_student.py         # 학생용 Gradio 앱
├── app_admin.py           # 관리자용 Gradio 앱(구버전, Colab용)
└── demo.ipynb             # Colab 시연 노트북

app.py                     # HF 학생 Space 진입점(Gradio)
app_admin_streamlit.py     # HF 관리자 Space 진입점(Streamlit 대시보드)
seed_demo.py               # 발표용 데모 예약 시드
get_kakao_token.py         # 카카오 토큰 발급 헬퍼
tests/                     # pytest (42개, core·storage·agents 검증)
docs/superpowers/          # 설계 spec·구현 계획 문서
```

## 3. 구현된 기능 (완료)

| 기능 | 내용 | 상태 |
|---|---|---|
| OR 최적화 모델 | N\*=⌈C/b⌉ (요금 2,000원 → N\*=8), 순편익 b·N−C | ✅ 테스트 |
| 시간표 선택 | KTX/SRT 울산 시각 드롭다운(방면별) + 출발희망시각 근방매칭 | ✅ |
| 자율 예약 | LLM이 셔틀 슬롯이면 make_reservation으로 직접 예약 | ✅ |
| 개인화 추천 | 셔틀→513(실시간)→택시 우선순위, N\* 노출 | ✅ |
| 카풀 자동 편성 | 최대 4명 그룹, 장소(정문/역)·시각(+10분)·요금(평시1만/할증1.4만÷인원), 출발15분전 확정 | ✅ |
| 능동 알림 | N\* 돌파 운행확정 / 카풀매칭 / 지연(시뮬), 중복방지, 앱 피드+토스트 | ✅ |
| 카톡 푸시(PoC) | 알림을 발송자 본인 카톡으로 전송 | ✅ (토큰 필요) |
| 관리자 리포트 | KPI·차트·표·LLM 브리핑(Streamlit) | ✅ |
| 영구 저장 | Google Sheets(예약/알림/카풀 워크시트) | ✅ |
| 배포 | HF Spaces 2개(학생 Gradio / 관리자 Streamlit) | ✅ |

## 4. 배포 URL
- 학생: https://huggingface.co/spaces/jaeeewons/unist-shuttle
- 관리자: https://huggingface.co/spaces/jaeeewons/unist-shuttle-admin
- 데이터: 공유 Google Sheet (서비스 계정 연동)

## 5. 로컬 실행 (팀원용)
```bash
git clone <이 레포>
cd <레포>
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env          # 키 채우기 (각자 발급)
.venv/bin/pytest              # 테스트 확인
.venv/bin/python app.py                       # 학생 앱
.venv/bin/streamlit run app_admin_streamlit.py  # 관리자 대시보드
```
**필요한 키(각자 .env):** `OPENAI_API_KEY`, `ULSAN_BIS_API_KEY`, 서비스계정(`GOOGLE_SERVICE_ACCOUNT_FILE` 또는 JSON) + `RESERVATION_SHEET_ID`, (선택) `KAKAO_*`.
> ⚠️ `.env`·`service_account.json`은 git에 올리지 말 것(이미 .gitignore 처리됨). 키는 팀 내 안전한 경로로 공유.

## 6. 한계 & 확장 (보고서용)
- **카톡 알림은 PoC** — 발송자 본인만. 실서비스 전체 학생 발송은 **카카오 알림톡**(사업자등록·비즈채널·템플릿심사·중계사, 건당 ~10원)로 확장. `kakao.py` 발송 함수만 교체하면 됨.
- **지연 알림**은 미래 날짜 데모 한계로 시뮬레이션 트리거 제공. 실시간 513 API 연계는 당일 운행 시 동작.
- **수요 N**은 설문 기반 demo 값. 실제 운영 시 누적 예약으로 갱신.
- 시간표 변경 시 `shuttle_system/data/timetable.json`만 교체. 택시 할증시간은 `carpool_agent.py` 상수(현재 22~04시).

## 7. 문서
- 설계: `docs/superpowers/specs/2026-06-01-shuttle-agent-system-design.md`
- 구현계획: `docs/superpowers/plans/`
- 아키텍처: `shuttle_system/ARCHITECTURE.md`
- 배포 가이드: `DEPLOY_HF.md`, 카톡 설정: `SETUP_KAKAO.md`
