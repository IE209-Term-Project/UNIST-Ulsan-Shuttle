"""SHUTTLE_FIXED 동적 로드/저장 — Promotion Agent와 schedule.py를 잇는 연결고리.

스키마(시트 schedule_overrides):
  effective_from | direction | weekday | shuttle_time | slot_label | demand

매 변경 시 활성 fixed 슬롯 묶음을 통째로 append. 가장 최근
effective_from (≤ today) 묶음이 현재 활성. 미래 effective_from은
아직 활성화 전 (예약 윈도우 내 학생 보호).

5분 TTL 캐시로 시트 호출을 줄인다. apply 시 캐시 무효화.
"""
from datetime import datetime, timedelta

from shuttle_system.core import schedule as sch

TTL_SECONDS = 300   # 5분

# 캐시 key = (id(store), today_iso) → (data_dict_or_None, expires_at)
_CACHE = {}


def _today_iso():
    return datetime.now().strftime('%Y-%m-%d')


def load_active_overrides(store, today=None):
    """가장 최근 effective_from(≤ today) 묶음을 SHUTTLE_FIXED 형태로 반환.

    overrides 없거나 store가 지원하지 않으면 None.
    """
    today = today or _today_iso()
    try:
        rows = store.get_schedule_overrides()
    except AttributeError:
        return None
    if not rows:
        return None

    past = [r for r in rows if str(r.get('effective_from', '')) <= today]
    if not past:
        return None

    latest = max(str(r.get('effective_from')) for r in past)
    active_rows = [r for r in past if str(r.get('effective_from')) == latest]

    table = {'to_station': [], 'to_campus': []}
    for r in active_rows:
        direction = str(r.get('direction', ''))
        if direction not in table:
            continue
        try:
            wd = int(r.get('weekday'))
            demand = int(r.get('demand', 0) or 0)
        except (TypeError, ValueError):
            continue
        table[direction].append({
            'slot': str(r.get('slot_label', '')),
            'wd': wd,
            'shuttle': str(r.get('shuttle_time', '')),
            'demand': demand,
        })
    return table


def save_new_baseline(store, fixed_table, effective_from):
    """fixed_table 전체를 새 effective_from으로 시트에 append. 캐시 무효화."""
    rows = []
    for direction, entries in fixed_table.items():
        for e in entries:
            rows.append({
                'effective_from': effective_from,
                'direction': direction,
                'weekday': e.get('wd'),
                'shuttle_time': e.get('shuttle'),
                'slot_label': e.get('slot', ''),
                'demand': e.get('demand', 0),
            })
    if rows:
        store.add_schedule_overrides_rows(rows)
    invalidate_cache()


def refresh_active_schedule(store, today=None, ttl_seconds=TTL_SECONDS):
    """schedule.SHUTTLE_FIXED를 활성 overrides로 in-place 갱신.

    overrides 없으면 SHUTTLE_FIXED는 그대로(=baseline 유지).
    같은 (store, today)에 대해 ttl_seconds 동안 캐시.
    """
    today = today or _today_iso()
    now = datetime.now()
    key = (id(store), today)

    cached = _CACHE.get(key)
    if cached is not None and now < cached[1]:
        active = cached[0]
    else:
        active = load_active_overrides(store, today=today)
        _CACHE[key] = (active, now + timedelta(seconds=ttl_seconds))

    if active is None:
        return   # baseline 유지

    # in-place 갱신 (reference로 import 한 코드와 호환)
    sch.SHUTTLE_FIXED['to_station'] = active.get('to_station', [])
    sch.SHUTTLE_FIXED['to_campus'] = active.get('to_campus', [])


def invalidate_cache():
    _CACHE.clear()
