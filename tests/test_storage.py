import os
from shuttle_system.storage import MemoryReservationStore, make_store


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


def test_taxi_share_logic():
    from shuttle_system.agents.notify_agent import taxi_share_logic
    s = MemoryReservationStore()
    s.add('A', 'to_station', '13:58', '2026-06-05')
    s.add('B', 'to_station', '13:58', '2026-06-05')
    r = taxi_share_logic(s, 'to_station', '13:58', '2026-06-05', exclude_name='A')
    assert r['group_size'] == 2          # B + 본인
    assert 'B' in r['companions']
    assert r['per_person_krw'] == 7000


def test_make_and_cancel_reservation_actions():
    from shuttle_system.agents.notify_agent import _do_reserve, _do_cancel
    s = MemoryReservationStore()
    r = _do_reserve(s, '홍길동', 'to_station', '13:58', '2026-06-05')
    assert r['ok'] is True and r['current_reservations'] == 1
    _do_reserve(s, '김철수', 'to_station', '13:58', '2026-06-05')
    assert s.count('to_station', '13:58', '2026-06-05') == 2
    c = _do_cancel(s, '홍길동', 'to_station', '13:58', '2026-06-05')
    assert c['current_reservations'] == 1
    assert s.names('to_station', '13:58', '2026-06-05') == ['김철수']


def test_make_store_local_fallback(monkeypatch):
    # 서비스 계정 키 없음 + Colab 아님 -> 메모리 저장소로 폴백
    monkeypatch.delenv('GOOGLE_SERVICE_ACCOUNT_JSON', raising=False)
    monkeypatch.delenv('GOOGLE_SERVICE_ACCOUNT_FILE', raising=False)
    assert isinstance(make_store(), MemoryReservationStore)
