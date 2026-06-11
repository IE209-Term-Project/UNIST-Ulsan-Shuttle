"""이메일 발송 — Resend API (메인). Gmail SMTP는 한계 검증용 폴백으로 보존.

[설계 결정]
- 카카오톡 알림톡은 사업자 등록 + 비즈채널 심사 + 중계사 계약 필요 → 학생 텀프로젝트 범위 밖
- Gmail SMTP는 UNIST의 Microsoft 365 Exchange가 발송자 평판을 의심해 격리(silent drop)
- → 트랜잭셔널 메일 전용 서비스(Resend)로 전환. 발송 평판 관리는 서비스 측이 담당

환경변수:
  - RESEND_API_KEY    : Resend API 키 (필수)
  - RESEND_FROM       : 발송자(기본: 'UNIST Shuttle <onboarding@resend.dev>')
  - (폴백) GMAIL_USER + GMAIL_APP_PASSWORD : Resend 키 없을 때 SMTP로 시도(PoC)

자격증명 누락 시 조용히 미발송(앱은 정상 동작).
"""
import os
import smtplib
from email.message import EmailMessage

import requests

from shuttle_system import config  # noqa: F401 — .env 자동 로드


RESEND_URL = 'https://api.resend.com/emails'
SMTP_HOST = 'smtp.gmail.com'
SMTP_PORT = 587


def _send_via_resend(to_email, subject, body, attachments=None):
    """Resend로 발송. attachments=[{filename, content(bytes)}] 지원."""
    key = os.environ.get('RESEND_API_KEY')
    if not key:
        return None  # 폴백 시도하라는 신호
    from_addr = os.environ.get('RESEND_FROM', 'UNIST Shuttle <onboarding@resend.dev>')
    payload = {'from': from_addr, 'to': [to_email],
               'subject': subject, 'text': body}
    if attachments:
        import base64
        payload['attachments'] = [
            {'filename': a['filename'],
             'content': base64.b64encode(a['content']).decode('ascii')}
            for a in attachments]
    try:
        r = requests.post(RESEND_URL,
                          headers={'Authorization': f'Bearer {key}',
                                   'Content-Type': 'application/json'},
                          json=payload,
                          timeout=15)
        if r.status_code in (200, 201, 202):
            return {'sent': True, 'to': to_email, 'via': 'resend',
                    'id': r.json().get('id')}
        return {'sent': False, 'reason': f'resend_{r.status_code}',
                'body': r.text[:200]}
    except Exception as e:
        return {'sent': False, 'reason': str(e)}


def _send_via_smtp(to_email, subject, body, attachments=None):
    """Gmail SMTP로 발송. attachments=[{filename, content(bytes)}] 지원."""
    user = os.environ.get('GMAIL_USER')
    pw = os.environ.get('GMAIL_APP_PASSWORD')
    if not (user and pw):
        return {'sent': False, 'reason': 'no_credentials'}
    msg = EmailMessage()
    msg['From'] = f'UNIST Shuttle <{user}>'
    msg['To'] = to_email
    msg['Subject'] = subject
    msg.set_content(body)
    if attachments:
        for a in attachments:
            # xlsx의 공식 MIME: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
            mt = a.get('mimetype', 'application/octet-stream')
            maintype, _, subtype = mt.partition('/')
            msg.add_attachment(a['content'], maintype=maintype, subtype=subtype,
                               filename=a['filename'])
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as s:
            s.starttls()
            s.login(user, pw)
            s.send_message(msg)
        return {'sent': True, 'to': to_email, 'via': 'smtp_gmail'}
    except Exception as e:
        return {'sent': False, 'reason': str(e)}


def send(to_email, subject, body, attachments=None):
    """단건 발송. Resend 우선, 실패하면 Gmail SMTP 폴백.

    attachments=[{filename, content(bytes), mimetype}] 지원.
    """
    if not (to_email and '@' in to_email):
        return {'sent': False, 'reason': 'bad_recipient'}
    res = _send_via_resend(to_email, subject, body, attachments=attachments)
    if res is not None and res.get('sent'):
        return res
    smtp_res = _send_via_smtp(to_email, subject, body, attachments=attachments)
    if smtp_res.get('sent'):
        return smtp_res
    # 둘 다 실패 — 진단을 위해 Resend 실패 원인도 함께 반환
    if res is not None:
        return {'sent': False, 'reason': 'both_failed',
                'resend': res, 'smtp': smtp_res}
    return smtp_res


