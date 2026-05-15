"""
测试环境配置：在任何 app 导入之前设置环境变量与临时目录。
运行方式：在 neizhang-server 目录下执行  pytest
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

# 保证可从任意工作目录收集用例时找到 app 包
_SERVER_ROOT = Path(__file__).resolve().parent.parent
if str(_SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVER_ROOT))

# --- 测试专用环境（须在 import app 之前）---
_test_db_fd, _test_db_path = tempfile.mkstemp(prefix="neizhang_test_", suffix=".db")
os.close(_test_db_fd)
_test_db_path_posix = Path(_test_db_path).resolve().as_posix()
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_test_db_path_posix}"
os.environ["JWT_SECRET"] = "test-jwt-secret-key-must-be-long-enough!!"
os.environ["DEEPSEEK_API_KEY"] = "test-dummy-key-not-used-when-mocked"
os.environ["UPLOAD_DIR"] = str(_SERVER_ROOT / "tests" / "_uploads_tmp")
os.environ.setdefault("CHAT_TRACE", "false")

from starlette.testclient import TestClient

from app.main import app


def pytest_sessionfinish(session, exitstatus):
    for suffix in ("", "-wal", "-shm"):
        p = _test_db_path + suffix if suffix else _test_db_path
        try:
            os.unlink(p)
        except OSError:
            pass
    import shutil

    upload_root = Path(os.environ["UPLOAD_DIR"])
    if upload_root.exists():
        shutil.rmtree(upload_root, ignore_errors=True)


@pytest.fixture
def client() -> TestClient:
    """同步 TestClient，自动跑 FastAPI lifespan（建表等）。"""
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
