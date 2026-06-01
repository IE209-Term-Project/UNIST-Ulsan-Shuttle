from shuttle_system.storage import MemoryReservationStore
from shuttle_system.core.schedule import daily_dispatch


def _seed(s, direction, ktx, date, n):
    for i in range(n):
        s.add(f'{ktx}_{i}', direction, ktx, date)


def test_fixed_always_confirmed():
    s = MemoryReservationStore()
    # 금(2026-06-05): 고정 금오후(13:39)·금저녁(17:35)
    d = daily_dispatch(s, '2026-06-05')
    slots = {c['slot'] for c in d['confirmed']}
    assert '금 오후' in slots and '금 저녁' in slots


def test_conditional_meets_nstar_confirmed_when_no_conflict():
    s = MemoryReservationStore()
    # 금 10:00 조건부 8명 → 셔틀 09:43, 고정(13:39/17:35)과 안 겹침 → 확정
    _seed(s, 'to_station', '10:00', '2026-06-05', 8)
    d = daily_dispatch(s, '2026-06-05')
    assert any(c['ktx'] == '10:00' for c in d['confirmed'])


def test_two_close_conditionals_one_bumped():
    s = MemoryReservationStore()
    # 같은 토요일 13:56(셔틀13:39) 9명 vs 14:20(셔틀14:03) 8명 → 24분 차 < 50 → 하나만
    _seed(s, 'to_station', '13:56', '2026-06-06', 9)
    _seed(s, 'to_station', '14:20', '2026-06-06', 8)
    d = daily_dispatch(s, '2026-06-06')
    conf = [c['ktx'] for c in d['confirmed'] if c['service'] == 'conditional']
    bump = [c['ktx'] for c in d['bumped']]
    assert '13:56' in conf            # 수요 많은 쪽(9명) 확정
    assert '14:20' in bump            # 겹쳐서 밀림
    assert any('겹침' in c['reason'] for c in d['bumped'])


def test_below_nstar_not_candidate():
    s = MemoryReservationStore()
    _seed(s, 'to_station', '10:00', '2026-06-05', 3)   # 3 < 8
    d = daily_dispatch(s, '2026-06-05')
    assert not any(c['ktx'] == '10:00' for c in d['confirmed'])
    assert not any(c['ktx'] == '10:00' for c in d['bumped'])
