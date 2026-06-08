"""평가 기준 맞춤 데모 데이터 시드 — 기존 행 전체 삭제 후 일괄 재작성.

설계 의도 (평가 기준 매핑):
  • Novelty/Methodology (20+20%): N* 임계 충족/미달의 다양한 경계 시나리오
  • Progress (50%): 풍부한 운영 데이터 + 직전 주 완료 데이터(xlsx 보고서 demo)
  • Impact (10%): 정량적 순편익·대기절감으로 환산 가능한 분포

실행:
  .venv/bin/python scripts/seed_demo_v2.py

시드 후:
  • 학생 앱 — 운행 계획·예약 흐름 라이브 시연 가능
  • 관리자 — KPI/차트/주간 xlsx/LLM 브리핑 모두 의미 있는 결과 출력
"""
import os
import random
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shuttle_system import config  # noqa: F401 — .env 자동 로드
from shuttle_system.storage import make_store, HEADER

random.seed(42)  # 재현 가능

# ── 한국인 이름 풀 ─────────────────────────────────
LAST_NAMES = list('김이박최정강조윤장임한오서신권황안송류백남노문양손배진차표곽우구도라마변사어')
FIRST_NAMES = [
    '민준','서연','지호','서윤','도윤','하은','준우','예린','태민','수아',
    '지원','민서','연우','예준','나윤','주원','하준','지유','지훈','시우',
    '시아','유진','지아','민호','유나','준영','은서','우혁','예원','지연',
    '서준','민기','다인','채린','지환','예성','재훈','승현','도현','지율',
    '이안','은우','서아','우진','다은','지윤','윤서','하린','이준','수민',
    '재희','채원','지웅','연서','다율','시안','로운','정후','다온','수환',
]

USED_EMAILS = set()


def korean_name(used):
    """중복 없는 한국인 이름 1개."""
    for _ in range(200):
        nm = random.choice(LAST_NAMES) + random.choice(FIRST_NAMES)
        if nm not in used:
            used.add(nm)
            return nm
    # 풀 소진 시 인덱스 접미사
    return random.choice(LAST_NAMES) + random.choice(FIRST_NAMES) + str(random.randint(2, 9))


def fake_email():
    """실재하지 않는 @unist.ac.kr 이메일."""
    for _ in range(200):
        local = ''.join(random.choices('abcdefghijklmnopqrstuvwxyz', k=3)) \
                + str(random.randint(10, 99))
        addr = f'{local}@unist.ac.kr'
        if addr not in USED_EMAILS:
            USED_EMAILS.add(addr)
            return addr
    # fallback
    return f'demo{random.randint(1000,9999)}@unist.ac.kr'


