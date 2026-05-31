from datetime import datetime
from shuttle_system.core.connection import (
    evaluate_connection, recommend_taxi, RIDE_MIN,
)

NOW = datetime(2026, 6, 5, 13, 0)  # 금 13:00 고정


def test_to_station_safe():
    # 도보 0분, 버스 2분 후 -> 13:02 탑승 -> 13:22 역도착, KTX 13:58 -> 여유
    r = evaluate_connection('to_station', bus_arrival_min=2, ktx_time='13:58',
                            walk_to_stop_min=0, now=NOW)
    assert r['status'] == 'SAFE'


def test_to_station_miss():
    # 버스 50분 후 -> 13:50 탑승 -> 14:10 역도착 > 13:58 -> MISS
    r = evaluate_connection('to_station', bus_arrival_min=50, ktx_time='13:58', now=NOW)
    assert r['status'] == 'MISS'


def test_to_station_bus_too_soon():
    r = evaluate_connection('to_station', bus_arrival_min=2, ktx_time='13:58',
                            walk_to_stop_min=5, now=NOW)
    # 도보 5분 > 버스 2분이면 BUS_TOO_SOON
    assert r['status'] == 'BUS_TOO_SOON'


def test_to_campus_good():
    r = evaluate_connection('to_campus', bus_arrival_min=8, ktx_time='13:00', now=NOW)
    # 하차 ready=13:05, 버스 13:08 출발 -> 대기 3분 -> GOOD
    assert r['status'] == 'GOOD'


def test_taxi_has_estimate():
    r = recommend_taxi('to_station')
    assert r['mode'] == 'taxi'
    assert 'est_time_min' in r
