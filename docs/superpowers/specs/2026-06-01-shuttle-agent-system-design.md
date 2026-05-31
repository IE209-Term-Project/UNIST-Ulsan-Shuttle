# UNIST ↔ 울산역 수요대응형 셔틀 에이전트 시스템 — 설계

**작성일:** 2026-06-01
**마감:** 2026-06-04(목) 전 — 발표 2026-06-05(금)
**산출물 형태:** 모듈형 `.py` 프로젝트 + 발표 시연용 노트북 (옵션 3)

---

## 1. 배경 & 목표

기존 자산:
- `shuttle_recommendation_agent_v4.ipynb` — 실시간 513(울산 BIS API) + OpenAI function-calling 추천 + Google Sheets 예약 + Gradio.
- `셔틀_운영_모델_최종정리.pdf` — OR 최적화 모델(목적함수 `Z = Σ xₜ(b·Nₜ − C)`, 손익분기 `N* = ⌈C/b⌉`, 정원·운행횟수 제약 → knapsack). demo 데이터로 고정 8 + 조건부 5 슬롯 도출.

문제: **최적화 모델과 에이전트가 끊겨 있다.** 노트북의 셔틀 슬롯/임계값(`7`)은 모델 결과를 손으로 베껴 박은 상수이고, 모델 공식은 코드에 없다.

핵심 컨셉(README): LLM은 최적화를 직접 계산하지 않는다. **Python이 계산한 결과를 에이전트가 해석·전달**한다.

시스템 본질: **매 기간 예약 인원을 모델 기준 N\*와 대조해 운행/미운행을 결정**하는 수요대응형 운영 시스템.

이번 작업 두 갈래:
- (A) 실시간 추천 에이전트 디벨롭 — 개인화 강화 + 모델 연결
- (B) Report Agent 신규 — 관리자용 운영 리포트

---

## 2. 아키텍처

```
shuttle_system/
├── core/
│   ├── optimization.py   # b, C, N*=⌈C/b⌉, 순편익 b·N−C (PDF 모델 구현)
│   ├── schedule.py       # 고정8/조건부5 슬롯 데이터 + 요일·KTX 매칭
│   └── connection.py     # KTX↔513 연계 판정, 택시 추정 (기존 셀4·6)
├── agents/
│   ├── data_agent.py     # 실시간 BIS API 513 도착 (기존 셀3)
│   ├── notify_agent.py   # 개인화 추천 LLM (기존 셀7·8) + 택시셰어 매칭
│   └── report_agent.py   # 운영 리포트 LLM + 차트 (신규)
├── storage.py            # Google Sheets 예약 (기존 셀9)
├── app_student.py        # 🎓 학생용 Gradio: 예약 + 개인화 추천
├── app_admin.py          # 🛠 관리자용 Gradio: 운영 리포트
└── demo.ipynb            # 위 모듈 import 해서 두 앱 시연
```

### README 4-에이전트 매핑
| README 역할 | 구현 |
|---|---|
| 실시간 Data Agent | `data_agent.py` |
| Demand Prediction | demo 데이터의 슬롯별 수요 N을 `core`가 사용 (별도 ML 미구현) |
| Notification/Recommendation | `notify_agent.py` |
| Report Agent | `report_agent.py` |

### 멀티 에이전트 수준
**모듈형(옵션 1).** 각 에이전트 = 책임이 분리된 Python 모듈/클래스. LLM 호출은 `notify_agent`, `report_agent` 두 곳만. 진성 메시지패싱 멀티 에이전트는 3일 리스크로 채택하지 않음. 아키텍처 다이어그램으로 "4개 에이전트"를 설명.

---

## 3. core: 최적화 모델 연결

값의 성격 구분 (중요):

| 값 | 성격 | 결정 시점 |
|---|---|---|
| `N*` 손익분기 | **상수** | 요금/비용 정해지면 1회 계산 |
| 슬롯 수요 `N` | **상수** | 설문에서 도출, demo 데이터에 존재 |
| **실제 예약 수** | **유일한 실시간 값** | 학생이 예약할 때마다 증가 |

→ 시스템이 실시간으로 다루는 건 "이 슬롯 현재 예약 인원" 하나. 에이전트는 그것을 상수 `N*`와 **비교만** 한다.

```python
# core/optimization.py
C = 35_000  # 회당 변동 운영비 (PDF 5절)

def benefit_per_person(fare):
    # 택시 0.3 / 버스 0.7 가중 (PDF 3절). 결과표(6절)와 일치해야 함.
    taxi = 0.3 * (12_000 - fare)
    bus  = 0.7 * ((20/60)*10_000 + 1_500 - fare)
    return taxi + bus

def breakeven_N(fare):       # N* = ⌈C/b⌉  → 6/6/8/9 (요금 0/1k/2k/3k)
    return math.ceil(C / benefit_per_person(fare))

def net_benefit(N, fare):    # 실현 순편익 b·N − C (Report가 매 기간 사용)
    return benefit_per_person(fare) * N - C
```

