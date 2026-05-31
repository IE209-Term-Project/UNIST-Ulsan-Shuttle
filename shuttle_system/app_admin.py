"""관리자용 Gradio 앱 — 운영 리포트(표 + 차트 + LLM 요약)."""
import gradio as gr

from shuttle_system.core.optimization import POLICY_FARE
from shuttle_system.agents.report_agent import (
    compute_operations_report, make_charts, narrate_report,
)


def build_admin_app(store, fare=POLICY_FARE, chart_dir='/content'):
    def generate():
        report = compute_operations_report(store, fare=fare)
        headers = ['구분', '방향', '슬롯', 'KTX', '예약', '임계', '운행', '순편익(원)']
        table = [[r['service'], r['direction'], r['slot'], r['ktx'],
                  r['reservations'], r['required'],
                  '운행' if r['dispatched'] else '미운행', r['net_benefit']]
                 for r in report['slots']]
        summary = (f"총 운행 {report['total_runs']}회 · 수송 {report['total_passengers']}명 · "
                   f"순편익 ₩{report['total_net_benefit']:,} · "
                   f"대기 절감 {report['total_wait_saved_hours']}시간 (N*={report['n_star']})")
        try:
            charts = make_charts(report, out_dir=chart_dir)
        except Exception as e:
            charts = []
            summary += f'\n(차트 생성 오류: {e})'
        try:
            narration = narrate_report(report)
        except Exception as e:
            narration = f'(LLM 요약 오류: {e})'
        chart1 = charts[0] if len(charts) > 0 else None
        chart2 = charts[1] if len(charts) > 1 else None
        return summary, {'headers': headers, 'data': table}, chart1, chart2, narration

    with gr.Blocks(title='UNIST 셔틀 운영 리포트 (관리자용)') as demo:
        gr.Markdown('## 🛠 UNIST 셔틀 운영 리포트\n예약 누적분을 OR 모델 기준으로 집계합니다.')
        gen_btn = gr.Button('📊 리포트 생성', variant='primary')
        summary_out = gr.Textbox(label='요약', lines=2)
        table_out = gr.Dataframe(label='슬롯별 운영 현황', interactive=False)
        with gr.Row():
            chart1_out = gr.Image(label='예약 vs N*')
            chart2_out = gr.Image(label='실현 순편익')
        narr_out = gr.Textbox(label='🧠 LLM 운영 브리핑', lines=6)
        gen_btn.click(generate, None,
                      [summary_out, table_out, chart1_out, chart2_out, narr_out])
    return demo
