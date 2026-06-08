"""GitHub Actions에서 호출 — 변경된 파일만 두 HF Space에 sync.

매핑:
  WEB  (jaeeewons/unist-shuttle-web, Docker/FastAPI):
    api.py            → api.py
    web/**            → web/**
    shuttle_system/** → shuttle_system/**
    requirements.txt  → requirements.txt

  ADMIN (jaeeewons/unist-shuttle-admin, Docker/Streamlit):
    legacy/app_admin_streamlit.py → src/streamlit_app.py
    shuttle_system/**             → src/shuttle_system/**
    requirements.txt              → requirements.txt  (openpyxl 보장)

요구 환경변수: HF_TOKEN
"""
import os
import subprocess
import sys
from pathlib import Path

from huggingface_hub import HfApi

TOKEN = os.environ['HF_TOKEN']
api = HfApi(token=TOKEN)

WEB = 'jaeeewons/unist-shuttle-web'
ADMIN = 'jaeeewons/unist-shuttle-admin'


def changed_files() -> list[str]:
    """푸시된 모든 커밋의 diff. 환경변수 FORCE_FULL_SYNC=1이면 전체 파일.

    GitHub Actions의 push 이벤트는 GITHUB_EVENT_BEFORE에 직전 SHA를 제공.
    HEAD~1만 보면 다중 커밋 push에서 첫 커밋의 파일이 누락될 수 있다.
    """
    if os.environ.get('FORCE_FULL_SYNC') == '1':
        print('FORCE_FULL_SYNC=1 — 전체 파일 sync')
        out = subprocess.check_output(['git', 'ls-files'], text=True)
        return [f.strip() for f in out.splitlines() if f.strip()]

    before = os.environ.get('GITHUB_EVENT_BEFORE', '').strip()
    if before and not before.startswith('0' * 10):
        try:
            out = subprocess.check_output(
                ['git', 'diff', '--name-only', before, 'HEAD'], text=True)
            files = [f.strip() for f in out.splitlines() if f.strip()]
            if files:
                return files
        except subprocess.CalledProcessError:
            pass
    try:
        out = subprocess.check_output(
            ['git', 'diff', '--name-only', 'HEAD~1', 'HEAD'], text=True)
        files = [f.strip() for f in out.splitlines() if f.strip()]
        if files:
            return files
    except subprocess.CalledProcessError:
        pass
    out = subprocess.check_output(['git', 'ls-files'], text=True)
    return [f.strip() for f in out.splitlines() if f.strip()]


def match_web(path: str) -> str | None:
    if path == 'api.py':
        return 'api.py'
    if path.startswith('web/'):
        return path
    if path.startswith('shuttle_system/'):
        return path
    if path == 'requirements.txt':
        return 'requirements.txt'
    return None


def match_admin(path: str) -> str | None:
    # admin Space는 자체 requirements.txt(최소 의존성)를 따로 관리한다.
    # 로컬 requirements.txt를 그대로 덮어쓰면 안 됨 — 대신 ensure_admin_openpyxl()로
    # 필요한 패키지만 보장한다.
    if path == 'legacy/app_admin_streamlit.py':
        return 'src/streamlit_app.py'
    if path.startswith('shuttle_system/'):
        return 'src/' + path
    return None


def upload(repo: str, local: str, remote: str, msg: str) -> None:
    if not Path(local).exists():
        # 삭제는 별도 처리(현재 범위 밖)
        print(f'  · skip (missing): {local}')
        return
    api.upload_file(
        path_or_fileobj=local, path_in_repo=remote,
        repo_id=repo, repo_type='space', commit_message=msg)
    print(f'  ✓ {repo}: {remote}')


def ensure_admin_openpyxl() -> None:
    """admin Space의 requirements.txt에 openpyxl 보장."""
    from huggingface_hub import hf_hub_download
    p = hf_hub_download(ADMIN, 'requirements.txt',
                        repo_type='space', token=TOKEN)
    cur = open(p).read()
    if 'openpyxl' in cur:
        return
    new = cur.rstrip() + '\nopenpyxl>=3.1\n'
    api.upload_file(
        path_or_fileobj=new.encode('utf-8'),
        path_in_repo='requirements.txt',
        repo_id=ADMIN, repo_type='space',
        commit_message='auto: ensure openpyxl in admin requirements')
    print(f'  ✓ {ADMIN}: requirements.txt (+openpyxl)')


def main() -> int:
    files = changed_files()
    print(f'Changed files ({len(files)}):')
    for f in files:
        print(f'  · {f}')

    msg = f'auto-deploy from GitHub Actions ({os.environ.get("GITHUB_SHA", "")[:7]})'

    web_uploads = []
    admin_uploads = []
    for f in files:
        w = match_web(f)
        if w:
            web_uploads.append((f, w))
        a = match_admin(f)
        if a:
            admin_uploads.append((f, a))

    if not web_uploads and not admin_uploads:
        print('No relevant changes — nothing to deploy.')
        return 0

    if web_uploads:
        print(f'\n=== {WEB} ({len(web_uploads)} files) ===')
        for local, remote in web_uploads:
            upload(WEB, local, remote, msg)

    if admin_uploads:
        print(f'\n=== {ADMIN} ({len(admin_uploads)} files) ===')
        for local, remote in admin_uploads:
            upload(ADMIN, local, remote, msg)
        # admin requirements.txt는 로컬과 분리 관리 — 다른 패키지 셋
        # 로컬 requirements.txt 변경이 push되어도 admin에는 openpyxl만 보장
        ensure_admin_openpyxl()

    print('\nDone.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
