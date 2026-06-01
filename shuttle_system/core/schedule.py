"""고정 8 + 조건부 5 셔틀 슬롯 데이터와 요일+KTX 매칭. 순수 함수.

조건부 임계값은 하드코딩이 아니라 optimization.breakeven_N()에서 가져온다.
"""
from shuttle_system.core.optimization import breakeven_N, POLICY_FARE

WEEKDAY_KR = '월화수목금토일'

# 고정 8회: 출발=KTX 17분 전 / 복귀=KTX 도착 15분 후 (확정 운행)
# KTX 시각은 실제 시간표(5.15 기준)에 맞춰 정렬됨 → 기차연계 드롭다운에서 선택 가능
SHUTTLE_FIXED = {
    'to_station': [
        {'slot': '금 오후', 'wd': 4, 'ktx': '13:56', 'shuttle': '13:39', 'demand': 57},
        {'slot': '금 저녁', 'wd': 4, 'ktx': '17:52', 'shuttle': '17:35', 'demand': 51},
        {'slot': '목 저녁', 'wd': 3, 'ktx': '17:52', 'shuttle': '17:35', 'demand': 24},
        {'slot': '토 오전', 'wd': 5, 'ktx': '10:00', 'shuttle': '09:43', 'demand': 26},
    ],
    'to_campus': [
        {'slot': '월 오전', 'wd': 0, 'ktx': '08:45', 'shuttle': '09:00', 'demand': 31},
        {'slot': '일 오후', 'wd': 6, 'ktx': '12:07', 'shuttle': '12:22', 'demand': 36},
        {'slot': '일 저녁', 'wd': 6, 'ktx': '18:38', 'shuttle': '18:53', 'demand': 54},
        {'slot': '일 야간', 'wd': 6, 'ktx': '20:34', 'shuttle': '20:49', 'demand': 61},
    ],
}

# 조건부 5회: 예약 >= N* 일 때만 1회 배차 (전부 출발 방향)
SHUTTLE_CONDITIONAL = {
    'to_station': [
        {'slot': '목 오후', 'wd': 3, 'ktx': '13:56', 'shuttle': '13:39', 'demand': 13},
        {'slot': '목 야간', 'wd': 3, 'ktx': '22:39', 'shuttle': '22:22', 'demand': 12},
        {'slot': '금 오전', 'wd': 4, 'ktx': '10:00', 'shuttle': '09:43', 'demand': 16},
        {'slot': '금 야간', 'wd': 4, 'ktx': '22:39', 'shuttle': '22:22', 'demand': 21},
        {'slot': '토 오후', 'wd': 5, 'ktx': '13:56', 'shuttle': '13:39', 'demand': 14},
    ],
    'to_campus': [],
}


DEPART_LEAD = 17   # 출발(to_station) 셔틀 = KTX − 17분
ARRIVE_LAG = 15    # 복귀(to_campus) 셔틀 = KTX + 15분


def _shift(hhmm, minutes):
    from datetime import datetime, timedelta
    return (datetime.strptime(hhmm, '%H:%M') + timedelta(minutes=minutes)).strftime('%H:%M')


def shuttle_time_for(direction, ktx):
    """KTX 시각 → 셔틀 시각(출발 −17 / 복귀 +15)."""
    return _shift(ktx, -DEPART_LEAD if direction == 'to_station' else ARRIVE_LAG)


def find_shuttle_slot(direction, ktx_time, weekday, reservations=0, fare=POLICY_FARE):
    """요일+KTX 시각의 셔틀편을 찾는다.

    고정(피크) 우선 → 그 외 실재하는 모든 KTX/SRT 시각은 '조건부'(수요 N* 차면 운행).
    실재 열차 시각이 아니면 셔틀 없음.
    """
    from shuttle_system import timetable
    ktx_time = ktx_time.strip()
    wd_kr = WEEKDAY_KR[weekday] + '요일'

    # 1) 고정 피크
    for e in SHUTTLE_FIXED.get(direction, []):
        if e['wd'] == weekday and e['ktx'] == ktx_time:
            return {'available': True, 'service': 'fixed', 'mode': 'shuttle',
                    'weekday': wd_kr, 'slot': e['slot'], 'shuttle_time': e['shuttle'],
                    'ktx_time': e['ktx'], 'note': '고정 운행 확정편'}

    # 2) 그 외 실재 열차 시각 → 동적 조건부
    if ktx_time in timetable.all_times():
        n_star = breakeven_N(fare)
        ok = reservations >= n_star
        return {'available': ok, 'service': 'conditional', 'mode': 'shuttle',
                'weekday': wd_kr, 'slot': f'{wd_kr} {ktx_time}',
                'shuttle_time': shuttle_time_for(direction, ktx_time),
                'ktx_time': ktx_time, 'reservations': reservations, 'required': n_star,
                'note': (f'조건부 — 예약 {reservations}명 ≥ N*({n_star}) → 배차 확정'
                         if ok else
                         f'조건부 — 예약 {reservations}/{n_star}명 → 배차 미정, 대체수단 검토')}

    # 3) 셔틀 불가
    return {'available': False, 'service': None, 'mode': 'shuttle', 'weekday': wd_kr,
            'note': '해당 시각에 운행 가능한 셔틀 없음 → 513/택시 검토'}


