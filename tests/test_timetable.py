from shuttle_system.timetable import bounds, train_options, parse_time


def test_bounds():
    assert set(bounds()) == {'seoul_bound', 'busan_bound'}


def test_train_options_sorted_and_labeled():
    opts = train_options('seoul_bound')
    assert len(opts) > 0
    # 각 옵션은 "HH:MM (KTX)" 또는 "HH:MM (SRT)" 형태
    assert all('(' in o and (':' in o) for o in opts)
    # 시각 기준 정렬
    times = [parse_time(o) for o in opts]
    assert times == sorted(times)


def test_parse_time():
    assert parse_time('13:58 (KTX)') == '13:58'
    assert parse_time('05:23 (SRT)') == '05:23'


def test_known_time_present():
    # 5.15 기준 서울방면 KTX 첫차 05:08 포함
    opts = train_options('seoul_bound')
    assert any(o.startswith('05:08') for o in opts)
