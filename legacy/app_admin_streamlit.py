"""관리자용 운영 리포트 — Streamlit 대시보드.

학생 앱(메인: FastAPI)과 같은 Google Sheet를 공유한다. 로직(core/report_agent)은 그대로
재사용하고 UI만 Streamlit으로 구성한다.

실행:
  로컬:  streamlit run legacy/app_admin_streamlit.py
  HF:    SDK=streamlit Space에 올리고 app_file을 이 파일로 지정

필요한 Secrets: OPENAI_API_KEY, GOOGLE_SERVICE_ACCOUNT_JSON, RESERVATION_SHEET_ID
"""
import altair as alt
import pandas as pd
import streamlit as st

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime, date as _date, timedelta

from shuttle_system.storage import make_store
from shuttle_system.core.optimization import breakeven_N
from shuttle_system.agents.report_agent import (
    compute_operations_report, narrate_report, build_weekly_xlsx,
    week_label_kr, weekly_filename_kr)

st.set_page_config(page_title='UNIST–울산역 수요반응형 셔틀 운영 리포트',
                   layout='wide')

WD_ORDER = ['월', '화', '수', '목', '금', '토', '일']
DIRS = [('to_station', '울산역행'), ('to_campus', '캠퍼스행')]


@st.cache_resource
def get_store():
    return make_store()


st.title('UNIST–울산역 수요반응형 셔틀 운영 리포트')
st.caption('학생 예약(Google Sheets)을 OR 모델 기준으로 집계한 관리자용 대시보드')

# ── 사이드바 컨트롤 ─────────────────────────────────
fare = st.sidebar.select_slider('셔틀 요금 F (원)', options=[0, 1000, 2000, 3000], value=2000)
n_star = breakeven_N(fare)
st.sidebar.metric('손익분기 N*', f'{n_star}명', help='N* = ⌈C/b⌉ (운행 정당화 최소 인원)')
if st.sidebar.button('🔄 새로고침'):
    st.cache_data.clear()

store = get_store()


# ── 사이드바: 📋 슬롯 등급 관리 (Promotion Agent) ──────
with st.sidebar.expander('📋 슬롯 등급 관리', expanded=False):
    st.caption(
        '단기 Promotion Agent — 직전 4주 데이터로 슬롯 승격/강등 권고. '
        '적용 시 **다음 월요일 00시부터** 학생 앱에 반영됩니다.')

    if st.button('🔍 평가 실행', key='pa_eval', use_container_width=True):
        from shuttle_system.agents.promotion_agent import evaluate_promotions
        st.session_state['pa_result'] = evaluate_promotions(store, fare=fare)

    res = st.session_state.get('pa_result')
    if res:
        if res.get('frozen'):
            st.warning(f"동결: {res.get('frozen_reason', '콜드 스타트')}")
        else:
            st.caption(f"윈도우: {res['window_start']} ~ {res['window_end']}")
            promos = res.get('promotions', [])
            demotes = res.get('demotions', [])

            if promos:
                st.markdown(f'**⬆ 승격 권고 {len(promos)}건**')
                for p in promos:
                    st.markdown(
                        f"- `{p['direction']}` {WD_ORDER[p['weekday']]} "
                        f"{p['time']}  · 평균 **{p['avg_resv']}명** · "
                        f"운행률 **{int(p['dispatch_rate']*100)}%**")
            if demotes:
                st.markdown(f'**⬇ 강등 권고 {len(demotes)}건**')
                for d in demotes:
                    st.markdown(
                        f"- `{d['direction']}` {WD_ORDER[d['weekday']]} "
                        f"{d['time']}  · 평균 **{d['avg_resv']}명** · "
                        f"운행률 **{int(d['dispatch_rate']*100)}%**")
            if not (promos or demotes):
                st.success('변경 권고 없음 — 현 시간표 유지.')

            if (promos or demotes) and st.button(
                    '✅ 다음 월요일부터 적용', key='pa_apply',
                    use_container_width=True):
                from shuttle_system.agents.promotion_agent import apply_promotions
                from shuttle_system.core.booking_window import next_monday_midnight
                from shuttle_system.emailer import notify_admin_promotion
                eff = next_monday_midnight()
                out = apply_promotions(store, res, effective_from=eff)
                admin_email = os.environ.get('ADMIN_EMAIL', '')
                mail = notify_admin_promotion(
                    admin_email, res, apply_result=out)
                mail_note = ('발송' if mail.get('sent')
                             else '미발송 — ADMIN_EMAIL 환경변수 설정 필요')
                st.success(
                    f"적용됨 — 효력 발생: **{eff}**  (이메일: {mail_note})")
                st.session_state['pa_result'] = None

    st.markdown('---')
    st.caption('↩ 롤백 — 직전 baseline으로 즉시 복귀')
    confirm = st.checkbox('정말 롤백', key='pa_rb_confirm')
    if confirm and st.button('실행', key='pa_rb_run',
                             use_container_width=True):
        from shuttle_system.agents.promotion_agent import rollback_to_previous
        from shuttle_system.core.booking_window import next_monday_midnight
        r = rollback_to_previous(store, effective_from=next_monday_midnight())
        if r['rolled_back']:
            st.success(f"복귀됨 — 직전({r['restored_from']}) → 활성")
        else:
            st.error(r.get('reason', '롤백 실패'))
        st.session_state['pa_rb_confirm'] = False


