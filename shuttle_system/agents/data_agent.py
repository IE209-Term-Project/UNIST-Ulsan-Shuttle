"""실시간 Data Agent — 울산 BIS API에서 513 도착정보 조회."""
import xml.etree.ElementTree as ET
import requests

from shuttle_system.config import get_secret

BASE_URL = 'http://openapi.its.ulsan.kr/UlsanAPI'
USTEC_STOP_ID = '196040234'      # 울산과학기술원(울산역 방향)
ULSAN_ST_BACK_ID = '196015414'   # 울산역(캠퍼스 방향)


def _stop_id_for(direction):
    return USTEC_STOP_ID if direction == 'to_station' else ULSAN_ST_BACK_ID


def get_bus_arrival(stop_id, route_no_filter, api_key, num_of_rows=20):
    """해당 노선의 가장 빠른 도착 dict 또는 None."""
    url = f'{BASE_URL}/getBusArrivalInfo.xo'
    params = {'serviceKey': api_key, 'stopid': stop_id,
              'pageNo': 1, 'numOfRows': num_of_rows}
    resp = requests.get(url, params=params, timeout=8)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    candidates = []
    for row in root.iter('row'):
        route_nm = row.findtext('ROUTENM', '').strip()
        arrival_sec = row.findtext('ARRIVALTIME', '').strip()
        if route_nm == route_no_filter and arrival_sec.isdigit():
            candidates.append({
                'route': route_nm, 'arrival_sec': int(arrival_sec),
                'arrival_min': round(int(arrival_sec) / 60, 1),
                'present_stop': row.findtext('PRESENTSTOPNM', '').strip(),
                'stops_left': row.findtext('PREVSTOPCNT', '').strip(),
                'stop_name': row.findtext('STOPNM', '').strip()})
    if not candidates:
        return None
    return min(candidates, key=lambda c: c['arrival_sec'])


def fetch_513_arrival(direction):
    """실시간 513 도착. dict(found=bool, ...)."""
    if direction not in ('to_station', 'to_campus'):
        return {'error': "direction은 'to_station' 또는 'to_campus'"}
    api_key = get_secret('ULSAN_BIS_API_KEY')
    info = get_bus_arrival(_stop_id_for(direction), '513', api_key)
    if info is None:
        return {'found': False, 'note': '현재 도착 예정 513 없음'}
    return {'found': True, **info}
