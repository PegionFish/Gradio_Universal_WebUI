# 模块 2：配置系统

## 用途

管理 YAML 配置文件的读写、校验和持久化。WebUI 通过 `ConfigService` 操作配置，所有修改通过"写临时文件再原子重命名"的模式保存，防止写入不完整。

## 依赖

- **模块 1**：项目骨架（配置存储在 `config/` 目录）
- Python 包：`pyyaml>=6.0`

## ConfigService 类

### 文件位置

`core/config_service.py`

### 类定义

```python
import os
import yaml
from typing import Any

class ConfigService:
    """统一的 YAML 配置管理器。"""
    
    def __init__(self, config_dir: str = "config/"):
        self._config_dir = config_dir
        self._webui_config: dict = {}    # 解析后的 webui.yaml 内容
        self._services_config: dict = {} # 解析后的 services.yaml 内容
        self._ensure_defaults()
    
    # ── 初始化 ──
    
    def _ensure_defaults(self):
        """确保 config/ 目录和两个默认 YAML 文件存在。"""
        os.makedirs(self._config_dir, exist_ok=True)
        if not os.path.exists(self._webui_path):
            self._write_default_webui()
        if not os.path.exists(self._services_path):
            self._write_default_services()
    
    def load_all(self):
        """加载两个配置文件并校验。
        抛出 ConfigError 若加载失败。
        """
        self._webui_config = self._load_file(self._webui_path)
        self._services_config = self._load_file(self._services_path)
        self._validate_webui_config()
        self._validate_services_config()
    
    # ── 路径 ──
    
    @property
    def _webui_path(self) -> str:
        return os.path.join(self._config_dir, "webui.yaml")
    
    @property
    def _services_path(self) -> str:
        return os.path.join(self._config_dir, "services.yaml")
    
    # ── 读取 ──
    
    def get_webui_config(self) -> dict:
        return dict(self._webui_config)
    
    def get_services_list(self) -> list[dict]:
        return list(self._services_config.get("services", []))
    
    def get_server_setting(self, key: str, default=None):
        return self._webui_config.get("server", {}).get(key, default)
    
    def get_refresh_setting(self, key: str, default=None):
        return self._webui_config.get("refresh", {}).get(key, default)
    
    # ── 写入 ──
    
    def save_webui_config(self, config: dict):
        """校验并保存 webui.yaml。"""
        self._validate_webui_config(config)
        self._safe_write(self._webui_path, config)
        self._webui_config = config
    
    def save_services_config(self, services: list[dict]):
        """校验并保存 services.yaml。
        参数 services: 服务定义列表（不含顶层 wrapper）。
        """
        payload = {"services": services}
        self._validate_services_config(payload)
        self._safe_write(self._services_path, payload)
        self._services_config = payload
    
    # ── 内部 ──
    
    def _load_file(self, path: str) -> dict:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else {}
    
    def _safe_write(self, path: str, data: dict):
        """先写 .tmp 文件，校验后再 rename 覆盖原文件。"""
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True)
        # 重新加载验收证 YAML 合法性
        with open(tmp_path, "r", encoding="utf-8") as f:
            yaml.safe_load(f)
        os.replace(tmp_path, path)
    
    def _write_default_webui(self):
        defaults = {
            "server": {"host": "0.0.0.0", "port": 7860, "public_url": ""},
            "refresh": {"health_check_seconds": 10, "gpu_metrics_seconds": 5, "task_status_seconds": 15},
            "logging": {"level": "INFO", "max_mb_per_file": 10, "backup_count": 5, "directory": "data/logs/"},
        }
        self._safe_write(self._webui_path, defaults)
        self._webui_config = defaults
    
    def _write_default_services(self):
        defaults = {"services": []}
        self._safe_write(self._services_path, defaults)
        self._services_config = defaults
```

### ConfigError

```python
class ConfigError(Exception):
    """配置加载或校验失败。"""
    def __init__(self, message: str, field: str | None = None):
        self.field = field
        super().__init__(message)
```

## 校验规则

### webui.yaml 校验（`_validate_webui_config`）

```python
def _validate_webui_config(self, config: dict | None = None):
    cfg = config or self._webui_config
    
    server = cfg.get("server", {})
    if not isinstance(server.get("host"), str) or not server.get("host"):
        raise ConfigError("server.host 必须为非空字符串", "server.host")
    
    port = server.get("port", 7860)
    if not isinstance(port, int) or port < 1 or port > 65535:
        raise ConfigError("server.port 必须在 1-65535 之间", "server.port")
    
    refresh = cfg.get("refresh", {})
    for key in ("health_check_seconds", "gpu_metrics_seconds", "task_status_seconds"):
        val = refresh.get(key, 10)
        if not isinstance(val, (int, float)) or val < 1:
            raise ConfigError(f"refresh.{key} 必须 >= 1", f"refresh.{key}")
    
    log = cfg.get("logging", {})
    if log.get("level") not in ("DEBUG", "INFO", "WARNING", "ERROR", None):
        raise ConfigError("logging.level 必须为 DEBUG/INFO/WARNING/ERROR", "logging.level")
```

