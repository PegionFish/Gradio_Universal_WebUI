# core/service_record.py — 服务记录数据类

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ServiceRecord:
    """服务配置和状态的数据类"""

    # 核心标识
    id: str
    display_name: str
    model_type: str  # "stable-diffusion", "qwen3-asr", "whisperx", "fastwhisper"

    # 配置
    enabled: bool = False
    service_url: str = ""
    health_endpoint: str = "/health"
    start_command: str = ""
    working_dir: str = ""
    env: dict = field(default_factory=dict)
    stop_timeout_seconds: int = 30
    gpu_assignment: list[int] = field(default_factory=list)
    gpu_min_memory_gb: int = 0

    # 运行时状态
    runtime_state: str = "stopped"  # stopped | starting | running | unhealthy | stopping | exited
    pid: int | None = None

    # 只读属性
    @property
    def is_managed(self) -> bool:
        """是否为托管的服务（有启动命令）"""
        return bool(self.start_command)

    @classmethod
    def from_dict(cls, d: dict) -> "ServiceRecord":
        """从 YAML 字典创建 ServiceRecord"""
        return cls(
            id=d["id"],
            display_name=d["display_name"],
            model_type=d["model_type"],
            enabled=d.get("enabled", False),
            service_url=d.get("service_url", ""),
            health_endpoint=d.get("health_endpoint", "/health"),
            start_command=d.get("start", {}).get("command", ""),
            working_dir=d.get("start", {}).get("working_dir", ""),
            env=d.get("start", {}).get("env", {}),
            stop_timeout_seconds=d.get("start", {}).get("stop_timeout_seconds", 30),
            gpu_assignment=d.get("gpu", {}).get("assignment", []),
            gpu_min_memory_gb=d.get("gpu", {}).get("min_memory_gb", 0),
        )

    def to_dict(self) -> dict:
        """转换为 YAML 兼容的字典"""
        return {
            "id": self.id,
            "display_name": self.display_name,
            "model_type": self.model_type,
            "enabled": self.enabled,
            "service_url": self.service_url,
            "health_endpoint": self.health_endpoint,
            "start": {
                "command": self.start_command,
                "working_dir": self.working_dir,
                "env": dict(self.env),
                "stop_timeout_seconds": self.stop_timeout_seconds,
            },
            "gpu": {
                "assignment": list(self.gpu_assignment),
                "min_memory_gb": self.gpu_min_memory_gb,
            },
        }

    def clone(self) -> "ServiceRecord":
        """创建深拷贝"""
        return ServiceRecord(
            id=self.id,
            display_name=self.display_name,
            model_type=self.model_type,
            enabled=self.enabled,
            service_url=self.service_url,
            health_endpoint=self.health_endpoint,
            start_command=self.start_command,
            working_dir=self.working_dir,
            env=dict(self.env),
            stop_timeout_seconds=self.stop_timeout_seconds,
            gpu_assignment=list(self.gpu_assignment),
            gpu_min_memory_gb=self.gpu_min_memory_gb,
            runtime_state=self.runtime_state,
            pid=self.pid,
        )