def _to_min(hhmm):
    h, m = hhmm.strip().split(':')
    return int(h) * 60 + int(m)


def find_shuttle_near(direction, desired_time, weekday, window_min=30, fare=POLICY_FARE):
    """기차 없이 '출발 희망 시각'에 가장 가까운 셔틀 슬롯을 찾는다(셔틀 출발시각 기준).

    window_min 이내 최근접 슬롯을 반환. 예약은 그 슬롯의 ktx_time 키로 합류시킨다.
    """
    from shuttle_system import timetable
    target = _to_min(desired_time)
    best = None
    wd_kr = WEEKDAY_KR[weekday] + '요일'
    # 고정 피크 (해당 요일)
    for e in SHUTTLE_FIXED.get(direction, []):
        if e['wd'] != weekday:
            continue
        diff = abs(_to_min(e['shuttle']) - target)
        if diff <= window_min and (best is None or diff < best['diff_min']):
            best = {'found': True, 'service': 'fixed', 'slot': e['slot'],
                    'shuttle_time': e['shuttle'], 'ktx_time': e['ktx'], 'diff_min': diff}
    # 동적 조건부 (모든 실재 열차 시각)
    for ktx in timetable.all_times():
        st = shuttle_time_for(direction, ktx)
        diff = abs(_to_min(st) - target)
        if diff <= window_min and (best is None or diff < best['diff_min']):
            best = {'found': True, 'service': 'conditional', 'slot': f'{wd_kr} {ktx}',
                    'shuttle_time': st, 'ktx_time': ktx, 'diff_min': diff}
    if best is None:
        return {'found': False, 'note': f'출발 희망 {desired_time} 근방 {window_min}분 내 셔틀 없음'}
    return best


TURNAROUND_MIN = 50   # 한 운행 점유(왕복 40 + 정비/대기). 다음 운행은 이만큼 떨어져야
MAX_RUNS_PER_DAY = 6  # 기사 근로시간 상 하루 최대 운행 횟수


def _wd_of_date(date):
    from datetime import datetime
    return datetime.strptime(date.strip(), '%Y-%m-%d').weekday()


def daily_dispatch(store, date, fare=POLICY_FARE,
                   turnaround_min=TURNAROUND_MIN, max_runs=MAX_RUNS_PER_DAY):
    """버스 1대 기준 하루 실제 운행 스케줄 결정.

    고정편 = 항상 운행(커밋). 조건부 = N* 충족분을 수요 많은 순으로,
    이미 확정된 운행과 turnaround_min 내 겹치지 않고 일 최대 max_runs 안에서 선택.
    반환: {confirmed:[...], bumped:[...]} (bumped = 수요는 찼으나 차량 제약으로 미운행).
    """
    wd = _wd_of_date(date)
    n_star = breakeven_N(fare)

    confirmed = []
    for direction, entries in SHUTTLE_FIXED.items():
        for e in entries:
            if e['wd'] == wd:
                confirmed.append({'service': 'fixed', 'direction': direction, 'slot': e['slot'],
                                  'shuttle_time': e['shuttle'], 'ktx': e['ktx'],
                                  'count': store.count(direction, e['ktx'], date)})
    fixed_keys = {(c['direction'], c['ktx']) for c in confirmed}

    counts = {}
    for r in store.all_records():
        if str(r.get('travel_date')) == date:
            k = (str(r.get('direction')), str(r.get('ktx_time')))
            counts[k] = counts.get(k, 0) + 1
    cands = [{'service': 'conditional', 'direction': d, 'slot': f'{k} 조건부',
              'shuttle_time': shuttle_time_for(d, k), 'ktx': k, 'count': c}
             for (d, k), c in counts.items()
             if (d, k) not in fixed_keys and c >= n_star]
    cands.sort(key=lambda c: (-c['count'], c['shuttle_time']))   # 수요 많은 순(=순편익 큰 순)

    bumped = []
    for c in cands:
        if len(confirmed) >= max_runs:
            bumped.append({**c, 'reason': '일 최대 운행 초과'})
            continue
        if any(abs(_to_min(c['shuttle_time']) - _to_min(x['shuttle_time'])) < turnaround_min
               for x in confirmed):
            bumped.append({**c, 'reason': '다른 운행과 시간 겹침'})
            continue
        confirmed.append(c)
    confirmed.sort(key=lambda c: c['shuttle_time'])
    return {'date': date, 'n_star': n_star, 'confirmed': confirmed, 'bumped': bumped,
            'turnaround_min': turnaround_min, 'max_runs': max_runs}


def all_slots():
    """리포트용: (service, direction, slot dict) 전체 평탄화."""
    out = []
    for svc, table in (('fixed', SHUTTLE_FIXED), ('conditional', SHUTTLE_CONDITIONAL)):
        for direction, entries in table.items():
            for e in entries:
                out.append({'service': svc, 'direction': direction, **e})
    return out
