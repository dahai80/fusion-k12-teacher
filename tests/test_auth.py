"""auth 模块测试 — 注册/登录/token 校验/登出。"""

from __future__ import annotations

import pytest

from fusion_k12_teacher.auth.password import hash_password, verify_password
from fusion_k12_teacher.auth.service import AuthError, AuthService
from fusion_k12_teacher.repository.sqlite_repo import SQLiteRepository


@pytest.fixture
def auth(tmp_path):
    repo = SQLiteRepository(str(tmp_path / "auth.db"))
    yield AuthService(repo)
    repo.close()


class TestPassword:
    def test_hash_and_verify(self):
        h = hash_password("secret123")
        assert h.startswith("pbkdf2_sha256$")
        assert verify_password("secret123", h) is True

    def test_wrong_password(self):
        h = hash_password("secret123")
        assert verify_password("wrong", h) is False

    def test_unique_salts(self):
        assert hash_password("x") != hash_password("x")


class TestRegister:
    def test_register_success(self, auth):
        t = auth.register("teacher1", "pass123", name="张老师")
        assert t.id.startswith("t_")
        assert t.username == "teacher1"
        assert t.name == "张老师"

    def test_duplicate_username(self, auth):
        auth.register("teacher1", "pass123")
        with pytest.raises(AuthError, match="已存在"):
            auth.register("teacher1", "other456")

    def test_short_password(self, auth):
        with pytest.raises(AuthError, match="至少 6 位"):
            auth.register("teacher2", "123")


class TestLogin:
    def test_login_success(self, auth):
        auth.register("teacher1", "pass123")
        token, teacher = auth.login("teacher1", "pass123")
        assert token
        assert teacher.username == "teacher1"
        assert auth.verify_token(token) == teacher.id

    def test_login_wrong_password(self, auth):
        auth.register("teacher1", "pass123")
        with pytest.raises(AuthError, match="错误"):
            auth.login("teacher1", "wrong")

    def test_login_unknown_user(self, auth):
        with pytest.raises(AuthError, match="错误"):
            auth.login("ghost", "pass123")


class TestToken:
    def test_verify_expired(self, auth):
        auth.register("t1", "pass123")
        token, _teacher = auth.login("t1", "pass123")
        # 篡改 expiry 为过去时间
        import base64
        import hashlib
        import hmac

        raw = base64.urlsafe_b64decode(token.encode()).decode()
        tid, _exp, _sig = raw.split("|")
        payload = f"{tid}|1"
        from fusion_k12_teacher.auth.service import _auth_secret
        new_sig = hmac.new(_auth_secret(), payload.encode(), hashlib.sha256).hexdigest()
        tampered = base64.urlsafe_b64encode(f"{payload}|{new_sig}".encode()).decode()
        assert auth.verify_token(tampered) is None

    def test_verify_bad_sig(self, auth):
        auth.register("t1", "pass123")
        token, _ = auth.login("t1", "pass123")
        bad = token[:-4] + "AAAA"
        assert auth.verify_token(bad) is None

    def test_verify_empty(self, auth):
        assert auth.verify_token("") is None

    def test_logout_invalidates(self, auth):
        auth.register("t1", "pass123")
        token, teacher = auth.login("t1", "pass123")
        assert auth.verify_token(token) == teacher.id
        auth.logout(token)
        assert auth.verify_token(token) is None
