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
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from shuttle_system.storage import make_store
from shuttle_system.core.optimization import POLICY_FARE, breakeven_N
from shuttle_system.core.schedule import all_slots, WEEKDAY_KR
from shuttle_system.core.schedule_overrides import refresh_active_schedule
from shuttle_system.core.booking_window import (
    is_within_booking_window, next_monday_midnight,
)
from shuttle_system import timetable
from shuttle_system.recommend import recommend, slot_status, resolve_ktx, weekday_of
from shuttle_system.agents.data_agent import fetch_513_arrival
from shuttle_system.agents.alert_agent import run_notification_check
from shuttle_system.agents.carpool_agent import form_carpool_groups, group_message
# 카카오톡 알림은 제거됨 — 이메일(Resend/Gmail SMTP) 단일 채널로 운영
from shuttle_system.emailer import notify_slot as email_notify_slot, send_confirmation

app = FastAPI(title='UNIST Shuttle API')
store = make_store()
FARE = POLICY_FARE
WEB = Path(__file__).parent / 'web'
app.mount('/static', StaticFiles(directory=WEB / 'static'), name='static')


@app.middleware('http')
async def _refresh_schedule_overrides(request, call_next):
    """매 요청 시 활성 시간표를 최신화 (5분 캐시라 시트 호출은 5분에 1회).

    Promotion Agent가 새 baseline을 적재하면 다음 요청부터 (또는 캐시 만료 후)
    학생 앱에 자동 반영된다.
    """
    try:
        refresh_active_schedule(store)
    except Exception:
        pass  # 시트 일시 오류로 전체 요청이 깨지지 않도록 보호
    return await call_next(request)

# 결정론 멀티 에이전트 흐름 (LLM 미사용). LLM은 운영 리포트 서술 등 안전한 영역에만.
# Orchestrator(LLM planner)는 메시지 왜곡 위험으로 메인 흐름에서 제외했다.
# 코드가 trace를 명시적으로 만들어 화면에 표시한다.


def _today():
    return datetime.now().strftime('%Y-%m-%d')


# ── 정적 페이지 ──────────────────────────────────────
@app.get('/')
def index():
    return FileResponse(WEB / 'index.html')


@app.get('/api/_mtime')
def api_mtime():
    """개발용: web/index.html + api.py 최신 수정시각. 브라우저가 폴링해 자동 새로고침."""
    files = [WEB / 'index.html', Path(__file__)]
    return {'mtime': max(f.stat().st_mtime for f in files if f.exists())}


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
    return {'ok': True, 'train_time': ktx, 'info': info, 'travel_date': date, **st}


# ── 예약 ─────────────────────────────────────────────
class ReserveReq(StatusReq):
    name: str = '학생'
    email: str = ''


@app.post('/api/reserve')
def api_reserve(req: ReserveReq):
    date = (req.travel_date or '').strip() or _today()
    # 0) 예약 윈도우 검사 — 다음 월요일 00시 이후는 거부
    #    (시간표 갱신 시점이라 예약을 받아두면 변경 영향에 노출됨)
    if not is_within_booking_window(date):
        nm = next_monday_midnight()
        return JSONResponse(
            {'ok': False, 'info': (
                f'예약 가능 기간은 오늘부터 {nm} 직전(다음 월요일 00시 전)까지입니다. '
                f'다음 주 셔틀은 {nm}부터 예약하실 수 있습니다.')},
            status_code=400)
    # 1) 추천/예약 에이전트 — 결정론
    ktx, info = resolve_ktx(store, req.direction, req.mode,
                            _opt_time(req.train_time), req.desire_time, date, FARE)
    if ktx is None:
        return JSONResponse({'ok': False, 'info': info}, status_code=400)
    rec = recommend(store, req.name, req.direction, ktx, date, FARE, email=req.email)
    trace = ['추천 에이전트']
    # 2) 즉시 메일 — 모든 예약자에게 발송 (고정/조건부 모두)
    #    · 고정 셔틀 또는 이미 N* 넘은 조건부 → 확정 메일
    #    · 조건부 N* 미달 → 잠정 예약 메일 (마감 시점에 다시 안내)
    n_star = breakeven_N(FARE)
    svc = rec.get('service')
    count_after = rec.get('reservations') or 0
    is_confirmed = (svc == 'fixed') or (svc == 'conditional' and count_after >= n_star)
    if rec.get('booked') and req.email:
        send_confirmation(req.email, req.name, req.direction,
                          rec.get('shuttle_time') or ktx, date, svc,
                          tentative=not is_confirmed,
                          reservations=count_after, required=n_star)
        trace.append('이메일 발송')
    # 3) 알림 에이전트 — N* 첫 충족 시 탑승자 전원에게 단체 이메일 발송 (카톡 제거, 이메일 only)
    before = len(store.all_notifications())
    run_notification_check(store, fare=FARE, emailer_fn=email_notify_slot)
    new_msgs = [n.get('message', '') for n in store.all_notifications()[before:]]
    if new_msgs:
        trace.append('알림 에이전트')
    return {'ok': True, 'train_time': ktx, 'info': info, 'travel_date': date,
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
        ktx = str(r.get('train_time'))
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
            'train_time': ktx, 'travel_date': date, 'shuttle_time': slot.get('shuttle_time'),
            'service': slot['service'], 'phase': phase, 'status': status,
            'cancellable': phase != 'closed'})
    return {'reservations': out}


