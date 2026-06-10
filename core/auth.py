# core/auth.py — 简单令牌认证系统（LAN 部署用）

import hashlib
import secrets
import time
import threading
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# 会话过期时间（默认 24 小时）
SESSION_TTL_SECONDS = 86400


class AuthManager:
    """简单令牌认证管理器。

    用于 LAN 部署场景，提供基础的访问控制。
    不适用于公网暴露——公网请使用反向代理 + OAuth2。

    用法:
        auth = AuthManager()
        auth.set_token("my-secret-token")

        # 验证
        if auth.validate(token_str):
            # 放行
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._enabled: bool = False
        self._master_token: str = ""
        self._sessions: dict[str, float] = {}  # session_id → expiry_timestamp
        self._cleanup_counter: int = 0

    # ── 配置 ──

    @property
    def enabled(self) -> bool:
        """是否启用认证。"""
        return self._enabled

    def set_token(self, token: str):
        """设置主令牌并启用认证。

        传入空字符串或 None 可禁用认证。
        """
        token = (token or "").strip()
        if not token:
            self._enabled = False
            self._master_token = ""
            logger.info("认证已禁用")
            return

        self._master_token = token
        self._enabled = True
        logger.info("认证已启用 (token=%s...)", token[:6])

    # ── 登录/注销 ──

    def login(self, token_attempt: str) -> Optional[str]:
        """尝试登录。

        Returns:
            成功时返回 session_id，失败时返回 None。
        """
        if not self._enabled:
            return "_no_auth_session"

        if not token_attempt or token_attempt != self._master_token:
            logger.warning("认证失败: 令牌不匹配")
            return None

        session_id = secrets.token_urlsafe(32)
        expiry = time.time() + SESSION_TTL_SECONDS

        with self._lock:
            self._sessions[session_id] = expiry
            # 定期清理过期会话
            self._cleanup_counter += 1
            if self._cleanup_counter > 100:
                self._cleanup_expired()
                self._cleanup_counter = 0

        logger.info("用户登录成功 (session=%s...)", session_id[:12])
        return session_id

    def logout(self, session_id: str):
        """注销会话。"""
        with self._lock:
            self._sessions.pop(session_id, None)

    # ── 验证 ──

    def validate(self, session_id: str) -> bool:
        """验证会话是否有效。

        Returns:
            True 如果认证已禁用、或会话有效。
        """
        if not self._enabled:
            return True

        if not session_id:
            return False

        with self._lock:
            expiry = self._sessions.get(session_id)
            if expiry is None:
                return False
            if time.time() > expiry:
                self._sessions.pop(session_id, None)
                return False
            return True

    # ── 内部 ──

    def _cleanup_expired(self):
        """清理过期会话。"""
        now = time.time()
        expired = [
            sid for sid, exp in self._sessions.items()
            if now > exp
        ]
        for sid in expired:
            self._sessions.pop(sid, None)
        if expired:
            logger.debug("清理 %d 个过期会话", len(expired))


# ── 全局单例 ──
auth: Optional[AuthManager] = None


def get_auth() -> AuthManager:
    """获取全局 AuthManager 实例。"""
    global auth
    if auth is None:
        auth = AuthManager()
    return auth


def setup_auth(token: str = "") -> AuthManager:
    """初始化全局认证管理器。

    Args:
        token: 主令牌（空字符串 = 禁用认证）
    """
    global auth
    auth = AuthManager()
    if token:
        auth.set_token(token)
    return auth
