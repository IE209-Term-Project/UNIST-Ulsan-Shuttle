# 배포 가이드 — 학생 앱(Gradio) + 관리자 대시보드(Streamlit)

두 앱은 **같은 Google Sheet**(서비스 계정)를 공유한다. 학생이 예약하면 시트에 쌓이고,
관리자 대시보드가 그 시트를 읽어 운영 리포트를 만든다.

- **학생 앱** = Gradio → HF Spaces에 호스팅 (학생들이 URL로 접속)
- **관리자 대시보드** = Streamlit → **방법1) 두 번째 HF Space** 또는 **방법2) 발표 때 내 노트북에서 로컬 실행**

---

## A. Google Sheet + 서비스 계정 — ✅ 완료함
손에 있어야 할 것: ① **시트 ID**, ② **JSON 키 내용**, ③ 시트를 서비스 계정 이메일에 **편집자 공유**.

---

## B. 학생 앱 → HF Gradio Space

### B-1. Space 생성
[huggingface.co/new-space](https://huggingface.co/new-space) → name `unist-shuttle` → **SDK: Gradio** → CPU basic → Create.

### B-2. 파일 업로드 (Files → Add file → Upload files)
```
app.py
requirements.txt
shuttle_system/   ← 폴더 통째로
```
(폴더 업로드가 안 되면 git 방식 — 아래 부록)

### B-3. Secrets 4개 (Settings → Variables and secrets → New secret)
| Name | Value |
|---|---|
| `OPENAI_API_KEY` | OpenAI 키 |
| `ULSAN_BIS_API_KEY` | 울산 BIS 키 |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | JSON 파일 내용 전체 |
| `RESERVATION_SHEET_ID` | 시트 ID |

→ Running 되면 학생용 URL 완성. 이 URL을 학생들에게 배포.

---

## C. 관리자 대시보드 (Streamlit) — 두 방법 중 택1

### 방법 1) 두 번째 HF Space (상시 접속 원할 때)
1. 새 Space 생성 → name `unist-shuttle-admin` → **SDK: Streamlit** → Create
2. 업로드: `app_admin_streamlit.py`, `requirements.txt`, `shuttle_system/`
3. **진입점 지정:** 이 Space의 `README.md`를 열어 상단 YAML에 한 줄 추가/수정:
   ```yaml
   ---
   sdk: streamlit
   app_file: app_admin_streamlit.py
   ---
   ```
4. Secrets 3개: `OPENAI_API_KEY`, `GOOGLE_SERVICE_ACCOUNT_JSON`, `RESERVATION_SHEET_ID`
   (BIS 키는 관리자 앱엔 불필요)
   → **시트 ID는 학생 Space와 동일하게** 넣어야 데이터가 공유됨

### 방법 2) 발표 때 내 노트북에서 로컬 실행 (더 간단·추천)
관리자 대시보드는 **발표자(나)만 보면 되므로** 굳이 호스팅하지 않고 로컬에서 띄워도 된다.
```bash
cd "<프로젝트 폴더>"
export OPENAI_API_KEY="..."                  # 키 입력
export GOOGLE_SERVICE_ACCOUNT_JSON="$(cat ~/Downloads/서비스계정키.json)"
export RESERVATION_SHEET_ID="시트ID"
.venv/bin/streamlit run app_admin_streamlit.py
```
→ 브라우저에 `localhost:8501` 대시보드가 뜨고, 학생 Space와 **같은 시트**를 읽어 실시간 집계.

> 키를 매번 export하기 번거로우면 `.env` 파일을 쓰되, **절대 git에 올리지 말 것**(`.gitignore`에 `.env` 추가).

---

## D. 확인
1. 학생 URL에서 예약 입력 (슬롯에 맞는 **요일/날짜**로 — 예: 금요일 날짜 13:58)
2. 관리자 대시보드에서 KPI·차트·표·LLM 브리핑 확인
3. Google Sheet에 행이 쌓이면 성공 ✅
4. 오류 시: HF는 **Logs** 탭, 로컬은 터미널 메시지 확인 (대개 시트 공유 누락/Secret 오타)

---

## 부록: git으로 업로드
```bash
git clone https://huggingface.co/spaces/<HF아이디>/<space이름>
cd <space이름>
# 필요한 파일 복사 후
git add -A && git commit -m "deploy" && git push   # 사용자명 + HF 토큰 입력
```

## 참고: 저장소 자동 선택 (`make_store`)
- 서비스 계정 JSON 있음(HF/로컬 export) → Google Sheet 영구 저장
- Colab → 인증 팝업 방식
- 그 외 → 메모리(임시)
