"""울산역 KTX·SRT 시간표 로드 + 방면별 시각 옵션 제공.

데이터: shuttle_system/data/timetable.json (시간표 바뀌면 이 파일만 교체).
구조: {seoul_bound:{KTX:[...],SRT:[...]}, busan_bound:{KTX:[...],SRT:[...]}}
"""
import json
from pathlib import Path

_DATA_PATH = Path(__file__).parent / 'data' / 'timetable.json'
_DATA = json.loads(_DATA_PATH.read_text(encoding='utf-8'))

BOUND_LABEL = {
    'seoul_bound': '서울·수서 방면',
    'busan_bound': '부산 방면',
}


def bounds():
    return ['seoul_bound', 'busan_bound']


def updated_date():
    return _DATA.get('updated', '')


def train_options(bound):
    """방면별 'HH:MM (KTX/SRT)' 라벨 목록을 시각순 정렬로 반환."""
    d = _DATA[bound]
    items = [(t, 'KTX') for t in d.get('KTX', [])] + [(t, 'SRT') for t in d.get('SRT', [])]
    items.sort(key=lambda x: x[0])
    return [f'{t} ({typ})' for t, typ in items]


def parse_time(option):
    """'13:58 (KTX)' -> '13:58'."""
    return option.split()[0].strip()


def all_times():
    """양방향 KTX·SRT 울산 정차 시각 전체 집합."""
    s = set()
    for b in ('seoul_bound', 'busan_bound'):
        d = _DATA.get(b, {})
        s |= set(d.get('KTX', [])) | set(d.get('SRT', []))
    return s


def train_type(hhmm):
    """해당 시각의 열차 종류(KTX/SRT) 추정. 없으면 None."""
    for b in ('seoul_bound', 'busan_bound'):
        d = _DATA.get(b, {})
        if hhmm in d.get('KTX', []):
            return 'KTX'
        if hhmm in d.get('SRT', []):
            return 'SRT'
    return None
