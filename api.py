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
    ktx, info = resolve_ktx(store, req.direction, req.mode,
                            _opt_time(req.train_time), req.desire_time, date, FARE)
    if ktx is None:
        return JSONResponse({'ok': False, 'info': info}, status_code=400)
    rec = recommend(store, req.name, req.direction, ktx, date, FARE)
    # 예약 직후 능동 감지 + 카톡 발송
    new = run_notification_check(store, fare=FARE, pusher=kakao_send)
    return {'ok': True, 'ktx_time': ktx, 'info': info, 'travel_date': date,
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
    n_star = breakeven_N(FARE)
    shuttles = []
    for slot in all_slots():
        if slot['wd'] != wd:
            continue
        count = store.count(slot['direction'], slot['ktx'], date)
        if slot['service'] == 'fixed':
            status, run = '운행 확정 (고정)', True
        elif count >= n_star:
            status, run = f'운행 확정 ({count}/{n_star}명)', True
        else:
            status, run = f'대기 중 ({count}/{n_star}명)', False
        shuttles.append({
            'slot': slot['slot'], 'direction': slot['direction'],
            'dir_kr': '울산역행' if slot['direction'] == 'to_station' else '캠퍼스행',
            'shuttle_time': slot['shuttle'], 'ktx': slot['ktx'],
            'service': slot['service'], 'status': status, 'run': run, 'count': count})
    shuttles.sort(key=lambda s: s['shuttle_time'])
    return {'ok': True, 'date': date, 'weekday': WEEKDAY_KR[wd] + '요일',
            'n_star': n_star, 'shuttles': shuttles}


def _opt_time(v):
    """드롭다운 옵션('13:56 (KTX)') 또는 'HH:MM' → 'HH:MM'."""
    if not v:
        return v
    return timetable.parse_time(v) if '(' in v else v.strip()
