# UNIST 셔틀 에이전트 시스템 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 기존 Colab 노트북(v4)을 모듈형 Python 프로젝트로 재구성하고, OR 최적화 모델을 코드로 연결한 뒤, 개인화 추천 강화(택시 셰어)와 관리자용 Report Agent(별도 앱)를 추가한다.

**Architecture:** 순수 Python `core/`(최적화·슬롯·연계 계산) 위에 4개 모듈형 에이전트(`data`/`notify`/`report` + demo 수요)를 얹는다. LLM은 `notify_agent`/`report_agent`에서만 호출하며 계산은 전부 코드가 담당한다. 학생용·관리자용 두 개의 Gradio 앱이 같은 `core`/`storage`를 공유한다.

**Tech Stack:** Python 3.10+, pytest, OpenAI SDK(function-calling), gradio, gspread(+google-auth), matplotlib, requests. 개발/테스트는 로컬 Mac, 실행은 Colab(Secrets/auth) — 환경 차이는 `config.py`가 흡수.

---

## File Structure

```
shuttle_system/
├── __init__.py
├── config.py             # API 키/시크릿 로딩 (Colab userdata ↔ os.environ 폴백)
├── core/
│   ├── __init__.py
│   ├── optimization.py   # b, C, N*=⌈C/b⌉, net_benefit (PDF 모델). 순수 함수
│   ├── schedule.py       # 고정8/조건부5 슬롯 + 요일·KTX 매칭. 순수 함수
│   └── connection.py     # KTX↔513 연계 판정 + 택시 추정. 순수 함수
├── storage.py            # 예약 저장소: 추상 인터페이스 + 메모리 구현 + Sheets 구현
├── agents/
│   ├── __init__.py
│   ├── data_agent.py     # 실시간 BIS API (513 도착)
│   ├── notify_agent.py   # 추천 LLM 루프 + 도구 + 택시셰어
│   └── report_agent.py   # 운영 집계 + 차트 + LLM 요약
├── app_student.py        # 학생용 Gradio
├── app_admin.py          # 관리자용 Gradio
└── demo.ipynb            # 두 앱 시연

tests/
├── test_optimization.py
├── test_schedule.py
├── test_connection.py
├── test_storage.py
└── test_report_agent.py
```

**경계 원칙:** `core/*`와 `storage`의 메모리 구현은 외부 의존성이 없어 pytest로 완전 검증 가능. 외부 의존(OpenAI/BIS/Sheets/gradio)은 `agents/`·`app_*`에 격리하고, 테스트에서는 메모리 저장소·페이크 함수로 대체.

---

## Task 0: 프로젝트 초기화

**Files:**
- Create: `requirements.txt`, `pytest.ini`, `.gitignore`, `shuttle_system/__init__.py`, `shuttle_system/core/__init__.py`, `shuttle_system/agents/__init__.py`

- [ ] **Step 1: git 저장소 초기화**

Run:
```bash
git init && git branch -m main
```
Expected: `Initialized empty Git repository`

- [ ] **Step 2: 파일 생성**

`requirements.txt`:
```
openai>=1.0
gradio>=4.0
gspread>=6.0
google-auth>=2.0
matplotlib>=3.7
requests>=2.31
pytest>=8.0
```

`pytest.ini`:
```ini
[pytest]
testpaths = tests
python_files = test_*.py
```

`.gitignore`:
```
__pycache__/
*.pyc
.venv/
shuttle_data.json
*.png
.DS_Store
```

빈 패키지 파일 3개 생성: `shuttle_system/__init__.py`, `shuttle_system/core/__init__.py`, `shuttle_system/agents/__init__.py` (내용 없음).

- [ ] **Step 3: 가상환경 + 설치**

Run:
```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```
Expected: 설치 성공 (마지막 줄 `Successfully installed ...`)

- [ ] **Step 4: Commit**

```bash
git add requirements.txt pytest.ini .gitignore shuttle_system tests
git commit -m "chore: scaffold shuttle_system project"
```

---

## Task 1: core/optimization.py (OR 모델)

**Files:**
- Create: `shuttle_system/core/optimization.py`
- Test: `tests/test_optimization.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_optimization.py`:
```python
import math
from shuttle_system.core.optimization import (
    C, benefit_per_person, breakeven_N, net_benefit,
)


def test_cost_constant():
    assert C == 35_000


def test_benefit_per_person_matches_pdf_table():
    # PDF 6절 결과표: 요금 0/1000/2000/3000 -> b 6983/5983/4983/3983
    assert round(benefit_per_person(0)) == 6983
    assert round(benefit_per_person(1000)) == 5983
    assert round(benefit_per_person(2000)) == 4983
    assert round(benefit_per_person(3000)) == 3983


def test_breakeven_matches_pdf_table():
    # N* = ceil(C/b): 6/6/8/9
    assert breakeven_N(0) == 6
    assert breakeven_N(1000) == 6
    assert breakeven_N(2000) == 8
    assert breakeven_N(3000) == 9


def test_net_benefit_sign():
    # F=2000 -> b=4983, N*=8. 8명이면 양수, 7명이면 음수
    assert net_benefit(8, 2000) > 0
    assert net_benefit(7, 2000) < 0
    assert round(net_benefit(8, 2000)) == round(4983 * 8 - 35_000)
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv/bin/pytest tests/test_optimization.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'shuttle_system.core.optimization'`

- [ ] **Step 3: 구현**

`shuttle_system/core/optimization.py`:
```python
"""PDF '셔틀 운영 모델'의 코드 구현 — 순수 함수, 외부 의존 없음.

값의 성격:
  - N* (손익분기): 상수. 요금/비용이 정해지면 1회 산출.
  - net_benefit: Report가 매 기간 실제 수송 인원으로 계산.
"""
import math

# ── 파라미터 (PDF 3·5절) ────────────────────────────────
C = 35_000              # 회당 변동 운영비(원)
P_TAXI = 0.3            # 셔틀 이용자 중 원래 택시 비율
P_BUS = 0.7             # 〃 버스 비율
TAXI_FARE = 12_000      # 캠퍼스↔울산역 택시요금
BUS_FARE = 1_500        # 513 요금
T_SAVED_MIN = 20        # 513 대비 셔틀 시간절약(분)
VOT_PER_HOUR = 10_000   # 학생 시간가치(원/h)

# 정책 요금 (확정: 2,000원 → N*=8)
POLICY_FARE = 2_000


def benefit_per_person(fare: int) -> float:
    """1인당 편익 b (PDF 3절). fare는 셔틀 요금(0~3000)."""
    taxi = P_TAXI * (TAXI_FARE - fare)
    bus = P_BUS * ((T_SAVED_MIN / 60) * VOT_PER_HOUR + BUS_FARE - fare)
    return taxi + bus


def breakeven_N(fare: int = POLICY_FARE) -> int:
    """손익분기 인원 N* = ceil(C / b). 상수."""
    return math.ceil(C / benefit_per_person(fare))


def net_benefit(passengers: int, fare: int = POLICY_FARE) -> float:
    """실현 사회 순편익 b·N − C."""
    return benefit_per_person(fare) * passengers - C
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv/bin/pytest tests/test_optimization.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add shuttle_system/core/optimization.py tests/test_optimization.py
git commit -m "feat: implement OR optimization model (N*, net benefit)"
```

