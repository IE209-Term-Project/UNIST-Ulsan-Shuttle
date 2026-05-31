"""예약 저장소. 슬롯 = (direction, ktx_time, travel_date).

- MemoryReservationStore: 테스트/로컬용. 외부 의존 없음.
- SheetsReservationStore: Colab/운영용. gspread 필요.
공통 인터페이스: add / count / names / all_records / clear_slot
"""
from datetime import datetime

HEADER = ['name', 'direction', 'ktx_time', 'travel_date', 'created_at']


def _match(r, direction, ktx_time, travel_date):
    return (str(r.get('direction', '')) == direction
            and str(r.get('ktx_time', '')) == ktx_time
            and str(r.get('travel_date', '')) == travel_date)


class MemoryReservationStore:
    def __init__(self):
        self._rows = []

    def add(self, name, direction, ktx_time, travel_date):
        self._rows.append({'name': (name or '익명').strip(), 'direction': direction,
                           'ktx_time': ktx_time, 'travel_date': travel_date,
                           'created_at': datetime.now().isoformat(timespec='seconds')})

    def all_records(self):
        return list(self._rows)

    def count(self, direction, ktx_time, travel_date):
        return sum(1 for r in self._rows if _match(r, direction, ktx_time, travel_date))

    def names(self, direction, ktx_time, travel_date):
        return [r['name'] for r in self._rows if _match(r, direction, ktx_time, travel_date)]

    def clear_slot(self, direction, ktx_time, travel_date):
        self._rows = [r for r in self._rows
                      if not _match(r, direction, ktx_time, travel_date)]


class SheetsReservationStore:
    """Colab 전용. gspread 핸들을 받아 동일 인터페이스 제공."""
    def __init__(self, sheet_name='UNIST_shuttle_reservations'):
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
        vals = self.ws.get_all_values()
        if not vals or vals[0] != HEADER:
            self.ws.clear()
            self.ws.append_row(HEADER, value_input_option='RAW')
        self.url = sh.url

    def add(self, name, direction, ktx_time, travel_date):
        self.ws.append_row([(name or '익명').strip(), direction, ktx_time, travel_date,
                            datetime.now().isoformat(timespec='seconds')],
                           value_input_option='RAW')

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
        self.ws.append_row(HEADER, value_input_option='RAW')
        for r in kept:
            self.ws.append_row([r.get('name'), r.get('direction'), r.get('ktx_time'),
                                r.get('travel_date'), r.get('created_at')],
                               value_input_option='RAW')
