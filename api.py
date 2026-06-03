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

# 결정론 멀티 에이전트 흐름 (LLM 미사용). LLM은 운영 리포트 서술 등 안전한 영역에만.
# Orchestrator(LLM planner)는 메시지 왜곡 위험으로 메인 흐름에서 제외했다.
# 코드가 trace를 명시적으로 만들어 화면에 표시한다.


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


# ── 셔틀 그리드 (방향별) ─────────────────────────────
@app.get('/api/grid')
def api_grid():
    from shuttle_system.core.schedule import grid_options, SHUTTLE_FIXED, WEEKDAY_KR
    fixed = {d: [{'wd': e['wd'], 'wd_kr': WEEKDAY_KR[e['wd']],
                  'shuttle': e['shuttle'], 'slot': e['slot']}
                 for e in entries]
             for d, entries in SHUTTLE_FIXED.items()}
    return {
        'to_station': {'grid': grid_options('to_station'), 'fixed': fixed['to_station']},
        'to_campus': {'grid': grid_options('to_campus'), 'fixed': fixed['to_campus']},
    }


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
    # 1) 추천/예약 에이전트 — 결정론
    ktx, info = resolve_ktx(store, req.direction, req.mode,
                            _opt_time(req.train_time), req.desire_time, date, FARE)
    if ktx is None:
        return JSONResponse({'ok': False, 'info': info}, status_code=400)
    rec = recommend(store, req.name, req.direction, ktx, date, FARE)
    trace = ['추천 에이전트']
    # 2) 알림 에이전트 — 능동 감지(예약 직후) + 카톡 발송
    before = len(store.all_notifications())
    run_notification_check(store, fare=FARE, pusher=kakao_send)
    new_msgs = [n.get('message', '') for n in store.all_notifications()[before:]]
    if new_msgs:
        trace.append('알림 에이전트')
    return {'ok': True, 'ktx_time': ktx, 'info': info, 'travel_date': date,
            'trace': trace, 'new_alerts': new_msgs, **rec}


# ── 카풀 ─────────────────────────────────────────────
class CarpoolReq(ReserveReq):
    pass


# ── 내 예약 / 취소 ──────────────────────────────────
@app.get('/api/my')
def api_my(name: str = None):
    """내 예약 목록 + 슬롯별 상태(잠정·확정·마감 여부)."""
    from shuttle_system.core.schedule import slot_phase, find_shuttle_slot
    if not (name and name.strip()):
        return {'reservations': []}
    nm = name.strip()
    out = []
    for r in store.all_records():
        if str(r.get('name')) != nm:
            continue
        direction = str(r.get('direction'))
        ktx = str(r.get('ktx_time'))
        date = str(r.get('travel_date'))
        try:
            from datetime import datetime
            wd = datetime.strptime(date, '%Y-%m-%d').weekday()
        except ValueError:
            continue
        n = store.count(direction, ktx, date)
        slot = find_shuttle_slot(direction, ktx, wd, reservations=n, fare=FARE)
        if slot['service'] is None:
            continue
        phase = slot_phase(slot.get('shuttle_time') or ktx, date)
        if slot['service'] == 'fixed':
            status = '확정 (고정)'
        elif phase == 'closed':
            status = '확정' if n >= breakeven_N(FARE) else '미운행'
        else:
            status = f'잠정 ({n}/{breakeven_N(FARE)}명)'
        out.append({
            'direction': direction, 'dir_kr': '울산역행' if direction == 'to_station' else '캠퍼스행',
            'ktx_time': ktx, 'travel_date': date, 'shuttle_time': slot.get('shuttle_time'),
            'service': slot['service'], 'phase': phase, 'status': status,
            'cancellable': phase != 'closed' and slot['service'] != 'fixed'})
    return {'reservations': out}


class CancelReq(BaseModel):
    name: str
    direction: str
    ktx_time: str
    travel_date: str


