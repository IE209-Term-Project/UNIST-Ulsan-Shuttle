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


def _send_via_resend(to_email, subject, body):
    key = os.environ.get('RESEND_API_KEY')
    if not key:
        return None  # 폴백 시도하라는 신호
    from_addr = os.environ.get('RESEND_FROM', 'UNIST Shuttle <onboarding@resend.dev>')
    try:
        r = requests.post(RESEND_URL,
                          headers={'Authorization': f'Bearer {key}',
                                   'Content-Type': 'application/json'},
                          json={'from': from_addr, 'to': [to_email],
                                'subject': subject, 'text': body},
                          timeout=10)
        if r.status_code in (200, 201, 202):
            return {'sent': True, 'to': to_email, 'via': 'resend',
                    'id': r.json().get('id')}
        return {'sent': False, 'reason': f'resend_{r.status_code}',
                'body': r.text[:200]}
    except Exception as e:
        return {'sent': False, 'reason': str(e)}


def _send_via_smtp(to_email, subject, body):
    user = os.environ.get('GMAIL_USER')
    pw = os.environ.get('GMAIL_APP_PASSWORD')
    if not (user and pw):
        return {'sent': False, 'reason': 'no_credentials'}
    msg = EmailMessage()
    msg['From'] = f'UNIST Shuttle <{user}>'
    msg['To'] = to_email
    msg['Subject'] = subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as s:
            s.starttls()
            s.login(user, pw)
            s.send_message(msg)
        return {'sent': True, 'to': to_email, 'via': 'smtp_gmail'}
    except Exception as e:
        return {'sent': False, 'reason': str(e)}


def send(to_email, subject, body):
    """단건 발송. Resend 우선, 없으면 Gmail SMTP 폴백."""
    if not (to_email and '@' in to_email):
        return {'sent': False, 'reason': 'bad_recipient'}
    res = _send_via_resend(to_email, subject, body)
    if res is not None:
        return res
    return _send_via_smtp(to_email, subject, body)


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
