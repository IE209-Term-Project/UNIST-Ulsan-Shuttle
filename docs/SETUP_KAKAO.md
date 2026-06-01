# 카카오톡 '나에게 보내기' 알림 설정

셔틀/카풀 확정·지연 시 **발송자 본인 카톡으로 알림**을 보낸다(PoC).
실서비스 전체 학생 발송은 카카오 알림톡(비즈메시지)로 확장 — 사업자등록·템플릿 심사 필요.

토큰이 없으면 앱은 그대로 동작하고 카톡 발송만 조용히 생략된다.

---

## 1. 카카오 앱 만들기
1. [developers.kakao.com](https://developers.kakao.com) 로그인 → **내 애플리케이션 → 애플리케이션 추가하기**
2. **앱 키**에서 **REST API 키** 복사 → 이게 `KAKAO_REST_API_KEY`
3. **카카오 로그인** 메뉴 → **활성화 ON**
4. **카카오 로그인 → Redirect URI** 등록: `https://localhost` (아무 등록값이면 됨)
5. **카카오 로그인 → 동의항목** → **"카카오톡 메시지 전송"(talk_message)** 사용 설정

## 2. 토큰 발급
**(a) 인가코드 받기** — 아래 URL의 `{REST_KEY}`만 바꿔 브라우저에서 열기:
```
https://kauth.kakao.com/oauth/authorize?client_id={REST_KEY}&redirect_uri=https://localhost&response_type=code&scope=talk_message
```
로그인·동의하면 `https://localhost/?code=XXXXX` 로 이동(페이지는 안 떠도 됨). 주소창의 **code 값** 복사.

**(b) 토큰 교환** — 터미널:
```bash
cd "<프로젝트 폴더>"
.venv/bin/python get_kakao_token.py <REST_KEY> https://localhost <CODE>
```
→ `KAKAO_ACCESS_TOKEN`, `KAKAO_REFRESH_TOKEN` 출력됨.

## 3. 시크릿 등록
**로컬(.env):**
```
KAKAO_ACCESS_TOKEN=...
KAKAO_REFRESH_TOKEN=...
KAKAO_REST_API_KEY=...
```
**HF Space(Secrets):** 위 3개를 학생/관리자 Space에 추가.

> access_token은 ~6시간 만료지만, REFRESH_TOKEN + REST_API_KEY가 있으면 **자동 갱신**된다.

## 4. 확인
앱에서 "🔔 지금 알림 체크"나 예약으로 새 알림이 생기면 본인 카톡 '나와의 채팅'에 메시지가 온다.
토큰 미설정이면 발송만 생략(앱 정상).