class CancelReq(BaseModel):
    name: str
    direction: str
    train_time: str
    travel_date: str


@app.post('/api/cancel')
def api_cancel(req: CancelReq):
    from shuttle_system.core.schedule import slot_phase, find_shuttle_slot
    from datetime import datetime
    try:
        wd = datetime.strptime(req.travel_date, '%Y-%m-%d').weekday()
    except ValueError:
        return JSONResponse({'ok': False, 'info': '날짜 오류'}, status_code=400)
    slot = find_shuttle_slot(req.direction, req.train_time, wd, fare=FARE)
    if slot_phase(slot.get('shuttle_time') or req.train_time, req.travel_date) == 'closed':
        return JSONResponse({'ok': False, 'info': '마감 후엔 취소할 수 없습니다.'},
                            status_code=400)
    ok = store.remove_one(req.name, req.direction, req.train_time, req.travel_date)
    if not ok:
        return JSONResponse({'ok': False, 'info': '해당 예약을 찾지 못했습니다.'},
                            status_code=404)
    return {'ok': True, 'message': '예약이 취소되었습니다.'}


@app.post('/api/carpool/signup')
def api_carpool_signup(req: CarpoolReq):
    date = (req.travel_date or '').strip() or _today()
    if not is_within_booking_window(date):
        nm = next_monday_midnight()
        return JSONResponse(
            {'ok': False, 'info': (
                f'카풀 신청도 예약 윈도우와 동일하게 {nm} 직전까지 가능합니다.')},
            status_code=400)
    ktx, info = resolve_ktx(store, req.direction, req.mode,
                            _opt_time(req.train_time), req.desire_time, date, FARE)
    if ktx is None:
        return JSONResponse({'ok': False, 'info': info}, status_code=400)
    store.add_carpool_request(req.name, req.direction, ktx, date)
    groups = form_carpool_groups(store)
    mine = [g for g in groups if req.name in g['members'] and g['direction'] == req.direction
            and g['train_time'] == ktx and g['travel_date'] == date]
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
    mine = {(str(r.get('direction')), str(r.get('train_time')), str(r.get('travel_date')))
            for r in store.all_records() if str(r.get('name')) == name.strip()}
    notes = [n for n in store.all_notifications()
             if (str(n.get('direction')), str(n.get('train_time')),
                 str(n.get('travel_date'))) in mine]
    return {'notifications': [n.get('message', '') for n in notes[-12:][::-1]]}


@app.post('/api/notify/check')
def api_notify_check():
    new = run_notification_check(store, fare=FARE, emailer_fn=email_notify_slot)
    return {'ok': True, 'new': [n['message'] for n in new]}


def _mask_name(nm):
    """한글 이름 익명화: 2자→홍*, 3자→홍*동, 4자+→홍**동 형식."""
    s = (nm or '').strip()
    if not s:
        return '익명'
    if len(s) == 1:
        return s + '*'
    if len(s) == 2:
        return s[0] + '*'
    return s[0] + '*' * (len(s) - 2) + s[-1]


