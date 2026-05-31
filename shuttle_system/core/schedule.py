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


def all_slots():
    """리포트용: (service, direction, slot dict) 전체 평탄화."""
    out = []
    for svc, table in (('fixed', SHUTTLE_FIXED), ('conditional', SHUTTLE_CONDITIONAL)):
        for direction, entries in table.items():
            for e in entries:
                out.append({'service': svc, 'direction': direction, **e})
    return out
