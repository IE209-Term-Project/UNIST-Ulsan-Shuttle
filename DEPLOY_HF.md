# Hugging Face Spaces 배포 가이드 (서비스 계정 Google Sheets)

이 문서대로 하면 `app.py`(학생용+관리자용 두 탭)를 **상시 켜진 고정 URL**로 띄우고,
예약을 **당신 소유의 Google Sheet에 영구 저장**할 수 있다.

준비물: Google 계정, Hugging Face 계정(무료), OpenAI API 키, 울산 BIS API 키.

전체 흐름: **A. 구글 시트+서비스 계정 → B. HF Space 생성·업로드 → C. Secrets 등록 → D. 확인**

---

## A. Google Sheet + 서비스 계정 (한 번만)

### A-1. 빈 시트 만들기
1. [sheets.google.com](https://sheets.google.com) → 빈 스프레드시트 생성
2. 이름을 `UNIST_shuttle_reservations` 로 변경
3. 주소창 URL에서 **시트 ID**를 복사해 둔다 (아래 굵은 부분):
   `https://docs.google.com/spreadsheets/d/`**`1AbCdEf...XyZ`**`/edit`

### A-2. Google Cloud 프로젝트 + API 켜기
1. [console.cloud.google.com](https://console.cloud.google.com) 접속 → 상단에서 **새 프로젝트** 생성(이름 아무거나)
2. 검색창에 **"Google Sheets API"** → 들어가서 **사용(Enable)**
3. 검색창에 **"Google Drive API"** → 들어가서 **사용(Enable)**

### A-3. 서비스 계정 + JSON 키
1. 좌측 메뉴 **IAM 및 관리자 → 서비스 계정 → 서비스 계정 만들기**
2. 이름 아무거나(예: `shuttle-bot`) 입력 → **완료**
3. 만들어진 서비스 계정 클릭 → **키 탭 → 키 추가 → 새 키 만들기 → JSON** 선택
4. `xxxxx.json` 파일이 다운로드된다. **이 파일 내용 전체가 곧 Secret 값**이다.
5. 그 서비스 계정의 **이메일**(예: `shuttle-bot@프로젝트.iam.gserviceaccount.com`)을 복사

### A-4. 시트를 서비스 계정에 공유 ⚠️ 빠지기 쉬움
1. A-1에서 만든 Google Sheet로 돌아가 우상단 **공유** 클릭
2. A-3에서 복사한 **서비스 계정 이메일**을 붙여넣고 권한을 **편집자**로 → 보내기

> 이걸 안 하면 앱이 "시트를 찾을 수 없음" 오류를 낸다.

---

## B. Hugging Face Space 생성 + 파일 업로드

### B-1. Space 만들기
1. [huggingface.co/new-space](https://huggingface.co/new-space)
2. **Space name** 입력(예: `unist-shuttle`), **SDK = Gradio**, 가시성은 Public/Private 자유
3. **Create Space**

### B-2. 파일 업로드
Space의 **Files** 탭 → **Add file → Upload files** 로 다음을 올린다(폴더 구조 유지):
```
app.py
requirements.txt
shuttle_system/        ← 폴더 통째로 (core/, agents/ 포함)
```
> 웹 업로드가 폴더를 어려워하면, 로컬에서 `git clone` 한 Space 폴더에 파일을 복사하고 `git push` 하는 방법이 더 확실하다(아래 B-3).

### B-3. (대안) git으로 올리기
```bash
git clone https://huggingface.co/spaces/<HF아이디>/unist-shuttle
cd unist-shuttle
# 이 프로젝트의 app.py, requirements.txt, shuttle_system/ 를 복사해 넣고
git add app.py requirements.txt shuttle_system
git commit -m "deploy shuttle agent"
git push
```

---

## C. Space Secrets 등록

Space의 **Settings → Variables and secrets → New secret** 에서 4개 추가:

| 이름 | 값 |
|---|---|
| `OPENAI_API_KEY` | OpenAI 키 |
| `ULSAN_BIS_API_KEY` | 울산 BIS 키 |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | A-3에서 받은 **JSON 파일 내용 전체**를 그대로 붙여넣기 |
| `RESERVATION_SHEET_ID` | A-1에서 복사한 **시트 ID** |

> Secret은 코드/깃에 절대 넣지 말 것. 반드시 이 Secrets 화면에만 입력한다.

저장하면 Space가 자동으로 다시 빌드된다.

---

## D. 확인
1. Space 상단이 **Running** 이 되면 앱 화면이 뜬다 (고정 URL: `https://huggingface.co/spaces/<HF아이디>/unist-shuttle`)
2. **🎓 학생용** 탭에서 예약 → **🛠 관리자용** 탭에서 "리포트 생성" 클릭
3. A-1의 Google Sheet를 열어 예약 행이 쌓였는지 확인 → 영구 저장 확인 ✅

문제 시 Space의 **Logs** 탭에서 오류 메시지를 보면 원인이 나온다(대개 A-4 공유 누락 또는 Secret 오타).

---

## 참고: 환경별 저장소 자동 선택
`make_store()`가 환경을 감지한다.
- HF Spaces(서비스 계정 JSON 있음) → Google Sheet 영구 저장
- Colab → 기존 인증 팝업 방식(`demo.ipynb`)
- 로컬/테스트 → 메모리(임시)

→ 같은 코드가 세 환경에서 모두 동작한다.
