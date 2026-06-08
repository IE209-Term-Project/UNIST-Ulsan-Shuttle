"""Promotion Agent — 단기 슬롯 등급(승격/강등) 권고.

매주 월요일에 직전 4주 데이터를 평가해, 조건부 슬롯을 고정으로 승격하거나
저수요 고정 슬롯을 조건부로 강등하는 권고를 산출한다.

규칙(잠금):
  · 윈도우 = 직전 4주(28일, today 미포함)
  · 승격(conditional→fixed): 평균 ≥ N*(=8) AND 운행률 ≥ 75%
  · 강등(fixed→conditional): 평균 < 4    AND 운행률 ≤ 25%
  · Dead Zone (4 ≤ 평균 ≤ 7): 현 상태 유지
  · 콜드 스타트: 학기 1~3주차는 평가 동결
"""
from collections import defaultdict
from datetime import datetime, timedelta

from shuttle_system.core.optimization import POLICY_FARE, breakeven_N
from shuttle_system.core.schedule import GRID_MIN, SHUTTLE_FIXED

WINDOW_WEEKS = 4
DEMOTE_AVG_MAX = 4          # 평균 < 4 → 강등 조건 1
DEMOTE_RATE_MAX = 0.25      # 운행률 ≤ 0.25 → 강등 조건 2
PROMOTE_RATE_MIN = 0.75     # 운행률 ≥ 0.75 → 승격 조건 2
COLD_START_WEEKS = 3        # 1~3주차 동결, 4주차부터 평가


def evaluate_promotions(store, today=None, fare=POLICY_FARE,
                        semester_week=None, fixed_table=None):
    """최근 4주 데이터로 슬롯별 승격/강등 권고를 산출.

    Args:
      store: 예약 저장소 (all_records()).
      today: 평가 기준일 'YYYY-MM-DD'. None이면 오늘.
      fare: N* 계산용 요금(원).
      semester_week: 현재 학기 주차(1~16). 1~3이면 동결.
                     None이면 동결 검사 건너뜀(테스트/관리자 강제실행).
      fixed_table: 현재 SHUTTLE_FIXED. None이면 모듈 임포트 값.

    Returns:
      dict with keys: evaluated_at, window_start, window_end,
                      frozen, frozen_reason(optional),
                      promotions[], demotions[], unchanged[]
    """
    if today is None:
        today = datetime.now().strftime('%Y-%m-%d')
    if fixed_table is None:
        fixed_table = SHUTTLE_FIXED

    today_d = datetime.strptime(today, '%Y-%m-%d').date()
    window_end_d = today_d - timedelta(days=1)
    window_start_d = today_d - timedelta(days=WINDOW_WEEKS * 7)

    base = {
        'evaluated_at': datetime.now().isoformat(timespec='seconds'),
        'window_start': window_start_d.strftime('%Y-%m-%d'),
        'window_end': window_end_d.strftime('%Y-%m-%d'),
        'frozen': False,
        'promotions': [], 'demotions': [], 'unchanged': [],
    }

    # 콜드 스타트: 학기 첫 3주는 평가 동결
    if semester_week is not None and semester_week <= COLD_START_WEEKS:
        base['frozen'] = True
        base['frozen_reason'] = (
            f'학기 {semester_week}주차 — 콜드 스타트 (4주차부터 평가 시작)')
        return base

    n_star = breakeven_N(fare)

    # 현재 fixed 슬롯 집합: {(direction, weekday, shuttle_time)}
    fixed_set = set()
    for direction, entries in fixed_table.items():
        for e in entries:
            fixed_set.add((direction, e['wd'], e['shuttle']))

    # 윈도우 안 예약을 (direction, weekday, time) × 주차 단위로 집계
    weekly = defaultdict(lambda: [0] * WINDOW_WEEKS)

    for r in store.all_records():
        date_s = str(r.get('travel_date', '')).strip()
        try:
            d = datetime.strptime(date_s, '%Y-%m-%d').date()
        except ValueError:
            continue
        if not (window_start_d <= d <= window_end_d):
            continue
        w_idx = (d - window_start_d).days // 7
        if not (0 <= w_idx < WINDOW_WEEKS):
            continue

        direction = str(r.get('direction', ''))
        time = str(r.get('train_time', ''))
        gmin = GRID_MIN.get(direction)
        if gmin is None:
            continue
        # 그리드 시각(:10 또는 :30)이 아닌 예약은 평가 제외
        try:
            mm = int(time.split(':')[1])
        except (ValueError, IndexError, AttributeError):
            continue
        if mm != gmin:
            continue

        weekly[(direction, d.weekday(), time)][w_idx] += 1

    # 평가 대상 = (윈도우 안 데이터 있는 슬롯) ∪ (현재 fixed 슬롯 전부)
    candidates = set(weekly.keys()) | fixed_set

    for key in candidates:
        direction, weekday, time = key
        counts = weekly.get(key, [0] * WINDOW_WEEKS)
        avg = sum(counts) / WINDOW_WEEKS
        rate = sum(1 for c in counts if c >= n_star) / WINDOW_WEEKS
        is_fixed = key in fixed_set
        current = 'fixed' if is_fixed else 'conditional'

        rec = {
            'direction': direction, 'weekday': weekday, 'time': time,
            'avg_resv': round(avg, 2),
            'dispatch_rate': round(rate, 2),
            'weekly_counts': counts,
            'current_service': current,
        }

        if (not is_fixed
                and avg >= n_star
                and rate >= PROMOTE_RATE_MIN):
            rec['recommendation'] = 'promote'
            rec['reason'] = (f'평균 {avg:.1f}명 ≥ N*({n_star}), '
                             f'운행률 {int(rate*100)}% ≥ 75%')
            base['promotions'].append(rec)
        elif (is_fixed
              and avg < DEMOTE_AVG_MAX
              and rate <= DEMOTE_RATE_MAX):
            rec['recommendation'] = 'demote'
            rec['reason'] = (f'평균 {avg:.1f}명 < 4, '
                             f'운행률 {int(rate*100)}% ≤ 25%')
            base['demotions'].append(rec)
        else:
            rec['recommendation'] = 'unchanged'
            base['unchanged'].append(rec)

    # 결정성 있는 출력 순서 (direction → weekday → time)
    def _sk(r):
        return (r['direction'], r['weekday'], r['time'])
    base['promotions'].sort(key=_sk)
    base['demotions'].sort(key=_sk)
    base['unchanged'].sort(key=_sk)
    return base
