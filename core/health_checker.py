# core/health_checker.py — 健康检查器，定时探测服务健康状态

import asyncio
import threading
import logging

import aiohttp

logger = logging.getLogger(__name__)


class HealthChecker:
    """HTTP 健康检查器，定时探测服务健康状况并更新运行状态。

    在后台线程中运行独立的 asyncio 事件循环。
    探测间隔和超时均可配置。
    """

    def __init__(self):
        self._running = False
        self._thread: threading.Thread | None = None

    # ── 生命周期 ──

    def start(self, interval_seconds: int = 10):
        """启动健康检查线程。

        Args:
            interval_seconds: 探测间隔（秒）
        """
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run_loop,
            args=(interval_seconds,),
            daemon=True,
            name="health-checker",
        )
        self._thread.start()
        logger.info("HealthChecker 已启动 (间隔 %ds)", interval_seconds)

    def stop(self):
        """停止健康检查线程。"""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        logger.info("HealthChecker 已停止")

    # ── 主循环 ──

    def _run_loop(self, interval: int):
        """在后台线程中运行，使用独立的 asyncio 事件循环。"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        from core import registry

        while self._running:
            services = registry.list_services()

            for svc in services:
                # 只探测以下状态的服务
                if svc.runtime_state not in ("running", "starting", "unhealthy"):
                    continue
                if not svc.service_url or not svc.health_endpoint:
                    continue

                # 构建完整健康检查 URL
                url = (
                    svc.service_url.rstrip("/")
                    + "/"
                    + svc.health_endpoint.lstrip("/")
                )

                try:
                    healthy = loop.run_until_complete(self._probe(url))
                    if healthy:
                        if svc.runtime_state != "running":
                            registry.set_runtime_state(svc.id, "running")
                    else:
                        if svc.runtime_state != "unhealthy":
                            registry.set_runtime_state(svc.id, "unhealthy")
                except Exception as e:
                    logger.debug("探测 %s 异常: %s", svc.id, e)
                    if svc.runtime_state != "unhealthy":
                        registry.set_runtime_state(svc.id, "unhealthy")

            # 等待指定间隔，但可被 stop() 中断
            for _ in range(interval):
                if not self._running:
                    break
                if threading.Event().wait(1):
                    break

        loop.close()
        logger.info("HealthChecker 事件循环已关闭")

    async def _probe(self, url: str) -> bool:
        """探测健康端点，5 秒超时，返回是否健康。

        Args:
            url: 完整的健康检查 URL

        Returns:
            HTTP 2xx → True，否则 False
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=5)
                ) as resp:
                    return 200 <= resp.status < 300
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return False
