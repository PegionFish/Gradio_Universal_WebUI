# adapters/base.py — 模型适配器抽象基类，定义适配器接口

from abc import ABC, abstractmethod
from typing import Optional


class BaseModelAdapter(ABC):
    """模型适配器基类。所有模型适配器必须实现此接口。"""

    @abstractmethod
    def model_type(self) -> str:
        """返回唯一标识符，与 ServiceRegistry 中的 model_type 匹配。"""
        ...

    async def validate(self, payload: dict) -> list[str]:
        """校验请求负载。

        返回校验错误列表，空列表表示校验通过。
        基类默认实现不校验任何字段。
        """
        return []

    @abstractmethod
    async def submit(
        self,
        service_url: str,
        payload: dict,
        target_gpu: Optional[list[int]] = None,
    ) -> str:
        """提交任务到模型服务。

        参数:
            service_url: 服务的基础 URL（来自 ServiceRegistry）
            payload: 请求参数（模型特定）
            target_gpu: 目标 GPU 索引列表，或 None

        返回:
            服务侧的任务引用 ID（用于 poll_status）

        可能抛出:
            NotImplementedError: 占位适配器
            ConnectionError: 服务不可达
            ValueError: 无效参数
        """
        ...

    async def poll_status(self, service_url: str, task_ref: str) -> dict:
        """查询任务执行状态。

        第一阶段无实际调用者（任务状态通过 SQLite 查询）。
        为第二阶段预留的接口。

        返回:
            {"status": "running" | "completed" | "failed",
             "result": {...} | None,
             "error": str | None}
        """
        return {"status": "unknown", "result": None, "error": "poll_status 未实现"}
