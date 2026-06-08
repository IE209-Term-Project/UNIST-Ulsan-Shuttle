"""실시간 Data Agent — 울산 BIS API에서 513 도착정보 조회.

캐시: 30초 단위. quota 절약 + 프론트의 빈번한 폴링 흡수.
키 로테이션: 환경변수 ULSAN_BIS_API_KEY (1차) → ULSAN_BIS_API_KEY_2 (백업).
  1차 키가 quota 초과 시 2차 키로 자동 재시도. 둘 다 초과 시 에러 표시.
에러: API의 quota·인증 에러를 명시적으로 반환.
"""
import time
import xml.etree.ElementTree as ET
import requests

from shuttle_system.config import get_secret

BASE_URL = 'http://openapi.its.ulsan.kr/UlsanAPI'
USTEC_STOP_ID = '196040234'      # 울산과학기술원(울산역 방향)
ULSAN_ST_BACK_ID = '196015414'   # 울산역(캠퍼스 방향)

CACHE_TTL_SEC = 30
_cache = {}  # {direction: (ts, dict)}

# 키 quota 상태 (당일 한도 초과한 키는 캐시해서 재시도 방지)
_exhausted_keys = set()
_exhausted_reset_ts = 0  # 자정마다 리셋

KEY_ENV_NAMES = ['ULSAN_BIS_API_KEY', 'ULSAN_BIS_API_KEY_2']


def _get_keys():
    """등록된 BIS API 키 목록. 빈/None은 제외."""
    keys = []
    for env in KEY_ENV_NAMES:
        v = get_secret(env)
        if v and v.strip():
            keys.append(v.strip())
    return keys


def _maybe_reset_exhausted():
    """자정(KST) 지나면 quota 초과 캐시 리셋. 단순 24h 기반 추정."""
    global _exhausted_reset_ts, _exhausted_keys
    now = time.time()
    # 자정 다음날 00:00:01 KST = epoch 기준 다음 9시간 후의 00시
    # 단순화: 24시간 경과 시 리셋
    if _exhausted_reset_ts == 0:
        _exhausted_reset_ts = now + 86400
    elif now > _exhausted_reset_ts:
        _exhausted_keys.clear()
        _exhausted_reset_ts = now + 86400


def _stop_id_for(direction):
    return USTEC_STOP_ID if direction == 'to_station' else ULSAN_ST_BACK_ID


def _parse_arrival_xml(content, route_no_filter='513'):
    """원시 XML에서 (status, data) 추출.

    status: 'ok' | 'quota' | 'error'
    data:   ok면 best candidate dict 또는 None; 그 외엔 error message.
    """
    root = ET.fromstring(content)
    # 에러 응답 체크 (BIS 표준: <error><resultMsg>...<resultCode>...)
    err = root.find('.//error')
    if err is not None:
        msg = (err.findtext('resultMsg') or '').strip()
        code = (err.findtext('resultCode') or '').strip()
        if 'LIMITED NUMBER OF SERVICE REQUESTS' in msg.upper() or code == '22':
            return 'quota', f'BIS API 일일 호출 한도 초과 (code {code})'
        return 'error', f'{msg} (code {code})'

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
        return 'ok', None
    return 'ok', min(candidates, key=lambda c: c['arrival_sec'])


def _call_with_key(key, stop_id):
    """주어진 키로 1회 API 호출. (status, data_or_error) 반환."""
    url = f'{BASE_URL}/getBusArrivalInfo.xo'
    params = {'serviceKey': key, 'stopid': stop_id,
              'pageNo': 1, 'numOfRows': 20}
    try:
        resp = requests.get(url, params=params, timeout=8)
        resp.raise_for_status()
    except Exception as e:
        return 'network', str(e)
    return _parse_arrival_xml(resp.content, '513')


def fetch_513_arrival(direction):
    """실시간 513 도착. 30초 캐시 + 다중 키 자동 로테이션."""
    if direction not in ('to_station', 'to_campus'):
        return {'error': "direction은 'to_station' 또는 'to_campus'"}

    now = time.time()
    cached = _cache.get(direction)
    if cached and (now - cached[0]) < CACHE_TTL_SEC:
        return {**cached[1], 'cached': True}

    _maybe_reset_exhausted()
    keys = _get_keys()
    if not keys:
        result = {'found': False, 'note': '⚠ API 키 미설정'}
        _cache[direction] = (now, result)
        return result

    stop_id = _stop_id_for(direction)
    last_error = None
    used_key_idx = None

    for idx, key in enumerate(keys):
        if key in _exhausted_keys:
            continue  # 오늘 이미 한도 도달 → 건너뛰기
        status, data = _call_with_key(key, stop_id)
        used_key_idx = idx
        if status == 'quota':
            _exhausted_keys.add(key)
            last_error = data
            continue  # 다음 키로 폴백
        # 성공이거나 quota 이외 에러 → 사용
        if status == 'ok':
            if data is None:
                result = {'found': False, 'note': '현재 도착 예정 513 없음',
                          'key_idx': idx}
            else:
                result = {'found': True, 'key_idx': idx, **data}
        elif status == 'network':
            result = {'found': False, 'note': f'네트워크 오류: {data}',
                      'key_idx': idx}
        else:  # 'error'
            result = {'found': False, 'note': f'⚠ BIS 응답 오류: {data}',
                      'key_idx': idx}
        _cache[direction] = (now, result)
        return result

    # 모든 키가 quota 초과
    result = {'found': False,
              'note': f'⚠ API 일일 호출 한도 초과 (모든 키 소진, {len(keys)}개)'}
    _cache[direction] = (now, result)
    return result
