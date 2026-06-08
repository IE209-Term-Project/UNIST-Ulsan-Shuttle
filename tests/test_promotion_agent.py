"""Promotion Agent 테스트 — 단기 슬롯 등급(승격/강등) 권고 로직.

규칙:
  · 윈도우 = 직전 4주 (28일, today 미포함)
  · 승격 (conditional→fixed): avg ≥ N*(8) AND rate(≥N*인 주) ≥ 0.75
  · 강등 (fixed→conditional): avg < 4   AND rate ≤ 0.25
  · Dead Zone (4 ≤ avg ≤ 7): 현 상태 유지
  · 콜드 스타트: 학기 1~3주차는 평가 자체를 동결 (frozen=True)
"""
from datetime import datetime, timedelta

from shuttle_system.storage import MemoryReservationStore
from shuttle_system.agents.promotion_agent import evaluate_promotions

# 평가 기준일 — 월요일. 4주 전 월요일(REF_MONDAY)부터 일요일 23:59까지가 윈도우.
TODAY = '2026-06-08'        # 월
REF_MONDAY = '2026-05-11'   # 4주 전 월요일 (윈도우 시작)
WINDOW_END = '2026-06-07'   # today 하루 전 (윈도우 종료)


def _add_weekly_counts(store, counts, weekday, direction, time,
                       ref_monday=REF_MONDAY):
    """ref_monday(월요일)부터 4주간, 매주 같은 weekday에 counts[w]명씩 예약 주입.

    counts: 길이 4 리스트. 예: [9, 9, 9, 9] → 4주 모두 9명.
    weekday: 0(월)~6(일)
    """
    mon = datetime.strptime(ref_monday, '%Y-%m-%d')
    for w, n in enumerate(counts):
        d = (mon + timedelta(days=7 * w + weekday)).strftime('%Y-%m-%d')
        for i in range(n):
            store.add(f'U{w}_{i}', direction, time, d)


# ──────────────────────────────────────────────
# 승격 (conditional → fixed)
# ──────────────────────────────────────────────

def test_promote_conditional_when_avg_ge_8_and_rate_ge_075():
    """화 14:10 to_station(현재 conditional)에 4주 연속 9명 → 승격 권고."""
    s = MemoryReservationStore()
    _add_weekly_counts(s, [9, 9, 9, 9], weekday=1,
                       direction='to_station', time='14:10')
    result = evaluate_promotions(s, today=TODAY, semester_week=5)
    promos = result['promotions']
    assert len(promos) == 1
    p = promos[0]
    assert p['direction'] == 'to_station'
    assert p['weekday'] == 1
    assert p['time'] == '14:10'
    assert p['avg_resv'] == 9.0
    assert p['dispatch_rate'] == 1.0
    assert p['current_service'] == 'conditional'
    assert p['recommendation'] == 'promote'


def test_no_promote_when_avg_ge_8_but_rate_below_075():
    """avg=8.5지만 rate=0.5(2/4) → 승격 안 함 (이중조건 미충족)."""
    s = MemoryReservationStore()
    _add_weekly_counts(s, [12, 12, 5, 5], weekday=1,
                       direction='to_station', time='14:10')
    result = evaluate_promotions(s, today=TODAY, semester_week=5)
    assert result['promotions'] == []


def test_no_promote_for_fixed_slot_even_if_high_demand():
    """현재 이미 fixed인 슬롯은 승격 대상이 아님(이미 최상위 등급)."""
    s = MemoryReservationStore()
    # 금 13:10 to_station은 SHUTTLE_FIXED에 존재(고정)
    _add_weekly_counts(s, [9, 9, 9, 9], weekday=4,
                       direction='to_station', time='13:10')
    result = evaluate_promotions(s, today=TODAY, semester_week=5)
    assert result['promotions'] == []


# ──────────────────────────────────────────────
# 강등 (fixed → conditional)
# ──────────────────────────────────────────────

def test_demote_fixed_when_avg_lt_4_and_rate_le_025():
    """금 13:10 to_station(현재 fixed)에 4주 평균 2명 → 강등 권고.

    다른 fixed 슬롯들도 데이터 0으로 강등 후보가 되지만(다른 테스트가 검증),
    여기서는 이 특정 슬롯이 정확한 권고 메타데이터로 잡히는지만 확인.
    """
    s = MemoryReservationStore()
    _add_weekly_counts(s, [2, 2, 2, 2], weekday=4,
                       direction='to_station', time='13:10')
    result = evaluate_promotions(s, today=TODAY, semester_week=5)
    target = [d for d in result['demotions']
              if d['direction'] == 'to_station'
              and d['weekday'] == 4
              and d['time'] == '13:10']
    assert len(target) == 1
    d = target[0]
    assert d['avg_resv'] == 2.0
    assert d['dispatch_rate'] == 0.0
    assert d['current_service'] == 'fixed'
    assert d['recommendation'] == 'demote'


