from datetime import datetime
from shuttle_system.storage import MemoryReservationStore
from shuttle_system.agents.carpool_agent import (
    fare_for_time, form_carpool_groups, MEETING_PLACE,
)


def test_fare_surcharge_by_time():
    assert fare_for_time('13:58') == 10_000   # 평시
    assert fare_for_time('23:30') == 14_000   # 할증(22시 이후)
    assert fare_for_time('02:00') == 14_000   # 새벽 할증
    assert fare_for_time('04:30') == 10_000   # 할증 종료 후


def _signup(s, names, direction, ktx, date):
    for n in names:
        s.add_carpool_request(n, direction, ktx, date)


def test_groups_of_four():
    s = MemoryReservationStore()
    _signup(s, ['A', 'B', 'C', 'D', 'E'], 'to_station', '13:58', '2026-06-05')
    # 출발 한참 전(now 12:00) -> 모집 중
    groups = form_carpool_groups(s, now=datetime(2026, 6, 5, 12, 0))
    assert len(groups) == 2
    assert groups[0]['size'] == 4 and groups[1]['size'] == 1
    assert groups[0]['status'] == 'collecting'
    assert groups[0]['place'] == MEETING_PLACE['to_station']
    assert groups[0]['per_person'] == 2_500   # 10000/4


def test_finalize_within_15min():
    s = MemoryReservationStore()
    _signup(s, ['A', 'B'], 'to_station', '13:58', '2026-06-05')
    # 출발 13:58 기준 13:50 = 8분 전 -> 확정
    groups = form_carpool_groups(s, now=datetime(2026, 6, 5, 13, 50))
    assert groups[0]['status'] == 'confirmed'
    assert groups[0]['size'] == 2
    assert groups[0]['per_person'] == 5_000   # 10000/2


def test_single_signup_no_carpool_when_confirmed():
    s = MemoryReservationStore()
    _signup(s, ['A'], 'to_station', '13:58', '2026-06-05')
    groups = form_carpool_groups(s, now=datetime(2026, 6, 5, 13, 50))
    assert groups[0]['status'] == 'no_carpool'


def test_meeting_window_plus_10():
    s = MemoryReservationStore()
    _signup(s, ['A', 'B'], 'to_campus', '18:43', '2026-06-07')
    groups = form_carpool_groups(s, now=datetime(2026, 6, 7, 12, 0))
    g = groups[0]
    assert g['meet_from'] == '18:43' and g['meet_to'] == '18:53'
    assert g['place'] == MEETING_PLACE['to_campus']
