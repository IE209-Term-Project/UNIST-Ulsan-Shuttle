"""예약 저장소. 슬롯 = (direction, ktx_time, travel_date).

- MemoryReservationStore     : 테스트/로컬용. 외부 의존 없음.
- SheetsReservationStore     : Colab용. google.colab.auth(팝업)로 인증.
- ServiceAccountSheetsStore  : HF Spaces 등 Colab 밖 운영용. 서비스 계정 JSON으로 인증.

make_store()가 환경을 감지해 적절한 저장소를 돌려준다.
공통 인터페이스: add / count / names / all_records / clear_slot
"""
import json
import os
from datetime import datetime

# .env 자동 로드를 보장한다(config import의 부수효과). 이게 없으면 make_store가
# 환경변수를 못 읽어 메모리 저장소로 잘못 떨어진다.
from shuttle_system import config  # noqa: F401

HEADER = ['name', 'direction', 'ktx_time', 'travel_date', 'created_at']
NOTIF_HEADER = ['created_at', 'type', 'direction', 'ktx_time', 'travel_date', 'message']
NOTIF_SHEET = 'notifications'

# Google Sheets API 권한 범위 (시트 읽기/쓰기 + 이름으로 열기)
GSPREAD_SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive',
]
DEFAULT_SHEET_NAME = 'UNIST_shuttle_reservations'


def _match(r, direction, ktx_time, travel_date):
    return (str(r.get('direction', '')) == direction
            and str(r.get('ktx_time', '')) == ktx_time
            and str(r.get('travel_date', '')) == travel_date)


class MemoryReservationStore:
    def __init__(self):
        self._rows = []
        self._notifs = []

    def add_notification(self, rec):
        r = {'created_at': datetime.now().isoformat(timespec='seconds'), **rec}
        self._notifs.append(r)
        return r

    def all_notifications(self):
        return list(self._notifs)

    def add(self, name, direction, ktx_time, travel_date):
        self._rows.append({'name': (name or '익명').strip(), 'direction': direction,
                           'ktx_time': ktx_time, 'travel_date': travel_date,
                           'created_at': datetime.now().isoformat(timespec='seconds')})

    def add_many(self, rows):
        """rows: (name, direction, ktx_time, travel_date) 튜플 리스트."""
        for name, direction, ktx_time, travel_date in rows:
            self.add(name, direction, ktx_time, travel_date)

    def all_records(self):
        return list(self._rows)

    def count(self, direction, ktx_time, travel_date):
        return sum(1 for r in self._rows if _match(r, direction, ktx_time, travel_date))

    def names(self, direction, ktx_time, travel_date):
        return [r['name'] for r in self._rows if _match(r, direction, ktx_time, travel_date)]

    def clear_slot(self, direction, ktx_time, travel_date):
        self._rows = [r for r in self._rows
                      if not _match(r, direction, ktx_time, travel_date)]


class _SheetsStoreBase:
    """gspread 워크시트(self.ws)에 대한 공통 CRUD. 인증/시트 열기는 서브클래스가 담당."""

    def _ensure_header(self):
        vals = self.ws.get_all_values()
        if not vals or vals[0] != HEADER:
            self.ws.clear()
            self.ws.append_row(HEADER, value_input_option='RAW')

    def _ensure_notif_ws(self, sh):
        """notifications 워크시트 확보(없으면 생성)."""
        import gspread
        try:
            self.notif_ws = sh.worksheet(NOTIF_SHEET)
        except gspread.WorksheetNotFound:
            self.notif_ws = sh.add_worksheet(NOTIF_SHEET, rows=1000, cols=len(NOTIF_HEADER))
        vals = self.notif_ws.get_all_values()
        if not vals or vals[0] != NOTIF_HEADER:
            self.notif_ws.clear()
            self.notif_ws.append_row(NOTIF_HEADER, value_input_option='RAW')

    def add_notification(self, rec):
        r = {'created_at': datetime.now().isoformat(timespec='seconds'), **rec}
        self.notif_ws.append_row([r.get(k, '') for k in NOTIF_HEADER],
                                 value_input_option='RAW')
        return r

    def all_notifications(self):
        return self.notif_ws.get_all_records()

    def add(self, name, direction, ktx_time, travel_date):
        self.ws.append_row([(name or '익명').strip(), direction, ktx_time, travel_date,
                            datetime.now().isoformat(timespec='seconds')],
                           value_input_option='RAW')

    def add_many(self, rows):
        """여러 예약을 단일 API 호출로 추가(분당 쓰기 한도 회피).

        rows: (name, direction, ktx_time, travel_date) 튜플 리스트.
        """
        now = datetime.now().isoformat(timespec='seconds')
        payload = [[(name or '익명').strip(), direction, ktx_time, travel_date, now]
                   for name, direction, ktx_time, travel_date in rows]
        if payload:
            self.ws.append_rows(payload, value_input_option='RAW')

    def all_records(self):
        return self.ws.get_all_records()

    def count(self, direction, ktx_time, travel_date):
        return sum(1 for r in self.all_records()
                   if _match(r, direction, ktx_time, travel_date))

    def names(self, direction, ktx_time, travel_date):
        return [str(r.get('name', '')) for r in self.all_records()
                if _match(r, direction, ktx_time, travel_date)]

    def clear_slot(self, direction, ktx_time, travel_date):
        kept = [r for r in self.all_records()
                if not _match(r, direction, ktx_time, travel_date)]
        self.ws.clear()
        rows = [HEADER] + [[r.get('name'), r.get('direction'), r.get('ktx_time'),
                            r.get('travel_date'), r.get('created_at')] for r in kept]
        self.ws.append_rows(rows, value_input_option='RAW')  # 단일 호출