---

## Task 2: core/schedule.py (슬롯 데이터 + 매칭)

**Files:**
- Create: `shuttle_system/core/schedule.py`
- Test: `tests/test_schedule.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_schedule.py`:
```python
from shuttle_system.core.schedule import find_shuttle_slot, WEEKDAY_KR


def test_fixed_slot_found_friday_afternoon():
    # 금요일(wd=4) 13:58 출발 = 고정편
    r = find_shuttle_slot('to_station', '13:58', weekday=4, reservations=0)
    assert r['available'] is True
    assert r['service'] == 'fixed'
    assert r['shuttle_time'] == '13:41'


def test_conditional_below_threshold_not_dispatched():
    # 목요일(wd=3) 13:58 = 조건부. 예약 7 < N*(8) -> 미배차
    r = find_shuttle_slot('to_station', '13:58', weekday=3, reservations=7)
    assert r['service'] == 'conditional'
    assert r['available'] is False
    assert r['required'] == 8


def test_conditional_meets_threshold_dispatched():
    r = find_shuttle_slot('to_station', '13:58', weekday=3, reservations=8)
    assert r['service'] == 'conditional'
    assert r['available'] is True


def test_no_slot():
    r = find_shuttle_slot('to_station', '03:00', weekday=2, reservations=0)
    assert r['available'] is False
    assert r['service'] is None
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv/bin/pytest tests/test_schedule.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 구현**

`shuttle_system/core/schedule.py`:
```python
"""고정 8 + 조건부 5 셔틀 슬롯 데이터와 요일+KTX 매칭. 순수 함수.

조건부 임계값은 하드코딩이 아니라 optimization.breakeven_N()에서 가져온다.
"""
from shuttle_system.core.optimization import breakeven_N, POLICY_FARE

WEEKDAY_KR = '월화수목금토일'

# 고정 8회: 출발=KTX 17분 전 / 복귀=KTX 도착 15분 후 (확정 운행)
SHUTTLE_FIXED = {
    'to_station': [
        {'slot': '금 오후', 'wd': 4, 'ktx': '13:58', 'shuttle': '13:41', 'demand': 57},
        {'slot': '금 저녁', 'wd': 4, 'ktx': '17:51', 'shuttle': '17:34', 'demand': 51},
        {'slot': '목 저녁', 'wd': 3, 'ktx': '17:51', 'shuttle': '17:34', 'demand': 24},
        {'slot': '토 오전', 'wd': 5, 'ktx': '10:02', 'shuttle': '09:45', 'demand': 26},
    ],
    'to_campus': [
        {'slot': '월 오전', 'wd': 0, 'ktx': '08:45', 'shuttle': '09:00', 'demand': 31},
        {'slot': '일 오후', 'wd': 6, 'ktx': '12:07', 'shuttle': '12:22', 'demand': 36},
        {'slot': '일 저녁', 'wd': 6, 'ktx': '18:43', 'shuttle': '18:58', 'demand': 54},
        {'slot': '일 야간', 'wd': 6, 'ktx': '20:29', 'shuttle': '20:44', 'demand': 61},
    ],
}

# 조건부 5회: 예약 >= N* 일 때만 1회 배차 (전부 출발 방향)
SHUTTLE_CONDITIONAL = {
    'to_station': [
        {'slot': '목 오후', 'wd': 3, 'ktx': '13:58', 'shuttle': '13:41', 'demand': 13},
        {'slot': '목 야간', 'wd': 3, 'ktx': '22:39', 'shuttle': '22:22', 'demand': 12},
        {'slot': '금 오전', 'wd': 4, 'ktx': '10:02', 'shuttle': '09:45', 'demand': 16},
        {'slot': '금 야간', 'wd': 4, 'ktx': '22:39', 'shuttle': '22:22', 'demand': 21},
        {'slot': '토 오후', 'wd': 5, 'ktx': '13:58', 'shuttle': '13:41', 'demand': 14},
    ],
    'to_campus': [],
}


def find_shuttle_slot(direction, ktx_time, weekday, reservations=0, fare=POLICY_FARE):
    """요일+KTX 시각으로 배정된 셔틀편을 찾는다. 고정 우선, 없으면 조건부."""
    ktx_time = ktx_time.strip()
    wd_kr = WEEKDAY_KR[weekday] + '요일'

    for e in SHUTTLE_FIXED.get(direction, []):
        if e['wd'] == weekday and e['ktx'] == ktx_time:
            return {'available': True, 'service': 'fixed', 'mode': 'shuttle',
                    'weekday': wd_kr, 'slot': e['slot'], 'shuttle_time': e['shuttle'],
                    'ktx_time': e['ktx'], 'note': '고정 운행 확정편'}

    n_star = breakeven_N(fare)
    for e in SHUTTLE_CONDITIONAL.get(direction, []):
        if e['wd'] == weekday and e['ktx'] == ktx_time:
            ok = reservations >= n_star
            return {'available': ok, 'service': 'conditional', 'mode': 'shuttle',
                    'weekday': wd_kr, 'slot': e['slot'], 'shuttle_time': e['shuttle'],
                    'ktx_time': e['ktx'], 'reservations': reservations,
                    'required': n_star,
                    'note': (f'조건부편 — 예약 {reservations}명 ≥ N*({n_star}) → 배차 확정'
                             if ok else
                             f'조건부편 — 예약 {reservations}/{n_star}명 → 배차 미정, 대체수단 검토')}

    return {'available': False, 'service': None, 'mode': 'shuttle', 'weekday': wd_kr,
            'note': '해당 요일/KTX 시각에 배정된 셔틀편 없음 → 513/택시 검토'}


def all_slots():
    """리포트용: (service, direction, slot dict) 전체 평탄화."""
    out = []
    for svc, table in (('fixed', SHUTTLE_FIXED), ('conditional', SHUTTLE_CONDITIONAL)):
        for direction, entries in table.items():
            for e in entries:
                out.append({'service': svc, 'direction': direction, **e})
    return out
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv/bin/pytest tests/test_schedule.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add shuttle_system/core/schedule.py tests/test_schedule.py
git commit -m "feat: shuttle slot data + model-driven conditional threshold"
```

---

## Task 3: core/connection.py (513 연계 판정 + 택시)

**Files:**
- Create: `shuttle_system/core/connection.py`
- Test: `tests/test_connection.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_connection.py`:
```python
from datetime import datetime
from shuttle_system.core.connection import (
    evaluate_connection, recommend_taxi, RIDE_MIN,
)

NOW = datetime(2026, 6, 5, 13, 0)  # 금 13:00 고정


def test_to_station_safe():
    # 13:00 기준, 버스 2분 후 도착, 20분 승차 -> 13:22 역도착, KTX 13:58 -> 여유
    r = evaluate_connection('to_station', bus_arrival_min=2, ktx_time='13:58', now=NOW)
    assert r['status'] == 'SAFE'


