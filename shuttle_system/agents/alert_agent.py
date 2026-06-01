"""알림(Notification) Agent — 능동 감지 + 메시지 작성.

감지(코드, 결정론적): 예약 데이터에서 이벤트 추출
  - dispatch: 조건부 슬롯 예약이 N* 돌파 → 운행 확정
  - carpool : 셔틀 미운행(조건부 미달/슬롯없음)인데 같은 슬롯 예약자 ≥2명 → 카풀 가능
  - delay   : 513 지연 (데모용 시뮬레이션 트리거)
작성(LLM, 선택): 이벤트를 사람 말 메시지로. 실패 시 템플릿 폴백.
중복 방지: 알림 로그에 (type, direction, ktx_time, travel_date) 있으면 skip.
"""
from collections import Counter
from datetime import datetime

from shuttle_system.config import get_secret
from shuttle_system.core.optimization import breakeven_N, POLICY_FARE
from shuttle_system.core.schedule import find_shuttle_slot

MODEL = 'gpt-4o-mini'


def _wd(date):
    return datetime.strptime(str(date).strip(), '%Y-%m-%d').weekday()


def detect_events(store, fare=POLICY_FARE, simulate_delay=False):
    """예약 데이터에서 알림 이벤트를 추출(결정론적)."""
    n_star = breakeven_N(fare)
    groups = Counter()
    for r in store.all_records():
        groups[(str(r.get('direction')), str(r.get('ktx_time')), str(r.get('travel_date')))] += 1

    events = []
    for (direction, ktx, date), count in groups.items():
        try:
            wd = _wd(date)
        except ValueError:
            continue
        slot = find_shuttle_slot(direction, ktx, wd, reservations=count, fare=fare)
        running = (slot['service'] == 'fixed'
                   or (slot['service'] == 'conditional' and count >= n_star))
        if slot['service'] == 'conditional' and count >= n_star:
            events.append({'type': 'dispatch', 'direction': direction, 'ktx_time': ktx,
                           'travel_date': date, 'slot': slot.get('slot', ''), 'count': count,
                           'n_star': n_star})
        if not running and count >= 2:
            from shuttle_system.agents.carpool_agent import fare_for_time, TAXI_CAPACITY
            group = min(count, TAXI_CAPACITY)
            events.append({'type': 'carpool', 'direction': direction, 'ktx_time': ktx,
                           'travel_date': date, 'count': count,
                           'per_person': round(fare_for_time(ktx) / group)})
    if simulate_delay and groups:
        (direction, ktx, date), count = next(iter(groups.items()))
        events.append({'type': 'delay', 'direction': direction, 'ktx_time': ktx,
                       'travel_date': date, 'count': count, 'delay_min': 10})
    return events


def _template_message(e):
    d = '울산역행' if e['direction'] == 'to_station' else '캠퍼스행'
    if e['type'] == 'dispatch':
        return (f"🚌 [운행 확정] {e['travel_date']} {e['ktx_time']} {d} 셔틀이 예약 "
                f"{e['count']}명(N*={e['n_star']})으로 운행 확정되었습니다!")
    if e['type'] == 'carpool':
        return (f"🚕 [카풀 가능] {e['travel_date']} {e['ktx_time']} {d}, 같은 시각 {e['count']}명이 "
                f"있어요. 택시 카풀 시 1인 약 {e['per_person']:,}원!")
    if e['type'] == 'delay':
        return (f"⚠️ [지연 경고] {e['ktx_time']} {d} 연계 513이 지연 중입니다. "
                f"약 {e['delay_min']}분 일찍 출발하세요.")
    return str(e)


def _key(e):
    return (e['type'], e['direction'], e['ktx_time'], e['travel_date'])


def run_notification_check(store, fare=POLICY_FARE, simulate_delay=False,
                           composer=None, pusher=None):
    """새 이벤트만 알림 저장소에 기록하고, 생성된 알림 리스트를 반환.

    pusher가 주어지면 생성된 알림마다 pusher(message)를 호출해 외부 발송(예: 카톡).
    pusher는 예외를 던져도 전체 흐름을 막지 않는다.
    """
    compose = composer or _template_message
    existing = {(str(n.get('type')), str(n.get('direction')), str(n.get('ktx_time')),
                 str(n.get('travel_date'))) for n in store.all_notifications()}
    created = []
    for e in detect_events(store, fare, simulate_delay):
        if _key(e) in existing:
            continue
        rec = {'type': e['type'], 'direction': e['direction'], 'ktx_time': e['ktx_time'],
               'travel_date': e['travel_date'], 'message': compose(e)}
        store.add_notification(rec)
        created.append(rec)
        existing.add(_key(e))
        if pusher:
            try:
                pusher(rec['message'])
            except Exception:
                pass
    return created


def llm_compose(event):
    """LLM이 이벤트를 사람 말 메시지로. 실패 시 템플릿 폴백."""
    try:
        from openai import OpenAI
        client = OpenAI(api_key=get_secret('OPENAI_API_KEY'))
        prompt = ("아래 이벤트를 학생에게 보낼 1문장 한국어 알림으로 작성해라. 이모지 1개, "
                  "주어진 숫자만 사용. JSON: " + str(event))
        resp = client.chat.completions.create(
            model=MODEL, messages=[{'role': 'user', 'content': prompt}])
        return resp.choices[0].message.content.strip()
    except Exception:
        return _template_message(event)
