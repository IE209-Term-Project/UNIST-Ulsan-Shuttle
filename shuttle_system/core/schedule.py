"""고정 8 + 조건부 5 셔틀 슬롯 데이터와 요일+KTX 매칭. 순수 함수.

조건부 임계값은 하드코딩이 아니라 optimization.breakeven_N()에서 가져온다.
"""
from shuttle_system.core.optimization import breakeven_N, POLICY_FARE

WEEKDAY_KR = '월화수목금토일'

# 고정 8회: 출발=KTX 17분 전 / 복귀=KTX 도착 15분 후 (확정 운행)
SHUTTLE_FIXED = {
    'to_station': [
        {'slot': '금 오후', 'wd': 4, 'ktx': '13:58', 'shuttle': '13:41', 'demand': 57},
        {'slot': '금 저녁', 'wd': 4, 'ktx': '17:51', 'shuttle': '17:34', 'demand': 51},
        {'slot': '목 저녁', 'wd': 3, 'ktx': '17:51', 'shuttle': '17:34', 'demand': 24},
        {'slot': '토 오전', 'wd': 5, 'ktx': '10:02', 'shuttle': '09:45', 'demand': 26},
    ],
    'to_campus': [
        {'slot': '월 오전', 'wd': 0, 'ktx': '08:45', 'shuttle': '09:00', 'demand': 31},
        {'slot': '일 오후', 'wd': 6, 'ktx': '12:07', 'shuttle': '12:22', 'demand': 36},
        {'slot': '일 저녁', 'wd': 6, 'ktx': '18:43', 'shuttle': '18:58', 'demand': 54},
        {'slot': '일 야간', 'wd': 6, 'ktx': '20:29', 'shuttle': '20:44', 'demand': 61},
    ],
}

# 조건부 5회: 예약 >= N* 일 때만 1회 배차 (전부 출발 방향)
SHUTTLE_CONDITIONAL = {
    'to_station': [
        {'slot': '목 오후', 'wd': 3, 'ktx': '13:58', 'shuttle': '13:41', 'demand': 13},
        {'slot': '목 야간', 'wd': 3, 'ktx': '22:39', 'shuttle': '22:22', 'demand': 12},
        {'slot': '금 오전', 'wd': 4, 'ktx': '10:02', 'shuttle': '09:45', 'demand': 16},
        {'slot': '금 야간', 'wd': 4, 'ktx': '22:39', 'shuttle': '22:22', 'demand': 21},
        {'slot': '토 오후', 'wd': 5, 'ktx': '13:58', 'shuttle': '13:41', 'demand': 14},
    ],
    'to_campus': [],
}


def find_shuttle_slot(direction, ktx_time, weekday, reservations=0, fare=POLICY_FARE):
    """요일+KTX 시각으로 배정된 셔틀편을 찾는다. 고정 우선, 없으면 조건부."""
    ktx_time = ktx_time.strip()
    wd_kr = WEEKDAY_KR[weekday] + '요일'

    for e in SHUTTLE_FIXED.get(direction, []):
        if e['wd'] == weekday and e['ktx'] == ktx_time:
            return {'available': True, 'service': 'fixed', 'mode': 'shuttle',
                    'weekday': wd_kr, 'slot': e['slot'], 'shuttle_time': e['shuttle'],
                    'ktx_time': e['ktx'], 'note': '고정 운행 확정편'}

    n_star = breakeven_N(fare)
    for e in SHUTTLE_CONDITIONAL.get(direction, []):
        if e['wd'] == weekday and e['ktx'] == ktx_time:
            ok = reservations >= n_star
            return {'available': ok, 'service': 'conditional', 'mode': 'shuttle',
                    'weekday': wd_kr, 'slot': e['slot'], 'shuttle_time': e['shuttle'],
                    'ktx_time': e['ktx'], 'reservations': reservations,
                    'required': n_star,
                    'note': (f'조건부편 — 예약 {reservations}명 ≥ N*({n_star}) → 배차 확정'
                             if ok else
                             f'조건부편 — 예약 {reservations}/{n_star}명 → 배차 미정, 대체수단 검토')}

    return {'available': False, 'service': None, 'mode': 'shuttle', 'weekday': wd_kr,
            'note': '해당 요일/KTX 시각에 배정된 셔틀편 없음 → 513/택시 검토'}


def _to_min(hhmm):
    h, m = hhmm.strip().split(':')
    return int(h) * 60 + int(m)


def find_shuttle_near(direction, desired_time, weekday, window_min=30, fare=POLICY_FARE):
    """기차 없이 '출발 희망 시각'에 가장 가까운 셔틀 슬롯을 찾는다(셔틀 출발시각 기준).

    window_min 이내 최근접 슬롯을 반환. 예약은 그 슬롯의 ktx_time 키로 합류시킨다.
    """
    target = _to_min(desired_time)
    best = None
    for svc, table in (('fixed', SHUTTLE_FIXED), ('conditional', SHUTTLE_CONDITIONAL)):
        for e in table.get(direction, []):
            if e['wd'] != weekday:
                continue
            diff = abs(_to_min(e['shuttle']) - target)
            if diff <= window_min and (best is None or diff < best['diff_min']):
                best = {'found': True, 'service': svc, 'slot': e['slot'],
                        'shuttle_time': e['shuttle'], 'ktx_time': e['ktx'],
                        'diff_min': diff}
    if best is None:
        return {'found': False, 'note': f'출발 희망 {desired_time} 근방 {window_min}분 내 셔틀 없음'}
    return best


def all_slots():
    """리포트용: (service, direction, slot dict) 전체 평탄화."""
    out = []
    for svc, table in (('fixed', SHUTTLE_FIXED), ('conditional', SHUTTLE_CONDITIONAL)):
        for direction, entries in table.items():
            for e in entries:
                out.append({'service': svc, 'direction': direction, **e})
    return out