def notify_admin_promotion(admin_email, eval_result, apply_result=None):
    """Promotion Agent 평가/적용 결과를 관리자 이메일로 발송.

    eval_result: evaluate_promotions() 반환 dict.
    apply_result: apply_promotions() 반환 dict (적용까지 한 경우만).
    """
    if not admin_email:
        return {'sent': False, 'reason': 'no_admin_email'}

    WD = '월화수목금토일'
    DIR = {'to_station': '울산역행', 'to_campus': '캠퍼스행'}
    promos = eval_result.get('promotions', [])
    demotes = eval_result.get('demotions', [])
    frozen = eval_result.get('frozen', False)

    lines = ['UNIST↔울산역 셔틀 · 슬롯 등급 평가 결과', '']
    lines.append(f"평가 시각: {eval_result.get('evaluated_at', '')}")
    lines.append(
        f"평가 윈도우: {eval_result.get('window_start', '')} "
        f"~ {eval_result.get('window_end', '')}")
    if frozen:
        lines.append('')
        lines.append(
            f"⚠ 동결: {eval_result.get('frozen_reason', '콜드 스타트')}")
        return send(admin_email,
                    '[UNIST 셔틀] 슬롯 등급 평가 (동결)',
                    '\n'.join(lines))

    lines.append('')
    lines.append(f"승격 권고: {len(promos)}건")
    for p in promos:
        lines.append(
            f"  ⬆ {DIR.get(p['direction'], p['direction'])} · "
            f"{WD[p['weekday']]}요일 {p['time']}  "
            f"(평균 {p['avg_resv']}명, 운행률 {int(p['dispatch_rate']*100)}%)")
    lines.append('')
    lines.append(f"강등 권고: {len(demotes)}건")
    for d in demotes:
        lines.append(
            f"  ⬇ {DIR.get(d['direction'], d['direction'])} · "
            f"{WD[d['weekday']]}요일 {d['time']}  "
            f"(평균 {d['avg_resv']}명, 운행률 {int(d['dispatch_rate']*100)}%)")

    if apply_result:
        lines.append('')
        lines.append(
            f"✅ 적용 완료 — 효력 발생: {apply_result.get('effective_from', '')}")
        lines.append(
            '되돌리려면 관리자 대시보드의 [↩ 직전 시간표로 롤백] 버튼을 사용하세요.')
    else:
        lines.append('')
        lines.append('관리자 대시보드에서 [✅ 적용] 또는 [무시] 결정을 내려주세요.')

    n_change = len(promos) + len(demotes)
    subj = (f'[UNIST 셔틀] 슬롯 등급 평가 — 변경 {n_change}건'
            if n_change else '[UNIST 셔틀] 슬롯 등급 평가 — 변경 없음')
    return send(admin_email, subj, '\n'.join(lines))


