"""예약 가능 윈도우 = '오늘 ~ 다음 월요일 00시 직전'.

매주 월요일 00시에 시간표가 갱신되므로 그 이전까지의 셔틀만 예약 가능.
이로써 예약 후 시간표 변경에 따른 혼란을 원천 차단한다.
"""
from shuttle_system.core.booking_window import (
    is_within_booking_window, next_monday_midnight,
)


# ── next_monday_midnight: 윈도우 종료 시점 ──────────────

def test_next_monday_when_today_is_tuesday():
    # 2026-06-02 화 → 다음 월요일 = 06-08
    assert next_monday_midnight('2026-06-02') == '2026-06-08'


def test_next_monday_when_today_is_monday():
    # 2026-06-08 월 → 다음 월요일 = 06-15 (7일 후)
    assert next_monday_midnight('2026-06-08') == '2026-06-15'


def test_next_monday_when_today_is_sunday():
    # 2026-06-07 일 → 다음 월요일 = 06-08 (하루 뒤)
    assert next_monday_midnight('2026-06-07') == '2026-06-08'


def test_next_monday_when_today_is_friday():
    # 2026-06-05 금 → 다음 월요일 = 06-08
    assert next_monday_midnight('2026-06-05') == '2026-06-08'


# ── is_within_booking_window: 예약 허용 여부 ────────────

def test_allow_booking_today():
    """오늘 예약은 허용."""
    assert is_within_booking_window('2026-06-02', today='2026-06-02') is True


def test_allow_booking_within_this_week():
    """오늘(화) ~ 이번 주 금요일 예약 허용."""
    assert is_within_booking_window('2026-06-05', today='2026-06-02') is True


def test_allow_booking_until_this_sunday():
    """이번 주 일요일까지 허용."""
    assert is_within_booking_window('2026-06-07', today='2026-06-02') is True


def test_reject_booking_next_monday():
    """다음 월요일은 막힘 (시간표 갱신 시점 이후)."""
    assert is_within_booking_window('2026-06-08', today='2026-06-02') is False


def test_reject_booking_far_future():
    """2주 뒤는 막힘."""
    assert is_within_booking_window('2026-06-15', today='2026-06-02') is False


def test_reject_booking_past_week():
    """지난 주 이전 날짜는 막힘 (이번 주 월요일 이전)."""
    # 2026-06-02(화) 기준 이번 주 월요일은 2026-06-01 — 지난 주 일요일(5/31)은 거부
    assert is_within_booking_window('2026-05-31', today='2026-06-02') is False
    assert is_within_booking_window('2026-05-25', today='2026-06-02') is False


def test_same_week_monday_allowed_even_if_past():
    """오늘이 화·수여도 그 주의 월요일(과거)은 허용 — UI에서 한 주 단위로 보임."""
    assert is_within_booking_window('2026-06-01', today='2026-06-03') is True   # 월 < 수


def test_reject_invalid_date_string():
    """잘못된 날짜 문자열은 막힘."""
    assert is_within_booking_window('not-a-date', today='2026-06-02') is False


def test_monday_today_allows_through_sunday():
    """오늘이 월요일이면 이번 주 일요일(+6일)까지 OK, 다음 주 월요일은 막힘."""
    assert is_within_booking_window('2026-06-08', today='2026-06-08') is True   # today
    assert is_within_booking_window('2026-06-14', today='2026-06-08') is True   # 일
    assert is_within_booking_window('2026-06-15', today='2026-06-08') is False  # 다음 월
