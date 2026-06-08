"""schedule_overrides 모듈 테스트 — SHUTTLE_FIXED 동적 로드/저장.

요구사항:
  · overrides 시트에서 가장 최근 effective_from(≤today)의 묶음을 활성 fixed로 사용
  · 미래 effective_from은 활성에서 제외 (= 예약 윈도우 보호)
  · overrides 없으면 None 반환 → 호출자가 하드코딩 baseline 사용
  · save → load roundtrip 보장
  · refresh_active_schedule()이 schedule 모듈의 SHUTTLE_FIXED를 in-place 갱신
"""
from shuttle_system.storage import MemoryReservationStore
from shuttle_system.core import schedule_overrides as ov
from shuttle_system.core import schedule as sch


def _fixed_table_sample():
    """테스트용 작은 fixed 묶음 (2슬롯)."""
    return {
        'to_station': [
            {'slot': '목 저녁', 'wd': 3, 'shuttle': '21:10', 'demand': 9},
        ],
        'to_campus': [
            {'slot': '월 오전', 'wd': 0, 'shuttle': '09:30', 'demand': 31},
        ],
    }


def test_load_returns_none_when_empty():
    s = MemoryReservationStore()
    assert ov.load_active_overrides(s, today='2026-06-08') is None


def test_save_then_load_returns_latest_effective_set():
    s = MemoryReservationStore()
    table = _fixed_table_sample()
    ov.save_new_baseline(s, table, effective_from='2026-05-25')
    loaded = ov.load_active_overrides(s, today='2026-06-08')
    assert loaded is not None
    # 방향 key 그대로
    assert set(loaded.keys()) == {'to_station', 'to_campus'}
    # 슬롯 수 일치
    assert len(loaded['to_station']) == 1
    assert len(loaded['to_campus']) == 1
    # 내용 일치 (수요는 라운드트립에 포함)
    assert loaded['to_station'][0]['shuttle'] == '21:10'
    assert loaded['to_station'][0]['wd'] == 3
    assert loaded['to_campus'][0]['shuttle'] == '09:30'


def test_load_ignores_future_effective_from():
    """미래 effective_from은 아직 활성이 아님 → 직전 묶음을 반환."""
    s = MemoryReservationStore()
    old_table = _fixed_table_sample()
    future_table = {
        'to_station': [{'slot': 'X', 'wd': 2, 'shuttle': '10:10', 'demand': 1}],
        'to_campus': [],
    }
    ov.save_new_baseline(s, old_table, effective_from='2026-05-25')
    ov.save_new_baseline(s, future_table, effective_from='2026-06-15')  # 미래
    loaded = ov.load_active_overrides(s, today='2026-06-08')
    # 직전(05-25) 묶음이 활성
    assert loaded is not None
    assert loaded['to_station'][0]['shuttle'] == '21:10'


def test_load_picks_most_recent_past_effective_from():
    """과거 묶음 여러 개면 가장 최근 것이 활성."""
    s = MemoryReservationStore()
    t1 = _fixed_table_sample()
    t2 = {
        'to_station': [{'slot': 'Y', 'wd': 4, 'shuttle': '13:10', 'demand': 50}],
        'to_campus': [],
    }
    ov.save_new_baseline(s, t1, effective_from='2026-05-04')
    ov.save_new_baseline(s, t2, effective_from='2026-05-25')
    loaded = ov.load_active_overrides(s, today='2026-06-08')
    assert loaded['to_station'][0]['shuttle'] == '13:10'


def test_refresh_updates_schedule_module():
    """refresh_active_schedule()은 schedule.SHUTTLE_FIXED를 in-place로 갱신."""
    # 원본 백업
    original_station = list(sch.SHUTTLE_FIXED['to_station'])
    original_campus = list(sch.SHUTTLE_FIXED['to_campus'])
    try:
        s = MemoryReservationStore()
        new_table = {
            'to_station': [{'slot': 'Z', 'wd': 5, 'shuttle': '08:10', 'demand': 26}],
            'to_campus': [],
        }
        ov.save_new_baseline(s, new_table, effective_from='2026-05-25')
        ov.refresh_active_schedule(s, today='2026-06-08')
        assert sch.SHUTTLE_FIXED['to_station'] == new_table['to_station']
        assert sch.SHUTTLE_FIXED['to_campus'] == []
    finally:
        # 원복
        sch.SHUTTLE_FIXED['to_station'] = original_station
        sch.SHUTTLE_FIXED['to_campus'] = original_campus


def test_refresh_keeps_baseline_when_no_overrides():
    """overrides 없으면 schedule.SHUTTLE_FIXED는 그대로."""
    s = MemoryReservationStore()
    snapshot_station = list(sch.SHUTTLE_FIXED['to_station'])
    snapshot_campus = list(sch.SHUTTLE_FIXED['to_campus'])
    ov.refresh_active_schedule(s, today='2026-06-08')
    assert sch.SHUTTLE_FIXED['to_station'] == snapshot_station
    assert sch.SHUTTLE_FIXED['to_campus'] == snapshot_campus
