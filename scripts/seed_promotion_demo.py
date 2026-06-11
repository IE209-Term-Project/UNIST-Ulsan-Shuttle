"""scripts/seed_promotion_demo.py

발표 시연용 종합 시드 — 다음 3가지 동시 달성:

1. Promotion Agent가 **2 promotions + 2 demotions** 권고를 산출
2. 관리자 대시보드의 **순편익이 모든 필터에서 양수** (≥8명 = 손익분기)
3. 6/12-6/14에 학생 이동 형태 반영한 조건부 슬롯 색깔 추가
   특히 ⭐ 6/14 일 22:30 to_campus 7/8명 → 라이브에서 1명 예약 → N* 돌파

시연 시퀀스
  1) 이 스크립트 실행 → 데이터 주입
  2) GitHub Actions → Weekly Promotion Agent → Run workflow
  3) 학생 앱에서 ⭐ 6/14 일 22:30 to_campus 예약 → 알림 에이전트 발동

순편익 설계
  b = 4,983원/명, C = 35,000원 → 손익분기 N* = 8
  · 운행하는 fixed/conditional 슬롯은 모두 ≥8명 → 슬롯당 +4,864원
  · 강등 후보 fixed 슬롯은 0명 → 운행 안 됨, 음수 기여 없음
  · 조건부 미달 슬롯(<8명)은 운행 안 됨, 차트만 채움

실행:
  .venv/bin/python scripts/seed_promotion_demo.py
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shuttle_system.storage import (
    make_store, HEADER, SCHEDULE_OVERRIDES_HEADER,
)


# ─────────────────────────────────────────────
# 평가 기준: today=2026-06-11 → 윈도우 2026-05-14 ~ 2026-06-10
# ─────────────────────────────────────────────
EVAL_DATE = datetime.strptime('2026-06-11', '%Y-%m-%d').date()
WINDOW_START = EVAL_DATE - timedelta(days=28)


# ─────────────────────────────────────────────
# 4주 히스토리 — 2 승격 + 2 강등 + 6 유지, 모두 손익분기 통과
# ─────────────────────────────────────────────
HISTORY_PATTERN = [
    # (direction, weekday, time, count_per_week, label)

    # ⬆ 승격 (현재 조건부, 9명 × 4주 → avg 9, rate 1.0)
    ('to_station', 4, '09:10', 9, '★ 승격 → 금 오전 (신규 발견)'),
    ('to_campus',  6, '12:30', 9, '★ 승격 → 일 점심 (신규 발견)'),

    # = 유지 (현재 고정, 8명 × 4주 → avg 8, 손익분기 통과)
    ('to_station', 4, '13:10', 8, '= 유지 → 금 오후 (손익분기)'),
    ('to_station', 3, '18:10', 8, '= 유지 → 목 저녁 (손익분기)'),
    ('to_station', 4, '18:10', 8, '= 유지 → 금 저녁 (손익분기)'),
    ('to_campus',  0, '09:30', 8, '= 유지 → 월 오전 (손익분기)'),
    ('to_campus',  6, '18:30', 8, '= 유지 → 일 저녁 (손익분기)'),
    ('to_campus',  6, '21:30', 8, '= 유지 → 일 야간 (손익분기)'),

    # ⬇ 강등 (현재 고정, 데이터 0명 → 자동 강등, 운행 안 돼서 순편익 음수 없음)
    ('to_station', 5, '08:10', 0, '↓ 강등 → 토 오전 (수요 0, 운행 안 됨)'),
    ('to_campus',  6, '15:30', 0, '↓ 강등 → 일 오후 (수요 0, 운행 안 됨)'),
]


def dates_for_weekday(wd):
    """28일 윈도우 안의 해당 요일 날짜 4개."""
    out = []
    for offset in range(28):
        d = WINDOW_START + timedelta(days=offset)
        if d.weekday() == wd:
            out.append(d.strftime('%Y-%m-%d'))
    return out


# ─────────────────────────────────────────────
# 이번 주 6/12-6/14 — 설문 분포 + 학생 이동 형태 반영
# ─────────────────────────────────────────────
THIS_WEEK_DATA = [
    # (direction, date, time, count, note)

    # ─── 6/12 (금) — 학생들 집으로 (KTX 연계) ───
    ('to_station', '2026-06-12', '11:10', 2,
     '금 점심 KTX 연계 (조건부 2명)'),
    ('to_station', '2026-06-12', '13:10', 8,
     '금 오후 고정 — 8/12명 (손익분기 통과)'),
    ('to_station', '2026-06-12', '16:10', 3,
     '금 오후 KTX 연계 (조건부 3명)'),
    ('to_station', '2026-06-12', '18:10', 8,
     '금 저녁 고정 — 8/12명 (손익분기 통과)'),
    ('to_station', '2026-06-12', '20:10', 3,
     '금 저녁 KTX 연계 (조건부 3명)'),
    ('to_station', '2026-06-12', '21:10', 2,
     '금 밤 KTX 연계 (조건부 2명)'),

    # ─── 6/13 (토) — 활동 적음 ───
    ('to_station', '2026-06-13', '08:10', 0,
     '토 오전 — 수요 없음 (강등 일관성)'),
    ('to_station', '2026-06-13', '10:10', 2,
     '토 오전 외출 (조건부 2명)'),
    ('to_station', '2026-06-13', '13:10', 5,
     '토 오후 (조건부 5명, 3명 더 필요)'),
    ('to_station', '2026-06-13', '17:10', 2,
     '토 저녁 외출 (조건부 2명)'),

    # ─── 6/14 (일) — 학생들 학교로 복귀 ───
    ('to_campus',  '2026-06-14', '12:30', 6,
     '일 점심 (조건부 6/8명, 2명 더 필요)'),
    ('to_campus',  '2026-06-14', '13:30', 2,
     '일 점심 도착 (조건부 2명)'),
    ('to_campus',  '2026-06-14', '15:30', 0,
     '일 오후 — 수요 없음 (강등 일관성)'),
    ('to_campus',  '2026-06-14', '16:30', 2,
     '일 오후 도착 (조건부 2명)'),
    ('to_campus',  '2026-06-14', '18:30', 8,
     '일 저녁 고정 — 8/12명 (손익분기 통과)'),
    ('to_campus',  '2026-06-14', '19:30', 3,
     '일 저녁 도착 (조건부 3명)'),
    ('to_campus',  '2026-06-14', '20:30', 2,
     '일 밤 도착 (조건부 2명)'),
    ('to_campus',  '2026-06-14', '21:30', 8,
     '일 야간 고정 — 8/12명 (손익분기 통과)'),
    ('to_campus',  '2026-06-14', '22:30', 7,
     '⭐ 일 늦은 야간 조건부 — 7/8명, 1명만 더 예약하면 N* 돌파'),
]


# ─────────────────────────────────────────────
# 정리 헬퍼
# ─────────────────────────────────────────────
def collect_target_keys():
    """이 스크립트가 다루는 (direction, time, date) 키 집합 (count=0 포함)."""
    keys = set()
    for direction, wd, time, _, _ in HISTORY_PATTERN:
        for d in dates_for_weekday(wd):
            keys.add((direction, time, d))
    for direction, date, time, _, _ in THIS_WEEK_DATA:
        keys.add((direction, time, date))
    return keys


def clean_existing(store):
    """대상 슬롯·날짜의 기존 예약 일괄 제거 (1회 재기록 → Sheets quota 절약)."""
    targets = collect_target_keys()
    records = store.all_records()
    kept = [r for r in records
            if (str(r.get('direction', '')),
                str(r.get('train_time', '')),
                str(r.get('travel_date', ''))) not in targets]
    removed = len(records) - len(kept)

    if hasattr(store, 'ws'):
        store.ws.clear()
        rows = [HEADER]
        for r in kept:
            rows.append([r.get('name'), r.get('email', ''),
                         r.get('direction'), r.get('train_time'),
                         r.get('travel_date'), r.get('created_at')])
        store.ws.append_rows(rows, value_input_option='RAW')
    else:
        store._rows = kept

    return removed


def clean_demo_overrides(store):
    """schedule_overrides 초기화."""
    if hasattr(store, 'overrides_ws'):
        store.overrides_ws.clear()
        store.overrides_ws.append_row(
            SCHEDULE_OVERRIDES_HEADER, value_input_option='RAW')
        return True
    if hasattr(store, '_overrides'):
        store._overrides = []
        return True
    return False


# ─────────────────────────────────────────────
# 메인
# ─────────────────────────────────────────────
def main():
    WD_KR = '월화수목금토일'

    store = make_store()
    print(f'store = {type(store).__name__}')
    print(f'평가 기준일: {EVAL_DATE}')
    print(f'4주 윈도우: {WINDOW_START} ~ {EVAL_DATE - timedelta(days=1)}')
    print('손익분기 N* = 8명 → 운행 슬롯당 순편익 = +4,864원')
    print('')

    # 0) 정리
    print('=== 0) 기존 demo 예약·overrides 정리 ===')
    removed = clean_existing(store)
    print(f'  · 기존 demo 슬롯 예약 {removed}건 제거')
    if clean_demo_overrides(store):
        print(f'  · schedule_overrides 초기화')
    print('')

    # 1) 4주 히스토리
    print('=== 1) 4주 히스토리 (Promotion Agent 평가 입력) ===')
    total_hist = 0
    weekly_net = 0
    for direction, wd, time, n, label in HISTORY_PATTERN:
        dates = dates_for_weekday(wd)
        rows = []
        for d in dates:
            for i in range(n):
                rows.append((
                    f'Demo_{wd}{time.replace(":", "")}_{d[-5:].replace("-", "")}_{i}',
                    direction, time, d))
        if rows:
            store.add_many(rows)
        total_hist += len(rows)
        # 슬롯 1회당 순편익 (해당 슬롯이 운행될 때)
        if n >= 8:
            nb_per_week = n * 4983 - 35000
            weekly_net += nb_per_week
        print(f'  {direction:11} {WD_KR[wd]} {time}: '
              f'{n}명/주 × 4주 = {len(rows)}건  {label}')
    print(f'  --- 4주 합계: {total_hist}건 예약, '
          f'주당 운행 순편익 ≈ +{weekly_net:,}원 ---')
    print('')

    # 2) 이번 주 6/12-6/14
    print('=== 2) 이번 주 6/12-6/14 (라이브 시연 입력) ===')
    total_week = 0
    week_net = 0
    for direction, date, time, n, note in THIS_WEEK_DATA:
        wd = datetime.strptime(date, '%Y-%m-%d').weekday()
        rows = [(f'Live_{date[-5:]}_{time.replace(":", "")}_{i}',
                 direction, time, date) for i in range(n)]
        if rows:
            store.add_many(rows)
        total_week += n
        if n >= 8:
            week_net += n * 4983 - 35000
        print(f'  {date} ({WD_KR[wd]}) {direction:11} {time}: '
              f'{n:>2}명  {note}')
    print(f'  --- 이번 주 합계: {total_week}건 예약, '
          f'운행 순편익 ≈ +{week_net:,}원 ---')
    print('')

    print('=' * 60)
    print('완료. 발표 진행 순서:')
    print('  ① Run workflow (GitHub Actions)')
    print('     → 2 promotions + 2 demotions 산출')
    print('     → 메일: "주간 시간표 자동 개편 — 변경 4건"')
    print('  ② 학생 앱에서 ⭐ 6/14 일 22:30 to_campus 예약')
    print('     → 8번째 예약자 → 알림 에이전트 발동')
    print('     → 단체 운행 확정 메일 발송')
    print('  ③ 관리자 대시보드 — 어떤 필터를 골라도 순편익 양수')
    print('     · 전체 누적 / 이번 주 / 지난 주 / 최근 4주 모두 ≥0')
    print('  ④ 관리자 🎓 다음 학기 시간표 편성 → 🔍 미리보기')
    print('     → EWMA(0.5/0.3/0.2) 기반 2026-2 baseline')


if __name__ == '__main__':
    main()