### services.yaml 校验（`_validate_services_config`）

```python
VALID_MODEL_TYPES = {"stable-diffusion", "qwen3-asr", "whisperx", "fastwhisper"}

def _validate_services_config(self, payload: dict | None = None):
    data = payload or self._services_config
    services = data.get("services", [])
    if not isinstance(services, list):
        raise ConfigError("services 必须为列表")
    
    ids = set()
    for i, svc in enumerate(services):
        prefix = f"services[{i}]"
        svc_id = svc.get("id", "")
        if not isinstance(svc_id, str) or not svc_id:
            raise ConfigError(f"{prefix}.id 必须为非空字符串")
        if not all(c.isalnum() or c == "-" for c in svc_id):
            raise ConfigError(f"{prefix}.id 只能包含小写字母、数字和连字符")
        if svc_id in ids:
            raise ConfigError(f"{prefix}.id '{svc_id}' 重复")
        ids.add(svc_id)
        
        if not isinstance(svc.get("display_name"), str) or not svc["display_name"]:
            raise ConfigError(f"{prefix}.display_name 必须为非空字符串")
        
        model_type = svc.get("model_type", "")
        if model_type not in VALID_MODEL_TYPES:
            raise ConfigError(f"{prefix}.model_type 必须为 {VALID_MODEL_TYPES}")
        
        if svc.get("start", {}).get("command"):
            if not svc.get("start", {}).get("working_dir"):
                raise ConfigError(f"{prefix}.start.working_dir 在 command 非空时必须设置")
        
        timeout = svc.get("start", {}).get("stop_timeout_seconds", 30)
        if not isinstance(timeout, int) or timeout < 5 or timeout > 120:
            raise ConfigError(f"{prefix}.start.stop_timeout_seconds 必须在 5-120 之间")
        
        gpu = svc.get("gpu", {})
        for idx in gpu.get("assignment", []):
            if not isinstance(idx, int) or idx < 0:
                raise ConfigError(f"{prefix}.gpu.assignment 只能包含非负整数")
        
        min_mem = gpu.get("min_memory_gb", 0)
        if not isinstance(min_mem, int) or min_mem < 0:
            raise ConfigError(f"{prefix}.gpu.min_memory_gb 必须为非负整数")
```

## ServiceRecord 类

虽然 ServiceRegistry 在模块 3 中完整定义，但 ConfigService 需要能够导出/导入 `ServiceRecord` 格式的数据：

```python
from dataclasses import dataclass, field

@dataclass
class ServiceRecord:
    id: str
    display_name: str
    model_type: str
    enabled: bool = False
    service_url: str = ""
    health_endpoint: str = "/health"
    start_command: str = ""
    working_dir: str = ""
    env: dict = field(default_factory=dict)
    stop_timeout_seconds: int = 30
    gpu_assignment: list[int] = field(default_factory=list)
    gpu_min_memory_gb: int = 0
    runtime_state: str = "stopped"   # stopped | starting | running | unhealthy | stopping | exited
    pid: int | None = None
    
    @classmethod
    def from_dict(cls, d: dict) -> "ServiceRecord":
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
```

## 集成点

### 在 main.py 中的使用

```python
# main.py 步骤 3: 加载配置
from core.config_service import ConfigService, ConfigError

config = ConfigService(config_dir=args.config or "config/")
try:
    config.load_all()
except ConfigError as e:
    print(f"配置错误: {e}")
    return 1
```

### 在 WebUI 配置页面中的使用

```python
# pages/config.py 中保存回调:
def on_save_yaml(yaml_text: str):
    try:
        parsed = yaml.safe_load(yaml_text)
        if not isinstance(parsed, dict):
            raise ConfigError("YAML 必须是一个字典")
        services_list = parsed.get("services", [])
        config.save_services_config(services_list)
        return "保存成功", ""
    except (yaml.YAMLError, ConfigError) as e:
        return "", f"保存失败: {e}"
```

## 验收标准

1. `ConfigService(config_dir="test_config/")` 在指定目录不存在时自动创建
2. `load_all()` 加载合法 YAML 返回解析后的字典
3. `load_all()` 遇到非法 YAML 抛出 `ConfigError`
4. `save_services_config()` 校验通过后写入文件，写入后原文件有效
5. `save_services_config()` 校验失败时不覆盖原文件
6. `.tmp` 文件在写入完成后被 rename 覆盖，不残留在磁盘上
7. 空服务列表 `{"services": []}` 通过校验
8. 服务 ID 重复被拒绝
9. `model_type` 不在枚举中被拒绝
10. 端口号码范围检查生效
