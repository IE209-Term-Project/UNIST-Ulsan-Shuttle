from shuttle_system.storage import MemoryReservationStore
from shuttle_system.agents.alert_agent import (
    detect_events, run_notification_check,
)


def _seed(store, direction, ktx, date, n):
    for i in range(n):
        store.add(f'U{i}', direction, ktx, date)


def test_dispatch_event_when_conditional_crosses_nstar():
    s = MemoryReservationStore()
    # 목(2026-06-04) 13:58 조건부, 8명 -> N*=8 충족
    _seed(s, 'to_station', '13:56', '2026-06-04', 8)
    types = {e['type'] for e in detect_events(s, fare=2000)}
    assert 'dispatch' in types
    assert 'carpool' not in types   # 운행하므로 카풀 아님


def test_carpool_event_when_below_nstar():
    s = MemoryReservationStore()
    # 목 13:58 조건부, 3명 (<8) 이고 2명 이상 -> 카풀
    _seed(s, 'to_station', '13:56', '2026-06-04', 3)
    evs = detect_events(s, fare=2000)
    assert any(e['type'] == 'carpool' for e in evs)
    assert not any(e['type'] == 'dispatch' for e in evs)


def test_no_carpool_for_single_reserver():
    s = MemoryReservationStore()
    _seed(s, 'to_station', '13:56', '2026-06-04', 1)
    assert detect_events(s, fare=2000) == []


def test_run_check_dedup():
    s = MemoryReservationStore()
    _seed(s, 'to_station', '13:56', '2026-06-04', 8)
    first = run_notification_check(s, fare=2000)
    assert len(first) == 1 and first[0]['type'] == 'dispatch'
    # 다시 돌려도 중복 생성 안 함
    second = run_notification_check(s, fare=2000)
    assert second == []
    assert len(s.all_notifications()) == 1


def test_pusher_called_for_new_alerts():
    s = MemoryReservationStore()
    _seed(s, 'to_station', '13:56', '2026-06-04', 8)
    sent = []
    created = run_notification_check(s, fare=2000, pusher=lambda m: sent.append(m))
    assert len(sent) == len(created) == 1
    # 재실행 시 중복 없으므로 추가 발송 없음
    run_notification_check(s, fare=2000, pusher=lambda m: sent.append(m))
    assert len(sent) == 1


def test_pusher_exception_does_not_break():
    s = MemoryReservationStore()
    _seed(s, 'to_station', '13:56', '2026-06-04', 8)
    def boom(m):
        raise RuntimeError('카톡 실패')
    created = run_notification_check(s, fare=2000, pusher=boom)
    assert len(created) == 1   # 발송 실패해도 알림 기록은 됨


def test_delay_simulation():
    s = MemoryReservationStore()
    _seed(s, 'to_station', '13:56', '2026-06-04', 3)
    created = run_notification_check(s, fare=2000, simulate_delay=True)
    assert any(c['type'] == 'delay' for c in created)


def test_notification_store_roundtrip():
    s = MemoryReservationStore()
    s.add_notification({'type': 'dispatch', 'direction': 'to_station',
                        'ktx_time': '13:56', 'travel_date': '2026-06-04', 'message': 'hi'})
    notes = s.all_notifications()
    assert len(notes) == 1
    assert notes[0]['message'] == 'hi'
    assert 'created_at' in notes[0]