def test_to_station_miss():
    # 버스 50분 후 -> 13:50 탑승 -> 14:10 역도착 > 13:58 -> MISS
    r = evaluate_connection('to_station', bus_arrival_min=50, ktx_time='13:58', now=NOW)
    assert r['status'] == 'MISS'


def test_to_station_bus_too_soon():
    r = evaluate_connection('to_station', bus_arrival_min=2, ktx_time='13:58',
                            walk_to_stop_min=5, now=NOW)
    # 도보 5분 > 버스 2분이면 BUS_TOO_SOON
    assert r['status'] == 'BUS_TOO_SOON'


def test_to_campus_good():
    r = evaluate_connection('to_campus', bus_arrival_min=8, ktx_time='13:00', now=NOW)
    # 하차 ready=13:05, 버스 13:08 출발 -> 대기 3분 -> GOOD
    assert r['status'] == 'GOOD'


def test_taxi_has_estimate():
    r = recommend_taxi('to_station')
    assert r['mode'] == 'taxi'
    assert 'est_time_min' in r
```

> 주의: `test_to_station_safe`와 `test_to_station_bus_too_soon`는 `walk_to_stop_min` 기본값이 다르다. SAFE 케이스는 도보 0분 가정이 필요하므로 구현의 기본값을 5로 두고, SAFE 테스트는 `walk_to_stop_min=0`을 넘기도록 아래 구현 후 보정한다. (Step 3 구현 후 Step 4에서 확인)

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv/bin/pytest tests/test_connection.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 구현**

`shuttle_system/core/connection.py`:
```python
"""KTX ↔ 513 연계 판정과 택시 추정. 모든 시간 계산은 코드가 담당. 순수 함수."""
from datetime import datetime, timedelta

RIDE_MIN = 20             # 513 UNIST↔울산역 평균 소요(분)
KTX_BOARDING_BUFFER = 5   # 역 도착 후 발권/승차 준비(분)
STATION_EXIT_MIN = 5      # KTX 하차 후 정류장 이동(분)

TAXI_EST = {'est_time_min': 18, 'est_fare_krw': '약 13,000~16,000원'}


def _parse_hhmm(value, base):
    t = datetime.strptime(value.strip(), '%H:%M').time()
    return base.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)


def evaluate_connection(direction, bus_arrival_min, ktx_time,
                        walk_to_stop_min=5, now=None):
    """KTX 시각과 실시간 513 도착을 대조해 연계 가능 여부를 결정론적으로 계산."""
    now = now or datetime.now()
    facts = {'direction': direction, 'now': now.strftime('%H:%M'),
             'bus_arrival_min': bus_arrival_min, 'ktx_time': ktx_time}

    if direction == 'to_station':
        ktx_dep = _parse_hhmm(ktx_time, now)
        if bus_arrival_min < walk_to_stop_min:
            facts.update(status='BUS_TOO_SOON',
                         reason=f'정류장까지 도보 {walk_to_stop_min}분인데 버스가 '
                                f'{bus_arrival_min}분 후 도착 → 이번 513 탑승 불가',
                         recommend='다음 513 또는 고정 시간표 확인 필요')
            return facts
        board = now + timedelta(minutes=bus_arrival_min)
        arrive_st = board + timedelta(minutes=RIDE_MIN)
        slack_min = round((ktx_dep - arrive_st).total_seconds() / 60)
        eff_slack = slack_min - KTX_BOARDING_BUFFER
        if arrive_st >= ktx_dep:
            status, recommend = 'MISS', '이 KTX는 놓침 → 다음 열차/택시 검토'
        elif eff_slack < 10:
            status, recommend = 'TIGHT', '탑승 가능하나 빠듯 → 바로 정류장으로 이동'
        else:
            status, recommend = 'SAFE', '여유 있음 → 정시 출발하면 OK'
        facts.update(status=status, board_time=board.strftime('%H:%M'),
                     station_arrival=arrive_st.strftime('%H:%M'),
                     ktx_departure=ktx_dep.strftime('%H:%M'),
                     slack_min=slack_min, effective_slack_min=eff_slack,
                     recommend=recommend)
        return facts

    # to_campus
    ktx_arr = _parse_hhmm(ktx_time, now)
    ready = ktx_arr + timedelta(minutes=STATION_EXIT_MIN)
    depart = now + timedelta(minutes=bus_arrival_min)
    wait = round((depart - ready).total_seconds() / 60)
    if depart < ready:
        status, recommend = 'BUS_BEFORE_READY', '이 513은 하차 전 출발 → 다음 차/택시 검토'
    elif wait <= 10:
        status, recommend = 'GOOD', '하차 후 바로 탑승 가능'
    else:
        status, recommend = 'LONG_WAIT', f'정류장에서 약 {wait}분 대기 예상'
    facts.update(status=status, ktx_arrival=ktx_arr.strftime('%H:%M'),
                 ready_time=ready.strftime('%H:%M'),
                 bus_departure=depart.strftime('%H:%M'), wait_min=wait,
                 recommend=recommend)
    return facts


def recommend_taxi(direction):
    """최후 대안: 택시(상시)."""
    return {'mode': 'taxi', **TAXI_EST,
            'note': '상시 이용 가능. 심야(00~04시) 할증 가능. 최후 대안.'}
```

- [ ] **Step 4: 테스트 통과 확인 (+ SAFE 케이스 보정)**

`tests/test_connection.py`의 `test_to_station_safe`를 다음으로 수정 (도보 0분이면 SAFE):
```python
def test_to_station_safe():
    r = evaluate_connection('to_station', bus_arrival_min=2, ktx_time='13:58',
                            walk_to_stop_min=0, now=NOW)
    assert r['status'] == 'SAFE'
```

Run: `.venv/bin/pytest tests/test_connection.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add shuttle_system/core/connection.py tests/test_connection.py
git commit -m "feat: KTX-513 connection logic + taxi estimate"
```

---

## Task 4: config.py + storage.py (예약 저장소)

**Files:**
- Create: `shuttle_system/config.py`, `shuttle_system/storage.py`
- Test: `tests/test_storage.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_storage.py`:
```python
from shuttle_system.storage import MemoryReservationStore


def test_add_and_count():
    s = MemoryReservationStore()
    s.add('홍길동', 'to_station', '13:58', '2026-06-05')
    s.add('김철수', 'to_station', '13:58', '2026-06-05')
    s.add('이영희', 'to_campus', '12:07', '2026-06-07')
    assert s.count('to_station', '13:58', '2026-06-05') == 2
    assert s.count('to_campus', '12:07', '2026-06-07') == 1
    assert s.count('to_station', '13:58', '2026-06-06') == 0


def test_names_and_clear():
    s = MemoryReservationStore()
    s.add('A', 'to_station', '13:58', '2026-06-05')
    s.add('B', 'to_station', '13:58', '2026-06-05')
    assert set(s.names('to_station', '13:58', '2026-06-05')) == {'A', 'B'}
    s.clear_slot('to_station', '13:58', '2026-06-05')
    assert s.count('to_station', '13:58', '2026-06-05') == 0