# ── 슬롯 시나리오 (direction, 셔틀시각, travel_date, 예약 인원) ───────
# N* = 8 (요금 2000원 기준). 0~7명 = 미운행, 8명+ = 조건부 운행, FIXED는 항상 운행
SLOTS = [
    # ━━━━━━━━ 이번 주 (2026-06-01 ~ 06-07, 진행 중) ━━━━━━━━

    # 월 6/1
    ('to_campus',  '09:30', '2026-06-01', 7),   # FIXED 월 — 안정 운행
    ('to_station', '17:10', '2026-06-01', 6),   # 조건부 — 부족 2명 🟡 중기 검토

    # 화 6/2
    ('to_station', '14:10', '2026-06-02', 9),   # 조건부 — N* 달성 ⭐ 조건부 운행 성공

    # 수 6/3
    ('to_campus',  '16:30', '2026-06-03', 7),   # 조건부 — 부족 1명 🔴 즉시 실행

    # 목 6/4 (오늘)
    ('to_station', '18:10', '2026-06-04', 8),   # FIXED 목 — 운행 확정

    # 금 6/5 (주중 피크)
    ('to_station', '13:10', '2026-06-05', 12),  # FIXED 금 — 정원 만석 ⭐
    ('to_station', '18:10', '2026-06-05', 9),   # FIXED 금
    ('to_station', '11:10', '2026-06-05', 8),   # 조건부 — N* 정확히 달성
    ('to_campus',  '20:30', '2026-06-05', 4),   # 조건부 — 부족 4명 🟢 관찰

    # ⭐ 알림 에이전트 시연용 트리거 슬롯 (현재 7/8 = N*-1, 발표 중 1명 추가하면 N* 충족)
    ('to_campus',  '14:30', '2026-06-05', 7),   # 금 조건부 — 알림 트리거 대기 🔴

    # 토 6/6
    ('to_station', '08:10', '2026-06-06', 5),   # FIXED 토 — 운행 확정
    ('to_station', '11:10', '2026-06-06', 7),   # 토 조건부 — 백업 알림 트리거 🔴

    # 일 6/7 (캠퍼스행 피크)
    ('to_campus',  '15:30', '2026-06-07', 8),   # FIXED 일
    ('to_campus',  '18:30', '2026-06-07', 11),  # FIXED 일 — 인기 슬롯
    ('to_campus',  '21:30', '2026-06-07', 6),   # FIXED 일

    # ━━━━━━━━ 직전 주 (2026-05-25 ~ 05-31, 완료) — xlsx 보고서 demo용 ━━━━━━━━

    ('to_campus',  '09:30', '2026-05-25', 5),   # 월 FIXED
    ('to_station', '14:10', '2026-05-26', 8),   # 화 조건부 — N* 정확히
    ('to_station', '18:10', '2026-05-28', 7),   # 목 FIXED
    ('to_station', '13:10', '2026-05-28', 5),   # 목 조건부 — 부족 3명 🟢
    ('to_station', '13:10', '2026-05-29', 9),   # 금 FIXED
    ('to_station', '18:10', '2026-05-29', 6),   # 금 FIXED
    ('to_campus',  '15:30', '2026-05-31', 6),   # 일 FIXED
    ('to_campus',  '18:30', '2026-05-31', 9),   # 일 FIXED

    # ━━━━━━━━ 추가 분산용 저수요 슬롯 (이번 주) ━━━━━━━━
    # 히트맵·시각화에 다양한 시각이 색칠되도록 (1~5명, 모두 N* 미만)
    ('to_station', '10:10', '2026-06-01', 2),   # 월 한산
    ('to_station', '15:10', '2026-06-01', 3),
    ('to_campus',  '11:30', '2026-06-01', 2),
    ('to_station', '09:10', '2026-06-02', 4),   # 화 모집 중 단계
    ('to_campus',  '12:30', '2026-06-02', 2),
    ('to_campus',  '17:30', '2026-06-02', 5),
    ('to_station', '13:10', '2026-06-03', 3),   # 수
    ('to_station', '16:10', '2026-06-03', 2),
    ('to_campus',  '19:30', '2026-06-03', 4),
    ('to_station', '09:10', '2026-06-04', 2),   # 목 (오늘)
    ('to_station', '15:10', '2026-06-04', 4),
    ('to_campus',  '13:30', '2026-06-04', 3),
    ('to_station', '15:10', '2026-06-05', 5),   # 금
    ('to_station', '09:10', '2026-06-05', 3),
    ('to_station', '19:10', '2026-06-05', 4),
    ('to_campus',  '12:30', '2026-06-05', 2),
    ('to_campus',  '17:30', '2026-06-05', 3),
    ('to_station', '14:10', '2026-06-06', 3),   # 토
    ('to_station', '16:10', '2026-06-06', 2),
    ('to_campus',  '13:30', '2026-06-06', 2),
    ('to_campus',  '19:30', '2026-06-06', 4),
    ('to_campus',  '10:30', '2026-06-07', 2),   # 일
    ('to_campus',  '13:30', '2026-06-07', 3),
    ('to_campus',  '19:30', '2026-06-07', 5),
    ('to_station', '09:10', '2026-06-07', 2),
    ('to_station', '14:10', '2026-06-07', 3),

    # ── 직전 주 분산용 ──
    ('to_station', '10:10', '2026-05-26', 2),
    ('to_station', '13:10', '2026-05-27', 3),   # 수
    ('to_campus',  '11:30', '2026-05-28', 2),
    ('to_station', '11:10', '2026-05-29', 4),
    ('to_campus',  '12:30', '2026-05-31', 3),
]


def build_rows():
    """SLOTS → 시트에 들어갈 row 리스트(HEADER 순서)."""
    used_names = set()
    rows = []
    now_iso = datetime.now().isoformat(timespec='seconds')
    for direction, t, date, count in SLOTS:
        for _ in range(count):
            rows.append({
                'name': korean_name(used_names),
                'email': fake_email(),
                'direction': direction,
                'train_time': t,
                'travel_date': date,
                'created_at': now_iso,
            })
    return rows


def main():
    store = make_store()
    print(f'Store: {type(store).__name__}')
    print(f'시트 URL: {getattr(store, "url", "?")}')
    cur = store.all_records()
    print(f'기존 행 수: {len(cur)}')

    rows = build_rows()
    print(f'\n새 데모 데이터 행 수: {len(rows)}')
    print(f'  슬롯 수: {len(SLOTS)}')

    # 슬롯별 요약 출력 (사전 점검)
    print('\n── 슬롯별 분포 ──')
    for direction, t, date, count in SLOTS:
        wd = datetime.strptime(date, '%Y-%m-%d').weekday()
        wd_kr = '월화수목금토일'[wd]
        d_kr = '울산역행' if direction == 'to_station' else '캠퍼스행'
        tag = ''
        if count >= 12:
            tag = '🟢 정원 만석'
        elif count >= 8:
            tag = '🟢 운행 (N* 달성)'
        elif count == 7:
            tag = '🔴 부족 1 (즉시)'
        elif count == 6:
            tag = '🟡 부족 2 (중기)'
        else:
            tag = f'🟢 관찰 (부족 {8 - count})'
        print(f'  {date} {wd_kr} {t} {d_kr:8s} {count:2d}명  {tag}')

    print(f'\n진행: 기존 {len(cur)}행 삭제 → 새 {len(rows)}행 삽입')
    answer = input('계속? (y/N): ')
    if answer.strip().lower() != 'y':
        print('취소.')
        return

    # 일괄 삭제 + 재삽입 (gspread batch)
    print('\n시트 클리어 중...')
    store.ws.clear()
    print('헤더 + 데이터 일괄 삽입 중...')
    payload = [HEADER] + [[r[k] for k in HEADER] for r in rows]
    store.ws.append_rows(payload, value_input_option='RAW')
    print(f'✓ 완료 — {len(rows)}행 삽입')

    # 검증
    after = store.all_records()
    print(f'✓ 시트 행 수 확인: {len(after)}')


if __name__ == '__main__':
    main()
