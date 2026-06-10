# tests/test_auth.py — Phase 4 认证系统测试

import time
from core.auth import AuthManager


class TestAuthManager:
    def test_disabled_by_default(self):
        auth = AuthManager()
        assert auth.enabled is False
        assert auth.validate("any") is True

    def test_enable_with_token(self):
        auth = AuthManager()
        auth.set_token("secret123")
        assert auth.enabled is True

    def test_login_success(self):
        auth = AuthManager()
        auth.set_token("mytoken")
        session = auth.login("mytoken")
        assert session is not None
        assert len(session) > 20

    def test_login_failure(self):
        auth = AuthManager()
        auth.set_token("correct")
        assert auth.login("wrong") is None
        assert auth.login("") is None

    def test_validate_valid_session(self):
        auth = AuthManager()
        auth.set_token("tok")
        session = auth.login("tok")
        assert auth.validate(session) is True

    def test_validate_invalid_session(self):
        auth = AuthManager()
        auth.set_token("tok")
        assert auth.validate("fake-session-id") is False

    def test_logout(self):
        auth = AuthManager()
        auth.set_token("tok")
        session = auth.login("tok")
        auth.logout(session)
        assert auth.validate(session) is False

    def test_disable_clears_enforcement(self):
        auth = AuthManager()
        auth.set_token("tok")
        auth.set_token("")
        assert auth.enabled is False
        assert auth.validate("anything") is True

    def test_expired_session(self):
        auth = AuthManager()
        auth.set_token("tok")
        session = auth.login("tok")
        # 手动过期
        auth._sessions[session] = time.time() - 1
        assert auth.validate(session) is False


class TestGpuAllocatorIsolated:
    """GPU 分配器独立测试（不依赖 NVML）。"""

    def test_reserve_tracking(self):
        from core.gpu_allocator import GpuAllocator
        alloc = GpuAllocator()
        assert alloc.reserve(0, "svc", "sd", 4)
        assert alloc.get_reserved_memory(0) == 4

    def test_release_workflow(self):
        from core.gpu_allocator import GpuAllocator
        alloc = GpuAllocator()
        alloc.reserve(0, "s1", "sd", 8)
        alloc.reserve(1, "s2", "asr", 4)
        alloc.release(0, "s1")
        assert alloc.get_reserved_memory(0) == 0
        assert alloc.get_reserved_memory(1) == 4