def test_all_records():
    s = MemoryReservationStore()
    s.add('A', 'to_station', '13:58', '2026-06-05')
    recs = s.all_records()
    assert len(recs) == 1
    assert recs[0]['direction'] == 'to_station'
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv/bin/pytest tests/test_storage.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 구현**

`shuttle_system/config.py`:
```python
"""환경 차이 흡수: Colab Secrets ↔ 로컬 os.environ. 키 원문은 절대 코드에 두지 않는다."""
import os


def get_secret(name: str):
    """Colab이면 userdata, 아니면 환경변수에서 시크릿을 읽는다."""
    try:
        from google.colab import userdata  # Colab에서만 존재
        val = userdata.get(name)
        if val:
            return val
    except Exception:
        pass
    return os.environ.get(name)
```

`shuttle_system/storage.py`:
```python
"""예약 저장소. 슬롯 = (direction, ktx_time, travel_date).

- MemoryReservationStore: 테스트/로컬용. 외부 의존 없음.
- SheetsReservationStore: Colab/운영용. gspread 필요.
공통 인터페이스: add / count / names / all_records / clear_slot
"""
from datetime import datetime

HEADER = ['name', 'direction', 'ktx_time', 'travel_date', 'created_at']


def _match(r, direction, ktx_time, travel_date):
    return (str(r.get('direction', '')) == direction
            and str(r.get('ktx_time', '')) == ktx_time
            and str(r.get('travel_date', '')) == travel_date)


class MemoryReservationStore:
    def __init__(self):
        self._rows = []

    def add(self, name, direction, ktx_time, travel_date):
        self._rows.append({'name': (name or '익명').strip(), 'direction': direction,
                           'ktx_time': ktx_time, 'travel_date': travel_date,
                           'created_at': datetime.now().isoformat(timespec='seconds')})

    def all_records(self):
        return list(self._rows)

    def count(self, direction, ktx_time, travel_date):
        return sum(1 for r in self._rows if _match(r, direction, ktx_time, travel_date))

    def names(self, direction, ktx_time, travel_date):
        return [r['name'] for r in self._rows if _match(r, direction, ktx_time, travel_date)]

    def clear_slot(self, direction, ktx_time, travel_date):
        self._rows = [r for r in self._rows
                      if not _match(r, direction, ktx_time, travel_date)]


class SheetsReservationStore:
    """Colab 전용. gspread 핸들을 받아 동일 인터페이스 제공."""
    def __init__(self, sheet_name='UNIST_shuttle_reservations'):
        from google.colab import auth
        auth.authenticate_user()
        import gspread
        from google.auth import default
        creds, _ = default()
        gc = gspread.authorize(creds)
        try:
            sh = gc.open(sheet_name)
        except gspread.SpreadsheetNotFound:
            sh = gc.create(sheet_name)
        self.ws = sh.sheet1
        vals = self.ws.get_all_values()
        if not vals or vals[0] != HEADER:
            self.ws.clear()
            self.ws.append_row(HEADER, value_input_option='RAW')
        self.url = sh.url

    def add(self, name, direction, ktx_time, travel_date):
        self.ws.append_row([(name or '익명').strip(), direction, ktx_time, travel_date,
                            datetime.now().isoformat(timespec='seconds')],
                           value_input_option='RAW')

    def all_records(self):
        return self.ws.get_all_records()

    def count(self, direction, ktx_time, travel_date):
        return sum(1 for r in self.all_records()
                   if _match(r, direction, ktx_time, travel_date))

    def names(self, direction, ktx_time, travel_date):
        return [str(r.get('name', '')) for r in self.all_records()
                if _match(r, direction, ktx_time, travel_date)]

    def clear_slot(self, direction, ktx_time, travel_date):
        kept = [r for r in self.all_records()
                if not _match(r, direction, ktx_time, travel_date)]
        self.ws.clear()
        self.ws.append_row(HEADER, value_input_option='RAW')
        for r in kept:
            self.ws.append_row([r.get('name'), r.get('direction'), r.get('ktx_time'),
                                r.get('travel_date'), r.get('created_at')],
                               value_input_option='RAW')
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv/bin/pytest tests/test_storage.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add shuttle_system/config.py shuttle_system/storage.py tests/test_storage.py
git commit -m "feat: reservation store (memory + sheets) and secret config"
```

---

## Task 5: agents/data_agent.py (실시간 BIS API)

**Files:**
- Create: `shuttle_system/agents/data_agent.py`

> 외부 API 의존이라 단위 테스트는 생략(통합 시 Colab에서 실 키로 확인). 구현은 기존 노트북 셀3 로직 이전.

- [ ] **Step 1: 구현**

`shuttle_system/agents/data_agent.py`:
```python
"""실시간 Data Agent — 울산 BIS API에서 513 도착정보 조회."""
import xml.etree.ElementTree as ET
import requests

from shuttle_system.config import get_secret

BASE_URL = 'http://openapi.its.ulsan.kr/UlsanAPI'
USTEC_STOP_ID = '196040234'      # 울산과학기술원(울산역 방향)
ULSAN_ST_BACK_ID = '196015414'   # 울산역(캠퍼스 방향)


def _stop_id_for(direction):
    return USTEC_STOP_ID if direction == 'to_station' else ULSAN_ST_BACK_ID


def get_bus_arrival(stop_id, route_no_filter, api_key, num_of_rows=20):
    """해당 노선의 가장 빠른 도착 dict 또는 None."""
    url = f'{BASE_URL}/getBusArrivalInfo.xo'
    params = {'serviceKey': api_key, 'stopid': stop_id,
              'pageNo': 1, 'numOfRows': num_of_rows}
    resp = requests.get(url, params=params, timeout=8)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    candidates = []
    for row in root.iter('row'):
        route_nm = row.findtext('ROUTENM', '').strip()
        arrival_sec = row.findtext('ARRIVALTIME', '').strip()
        if route_nm == route_no_filter and arrival_sec.isdigit():
            candidates.append({
                'route': route_nm, 'arrival_sec': int(arrival_sec),
                'arrival_min': round(int(arrival_sec) / 60, 1),
                'present_stop': row.findtext('PRESENTSTOPNM', '').strip(),
                'stops_left': row.findtext('PREVSTOPCNT', '').strip(),
                'stop_name': row.findtext('STOPNM', '').strip()})
    if not candidates:
        return None
    return min(candidates, key=lambda c: c['arrival_sec'])


def fetch_513_arrival(direction):
    """실시간 513 도착. dict(found=bool, ...)."""
    if direction not in ('to_station', 'to_campus'):
        return {'error': "direction은 'to_station' 또는 'to_campus'"}
    api_key = get_secret('ULSAN_BIS_API_KEY')
    info = get_bus_arrival(_stop_id_for(direction), '513', api_key)
    if info is None:
        return {'found': False, 'note': '현재 도착 예정 513 없음'}
    return {'found': True, **info}
```

- [ ] **Step 2: import 확인**

Run: `.venv/bin/python -c "from shuttle_system.agents.data_agent import fetch_513_arrival; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add shuttle_system/agents/data_agent.py
git commit -m "feat: real-time data agent (Ulsan BIS 513 arrival)"
```