# ── 사이드바: 📑 주간 보고서 ───────────────────────────
# 매주 월요일 00시가 지나면 직전 주(Mon~Sun)가 "완료 주차"로 추가된다.
# 사이드바 좌상단 >> 토글을 열면 보고서 탭이 보인다.
def _completed_weeks(records):
    today = _date.today()
    dates = set()
    for r in records:
        try:
            dates.add(datetime.strptime(str(r.get('travel_date')).strip(),
                                        '%Y-%m-%d').date())
        except (ValueError, AttributeError):
            continue
    weeks = set()
    for d in dates:
        mon = d - timedelta(days=d.weekday())
        sun = mon + timedelta(days=6)
        if sun < today:                  # 일요일이 지난 주만 "완료"로 본다
            weeks.add((mon, sun))
    return sorted(weeks, reverse=True)


@st.cache_data(ttl=300)
def _weekly_xlsx_bytes(mon_iso, sun_iso, fare):
    return build_weekly_xlsx(store, mon_iso, sun_iso, fare=fare)


with st.sidebar:
    st.markdown('---')
    st.markdown('### 📑 보고서')
    st.caption('월별 폴더에 주차별 .xlsx 보고서가 정리됩니다. '
               '매주 월요일 00시가 지나면 직전 주가 자동으로 추가됩니다.')
    try:
        recs = store.all_records()
    except Exception as e:
        recs = []; st.caption(f'⚠ 시트 읽기 실패: {e}')
    weeks = _completed_weeks(recs)

    # 월별 그룹화 (월요일 기준 월)
    from collections import OrderedDict
    monthly = OrderedDict()
    for mon, sun in weeks:
        key = (mon.year, mon.month)
        monthly.setdefault(key, []).append((mon, sun))

    if not monthly:
        st.caption('_완료된 주차 없음 — 이번 주가 끝나야 첫 보고서가 생성됩니다._')
    else:
        for (year, month), wks in monthly.items():
            with st.expander(f'📁 {year}년 {month:02d}월  ({len(wks)}개 주차)',
                             expanded=(year, month) == next(iter(monthly))):
                for mon, sun in wks:
                    label = week_label_kr(mon)
                    period = f"{mon.strftime('%m/%d')}~{sun.strftime('%m/%d')}"
                    try:
                        data = _weekly_xlsx_bytes(mon.isoformat(),
                                                  sun.isoformat(), fare)
                        st.download_button(
                            f'📄 {label}  ({period})',
                            data=data,
                            file_name=weekly_filename_kr(mon),
                            mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                            key=f'rep_{mon.isoformat()}',
                            use_container_width=True)
                    except Exception as e:
                        st.caption(f'⚠ {label}: {e}')

    # ── 진행 중 주차 (별도 섹션) ──
    st.markdown('---')
    today_d = _date.today()
    cur_mon = today_d - timedelta(days=today_d.weekday())
    cur_sun = cur_mon + timedelta(days=6)
    cur_label = week_label_kr(cur_mon)
    st.caption(f'📅 진행 중: {cur_label} ({cur_mon.strftime("%m/%d")}~{cur_sun.strftime("%m/%d")}) — '
               '일요일 이후 위 폴더에 자동 추가됨')
    try:
        data = _weekly_xlsx_bytes(cur_mon.isoformat(),
                                  cur_sun.isoformat(), fare)
        st.download_button(
            f'📄 미리보기 다운로드',
            data=data,
            file_name=f'(미리보기) {weekly_filename_kr(cur_mon)}',
            mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            key='rep_preview',
            use_container_width=True)
    except Exception:
        pass


@st.cache_data(ttl=30)
def load_report(fare):
    return compute_operations_report(store, fare=fare)


report = load_report(fare)
df = pd.DataFrame(report['slots'])
if df.empty:
    raw = len(getattr(store.ws, 'get_all_values', lambda: [])()) if hasattr(store, 'ws') else None
    st.info('아직 집계할 예약이 없습니다.')
    st.caption(
        f"🛠 디버그 · 저장소={type(store).__name__} · 시트URL={getattr(store, 'url', '?')} · "
        f"sheet1 raw행수={raw} · SHEET_ID env앞8={(os.environ.get('RESERVATION_SHEET_ID', '?')[:8])} · "
        f"SA_JSON 길이={len(os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON', ''))}")
    st.stop()

# 슬롯 라벨 = "요일 + 시간"
df['slot_label'] = df['weekday'] + ' ' + df['train_time']

