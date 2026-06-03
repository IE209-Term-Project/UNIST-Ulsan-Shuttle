"""고정 8 + 조건부 5 셔틀 슬롯 데이터와 요일+KTX 매칭. 순수 함수.

조건부 임계값은 하드코딩이 아니라 optimization.breakeven_N()에서 가져온다.
"""
from shuttle_system.core.optimization import breakeven_N, POLICY_FARE

WEEKDAY_KR = '월화수목금토일'

# 셔틀 그리드 분 (방향별 — 데이터 분석으로 결정)
# to_station: KTX 출발 25~60분 전이 적합 → :10 그리드 최적 (정각·반시 KTX 잡음)
# to_campus:  KTX 도착 5~25분 후가 적합  → :30 그리드 최적
GRID_MIN = {'to_station': 10, 'to_campus': 30}
MATCH_BEFORE = (25, 60)   # to_station: 셔틀 출발 ~ KTX 출발 사이 분
MATCH_AFTER = (5, 25)     # to_campus:  KTX 도착 ~ 셔틀 출발 사이 분

# 고정 8편 (설문 수요 ≥ 20명 기준 + 목 저녁 보장)
# wd: 0=월, 1=화, ..., 6=일
SHUTTLE_FIXED = {
    'to_station': [
        {'slot': '토 오전', 'wd': 5, 'shuttle': '08:30', 'demand': 26},
        {'slot': '금 오후', 'wd': 4, 'shuttle': '13:50', 'demand': 57},
        {'slot': '목 저녁', 'wd': 3, 'shuttle': '18:20', 'demand': 24},
        {'slot': '금 저녁', 'wd': 4, 'shuttle': '18:20', 'demand': 51},
    ],
    'to_campus': [
        {'slot': '월 오전', 'wd': 0, 'shuttle': '09:30', 'demand': 31},
        {'slot': '일 오후', 'wd': 6, 'shuttle': '15:00', 'demand': 36},
        {'slot': '일 저녁', 'wd': 6, 'shuttle': '18:30', 'demand': 54},
        {'slot': '일 야간', 'wd': 6, 'shuttle': '21:00', 'demand': 61},
    ],
}

# 조건부 후보 그리드 (모든 요일 공통 — 8명 모이면 운행)
# 고정과 같은 시각이 있으면 자동으로 고정 우선
CONDITIONAL_GRID_HOURS = list(range(8, 23))   # 08~22시 (저녁·야간 포함)
SHUTTLE_CONDITIONAL = {'to_station': [], 'to_campus': []}  # 동적 생성 (find_shuttle_slot에서 처리)


DEPART_LEAD = 17   # 출발(to_station) 셔틀 = KTX − 17분
ARRIVE_LAG = 15    # 복귀(to_campus) 셔틀 = KTX + 15분


def _shift(hhmm, minutes):
    from datetime import datetime, timedelta
    return (datetime.strptime(hhmm, '%H:%M') + timedelta(minutes=minutes)).strftime('%H:%M')


def shuttle_time_for(direction, ktx):
    """KTX 시각 → 셔틀 시각(출발 −17 / 복귀 +15)."""
    return _shift(ktx, -DEPART_LEAD if direction == 'to_station' else ARRIVE_LAG)


def _to_min(hhmm):
    h, m = hhmm.strip().split(':')
    return int(h) * 60 + int(m)


def grid_shuttle_time_for(direction, ktx_time):
    """학생이 입력한 KTX 시각 → 그 방향 그리드에서 가장 적합한 셔틀 시각.

    to_station: KTX 출발 25~60분 전 그리드 슬롯 (없으면 가장 가까운 -25분 이상)
    to_campus:  KTX 도착 5~25분 후 그리드 슬롯
    매칭 가능한 그리드가 없으면 None.
    """
    gmin = GRID_MIN[direction]
    ktx_m = _to_min(ktx_time)
    # 후보: 06~23시의 :gmin 그리드
    best = None
    for h in range(5, 24):
        sm = h * 60 + gmin
        if direction == 'to_station':
            gap = ktx_m - sm
            lo, hi = MATCH_BEFORE
        else:
            gap = sm - ktx_m
            lo, hi = MATCH_AFTER
        if lo <= gap <= hi:
            if best is None or gap < best[1]:   # 가장 가까운(작은 gap) 선택
                best = (sm, gap)
    if best is None:
        return None
    return f'{best[0]//60:02d}:{best[0]%60:02d}'


