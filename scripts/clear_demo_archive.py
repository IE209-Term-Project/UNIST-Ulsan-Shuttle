"""모의 archive 데이터 삭제 — seed_semester_archive.py가 주입한 데이터를 제거.

발표 시연 후 라이브 시트를 깨끗하게 되돌리는 용도.

실행:
  로컬:  .venv/bin/python scripts/clear_demo_archive.py
  HF:    Space에 SSH 또는 동일 환경변수로 실행

삭제 대상: semester_id ∈ {'2025-1', '2024-1', '2023-1'}
실제로 운영해서 쌓인 진짜 archive(예: '2026-1')는 건드리지 않는다.

함께 처리 권장:
  · schedule_overrides 시트에서 시연 중 적재된 새 baseline도 정리하려면
    관리자 대시보드의 [↩ 롤백] 버튼으로 직전 상태로 복귀
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shuttle_system.storage import make_store

DEMO_SEMESTER_IDS = ['2025-1', '2024-1', '2023-1']


def main():
    store = make_store()
    print(f'store = {type(store).__name__}')
    before = len(store.get_semester_archive())
    removed = store.clear_semester_archive(semester_ids=DEMO_SEMESTER_IDS)
    after = len(store.get_semester_archive())
    print(f'  before: {before}행 → after: {after}행 (삭제: {removed}행)')
    print(f'  대상: {DEMO_SEMESTER_IDS}')
    if removed == 0:
        print('  (이미 깨끗했음 — 삭제할 모의 데이터 없음)')


if __name__ == '__main__':
    main()
