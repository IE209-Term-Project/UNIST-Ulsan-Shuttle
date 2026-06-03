"""Orchestrator 모듈 보존 테스트 (현재 메인 흐름에선 미사용, 팀원 작업·확장용으로 유지)."""
import pytest
from shuttle_system.storage import MemoryReservationStore
from shuttle_system.agents.orchestrator import Orchestrator

pytestmark = pytest.mark.skip(reason='Orchestrator는 메인 흐름에서 제외(메시지 왜곡 위험). 모듈만 보존.')


def test_orchestrator_falls_back_and_books(monkeypatch):
    # 더미 키 → LLM 호출 실패 → _fallback(결정론) 경로
    monkeypatch.setenv('OPENAI_API_KEY', 'sk-dummy')
    s = MemoryReservationStore()
    for i in range(7):
        s.add(f'U{i}', 'to_station', '13:56', '2026-06-04')   # 목 조건부 7명
    orch = Orchestrator(s, fare=2000)
    res = orch.handle('테스터', 'to_station', 'time',
                      desire_time='13:40', travel_date='2026-06-04', intent='reserve')
    assert res['ok'] is True
    assert res['reservations'] == 8          # 7 + 1 (실제 예약됨)
    assert '잠정' in res['message']          # 마감 후 확정 모델
    assert any('fallback' in t for t in res['trace'])


def test_orchestrator_invalid_input(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'sk-dummy')
    s = MemoryReservationStore()
    orch = Orchestrator(s, fare=2000)
    res = orch.handle('학생', 'to_station', 'time',
                      desire_time='', travel_date='2026-06-04', intent='reserve')
    assert res['ok'] is False