---

## Task 6: agents/notify_agent.py (추천 LLM + 택시 셰어)

**Files:**
- Create: `shuttle_system/agents/notify_agent.py`

> LLM 의존이라 단위 테스트는 생략. `taxi_share_logic`만 순수 함수로 분리해 store 주입으로 검증 가능하게 한다.

- [ ] **Step 1: 구현**

`shuttle_system/agents/notify_agent.py`:
```python
"""Notification/Recommendation Agent — 셔틀→513→택시 캐스케이드 추천.

LLM은 도구 반환값을 해석·서술만 한다(계산 금지). 개인화: 모델 임계값 N* 노출 + 택시 셰어.
"""
import json
from dataclasses import dataclass
from datetime import datetime

from openai import OpenAI

from shuttle_system.config import get_secret
from shuttle_system.core.optimization import breakeven_N, POLICY_FARE
from shuttle_system.core.schedule import find_shuttle_slot
from shuttle_system.core.connection import evaluate_connection, recommend_taxi
from shuttle_system.agents.data_agent import fetch_513_arrival

MODEL = 'gpt-4o-mini'


def _weekday_of(travel_date):
    if travel_date:
        return datetime.strptime(travel_date.strip(), '%Y-%m-%d').weekday()
    return datetime.now().weekday()


def taxi_share_logic(store, direction, ktx_time, travel_date, exclude_name=None):
    """같은 슬롯 예약자 기반 택시 셰어 후보 집계. 순수 로직(store 주입)."""
    names = [n for n in store.names(direction, ktx_time, travel_date)
             if n != exclude_name]
    n = len(names) + 1  # 본인 포함
    per_person = round(14000 / n) if n > 0 else 14000
    return {'companions': names, 'group_size': n,
            'est_total_krw': 14000, 'per_person_krw': per_person,
            'note': f'같은 {ktx_time} KTX 예약자 {len(names)}명 → {n}명 셰어 시 1인 약 {per_person}원'}


@dataclass
class StudentProfile:
    name: str
    direction: str
    ktx_time: str
    travel_date: str = None
    walk_to_stop_min: int = 5
    current_reservations: int = 0


class NotifyAgent:
    def __init__(self, store, fare=POLICY_FARE):
        self.store = store
        self.fare = fare
        self.client = OpenAI(api_key=get_secret('OPENAI_API_KEY'))
        self._tools = self._build_tools()

    def _build_tools(self):
        return {
            'find_shuttle': lambda direction, ktx_time, travel_date=None, reservations=0:
                json.dumps(find_shuttle_slot(direction, ktx_time,
                           _weekday_of(travel_date), reservations, self.fare),
                           ensure_ascii=False),
            'fetch_513_arrival': lambda direction:
                json.dumps(fetch_513_arrival(direction), ensure_ascii=False),
            'evaluate_connection': lambda direction, bus_arrival_min, ktx_time, walk_to_stop_min=5:
                json.dumps(evaluate_connection(direction, bus_arrival_min, ktx_time,
                           walk_to_stop_min), ensure_ascii=False, default=str),
            'recommend_taxi': lambda direction:
                json.dumps(recommend_taxi(direction), ensure_ascii=False),
            'find_taxi_share': lambda direction, ktx_time, travel_date:
                json.dumps(taxi_share_logic(self.store, direction, ktx_time, travel_date),
                           ensure_ascii=False),
        }

    def generate(self, profile, max_rounds=10):
        messages = [{'role': 'system', 'content': SYSTEM_PROMPT},
                    {'role': 'user', 'content': _profile_message(profile, self.fare)}]
        for _ in range(max_rounds):
            resp = self.client.chat.completions.create(
                model=MODEL, messages=messages, tools=TOOLS_SCHEMA)
            msg = resp.choices[0].message
            messages.append(msg)
            if not msg.tool_calls:
                return msg.content
            for tc in msg.tool_calls:
                args = json.loads(tc.function.arguments)
                result = self._tools[tc.function.name](**args)
                messages.append({'role': 'tool', 'tool_call_id': tc.id, 'content': result})
        return msg.content or '(도구 호출 한도 초과)'


def _profile_message(p, fare):
    dir_kr = ('울산과학기술원→울산역 (출발 KTX 탑승)' if p.direction == 'to_station'
              else '울산역→울산과학기술원 (KTX 하차 후 캠퍼스행)')
    return (f"학생: {p.name}\n방향: {dir_kr} (direction={p.direction})\n"
            f"KTX 시각: {p.ktx_time}\n여행 날짜: {p.travel_date or '오늘'}\n"
            f"정류장까지 도보: {p.walk_to_stop_min}분\n"
            f"조건부 셔틀 현재 예약: {p.current_reservations}명 (배차 임계 N*={breakeven_N(fare)})\n"
            f"위 학생에게 최적 교통수단을 우선순위대로 판단해 개인화 알림을 만들어줘.")


SYSTEM_PROMPT = """너는 UNIST ↔ 울산역 이동 학생에게 '최적 교통수단 1개'를 추천하는 에이전트다.
추천 우선순위(위에서부터 '이용 가능'한 첫 수단): 1순위 셔틀 → 2순위 513 → 3순위 택시.

[절차 — 한 번에 한 수단씩]
1) find_shuttle 호출. available=true면 셔틀 추천 후 종료.
   available=false이고 service='conditional'이면(예약<N*) find_taxi_share도 호출해 셰어 안내를 곁들인다.
2) available=false면 fetch_513_arrival 호출.
   found=true면 evaluate_connection으로 판정. SAFE/TIGHT/GOOD/LONG_WAIT면 513 추천 후 종료.
   MISS/BUS_TOO_SOON/BUS_BEFORE_READY거나 버스 없으면 3단계.
3) recommend_taxi 호출 → 택시 추천. find_taxi_share로 셰어 가능하면 함께 안내.

[작성 규칙]
- 시간/요일/요금 계산은 절대 직접 하지 말 것. 도구 반환값만 근거로.
- 최종 추천 수단 1개 + 핵심 시각/수치 + 한 줄 이유. 2~4문장, 친근, 이모지 1~2개.
- 조건부 셔틀이면 'N*' 임계값을 언급. 도구가 주지 않은 숫자/시각 금지."""


TOOLS_SCHEMA = [
    {'type': 'function', 'function': {
        'name': 'find_shuttle',
        'description': '1순위. 요일+KTX 시각에 배정된 셔틀편(고정/조건부) 조회.',
        'parameters': {'type': 'object', 'properties': {
            'direction': {'type': 'string', 'enum': ['to_station', 'to_campus']},
            'ktx_time': {'type': 'string'},
            'travel_date': {'type': 'string'},
            'reservations': {'type': 'integer'}}, 'required': ['direction', 'ktx_time']}}},
    {'type': 'function', 'function': {
        'name': 'fetch_513_arrival', 'description': '실시간 513 도착(BIS API).',
        'parameters': {'type': 'object', 'properties': {
            'direction': {'type': 'string', 'enum': ['to_station', 'to_campus']}},
            'required': ['direction']}}},
    {'type': 'function', 'function': {
        'name': 'evaluate_connection',
        'description': 'KTX와 513 도착 대조 연계 판정. 시간 계산은 반드시 이 도구로.',
        'parameters': {'type': 'object', 'properties': {
            'direction': {'type': 'string', 'enum': ['to_station', 'to_campus']},
            'bus_arrival_min': {'type': 'number'}, 'ktx_time': {'type': 'string'},
            'walk_to_stop_min': {'type': 'integer'}},
            'required': ['direction', 'bus_arrival_min', 'ktx_time']}}},
    {'type': 'function', 'function': {
        'name': 'recommend_taxi', 'description': '3순위 택시.',
        'parameters': {'type': 'object', 'properties': {
            'direction': {'type': 'string', 'enum': ['to_station', 'to_campus']}},
            'required': ['direction']}}},
    {'type': 'function', 'function': {
        'name': 'find_taxi_share',
        'description': '같은 슬롯(방향·KTX·날짜) 예약자 기반 택시 셰어 후보 집계.',
        'parameters': {'type': 'object', 'properties': {
            'direction': {'type': 'string', 'enum': ['to_station', 'to_campus']},
            'ktx_time': {'type': 'string'}, 'travel_date': {'type': 'string'}},
            'required': ['direction', 'ktx_time', 'travel_date']}}},
]
```

