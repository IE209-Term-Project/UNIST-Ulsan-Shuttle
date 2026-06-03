"""스케줄 테스트 — 새 그리드 모델 (:10 to_station, :30 to_campus)."""
from shuttle_system.core.schedule import (
    find_shuttle_slot, find_shuttle_near, grid_shuttle_time_for, grid_options,
    WEEKDAY_KR,
)


def test_fixed_friday_afternoon_match():
    # 금요일(wd=4) 13:50 셔틀 = 고정 (금 오후)
    r = find_shuttle_slot('to_station', '13:50', weekday=4, reservations=0)
    assert r['available'] is True
    assert r['service'] == 'fixed'
    assert r['slot'] == '금 오후'


def test_fixed_sunday_night_match():
    # 일요일(wd=6) 21:00 셔틀 = 고정 (일 야간 to_campus)
    r = find_shuttle_slot('to_campus', '21:00', weekday=6)
    assert r['available'] is True
    assert r['service'] == 'fixed'


def test_conditional_grid_below_nstar():
    # 평일 10:10 그리드(조건부), 7명 < N*=8 → 미배차
    r = find_shuttle_slot('to_station', '10:10', weekday=2, reservations=7)
    assert r['service'] == 'conditional'
    assert r['available'] is False


def test_conditional_grid_meets_nstar():
    r = find_shuttle_slot('to_station', '10:10', weekday=2, reservations=8)
    assert r['service'] == 'conditional'
    assert r['available'] is True


def test_non_grid_time_no_slot():
    # :20 같이 그리드 아닌 시각 → 슬롯 없음
    r = find_shuttle_slot('to_station', '13:25', weekday=2)
    assert r['service'] is None


def test_grid_shuttle_time_for_to_station():
    # KTX 14:00 출발 → 셔틀이 25~60분 전 :10 그리드 → 13:10 (50분 전)
    assert grid_shuttle_time_for('to_station', '14:00') == '13:10'


def test_grid_shuttle_time_for_to_campus():
    # KTX 14:00 도착 → 셔틀이 5~25분 후 :30 그리드 → 14:30 (30분 후 NOT, 5~25분이면 안 됨!)
    # 14:00 + 5~25분 → 14:05~14:25 → :30 그리드 중 14:30(30분 후, 범위 초과) 안 됨, 다음 없음
    # 실제 매칭: 5~25분 범위 안 :30 그리드 없음 → 14:30(30분 차)는 범위 초과
    # 따라서 None이 정답
    result = grid_shuttle_time_for('to_campus', '14:00')
    # 13:30은 30분 전, 14:30은 30분 후 — 둘 다 범위(5~25) 밖
    assert result is None


def test_grid_shuttle_time_for_to_campus_within_window():
    # KTX 14:10 도착 → 14:15~14:35 사이 셔틀 → 14:30(20분 후) ✅
    assert grid_shuttle_time_for('to_campus', '14:10') == '14:30'


def test_find_shuttle_near_picks_grid():
    # 금요일 13:30 출발 희망 → 가까운 :10 그리드 또는 금 13:50 고정
    r = find_shuttle_near('to_station', '13:30', weekday=4, window_min=60)
    assert r['found'] is True
    # 13:10(20분), 13:50(20분 — 고정) 동률 → 둘 중 하나
    assert r['shuttle_time'] in ('13:10', '13:50')


def test_grid_options():
    st = grid_options('to_station')
    assert '13:10' in st and '21:10' in st
    cp = grid_options('to_campus')
    assert '13:30' in cp and '21:30' in cp


def test_weekday_kr_constant():
    assert WEEKDAY_KR[0] == '월' and WEEKDAY_KR[6] == '일'
