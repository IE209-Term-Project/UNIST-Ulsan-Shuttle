"""학생용 Gradio Space 진입점 (HF Spaces SDK=gradio, app_file=app.py).

관리자용은 별도 Streamlit Space(app_admin_streamlit.py)로 분리되어 있다.
저장소는 make_store()가 환경에 맞게 자동 선택(HF=서비스 계정 Google Sheets).

필요한 Space Secrets:
  - OPENAI_API_KEY
  - ULSAN_BIS_API_KEY
  - GOOGLE_SERVICE_ACCOUNT_JSON
  - RESERVATION_SHEET_ID
"""
from shuttle_system.storage import make_store
from shuttle_system.app_student import build_student_app

store = make_store()
demo = build_student_app(store)

if __name__ == '__main__':
    demo.launch()
