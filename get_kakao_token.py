"""카카오 인가코드 → 액세스/리프레시 토큰 교환 헬퍼.

사용법:
  1) 아래 인가 URL을 브라우저에서 열어 로그인·동의 → redirect URL의 ?code=XXXX 복사
     https://kauth.kakao.com/oauth/authorize?client_id={REST_KEY}&redirect_uri={REDIRECT}&response_type=code&scope=talk_message
  2) python get_kakao_token.py <REST_KEY> <REDIRECT_URI> <CODE>
  출력된 access_token / refresh_token 을 Secret으로 등록.
"""
import sys
import requests


def main():
    if len(sys.argv) not in (4, 5):
        print('usage: python get_kakao_token.py <REST_API_KEY> <REDIRECT_URI> <CODE> [CLIENT_SECRET]')
        sys.exit(1)
    rest_key, redirect_uri, code = sys.argv[1], sys.argv[2], sys.argv[3]
    payload = {'grant_type': 'authorization_code', 'client_id': rest_key,
               'redirect_uri': redirect_uri, 'code': code}
    if len(sys.argv) == 5:
        payload['client_secret'] = sys.argv[4]
    resp = requests.post('https://kauth.kakao.com/oauth/token', data=payload, timeout=10)
    data = resp.json()
    if resp.status_code != 200:
        print('실패:', data)
        sys.exit(1)
    print('=== 토큰 발급 성공 ===')
    print('KAKAO_ACCESS_TOKEN =', data.get('access_token'))
    print('KAKAO_REFRESH_TOKEN =', data.get('refresh_token'))
    print('(access_token 만료', data.get('expires_in'), '초 · refresh로 자동 갱신됨)')


if __name__ == '__main__':
    main()