- [ ] **Step 2: 택시셰어 순수 로직 테스트 추가**

`tests/test_storage.py` 하단에 추가:
```python
def test_taxi_share_logic():
    from shuttle_system.agents.notify_agent import taxi_share_logic
    s = MemoryReservationStore()
    s.add('A', 'to_station', '13:58', '2026-06-05')
    s.add('B', 'to_station', '13:58', '2026-06-05')
    r = taxi_share_logic(s, 'to_station', '13:58', '2026-06-05', exclude_name='A')
    assert r['group_size'] == 2          # B + 본인
    assert 'B' in r['companions']
    assert r['per_person_krw'] == 7000
```

Run: `.venv/bin/pytest tests/test_storage.py -v`
Expected: PASS (4 passed)

- [ ] **Step 3: Commit**

```bash
git add shuttle_system/agents/notify_agent.py tests/test_storage.py
git commit -m "feat: notify agent with N* threshold + taxi-share matching"
```

---

## Task 7: agents/report_agent.py (집계 + 차트 + LLM 요약)

**Files:**
- Create: `shuttle_system/agents/report_agent.py`
- Test: `tests/test_report_agent.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_report_agent.py`:
```python
from shuttle_system.storage import MemoryReservationStore
from shuttle_system.agents.report_agent import compute_operations_report


def test_report_counts_and_net_benefit():
    s = MemoryReservationStore()
    # 금 13:58 고정편(출발)에 9명 예약 (날짜 2026-06-05 = 금)
    for i in range(9):
        s.add(f'U{i}', 'to_station', '13:58', '2026-06-05')
    rep = compute_operations_report(s, fare=2000)

    assert rep['total_runs'] >= 1
    assert rep['total_passengers'] >= 9
    # 9명 슬롯의 순편익은 양수 (b*9 - C)
    friday = [r for r in rep['slots']
              if r['slot'] == '금 오후' and r['direction'] == 'to_station'][0]
    assert friday['reservations'] == 9
    assert friday['dispatched'] is True
    assert friday['net_benefit'] > 0


def test_conditional_below_threshold_not_dispatched():
    s = MemoryReservationStore()
    # 목 13:58 조건부편에 3명 (2026-06-04 = 목)
    for i in range(3):
        s.add(f'U{i}', 'to_station', '13:58', '2026-06-04')
    rep = compute_operations_report(s, fare=2000)
    cond = [r for r in rep['slots']
            if r['slot'] == '목 오후' and r['direction'] == 'to_station'][0]
    assert cond['reservations'] == 3
    assert cond['dispatched'] is False   # 3 < N*(8)
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv/bin/pytest tests/test_report_agent.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 구현 (집계 + 차트 + LLM)**

`shuttle_system/agents/report_agent.py`:
```python
"""Report Agent — 관리자용 운영 리포트. 집계·차트는 코드, 서술은 LLM."""
from datetime import datetime

from shuttle_system.config import get_secret
from shuttle_system.core.optimization import breakeven_N, net_benefit, POLICY_FARE
from shuttle_system.core.connection import RIDE_MIN
from shuttle_system.core.schedule import all_slots

MODEL = 'gpt-4o-mini'
T_SAVED_MIN = 20  # 셔틀이 제거하는 513 연계 대기(분/인)


