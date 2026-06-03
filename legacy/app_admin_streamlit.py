"""관리자용 운영 리포트 — Streamlit 대시보드.

학생 앱(Gradio)과 같은 저장소를 공유한다. 로직(core/report_agent)은 그대로 재사용하고
UI만 Streamlit으로 구성한다.

실행:
  로컬:  streamlit run app_admin_streamlit.py
  HF:    SDK=streamlit Space에 올리고 app_file을 이 파일로 지정

필요한 Secrets: OPENAI_API_KEY, GOOGLE_SERVICE_ACCOUNT_JSON, RESERVATION_SHEET_ID
"""
import altair as alt
import pandas as pd
import streamlit as st

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shuttle_system.storage import make_store
from shuttle_system.core.optimization import breakeven_N
from shuttle_system.agents.report_agent import compute_operations_report, narrate_report

st.set_page_config(page_title='UNIST 셔틀 운영 리포트', page_icon='🛠', layout='wide')


@st.cache_resource
def get_store():
    return make_store()


st.title('🛠 UNIST ↔ 울산역 셔틀 운영 리포트')
st.caption('학생 예약(Google Sheets)을 OR 모델 기준으로 집계한 관리자용 대시보드')

# ── 사이드바 컨트롤 ─────────────────────────────────
fare = st.sidebar.select_slider('셔틀 요금 F (원)', options=[0, 1000, 2000, 3000], value=2000)
n_star = breakeven_N(fare)
st.sidebar.metric('손익분기 N*', f'{n_star}명', help='N* = ⌈C/b⌉ (운행 정당화 최소 인원)')
if st.sidebar.button('🔄 새로고침'):
    st.cache_data.clear()

store = get_store()


@st.cache_data(ttl=30)
def load_report(fare):
    return compute_operations_report(store, fare=fare)


report = load_report(fare)
df = pd.DataFrame(report['slots'])
df['label'] = df['slot'] + '·' + df['direction'].str[3:]

# ── KPI 카드 ────────────────────────────────────────
c1, c2, c3, c4 = st.columns(4)
c1.metric('운행 횟수', f"{report['total_runs']}회")
c2.metric('수송 인원', f"{report['total_passengers']}명")
c3.metric('실현 순편익', f"₩{report['total_net_benefit']:,}")
c4.metric('대기 절감', f"{report['total_wait_saved_hours']}시간")

st.divider()

# ── 차트 1: 예약 vs N* (기준선) ─────────────────────
left, right = st.columns(2)
with left:
    st.subheader(f'슬롯별 예약 인원 vs N*={n_star}')
    bars = alt.Chart(df).mark_bar().encode(
        x=alt.X('label:N', sort=None, title=None),
        y=alt.Y('reservations:Q', title='예약 인원'),
        color=alt.Color('dispatched:N', scale=alt.Scale(
            domain=[True, False], range=['#2e7d32', '#bdbdbd']), title='운행'),
        tooltip=['slot', 'direction', 'reservations', 'required', 'dispatched'])
    rule = alt.Chart(pd.DataFrame({'y': [n_star]})).mark_rule(
        color='red', strokeDash=[6, 4]).encode(y='y:Q')
    st.altair_chart((bars + rule).properties(width='container'))

# ── 차트 2: 실현 순편익 ─────────────────────────────
with right:
    st.subheader('슬롯별 실현 순편익 (b·N − C)')
    nb = alt.Chart(df).mark_bar().encode(
        x=alt.X('label:N', sort=None, title=None),
        y=alt.Y('net_benefit:Q', title='순편익(원)'),
        color=alt.condition(alt.datum.net_benefit >= 0,
                            alt.value('#1565c0'), alt.value('#c62828')),
        tooltip=['slot', 'direction', 'net_benefit'])
    st.altair_chart(nb.properties(width='container'))

# ── 상세 표 ─────────────────────────────────────────
st.subheader('슬롯별 상세')
st.dataframe(
    df[['service', 'direction', 'slot', 'ktx', 'reservations',
        'required', 'dispatched', 'net_benefit', 'survey_demand']],
    width='stretch', hide_index=True)

# ── LLM 운영 브리핑 ─────────────────────────────────
st.subheader('🧠 운영 브리핑 (LLM)')
if st.button('브리핑 생성'):
    with st.spinner('LLM이 집계 결과를 해석하는 중...'):
        try:
            st.write(narrate_report(report))
        except Exception as e:
            st.error(f'LLM 요약 오류: {e}')
else:
    st.caption('버튼을 누르면 위 집계 숫자를 바탕으로 LLM이 서술 요약을 생성합니다.')

st.caption(f"집계 시각: {report['generated_at']}")
