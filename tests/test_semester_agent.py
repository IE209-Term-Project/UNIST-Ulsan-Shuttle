"""장기 Semester Agent — archive 적재 + 동일학기 지수가중 baseline 도출.

archive_semester: 학기 종료 시 슬롯별 평균/운행률을 semester_archive에 적재.
generate_next_baseline: 동일학기명(예: 25-1 ← 24-1, 23-1, 22-1) 0.5/0.3/0.2 가중평균.
                       데이터 부족 시 정규화, 완전히 비면 fallback(=하드코딩) 사용.
"""
from datetime import timedelta, datetime
from shuttle_system.storage import MemoryReservationStore
from shuttle_system.agents.semester_agent import (
    archive_semester, generate_next_baseline,
)
from shuttle_system.core.semester import semester_start_date


def _seed_reservations_in_semester(store, year, term, slot_specs):
    """학기 N주차 화요일 등에 예약 주입.

    slot_specs: [(week_idx, weekday, direction, time, n_people), ...]
      week_idx: 1..16
    """
    start = semester_start_date(year, term)
    for w, wd, direction, time, n in slot_specs:
        d = (start + timedelta(days=(w - 1) * 7 + wd)).strftime('%Y-%m-%d')
        for i in range(n):
            store.add(f'U{w}_{wd}_{i}', direction, time, d)


# ── archive_semester ────────────────────────────────

def test_archive_groups_by_slot_and_computes_avg():
    """같은 슬롯 4주 데이터 → avg_resv = (합/주차수)."""
    s = MemoryReservationStore()
    # 화요일 14:10 to_station에 1, 2, 3주차 각 9명 (3주만 출현)
    _seed_reservations_in_semester(s, 2025, 1, [
        (1, 1, 'to_station', '14:10', 9),
        (2, 1, 'to_station', '14:10', 9),
        (3, 1, 'to_station', '14:10', 9),
    ])
    archive_semester(s, '2025-1', n_star=8)
    rows = s.get_semester_archive()
    matching = [r for r in rows
                if r['direction'] == 'to_station'
                and int(r['weekday']) == 1
                and r['shuttle_time'] == '14:10']
    assert len(matching) == 1
    assert float(matching[0]['avg_resv']) == 9.0
    assert float(matching[0]['dispatch_rate']) == 1.0
    assert matching[0]['semester_id'] == '2025-1'


def test_archive_dispatch_rate_partial():
    """4주 중 2주만 N* 충족 → dispatch_rate = 0.5."""
    s = MemoryReservationStore()
    _seed_reservations_in_semester(s, 2025, 1, [
        (1, 1, 'to_station', '14:10', 9),    # 충족
        (2, 1, 'to_station', '14:10', 8),    # 충족
        (3, 1, 'to_station', '14:10', 5),    # 미달
        (4, 1, 'to_station', '14:10', 3),    # 미달
    ])
    archive_semester(s, '2025-1', n_star=8)
    rows = s.get_semester_archive()
    m = [r for r in rows if r['shuttle_time'] == '14:10'][0]
    assert float(m['avg_resv']) == 6.25
    assert float(m['dispatch_rate']) == 0.5


def test_archive_ignores_non_grid_times():
    """:10/:30 그리드가 아닌 시각은 적재하지 않음."""
    s = MemoryReservationStore()
    _seed_reservations_in_semester(s, 2025, 1, [
        (1, 1, 'to_station', '14:25', 9),  # 비그리드
    ])
    archive_semester(s, '2025-1', n_star=8)
    assert s.get_semester_archive() == []


# ── generate_next_baseline ─────────────────────────

def _fallback_table():
    return {
        'to_station': [
            {'slot': '금 오후', 'wd': 4, 'shuttle': '13:10', 'demand': 57}
        ],
        'to_campus': [
            {'slot': '월 오전', 'wd': 0, 'shuttle': '09:30', 'demand': 31}
        ],
    }


def test_generate_returns_fallback_when_archive_empty():
    """archive에 데이터가 없으면 fallback(하드코딩) 그대로."""
    s = MemoryReservationStore()
    out = generate_next_baseline(s, target_semester_id='2026-1',
                                 n_star=8, fallback_table=_fallback_table())
    assert out['used_fallback'] is True
    assert out['baseline']['to_station'][0]['shuttle'] == '13:10'


