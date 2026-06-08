"""KTX ↔ 513 연계 판정과 택시 추정. 모든 시간 계산은 코드가 담당. 순수 함수."""
from datetime import datetime, timedelta

RIDE_MIN = 20             # 513 UNIST↔울산역 평균 소요(분)
KTX_BOARDING_BUFFER = 5   # 역 도착 후 발권/승차 준비(분)
STATION_EXIT_MIN = 5      # KTX 하차 후 정류장 이동(분)

TAXI_EST = {'est_time_min': 18, 'est_fare_krw': '약 13,000~16,000원'}


def _parse_hhmm(value, base):
    t = datetime.strptime(value.strip(), '%H:%M').time()
    return base.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)


def evaluate_connection(direction, bus_arrival_min, train_time,
                        walk_to_stop_min=5, now=None):
    """KTX 시각과 실시간 513 도착을 대조해 연계 가능 여부를 결정론적으로 계산."""
    now = now or datetime.now()
    facts = {'direction': direction, 'now': now.strftime('%H:%M'),
             'bus_arrival_min': bus_arrival_min, 'train_time': train_time}

    if direction == 'to_station':
        ktx_dep = _parse_hhmm(train_time, now)
        if bus_arrival_min < walk_to_stop_min:
            facts.update(status='BUS_TOO_SOON',
                         reason=f'정류장까지 도보 {walk_to_stop_min}분인데 버스가 '
                                f'{bus_arrival_min}분 후 도착 → 이번 513 탑승 불가',
                         recommend='다음 513 또는 고정 시간표 확인 필요')
            return facts
        board = now + timedelta(minutes=bus_arrival_min)
        arrive_st = board + timedelta(minutes=RIDE_MIN)
        slack_min = round((ktx_dep - arrive_st).total_seconds() / 60)
        eff_slack = slack_min - KTX_BOARDING_BUFFER
        if arrive_st >= ktx_dep:
            status, recommend = 'MISS', '이 KTX는 놓침 → 다음 열차/택시 검토'
        elif eff_slack < 10:
            status, recommend = 'TIGHT', '탑승 가능하나 빠듯 → 바로 정류장으로 이동'
        else:
            status, recommend = 'SAFE', '여유 있음 → 정시 출발하면 OK'
        facts.update(status=status, board_time=board.strftime('%H:%M'),
                     station_arrival=arrive_st.strftime('%H:%M'),
                     ktx_departure=ktx_dep.strftime('%H:%M'),
                     slack_min=slack_min, effective_slack_min=eff_slack,
                     recommend=recommend)
        return facts

    # to_campus
    ktx_arr = _parse_hhmm(train_time, now)
    ready = ktx_arr + timedelta(minutes=STATION_EXIT_MIN)
    depart = now + timedelta(minutes=bus_arrival_min)
    wait = round((depart - ready).total_seconds() / 60)
    if depart < ready:
        status, recommend = 'BUS_BEFORE_READY', '이 513은 하차 전 출발 → 다음 차/택시 검토'
    elif wait <= 10:
        status, recommend = 'GOOD', '하차 후 바로 탑승 가능'
    else:
        status, recommend = 'LONG_WAIT', f'정류장에서 약 {wait}분 대기 예상'
    facts.update(status=status, ktx_arrival=ktx_arr.strftime('%H:%M'),
                 ready_time=ready.strftime('%H:%M'),
                 bus_departure=depart.strftime('%H:%M'), wait_min=wait,
                 recommend=recommend)
    return facts


def recommend_taxi(direction):
    """최후 대안: 택시(상시)."""
    return {'mode': 'taxi', **TAXI_EST,
            'note': '상시 이용 가능. 심야(00~04시) 할증 가능. 최후 대안.'}
