"""Report Agent — 관리자용 운영 리포트. 집계·차트는 코드, 서술은 LLM."""
from datetime import datetime

from shuttle_system.config import get_secret
from shuttle_system.core.optimization import breakeven_N, net_benefit, POLICY_FARE
from shuttle_system.core.schedule import all_slots

MODEL = 'gpt-4o-mini'
T_SAVED_MIN = 20  # 셔틀이 제거하는 513 연계 대기(분/인)


def compute_operations_report(store, fare=POLICY_FARE, travel_date=None, date_range=None):
    """예약 누적분을 슬롯별로 집계해 운행 여부·순편익·절감 대기시간 산출.

    travel_date=None이면 모든 날짜의 예약을 슬롯(요일+KTX+방향) 단위로 합산.
    date_range=(start_iso, end_iso) — 두 날짜 모두 포함(YYYY-MM-DD). 주간 보고서용.
    """
    from collections import Counter
    from shuttle_system.core.schedule import find_shuttle_slot
    n_star = breakeven_N(fare)
    records = store.all_records()

    # 실제 예약을 (방향·KTX·날짜)로 묶어 집계 (동적 조건부 대응)
    groups = Counter()
    for r in records:
        date = str(r.get('travel_date'))
        if travel_date is not None and date != travel_date:
            continue
        if date_range is not None:
            start, end = date_range
            if not (start <= date <= end):
                continue
        groups[(str(r.get('direction')), str(r.get('train_time')), date)] += 1

    slot_rows = []
    total_runs = total_pax = total_net = total_wait_saved = 0
    for (direction, ktx, date), resv in groups.items():
        wd = _date_weekday(date)
        if wd < 0:
            continue
        slot = find_shuttle_slot(direction, ktx, wd, reservations=resv, fare=fare)
        if slot['service'] is None:
            continue   # 셔틀 운행 불가 시각(513/택시 대상)은 운영 집계에서 제외

        if slot['service'] == 'fixed':
            dispatched = resv > 0   # 고정편은 항상 운행하나, 리포트는 실제 탑승분만 집계
        else:
            dispatched = resv >= n_star

        pax = resv if dispatched else 0
        nb = net_benefit(pax, fare) if dispatched else 0
        wait_saved = pax * T_SAVED_MIN

        if dispatched:
            total_runs += 1
            total_pax += pax
            total_net += nb
            total_wait_saved += wait_saved

        slot_rows.append({
            'service': slot['service'], 'direction': direction,
            'slot': slot['slot'], 'train_time': ktx,
            'weekday': '월화수목금토일'[wd],
            'travel_date': date,
            'reservations': resv, 'required': (n_star if slot['service'] == 'conditional' else 1),
            'dispatched': dispatched, 'net_benefit': round(nb),
            'wait_saved_min': wait_saved})

    slot_rows.sort(key=lambda r: (r['travel_date'], r['train_time'], r['direction']))
    return {
        'fare': fare, 'n_star': n_star,
        'total_runs': total_runs, 'total_passengers': total_pax,
        'total_net_benefit': round(total_net),
        'total_wait_saved_hours': round(total_wait_saved / 60, 1),
        'slots': slot_rows,
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M')}


def _date_weekday(travel_date):
    try:
        return datetime.strptime(str(travel_date).strip(), '%Y-%m-%d').weekday()
    except (ValueError, AttributeError):
        return -1


def make_charts(report, out_dir='/content'):
    """슬롯별 (예약 vs N*) 막대 + (실현 순편익) 막대 2장을 PNG로 저장. 경로 리스트 반환."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    rows = report['slots']
    labels = [f"{r['slot']}\n{r['direction'][3:]}" for r in rows]

    # 차트1: 예약 vs N*
    fig1, ax1 = plt.subplots(figsize=(11, 4))
    resv = [r['reservations'] for r in rows]
    colors = ['#2e7d32' if r['dispatched'] else '#bdbdbd' for r in rows]
    ax1.bar(labels, resv, color=colors)
    ax1.axhline(report['n_star'], color='red', linestyle='--',
                label=f"N* = {report['n_star']}")
    ax1.set_title('Reservations vs Breakeven N*')
    ax1.set_ylabel('reservations'); ax1.legend()
    plt.xticks(rotation=45, ha='right'); fig1.tight_layout()
    p1 = f'{out_dir}/report_reservations.png'; fig1.savefig(p1, dpi=120); plt.close(fig1)

    # 차트2: 실현 순편익
    fig2, ax2 = plt.subplots(figsize=(11, 4))
    nb = [r['net_benefit'] for r in rows]
    ax2.bar(labels, nb, color=['#1565c0' if v >= 0 else '#c62828' for v in nb])
    ax2.axhline(0, color='black', linewidth=0.8)
    ax2.set_title('Realized Social Net Benefit (b*N - C)')
    ax2.set_ylabel('KRW')
    plt.xticks(rotation=45, ha='right'); fig2.tight_layout()
    p2 = f'{out_dir}/report_net_benefit.png'; fig2.savefig(p2, dpi=120); plt.close(fig2)

    return [p1, p2]


def narrate_report(report):
    """집계 숫자를 LLM이 관리자용 상세 운영 브리핑으로 변환. 계산은 하지 않는다."""
    from openai import OpenAI
    client = OpenAI(api_key=get_secret('OPENAI_API_KEY'))

    DIR_KR = {'to_station': '울산역행', 'to_campus': '캠퍼스행'}
    slots = report['slots']

    # 풍부한 facts 구성 — LLM이 구체적 서술을 짤 수 있도록 정렬·집계해 넣는다.
    dispatched = [r for r in slots if r['dispatched']]
    missed = [r for r in slots if not r['dispatched'] and r['reservations'] >= 1]

    by_dir = {}
    for r in dispatched:
        d = by_dir.setdefault(r['direction'], {'runs': 0, 'pax': 0, 'net': 0})
        d['runs'] += 1; d['pax'] += r['reservations']; d['net'] += r['net_benefit']

    by_wd = {}
    for r in dispatched:
        d = by_wd.setdefault(r['weekday'], {'runs': 0, 'pax': 0, 'net': 0})
        d['runs'] += 1; d['pax'] += r['reservations']; d['net'] += r['net_benefit']

    top_slots = sorted(dispatched, key=lambda r: r['net_benefit'], reverse=True)[:5]
    busy_slots = sorted(dispatched, key=lambda r: r['reservations'], reverse=True)[:5]
    close_miss = sorted(missed, key=lambda r: r['reservations'], reverse=True)[:5]

    facts = {
        '집계_기간': report.get('generated_at'),
        '요금정책_F': report['fare'], '손익분기_N별': report['n_star'],
        '총_운행_횟수': report['total_runs'],
        '총_수송_인원': report['total_passengers'],
        '총_실현_순편익_원': report['total_net_benefit'],
        '총_대기절감_시간': report['total_wait_saved_hours'],
        '방향별_집계': {DIR_KR.get(k, k): v for k, v in by_dir.items()},
        '요일별_집계': by_wd,
        '순편익_상위_슬롯': [
            {'슬롯': r['slot'], '방향': DIR_KR.get(r['direction']), 'KTX': r['train_time'],
             '요일': r['weekday'], '날짜': r['travel_date'],
             '예약': r['reservations'], '순편익': r['net_benefit']} for r in top_slots],
        '수송_상위_슬롯': [
            {'슬롯': r['slot'], '방향': DIR_KR.get(r['direction']), '요일': r['weekday'],
             '예약': r['reservations']} for r in busy_slots],
        '아쉽게_미운행': [
            {'슬롯': r['slot'], '방향': DIR_KR.get(r['direction']), '요일': r['weekday'],
             '날짜': r['travel_date'], '예약': r['reservations'], '필요_N별': r['required'],
             '부족_인원': r['required'] - r['reservations']} for r in close_miss],
        '미운행_슬롯_총건수': len(missed),
        '미운행_총_잠재인원': sum(r['reservations'] for r in missed),
    }

    prompt = (
        "너는 UNIST↔울산역 수요반응형 셔틀의 운영 관리자에게 보고서를 쓰는 분석가다. "
        "아래 JSON 집계 결과만 근거로 한국어 운영 브리핑을 작성해라. "
        "숫자는 절대 지어내지 말고 JSON에 있는 값만 사용하라. 추정·예측 표현 금지. "
        "다음 6개 섹션을 모두 포함하되 각 섹션은 헤더(예: '### 1) 한 줄 요약')로 시작한다:\n"
        "1) **한 줄 요약** — 총 운행/수송/순편익/대기절감을 한 문장으로.\n"
        "2) **방향별 분석** — 울산역행 vs 캠퍼스행 운행·수송·순편익 비교, 어느 쪽 수요가 두꺼운지.\n"
        "3) **요일별 패턴** — 가장 바쁜 요일·한산한 요일 지목, 운행 집중도 코멘트.\n"
        "4) **순편익 기여 TOP 슬롯** — 상위 3개 슬롯을 (요일·KTX·방향·예약·순편익)로 구체적으로 언급.\n"
        "5) **아쉬운 미운행 케이스** — N* 임계에 가깝게 미달한 슬롯을 부족 인원과 함께 짚고, "
        "잠재 손실(미운행 총 잠재인원)을 명시.\n"
        "6) **운영 권고** — 위 패턴 근거로 1~2가지 실행 가능한 권고(예: 특정 시각대 홍보, 임계 가까운 슬롯의 카풀 우선 매칭). "
        "근거 없는 권고는 금지.\n\n"
        "톤은 보수적·실무적. 전체 분량 12~18문장. Markdown 사용. JSON:\n"
        f"{facts}")
    resp = client.chat.completions.create(
        model=MODEL, messages=[{'role': 'user', 'content': prompt}])
    return resp.choices[0].message.content


# ── 주간 xlsx 보고서 ───────────────────────────────────
def build_weekly_xlsx(store, week_start, week_end, fare=POLICY_FARE):
    """(week_start~week_end, YYYY-MM-DD 포함구간) 주간 운영 보고서 xlsx 바이트.

    시트 구성: 1) 요약(KPI) 2) 슬롯별 상세 3) 요일별 그래프 4) 미운행 슬롯.
    매주 월요일 00시 이후 직전 주(Mon~Sun)를 대상으로 호출한다.
    """
    import io
    from openpyxl import Workbook
    from openpyxl.chart import BarChart, Reference
    from openpyxl.chart.label import DataLabelList
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    report = compute_operations_report(store, fare=fare,
                                       date_range=(week_start, week_end))
    DIR_KR = {'to_station': '울산역행', 'to_campus': '캠퍼스행'}
    WD = ['월', '화', '수', '목', '금', '토', '일']

    wb = Workbook()
    thin = Border(left=Side(style='thin', color='E5E7EB'),
                  right=Side(style='thin', color='E5E7EB'),
                  top=Side(style='thin', color='E5E7EB'),
                  bottom=Side(style='thin', color='E5E7EB'))
    head_fill = PatternFill('solid', fgColor='111827')
    head_font = Font(bold=True, color='FFFFFF', size=11)
    title_font = Font(bold=True, size=16, color='111827')
    sub_font = Font(size=11, color='6B7280')
    kpi_label = Font(bold=True, size=11, color='6B7280')
    kpi_value = Font(bold=True, size=14, color='111827')

    # ── 시트1: 요약 ─────────────────────────
    ws = wb.active
    ws.title = '요약'
    ws['A1'] = 'UNIST↔울산역 셔틀 주간 운영 보고서'; ws['A1'].font = title_font
    ws['A2'] = f"기간: {week_start} ~ {week_end} (월~일)"; ws['A2'].font = sub_font
    ws['A3'] = (f"요금 정책 F: ₩{report['fare']:,}   ·   "
                f"손익분기 N*: {report['n_star']}명   ·   "
                f"집계 시각: {report['generated_at']}")
    ws['A3'].font = sub_font

    ws['A5'] = '핵심 지표'; ws['A5'].font = Font(bold=True, size=13)
    kpis = [
        ('운행 횟수', f"{report['total_runs']} 회"),
        ('수송 인원', f"{report['total_passengers']} 명"),
        ('실현 순편익', f"₩{report['total_net_benefit']:,}"),
        ('대기시간 절감', f"{report['total_wait_saved_hours']} 시간"),
    ]
    for i, (k, v) in enumerate(kpis):
        col = get_column_letter(1 + i * 2)
        ws[f'{col}6'] = k; ws[f'{col}6'].font = kpi_label
        ws[f'{col}7'] = v; ws[f'{col}7'].font = kpi_value
        ws.column_dimensions[col].width = 18
        ws.column_dimensions[get_column_letter(2 + i * 2)].width = 4

    # 방향별 요약
    ws['A10'] = '방향별 요약'; ws['A10'].font = Font(bold=True, size=13)
    dir_head = ['방향', '운행 횟수', '수송 인원', '실현 순편익(원)']
    for j, h in enumerate(dir_head, start=1):
        c = ws.cell(row=11, column=j, value=h)
        c.font = head_font; c.fill = head_fill; c.alignment = Alignment(horizontal='center')
    by_dir = {}
    for r in report['slots']:
        if not r['dispatched']:
            continue
        d = by_dir.setdefault(r['direction'], {'runs': 0, 'pax': 0, 'net': 0})
        d['runs'] += 1; d['pax'] += r['reservations']; d['net'] += r['net_benefit']
    for i, (dkey, label) in enumerate([('to_station', '울산역행'), ('to_campus', '캠퍼스행')], start=12):
        d = by_dir.get(dkey, {'runs': 0, 'pax': 0, 'net': 0})
        ws.cell(row=i, column=1, value=label)
        ws.cell(row=i, column=2, value=d['runs'])
        ws.cell(row=i, column=3, value=d['pax'])
        ws.cell(row=i, column=4, value=d['net']).number_format = '#,##0'

    # 미운행 요약
    missed = [r for r in report['slots']
              if not r['dispatched'] and r['reservations'] >= 1]
    ws['A15'] = '미운행 슬롯 (예약 ≥1, N* 미달)'
    ws['A15'].font = Font(bold=True, size=13)
    ws['A16'] = (f"{len(missed)} 건  ·  총 잠재 인원 "
                 f"{sum(r['reservations'] for r in missed)} 명")
    ws.column_dimensions['A'].width = 22

    # ── 시트2: 슬롯별 상세 ─────────────────
    ws2 = wb.create_sheet('슬롯별 상세')
    headers = ['요일', '날짜', '방향', '슬롯', 'KTX', '예약 인원',
               '필요 N*', '운행', '실현 순편익(원)', '서비스 유형']
    ws2.append(headers)
    for c in ws2[1]:
        c.font = head_font; c.fill = head_fill
        c.alignment = Alignment(horizontal='center')
    for r in report['slots']:
        ws2.append([r['weekday'], r['travel_date'], DIR_KR.get(r['direction'], r['direction']),
                    r['slot'], r['train_time'], r['reservations'], r['required'],
                    '✓ 운행' if r['dispatched'] else '✗ 미운행', r['net_benefit'],
                    '고정' if r['service'] == 'fixed' else '조건부'])
    for row in ws2.iter_rows(min_row=2, max_row=ws2.max_row,
                             min_col=1, max_col=len(headers)):
        for c in row:
            c.border = thin
            if c.column == 9:
                c.number_format = '#,##0'
    widths = [6, 12, 10, 16, 8, 9, 9, 10, 14, 10]
    for i, w in enumerate(widths, start=1):
        ws2.column_dimensions[get_column_letter(i)].width = w
    ws2.freeze_panes = 'A2'

    # ── 시트3: 그래프 (요일별 인원·순편익) ──
    ws3 = wb.create_sheet('그래프')
    ws3.append(['요일', '수송 인원', '실현 순편익(원)'])
    for c in ws3[1]:
        c.font = head_font; c.fill = head_fill
        c.alignment = Alignment(horizontal='center')
    by_wd = {wd: {'pax': 0, 'net': 0} for wd in WD}
    for r in report['slots']:
        if r['dispatched'] and r['weekday'] in by_wd:
            by_wd[r['weekday']]['pax'] += r['reservations']
            by_wd[r['weekday']]['net'] += r['net_benefit']
    for wd in WD:
        ws3.append([wd, by_wd[wd]['pax'], by_wd[wd]['net']])
    for col in range(1, 4):
        ws3.column_dimensions[get_column_letter(col)].width = 16

    c1 = BarChart(); c1.type = 'col'; c1.style = 11
    c1.title = '요일별 수송 인원'; c1.y_axis.title = '명'; c1.x_axis.title = '요일'
    c1.add_data(Reference(ws3, min_col=2, min_row=1, max_row=8), titles_from_data=True)
    c1.set_categories(Reference(ws3, min_col=1, min_row=2, max_row=8))
    c1.dataLabels = DataLabelList(showVal=True); c1.height = 9; c1.width = 18
    ws3.add_chart(c1, 'E2')

    c2 = BarChart(); c2.type = 'col'; c2.style = 12
    c2.title = '요일별 실현 순편익 (원)'; c2.y_axis.title = '원'; c2.x_axis.title = '요일'
    c2.add_data(Reference(ws3, min_col=3, min_row=1, max_row=8), titles_from_data=True)
    c2.set_categories(Reference(ws3, min_col=1, min_row=2, max_row=8))
    c2.dataLabels = DataLabelList(showVal=True); c2.height = 9; c2.width = 18
    ws3.add_chart(c2, 'E22')

    # ── 시트4: 미운행 슬롯 ─────────────────
    ws4 = wb.create_sheet('미운행 슬롯')
    mh = ['요일', '날짜', '방향', '슬롯', 'KTX', '예약 인원', '필요 N*', '부족 인원']
    ws4.append(mh)
    for c in ws4[1]:
        c.font = head_font; c.fill = head_fill
        c.alignment = Alignment(horizontal='center')
    missed_sorted = sorted(missed, key=lambda r: r['reservations'], reverse=True)
    for r in missed_sorted:
        ws4.append([r['weekday'], r['travel_date'], DIR_KR.get(r['direction'], r['direction']),
                    r['slot'], r['train_time'], r['reservations'], r['required'],
                    r['required'] - r['reservations']])
    for row in ws4.iter_rows(min_row=2, max_row=ws4.max_row,
                             min_col=1, max_col=len(mh)):
        for c in row:
            c.border = thin
    widths4 = [6, 12, 10, 16, 8, 10, 9, 10]
    for i, w in enumerate(widths4, start=1):
        ws4.column_dimensions[get_column_letter(i)].width = w
    ws4.freeze_panes = 'A2'

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
