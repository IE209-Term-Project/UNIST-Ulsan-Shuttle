"""발표용 데모 예약 시드 — 현재 설정된 저장소(make_store)에 샘플 예약을 채운다.

실행 예:
  .venv/bin/python seed_demo.py          # 데모 예약 추가
  .venv/bin/python seed_demo.py --clear  # 같은 슬롯을 비우고 다시 채움

키/시트가 .env로 설정돼 있으면 실제 Google Sheet에 쌓인다(영구).
설정이 없으면 메모리 저장소라 이 실행에서만 유효(시드 의미 없음 → 안내만).
"""
import sys

from shuttle_system.storage import make_store, MemoryReservationStore
from shuttle_system.core.optimization import breakeven_N

# (이름접두, 방향, KTX시각, 날짜, 인원) — 날짜는 슬롯 요일과 맞춰야 리포트에 잡힘
# 발표 시연용 구성 (기준 주: 2026-06-04 목 ~ 06-08 월)
DEMO = [
    ('금오후', 'to_station', '13:58', '2026-06-05', 9),   # 고정편, 양호
    ('금저녁', 'to_station', '17:51', '2026-06-05', 6),   # 고정편
    ('목오후', 'to_station', '13:58', '2026-06-04', 7),   # ★ 조건부 7명(N*=8) → 발표 때 1명 추가하면 확정 라이브
    ('토오후', 'to_station', '13:58', '2026-06-06', 3),   # 조건부 미달 → 카풀 시연
    ('일저녁', 'to_campus', '18:43', '2026-06-07', 12),   # 고정편(복귀)
]


def main():
    clear = '--clear' in sys.argv
    store = make_store()

    if isinstance(store, MemoryReservationStore):
        print('⚠️  현재 메모리 저장소입니다(.env 미설정). 시드해도 이 프로세스에서만 유효합니다.')
        print('    실제 시트에 채우려면 .env에 서비스 계정/시트ID를 설정한 뒤 다시 실행하세요.')

    n_star = breakeven_N(2000)
    print(f'N* (F=2000) = {n_star}명 기준\n')

    for prefix, direction, ktx, date, count in DEMO:
        if clear:
            store.clear_slot(direction, ktx, date)
        rows = [(f'{prefix}{i + 1}', direction, ktx, date) for i in range(count)]
        store.add_many(rows)  # 단일 API 호출 (분당 쓰기 한도 회피)
        print(f'  {date} {ktx} {direction:10s} → {count}명 추가')

    print('\n완료. 관리자 대시보드에서 리포트를 생성해 확인하세요.')


if __name__ == '__main__':
    main()
