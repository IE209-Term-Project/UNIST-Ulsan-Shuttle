"""Hugging Face Spaces 진입점.

학생용 앱과 관리자용 앱을 한 페이지의 두 탭으로 묶어 단일 Gradio 앱으로 띄운다.
저장소는 환경에 따라 자동 선택(make_store): HF에선 서비스 계정 Google Sheets.

필요한 Space Secrets:
  - OPENAI_API_KEY
  - ULSAN_BIS_API_KEY
  - GOOGLE_SERVICE_ACCOUNT_JSON   (서비스 계정 키 JSON 전체)
  - RESERVATION_SHEET_ID          (대상 시트 ID, 권장)
"""
import tempfile

import gradio as gr

from shuttle_system.storage import make_store
from shuttle_system.app_student import build_student_app
from shuttle_system.app_admin import build_admin_app

store = make_store()

student_app = build_student_app(store)
admin_app = build_admin_app(store, chart_dir=tempfile.gettempdir())

demo = gr.TabbedInterface(
    [student_app, admin_app],
    ['🎓 학생용 (예약·추천)', '🛠 관리자용 (운영 리포트)'],
    title='UNIST ↔ 울산역 수요대응형 셔틀 에이전트',
)

if __name__ == '__main__':
    demo.launch()
