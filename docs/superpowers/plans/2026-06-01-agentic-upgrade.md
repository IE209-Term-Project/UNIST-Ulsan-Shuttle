# 에이전틱 개선 + 시간표 반영 — 구현 계획

**Goal:** 시간표 기반 선택 UI, LLM 자율 예약+카풀, 능동 알림 에이전트를 추가해 시스템을 더 에이전틱하게 만든다.

**원칙 유지:** LLM은 OR 계산을 하지 않는다(코드가 계산). LLM은 판단·행동·서술.

---

## 3단계 구성

### 1단계: 시간표 선택 + 예약 인원 표시 + 두 입력 모드
- `shuttle_system/data/timetable.json` (KTX·SRT 울산 정차 시각, 5.15 기준) — 이미 추출됨
- `shuttle_system/timetable.py`: JSON 로드 + 방면별 시각 옵션 제공
- **입력 모드 2종:**
  - A. 기차 연계: `방면` + `KTX/SRT 시각 드롭다운` → 기존 find_shuttle(ktx_time)
  - B. 단순 이동: `출발 희망 시각` 입력 → `find_shuttle_near`(셔틀 출발시각 ±30분 최근접 슬롯)
- 모드 B가 슬롯을 찾으면 그 슬롯의 ktx_time으로 예약(같은 슬롯 N* 카운트에 합류)
- 시각 선택/입력 시 "현재 예약 N명" 표시 (store.count)
- `schedule.find_shuttle_near(direction, desired_time, weekday, window_min=30)` 추가

### 2단계: 자율 예약 + 카풀
- `notify_agent`에 행동 도구 `make_reservation`, `cancel_reservation` 추가
- 카풀: 셔틀 미운행 + 같은 슬롯 예약자 ≥1명 → 카풀 추천 (`find_taxi_share` 활용, 임계 1명)
- 버튼=즉시: 학생이 요청하면 LLM이 분석 후 셔틀 슬롯이면 예약, 아니면 513/카풀 추천

### 3단계: 알림 에이전트 (앱 내 피드)
- 저장소: `notifications` 워크시트 + Memory 구현
- 감지(`run_notification_check`): ①조건부 N*=8 돌파 ②카풀 매칭(≥2명, 미운행) ③513 지연(+시뮬)
- 중복 차단: 알림 로그에 (type, slot, date) 존재하면 skip
- 시점: 예약 직후 + 주기 폴링 + "지금 체크" 버튼
- LLM: 이벤트 → 메시지 작성
- 표시: 학생·관리자 앱 🔔 피드

---

## 데이터/타입 규약
- 예약 슬롯 키: (direction ∈ {to_station,to_campus}, ktx_time 'HH:MM', travel_date 'YYYY-MM-DD')
- 시간표: `seoul_bound`/`busan_bound` 각 {KTX:[...], SRT:[...]}
- 알림 레코드: {created_at, type ∈ {dispatch,carpool,delay}, direction, ktx_time, travel_date, message}

각 단계 완료 시 테스트 통과 + 커밋. 단계는 독립적으로 동작 가능.
