"""apply_promotions / rollback_to_previous — 평가 결과를 실제 baseline에 반영.

apply: 평가 결과(promotions+demotions)를 받아 현재 active baseline에서 변경을 적용한
       새 baseline을 schedule_overrides에 새 effective_from으로 적재.
rollback: 직전 효력 묶음의 내용을 새 effective_from으로 다시 적재 → 직전 상태로 복귀.
"""
from shuttle_system.storage import MemoryReservationStore
from shuttle_system.core import schedule_overrides as ov
from shuttle_system.agents.promotion_agent import (
    apply_promotions, rollback_to_previous,
)


def _seed_baseline(store, effective_from='2026-05-04'):
    """초기 baseline: to_station 금 13:10 + to_campus 월 09:30."""
    table = {
        'to_station': [
            {'slot': '금 오후', 'wd': 4, 'shuttle': '13:10', 'demand': 57},
        ],
        'to_campus': [
            {'slot': '월 오전', 'wd': 0, 'shuttle': '09:30', 'demand': 31},
        ],
    }
    ov.save_new_baseline(store, table, effective_from=effective_from)
    return table


# ── apply: 승격/강등 반영 ─────────────────────────────────

def test_apply_promotion_adds_new_fixed_slot():
    """승격 권고 1건 → 그 슬롯이 새 baseline에 fixed로 추가."""
    s = MemoryReservationStore()
    _seed_baseline(s)
    eval_result = {
        'promotions': [{
            'direction': 'to_station', 'weekday': 1, 'time': '14:10',
            'avg_resv': 9.0, 'dispatch_rate': 1.0,
            'current_service': 'conditional', 'recommendation': 'promote',
        }],
        'demotions': [],
    }
    out = apply_promotions(s, eval_result, effective_from='2026-06-08')
    new = out['new_baseline']
    times = [e['shuttle'] for e in new['to_station']]
    assert '14:10' in times
    assert '13:10' in times   # 기존 fixed 유지
    assert len(out['applied_promotions']) == 1


def test_apply_demotion_removes_fixed_slot():
    """강등 권고 1건 → 그 슬롯이 새 baseline에서 제거."""
    s = MemoryReservationStore()
    _seed_baseline(s)
    eval_result = {
        'promotions': [],
        'demotions': [{
            'direction': 'to_station', 'weekday': 4, 'time': '13:10',
            'avg_resv': 2.0, 'dispatch_rate': 0.0,
            'current_service': 'fixed', 'recommendation': 'demote',
        }],
    }
    out = apply_promotions(s, eval_result, effective_from='2026-06-08')
    times = [e['shuttle'] for e in out['new_baseline']['to_station']]
    assert '13:10' not in times
    assert len(out['applied_demotions']) == 1


def test_apply_writes_new_effective_from_to_overrides():
    """apply 후 schedule_overrides 시트에 새 effective_from의 행이 들어가야 한다."""
    s = MemoryReservationStore()
    _seed_baseline(s, effective_from='2026-05-04')
    eval_result = {
        'promotions': [{'direction': 'to_station', 'weekday': 1, 'time': '14:10',
                        'avg_resv': 9.0, 'dispatch_rate': 1.0,
                        'current_service': 'conditional',
                        'recommendation': 'promote'}],
        'demotions': [],
    }
    apply_promotions(s, eval_result, effective_from='2026-06-08')
    eff_dates = {r.get('effective_from') for r in s.get_schedule_overrides()}
    assert '2026-05-04' in eff_dates
    assert '2026-06-08' in eff_dates


def test_apply_no_changes_returns_unchanged_marker():
    """승격·강등 모두 빈 평가 → apply는 동일 baseline을 새 effective_from으로만 저장."""
    s = MemoryReservationStore()
    _seed_baseline(s)
    out = apply_promotions(s, {'promotions': [], 'demotions': []},
                           effective_from='2026-06-08')
    assert out['applied_promotions'] == []
    assert out['applied_demotions'] == []


# ── rollback: 직전 상태 복원 ──────────────────────────────

def test_rollback_restores_previous_baseline():
    """변경 적용 후 롤백 → 활성 baseline이 직전 묶음과 동일해야 한다."""
    s = MemoryReservationStore()
    _seed_baseline(s, effective_from='2026-05-04')
    # 변경 적용
    apply_promotions(s, {
        'promotions': [{'direction': 'to_station', 'weekday': 1, 'time': '14:10',
                        'avg_resv': 9.0, 'dispatch_rate': 1.0,
                        'current_service': 'conditional',
                        'recommendation': 'promote'}],
        'demotions': [],
    }, effective_from='2026-06-08')
    # 롤백
    rollback_to_previous(s, effective_from='2026-06-15')
    # 현재(=가장 최근) 활성이 직전(05-04) 묶음과 같아야 함
    active = ov.load_active_overrides(s, today='2026-06-15')
    times = [e['shuttle'] for e in active['to_station']]
    assert '14:10' not in times   # 승격된 슬롯이 사라짐
    assert '13:10' in times       # 원래 슬롯 복원


def test_rollback_noop_when_only_one_baseline():
    """과거 baseline이 1개뿐이면 롤백 불가 → 명시적으로 알려야 한다."""
    s = MemoryReservationStore()
    _seed_baseline(s, effective_from='2026-05-04')
    result = rollback_to_previous(s, effective_from='2026-06-08')
    assert result['rolled_back'] is False
    assert 'reason' in result