# ── KPI 카드 ────────────────────────────────────────
c1, c2, c3, c4 = st.columns(4)
c1.metric('운행 횟수', f"{report['total_runs']}회")
c2.metric('수송 인원', f"{report['total_passengers']}명")
c3.metric('실현 순편익', f"₩{report['total_net_benefit']:,}")
c4.metric('대기 절감', f"{report['total_wait_saved_hours']}시간")

st.divider()


# ── 누적 막대그래프 (방향별 × 인원/순편익) — 운행 슬롯만 ──
def stacked_chart(sub, y_field, y_title):
    return alt.Chart(sub).mark_bar().encode(
        x=alt.X('weekday:N', sort=WD_ORDER, title='요일',
                axis=alt.Axis(labelAngle=0)),
        y=alt.Y(f'{y_field}:Q', title=y_title, stack='zero'),
        color=alt.Color('slot_label:N', title='슬롯',
                        scale=alt.Scale(scheme='tableau20')),
        order=alt.Order('train_time:N'),
        tooltip=[alt.Tooltip('slot_label:N', title='슬롯'),
                 alt.Tooltip('service:N', title='유형'),
                 alt.Tooltip('travel_date:N', title='날짜'),
                 alt.Tooltip('reservations:Q', title='예약 인원'),
                 alt.Tooltip('net_benefit:Q', title='순편익(원)', format=',d')]
    ).properties(width='container', height=320)


dispatched_df = df[df['dispatched'] == True]
for dir_code, dir_kr in DIRS:
    st.subheader(f'📊 {dir_kr} (운행 확정 슬롯)')
    sub = dispatched_df[dispatched_df['direction'] == dir_code]
    if sub.empty:
        st.caption(f'{dir_kr} 방향 운행 슬롯 없음'); continue
    left, right = st.columns(2)
    with left:
        st.markdown('**요일별 예약 인원 (슬롯 누적)**')
        st.altair_chart(stacked_chart(sub, 'reservations', '예약 인원'))
    with right:
        st.markdown('**요일별 실현 순편익 — 원 (슬롯 누적)**')
        st.altair_chart(stacked_chart(sub, 'net_benefit', '순편익(원)'))

st.divider()

# ── 미운행 슬롯 차트 (예약자 ≥ 1, 운행 X) ───────────
st.subheader('🚫 미운행 슬롯 — 예약자는 있었으나 N\\* 미달')
missed = df[(df['dispatched'] == False) & (df['reservations'] >= 1)].copy()
if missed.empty:
    st.caption('해당 케이스 없음 — 모든 예약자가 있는 슬롯이 운행됐습니다.')
else:
    missed['dir_kr'] = missed['direction'].map(
        {'to_station': '울산역행', 'to_campus': '캠퍼스행'})
    missed_chart = alt.Chart(missed).mark_bar().encode(
        x=alt.X('slot_label:N', sort='-y', title='슬롯 (요일 + 시간)',
                axis=alt.Axis(labelAngle=0)),
        y=alt.Y('reservations:Q', title='예약 인원'),
        color=alt.Color('dir_kr:N', title='방향',
                        scale=alt.Scale(domain=['울산역행', '캠퍼스행'],
                                        range=['#d97706', '#a855f7'])),
        tooltip=[alt.Tooltip('slot_label:N', title='슬롯'),
                 alt.Tooltip('dir_kr:N', title='방향'),
                 alt.Tooltip('travel_date:N', title='날짜'),
                 alt.Tooltip('reservations:Q', title='예약 인원'),
                 alt.Tooltip('required:Q', title='필요 N*')]
    ).properties(width='container', height=300)
    threshold = alt.Chart(pd.DataFrame({'y': [n_star]})).mark_rule(
        color='red', strokeDash=[6, 4]).encode(y='y:Q')
    st.altair_chart(missed_chart + threshold)
    st.caption(f'빨간 점선 = N\\*({n_star}명). 점선까지 모이면 운행 가능.')

st.divider()

# ── 슬롯별 상세 표 ─ slot만 유지 (weekday, train_time 제거) ──
st.subheader('슬롯별 상세')
st.dataframe(
    df[['service', 'direction', 'slot_label', 'travel_date',
        'reservations', 'required', 'dispatched', 'net_benefit']]
      .rename(columns={'slot_label': 'slot'}),
    width='stretch', hide_index=True)

# ── LLM 운영 브리핑 ─────────────────────────────────
st.subheader('🧠 운영 브리핑 (LLM, 상세)')
st.caption('한 줄 요약 · 방향별 분석 · 요일별 패턴 · 순편익 TOP 슬롯 · 아쉬운 미운행 · 운영 권고 — 6개 섹션으로 구체 서술.')
if st.button('상세 브리핑 생성'):
    with st.spinner('LLM이 집계 결과를 해석하는 중...'):
        try:
            st.markdown(narrate_report(report))
        except Exception as e:
            st.error(f'LLM 요약 오류: {e}')
else:
    st.caption('버튼을 누르면 위 집계 숫자를 바탕으로 LLM이 6개 섹션의 상세 브리핑을 생성합니다.')

st.caption(f"집계 시각: {report['generated_at']}")
