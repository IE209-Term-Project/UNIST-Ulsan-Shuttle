"""Notification/Recommendation Agent — 셔틀→513→택시 캐스케이드 추천.

LLM은 도구 반환값을 해석·서술만 한다(계산 금지). 개인화: 모델 임계값 N* 노출 + 택시 셰어.
"""
import json
from dataclasses import dataclass
from datetime import datetime

from openai import OpenAI

from shuttle_system.config import get_secret
from shuttle_system.core.optimization import breakeven_N, POLICY_FARE
from shuttle_system.core.schedule import find_shuttle_slot
from shuttle_system.core.connection import evaluate_connection, recommend_taxi
from shuttle_system.agents.data_agent import fetch_513_arrival

MODEL = 'gpt-4o-mini'


def _weekday_of(travel_date):
    if travel_date:
        return datetime.strptime(travel_date.strip(), '%Y-%m-%d').weekday()
    return datetime.now().weekday()


def taxi_share_logic(store, direction, train_time, travel_date, exclude_name=None):
    """같은 슬롯 예약자 기반 택시 카풀 후보 집계. 택시 정원 4명 상한 + 시간대 할증 반영."""
    from shuttle_system.agents.carpool_agent import fare_for_time, TAXI_CAPACITY
    names = [n for n in store.names(direction, train_time, travel_date)
             if n != exclude_name]
    group = min(len(names) + 1, TAXI_CAPACITY)  # 본인 포함, 정원 4 상한
    fare = fare_for_time(train_time)
    per_person = round(fare / group) if group > 0 else fare
    return {'companions': names, 'group_size': group, 'taxi_capacity': TAXI_CAPACITY,
            'est_total_krw': fare, 'per_person_krw': per_person,
            'note': f'같은 {train_time} 예약자 {len(names)}명 → {group}명(최대4) 카풀 시 1인 약 {per_person}원'}


def _do_reserve(store, name, direction, train_time, travel_date):
    """행동: 실제 예약을 저장소에 기록."""
    store.add(name, direction, train_time, travel_date)
    n = store.count(direction, train_time, travel_date)
    return {'ok': True, 'current_reservations': n}


def _do_cancel(store, name, direction, train_time, travel_date):
    """행동: 같은 슬롯에서 해당 이름의 예약을 취소(데모 규모: 슬롯 전체 비우고 재기록)."""
    rows = [r for r in store.all_records()
            if not (str(r.get('direction')) == direction
                    and str(r.get('train_time')) == train_time
                    and str(r.get('travel_date')) == travel_date
                    and str(r.get('name')) == (name or '').strip())]
    # 슬롯 비우고 본인 외 예약 복원
    store.clear_slot(direction, train_time, travel_date)
    keep = [(r.get('name'), r.get('direction'), r.get('train_time'), r.get('travel_date'))
            for r in rows
            if str(r.get('direction')) == direction
            and str(r.get('train_time')) == train_time
            and str(r.get('travel_date')) == travel_date]
    if keep and hasattr(store, 'add_many'):
        store.add_many(keep)
    return {'ok': True, 'current_reservations': store.count(direction, train_time, travel_date)}


@dataclass
class StudentProfile:
    name: str
    direction: str
    train_time: str
    travel_date: str = None
    walk_to_stop_min: int = 5
    current_reservations: int = 0


