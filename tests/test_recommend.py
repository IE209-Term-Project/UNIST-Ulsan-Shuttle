from shuttle_system.storage import MemoryReservationStore
from shuttle_system.recommend import recommend, slot_status, resolve_ktx


def test_fixed_slot_books_and_recommends_shuttle():
    s = MemoryReservationStore()
    # 금 13:58 고정 슬롯
    r = recommend(s, '홍길동', 'to_station', '13:56', '2026-06-05')
    assert r['mode'] == 'shuttle' and r['booked'] is True
    assert r['shuttle_time'] == '13:39'
    assert s.count('to_station', '13:56', '2026-06-05') == 1


def test_conditional_below_threshold_books_and_pending():
    s = MemoryReservationStore()
    for i in range(6):
        s.add(f'U{i}', 'to_station', '13:56', '2026-06-04')  # 목 조건부, 6명
    r = recommend(s, '신규', 'to_station', '13:56', '2026-06-04')
    assert r['booked'] is True
    assert r['reservations'] == 7        # 6 + 1
    assert r['required'] == 8
    assert '7/8' in r['message']
    assert '1명' in r['message']           # 1명 더 모이면
    assert '신규' in r['message']          # 이름 인용
    assert '잠정' in r['message']
    assert '카카오톡' in r['message']      # 마감 카톡 안내


def test_conditional_reaching_threshold_confirms():
    s = MemoryReservationStore()
    for i in range(7):
        s.add(f'U{i}', 'to_station', '13:56', '2026-06-04')  # 7명
    r = recommend(s, '8번째', 'to_station', '13:56', '2026-06-04')
    assert r['reservations'] == 8
    # 마감 전엔 잠정, 단 N* 충족 메시지 포함
    assert '잠정' in r['message']
    assert '8/8' in r['message']
    assert '카카오톡' in r['message']


def test_no_slot_recommends_alt_no_booking():
    s = MemoryReservationStore()
    r = recommend(s, '학생', 'to_station', '03:00', '2026-06-03')
    assert r['mode'] == 'alt' and r['booked'] is False
    assert s.count('to_station', '03:00', '2026-06-03') == 0


def test_slot_status_no_booking():
    s = MemoryReservationStore()
    s.add('A', 'to_station', '13:56', '2026-06-04')
    st = slot_status(s, 'to_station', '13:56', '2026-06-04')
    assert st['reservations'] == 1 and st['n_star'] == 8
    assert st['service'] == 'conditional'


def test_resolve_ktx_time_mode_matches_near_shuttle():
    s = MemoryReservationStore()
    ktx, info = resolve_ktx(s, 'to_station', 'time', None, '13:40', '2026-06-04')
    assert ktx == '13:56'   # 목 13:41 셔틀 → 슬롯 ktx 13:58
