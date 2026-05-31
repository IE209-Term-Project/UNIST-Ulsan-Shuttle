"""학생용 Gradio 앱 — 예약 + 개인화 추천."""
from datetime import datetime
import gradio as gr

from shuttle_system.core.optimization import breakeven_N, POLICY_FARE
from shuttle_system.agents.notify_agent import NotifyAgent, StudentProfile

DIRECTION_MAP = {
    '울산역 방향 (캠퍼스→역, KTX 타러)': 'to_station',
    '캠퍼스 방향 (역→캠퍼스, KTX 하차 후)': 'to_campus',
}


def build_student_app(store, fare=POLICY_FARE):
    agent = NotifyAgent(store, fare=fare)
    n_star = breakeven_N(fare)

    def _norm(label, travel_date):
        direction = DIRECTION_MAP[label]
        travel_date = (travel_date or '').strip() or datetime.now().strftime('%Y-%m-%d')
        return direction, travel_date

    def _status(label, ktx, date):
        if not (ktx and ktx.strip()):
            return '예약 현황: KTX 시각을 입력하세요.'
        direction, date = _norm(label, date)
        ktx = ktx.strip()
        n = store.count(direction, ktx, date)
        names = store.names(direction, ktx, date)
        flag = '✅ 배차 충족' if n >= n_star else f'{max(0, n_star - n)}명 더 필요'
        return (f'📋 {date} · {ktx} · {label}\n예약 {n}/{n_star}명 ({flag})\n'
                f'예약자: {", ".join(names) or "없음"}')

    def _recommend(name, label, ktx, date):
        direction, date = _norm(label, date)
        ktx = ktx.strip()
        n = store.count(direction, ktx, date)
        profile = StudentProfile(name=(name or '학생').strip(), direction=direction,
                                 ktx_time=ktx, travel_date=date, current_reservations=n)
        try:
            return agent.generate(profile)
        except Exception as e:
            return f'❌ 처리 중 오류: {e}\n입력 형식 확인 (KTX HH:MM, 날짜 YYYY-MM-DD).'

    def on_reserve(name, label, ktx, date):
        if not (ktx and ktx.strip()):
            return '⚠️ KTX 시각(HH:MM)을 입력하세요.', '예약 현황: -'
        direction, d = _norm(label, date)
        store.add(name, direction, ktx.strip(), d)
        return _recommend(name, label, ktx, date), _status(label, ktx, date)

    def on_recommend_only(name, label, ktx, date):
        if not (ktx and ktx.strip()):
            return '⚠️ KTX 시각(HH:MM)을 입력하세요.', '예약 현황: -'
        return _recommend(name, label, ktx, date), _status(label, ktx, date)

    with gr.Blocks(title='UNIST 셔틀 추천 (학생용)') as demo:
        gr.Markdown(f'## 🚌 UNIST ↔ 울산역 추천 + 예약\n'
                    f'셔틀 → 513 → 택시 우선순위. **조건부 셔틀은 예약 N\\*={n_star}명 이상**이면 배차.')
        with gr.Row():
            name_in = gr.Textbox(label='이름', placeholder='홍길동')
            dir_in = gr.Radio(list(DIRECTION_MAP), label='방향',
                              value='울산역 방향 (캠퍼스→역, KTX 타러)')
        with gr.Row():
            ktx_in = gr.Textbox(label='KTX 시각 (HH:MM)', placeholder='13:58')
            date_in = gr.Textbox(label='날짜 (YYYY-MM-DD)',
                                 value=datetime.now().strftime('%Y-%m-%d'))
        with gr.Row():
            reserve_btn = gr.Button('✅ 예약하고 추천', variant='primary')
            rec_btn = gr.Button('🔎 추천만 보기')
        status_out = gr.Textbox(label='예약 현황', lines=3)
        rec_out = gr.Textbox(label='추천 결과', lines=5)

        full = [name_in, dir_in, ktx_in, date_in]
        reserve_btn.click(on_reserve, full, [rec_out, status_out])
        rec_btn.click(on_recommend_only, full, [rec_out, status_out])
    return demo
