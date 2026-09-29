from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import time
import uuid

from ..repository.base import Repository
from .models import TeacherProfile
from .password import hash_password, verify_password

logger = logging.getLogger(__name__)

_TOKEN_TTL = 7 * 24 * 3600  # 7 天


def _auth_secret() -> bytes:
    raw = os.environ.get("FUSION_K12_AUTH_SECRET", "")
    if not raw:
        # 未配独立密钥: 从 api key 派生 (同进程一致, 重启稳定)。
        raw = "fusion-k12-auth::" + os.environ.get("FUSION_K12_API_KEY", "fallback")
    return hashlib.sha256(raw.encode("utf-8")).digest()


class AuthError(Exception):
    pass


class AuthService:
    """教师身份服务 — 注册/登录/令牌验证。

    token = base64(teacher_id|expiry|hmac) — HMAC 校验防伪造, expiry 防过期。
    session 行同步落 sessions 表 (可主动注销/可重启校验)。
    """

    def __init__(self, repo: Repository):
        self._repo = repo

    def register(
        self,
        username: str,
        password: str,
        name: str = "",
        school: str = "",
        region: str = "",
        default_edition: str = "renjiao",
    ) -> TeacherProfile:
        username = (username or "").strip()
        if not username or not password:
            raise AuthError("用户名和密码不能为空")
        if len(password) < 6:
            raise AuthError("密码至少 6 位")
        existing = self._repo.get_teacher_by_username(username)
        if existing:
            raise AuthError("用户名已存在")
        teacher_id = "t_" + uuid.uuid4().hex[:12]
        now = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        record = {
            "id": teacher_id,
            "username": username,
            "name": name,
            "school": school,
            "region": region,
            "default_edition": default_edition,
            "password_hash": hash_password(password),
            "created_at": now,
        }
        self._repo.create_teacher(record)
        logger.info("教师注册成功: id=%s username=%s", teacher_id, username)
        return TeacherProfile(
            id=teacher_id, username=username, name=name, school=school,
            region=region, default_edition=default_edition, created_at=now,
        )

    def login(self, username: str, password: str) -> tuple[str, TeacherProfile]:
        username = (username or "").strip()
        record = self._repo.get_teacher_by_username(username)
        if not record or not verify_password(password, record.get("password_hash", "")):
            raise AuthError("用户名或密码错误")
        teacher = TeacherProfile.from_dict(record)
        token = self._make_token(teacher.id)
        expires_at = time.time() + _TOKEN_TTL
        self._repo.create_session(token, teacher.id, expires_at)
        logger.info("教师登录: id=%s username=%s", teacher.id, username)
        return token, teacher

    def _make_token(self, teacher_id: str) -> str:
        expiry = int(time.time()) + _TOKEN_TTL
        payload = f"{teacher_id}|{expiry}"
        sig = hmac.new(_auth_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
        raw = f"{payload}|{sig}"
        return base64.urlsafe_b64encode(raw.encode("utf-8")).decode()

    def verify_token(self, token: str) -> str | None:
        if not token:
            return None
        try:
            raw = base64.urlsafe_b64decode(token.encode("utf-8")).decode("utf-8")
            parts = raw.split("|")
            if len(parts) != 3:
                return None
            teacher_id, expiry_str, sig = parts
            payload = f"{teacher_id}|{expiry_str}"
            expected = hmac.new(_auth_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(sig, expected):
                logger.warning("token HMAC 校验失败: teacher=%s", teacher_id)
                return None
            if int(expiry_str) < time.time():
                return None
            session = self._repo.get_session(token)
            if not session:
                return None
            return teacher_id
        except Exception as e:
            logger.warning("token 解析失败: %s", e)
            return None

    def get_teacher(self, teacher_id: str) -> TeacherProfile | None:
        record = self._repo.get_teacher(teacher_id)
        if not record:
            return None
        return TeacherProfile.from_dict(record)

    def logout(self, token: str) -> None:
        if token:
            self._repo.delete_session(token)