def test_generate_picks_slots_above_n_star_from_single_past_semester():
    """과거 학기 1개에서 avg ≥ N*인 슬롯들이 새 baseline 후보."""
    s = MemoryReservationStore()
    # 2025-1 학기: 두 슬롯 각각 9명/3명 평균
    s.add_semester_archive_rows([
        {'semester_id': '2025-1', 'direction': 'to_station',
         'weekday': 1, 'shuttle_time': '14:10', 'slot_label': '화 14:10',
         'avg_resv': 9.0, 'dispatch_rate': 1.0, 'recorded_at': '2025-06-22'},
        {'semester_id': '2025-1', 'direction': 'to_station',
         'weekday': 2, 'shuttle_time': '10:10', 'slot_label': '수 10:10',
         'avg_resv': 3.0, 'dispatch_rate': 0.0, 'recorded_at': '2025-06-22'},
    ])
    out = generate_next_baseline(s, target_semester_id='2026-1',
                                 n_star=8, fallback_table=_fallback_table())
    assert out['used_fallback'] is False
    times = [e['shuttle'] for e in out['baseline']['to_station']]
    assert '14:10' in times          # 9명 → 채택
    assert '10:10' not in times      # 3명 → 탈락


def test_generate_exponential_weighted_average_three_past_semesters():
    """3개 과거 학기 → 0.5/0.3/0.2 가중평균.

    target=2026-1: 직전(25-1)=10명·중간(24-1)=8명·과거(23-1)=2명
    가중평균 = 10*0.5 + 8*0.3 + 2*0.2 = 5.0 + 2.4 + 0.4 = 7.8 → < 8 → 탈락
    """
    s = MemoryReservationStore()
    s.add_semester_archive_rows([
        {'semester_id': '2025-1', 'direction': 'to_station',
         'weekday': 1, 'shuttle_time': '14:10', 'slot_label': '',
         'avg_resv': 10.0, 'dispatch_rate': 1.0, 'recorded_at': ''},
        {'semester_id': '2024-1', 'direction': 'to_station',
         'weekday': 1, 'shuttle_time': '14:10', 'slot_label': '',
         'avg_resv': 8.0, 'dispatch_rate': 1.0, 'recorded_at': ''},
        {'semester_id': '2023-1', 'direction': 'to_station',
         'weekday': 1, 'shuttle_time': '14:10', 'slot_label': '',
         'avg_resv': 2.0, 'dispatch_rate': 0.0, 'recorded_at': ''},
    ])
    out = generate_next_baseline(s, target_semester_id='2026-1',
                                 n_star=8, fallback_table=_fallback_table())
    times = [e['shuttle'] for e in out['baseline']['to_station']]
    assert '14:10' not in times      # 가중평균 7.8 < 8


def test_generate_matches_only_same_term_name():
    """target=2026-1이면 과거 2학기(YYYY-2)는 매칭 제외."""
    s = MemoryReservationStore()
    s.add_semester_archive_rows([
        # 2학기 데이터는 1학기 baseline에 반영되지 않아야 함
        {'semester_id': '2025-2', 'direction': 'to_station',
         'weekday': 1, 'shuttle_time': '14:10', 'slot_label': '',
         'avg_resv': 15.0, 'dispatch_rate': 1.0, 'recorded_at': ''},
    ])
    out = generate_next_baseline(s, target_semester_id='2026-1',
                                 n_star=8, fallback_table=_fallback_table())
    # 같은 학기명(1) 데이터 0개 → fallback
    assert out['used_fallback'] is True


def test_generate_normalizes_weights_when_only_one_past_semester():
    """과거 학기 1개만 있으면 가중치 정규화 → 그 값 그대로 평균."""
    s = MemoryReservationStore()
    s.add_semester_archive_rows([
        {'semester_id': '2025-1', 'direction': 'to_station',
         'weekday': 1, 'shuttle_time': '14:10', 'slot_label': '',
         'avg_resv': 9.0, 'dispatch_rate': 1.0, 'recorded_at': ''},
    ])
    out = generate_next_baseline(s, target_semester_id='2026-1',
                                 n_star=8, fallback_table=_fallback_table())
    # 9 ≥ 8 → 채택
    times = [e['shuttle'] for e in out['baseline']['to_station']]
    assert '14:10' in times
    # 메타에 가중치 정보 포함
    assert out['weight_info']['n_past_semesters'] == 1
