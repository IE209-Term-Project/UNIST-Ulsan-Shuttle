"""scripts/seed_promotion_demo.py

발표 시연용 종합 시드 — 두 가지를 동시 주입:

1. 직전 4주(2026-05-14 ~ 06-10) 예약 패턴
   Promotion Agent가 다음 호출 시 **2 promotions + 2 demotions** 권고를 산출하도록 설계.

2. 이번 주 금·토·일(2026-06-12 ~ 06-14) 예약 (설문 분포 기반)
   특정 조건부 슬롯은 7/8명으로 두어 **라이브에서 1명만 더 예약하면 N*=8 돌파**.

시연 시퀀스
  1) 이 스크립트 실행 → 데이터 주입
  2) GitHub Actions → Weekly Promotion Agent → Run workflow
     · 결과: 2 promotions + 2 demotions
     · 메일 도착: 주간 시간표 자동 개편 — 변경 4건
  3) 학생 앱에서 ⭐ 일 22:30 to_campus 예약 → N*=8 즉시 돌파 + 알림 에이전트 발동

주의
  · 본 스크립트는 schedule_overrides도 초기화 (이전 06-15 잘못된 baseline 제거).
  · semester_archive(25-2/24-2/23-2 모의 학기)는 건드리지 않음.
  · 발표 끝나면 clear_demo_archive.py 함께 실행 권장.

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
# 4주 히스토리 — 2 승격 + 2 강등 + 6 유지
# ─────────────────────────────────────────────
# 평가 기준: today=2026-06-11 → 윈도우 2026-05-14 ~ 2026-06-10
EVAL_DATE = datetime.strptime('2026-06-11', '%Y-%m-%d').date()
WINDOW_START = EVAL_DATE - timedelta(days=28)

HISTORY_PATTERN = [
    # (direction, weekday, time, count_per_week, label)
    #  weekday: 0=월 ~ 6=일

    # ⬆ 승격 후보 (현재 조건부, 평균 9명 × 4주 → avg 9 ≥ 8, rate 1.0 ≥ 0.75)
    ('to_station', 4, '09:10', 9, '★ 승격 → 금 오전 (신규 발견)'),
    ('to_campus',  6, '12:30', 9, '★ 승격 → 일 점심 (신규 발견)'),

    # ⬇ 강등 후보 (현재 고정, 평균 2명 × 4주 → avg 2 < 4, rate 0.0 ≤ 0.25)
    ('to_station', 5, '08:10', 2, '↓ 강등 → 토 오전 (저수요)'),
    ('to_campus',  6, '15:30', 2, '↓ 강등 → 일 오후 (저수요)'),

    # = 유지 (현재 고정, Dead Zone 4~7명)
    ('to_station', 4, '13:10', 6, '= 유지 → 금 오후'),
    ('to_station', 3, '18:10', 5, '= 유지 → 목 저녁'),
    ('to_station', 4, '18:10', 7, '= 유지 → 금 저녁'),
    ('to_campus',  0, '09:30', 5, '= 유지 → 월 오전'),
    ('to_campus',  6, '18:30', 6, '= 유지 → 일 저녁'),
    ('to_campus',  6, '21:30', 7, '= 유지 → 일 야간'),
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
# 이번 주 6/12-6/14 — 설문 분포 기반 + ⭐ 라이브 트리거 슬롯
# ─────────────────────────────────────────────
THIS_WEEK_DATA = [
    # (direction, date, time, count, note)

    # 6/12 (금)
    ('to_station', '2026-06-12', '13:10', 6, '금 오후 고정 — 6/12명'),
    ('to_station', '2026-06-12', '18:10', 8, '금 저녁 고정 — 8/12명'),

    # 6/13 (토)
    ('to_station', '2026-06-13', '08:10', 4, '토 오전 조건부 — 4명 (4명 더 필요)'),
    ('to_station', '2026-06-13', '13:10', 5, '토 오후 조건부 — 5명 (3명 더 필요)'),

    # 6/14 (일)
    ('to_campus',  '2026-06-14', '12:30', 6, '일 점심 조건부 — 6/8명 (2명 더 필요)'),
    ('to_campus',  '2026-06-14', '15:30', 5, '일 오후 고정 — 5/12명'),
    ('to_campus',  '2026-06-14', '18:30', 7, '일 저녁 고정 — 7/12명'),
    ('to_campus',  '2026-06-14', '21:30', 7, '일 야간 고정 — 7/12명'),
    ('to_campus',  '2026-06-14', '22:30', 7,
     '⭐ 일 늦은 야간 조건부 — 7/8명, 1명만 더 예약하면 N* 돌파 + 알림 에이전트 발동'),
]


# ─────────────────────────────────────────────
# 정리 헬퍼
# ─────────────────────────────────────────────
def collect_target_keys():
    """이 스크립트가 다루는 (direction, time, date) 키 집합."""
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
        # SheetsStore — 한 번의 clear() + append_rows
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
    """schedule_overrides 초기화 (이전 잘못된 06-15 baseline 제거)."""
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
    print('')

    # 0) 정리
    print('=== 0) 기존 demo 예약·overrides 정리 ===')
    removed = clean_existing(store)
    print(f'  · 기존 demo 슬롯 예약 {removed}건 제거')
    if clean_demo_overrides(store):
        print(f'  · schedule_overrides 초기화 (이전 06-15 baseline 제거)')
    print('')

    # 1) 4주 히스토리
    print('=== 1) 4주 히스토리 (Promotion Agent 평가 입력) ===')
    total_hist = 0
    for direction, wd, time, n, label in HISTORY_PATTERN:
        dates = dates_for_weekday(wd)
        rows = []
        for d in dates:
            for i in range(n):
                rows.append((f'Demo_{wd}{time.replace(":", "")}_{d[-5:].replace("-", "")}_{i}',
                             direction, time, d))
        store.add_many(rows)
        total_hist += len(rows)
        print(f'  {direction:11} {WD_KR[wd]} {time}: '
              f'{n}명/주 × 4주 = {len(rows)}건  {label}')
    print(f'  --- 4주 합계 {total_hist}건 ---')
    print('')

    # 2) 이번 주 6/12-6/14
    print('=== 2) 이번 주 6/12-6/14 (라이브 시연 입력) ===')
    total_week = 0
    for direction, date, time, n, note in THIS_WEEK_DATA:
        wd = datetime.strptime(date, '%Y-%m-%d').weekday()
        rows = [(f'Live_{date[-5:]}_{time.replace(":", "")}_{i}',
                 direction, time, date) for i in range(n)]
        store.add_many(rows)
        total_week += n
        print(f'  {date} ({WD_KR[wd]}) {direction:11} {time}: {n}명  {note}')
    print(f'  --- 이번 주 합계 {total_week}건 ---')
    print('')

    print('=' * 60)
    print('완료. 발표 진행 순서:')
    print('  ① Run workflow (GitHub Actions)')
    print('     → 2 promotions + 2 demotions 산출')
    print('     → 메일: "주간 시간표 자동 개편 — 변경 4건" 도착')
    print('  ② 학생 앱에서 ⭐ 6/14 일요일 22:30 to_campus 예약')
    print('     → 8번째 예약자 발생 → 알림 에이전트 발동')
    print('     → 단체 운행 확정 메일 발송')
    print('  ③ 관리자 대시보드에서 🎓 다음 학기 시간표 편성 미리보기')
    print('     → 모의 archive 기반 EWMA 결과 시연')


if __name__ == '__main__':
    main()
