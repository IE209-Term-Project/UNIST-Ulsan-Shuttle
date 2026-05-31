"""환경 차이 흡수: Colab Secrets ↔ 로컬 os.environ. 키 원문은 절대 코드에 두지 않는다."""
import os


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