# ── 전체 예약 현황 (공개·익명화) ──────────────────────
@app.get('/api/reservations')
def api_reservations(date: str = None):
    """선택 날짜의 모든 예약을 슬롯별로 그룹화해 익명 명단으로 반환."""
    target = (date or '').strip() or _today()
    groups = {}
    for r in store.all_records():
        if str(r.get('travel_date')) != target:
            continue
        key = (str(r.get('direction')), str(r.get('train_time')))
        groups.setdefault(key, []).append(_mask_name(r.get('name')))
    out = []
    for (direction, t), names in groups.items():
        out.append({
            'direction': direction,
            'dir_kr': '울산역행' if direction == 'to_station' else '캠퍼스행',
            'shuttle_time': t,
            'count': len(names),
            'names': names,
        })
    out.sort(key=lambda x: (x['shuttle_time'], 0 if x['direction'] == 'to_station' else 1))
    return {'ok': True, 'date': target, 'slots': out, 'total': sum(len(g['names']) for g in out)}


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




# ── 셔틀 운행 계획 (해당 요일, 모든 그리드 슬롯 + 예약 반영 실시간) ───────
@app.get('/api/plan')
def api_plan(date: str = None):
    date = (date or '').strip() or _today()
    try:
        wd = weekday_of(date)
    except ValueError:
        return JSONResponse({'ok': False, 'info': '날짜 형식 오류'}, status_code=400)
    from shuttle_system.core.schedule import (
        daily_dispatch, grid_options, SHUTTLE_FIXED, slot_phase, VEHICLE_CAPACITY,
    )
    disp = daily_dispatch(store, date, FARE)
    n_star = disp['n_star']
    cap = VEHICLE_CAPACITY

    def _dir_kr(d):
        return '울산역행' if d == 'to_station' else '캠퍼스행'

    # 1) 확정·밀림 인덱스
    confirmed_map = {(c['direction'], c['shuttle_time']): c for c in disp['confirmed']}
    bumped_map = {(c['direction'], c['shuttle_time']): c for c in disp['bumped']}

    # 2) 해당 요일 고정 슬롯 인덱스 (이름 표시용)
    fixed_map = {}
    for direction, entries in SHUTTLE_FIXED.items():
        for e in entries:
            if e['wd'] == wd:
                fixed_map[(direction, e['shuttle'])] = e['slot']

    # 3) 예약 수 카운트
    counts = {}
    for r in store.all_records():
        if str(r.get('travel_date')) == date:
            k = (str(r.get('direction')), str(r.get('train_time')))
            counts[k] = counts.get(k, 0) + 1

    # 4) 모든 그리드 슬롯을 양방향으로 나열
    shuttles = []
    for direction in ('to_station', 'to_campus'):
        for t in grid_options(direction):
            key = (direction, t)
            count = counts.get(key, 0)
            is_fixed = key in fixed_map
            slot_label = fixed_map.get(key, f'{t} 그리드')
            if key in confirmed_map:
                if is_fixed:
                    status, run, svc = f'🟢 운행 확정 (고정 · {count}/{cap}명)', True, 'fixed'
                else:
                    status, run, svc = f'🟢 운행 확정 ({count}/{cap}명)', True, 'conditional'
            elif key in bumped_map:
                status, run, svc = f"🔴 미운행 ({bumped_map[key]['reason']})", False, 'conditional'
            elif is_fixed:
                status, run, svc = f'🟢 운행 확정 (고정 · {count}/{cap}명)', True, 'fixed'
            elif count >= n_star:
                status, run, svc = f'🟢 운행 확정 ({count}/{cap}명)', True, 'conditional'
            elif slot_phase(t, date) == 'closed':
                status, run, svc = f'🔴 미운행 (예약 부족 · {count}/{cap}명)', False, 'conditional'
            elif count > 0:
                status, run, svc = f'🟡 모집 중 ({count}/{cap}명)', False, 'conditional'
            else:
                status, run, svc = f'⚪ 신청 없음 (0/{cap}명)', False, 'conditional'
            shuttles.append({
                'slot': slot_label, 'direction': direction, 'dir_kr': _dir_kr(direction),
                'shuttle_time': t, 'ktx': t, 'service': svc,
                'status': status, 'run': run, 'count': count,
                'is_fixed': is_fixed})
    # 시각순(같은 시각이면 to_station 먼저)
    shuttles.sort(key=lambda s: (s['shuttle_time'], 0 if s['direction'] == 'to_station' else 1))
    return {'ok': True, 'date': date, 'weekday': WEEKDAY_KR[wd] + '요일',
            'n_star': n_star, 'shuttles': shuttles}


def _opt_time(v):
    """드롭다운 옵션('13:56 (KTX)') 또는 'HH:MM' → 'HH:MM'."""
    if not v:
        return v
    return timetable.parse_time(v) if '(' in v else v.strip()
