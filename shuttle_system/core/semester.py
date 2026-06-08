"""학기 경계 — 3월/9월 첫 월요일부터 16주 학기, 학기 사이는 방학.

학사 캘린더 API 의존성 없이 Python 표준 datetime만으로 매년 자동 계산.
실제 UNIST 개강일과 ±1주 오차 가능하나, 콜드 스타트 3주가 흡수.
"""
from datetime import date, datetime, timedelta

SEMESTER_WEEKS = 16


def _first_monday_of_month(year, month):
    """그 달의 첫 월요일 (그 달 1일이 월요일이면 1일 자체)."""
    d = date(year, month, 1)
    # weekday: 월=0..일=6. 다음 월요일까지 = (0 - wd) % 7
    delta = (0 - d.weekday()) % 7
    return d + timedelta(days=delta)


def semester_start_date(year, term):
    """학기 시작일(1주차 월요일). term=1(봄)→3월, term=2(가을)→9월."""
    return _first_monday_of_month(year, 3 if term == 1 else 9)


def semester_end_date(year, term):
    """학기 종료일(16주차 일요일) = 시작 + 16*7 - 1 = +111일."""
    return semester_start_date(year, term) + timedelta(
        days=SEMESTER_WEEKS * 7 - 1)


def _semester_window(year, term):
    s = semester_start_date(year, term)
    e = semester_end_date(year, term)
    return s, e


def _vacation_response(d, next_year, next_term):
    nxt_start = semester_start_date(next_year, next_term)
    return {
        'semester_id': None,
        'week': None,
        'is_vacation': True,
        'next_semester_id': f'{next_year}-{next_term}',
        'next_semester_start': nxt_start.isoformat(),
    }


def semester_of(date_str):
    """date_str(YYYY-MM-DD)가 어느 학기 몇 주차인지, 또는 방학인지 반환.

    Returns:
      {
        'semester_id': 'YYYY-1' | 'YYYY-2' | None,
        'week': 1..16 | None,
        'is_vacation': bool,
        'next_semester_id': str,        # 항상 채워짐
        'next_semester_start': 'YYYY-MM-DD',
      }
    """
    d = datetime.strptime(str(date_str), '%Y-%m-%d').date()
    year = d.year

    s1_start, s1_end = _semester_window(year, 1)
    s2_start, s2_end = _semester_window(year, 2)

    # 1학기 중
    if s1_start <= d <= s1_end:
        week = (d - s1_start).days // 7 + 1
        return {
            'semester_id': f'{year}-1', 'week': week, 'is_vacation': False,
            'next_semester_id': f'{year}-2',
            'next_semester_start': s2_start.isoformat(),
        }
    # 2학기 중
    if s2_start <= d <= s2_end:
        week = (d - s2_start).days // 7 + 1
        nxt_s1 = semester_start_date(year + 1, 1)
        return {
            'semester_id': f'{year}-2', 'week': week, 'is_vacation': False,
            'next_semester_id': f'{year + 1}-1',
            'next_semester_start': nxt_s1.isoformat(),
        }

    # 방학 — 어디?
    if d < s1_start:
        # 1학기 전 = 작년 2학기에서 넘어온 겨울방학, 다음 학기 = 올해 1학기
        return _vacation_response(d, year, 1)
    if d < s2_start:
        # 1학기 끝 ~ 2학기 전 = 여름방학
        return _vacation_response(d, year, 2)
    # 2학기 끝 이후 = 다음 해 1학기로 가는 겨울방학
    return _vacation_response(d, year + 1, 1)

