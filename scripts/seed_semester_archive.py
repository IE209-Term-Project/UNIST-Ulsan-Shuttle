"""모의 학기 archive 시드 — 장기 Semester Agent 발표 시연용.

3개의 과거 학기(2025-1, 2024-1, 2023-1) 데이터를 직접 semester_archive 시트에
주입한다. 이후 /api/semester/run 또는 generate_next_baseline()을 호출하면
지수가중평균(0.5/0.3/0.2)으로 2026-1 baseline이 도출되는 과정을 시연할 수 있다.

실행:
  로컬:  .venv/bin/python scripts/seed_semester_archive.py
  HF:    Space의 Settings → Variables에 GOOGLE_SERVICE_ACCOUNT_JSON이 설정된 환경에서

주의:
  · 같은 학기 ID로 여러 번 실행하면 시트에 중복 행이 쌓인다.
  · 실제 운영 환경(=라이브 시트)에 모의 데이터를 넣지 말 것.
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shuttle_system.storage import make_store


# 시연용 슬롯 분포 — 실제 운영 결과처럼 학기마다 살짝 변동
# (slot_label은 표시용. 진짜 baseline 결정은 avg_resv·dispatch_rate가 함)
TEMPLATE_2025_1 = [
    # 직전 학기: 평균 ↑, 안정적인 슬롯들
    ('to_station', 4, '13:10', 10.5, 0.94),   # 금 오후
    ('to_station', 4, '18:10', 9.8, 0.88),    # 금 저녁
    ('to_station', 5, '08:10', 8.2, 0.75),    # 토 오전
    ('to_station', 3, '18:10', 7.0, 0.50),    # 목 저녁 (살짝 약함)
    ('to_campus',  0, '09:30', 9.0, 0.81),    # 월 오전
    ('to_campus',  6, '21:30', 11.0, 1.00),   # 일 야간 (가장 인기)
    ('to_campus',  6, '18:30', 9.3, 0.81),    # 일 저녁
    ('to_campus',  6, '15:30', 8.1, 0.62),    # 일 오후
]

TEMPLATE_2024_1 = [
    ('to_station', 4, '13:10', 9.7, 0.88),
    ('to_station', 4, '18:10', 9.1, 0.81),
    ('to_station', 5, '08:10', 7.5, 0.62),
    ('to_campus',  0, '09:30', 8.4, 0.69),
    ('to_campus',  6, '21:30', 10.2, 0.94),
    ('to_campus',  6, '18:30', 8.8, 0.75),
    ('to_campus',  6, '15:30', 7.0, 0.50),
]

TEMPLATE_2023_1 = [
    ('to_station', 4, '13:10', 8.5, 0.81),
    ('to_station', 4, '18:10', 8.0, 0.69),
    ('to_campus',  0, '09:30', 7.2, 0.56),
    ('to_campus',  6, '21:30', 9.5, 0.88),
    ('to_campus',  6, '18:30', 8.0, 0.69),
]

WD_KR = '월화수목금토일'


def _rows_for(semester_id, template):
    now_iso = datetime.now().isoformat(timespec='seconds')
    return [
        {
            'semester_id': semester_id,
            'direction': direction,
            'weekday': wd,
            'shuttle_time': time,
            'slot_label': f'{WD_KR[wd]} {time}',
            'avg_resv': avg,
            'dispatch_rate': rate,
            'recorded_at': now_iso,
        }
        for direction, wd, time, avg, rate in template
    ]


def main():
    store = make_store()
    print(f'store = {type(store).__name__}')
    payloads = [
        ('2025-1', TEMPLATE_2025_1),
        ('2024-1', TEMPLATE_2024_1),
        ('2023-1', TEMPLATE_2023_1),
    ]
    for sid, tmpl in payloads:
        rows = _rows_for(sid, tmpl)
        store.add_semester_archive_rows(rows)
        print(f'  + {sid}: {len(rows)} slot rows')
    print('완료. /api/semester/run 또는 관리자 UI에서 baseline 도출 시연 가능.')


if __name__ == '__main__':
    main()
