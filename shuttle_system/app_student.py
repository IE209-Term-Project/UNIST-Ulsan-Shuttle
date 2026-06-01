"""학생용 Gradio 앱 — 시간표 기반 선택 + 예약 + 개인화 추천.

입력 모드 2종:
  A. 기차 연계 — 방면 선택 → KTX/SRT 시각 드롭다운
  B. 단순 이동 — 출발 희망 시각 입력 → 근방 셔틀 매칭
시각/시각 선택 시 그 슬롯의 현재 예약 인원을 표시한다.
"""
from datetime import datetime
import gradio as gr

from shuttle_system.core.optimization import breakeven_N, POLICY_FARE
from shuttle_system.core.schedule import find_shuttle_near
from shuttle_system.agents.notify_agent import NotifyAgent, StudentProfile
from shuttle_system.agents.alert_agent import run_notification_check, llm_compose
from shuttle_system.agents.carpool_agent import form_carpool_groups, group_message
from shuttle_system import timetable

DIRECTION_MAP = {
    '울산역 방향 (캠퍼스→역)': 'to_station',
    '캠퍼스 방향 (역→캠퍼스)': 'to_campus',
}
MODE_TRAIN = '기차 연계 (KTX/SRT 시각 선택)'
MODE_TIME = '단순 이동 (출발 희망 시각 입력)'
BOUND_BY_LABEL = {v: k for k, v in timetable.BOUND_LABEL.items()}


def _weekday(date_str):
    return datetime.strptime(date_str.strip(), '%Y-%m-%d').weekday()


