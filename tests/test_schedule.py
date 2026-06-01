from shuttle_system.core.schedule import (
    find_shuttle_slot, find_shuttle_near, WEEKDAY_KR,
)


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


def test_find_shuttle_near_matches_closest():
    # 금(wd=4) 13:30 출발 희망 -> 셔틀 13:41(금 오후 고정) 가장 가까움 (11분 차)
    r = find_shuttle_near('to_station', '13:30', weekday=4, window_min=30)
    assert r['found'] is True
    assert r['shuttle_time'] == '13:41'
    assert r['ktx_time'] == '13:58'      # 그 슬롯의 ktx_time (예약 키)
    assert r['diff_min'] == 11


def test_find_shuttle_near_out_of_window():
    # 금 03:00 출발 희망 -> 근방 30분 내 셔틀 없음
    r = find_shuttle_near('to_station', '03:00', weekday=4, window_min=30)
    assert r['found'] is False


def test_find_shuttle_near_picks_minimum_diff():
    # 금 17:40 -> 17:34(금 저녁, 6분) vs 13:41(멀다) -> 17:34 선택
    r = find_shuttle_near('to_station', '17:40', weekday=4, window_min=30)
    assert r['shuttle_time'] == '17:34'
    assert r['diff_min'] == 6