class NotifyAgent:
    def __init__(self, store, fare=POLICY_FARE):
        self.store = store
        self.fare = fare
        self.client = OpenAI(api_key=get_secret('OPENAI_API_KEY'))

    def _build_tools(self, allow_booking):
        tools = {
            'find_shuttle': lambda direction, train_time, travel_date=None, reservations=0:
                json.dumps(find_shuttle_slot(direction, train_time,
                           _weekday_of(travel_date), reservations, self.fare),
                           ensure_ascii=False),
            'fetch_513_arrival': lambda direction:
                json.dumps(fetch_513_arrival(direction), ensure_ascii=False),
            'evaluate_connection': lambda direction, bus_arrival_min, train_time, walk_to_stop_min=5:
                json.dumps(evaluate_connection(direction, bus_arrival_min, train_time,
                           walk_to_stop_min), ensure_ascii=False, default=str),
            'recommend_taxi': lambda direction:
                json.dumps(recommend_taxi(direction), ensure_ascii=False),
            'find_taxi_share': lambda direction, train_time, travel_date:
                json.dumps(taxi_share_logic(self.store, direction, train_time, travel_date),
                           ensure_ascii=False),
        }
        if allow_booking:
            tools['make_reservation'] = lambda name, direction, train_time, travel_date: \
                json.dumps(_do_reserve(self.store, name, direction, train_time, travel_date),
                           ensure_ascii=False)
            tools['cancel_reservation'] = lambda name, direction, train_time, travel_date: \
                json.dumps(_do_cancel(self.store, name, direction, train_time, travel_date),
                           ensure_ascii=False)
        return tools

    def generate(self, profile, allow_booking=False, max_rounds=10):
        tools = self._build_tools(allow_booking)
        schema = TOOLS_SCHEMA + (BOOKING_TOOLS_SCHEMA if allow_booking else [])
        mode_note = (BOOKING_NOTE if allow_booking else RECOMMEND_ONLY_NOTE)
        messages = [{'role': 'system', 'content': SYSTEM_PROMPT + '\n\n' + mode_note},
                    {'role': 'user', 'content': _profile_message(profile, self.fare)}]
        msg = None
        for _ in range(max_rounds):
            resp = self.client.chat.completions.create(
                model=MODEL, messages=messages, tools=schema)
            msg = resp.choices[0].message
            messages.append(msg)
            if not msg.tool_calls:
                return msg.content
            for tc in msg.tool_calls:
                args = json.loads(tc.function.arguments)
                result = tools[tc.function.name](**args)
                messages.append({'role': 'tool', 'tool_call_id': tc.id, 'content': result})
        return (msg.content if msg else None) or '(도구 호출 한도 초과)'


def _profile_message(p, fare):
    dir_kr = ('울산과학기술원→울산역 (출발 KTX 탑승)' if p.direction == 'to_station'
              else '울산역→울산과학기술원 (KTX 하차 후 캠퍼스행)')
    return (f"학생: {p.name}\n방향: {dir_kr} (direction={p.direction})\n"
            f"KTX 시각: {p.train_time}\n여행 날짜: {p.travel_date or '오늘'}\n"
            f"정류장까지 도보: {p.walk_to_stop_min}분\n"
            f"조건부 셔틀 현재 예약: {p.current_reservations}명 (배차 임계 N*={breakeven_N(fare)})\n"
            f"위 학생에게 최적 교통수단을 우선순위대로 판단해 개인화 알림을 만들어줘.")


SYSTEM_PROMPT = """너는 UNIST ↔ 울산역 이동 학생에게 '최적 교통수단 1개'를 추천하는 에이전트다.
추천 우선순위(위에서부터 '이용 가능'한 첫 수단): 1순위 셔틀 → 2순위 513 → 3순위 택시.

[절차 — 한 번에 한 수단씩]
1) find_shuttle 호출.
   - service가 'fixed' 또는 'conditional'이면(셔틀 슬롯 존재) → 셔틀 안내.
   - available=false(조건부 N* 미달)이면 find_taxi_share도 호출: 같은 슬롯 예약자가
     1명 이상 더 있으면(group_size>=2) 카풀을 함께 추천한다.
   - service=null(슬롯 자체 없음)이면 2단계로.
2) fetch_513_arrival 호출.
   found=true면 evaluate_connection으로 판정. SAFE/TIGHT/GOOD/LONG_WAIT면 513 추천 후 종료.
   MISS/BUS_TOO_SOON/BUS_BEFORE_READY거나 버스 없으면 3단계.
3) recommend_taxi 호출 → 택시 추천. find_taxi_share로 카풀 가능하면 함께 안내.

[작성 규칙]
- 시간/요일/요금 계산은 절대 직접 하지 말 것. 도구 반환값만 근거로.
- 최종 추천 수단 1개 + 핵심 시각/수치 + 한 줄 이유. 2~4문장, 친근, 이모지 1~2개.
- 조건부 셔틀이면 'N*' 임계값을 언급. 도구가 주지 않은 숫자/시각 금지."""