@app.post('/api/cancel')
def api_cancel(req: CancelReq):
    from shuttle_system.core.schedule import slot_phase, find_shuttle_slot
    from datetime import datetime
    try:
        wd = datetime.strptime(req.travel_date, '%Y-%m-%d').weekday()
    except ValueError:
        return JSONResponse({'ok': False, 'info': '날짜 오류'}, status_code=400)
    slot = find_shuttle_slot(req.direction, req.ktx_time, wd, fare=FARE)
    if slot.get('service') == 'fixed':
        return JSONResponse({'ok': False, 'info': '고정 셔틀은 취소 대상이 아닙니다.'},
                            status_code=400)
    if slot_phase(slot.get('shuttle_time') or req.ktx_time, req.travel_date) == 'closed':
        return JSONResponse({'ok': False, 'info': '마감 후엔 취소할 수 없습니다.'},
                            status_code=400)
    ok = store.remove_one(req.name, req.direction, req.ktx_time, req.travel_date)
    if not ok:
        return JSONResponse({'ok': False, 'info': '해당 예약을 찾지 못했습니다.'},
                            status_code=404)
    return {'ok': True, 'message': '예약이 취소되었습니다.'}


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
def api_notifications(name: str = None):
    """내 알림: 그 사람이 예약한 슬롯의 알림만. 이름 없으면 빈 목록."""
    if not (name and name.strip()):
        return {'notifications': []}
    mine = {(str(r.get('direction')), str(r.get('ktx_time')), str(r.get('travel_date')))
            for r in store.all_records() if str(r.get('name')) == name.strip()}
    notes = [n for n in store.all_notifications()
             if (str(n.get('direction')), str(n.get('ktx_time')),
                 str(n.get('travel_date'))) in mine]
    return {'notifications': [n.get('message', '') for n in notes[-12:][::-1]]}


@app.post('/api/notify/check')
def api_notify_check():
    new = run_notification_check(store, fare=FARE, pusher=kakao_send)
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
    from shuttle_system.core.schedule import daily_dispatch
    disp = daily_dispatch(store, date, FARE)
    n_star = disp['n_star']
    shuttles = []
    seen = set()

    def _dir_kr(d):
        return '울산역행' if d == 'to_station' else '캠퍼스행'

    # 확정된 운행 (고정 + 단일버스 가능 조건부)
    for c in disp['confirmed']:
        seen.add((c['direction'], c['ktx']))
        shuttles.append({
            'slot': c['slot'], 'direction': c['direction'], 'dir_kr': _dir_kr(c['direction']),
            'shuttle_time': c['shuttle_time'], 'ktx': c['ktx'], 'service': c['service'],
            'status': '운행 확정 (고정)' if c['service'] == 'fixed' else f"운행 확정 ({c['count']}/{n_star}명)",
            'run': True, 'count': c['count']})
    # 수요는 찼으나 버스 한 대 제약으로 밀린 운행
    for c in disp['bumped']:
        seen.add((c['direction'], c['ktx']))
        shuttles.append({
            'slot': c['slot'], 'direction': c['direction'], 'dir_kr': _dir_kr(c['direction']),
            'shuttle_time': c['shuttle_time'], 'ktx': c['ktx'], 'service': 'conditional',
            'status': f"미운행 ({c['reason']}) → 카풀/513", 'run': False, 'count': c['count']})
    # 아직 모집 중(N* 미달) 조건부
    counts = {}
    for r in store.all_records():
        if str(r.get('travel_date')) == date:
            k = (str(r.get('direction')), str(r.get('ktx_time')))
            counts[k] = counts.get(k, 0) + 1
    from shuttle_system.core.schedule import shuttle_time_for
    for (direction, ktx), count in counts.items():
        if (direction, ktx) in seen or count >= n_star:
            continue
        shuttles.append({
            'slot': f'{ktx} 조건부', 'direction': direction, 'dir_kr': _dir_kr(direction),
            'shuttle_time': shuttle_time_for(direction, ktx), 'ktx': ktx, 'service': 'conditional',
            'status': f'모집 중 ({count}/{n_star}명)', 'run': False, 'count': count})
    shuttles.sort(key=lambda s: s['shuttle_time'])
    return {'ok': True, 'date': date, 'weekday': WEEKDAY_KR[wd] + '요일',
            'n_star': n_star, 'shuttles': shuttles}


def _opt_time(v):
    """드롭다운 옵션('13:56 (KTX)') 또는 'HH:MM' → 'HH:MM'."""
    if not v:
        return v
    return timetable.parse_time(v) if '(' in v else v.strip()
