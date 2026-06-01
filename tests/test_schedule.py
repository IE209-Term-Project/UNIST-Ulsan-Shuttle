from shuttle_system.core.schedule import (
    find_shuttle_slot, find_shuttle_near, WEEKDAY_KR,
)


def test_fixed_slot_found_friday_afternoon():
    # 금요일(wd=4) 13:56 출발 = 고정편
    r = find_shuttle_slot('to_station', '13:56', weekday=4, reservations=0)
    assert r['available'] is True
    assert r['service'] == 'fixed'
    assert r['shuttle_time'] == '13:39'


def test_conditional_below_threshold_not_dispatched():
    # 목요일(wd=3) 13:56 = 조건부. 예약 7 < N*(8) -> 미배차
    r = find_shuttle_slot('to_station', '13:56', weekday=3, reservations=7)
    assert r['service'] == 'conditional'
    assert r['available'] is False
    assert r['required'] == 8


def test_conditional_meets_threshold_dispatched():
    r = find_shuttle_slot('to_station', '13:56', weekday=3, reservations=8)
    assert r['service'] == 'conditional'
    assert r['available'] is True


def test_no_slot():
    r = find_shuttle_slot('to_station', '03:00', weekday=2, reservations=0)
    assert r['available'] is False
    assert r['service'] is None


def test_find_shuttle_near_finds_close_shuttle():
    # 13:30 출발 희망 -> 근방 셔틀이 잡히고 차이가 작아야 함
    r = find_shuttle_near('to_station', '13:30', weekday=4, window_min=30)
    assert r['found'] is True
    assert r['diff_min'] <= 15
    assert ':' in r['shuttle_time'] and ':' in r['ktx_time']


def test_find_shuttle_near_out_of_window():
    # 03:00 출발 희망 -> 그 시간대 열차/셔틀 없음
    r = find_shuttle_near('to_station', '03:00', weekday=4, window_min=30)
    assert r['found'] is False
