"""결정론적 추천 (LLM 없음) — 빠르고 일관적.

셔틀 슬롯이 있으면 예약하고, 없으면 513/택시/카풀을 안내한다.
모든 판단/문구는 코드가 생성(테스트 가능).
"""
from datetime import datetime

from shuttle_system.core.optimization import breakeven_N, POLICY_FARE
from shuttle_system.core.schedule import (
    find_shuttle_slot, find_shuttle_near, slot_phase, VEHICLE_CAPACITY, CUTOFF_HOURS,
)
from shuttle_system.agents.notify_agent import taxi_share_logic


def weekday_of(travel_date):
    return datetime.strptime(travel_date.strip(), '%Y-%m-%d').weekday()


def resolve_ktx(store, direction, mode, train_time, desire_time, travel_date, fare=POLICY_FARE):
    """입력 모드에 따라 예약 키 ktx_time과 설명을 결정.

    mode='train' → train_time 그대로. mode='time' → 근방 셔틀 매칭.
    returns (ktx_time or None, info_text).
    """
    if mode == 'train':
        if not train_time:
            return None, '열차 시각을 선택하세요.'
        return train_time.strip(), f'선택 시각 {train_time.strip()}'
    if not (desire_time and desire_time.strip()):
        return None, '출발 희망 시각을 입력하세요.'
    try:
        wd = weekday_of(travel_date)
    except ValueError:
        return None, '날짜 형식 오류 (YYYY-MM-DD).'
    near = find_shuttle_near(direction, desire_time.strip(), wd, fare=fare)
    if near['found']:
        return near['ktx_time'], (f"가장 가까운 셔틀 {near['shuttle_time']} "
                                  f"({near['diff_min']}분 차)")
    return desire_time.strip(), '근방 30분 내 셔틀 없음 → 513/택시/카풀 검토'


def slot_status(store, direction, ktx_time, travel_date, fare=POLICY_FARE):
    """예약 없이 현재 상태(예약 인원 + 배차 셔틀)를 조회."""
    wd = weekday_of(travel_date)
    n_star = breakeven_N(fare)
    count = store.count(direction, ktx_time, travel_date)
    slot = find_shuttle_slot(direction, ktx_time, wd, reservations=count, fare=fare)
    return {'reservations': count, 'n_star': n_star, 'service': slot['service'],
            'shuttle_time': slot.get('shuttle_time'), 'available': slot.get('available', False)}


def recommend(store, name, direction, ktx_time, travel_date, fare=POLICY_FARE, do_book=True):
    """결정론적 추천 + (셔틀 슬롯이면) 예약 수행.

    returns dict(mode, message, booked, reservations, required, service, shuttle_time).
    """
    wd = weekday_of(travel_date)
    n_star = breakeven_N(fare)
    before = store.count(direction, ktx_time, travel_date)
    slot = find_shuttle_slot(direction, ktx_time, wd, reservations=before, fare=fare)
    service = slot['service']
    dir_kr = '울산역행' if direction == 'to_station' else '캠퍼스행'

    # 마감 여부·정원 체크
    phase = slot_phase(slot.get('shuttle_time') or ktx_time, travel_date) if service else 'open'
    is_closed = (phase == 'closed')
    is_full = (service in ('fixed', 'conditional') and before >= VEHICLE_CAPACITY)

    booked = False
    if service in ('fixed', 'conditional') and do_book and not is_closed and not is_full:
        store.add(name, direction, ktx_time, travel_date)
        booked = True
    count = store.count(direction, ktx_time, travel_date)

    # 닫힘/만석은 예약 거부 + 대체 안내
    if service in ('fixed', 'conditional') and (is_closed or is_full):
        reason = ('이미 마감되어' if is_closed else f'정원({VEHICLE_CAPACITY}명) 도달로')
        share = taxi_share_logic(store, direction, ktx_time, travel_date)
        return {'mode': 'alt', 'booked': False, 'reservations': count, 'required': n_star,
                'service': service, 'shuttle_time': slot.get('shuttle_time'),
                'phase': phase,
                'message': (f"❌ 예약 불가 — 이 셔틀은 {reason} 예약이 마감되었습니다. "
                            f"같은 시각 {share['group_size']}명과 택시 카풀(1인 약 "
                            f"{share['per_person_krw']:,}원) 또는 513 버스를 이용하세요.")}

    if service == 'fixed':
        return {'mode': 'shuttle', 'booked': booked, 'reservations': count, 'required': None,
                'service': service, 'shuttle_time': slot['shuttle_time'], 'phase': phase,
                'message': f"✅ 예약 완료! {ktx_time} {dir_kr} 고정 셔틀이 "
                           f"{slot['shuttle_time']}에 출발합니다. 시간 맞춰 정류장으로 오세요."}

    if service == 'conditional':
        soon = ' (마감 임박!)' if phase == 'closing_soon' else ''
        if count >= n_star:
            msg = (f"📝 잠정 예약 완료! 현재 {count}/{n_star}명 충족 — 마감(출발 {CUTOFF_HOURS}시간 전) "
                   f"시 단일 차량 가능하면 {slot['shuttle_time']} 셔틀 **확정**됩니다.{soon} "
                   f"확정/미운행은 마감 시 카톡으로 알려드려요.")
        else:
            share = taxi_share_logic(store, direction, ktx_time, travel_date)
            msg = (f"📝 잠정 예약 접수! 현재 {count}/{n_star}명 — {n_star - count}명 더 모이면 "
                   f"마감 시 {slot['shuttle_time']} 셔틀이 확정됩니다.{soon} 미달 시 같은 시각 "
                   f"{share['group_size']}명과 택시 카풀(1인 약 {share['per_person_krw']:,}원·최대 4명) "
                   f"또는 513 버스 안내가 카톡으로 갑니다.")
        return {'mode': 'shuttle', 'booked': booked, 'reservations': count,
                'required': n_star, 'service': service, 'phase': phase,
                'shuttle_time': slot['shuttle_time'], 'message': msg}

    # 셔틀 슬롯 없음
    share = taxi_share_logic(store, direction, ktx_time, travel_date)
    if share['group_size'] >= 2:
        msg = (f"이 시각엔 배차된 셔틀이 없어요. 같은 시각 이동 {share['group_size']}명과 "
               f"택시 카풀 시 1인 약 {share['per_person_krw']:,}원! 아래 '카풀 신청'을 누르세요. "
               f"또는 513 버스를 이용할 수 있어요.")
    else:
        msg = ("이 시각엔 배차된 셔틀이 없어요. 513 버스 또는 택시 이용을 추천합니다. "
               "같은 시각 예약자가 더 생기면 카풀도 가능해요.")
    return {'mode': 'alt', 'booked': False, 'reservations': count, 'required': None,
            'service': None, 'shuttle_time': None, 'message': msg}
