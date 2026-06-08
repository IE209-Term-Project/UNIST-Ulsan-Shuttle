"""예약 가능 윈도우 = '오늘 ~ 다음 월요일 00시 직전'.

매주 월요일 00시에 시간표가 갱신되므로, 학생은 그 이전까지의 셔틀만 예약 가능.
변경 시점과 예약 가능 범위가 정확히 맞물려, 예약 후 시간표가 바뀌어 학생이
혼란을 겪는 케이스가 발생하지 않는다.
"""
from datetime import datetime, timedelta


def _today_iso():
    return datetime.now().strftime('%Y-%m-%d')


def next_monday_midnight(today=None):
    """today 기준 '다음 월요일' 날짜(YYYY-MM-DD).

    today가 월요일이면 7일 후 월요일을 반환.
    """
    today = today or _today_iso()
    d = datetime.strptime(today, '%Y-%m-%d').date()
    days_to_next_mon = 7 - d.weekday()    # 월=0 → 7, 일=6 → 1
    return (d + timedelta(days=days_to_next_mon)).strftime('%Y-%m-%d')


def is_within_booking_window(travel_date, today=None):
    """travel_date가 [today, 다음 월요일) 범위 안인지."""
    today = today or _today_iso()
    try:
        tv = datetime.strptime(str(travel_date), '%Y-%m-%d').date()
        td = datetime.strptime(today, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return False
    nm = datetime.strptime(next_monday_midnight(today), '%Y-%m-%d').date()
    return td <= tv < nm