def build_student_app(store, fare=POLICY_FARE):
    agent = NotifyAgent(store, fare=fare)
    n_star = breakeven_N(fare)

    def _norm_date(date):
        return (date or '').strip() or datetime.now().strftime('%Y-%m-%d')

    def _resolve_slot(mode, bound_label, train_opt, desire_time, direction, date):
        """입력 모드에 따라 예약 키가 될 ktx_time과 설명을 결정.

        returns (ktx_time or None, 설명문). ktx_time None이면 에러/안내.
        """
        date = _norm_date(date)
        if mode == MODE_TRAIN:
            if not train_opt:
                return None, '열차 시각을 선택하세요.'
            ktx = timetable.parse_time(train_opt)
            return ktx, f'선택 열차: {train_opt}'
        # MODE_TIME
        if not (desire_time and desire_time.strip()):
            return None, '출발 희망 시각(HH:MM)을 입력하세요.'
        try:
            wd = _weekday(date)
        except ValueError:
            return None, '날짜 형식 오류 (YYYY-MM-DD).'
        near = find_shuttle_near(direction, desire_time.strip(), wd, fare=fare)
        if near['found']:
            return near['ktx_time'], (f"가장 가까운 셔틀 {near['shuttle_time']} "
                                      f"({near['diff_min']}분 차, {near['slot']})")
        return desire_time.strip(), '근방 30분 내 셔틀 없음 → 513/택시/카풀 검토'

    def _status(direction_label, ktx, date):
        direction = DIRECTION_MAP[direction_label]
        date = _norm_date(date)
        n = store.count(direction, ktx, date)
        names = store.names(direction, ktx, date)
        flag = '✅ 배차 충족' if n >= n_star else f'{max(0, n_star - n)}명 더 필요'
        return (f'📋 {date} · {ktx} · {direction_label}\n예약 {n}/{n_star}명 ({flag})\n'
                f'예약자: {", ".join(names) or "없음"}')

    # ── 드롭다운 동적 갱신 / 모드 토글 ───────────────────
    def on_bound_change(bound_label):
        opts = timetable.train_options(BOUND_BY_LABEL[bound_label])
        return gr.update(choices=opts, value=(opts[0] if opts else None))

    def on_mode_change(mode):
        is_train = (mode == MODE_TRAIN)
        return (gr.update(visible=is_train), gr.update(visible=is_train),
                gr.update(visible=not is_train))

    def on_check(direction_label, mode, bound_label, train_opt, desire_time, date):
        ktx, info = _resolve_slot(mode, bound_label, train_opt, desire_time,
                                  DIRECTION_MAP[direction_label], date)
        if ktx is None:
            return f'⚠️ {info}'
        return f'{info}\n\n' + _status(direction_label, ktx, date)

    def _recommend(name, direction_label, ktx, date, allow_booking):
        direction = DIRECTION_MAP[direction_label]
        date = _norm_date(date)
        n = store.count(direction, ktx, date)
        profile = StudentProfile(name=(name or '학생').strip(), direction=direction,
                                 ktx_time=ktx, travel_date=date, current_reservations=n)
        try:
            return agent.generate(profile, allow_booking=allow_booking)
        except Exception as e:
            return f'❌ 처리 중 오류: {e}'

    # ── 알림 피드 ───────────────────────────────────────
    def render_feed():
        notes = store.all_notifications()
        if not notes:
            return '🔔 알림 없음'
        lines = [f"- {n.get('message', '')}" for n in notes[-8:][::-1]]
        return '### 🔔 실시간 알림\n' + '\n'.join(lines)

    def do_check():
        run_notification_check(store, fare=fare, composer=llm_compose)
        return render_feed()

    def do_delay():
        run_notification_check(store, fare=fare, simulate_delay=True, composer=llm_compose)
        return render_feed()

    def on_reserve(name, direction_label, mode, bound_label, train_opt, desire_time, date):
        # 예약은 에이전트가 make_reservation 도구로 직접 수행(셔틀 슬롯일 때만)
        ktx, info = _resolve_slot(mode, bound_label, train_opt, desire_time,
                                  DIRECTION_MAP[direction_label], date)
        if ktx is None:
            return f'⚠️ {info}', '예약 현황: -', render_feed()
        d = _norm_date(date)
        msg = _recommend(name, direction_label, ktx, d, allow_booking=True)
        # 예약 직후 능동 감지(이 예약이 N* 돌파/카풀 형성 트리거할 수 있음)
        run_notification_check(store, fare=fare, composer=llm_compose)
        return (info + '\n\n' + msg, _status(direction_label, ktx, d), render_feed())

    # ── 카풀 ─────────────────────────────────────────────
    def on_carpool_signup(name, direction_label, mode, bound_label, train_opt, desire_time, date):
        ktx, info = _resolve_slot(mode, bound_label, train_opt, desire_time,
                                  DIRECTION_MAP[direction_label], date)
        if ktx is None:
            return f'⚠️ {info}'
        direction = DIRECTION_MAP[direction_label]
        d = _norm_date(date)
        store.add_carpool_request((name or '학생').strip(), direction, ktx, d)
        groups = form_carpool_groups(store)
        mine = [g for g in groups if (name or '학생').strip() in g['members']
                and g['direction'] == direction and g['ktx_time'] == ktx
                and g['travel_date'] == d]
        if mine:
            return '🚕 카풀 신청 완료!\n\n' + group_message(mine[0])
        return '🚕 카풀 신청 완료! (그룹 편성 대기)'

    def on_carpool_finalize():
        groups = form_carpool_groups(store, finalize=True)
        if not groups:
            return '카풀 신청 없음'
        return '### 🚕 카풀 그룹 확정 결과\n' + '\n'.join(
            f'- {group_message(g)}' for g in groups)

    def on_recommend_only(name, direction_label, mode, bound_label, train_opt, desire_time, date):
        ktx, info = _resolve_slot(mode, bound_label, train_opt, desire_time,
                                  DIRECTION_MAP[direction_label], date)
        if ktx is None:
            return f'⚠️ {info}', '예약 현황: -'
        d = _norm_date(date)
        return (info + '\n\n' + _recommend(name, direction_label, ktx, d, allow_booking=False),
                _status(direction_label, ktx, d))

    default_bound = timetable.BOUND_LABEL['seoul_bound']
    init_opts = timetable.train_options('seoul_bound')

    with gr.Blocks(title='UNIST 셔틀 추천 (학생용)') as demo:
        gr.Markdown(f'## 🚌 UNIST ↔ 울산역 추천 + 예약\n'
                    f'셔틀 → 513 → 택시/카풀 우선순위. **조건부 셔틀은 예약 N\\*={n_star}명 이상**이면 배차. '
                    f'(시간표 {timetable.updated_date()} 기준)')
        with gr.Row():
            name_in = gr.Textbox(label='이름', placeholder='홍길동')
            dir_in = gr.Radio(list(DIRECTION_MAP), label='방향',
                              value=list(DIRECTION_MAP)[0])
        mode_in = gr.Radio([MODE_TRAIN, MODE_TIME], label='입력 방식', value=MODE_TRAIN)
        with gr.Row():
            bound_in = gr.Dropdown(list(timetable.BOUND_LABEL.values()), label='방면',
                                   value=default_bound, visible=True)
            train_in = gr.Dropdown(init_opts, label='열차 시각 (KTX/SRT)',
                                   value=(init_opts[0] if init_opts else None), visible=True)
            desire_in = gr.Textbox(label='출발 희망 시각 (HH:MM)', placeholder='13:30',
                                   visible=False)
        date_in = gr.Textbox(label='날짜 (YYYY-MM-DD)',
                             value=datetime.now().strftime('%Y-%m-%d'))
        with gr.Row():
            check_btn = gr.Button('🔍 이 시각 예약 현황')
            reserve_btn = gr.Button('✅ 예약하고 추천', variant='primary')
            rec_btn = gr.Button('🔎 추천만 보기')
        status_out = gr.Textbox(label='예약 현황', lines=4)
        rec_out = gr.Textbox(label='추천 결과', lines=5)

        gr.Markdown('---')
        with gr.Row():
            carpool_btn = gr.Button('🚕 카풀 신청')
            carpool_final_btn = gr.Button('🚕 카풀 지금 확정 (데모)')
        carpool_out = gr.Markdown('카풀 신청 시 같은 시각 인원으로 최대 4명 그룹이 편성됩니다.')

        gr.Markdown('---')
        with gr.Row():
            notif_check_btn = gr.Button('🔔 지금 알림 체크')
            delay_btn = gr.Button('⚠️ 지연 시뮬레이션 (데모)')
        notif_out = gr.Markdown('🔔 알림 없음')

        bound_in.change(on_bound_change, bound_in, train_in)
        mode_in.change(on_mode_change, mode_in, [bound_in, train_in, desire_in])
        common = [name_in, dir_in, mode_in, bound_in, train_in, desire_in, date_in]
        check_btn.click(on_check,
                        [dir_in, mode_in, bound_in, train_in, desire_in, date_in],
                        status_out)
        reserve_btn.click(on_reserve, common, [rec_out, status_out, notif_out])
        rec_btn.click(on_recommend_only, common, [rec_out, status_out])
        carpool_btn.click(on_carpool_signup, common, carpool_out)
        carpool_final_btn.click(on_carpool_finalize, None, carpool_out)
        notif_check_btn.click(do_check, None, notif_out)
        delay_btn.click(do_delay, None, notif_out)

        # 능동 갱신: 15초마다 알림 피드 새로고침
        timer = gr.Timer(15)
        timer.tick(render_feed, None, notif_out)
    return demo
