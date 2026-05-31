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


def taxi_share_logic(store, direction, ktx_time, travel_date, exclude_name=None):
    """같은 슬롯 예약자 기반 택시 셰어 후보 집계. 순수 로직(store 주입)."""
    names = [n for n in store.names(direction, ktx_time, travel_date)
             if n != exclude_name]
    n = len(names) + 1  # 본인 포함
    per_person = round(14000 / n) if n > 0 else 14000
    return {'companions': names, 'group_size': n,
            'est_total_krw': 14000, 'per_person_krw': per_person,
            'note': f'같은 {ktx_time} KTX 예약자 {len(names)}명 → {n}명 셰어 시 1인 약 {per_person}원'}


@dataclass
class StudentProfile:
    name: str
    direction: str
    ktx_time: str
    travel_date: str = None
    walk_to_stop_min: int = 5
    current_reservations: int = 0


class NotifyAgent:
    def __init__(self, store, fare=POLICY_FARE):
        self.store = store
        self.fare = fare
        self.client = OpenAI(api_key=get_secret('OPENAI_API_KEY'))
        self._tools = self._build_tools()

    def _build_tools(self):
        return {
            'find_shuttle': lambda direction, ktx_time, travel_date=None, reservations=0:
                json.dumps(find_shuttle_slot(direction, ktx_time,
                           _weekday_of(travel_date), reservations, self.fare),
                           ensure_ascii=False),
            'fetch_513_arrival': lambda direction:
                json.dumps(fetch_513_arrival(direction), ensure_ascii=False),
            'evaluate_connection': lambda direction, bus_arrival_min, ktx_time, walk_to_stop_min=5:
                json.dumps(evaluate_connection(direction, bus_arrival_min, ktx_time,
                           walk_to_stop_min), ensure_ascii=False, default=str),
            'recommend_taxi': lambda direction:
                json.dumps(recommend_taxi(direction), ensure_ascii=False),
            'find_taxi_share': lambda direction, ktx_time, travel_date:
                json.dumps(taxi_share_logic(self.store, direction, ktx_time, travel_date),
                           ensure_ascii=False),
        }

    def generate(self, profile, max_rounds=10):
        messages = [{'role': 'system', 'content': SYSTEM_PROMPT},
                    {'role': 'user', 'content': _profile_message(profile, self.fare)}]
        for _ in range(max_rounds):
            resp = self.client.chat.completions.create(
                model=MODEL, messages=messages, tools=TOOLS_SCHEMA)
            msg = resp.choices[0].message
            messages.append(msg)
            if not msg.tool_calls:
                return msg.content
            for tc in msg.tool_calls:
                args = json.loads(tc.function.arguments)
                result = self._tools[tc.function.name](**args)
                messages.append({'role': 'tool', 'tool_call_id': tc.id, 'content': result})
        return msg.content or '(도구 호출 한도 초과)'


def _profile_message(p, fare):
    dir_kr = ('울산과학기술원→울산역 (출발 KTX 탑승)' if p.direction == 'to_station'
              else '울산역→울산과학기술원 (KTX 하차 후 캠퍼스행)')
    return (f"학생: {p.name}\n방향: {dir_kr} (direction={p.direction})\n"
            f"KTX 시각: {p.ktx_time}\n여행 날짜: {p.travel_date or '오늘'}\n"
            f"정류장까지 도보: {p.walk_to_stop_min}분\n"
            f"조건부 셔틀 현재 예약: {p.current_reservations}명 (배차 임계 N*={breakeven_N(fare)})\n"
            f"위 학생에게 최적 교통수단을 우선순위대로 판단해 개인화 알림을 만들어줘.")


SYSTEM_PROMPT = """너는 UNIST ↔ 울산역 이동 학생에게 '최적 교통수단 1개'를 추천하는 에이전트다.
추천 우선순위(위에서부터 '이용 가능'한 첫 수단): 1순위 셔틀 → 2순위 513 → 3순위 택시.

[절차 — 한 번에 한 수단씩]
1) find_shuttle 호출. available=true면 셔틀 추천 후 종료.
   available=false이고 service='conditional'이면(예약<N*) find_taxi_share도 호출해 셰어 안내를 곁들인다.
2) available=false면 fetch_513_arrival 호출.
   found=true면 evaluate_connection으로 판정. SAFE/TIGHT/GOOD/LONG_WAIT면 513 추천 후 종료.
   MISS/BUS_TOO_SOON/BUS_BEFORE_READY거나 버스 없으면 3단계.
3) recommend_taxi 호출 → 택시 추천. find_taxi_share로 셰어 가능하면 함께 안내.

[작성 규칙]
- 시간/요일/요금 계산은 절대 직접 하지 말 것. 도구 반환값만 근거로.
- 최종 추천 수단 1개 + 핵심 시각/수치 + 한 줄 이유. 2~4문장, 친근, 이모지 1~2개.
- 조건부 셔틀이면 'N*' 임계값을 언급. 도구가 주지 않은 숫자/시각 금지."""


TOOLS_SCHEMA = [
    {'type': 'function', 'function': {
        'name': 'find_shuttle',
        'description': '1순위. 요일+KTX 시각에 배정된 셔틀편(고정/조건부) 조회.',
        'parameters': {'type': 'object', 'properties': {
            'direction': {'type': 'string', 'enum': ['to_station', 'to_campus']},
            'ktx_time': {'type': 'string'},
            'travel_date': {'type': 'string'},
            'reservations': {'type': 'integer'}}, 'required': ['direction', 'ktx_time']}}},
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
            'bus_arrival_min': {'type': 'number'}, 'ktx_time': {'type': 'string'},
            'walk_to_stop_min': {'type': 'integer'}},
            'required': ['direction', 'bus_arrival_min', 'ktx_time']}}},
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
            'ktx_time': {'type': 'string'}, 'travel_date': {'type': 'string'}},
            'required': ['direction', 'ktx_time', 'travel_date']}}},
]
