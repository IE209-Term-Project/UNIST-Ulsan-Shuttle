"""FastAPI 백엔드 — 커스텀 예약 페이지(web/index.html)를 위한 API.

결정론적 추천(LLM 없음). 기존 core/agents/storage 재사용.
정적 페이지(/)와 API(/api/*)를 한 앱에서 제공.

실행: uvicorn api:app --host 0.0.0.0 --port 8000
"""
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from shuttle_system.storage import make_store
from shuttle_system.core.optimization import POLICY_FARE, breakeven_N
from shuttle_system.core.schedule import all_slots, WEEKDAY_KR
from shuttle_system import timetable
from shuttle_system.recommend import recommend, slot_status, resolve_ktx, weekday_of
from shuttle_system.agents.data_agent import fetch_513_arrival
from shuttle_system.agents.alert_agent import run_notification_check
from shuttle_system.agents.carpool_agent import form_carpool_groups, group_message
from shuttle_system.kakao import send_to_me as kakao_send

app = FastAPI(title='UNIST Shuttle API')
store = make_store()
FARE = POLICY_FARE
WEB = Path(__file__).parent / 'web'

# Orchestrator(LLM planner) — 키 없으면 None → 결정론 경로로 폴백
try:
    from shuttle_system.agents.orchestrator import Orchestrator
    orchestrator = Orchestrator(store, fare=FARE, pusher=kakao_send)
except Exception:
    orchestrator = None

# 에이전트 trace를 사람이 읽을 라벨로
TRACE_LABEL = {
    'recommend_transport': '추천 에이전트',
    'detect_and_notify': '알림 에이전트',
    'form_carpool': '카풀 에이전트',
    'fallback:recommend': '추천 에이전트(결정론)',
    'fallback:detect_and_notify': '알림 에이전트(결정론)',
}


def _today():
    return datetime.now().strftime('%Y-%m-%d')


# ── 정적 페이지 ──────────────────────────────────────
@app.get('/')
def index():
    return FileResponse(WEB / 'index.html')


# ── 시간표 옵션 ──────────────────────────────────────
@app.get('/api/timetable')
def api_timetable():
    return {b: {'label': timetable.BOUND_LABEL[b],
                'options': timetable.train_options(b)} for b in timetable.bounds()}


# ── 현황 조회 ────────────────────────────────────────
class StatusReq(BaseModel):
    direction: str
    mode: str = 'train'
    train_time: Optional[str] = None
    desire_time: Optional[str] = None
    travel_date: Optional[str] = None


@app.post('/api/status')
def api_status(req: StatusReq):
    date = (req.travel_date or '').strip() or _today()
    ktx, info = resolve_ktx(store, req.direction, req.mode,
                            _opt_time(req.train_time), req.desire_time, date, FARE)
    if ktx is None:
        return JSONResponse({'ok': False, 'info': info}, status_code=400)
    st = slot_status(store, req.direction, ktx, date, FARE)
    return {'ok': True, 'ktx_time': ktx, 'info': info, 'travel_date': date, **st}


# ── 예약 ─────────────────────────────────────────────
class ReserveReq(StatusReq):
    name: str = '학생'


@app.post('/api/reserve')
def api_reserve(req: ReserveReq):
    date = (req.travel_date or '').strip() or _today()
    if orchestrator is not None:
        # Orchestrator(LLM planner)가 어떤 하위 에이전트를 부를지 판단 → 예약 처리
        before = len(store.all_notifications())
        res = orchestrator.handle(req.name, req.direction, req.mode,
                                  _opt_time(req.train_time), req.desire_time, date, intent='reserve')
        if not res.get('ok'):
            return JSONResponse({'ok': False, 'info': res.get('info', '입력 확인')}, status_code=400)
        ktx, date = res['ktx_time'], res['travel_date']
        run_notification_check(store, fare=FARE, pusher=kakao_send)   # 알림 보장(중복 차단)
        new_msgs = [n.get('message', '') for n in store.all_notifications()[before:]]
        st = slot_status(store, req.direction, ktx, date, FARE)
        trace = [TRACE_LABEL.get(t, t) for t in res.get('trace', [])]
        return {'ok': True, 'ktx_time': ktx, 'travel_date': date, 'info': res.get('info', ''),
                'message': res['message'], 'trace': trace, 'new_alerts': new_msgs, **st}
    # 폴백: orchestrator 불가 → 결정론
    ktx, info = resolve_ktx(store, req.direction, req.mode,
                            _opt_time(req.train_time), req.desire_time, date, FARE)
    if ktx is None:
        return JSONResponse({'ok': False, 'info': info}, status_code=400)
    rec = recommend(store, req.name, req.direction, ktx, date, FARE)
    new = run_notification_check(store, fare=FARE, pusher=kakao_send)
    return {'ok': True, 'ktx_time': ktx, 'info': info, 'travel_date': date,
            'trace': ['추천 에이전트(결정론)', '알림 에이전트(결정론)'],
            'new_alerts': [n['message'] for n in new], **rec}