`N*`는 하드코딩 `7` 대신 이 공식에서 1회 산출 → "임계값의 근거"가 코드로 설명됨. 진짜 반복 계산은 Report의 실현 순편익뿐.

> 주의: `benefit_per_person`은 PDF 6절 결과표(b = 6,983 / 5,983 / 4,983 / 3,983)와 정확히 일치하도록 상수를 맞춘다. 구현 시 결과표를 단일 출처로 삼아 검증.

---

## 4. (A) 실시간 추천 에이전트 디벨롭 — `notify_agent.py`

기존 "셔틀 → 513 → 택시" 캐스케이드 유지. 개인화 2가지 추가.

### (1) 조건부 셔틀 판정을 모델 기준으로
- 기존: `예약 ≥ 7` (하드코딩)
- 변경: `예약 ≥ N*` (`N* = breakeven_N(fare)`). 추천 메시지에 모델 임계값 노출 — *"현재 예약 16/8명 → 운행 확정"*.
- **정책 요금 확정: F=2,000원 → N\*=8.** demo의 `7`은 임의값이었고, 모델로 8로 보정(발표 스토리: "임의 7 → 모델 근거 8"). 시스템 전체의 조건부 임계값은 `breakeven_N(2000)=8`을 단일 출처로 사용.

### (2) 택시 셰어 매칭
모델의 "N < N* → 미운영 시 대체교통" 로직 + README 개인화의 구체화.
- 예약이 `N*` 미달이라 셔틀 미운행일 때, 같은 슬롯(방향·KTX시각·날짜)에 예약한 다른 학생을 Sheets에서 조회.
- 새 도구 `find_taxi_share(direction, ktx_time, date)` → Sheets 집계 → LLM 해석.
- 메시지 예: *"같은 13:58 KTX를 노리는 학생이 2명 더 있어요 → 3명 택시 셰어 시 1인 ~₩4,500"*.

원칙 유지: 시간/요일/요금 계산은 전부 코드, LLM은 해석·서술만.

---

## 5. (B) Report Agent — 관리자용 별도 앱 `app_admin.py` + `report_agent.py`

**별도 앱인 이유:** 학생 앱(예약·알림)과 관리자 리포트는 사용자가 다르다. 학생 화면에 운영 통계를 섞지 않는다. 두 앱은 같은 `core`/`storage`를 공유하되 진입점만 다르다.

**데이터 소스:** Google Sheets 예약 누적분 + demo 슬롯 데이터(N, 요금별 N*).

**계산 (코드 담당):**
- 슬롯별: 실제 예약 수, 운행 여부(`예약 ≥ N*`), 실현 순편익 `b·N − C`, 절감 대기시간(`T_saved=20분 × 수송 인원`)
- 전체 집계: 총 운행 횟수, 총 수송 인원, 총 순편익(₩), 총 대기시간 절감

**차트 (matplotlib → Gradio):**
1. 슬롯별 예약 인원 vs N* 막대 (임계 초과 슬롯 색 구분)
2. 슬롯별 실현 순편익 막대 (양/음)

**LLM 서술 요약 (`report_agent`가 위 숫자를 받아 해석):**
> *"이번 주 셔틀 9개 슬롯 중 6개 운행, 총 87명 수송. 실현 사회 순편익 +₩31만, 누적 대기시간 약 29시간 절감. '금 저녁'이 순편익 1위(+₩7.8만). '토 오후'는 예약 3/8명 미달 → 택시 셰어 안내로 전환."*

LLM은 계산하지 않고 해석·서술만.

**Gradio 구성:** "리포트 생성" 버튼 → 집계 표 + 차트 2개 + LLM 요약 텍스트.

---

## 6. 발표 시연 흐름 (`demo.ipynb`)

모듈을 import만 하고 두 앱을 각각 `launch(share=True)` → URL 2개.
1. 학생 앱: 예약 입력 → 개인화 추천 수신
2. 관리자 앱: 같은 예약이 리포트(표·차트·요약)에 반영되는 것 확인

→ "같은 시스템을 두 역할이 쓴다"는 멀티 에이전트 스토리가 시연으로 드러남.

---

## 7. 테스트 (pytest)

LLM·API 없이 검증 가능한 `core` 중심:
- `breakeven_N(0)==6`, `breakeven_N(1000)==6`, `breakeven_N(2000)==8`, `breakeven_N(3000)==9` (PDF 6절 일치)
- `benefit_per_person`이 6,983 / 5,983 / 4,983 / 3,983 재현
- `net_benefit` 부호/값
- 슬롯 매칭(요일+KTX), 연계 판정(SAFE/TIGHT/MISS/GOOD/LONG_WAIT), 택시셰어 집계

---

## 8. 비범위 (YAGNI)

- 별도 ML 수요예측 모델 (demo 설문 수요로 충분)
- 진성 메시지패싱 멀티 에이전트
- KTX 실시간 지연 API 연동 (513 실시간만 유지)
- 학생 앱 UI 재설계 (기존 유지)

---

## 9. 보안

- OpenAI/BIS API 키는 Colab Secrets / 환경변수로만. 코드·문서·git에 키 원문 절대 미포함.
