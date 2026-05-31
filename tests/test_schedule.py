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