# 예약 가능 모드: 셔틀 슬롯이 있으면 실제 예약을 수행
BOOKING_NOTE = """[예약 모드]
이번 요청은 학생이 '예약'을 눌러 시작됐다. 다음을 따른다:
- find_shuttle 결과 service가 'fixed' 또는 'conditional'이면 → make_reservation(name,
  direction, train_time, travel_date)을 호출해 실제로 예약한다. (조건부는 예약이 N* 카운트에
  쌓이므로 미달이어도 예약한다.) 예약 후 결과를 안내한다.
- service=null(슬롯 없음)이면 예약하지 말고 513/택시/카풀만 추천한다.
- 예약했다면 메시지에 '예약 완료'와 현재 예약 인원을 명시한다."""

RECOMMEND_ONLY_NOTE = """[추천 전용 모드]
이번 요청은 '추천만 보기'다. 절대 예약을 수행하지 말고 추천/안내만 한다."""


TOOLS_SCHEMA = [
    {'type': 'function', 'function': {
        'name': 'find_shuttle',
        'description': '1순위. 요일+KTX 시각에 배정된 셔틀편(고정/조건부) 조회.',
        'parameters': {'type': 'object', 'properties': {
            'direction': {'type': 'string', 'enum': ['to_station', 'to_campus']},
            'train_time': {'type': 'string'},
            'travel_date': {'type': 'string'},
            'reservations': {'type': 'integer'}}, 'required': ['direction', 'train_time']}}},
    {'type': 'function', 'function': {
        'name': 'fetch_513_arrival', 'description': '실시간 513 도착(BIS API).',
        'parameters': {'type': 'object', 'properties': {
            'direction': {'type': 'string', 'enum': ['to_station', 'to_campus']}},
            'required': ['direction']}}},
    {'type': 'function', 'function': {
        'name': 'evaluate_connection',
        'description': 'KTX와 513 도착 대조 연계 판정. 시간 계산은 반드시 이 도구로.',
        'parameters': {'type': 'object', 'properties': {
            'direction': {'type': 'string', 'enum': ['to_station', 'to_campus']},
            'bus_arrival_min': {'type': 'number'}, 'train_time': {'type': 'string'},
            'walk_to_stop_min': {'type': 'integer'}},
            'required': ['direction', 'bus_arrival_min', 'train_time']}}},
    {'type': 'function', 'function': {
        'name': 'recommend_taxi', 'description': '3순위 택시.',
        'parameters': {'type': 'object', 'properties': {
            'direction': {'type': 'string', 'enum': ['to_station', 'to_campus']}},
            'required': ['direction']}}},
    {'type': 'function', 'function': {
        'name': 'find_taxi_share',
        'description': '같은 슬롯(방향·KTX·날짜) 예약자 기반 택시 셰어 후보 집계.',
        'parameters': {'type': 'object', 'properties': {
            'direction': {'type': 'string', 'enum': ['to_station', 'to_campus']},
            'train_time': {'type': 'string'}, 'travel_date': {'type': 'string'}},
            'required': ['direction', 'train_time', 'travel_date']}}},
]


# 예약 모드에서만 켜지는 행동 도구
BOOKING_TOOLS_SCHEMA = [
    {'type': 'function', 'function': {
        'name': 'make_reservation',
        'description': '실제 예약 기록. 셔틀 슬롯(fixed/conditional)이 있을 때만 호출.',
        'parameters': {'type': 'object', 'properties': {
            'name': {'type': 'string'},
            'direction': {'type': 'string', 'enum': ['to_station', 'to_campus']},
            'train_time': {'type': 'string'}, 'travel_date': {'type': 'string'}},
            'required': ['name', 'direction', 'train_time', 'travel_date']}}},
    {'type': 'function', 'function': {
        'name': 'cancel_reservation',
        'description': '같은 슬롯에서 해당 학생의 예약을 취소.',
        'parameters': {'type': 'object', 'properties': {
            'name': {'type': 'string'},
            'direction': {'type': 'string', 'enum': ['to_station', 'to_campus']},
            'train_time': {'type': 'string'}, 'travel_date': {'type': 'string'}},
            'required': ['name', 'direction', 'train_time', 'travel_date']}}},
]
