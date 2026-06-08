"""Orchestrator(Planner) Agent — 하위 에이전트를 '도구'로 노출하고 호출 순서를 LLM이 결정.

원칙(기존 유지): LLM은 OR 계산을 하지 않는다. 여기서도 planner는 '어떤 하위
에이전트를 어떤 순서로 부를지'만 판단하고, 실제 추천/감지/편성/집계는 하위
에이전트(그 안에서 다시 core 함수)가 수행한다.

기존 api.py의 하드코딩 흐름(예약→감지→카톡)을 LLM 판단으로 대체.
LLM 실패/한도 초과 시 결정론 폴백(_fallback)으로 떨어진다.
"""
import json
from datetime import datetime

from openai import OpenAI

from shuttle_system.config import get_secret
from shuttle_system.core.optimization import POLICY_FARE, breakeven_N
from shuttle_system.agents.alert_agent import run_notification_check
from shuttle_system.agents.carpool_agent import form_carpool_groups, group_message
from shuttle_system.recommend import recommend, resolve_ktx, weekday_of

MODEL = 'gpt-4o-mini'


class Orchestrator:
    def __init__(self, store, fare=POLICY_FARE, pusher=None):
        self.store = store
        self.fare = fare
        self.pusher = pusher          # 외부 발송(예: kakao). alert 도구가 사용.
        self.client = OpenAI(api_key=get_secret('OPENAI_API_KEY'))
        self.trace = []               # 어떤 하위 에이전트를 어떤 순서로 불렀는지 기록

    # ── 하위 에이전트 = 도구 ─────────────────────────────
    def _build_tools(self):
        return {
            # 추천 전담: 결정론 recommend (셔틀→513→택시/카풀 판단 + 예약). LLM 미사용 → 빠르고 일관적.
            'recommend_transport': lambda name, direction, train_time, travel_date, allow_booking=False:
                recommend(self.store, name, direction, train_time, travel_date, self.fare,
                          do_book=allow_booking)['message'],
            # 능동 감지: AlertAgent (dispatch/carpool/delay 이벤트 → 알림 생성·발송)
            'detect_and_notify': lambda: json.dumps(
                [n['message'] for n in run_notification_check(
                    self.store, fare=self.fare, pusher=self.pusher)], ensure_ascii=False),
            # 편성: CarpoolAgent (4명 그룹)
            'form_carpool': lambda finalize=False: json.dumps(
                [group_message(g) for g in form_carpool_groups(self.store, finalize=finalize)],
                ensure_ascii=False),
        }

    def handle(self, name, direction, mode, train_time=None, desire_time=None,
               travel_date=None, intent='reserve', max_rounds=8):
        """학생 요청 1건을 planner가 처리. intent: 'reserve' | 'status' | 'carpool'."""
        date = (travel_date or datetime.now().strftime('%Y-%m-%d')).strip()
        ktx, info = resolve_ktx(self.store, direction, mode, train_time, desire_time, date, self.fare)
        if ktx is None:
            return {'ok': False, 'info': info}

        tools = self._build_tools()
        self.trace = []
        messages = [
            {'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user', 'content': _request_message(
                name, direction, ktx, date, intent, breakeven_N(self.fare))},
        ]
        msg = None
        try:
            for _ in range(max_rounds):
                resp = self.client.chat.completions.create(
                    model=MODEL, messages=messages, tools=TOOLS_SCHEMA)
                msg = resp.choices[0].message
                messages.append(msg)
                if not msg.tool_calls:
                    return {'ok': True, 'train_time': ktx, 'travel_date': date,
                            'info': info, 'message': msg.content, 'trace': self.trace}
                for tc in msg.tool_calls:
                    args = json.loads(tc.function.arguments or '{}')
                    self.trace.append(tc.function.name)        # ← 대시보드가 보여줄 호출 순서
                    result = tools[tc.function.name](**args)
                    messages.append({'role': 'tool', 'tool_call_id': tc.id,
                                     'content': result if isinstance(result, str) else str(result)})
        except Exception:
            pass
        # 폴백: 기존 결정론 경로 그대로
        return self._fallback(name, direction, ktx, date, info, intent)

    def _fallback(self, name, direction, ktx, date, info, intent):
        rec = recommend(self.store, name, direction, ktx, date, self.fare,
                        do_book=(intent == 'reserve'))
        new = run_notification_check(self.store, fare=self.fare, pusher=self.pusher)
        return {'ok': True, 'train_time': ktx, 'travel_date': date, 'info': info,
                'message': rec['message'], 'new_alerts': [n['message'] for n in new],
                'trace': ['fallback:recommend', 'fallback:detect_and_notify'], **rec}


def _request_message(name, direction, ktx, date, intent, n_star):
    dir_kr = '울산역행' if direction == 'to_station' else '캠퍼스행'
    intent_kr = {'reserve': '예약', 'status': '현황 조회', 'carpool': '카풀 신청'}.get(intent, intent)
    return (f"학생 {name}이(가) '{intent_kr}'를 요청했다.\n"
            f"방향: {dir_kr} (direction={direction})\nKTX 시각: {ktx}\n날짜: {date}\n"
            f"조건부 배차 임계 N*={n_star}.\n"
            f"이 요청을 처리하기 위해 적절한 하위 에이전트를 순서대로 호출하라.")


SYSTEM_PROMPT = """너는 셔틀 시스템의 오케스트레이터다. 직접 계산하거나 메시지를 지어내지 말고,
아래 하위 에이전트를 '도구'로 호출해 요청을 처리하라.

- recommend_transport: 학생에게 최적 교통수단 추천(+예약 모드면 실제 예약). 예약/현황 요청의 1순위.
- detect_and_notify: 예약 상태 변화로 생긴 알림(운행 확정/카풀 가능/지연)을 감지·발송. 예약을 수행한 뒤 반드시 호출.
- form_carpool: 카풀 그룹 편성 결과 조회. 카풀 신청 요청이거나 셔틀 미운행 시 호출.

[판단 규칙]
- intent='예약'이면 recommend_transport를 allow_booking=true로 부르고, 그 다음 detect_and_notify를 부른다.
- intent='현황 조회'면 recommend_transport를 allow_booking=false로만 부른다.
- intent='카풀 신청'이면 form_carpool을 부른다.
마지막엔 학생에게 보여줄 한국어 요약 1~3문장을 반환하라(도구가 준 내용만 사용)."""


TOOLS_SCHEMA = [
    {'type': 'function', 'function': {
        'name': 'recommend_transport',
        'description': '추천 전담 하위 에이전트. allow_booking=true면 실제 예약까지 수행.',
        'parameters': {'type': 'object', 'properties': {
            'name': {'type': 'string'},
            'direction': {'type': 'string', 'enum': ['to_station', 'to_campus']},
            'train_time': {'type': 'string'}, 'travel_date': {'type': 'string'},
            'allow_booking': {'type': 'boolean'}},
            'required': ['name', 'direction', 'train_time', 'travel_date']}}},
    {'type': 'function', 'function': {
        'name': 'detect_and_notify',
        'description': '예약 상태 기반 알림을 감지하고 발송. 인자 없음.',
        'parameters': {'type': 'object', 'properties': {}}}},
    {'type': 'function', 'function': {
        'name': 'form_carpool',
        'description': '카풀 그룹 편성 조회. finalize=true면 즉시 확정.',
        'parameters': {'type': 'object', 'properties': {
            'finalize': {'type': 'boolean'}}}}},
]