def find_shuttle_slot(direction, key, weekday, reservations=0, fare=POLICY_FARE):
    """슬롯 조회. key는 셔틀 시각(HH:MM) — 그리드 기반.

    1) 요일+셔틀시각이 고정편이면 → fixed
    2) 그리드 시각(:10 또는 :30)이면 → conditional (N* 차면 운행)
    3) 그 외(임의 시각) → 셔틀 없음
    """
    key = key.strip()
    wd_kr = WEEKDAY_KR[weekday] + '요일'
    gmin = GRID_MIN.get(direction, 10)

    # 1) 고정
    for e in SHUTTLE_FIXED.get(direction, []):
        if e['wd'] == weekday and e['shuttle'] == key:
            return {'available': True, 'service': 'fixed', 'mode': 'shuttle',
                    'weekday': wd_kr, 'slot': e['slot'], 'shuttle_time': e['shuttle'],
                    'ktx_time': key, 'note': '고정 운행 확정편'}

    # 2) 그리드 (조건부)
    try:
        hh, mm = key.split(':')
        if int(mm) == gmin and 5 <= int(hh) <= 23:
            n_star = breakeven_N(fare)
            ok = reservations >= n_star
            return {'available': ok, 'service': 'conditional', 'mode': 'shuttle',
                    'weekday': wd_kr, 'slot': f'{wd_kr} {key}',
                    'shuttle_time': key, 'ktx_time': key,
                    'reservations': reservations, 'required': n_star,
                    'note': (f'조건부 — 예약 {reservations}명 ≥ N*({n_star}) → 배차 확정'
                             if ok else
                             f'조건부 — 예약 {reservations}/{n_star}명 → 배차 미정, 대체수단 검토')}
    except ValueError:
        pass

    return {'available': False, 'service': None, 'mode': 'shuttle', 'weekday': wd_kr,
            'note': '해당 시각에 운행 가능한 셔틀 없음 → 513/택시 검토'}


def find_shuttle_near(direction, desired_time, weekday, window_min=60, fare=POLICY_FARE):
    """'출발 희망 시각'에 가장 가까운 그리드 셔틀 슬롯을 찾는다.

    그리드 시각(:10 또는 :30)에 desired_time을 매핑. window_min(기본 60) 이내만 매칭.
    예약 키는 셔틀 시각 자체(HH:MM)로 통일.
    """
    target = _to_min(desired_time)
    wd_kr = WEEKDAY_KR[weekday] + '요일'
    best = None

    # 1) 고정 우선 (해당 요일)
    for e in SHUTTLE_FIXED.get(direction, []):
        if e['wd'] != weekday:
            continue
        diff = abs(_to_min(e['shuttle']) - target)
        if diff <= window_min and (best is None or diff < best['diff_min']):
            best = {'found': True, 'service': 'fixed', 'slot': e['slot'],
                    'shuttle_time': e['shuttle'], 'ktx_time': e['shuttle'], 'diff_min': diff}

    # 2) 조건부 그리드 (모든 :gmin 시각, 5~23시)
    gmin = GRID_MIN.get(direction, 10)
    for h in range(5, 24):
        sm = h * 60 + gmin
        diff = abs(sm - target)
        if diff <= window_min and (best is None or diff < best['diff_min']):
            hhmm = f'{h:02d}:{gmin:02d}'
            best = {'found': True, 'service': 'conditional', 'slot': f'{wd_kr} {hhmm}',
                    'shuttle_time': hhmm, 'ktx_time': hhmm, 'diff_min': diff}

    if best is None:
        return {'found': False, 'note': f'출발 희망 {desired_time} 근방 {window_min}분 내 셔틀 없음'}
    return best


def grid_options(direction):
    """방향별 그리드 시각 리스트(05:10~23:10 또는 05:30~23:30)."""
    gmin = GRID_MIN.get(direction, 10)
    return [f'{h:02d}:{gmin:02d}' for h in range(5, 24)]


TURNAROUND_MIN = 50    # 한 운행 점유(왕복 40 + 정비/대기). 다음 운행은 이만큼 떨어져야
MAX_RUNS_PER_DAY = 6   # 기사 근로시간 상 하루 최대 운행 횟수
CUTOFF_HOURS = 2       # 출발 N시간 전 = 마감 시각 (잠정 → 확정/미운행 결정)
VEHICLE_CAPACITY = 25  # 셔틀 1대 정원


def slot_phase(shuttle_time_hhmm, travel_date, now=None):
    """슬롯의 현 시점 단계: 'open' | 'closing_soon' | 'closed'.

    open: 마감 전(모집 중). closing_soon: 30분 이내 마감 임박. closed: 마감 지남.
    """
    from datetime import datetime, timedelta
    now = now or datetime.now()
    try:
        depart = datetime.strptime(f'{travel_date} {shuttle_time_hhmm}', '%Y-%m-%d %H:%M')
    except ValueError:
        return 'open'
    cutoff = depart - timedelta(hours=CUTOFF_HOURS)
    if now >= cutoff:
        return 'closed'
    if now >= cutoff - timedelta(minutes=30):
        return 'closing_soon'
    return 'open'


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
                                  'shuttle_time': e['shuttle'], 'ktx': e['shuttle'],
                                  'count': store.count(direction, e['shuttle'], date)})
    fixed_keys = {(c['direction'], c['ktx']) for c in confirmed}

    counts = {}
    for r in store.all_records():
        if str(r.get('travel_date')) == date:
            k = (str(r.get('direction')), str(r.get('ktx_time')))
            counts[k] = counts.get(k, 0) + 1
    # 그리드 시각인 예약만 (셔틀 시각으로 키 통일)
    cands = [{'service': 'conditional', 'direction': d, 'slot': f'{k} 조건부',
              'shuttle_time': k, 'ktx': k, 'count': c}
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
