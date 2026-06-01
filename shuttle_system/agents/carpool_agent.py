"""카풀(Carpool) Agent — 자동 4명 그룹 편성.

신청자(carpool 요청)를 같은 (방향·시각·날짜)로 모아 최대 4명씩 그룹으로 묶는다.
- 만남 장소: 방향별 사전 지정
- 만남 시각: 기준 시각 ~ +10분 윈도우
- 1인 요금: 택시요금(시간대 할증) ÷ 그룹 인원
- 확정: 출발 15분 전(또는 finalize=True)이면 그 시점 인원으로 확정.
  확정 시 1명뿐이면 카풀 불가.
모든 계산은 코드(결정론적). 메시지 작성만 LLM(선택).
"""
from collections import defaultdict
from datetime import datetime, timedelta

TAXI_CAPACITY = 4
WINDOW_MIN = 10            # 만남 시각 윈도우(+10분)
CONFIRM_BEFORE_MIN = 15    # 출발 15분 전 확정
FARE_NORMAL = 10_000
FARE_LATE = 14_000
# 심야 할증 시간대(상수 — 울산 공식 미공개, 흔한 표준 22~04로 둠. 00~04로 바꾸려면 22->0)
SURCHARGE_START_HOUR = 22
SURCHARGE_END_HOUR = 4

MEETING_PLACE = {
    'to_station': 'UNIST 정문 버스정류장',
    'to_campus': '울산역 택시승강장',
}


def fare_for_time(hhmm):
    """기준 시각의 택시요금(할증 반영)."""
    h = int(hhmm.split(':')[0])
    late = (h >= SURCHARGE_START_HOUR) or (h < SURCHARGE_END_HOUR)
    return FARE_LATE if late else FARE_NORMAL


def _dt(date, hhmm):
    return datetime.strptime(f'{date} {hhmm}', '%Y-%m-%d %H:%M')


def _plus(hhmm, minutes):
    base = datetime.strptime(hhmm, '%H:%M') + timedelta(minutes=minutes)
    return base.strftime('%H:%M')


def form_carpool_groups(store, now=None, finalize=False):
    """카풀 신청을 (방향·시각·날짜)별로 모아 4명씩 그룹 편성.

    각 그룹: {direction, ktx_time, travel_date, members, size, place,
             meet_from, meet_to, fare, per_person, status, group_no}
    status: 'collecting' | 'confirmed' | 'no_carpool'
    """
    now = now or datetime.now()
    buckets = defaultdict(list)
    for r in store.all_carpool_requests():
        key = (str(r.get('direction')), str(r.get('ktx_time')), str(r.get('travel_date')))
        buckets[key].append((str(r.get('created_at', '')), str(r.get('name', ''))))

    groups = []
    for (direction, ktx, date), reqs in buckets.items():
        reqs.sort()  # 신청 순
        members_all = [n for _, n in reqs]
        try:
            confirmed_time = _dt(date, ktx) - timedelta(minutes=CONFIRM_BEFORE_MIN)
            is_confirmed = finalize or now >= confirmed_time
        except ValueError:
            is_confirmed = finalize
        fare = fare_for_time(ktx)
        place = MEETING_PLACE.get(direction, '미정')
        # 4명씩 청크
        for i in range(0, len(members_all), TAXI_CAPACITY):
            chunk = members_all[i:i + TAXI_CAPACITY]
            size = len(chunk)
            if is_confirmed and size == 1:
                status = 'no_carpool'
            elif is_confirmed:
                status = 'confirmed'
            else:
                status = 'collecting'
            groups.append({
                'direction': direction, 'ktx_time': ktx, 'travel_date': date,
                'members': chunk, 'size': size, 'place': place,
                'meet_from': ktx, 'meet_to': _plus(ktx, WINDOW_MIN),
                'fare': fare, 'per_person': round(fare / size),
                'status': status, 'group_no': i // TAXI_CAPACITY + 1})
    return groups


_WD = '월화수목금토일'


def _fmt_date(date):
    from datetime import datetime as _dtm
    try:
        dt = _dtm.strptime(str(date).strip(), '%Y-%m-%d')
        return f'{dt.month}/{dt.day}({_WD[dt.weekday()]})'
    except ValueError:
        return str(date)


def group_message(g):
    """그룹을 사람 말 알림으로(템플릿)."""
    d = '울산역행' if g['direction'] == 'to_station' else '캠퍼스행'
    when = f"{_fmt_date(g['travel_date'])} {g['ktx_time']}"
    members = ', '.join(g['members'])
    if g['status'] == 'no_carpool':
        return (f"🚕 [카풀 미성사] {when} {d}: 현재 신청자 1명뿐이라 카풀이 성사되지 않았어요. "
                f"단독 택시 또는 513 버스를 이용해 주세요.")
    if g['status'] == 'confirmed':
        return (f"🚕 [카풀 확정] {when} {d} {g['group_no']}조 ({g['size']}명: {members}) — "
                f"📍{g['place']}에서 {g['meet_from']}~{g['meet_to']} 사이 만나 출발하세요. "
                f"1인 약 {g['per_person']:,}원(택시요금 ÷ {g['size']}명).")
    return (f"🚕 [카풀 모집 중] {when} {d} {g['group_no']}조 ({g['size']}/{TAXI_CAPACITY}명) — "
            f"📍{g['place']} {g['meet_from']}~{g['meet_to']} · 현재 1인 약 {g['per_person']:,}원. "
            f"출발 15분 전 최종 확정됩니다.")