# ── 카풀 ─────────────────────────────────────────────
class CarpoolReq(ReserveReq):
    pass


@app.post('/api/carpool/signup')
def api_carpool_signup(req: CarpoolReq):
    date = (req.travel_date or '').strip() or _today()
    ktx, info = resolve_ktx(store, req.direction, req.mode,
                            _opt_time(req.train_time), req.desire_time, date, FARE)
    if ktx is None:
        return JSONResponse({'ok': False, 'info': info}, status_code=400)
    store.add_carpool_request(req.name, req.direction, ktx, date)
    groups = form_carpool_groups(store)
    mine = [g for g in groups if req.name in g['members'] and g['direction'] == req.direction
            and g['ktx_time'] == ktx and g['travel_date'] == date]
    return {'ok': True, 'message': group_message(mine[0]) if mine else '카풀 신청 완료 (편성 대기)'}


@app.post('/api/carpool/finalize')
def api_carpool_finalize():
    groups = form_carpool_groups(store, finalize=True)
    return {'ok': True, 'groups': [group_message(g) for g in groups]}


# ── 알림 ─────────────────────────────────────────────
@app.get('/api/notifications')
def api_notifications():
    notes = store.all_notifications()
    return {'notifications': [n.get('message', '') for n in notes[-12:][::-1]]}


@app.post('/api/notify/check')
def api_notify_check():
    new = run_notification_check(store, fare=FARE, pusher=kakao_send)
    return {'ok': True, 'new': [n['message'] for n in new]}


@app.post('/api/notify/delay')
def api_notify_delay():
    new = run_notification_check(store, fare=FARE, simulate_delay=True, pusher=kakao_send)
    return {'ok': True, 'new': [n['message'] for n in new]}


# ── 실시간 513 (BIS) ────────────────────────────────
@app.get('/api/bis')
def api_bis():
    """513 실시간 도착: 울산과학기술원 정류장 / 울산역 정류장."""
    def safe(direction):
        try:
            return fetch_513_arrival(direction)
        except Exception as e:
            return {'found': False, 'note': f'조회 실패: {e}'}
    return {'unist': safe('to_station'), 'ulsan': safe('to_campus')}


# ── 셔틀 운행 계획 (해당 요일, 예약 반영 실시간) ───────
@app.get('/api/plan')
def api_plan(date: str = None):
    date = (date or '').strip() or _today()
    try:
        wd = weekday_of(date)
    except ValueError:
        return JSONResponse({'ok': False, 'info': '날짜 형식 오류'}, status_code=400)
    from shuttle_system.core.schedule import SHUTTLE_FIXED, shuttle_time_for
    n_star = breakeven_N(FARE)
    shuttles = []
    seen = set()
    # 1) 고정 피크 (해당 요일, 항상 운행)
    for direction, entries in SHUTTLE_FIXED.items():
        for e in entries:
            if e['wd'] != wd:
                continue
            count = store.count(direction, e['ktx'], date)
            seen.add((direction, e['ktx']))
            shuttles.append({
                'slot': e['slot'], 'direction': direction,
                'dir_kr': '울산역행' if direction == 'to_station' else '캠퍼스행',
                'shuttle_time': e['shuttle'], 'ktx': e['ktx'], 'service': 'fixed',
                'status': '운행 확정 (고정)', 'run': True, 'count': count})
    # 2) 조건부: 그 날짜에 예약이 있는 시각 (수요 모이는 중)
    groups = {}
    for r in store.all_records():
        if str(r.get('travel_date')) != date:
            continue
        groups[(str(r.get('direction')), str(r.get('ktx_time')))] = \
            groups.get((str(r.get('direction')), str(r.get('ktx_time'))), 0) + 1
    for (direction, ktx), count in groups.items():
        if (direction, ktx) in seen:
            continue
        run = count >= n_star
        shuttles.append({
            'slot': f'{ktx} 조건부', 'direction': direction,
            'dir_kr': '울산역행' if direction == 'to_station' else '캠퍼스행',
            'shuttle_time': shuttle_time_for(direction, ktx), 'ktx': ktx,
            'service': 'conditional',
            'status': (f'운행 확정 ({count}/{n_star}명)' if run else f'모집 중 ({count}/{n_star}명)'),
            'run': run, 'count': count})
    shuttles.sort(key=lambda s: s['shuttle_time'])
    return {'ok': True, 'date': date, 'weekday': WEEKDAY_KR[wd] + '요일',
            'n_star': n_star, 'shuttles': shuttles}


def _opt_time(v):
    """드롭다운 옵션('13:56 (KTX)') 또는 'HH:MM' → 'HH:MM'."""
    if not v:
        return v
    return timetable.parse_time(v) if '(' in v else v.strip()
