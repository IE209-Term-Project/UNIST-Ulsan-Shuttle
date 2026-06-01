from shuttle_system.storage import MemoryReservationStore
from shuttle_system.agents.report_agent import compute_operations_report


def test_report_counts_and_net_benefit():
    s = MemoryReservationStore()
    # 금 13:58 고정편(출발)에 9명 예약 (날짜 2026-06-05 = 금)
    for i in range(9):
        s.add(f'U{i}', 'to_station', '13:56', '2026-06-05')
    rep = compute_operations_report(s, fare=2000)

    assert rep['total_runs'] >= 1
    assert rep['total_passengers'] >= 9
    # 9명 슬롯의 순편익은 양수 (b*9 - C)
    friday = [r for r in rep['slots']
              if r['slot'] == '금 오후' and r['direction'] == 'to_station'][0]
    assert friday['reservations'] == 9
    assert friday['dispatched'] is True
    assert friday['net_benefit'] > 0


def test_conditional_below_threshold_not_dispatched():
    s = MemoryReservationStore()
    # 목 13:58 조건부편에 3명 (2026-06-04 = 목)
    for i in range(3):
        s.add(f'U{i}', 'to_station', '13:56', '2026-06-04')
    rep = compute_operations_report(s, fare=2000)
    cond = [r for r in rep['slots']
            if r['ktx'] == '13:56' and r['direction'] == 'to_station'][0]
    assert cond['service'] == 'conditional'
    assert cond['reservations'] == 3
    assert cond['dispatched'] is False   # 3 < N*(8)