def compute_operations_report(store, fare=POLICY_FARE, travel_date=None):
    """예약 누적분을 슬롯별로 집계해 운행 여부·순편익·절감 대기시간 산출.

    travel_date=None이면 모든 날짜의 예약을 슬롯(요일+KTX+방향) 단위로 합산.
    """
    n_star = breakeven_N(fare)
    records = store.all_records()

    slot_rows = []
    total_runs = total_pax = total_net = total_wait_saved = 0
    for slot in all_slots():
        # 이 슬롯 요일과 일치하는 예약을 KTX시각·방향으로 합산
        target_wd = slot['wd']
        resv = sum(
            1 for r in records
            if str(r.get('direction')) == slot['direction']
            and str(r.get('ktx_time')) == slot['ktx']
            and _date_weekday(r.get('travel_date')) == target_wd
            and (travel_date is None or str(r.get('travel_date')) == travel_date))

        if slot['service'] == 'fixed':
            dispatched = resv > 0  # 고정편은 예약 있으면 운행(확정편)
        else:
            dispatched = resv >= n_star

        pax = resv if dispatched else 0
        nb = net_benefit(pax, fare) if dispatched else 0
        wait_saved = pax * T_SAVED_MIN

        if dispatched:
            total_runs += 1
            total_pax += pax
            total_net += nb
            total_wait_saved += wait_saved

        slot_rows.append({
            'service': slot['service'], 'direction': slot['direction'],
            'slot': slot['slot'], 'ktx': slot['ktx'],
            'reservations': resv, 'required': (n_star if slot['service'] == 'conditional' else 1),
            'dispatched': dispatched, 'net_benefit': round(nb),
            'wait_saved_min': wait_saved, 'survey_demand': slot.get('demand')})

    return {
        'fare': fare, 'n_star': n_star,
        'total_runs': total_runs, 'total_passengers': total_pax,
        'total_net_benefit': round(total_net),
        'total_wait_saved_hours': round(total_wait_saved / 60, 1),
        'slots': slot_rows,
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M')}


def _date_weekday(travel_date):
    try:
        return datetime.strptime(str(travel_date).strip(), '%Y-%m-%d').weekday()
    except (ValueError, AttributeError):
        return -1


def make_charts(report, out_dir='/content'):
    """슬롯별 (예약 vs N*) 막대 + (실현 순편익) 막대 2장을 PNG로 저장. 경로 리스트 반환."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    rows = report['slots']
    labels = [f"{r['slot']}\n{r['direction'][3:]}" for r in rows]

    # 차트1: 예약 vs N*
    fig1, ax1 = plt.subplots(figsize=(11, 4))
    resv = [r['reservations'] for r in rows]
    colors = ['#2e7d32' if r['dispatched'] else '#bdbdbd' for r in rows]
    ax1.bar(labels, resv, color=colors)
    ax1.axhline(report['n_star'], color='red', linestyle='--',
                label=f"N* = {report['n_star']}")
    ax1.set_title('슬롯별 예약 인원 vs 손익분기 N*')
    ax1.set_ylabel('예약 인원'); ax1.legend()
    plt.xticks(rotation=45, ha='right'); fig1.tight_layout()
    p1 = f'{out_dir}/report_reservations.png'; fig1.savefig(p1, dpi=120); plt.close(fig1)

    # 차트2: 실현 순편익
    fig2, ax2 = plt.subplots(figsize=(11, 4))
    nb = [r['net_benefit'] for r in rows]
    ax2.bar(labels, nb, color=['#1565c0' if v >= 0 else '#c62828' for v in nb])
    ax2.axhline(0, color='black', linewidth=0.8)
    ax2.set_title('슬롯별 실현 사회 순편익 (b·N − C)')
    ax2.set_ylabel('순편익(원)')
    plt.xticks(rotation=45, ha='right'); fig2.tight_layout()
    p2 = f'{out_dir}/report_net_benefit.png'; fig2.savefig(p2, dpi=120); plt.close(fig2)

    return [p1, p2]


def narrate_report(report):
    """집계 숫자를 LLM이 관리자용 서술 요약으로 변환. 계산은 하지 않는다."""
    from openai import OpenAI
    client = OpenAI(api_key=get_secret('OPENAI_API_KEY'))
    facts = {k: v for k, v in report.items() if k != 'slots'}
    facts['dispatched_slots'] = [
        {'slot': r['slot'], 'direction': r['direction'], 'reservations': r['reservations'],
         'net_benefit': r['net_benefit']} for r in report['slots'] if r['dispatched']]
    facts['skipped_conditional'] = [
        {'slot': r['slot'], 'reservations': r['reservations'], 'required': r['required']}
        for r in report['slots']
        if r['service'] == 'conditional' and not r['dispatched']]

    prompt = ("너는 셔틀 운영 관리자용 리포트를 쓰는 분석가다. 아래 JSON 집계 결과만 근거로 "
              "3~5문장 한국어 브리핑을 써라. 총 운행/수송/순편익/대기시간 절감을 먼저 요약하고, "
              "순편익 기여 1위 슬롯과 임계 미달로 미운행된 조건부 슬롯을 언급해라. "
              "숫자를 지어내지 말고 주어진 값만 사용. JSON: "
              f"{facts}")
    resp = client.chat.completions.create(
        model=MODEL, messages=[{'role': 'user', 'content': prompt}])
    return resp.choices[0].message.content
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv/bin/pytest tests/test_report_agent.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: 전체 테스트 회귀 확인**

Run: `.venv/bin/pytest -v`
Expected: PASS (전체 통과, 약 18개)

- [ ] **Step 6: Commit**

```bash
git add shuttle_system/agents/report_agent.py tests/test_report_agent.py
git commit -m "feat: report agent (aggregation + charts + LLM narration)"
```

---

## Task 8: app_student.py (학생용 Gradio)

**Files:**
- Create: `shuttle_system/app_student.py`

> Gradio UI라 단위 테스트 생략. Colab에서 실행 검증.

- [ ] **Step 1: 구현**

`shuttle_system/app_student.py`:
```python
"""학생용 Gradio 앱 — 예약 + 개인화 추천."""
from datetime import datetime
import gradio as gr

from shuttle_system.core.optimization import breakeven_N, POLICY_FARE
from shuttle_system.agents.notify_agent import NotifyAgent, StudentProfile

DIRECTION_MAP = {
    '울산역 방향 (캠퍼스→역, KTX 타러)': 'to_station',
    '캠퍼스 방향 (역→캠퍼스, KTX 하차 후)': 'to_campus',
}


def build_student_app(store, fare=POLICY_FARE):
    agent = NotifyAgent(store, fare=fare)
    n_star = breakeven_N(fare)

    def _norm(label, travel_date):
        direction = DIRECTION_MAP[label]
        travel_date = (travel_date or '').strip() or datetime.now().strftime('%Y-%m-%d')
        return direction, travel_date

    def _status(label, ktx, date):
        if not (ktx and ktx.strip()):
            return '예약 현황: KTX 시각을 입력하세요.'
        direction, date = _norm(label, date)
        ktx = ktx.strip()
        n = store.count(direction, ktx, date)
        names = store.names(direction, ktx, date)
        flag = '✅ 배차 충족' if n >= n_star else f'{max(0, n_star - n)}명 더 필요'
        return (f'📋 {date} · {ktx} · {label}\n예약 {n}/{n_star}명 ({flag})\n'
                f'예약자: {", ".join(names) or "없음"}')

    def _recommend(name, label, ktx, date):
        direction, date = _norm(label, date)
        ktx = ktx.strip()
        n = store.count(direction, ktx, date)
        profile = StudentProfile(name=(name or '학생').strip(), direction=direction,
                                 ktx_time=ktx, travel_date=date, current_reservations=n)
        try:
            return agent.generate(profile)
        except Exception as e:
            return f'❌ 처리 중 오류: {e}\n입력 형식 확인 (KTX HH:MM, 날짜 YYYY-MM-DD).'

    def on_reserve(name, label, ktx, date):
        if not (ktx and ktx.strip()):
            return '⚠️ KTX 시각(HH:MM)을 입력하세요.', '예약 현황: -'
        direction, d = _norm(label, date)
        store.add(name, direction, ktx.strip(), d)
        return _recommend(name, label, ktx, date), _status(label, ktx, date)

    def on_recommend_only(name, label, ktx, date):
        if not (ktx and ktx.strip()):
            return '⚠️ KTX 시각(HH:MM)을 입력하세요.', '예약 현황: -'
        return _recommend(name, label, ktx, date), _status(label, ktx, date)

    with gr.Blocks(title='UNIST 셔틀 추천 (학생용)') as demo:
        gr.Markdown(f'## 🚌 UNIST ↔ 울산역 추천 + 예약\n'
                    f'셔틀 → 513 → 택시 우선순위. **조건부 셔틀은 예약 N\\*={n_star}명 이상**이면 배차.')
        with gr.Row():
            name_in = gr.Textbox(label='이름', placeholder='홍길동')
            dir_in = gr.Radio(list(DIRECTION_MAP), label='방향',
                              value='울산역 방향 (캠퍼스→역, KTX 타러)')
        with gr.Row():
            ktx_in = gr.Textbox(label='KTX 시각 (HH:MM)', placeholder='13:58')
            date_in = gr.Textbox(label='날짜 (YYYY-MM-DD)',
                                 value=datetime.now().strftime('%Y-%m-%d'))
        with gr.Row():
            reserve_btn = gr.Button('✅ 예약하고 추천', variant='primary')
            rec_btn = gr.Button('🔎 추천만 보기')
        status_out = gr.Textbox(label='예약 현황', lines=3)
        rec_out = gr.Textbox(label='추천 결과', lines=5)

        full = [name_in, dir_in, ktx_in, date_in]
        reserve_btn.click(on_reserve, full, [rec_out, status_out])
        rec_btn.click(on_recommend_only, full, [rec_out, status_out])
    return demo
```

- [ ] **Step 2: import 확인**

Run: `.venv/bin/python -c "from shuttle_system.app_student import build_student_app; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add shuttle_system/app_student.py
git commit -m "feat: student gradio app (reserve + personalized recommendation)"
```

---

## Task 9: app_admin.py (관리자용 Gradio)

**Files:**
- Create: `shuttle_system/app_admin.py`

- [ ] **Step 1: 구현**

`shuttle_system/app_admin.py`:
```python
"""관리자용 Gradio 앱 — 운영 리포트(표 + 차트 + LLM 요약)."""
import gradio as gr

from shuttle_system.core.optimization import POLICY_FARE
from shuttle_system.agents.report_agent import (
    compute_operations_report, make_charts, narrate_report,
)


def build_admin_app(store, fare=POLICY_FARE, chart_dir='/content'):
    def generate():
        report = compute_operations_report(store, fare=fare)
        # 표 데이터
        headers = ['구분', '방향', '슬롯', 'KTX', '예약', '임계', '운행', '순편익(원)']
        table = [[r['service'], r['direction'], r['slot'], r['ktx'],
                  r['reservations'], r['required'],
                  '운행' if r['dispatched'] else '미운행', r['net_benefit']]
                 for r in report['slots']]
        summary = (f"총 운행 {report['total_runs']}회 · 수송 {report['total_passengers']}명 · "
                   f"순편익 ₩{report['total_net_benefit']:,} · "
                   f"대기 절감 {report['total_wait_saved_hours']}시간 (N*={report['n_star']})")
        try:
            charts = make_charts(report, out_dir=chart_dir)
        except Exception as e:
            charts = []
            summary += f'\n(차트 생성 오류: {e})'
        try:
            narration = narrate_report(report)
        except Exception as e:
            narration = f'(LLM 요약 오류: {e})'
        chart1 = charts[0] if len(charts) > 0 else None
        chart2 = charts[1] if len(charts) > 1 else None
        return summary, headers_table(headers, table), chart1, chart2, narration

    def headers_table(headers, rows):
        return {'headers': headers, 'data': rows}

    with gr.Blocks(title='UNIST 셔틀 운영 리포트 (관리자용)') as demo:
        gr.Markdown('## 🛠 UNIST 셔틀 운영 리포트\n예약 누적분을 OR 모델 기준으로 집계합니다.')
        gen_btn = gr.Button('📊 리포트 생성', variant='primary')
        summary_out = gr.Textbox(label='요약', lines=2)
        table_out = gr.Dataframe(label='슬롯별 운영 현황', interactive=False)
        with gr.Row():
            chart1_out = gr.Image(label='예약 vs N*')
            chart2_out = gr.Image(label='실현 순편익')
        narr_out = gr.Textbox(label='🧠 LLM 운영 브리핑', lines=6)
        gen_btn.click(generate, None,
                      [summary_out, table_out, chart1_out, chart2_out, narr_out])
    return demo
```

- [ ] **Step 2: import 확인**

Run: `.venv/bin/python -c "from shuttle_system.app_admin import build_admin_app; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add shuttle_system/app_admin.py
git commit -m "feat: admin gradio app (operations report dashboard)"
```

---

## Task 10: demo.ipynb (발표 시연 노트북)

**Files:**
- Create: `shuttle_system/demo.ipynb`

> 노트북은 모듈을 import만 한다. Colab Secrets(`OPENAI_API_KEY`, `ULSAN_BIS_API_KEY`) 필요.

- [ ] **Step 1: 노트북 셀 구성**

다음 셀들을 가진 `demo.ipynb` 생성:

셀 1 (설치):
```python
!pip install -q openai gradio gspread google-auth matplotlib requests
```

셀 2 (모듈 경로 + import):
```python
import sys; sys.path.insert(0, '/content/shuttle_system_repo')  # 레포 위치에 맞게 조정
from shuttle_system.storage import SheetsReservationStore
from shuttle_system.app_student import build_student_app
from shuttle_system.app_admin import build_admin_app
from shuttle_system.core.optimization import breakeven_N
print('N* (F=2000) =', breakeven_N(2000))  # 8
```

셀 3 (저장소 초기화 — Sheets):
```python
store = SheetsReservationStore()
print('Sheet:', store.url)
```

셀 4 (학생 앱):
```python
build_student_app(store).launch(share=True)
```

셀 5 (관리자 앱):
```python
build_admin_app(store).launch(share=True)
```

- [ ] **Step 2: 노트북 JSON 유효성 확인**

Run: `.venv/bin/python -c "import json; json.load(open('shuttle_system/demo.ipynb')); print('valid notebook')"`
Expected: `valid notebook`

- [ ] **Step 3: Commit**

```bash
git add shuttle_system/demo.ipynb
git commit -m "feat: demo notebook launching both student and admin apps"
```

---

## Task 11: README + 아키텍처 다이어그램

**Files:**
- Create: `shuttle_system/ARCHITECTURE.md`

- [ ] **Step 1: 아키텍처 문서 작성 (발표용)**

`shuttle_system/ARCHITECTURE.md`:
```markdown
# 시스템 아키텍처

## 데이터 흐름
KTX 시간표 + 513 시간표 + 설문
        ↓ (OR 모델: Z=Σxₜ(b·Nₜ−C), N*=⌈C/b⌉)
고정 8 + 조건부 5 슬롯 (F=2,000원 → N*=8)
        ↓
[학생 앱] 예약 → Google Sheets ← [관리자 앱] 집계
        ↓                              ↓
Notify Agent (셔틀/513/택시 + 택시셰어)   Report Agent (순편익·대기절감 + 차트 + LLM)

## 4개 에이전트
| 에이전트 | 책임 | LLM |
|---|---|---|
| Data Agent | 실시간 513 도착(BIS API) | X |
| (Demand) | 설문 수요 N → core가 사용 | X |
| Notify Agent | 개인화 추천 메시지 | O |
| Report Agent | 운영 리포트 서술 | O |

핵심: LLM은 계산하지 않는다. Python(core)이 OR 모델로 계산하고, 에이전트는 해석·전달한다.
```

- [ ] **Step 2: Commit**

```bash
git add shuttle_system/ARCHITECTURE.md
git commit -m "docs: architecture diagram for presentation"
```

---

## 완료 기준

- [ ] `.venv/bin/pytest -v` 전체 통과 (optimization·schedule·connection·storage·report)
- [ ] 로컬에서 모든 모듈 import 성공
- [ ] Colab에서 두 앱이 각각 launch되고, 학생 예약이 관리자 리포트에 반영됨 (Colab 실 키 필요 — 사용자 확인)
- [ ] N*=8이 학생 앱 안내·조건부 배차·리포트 임계에 일관 적용
