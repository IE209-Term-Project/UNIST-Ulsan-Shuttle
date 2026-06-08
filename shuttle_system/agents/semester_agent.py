"""장기 Semester Baseline Agent — 학기별 archive + 동일학기 지수가중 baseline.

학기 종료 시 그 학기 데이터를 슬롯 단위로 집계해 semester_archive에 적재.
다음 학기 시작 직전, 동일 학기명(예: 26-1 ← 25-1, 24-1, 23-1)의 archive를
지수가중평균(0.5/0.3/0.2)해서 새 SHUTTLE_FIXED를 도출.

archive에 데이터가 없으면(첫·둘째 학기) fallback(=하드코딩 SHUTTLE_FIXED) 사용.
"""
from collections import defaultdict
from datetime import datetime, timedelta

from shuttle_system.core.optimization import POLICY_FARE, breakeven_N
from shuttle_system.core.schedule import GRID_MIN, WEEKDAY_KR
from shuttle_system.core.semester import semester_start_date, SEMESTER_WEEKS

# 직전 / 2학기 전 / 3학기 전 가중치
EWMA_WEIGHTS = [0.5, 0.3, 0.2]


def archive_semester(store, semester_id, n_star=None, fare=POLICY_FARE):
    """그 학기 모든 예약을 슬롯별로 집계해 semester_archive 시트에 적재.

    슬롯 = (direction, weekday, shuttle_time).
    avg_resv = 그 슬롯이 활성이었던 주차들의 평균 예약자 수.
    dispatch_rate = 활성 주차 중 N* 충족 비율.
    """
    if n_star is None:
        n_star = breakeven_N(fare)

    year_s, term_s = semester_id.split('-')
    start = semester_start_date(int(year_s), int(term_s))
    end_excl_days = SEMESTER_WEEKS * 7   # 학기 첫 날부터 112일 (16주)

    # 슬롯 키 → 주차별 카운트
    weekly = defaultdict(lambda: [0] * SEMESTER_WEEKS)
    for r in store.all_records():
        date_s = str(r.get('travel_date', '')).strip()
        try:
            d = datetime.strptime(date_s, '%Y-%m-%d').date()
        except ValueError:
            continue
        delta = (d - start).days
        if not (0 <= delta < end_excl_days):
            continue
        w_idx = delta // 7
        direction = str(r.get('direction', ''))
        gmin = GRID_MIN.get(direction)
        if gmin is None:
            continue
        time = str(r.get('train_time', ''))
        try:
            mm = int(time.split(':')[1])
        except (ValueError, IndexError, AttributeError):
            continue
        if mm != gmin:
            continue
        weekly[(direction, d.weekday(), time)][w_idx] += 1

    rows = []
    now_iso = datetime.now().isoformat(timespec='seconds')
    for (direction, wd, time), counts in weekly.items():
        active = [c for c in counts if c > 0]
        if not active:
            continue
        avg = sum(active) / len(active)
        rate = sum(1 for c in active if c >= n_star) / len(active)
        rows.append({
            'semester_id': semester_id,
            'direction': direction,
            'weekday': wd,
            'shuttle_time': time,
            'slot_label': f'{WEEKDAY_KR[wd]} {time}',
            'avg_resv': round(avg, 2),
            'dispatch_rate': round(rate, 2),
            'recorded_at': now_iso,
        })

    if rows:
        store.add_semester_archive_rows(rows)
    return rows


def generate_next_baseline(store, target_semester_id, n_star=None,
                           fallback_table=None, fare=POLICY_FARE):
    """동일 학기명 archive를 지수가중평균해 다음 학기 baseline 도출.

    target='2026-1' → 후보 = ['2025-1', '2024-1', '2023-1'] (가중 0.5/0.3/0.2)
    매칭되는 학기가 없으면 fallback(=하드코딩 SHUTTLE_FIXED) 사용.

    Returns:
      {
        'baseline': {'to_station': [...], 'to_campus': [...]},
        'used_fallback': bool,
        'weight_info': {
            'n_past_semesters': int,
            'matched_semesters': [...],
            'weights': [...],
            'reason': (optional) str,
        }
      }
    """
    if n_star is None:
        n_star = breakeven_N(fare)

    t_year, t_term = target_semester_id.split('-')
    t_year, t_term = int(t_year), int(t_term)
    candidate_ids = [
        f'{t_year - (k + 1)}-{t_term}'
        for k in range(len(EWMA_WEIGHTS))
    ]
    weight_by_sid = dict(zip(candidate_ids, EWMA_WEIGHTS))

    rows = []
    try:
        rows = store.get_semester_archive() or []
    except AttributeError:
        pass

    by_sem = defaultdict(list)
    for r in rows:
        sid = str(r.get('semester_id', ''))
        if sid in weight_by_sid:
            by_sem[sid].append(r)

    available = [sid for sid in candidate_ids if by_sem.get(sid)]

    if not available:
        return {
            'baseline': fallback_table or {'to_station': [], 'to_campus': []},
            'used_fallback': True,
            'weight_info': {
                'n_past_semesters': 0,
                'matched_semesters': [],
                'weights': [],
                'reason': 'archive에 동일 학기명 데이터 없음 — 하드코딩 fallback 사용.',
            },
        }

    # 슬롯 키 → 학기별 avg
    slot_data = defaultdict(dict)
    for sid in available:
        for r in by_sem[sid]:
            try:
                wd = int(r.get('weekday'))
                avg = float(r.get('avg_resv', 0))
            except (TypeError, ValueError):
                continue
            key = (str(r.get('direction', '')), wd,
                   str(r.get('shuttle_time', '')))
            slot_data[key][sid] = avg

    # 슬롯별 가중평균: 그 슬롯에 데이터가 있는 학기들만으로 정규화
    baseline = {'to_station': [], 'to_campus': []}
    for key, by_sid in slot_data.items():
        direction, wd, time = key
        if direction not in baseline:
            continue
        present_pairs = [(sid, by_sid[sid]) for sid in available
                        if sid in by_sid]
        present_weights = [weight_by_sid[sid] for sid, _ in present_pairs]
        norm = sum(present_weights)
        if norm == 0:
            continue
        wavg = sum(v * w for (_, v), w in zip(present_pairs, present_weights)) / norm
        if wavg >= n_star:
            baseline[direction].append({
                'slot': f'{WEEKDAY_KR[wd]} {time}',
                'wd': wd,
                'shuttle': time,
                'demand': round(wavg),
            })

    # 결정성 있는 정렬
    for direction in baseline:
        baseline[direction].sort(key=lambda e: (e['wd'], e['shuttle']))

    return {
        'baseline': baseline,
        'used_fallback': False,
        'weight_info': {
            'n_past_semesters': len(available),
            'matched_semesters': available,
            'weights': [weight_by_sid[sid] for sid in available],
        },
    }
