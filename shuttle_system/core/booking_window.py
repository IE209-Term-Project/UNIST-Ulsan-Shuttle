"""예약 가능 윈도우 = '이번 주 월요일 ~ 다음 월요일 00시 직전' (월~일 한 주 전체).

매주 월요일 00시에 시간표가 갱신되므로, 학생은 그 이전까지의 셔틀만 예약 가능.
오늘이 수요일이어도 그 주의 월·화도 윈도우 안 — 학생이 한 주 단위로 일정을 보고
예약하는 UX가 자연스럽다. (이미 출발 시각이 지난 셔틀은 별도 phase/time check가 거부.)
"""
from datetime import datetime, timedelta


def _today_iso():
    return datetime.now().strftime('%Y-%m-%d')


def current_monday(today=None):
    """today가 속한 주의 월요일 날짜(YYYY-MM-DD). 오늘이 월요일이면 그대로."""
    today = today or _today_iso()
    d = datetime.strptime(today, '%Y-%m-%d').date()
    return (d - timedelta(days=d.weekday())).strftime('%Y-%m-%d')


def next_monday_midnight(today=None):
    """today 기준 '다음 월요일' 날짜(YYYY-MM-DD).

    today가 월요일이면 7일 후 월요일을 반환.
    """
    today = today or _today_iso()
    d = datetime.strptime(today, '%Y-%m-%d').date()
    days_to_next_mon = 7 - d.weekday()    # 월=0 → 7, 일=6 → 1
    return (d + timedelta(days=days_to_next_mon)).strftime('%Y-%m-%d')


def is_within_booking_window(travel_date, today=None):
    """travel_date가 [이번 주 월요일, 다음 월요일) 범위 안인지."""
    today = today or _today_iso()
    try:
        tv = datetime.strptime(str(travel_date), '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return False
    mon = datetime.strptime(current_monday(today), '%Y-%m-%d').date()
    nm = datetime.strptime(next_monday_midnight(today), '%Y-%m-%d').date()
    return mon <= tv < nm

