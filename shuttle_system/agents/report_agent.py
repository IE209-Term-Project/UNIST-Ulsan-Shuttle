"""Report Agent — 관리자용 운영 리포트. 집계·차트는 코드, 서술은 LLM."""
from datetime import datetime

from shuttle_system.config import get_secret
from shuttle_system.core.optimization import breakeven_N, net_benefit, POLICY_FARE
from shuttle_system.core.schedule import all_slots

MODEL = 'gpt-4o-mini'
T_SAVED_MIN = 20  # 셔틀이 제거하는 513 연계 대기(분/인)


def compute_operations_report(store, fare=POLICY_FARE, travel_date=None):
    """예약 누적분을 슬롯별로 집계해 운행 여부·순편익·절감 대기시간 산출.

    travel_date=None이면 모든 날짜의 예약을 슬롯(요일+KTX+방향) 단위로 합산.
    """
    n_star = breakeven_N(fare)
    records = store.all_records()

    slot_rows = []
    total_runs = total_pax = total_net = total_wait_saved = 0
    for slot in all_slots():
        # 이 슬롯 요일과 일치하는 예약을 KTX시각·방향으로 합산
        target_wd = slot['wd']
        resv = sum(
            1 for r in records
            if str(r.get('direction')) == slot['direction']
            and str(r.get('ktx_time')) == slot['ktx']
            and _date_weekday(r.get('travel_date')) == target_wd
            and (travel_date is None or str(r.get('travel_date')) == travel_date))

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
            'service': slot['service'], 'direction': slot['direction'],
            'slot': slot['slot'], 'ktx': slot['ktx'],
            'reservations': resv, 'required': (n_star if slot['service'] == 'conditional' else 1),
            'dispatched': dispatched, 'net_benefit': round(nb),
            'wait_saved_min': wait_saved, 'survey_demand': slot.get('demand')})

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
    """집계 숫자를 LLM이 관리자용 서술 요약으로 변환. 계산은 하지 않는다."""
    from openai import OpenAI
    client = OpenAI(api_key=get_secret('OPENAI_API_KEY'))
    facts = {k: v for k, v in report.items() if k != 'slots'}
    facts['dispatched_slots'] = [
        {'slot': r['slot'], 'direction': r['direction'], 'reservations': r['reservations'],
         'net_benefit': r['net_benefit']} for r in report['slots'] if r['dispatched']]
    facts['skipped_conditional'] = [
        {'slot': r['slot'], 'reservations': r['reservations'], 'required': r['required']}
        for r in report['slots']
        if r['service'] == 'conditional' and not r['dispatched']]

    prompt = ("너는 셔틀 운영 관리자용 리포트를 쓰는 분석가다. 아래 JSON 집계 결과만 근거로 "
              "3~5문장 한국어 브리핑을 써라. 총 운행/수송/순편익/대기시간 절감을 먼저 요약하고, "
              "순편익 기여 1위 슬롯과 임계 미달로 미운행된 조건부 슬롯을 언급해라. "
              "숫자를 지어내지 말고 주어진 값만 사용. JSON: "
              f"{facts}")
    resp = client.chat.completions.create(
        model=MODEL, messages=[{'role': 'user', 'content': prompt}])
    return resp.choices[0].message.content
