"""카카오톡 '나에게 보내기'(메모) 발송.

발송자 본인에게만 보낸다(PoC). 실서비스 전체 발송은 카카오 알림톡(비즈메시지)로 확장.

필요한 시크릿(둘 중 하나):
  - KAKAO_ACCESS_TOKEN                      : talk_message 동의로 발급된 액세스 토큰
  - (자동 갱신용) KAKAO_REFRESH_TOKEN + KAKAO_REST_API_KEY

토큰이 없으면 조용히 미발송(앱은 정상 동작).
"""
import json
import os

import requests

# .env 자동 로드 보장(config import의 부수효과). 없으면 토큰 환경변수를 못 읽는다.
from shuttle_system import config  # noqa: F401

MEMO_URL = 'https://kapi.kakao.com/v2/api/talk/memo/default/send'
TOKEN_URL = 'https://kauth.kakao.com/oauth/token'


def _refresh_access_token():
    refresh = os.environ.get('KAKAO_REFRESH_TOKEN')
    rest_key = os.environ.get('KAKAO_REST_API_KEY')
    if not (refresh and rest_key):
        return None
    resp = requests.post(TOKEN_URL, data={
        'grant_type': 'refresh_token', 'client_id': rest_key,
        'refresh_token': refresh}, timeout=8)
    if resp.status_code != 200:
        return None
    return resp.json().get('access_token')


def _text_template(text, link_url=None):
    obj = {'object_type': 'text', 'text': text[:1000],
           'link': {'web_url': link_url or 'https://huggingface.co',
                    'mobile_web_url': link_url or 'https://huggingface.co'}}
    return {'template_object': json.dumps(obj, ensure_ascii=False)}


def send_to_me(text, link_url=None):
    """본인 카톡으로 텍스트 전송. 결과 dict(sent, ...) 반환(예외 안 던짐)."""
    token = os.environ.get('KAKAO_ACCESS_TOKEN')
    try:
        if not token:
            token = _refresh_access_token()
        if not token:
            return {'sent': False, 'reason': 'no_token'}
        headers = {'Authorization': f'Bearer {token}'}
        resp = requests.post(MEMO_URL, headers=headers,
                             data=_text_template(text, link_url), timeout=8)
        if resp.status_code == 401:
            # 만료 → 갱신 후 1회 재시도
            new = _refresh_access_token()
            if new:
                headers = {'Authorization': f'Bearer {new}'}
                resp = requests.post(MEMO_URL, headers=headers,
                                     data=_text_template(text, link_url), timeout=8)
        return {'sent': resp.status_code == 200, 'status': resp.status_code}
    except Exception as e:
        return {'sent': False, 'reason': str(e)}
