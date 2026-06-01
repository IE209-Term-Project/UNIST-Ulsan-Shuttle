"""환경 차이 흡수: Colab Secrets ↔ 로컬 os.environ. 키 원문은 절대 코드에 두지 않는다.

로컬에서 .env 파일이 있으면 자동 로드한다(python-dotenv 설치 시). HF/Colab은 영향 없음.
"""
import os

try:
    from dotenv import load_dotenv
    load_dotenv()  # 현재 폴더의 .env를 os.environ으로 (이미 설정된 값은 덮어쓰지 않음)
except Exception:
    pass


def get_secret(name: str):
    """Colab이면 userdata, 아니면 환경변수에서 시크릿을 읽는다."""
    try:
        from google.colab import userdata  # Colab에서만 존재
        val = userdata.get(name)
        if val:
            return val
    except Exception:
        pass
    return os.environ.get(name)
