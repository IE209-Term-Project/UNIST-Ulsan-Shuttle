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
from shuttle_system.core.schedule import GRID_MIN, SHUTTLE_FIXED, WEEKDAY_KR
from shuttle_system.core import schedule_overrides as ov

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


# ──────────────────────────────────────────────────────────────────────
# 변경 적용 / 롤백
# ──────────────────────────────────────────────────────────────────────

def _make_slot_label(weekday, time, suffix='자동승격'):
    return f'{WEEKDAY_KR[weekday]} {time} ({suffix})'


def apply_promotions(store, eval_result, effective_from, today=None,
                     base_table=None):
    """평가 결과(promotions+demotions)를 baseline에 적용해 새 effective_from으로 적재.

    Args:
      store: ReservationStore.
      eval_result: evaluate_promotions()의 반환 dict (promotions/demotions 키).
      effective_from: 새 baseline의 효력 발생일 'YYYY-MM-DD' (= 다음 월요일).
      today: 현재 활성 baseline을 결정할 기준일. None이면 effective_from 직전.
      base_table: 시작 baseline. None이면 store의 활성 overrides → 없으면
                  schedule.SHUTTLE_FIXED.

    Returns:
      {'effective_from', 'applied_promotions', 'applied_demotions',
       'new_baseline'}
    """
    promos = eval_result.get('promotions', [])
    demotes = eval_result.get('demotions', [])

    # 현재 활성 baseline 결정
    if base_table is None:
        base_table = ov.load_active_overrides(store, today=today)
        if base_table is None:
            base_table = {
                'to_station': [dict(e) for e in SHUTTLE_FIXED['to_station']],
                'to_campus': [dict(e) for e in SHUTTLE_FIXED['to_campus']],
            }

    # 강등 = (direction, wd, time) 제거
    demote_keys = {(d['direction'], d['weekday'], d['time']) for d in demotes}
    for direction, entries in base_table.items():
        base_table[direction] = [e for e in entries
                                 if (direction, e['wd'], e['shuttle'])
                                 not in demote_keys]

    # 승격 = baseline에 추가 (중복 방지)
    for p in promos:
        direction = p['direction']
        wd = p['weekday']
        time = p['time']
        existing = {(e['wd'], e['shuttle']) for e in base_table.get(direction, [])}
        if (wd, time) in existing:
            continue
        base_table.setdefault(direction, []).append({
            'slot': _make_slot_label(wd, time, '자동승격'),
            'wd': wd,
            'shuttle': time,
            'demand': int(round(p.get('avg_resv', 0))),
        })

    # 새 effective_from으로 저장
    ov.save_new_baseline(store, base_table, effective_from=effective_from)

    return {
        'effective_from': effective_from,
        'applied_promotions': list(promos),
        'applied_demotions': list(demotes),
        'new_baseline': base_table,
    }


def rollback_to_previous(store, effective_from, today=None):
    """직전 baseline을 새 effective_from으로 다시 적재 → 활성 복원.

    schedule_overrides에서 현재 활성(가장 최근 effective_from ≤ today)을 찾고,
    그보다 앞선 effective_from의 가장 최근 묶음을 가져와 새 effective_from으로 저장.

    Returns:
      {'rolled_back': bool, 'reason'?: str, 'restored_from'?: str,
       'new_baseline'?: dict}
    """
    rows = []
    try:
        rows = store.get_schedule_overrides() or []
    except AttributeError:
        return {'rolled_back': False,
                'reason': 'store에 schedule_overrides 인터페이스 없음.'}
    if not rows:
        return {'rolled_back': False, 'reason': '저장된 baseline이 없음.'}

    today = today or effective_from
    past = [r for r in rows if str(r.get('effective_from', '')) <= today]
    if not past:
        return {'rolled_back': False, 'reason': '활성 baseline이 없음.'}

    eff_set = sorted({str(r.get('effective_from')) for r in past}, reverse=True)
    if len(eff_set) < 2:
        return {'rolled_back': False,
                'reason': '직전 baseline이 없음(첫 baseline은 롤백 불가).'}

    prev_eff = eff_set[1]   # 두 번째로 최신 = 직전 활성
    prev_rows = [r for r in past if str(r.get('effective_from')) == prev_eff]

    table = {'to_station': [], 'to_campus': []}
    for r in prev_rows:
        direction = str(r.get('direction', ''))
        if direction not in table:
            continue
        try:
            wd = int(r.get('weekday'))
            demand = int(r.get('demand', 0) or 0)
        except (TypeError, ValueError):
            continue
        table[direction].append({
            'slot': str(r.get('slot_label', '')),
            'wd': wd,
            'shuttle': str(r.get('shuttle_time', '')),
            'demand': demand,
        })

    ov.save_new_baseline(store, table, effective_from=effective_from)
    return {
        'rolled_back': True,
        'restored_from': prev_eff,
        'new_baseline': table,
    }
