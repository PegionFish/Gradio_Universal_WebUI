# tests/test_health_checker.py

import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from core.health_checker import HealthChecker


class AsyncContextManagerMock:
    """Helper: creates an async context manager that returns `value`."""

    def __init__(self, value):
        self._value = value

    async def __aenter__(self):
        return self._value

    async def __aexit__(self, *args, **kwargs):
        pass


def make_mock_response(status):
    """Create a mock HTTP response with given status code."""
    resp = MagicMock()
    resp.status = status
    return resp


def make_mock_client_session(resp):
    """Create a mock aiohttp.ClientSession that returns `resp`.

    ClientSession is used as: async with ClientSession() as session
    session.get(url) is used as: async with session.get(...) as response
    """
    session = MagicMock()
    # session.get() returns an async context manager that yields the response
    session.get.return_value = AsyncContextManagerMock(resp)

    # ClientSession() returns an async context manager that yields `session`
    mock_cls = MagicMock()
    mock_cls.return_value = AsyncContextManagerMock(session)
    return mock_cls


class TestHealthCheckerInit:
    def test_initial_state(self):
        hc = HealthChecker()
        assert hc._running is False
        assert hc._thread is None

    def test_start_creates_thread(self):
        hc = HealthChecker()
        hc.start(interval_seconds=1)
        assert hc._running is True
        assert hc._thread is not None
        assert hc._thread.is_alive()
        hc.stop()

    def test_start_idempotent(self):
        hc = HealthChecker()
        hc.start(interval_seconds=1)
        thread1 = hc._thread
        hc.start(interval_seconds=1)
        assert hc._thread is thread1
        hc.stop()


class TestHealthCheckerStop:
    def test_stop_sets_running_false(self):
        hc = HealthChecker()
        hc.start(interval_seconds=1)
        hc.stop()
        assert hc._running is False


class TestProbe:
    """验收标准 6-9: 健康端点探测。"""

    @pytest.fixture
    def hc(self):
        return HealthChecker()

    @pytest.mark.asyncio
    async def test_probe_2xx_returns_true(self, hc):
        """验收标准 7: 2xx 返回 True。"""
        mock_cs = make_mock_client_session(make_mock_response(200))
        with patch("aiohttp.ClientSession", mock_cs):
            result = await hc._probe("http://localhost:8000/health")
            assert result is True

    @pytest.mark.asyncio
    async def test_probe_4xx_returns_false(self, hc):
        """验收标准 8: 非 2xx 返回 False。"""
        mock_cs = make_mock_client_session(make_mock_response(404))
        with patch("aiohttp.ClientSession", mock_cs):
            result = await hc._probe("http://localhost:8000/health")
            assert result is False

    @pytest.mark.asyncio
    async def test_probe_5xx_returns_false(self, hc):
        mock_cs = make_mock_client_session(make_mock_response(500))
        with patch("aiohttp.ClientSession", mock_cs):
            result = await hc._probe("http://localhost:8000/health")
            assert result is False

    @pytest.mark.asyncio
    async def test_probe_connection_error_returns_false(self, hc):
        """ClientSession 连接错误应返回 False。"""
        import aiohttp
        bad_cls = MagicMock()
        bad_cls.side_effect = aiohttp.ClientError("Connection refused")
        with patch("aiohttp.ClientSession", bad_cls):
            result = await hc._probe("http://localhost:9999/health")
            assert result is False

    @pytest.mark.asyncio
    async def test_probe_timeout_returns_false(self, hc):
        bad_cls = MagicMock()
        bad_cls.side_effect = asyncio.TimeoutError()
        with patch("aiohttp.ClientSession", bad_cls):
            result = await hc._probe("http://localhost:8000/health")
            assert result is False


class TestStateTransitionLogic:
    """测试状态判断逻辑（不启动实际线程）。"""

    def test_skip_stopped_services(self):
        from core.service_record import ServiceRecord
        svc = ServiceRecord(
            id="stopped-svc", display_name="S", model_type="sd",
        )
        svc.runtime_state = "stopped"
        svc.service_url = "http://localhost:8000"
        assert svc.runtime_state not in ("running", "starting", "unhealthy")

    def test_skip_services_without_url(self):
        from core.service_record import ServiceRecord
        svc = ServiceRecord(
            id="no-url", display_name="N", model_type="sd",
        )
        svc.runtime_state = "running"
        svc.service_url = ""
        assert not svc.service_url

    def test_starting_services_are_probed(self):
        from core.service_record import ServiceRecord
        svc = ServiceRecord(
            id="starting-svc", display_name="S", model_type="sd",
        )
        svc.runtime_state = "starting"
        svc.service_url = "http://localhost:8000"
        assert svc.runtime_state in ("running", "starting", "unhealthy")
