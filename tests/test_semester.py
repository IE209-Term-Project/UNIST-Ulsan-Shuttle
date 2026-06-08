"""학기 경계 헬퍼 — 3월/9월 첫 월요일부터 16주 학기, 학기 사이는 방학.

semester_of(date) 반환:
  - semester_id: 'YYYY-1' | 'YYYY-2' | None(방학)
  - week: 1..16 | None(방학)
  - is_vacation: bool
  - next_semester_id, next_semester_start
"""
from shuttle_system.core.semester import semester_of, semester_start_date


# ── 학기 시작일 ────────────────────────────────────

def test_2026_semester_1_starts_march_2_first_monday():
    # 2026-03-01 은 일요일 → 첫 월요일 = 03-02
    assert semester_start_date(2026, 1).isoformat() == '2026-03-02'


def test_2026_semester_2_starts_first_monday_of_september():
    # 2026-09-01 은 화요일 → 첫 월요일 = 09-07
    assert semester_start_date(2026, 2).isoformat() == '2026-09-07'


def test_2027_semester_1_starts_march_first_monday():
    # 2027-03-01 은 월요일 → 그 자체가 첫 월요일
    assert semester_start_date(2027, 1).isoformat() == '2027-03-01'


def test_2028_semester_1_starts_first_monday():
    # 2028-03-01 은 수요일 → 첫 월요일 = 03-06
    assert semester_start_date(2028, 1).isoformat() == '2028-03-06'


# ── 학기 중 ─────────────────────────────────────────

def test_semester_1_first_day_is_week_1():
    r = semester_of('2026-03-02')
    assert r['semester_id'] == '2026-1'
    assert r['week'] == 1
    assert r['is_vacation'] is False


def test_semester_1_day_8_is_week_2():
    r = semester_of('2026-03-09')   # 다음 주 월
    assert r['week'] == 2


def test_semester_1_week_16_last_day_sunday():
    # 시작 + 16*7 - 1 = 시작 + 111일 = 2026-06-21 (일)
    r = semester_of('2026-06-21')
    assert r['semester_id'] == '2026-1'
    assert r['week'] == 16
    assert r['is_vacation'] is False


def test_semester_2_first_day_is_week_1():
    r = semester_of('2026-09-07')
    assert r['semester_id'] == '2026-2'
    assert r['week'] == 1


def test_semester_2_week_16_last_day():
    # 2026-09-07 + 111일 = 2026-12-27 (일)
    r = semester_of('2026-12-27')
    assert r['semester_id'] == '2026-2'
    assert r['week'] == 16


# ── 방학 ───────────────────────────────────────────

def test_summer_vacation_starts_day_after_semester_1():
    r = semester_of('2026-06-22')   # 학기 1 마지막 날 다음 월요일
    assert r['is_vacation'] is True
    assert r['semester_id'] is None
    assert r['week'] is None


def test_summer_vacation_middle():
    r = semester_of('2026-07-15')
    assert r['is_vacation'] is True


def test_winter_vacation_crosses_year():
    # 2026-2 학기 끝나고 다음 해 1학기 전까지
    r = semester_of('2027-01-15')
    assert r['is_vacation'] is True


# ── 다음 학기 정보 (방학 안내 멘트용) ────────────

def test_summer_vacation_points_to_semester_2():
    r = semester_of('2026-07-15')
    assert r['next_semester_id'] == '2026-2'
    assert r['next_semester_start'] == '2026-09-07'


def test_winter_vacation_points_to_next_year_semester_1():
    r = semester_of('2027-01-15')
    assert r['next_semester_id'] == '2027-1'
    assert r['next_semester_start'] == '2027-03-01'


def test_during_semester_next_id_is_next_semester():
    # 학기 중일 때도 next_semester_id가 다음 학기를 가리킴
    r = semester_of('2026-04-15')   # 1학기 중
    assert r['semester_id'] == '2026-1'
    assert r['next_semester_id'] == '2026-2'


def test_pre_first_semester_of_year_is_winter_vacation():
    # 2026-02-15 = 2026-1 학기 시작 전 → 겨울방학, next = 2026-1
    r = semester_of('2026-02-15')
    assert r['is_vacation'] is True
    assert r['next_semester_id'] == '2026-1'
    assert r['next_semester_start'] == '2026-03-02'