class SheetsReservationStore(_SheetsStoreBase):
    """Colab 전용. 본인 구글 계정 인증 팝업을 사용."""
    def __init__(self, sheet_name=DEFAULT_SHEET_NAME):
        from google.colab import auth
        auth.authenticate_user()
        import gspread
        from google.auth import default
        creds, _ = default()
        gc = gspread.authorize(creds)
        try:
            sh = gc.open(sheet_name)
        except gspread.SpreadsheetNotFound:
            sh = gc.create(sheet_name)
        self.ws = sh.sheet1
        self.url = sh.url
        self._ensure_header()
        self._ensure_notif_ws(sh)


class ServiceAccountSheetsStore(_SheetsStoreBase):
    """Colab 밖(HF Spaces 등) 운영용. 서비스 계정 JSON으로 인증.

    인증: 환경변수 GOOGLE_SERVICE_ACCOUNT_JSON 에 서비스 계정 키(JSON 문자열).
    시트 지정: 환경변수 RESERVATION_SHEET_ID(권장) 또는 sheet_name.
    ※ 대상 시트를 서비스 계정 이메일에 '편집자'로 미리 공유해 두어야 한다.
    """
    def __init__(self, sheet_id=None, sheet_name=DEFAULT_SHEET_NAME,
                 service_account_json=None):
        import gspread
        from google.oauth2.service_account import Credentials

        raw = service_account_json or os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON')
        if raw:
            info = json.loads(raw)
        else:
            # 로컬 편의: JSON 문자열 대신 파일 경로로 줄 수도 있다
            path = os.environ.get('GOOGLE_SERVICE_ACCOUNT_FILE')
            if not path:
                raise RuntimeError(
                    'GOOGLE_SERVICE_ACCOUNT_JSON(또는 GOOGLE_SERVICE_ACCOUNT_FILE)'
                    ' 환경변수가 없습니다. 서비스 계정 키를 지정하세요.')
            with open(os.path.expanduser(path), encoding='utf-8') as f:
                info = json.load(f)
        creds = Credentials.from_service_account_info(info, scopes=GSPREAD_SCOPES)
        gc = gspread.authorize(creds)

        sheet_id = sheet_id or os.environ.get('RESERVATION_SHEET_ID')
        if sheet_id:
            sh = gc.open_by_key(sheet_id)
        else:
            try:
                sh = gc.open(sheet_name)
            except gspread.SpreadsheetNotFound as e:
                raise RuntimeError(
                    f"'{sheet_name}' 시트를 찾을 수 없습니다. 시트를 만들고 서비스 계정 "
                    f"이메일에 '편집자'로 공유한 뒤, RESERVATION_SHEET_ID 또는 같은 "
                    f"이름을 지정하세요.") from e
        self.ws = sh.sheet1
        self.url = sh.url
        self._ensure_header()
        self._ensure_notif_ws(sh)


def make_store():
    """환경을 감지해 적절한 예약 저장소를 반환한다.

    1) 서비스 계정 키(JSON 또는 FILE) 있으면 → ServiceAccountSheetsStore (HF/로컬 운영)
    2) Colab 환경이면                       → SheetsReservationStore (인증 팝업)
    3) 그 외(테스트)                        → MemoryReservationStore (임시)
    """
    if (os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON')
            or os.environ.get('GOOGLE_SERVICE_ACCOUNT_FILE')):
        return ServiceAccountSheetsStore()
    try:
        import google.colab  # noqa: F401
        return SheetsReservationStore()
    except ImportError:
        return MemoryReservationStore()
