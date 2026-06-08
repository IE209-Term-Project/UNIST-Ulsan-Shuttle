from datetime import datetime, timedelta

from shuttle_system.storage import MemoryReservationStore
from shuttle_system.recommend import recommend, slot_status, resolve_ktx


def _next_dow(target_wd):
    """today 기준 미래(혹은 today)의 target 요일 날짜를 YYYY-MM-DD로.

    cutoff(출발 2시간 전)에 안 걸리도록 최소 +7일 보장.
    """
    today = datetime.now().date()
    delta = (target_wd - today.weekday()) % 7
    if delta == 0:
        delta = 7
    return (today + timedelta(days=delta + 7)).strftime('%Y-%m-%d')


THU = _next_dow(3)   # 다음 목요일 이후 (조건부 14:10 테스트용)
FRI = _next_dow(4)   # 다음 금요일 이후 (고정 13:10 테스트용)


def test_fixed_slot_books_and_recommends_shuttle():
    s = MemoryReservationStore()
    r = recommend(s, '홍길동', 'to_station', '13:10', FRI)
    assert r['mode'] == 'shuttle' and r['booked'] is True
    assert r['shuttle_time'] == '13:10'
    assert s.count('to_station', '13:10', FRI) == 1


def test_conditional_below_threshold_books_and_pending():
    s = MemoryReservationStore()
    for i in range(6):
        s.add(f'U{i}', 'to_station', '14:10', THU)  # 목 조건부, 6명
    r = recommend(s, '신규', 'to_station', '14:10', THU)
    assert r['booked'] is True
    assert r['reservations'] == 7        # 6 + 1
    assert r['required'] == 8
    assert '7/8' in r['message']
    assert '1명' in r['message']           # 1명 더 모이면
    assert '신규' in r['message']          # 이름 인용
    assert '잠정' in r['message']
    assert '이메일' in r['message']        # 마감 안내 채널 (카카오톡 → 이메일)


def test_conditional_reaching_threshold_confirms():
    s = MemoryReservationStore()
    for i in range(7):
        s.add(f'U{i}', 'to_station', '14:10', THU)  # 7명
    r = recommend(s, '8번째', 'to_station', '14:10', THU)
    assert r['reservations'] == 8
    # N* 충족 시 확정 메시지로 분기
    assert '확정' in r['message']
    assert '8/8' in r['message']


def test_no_slot_recommends_alt_no_booking():
    s = MemoryReservationStore()
    r = recommend(s, '학생', 'to_station', '03:00', '2026-06-03')
    assert r['mode'] == 'alt' and r['booked'] is False
    assert s.count('to_station', '03:00', '2026-06-03') == 0


def test_slot_status_no_booking():
    s = MemoryReservationStore()
    s.add('A', 'to_station', '14:10', '2026-06-04')
    st = slot_status(s, 'to_station', '14:10', '2026-06-04')
    assert st['reservations'] == 1 and st['n_star'] == 8
    assert st['service'] == 'conditional'


def test_resolve_train_time_mode_matches_near_shuttle():
    s = MemoryReservationStore()
    # 목요일 13:40 → 가장 가까운 to_station 그리드(:10) = 13:10 또는 14:10 (둘 다 30분 차)
    ktx, info = resolve_ktx(s, 'to_station', 'time', None, '13:40', '2026-06-04')
    assert ktx in ('13:10', '14:10')
