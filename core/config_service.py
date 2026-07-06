# core/config_service.py — 配置服务，负责YAML文件的读写和校验

import os
import yaml
from typing import Any, Optional


class ConfigError(Exception):
    """配置加载或校验失败。"""
    def __init__(self, message: str, field: str | None = None):
        self.field = field
        super().__init__(message)


class ConfigService:
    """统一的 YAML 配置管理器。"""

    # 合法的模型类型
    VALID_MODEL_TYPES = {
        "stable-diffusion", "qwen3-asr", "whisperx", "fastwhisper",
        "waifu2x", "rembg", "llm-translator", "qwen3-tts",
    }

    def __init__(self, config_dir: str = "config/"):
        self._config_dir = os.path.abspath(config_dir)
        self._webui_config: dict = {}    # 解析后的 webui.yaml 内容
        self._services_config: dict = {} # 解析后的 services.yaml 内容
        self._ensure_defaults()

    # ── 内部路径 ──

    @property
    def _webui_path(self) -> str:
        return os.path.join(self._config_dir, "webui.yaml")

    @property
    def _services_path(self) -> str:
        return os.path.join(self._config_dir, "services.yaml")

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

    # ── 读取 ──

    def get_webui_config(self) -> dict:
        """返回完整的 webui.yaml 配置（深拷贝）"""
        return dict(self._webui_config)

    def get_services_list(self) -> list[dict]:
        """返回 services.yaml 中的服务列表（深拷贝）"""
        services = self._services_config.get("services", [])
        return [dict(svc) for svc in services]

    def get_server_setting(self, key: str, default=None) -> Any:
        """便捷访问 server 配置"""
        return self._webui_config.get("server", {}).get(key, default)

    def get_refresh_setting(self, key: str, default=None) -> Any:
        """便捷访问 refresh 配置"""
        return self._webui_config.get("refresh", {}).get(key, default)

    def get_logging_setting(self, key: str, default=None) -> Any:
        """便捷访问 logging 配置"""
        return self._webui_config.get("logging", {}).get(key, default)

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

    # ── 文件操作 ──

    def _load_file(self, path: str) -> dict:
        """加载 YAML 文件，确保总是返回字典"""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except (yaml.YAMLError, UnicodeDecodeError, OSError) as e:
            raise ConfigError(f"YAML 解析失败: {e}")

        return data if isinstance(data, dict) else {}

    def _safe_write(self, path: str, data: dict):
        """先写 .tmp 文件，校验后再 rename 覆盖原文件。"""
        tmp_path = path + ".tmp"
        try:
            # 写入临时文件
            os.makedirs(os.path.dirname(tmp_path), exist_ok=True)
            with open(tmp_path, "w", encoding="utf-8") as f:
                yaml.dump(data, f, default_flow_style=False, allow_unicode=True)

            # 重新加载验收证 YAML 合法性
            with open(tmp_path, "r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
                if not isinstance(loaded, dict):
                    raise ConfigError("写入的文件不是一个有效的字典")

            # 原子替换原文件
            if os.path.exists(path):
                os.replace(tmp_path, path)
            else:
                # 如果原文件不存在，直接重命名
                os.rename(tmp_path, path)

        except Exception as e:
            # 清理临时文件
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            raise ConfigError(f"写入配置失败: {e}")

    def _write_default_webui(self):
        """写入默认的 webui.yaml 配置"""
        defaults = {
            "server": {
                "host": "0.0.0.0",
                "port": 7860,
                "public_url": ""
            },
            "refresh": {
                "health_check_seconds": 10,
                "gpu_metrics_seconds": 5,
                "task_status_seconds": 15
            },
            "logging": {
                "level": "INFO",
                "max_mb_per_file": 10,
                "backup_count": 5,
                "directory": "data/logs/"
            }
        }
        self._safe_write(self._webui_path, defaults)
        self._webui_config = defaults

    def _write_default_services(self):
        """写入默认的 services.yaml 配置（空服务列表）"""
        defaults = {"services": []}
        self._safe_write(self._services_path, defaults)
        self._services_config = defaults

    # ── 校验规则 ──

    def _validate_webui_config(self, config: dict | None = None):
        """校验 webui.yaml 配置结构"""
        cfg = config or self._webui_config

        # 校验 server 配置
        server = cfg.get("server", {})
        if not isinstance(server.get("host"), str) or not server.get("host"):
            raise ConfigError("server.host 必须为非空字符串", "server.host")

        port = server.get("port", 7860)
        if not isinstance(port, int) or port < 1 or port > 65535:
            raise ConfigError("server.port 必须在 1-65535 之间", "server.port")

        # 校验 refresh 配置
        refresh = cfg.get("refresh", {})
        for key in ("health_check_seconds", "gpu_metrics_seconds", "task_status_seconds"):
            val = refresh.get(key, 10)
            if not isinstance(val, (int, float)) or val < 1:
                raise ConfigError(f"refresh.{key} 必须 >= 1", f"refresh.{key}")

        # 校验 logging 配置
        log = cfg.get("logging", {})
        if log.get("level") not in ("DEBUG", "INFO", "WARNING", "ERROR"):
            raise ConfigError("logging.level 必须为 DEBUG/INFO/WARNING/ERROR", "logging.level")

    def _validate_services_config(self, payload: dict | None = None):
        """校验 services.yaml 配置结构"""
        data = payload or self._services_config
        services = data.get("services", [])

        if not isinstance(services, list):
            raise ConfigError("services 必须为列表")

        ids = set()
        for i, svc in enumerate(services):
            if not isinstance(svc, dict):
                raise ConfigError(f"services[{i}] 必须为字典")

            prefix = f"services[{i}]"
            svc_id = svc.get("id", "")

            # 校验 id
            if not isinstance(svc_id, str) or not svc_id:
                raise ConfigError(f"{prefix}.id 必须为非空字符串")
            if not all(c.isalnum() or c == "-" for c in svc_id):
                raise ConfigError(f"{prefix}.id 只能包含小写字母、数字和连字符")
            if svc_id in ids:
                raise ConfigError(f"{prefix}.id '{svc_id}' 重复")
            ids.add(svc_id)

            # 校验 display_name
            if not isinstance(svc.get("display_name"), str) or not svc["display_name"]:
                raise ConfigError(f"{prefix}.display_name 必须为非空字符串")

            # 校验 model_type
            model_type = svc.get("model_type", "")
            if model_type not in self.VALID_MODEL_TYPES:
                valid_types = ", ".join(sorted(self.VALID_MODEL_TYPES))
                raise ConfigError(f"{prefix}.model_type 必须为 {valid_types}")

            # 校验 start 配置
            start = svc.get("start", {})
            if start.get("command") and not start.get("working_dir"):
                raise ConfigError(f"{prefix}.start.working_dir 在 command 非空时必须设置")

            timeout = start.get("stop_timeout_seconds", 30)
            if not isinstance(timeout, int) or timeout < 5 or timeout > 120:
                raise ConfigError(f"{prefix}.start.stop_timeout_seconds 必须在 5-120 之间")

            # 校验 gpu 配置
            gpu = svc.get("gpu", {})
            for idx in gpu.get("assignment", []):
                if not isinstance(idx, int) or idx < 0:
                    raise ConfigError(f"{prefix}.gpu.assignment 只能包含非负整数")

            min_mem = gpu.get("min_memory_gb", 0)
            if not isinstance(min_mem, int) or min_mem < 0:
                raise ConfigError(f"{prefix}.gpu.min_memory_gb 必须为非负整数")