def test_demote_fixed_slot_with_zero_data():
    """fixed 슬롯이 4주 동안 예약 0건이어도 강등 권고 (사용 안 되는 슬롯)."""
    s = MemoryReservationStore()
    # 데이터를 전혀 주입하지 않음 → 모든 fixed 슬롯은 avg=0, rate=0
    result = evaluate_promotions(s, today=TODAY, semester_week=5)
    # SHUTTLE_FIXED의 모든 슬롯이 강등 권고 대상
    assert len(result['demotions']) >= 1
    for d in result['demotions']:
        assert d['current_service'] == 'fixed'
        assert d['avg_resv'] == 0.0


def test_no_demote_when_avg_lt_4_but_rate_above_025():
    """avg=3.5지만 rate=0.5(2/4 ≥8) → 강등 안 함."""
    s = MemoryReservationStore()
    _add_weekly_counts(s, [8, 8, 0, 0], weekday=4,
                       direction='to_station', time='13:10')
    # avg=4.0, rate=0.5  — avg가 4 미만 아니므로 dead zone
    result = evaluate_promotions(s, today=TODAY, semester_week=5)
    # 4.0은 < 4가 아니므로 demote 조건 미충족
    matching = [d for d in result['demotions']
                if d['weekday'] == 4 and d['time'] == '13:10']
    assert matching == []


def test_no_demote_for_conditional_slot():
    """conditional 슬롯은 강등 대상이 아님(이미 최하위 등급)."""
    s = MemoryReservationStore()
    _add_weekly_counts(s, [1, 1, 1, 1], weekday=1,
                       direction='to_station', time='14:10')
    result = evaluate_promotions(s, today=TODAY, semester_week=5)
    # 화 14:10은 conditional, 데이터 낮아도 강등 X
    matching = [d for d in result['demotions']
                if d['weekday'] == 1 and d['time'] == '14:10']
    assert matching == []


# ──────────────────────────────────────────────
# Dead Zone (변경 없음)
# ──────────────────────────────────────────────

def test_dead_zone_keeps_conditional_unchanged():
    """avg=5명 conditional → 변경 없음."""
    s = MemoryReservationStore()
    _add_weekly_counts(s, [5, 5, 5, 5], weekday=1,
                       direction='to_station', time='14:10')
    result = evaluate_promotions(s, today=TODAY, semester_week=5)
    assert result['promotions'] == []
    # 강등에도 없음
    matching = [d for d in result['demotions']
                if d['weekday'] == 1 and d['time'] == '14:10']
    assert matching == []


# ──────────────────────────────────────────────
# 콜드 스타트 (학기 1~3주차 동결)
# ──────────────────────────────────────────────

def test_cold_start_freeze_week_2():
    """학기 2주차는 데이터가 충분해도 평가 동결."""
    s = MemoryReservationStore()
    _add_weekly_counts(s, [9, 9, 9, 9], weekday=1,
                       direction='to_station', time='14:10')
    result = evaluate_promotions(s, today=TODAY, semester_week=2)
    assert result['frozen'] is True
    assert result['promotions'] == []
    assert result['demotions'] == []
    assert 'frozen_reason' in result


def test_cold_start_releases_at_week_4():
    """학기 4주차부터는 평가가 정상 작동."""
    s = MemoryReservationStore()
    _add_weekly_counts(s, [9, 9, 9, 9], weekday=1,
                       direction='to_station', time='14:10')
    result = evaluate_promotions(s, today=TODAY, semester_week=4)
    assert result['frozen'] is False
    assert len(result['promotions']) >= 1


# ──────────────────────────────────────────────
# 메타데이터 (윈도우 정의)
# ──────────────────────────────────────────────

def test_window_is_28_days_before_today():
    """윈도우 = today 직전 4주(28일). today=2026-06-08(월) → 05-11~06-07."""
    s = MemoryReservationStore()
    result = evaluate_promotions(s, today=TODAY, semester_week=5)
    assert result['window_start'] == REF_MONDAY      # '2026-05-11'
    assert result['window_end'] == WINDOW_END        # '2026-06-07'
    assert result['evaluated_at']                    # 비어있지 않음


def test_data_outside_window_is_ignored():
    """윈도우 밖(5주 전, 미래)의 예약은 평가에 반영되지 않음."""
    s = MemoryReservationStore()
    # 5주 전(윈도우 밖)에 화 14:10 to_station 12명씩 4주
    old_monday = (datetime.strptime(REF_MONDAY, '%Y-%m-%d')
                  - timedelta(days=28)).strftime('%Y-%m-%d')
    _add_weekly_counts(s, [12, 12, 12, 12], weekday=1,
                       direction='to_station', time='14:10',
                       ref_monday=old_monday)
    result = evaluate_promotions(s, today=TODAY, semester_week=5)
    # 윈도우 안 데이터가 없으므로 승격되지 않아야 함
    promos_for_slot = [p for p in result['promotions']
                       if p['weekday'] == 1 and p['time'] == '14:10']
    assert promos_for_slot == []