def notify_admin_weekly_report(admin_email, xlsx_bytes, week_start_iso, week_end_iso,
                                summary=None):
    """주간 운영 보고서(xlsx)를 관리자 이메일에 첨부 발송.

    매주 월요일 cron에서 직전 주(Mon~Sun)를 정리해 호출.
    summary: 선택 — 본문에 간단 KPI 요약(dict).
    """
    if not admin_email:
        return {'sent': False, 'reason': 'no_admin_email'}
    if not xlsx_bytes:
        return {'sent': False, 'reason': 'no_xlsx'}

    filename = f'unist-shuttle-weekly-{week_start_iso}.xlsx'
    subject = f'[UNIST 셔틀] 주간 운영 보고서 — {week_start_iso} ~ {week_end_iso}'

    lines = [
        f'UNIST↔울산역 셔틀 · 주간 운영 보고서',
        '',
        f'대상 주차: {week_start_iso} (월) ~ {week_end_iso} (일)',
        '',
    ]
    if summary:
        lines += [
            f"· 운행 횟수: {summary.get('total_runs', 0)}회",
            f"· 수송 인원: {summary.get('total_passengers', 0)}명",
            f"· 실현 순편익: ₩{summary.get('total_net_benefit', 0):,}",
            f"· 대기 절감: {summary.get('total_wait_saved_hours', 0)}시간",
            '',
        ]
    lines += [
        f'첨부 파일: {filename} (5개 시트 — Summary/Matrix/Detail/Charts/Recommendation)',
        '',
        '본 메일은 매주 월요일 00시(KST) 자동 발송됩니다.',
    ]

    attachments = [{
        'filename': filename,
        'content': xlsx_bytes,
        'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    }]
    return send(admin_email, subject, '\n'.join(lines), attachments=attachments)


def notify_admin_semester(admin_email, run_result):
    """Semester Agent 실행 결과를 관리자 이메일로 발송.

    run_result: /api/semester/run 응답 dict.
    """
    if not admin_email:
        return {'sent': False, 'reason': 'no_admin_email'}

    WD = '월화수목금토일'
    DIR = {'to_station': '울산역행', 'to_campus': '캠퍼스행'}

    if run_result.get('frozen'):
        lines = [
            'UNIST↔울산역 셔틀 · 학기 전환 (동결)',
            '',
            f"사유: {run_result.get('reason', '학기 1주차 아님')}",
            f"현재 학기 정보: {run_result.get('semester', {})}",
        ]
        return send(admin_email,
                    '[UNIST 셔틀] 학기 전환 평가 (동결)',
                    '\n'.join(lines))

    baseline = run_result.get('baseline', {})
    weight = run_result.get('weight_info', {})
    used_fallback = run_result.get('used_fallback', False)

    lines = [
        'UNIST↔울산역 셔틀 · 학기 baseline 전환 결과',
        '',
        f"직전 학기 archive: {run_result.get('archived_semester', '?')} "
        f"({run_result.get('archived_slot_count', 0)} 슬롯)",
        f"새 학기: {run_result.get('new_semester', '?')}",
        f"효력 발생일: {run_result.get('effective_from', '?')}",
        '',
    ]
    if used_fallback:
        lines.append(f"⚠ Fallback 사용 — {weight.get('reason', '동일 학기명 archive 없음')}")
    else:
        lines.append(
            f"📚 학습 데이터: {weight.get('matched_semesters', [])} "
            f"(가중치 {weight.get('weights', [])})")
    lines.append('')

    for direction, label in [('to_station', '울산역행'), ('to_campus', '캠퍼스행')]:
        entries = baseline.get(direction, [])
        lines.append(f"[{label}] 고정 슬롯 {len(entries)}개")
        for e in entries:
            wd = e.get('wd')
            lines.append(
                f"  · {WD[wd]}요일 {e.get('shuttle', '?')}  "
                f"(예상 수요 {e.get('demand', 0)}명)")
        lines.append('')

    lines.append('되돌리려면 관리자 대시보드의 [↩ 직전 baseline으로 롤백] 버튼을 사용하세요.')

    n_slots = sum(len(baseline.get(d, [])) for d in baseline)
    subj = f'[UNIST 셔틀] 학기 baseline 전환 — 고정 슬롯 {n_slots}개'
    return send(admin_email, subj, '\n'.join(lines))


def send_confirmation(email, name, direction, shuttle_time, travel_date, service,
                      tentative=False, reservations=None, required=None):
    """예약 즉시 본인에게 보내는 메일.

    tentative=False: 운행 확정 메일 (고정편 / 이미 N* 넘은 조건부).
    tentative=True:  잠정 예약 메일 (조건부 N* 미달 — 출발 2시간 전 마감 시 확정/미운행 결정).
    """
    if not (email and '@' in email):
        return {'sent': False, 'reason': 'no_email'}
    d_kr = '울산역행' if direction == 'to_station' else '캠퍼스행'

    if tentative:
        subject = f'[UNIST Shuttle] 잠정 예약 접수 — {travel_date} {shuttle_time} {d_kr}'
        progress = ''
        if reservations is not None and required is not None:
            need = max(required - reservations, 0)
            progress = (f"• 현재 모집 인원: {reservations} / {required}명\n"
                        f"• 운행 확정까지 {need}명 더 필요\n")
        body = (f"{name or '학생'}님, UNIST 셔틀 예약이 잠정 접수되었습니다.\n\n"
                f"• 날짜: {travel_date}\n"
                f"• 시각: {shuttle_time}\n"
                f"• 방향: {d_kr}\n"
                f"• 유형: 조건부 셔틀 (잠정 — 인원 모집 중)\n"
                f"{progress}\n"
                f"📨 출발 2시간 전 마감 시점에 운행 확정/미운행 여부를 다시 이메일로 안내드립니다.\n"
                f"인원 부족 시 같은 시각 학생끼리의 카풀 채널도 안내드립니다.")
    else:
        label = '고정 셔틀' if service == 'fixed' else '조건부 셔틀 (운행 확정)'
        subject = f'[UNIST Shuttle] 예약 확정 — {travel_date} {shuttle_time} {d_kr}'
        body = (f"{name or '학생'}님, UNIST 셔틀 예약이 확정되었습니다.\n\n"
                f"• 날짜: {travel_date}\n"
                f"• 시각: {shuttle_time}\n"
                f"• 방향: {d_kr}\n"
                f"• 유형: {label}\n\n"
                f"시간 맞춰 정류장으로 와주세요.")
    return send(email, subject, body)


def notify_slot(store, event):
    """이벤트가 가리키는 슬롯의 모든 예약자에게 이메일 발송.

    store.all_records()에서 (direction, train_time, travel_date) 매칭 + 이메일이 있는 행 추출.
    """
    direction = event.get('direction')
    ktx = event.get('train_time')
    date = event.get('travel_date')
    subject = '[UNIST Shuttle] ' + ('운행 확정 안내' if event.get('type') == 'dispatch'
                                     else '셔틀 알림')
    body = event.get('message', '')
    sent, skipped = [], []
    for r in store.all_records():
        if (str(r.get('direction')) == direction
                and str(r.get('train_time')) == ktx
                and str(r.get('travel_date')) == date):
            email = str(r.get('email', '')).strip()
            if not email or '@' not in email:
                skipped.append(r.get('name'))
                continue
            res = send(email, subject, body)
            (sent if res.get('sent') else skipped).append(r.get('name'))
    return {'sent': sent, 'skipped': skipped}
