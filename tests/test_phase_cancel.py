from datetime import datetime, timedelta
from shuttle_system.storage import MemoryReservationStore
from shuttle_system.core.schedule import slot_phase, CUTOFF_HOURS


def _today_at(hhmm, days_ahead=0):
    return (datetime.now() + timedelta(days=days_ahead)).strftime('%Y-%m-%d'), hhmm


def test_slot_phase_open_far_future():
    date, hh = _today_at('13:10', days_ahead=2)
    assert slot_phase(hh, date) == 'open'


def test_slot_phase_closed_past():
    date, hh = _today_at('00:01', days_ahead=-1)
    assert slot_phase(hh, date) == 'closed'


def test_slot_phase_closing_soon():
    # 출발 시각 = 지금 + (CUTOFF_HOURS시간 + 10분) → 마감 10분 후가 출발 → 임박
    target = datetime.now() + timedelta(hours=CUTOFF_HOURS, minutes=10)
    date = target.strftime('%Y-%m-%d')
    hh = target.strftime('%H:%M')
    assert slot_phase(hh, date) == 'closing_soon'


def test_remove_one_only_my_record():
    s = MemoryReservationStore()
    s.add('A', 'to_station', '14:10', '2026-06-04')
    s.add('B', 'to_station', '14:10', '2026-06-04')
    s.add('A', 'to_station', '18:10', '2026-06-04')
    assert s.remove_one('A', 'to_station', '14:10', '2026-06-04') is True
    assert s.count('to_station', '14:10', '2026-06-04') == 1
    assert s.names('to_station', '14:10', '2026-06-04') == ['B']
    # A의 다른 슬롯 예약은 유지
    assert s.count('to_station', '18:10', '2026-06-04') == 1


def test_remove_one_not_found():
    s = MemoryReservationStore()
    s.add('A', 'to_station', '14:10', '2026-06-04')
    assert s.remove_one('Z', 'to_station', '14:10', '2026-06-04') is False
