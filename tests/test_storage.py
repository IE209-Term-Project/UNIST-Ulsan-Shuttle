from shuttle_system.storage import MemoryReservationStore


def test_add_and_count():
    s = MemoryReservationStore()
    s.add('홍길동', 'to_station', '13:58', '2026-06-05')
    s.add('김철수', 'to_station', '13:58', '2026-06-05')
    s.add('이영희', 'to_campus', '12:07', '2026-06-07')
    assert s.count('to_station', '13:58', '2026-06-05') == 2
    assert s.count('to_campus', '12:07', '2026-06-07') == 1
    assert s.count('to_station', '13:58', '2026-06-06') == 0


def test_names_and_clear():
    s = MemoryReservationStore()
    s.add('A', 'to_station', '13:58', '2026-06-05')
    s.add('B', 'to_station', '13:58', '2026-06-05')
    assert set(s.names('to_station', '13:58', '2026-06-05')) == {'A', 'B'}
    s.clear_slot('to_station', '13:58', '2026-06-05')
    assert s.count('to_station', '13:58', '2026-06-05') == 0


def test_all_records():
    s = MemoryReservationStore()
    s.add('A', 'to_station', '13:58', '2026-06-05')
    recs = s.all_records()
    assert len(recs) == 1
    assert recs[0]['direction'] == 'to_station'
